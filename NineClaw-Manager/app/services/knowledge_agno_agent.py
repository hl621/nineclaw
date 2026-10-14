"""AGNO-based Knowledge Q&A agent — mirrors Skill Studio agent architecture."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.models.openai.like import OpenAILike
from agno.tools import Toolkit

from app.services.knowledge_factory import KnowledgeBackend
from app.services.knowledge_chunk_service import list_file_chunks
from app.services.knowledge_llm_service import QaLlmConfig
from app.services.knowledge_qa_service import _collect_references, _validate_datasets
from app.services.knowledge_time_context import (
    current_time_context,
    exact_current_time_context,
)
from app.services.chunk_availability import parse_chunk_available

logger = logging.getLogger(__name__)

AGENTS_FILE_NAME = "AGENTS.md"
KNOWLEDGE_STUDIO_RESOURCE_DIR = (
    Path(__file__).resolve().parents[1] / "resources" / "knowledge_studio"
)
AGENTS_CONTEXT_MAX_CHARS = 24000
CONVERSATION_CONTEXT_MAX_CHARS_PER_MESSAGE = 3000
CONVERSATION_KEEP_RECENT = 8
DOCUMENT_SCAN_PAGE_SIZE = 100
DOCUMENT_SCAN_MAX_PAGES = 200
DOCUMENT_EXPORT_DIR = Path("knowledge_qa_exports")
CONTEXT_MIN_STRONG_REFS = 1
CONTEXT_MIN_COVERAGE = 0.45

KNOWLEDGE_AGNO_INSTRUCTIONS = [
    "你是 NineClaw 知识库问答智能体（Knowledge Q&A Agent）。",
    "只能基于知识库工具返回的文档切片回答；不得编造知识库中不存在的内容。",
    "回答前先调用 rag_retrieve；若无匹配切片，最多换关键词进行少量有目的重试，仍无结果则明确告知「知识库中未找到相关切片」。",
    "当召回片段明显缺少上下文、出现「如下/上述/本条款」等指代，调用 rag_expand_context 获取同文档上下文。",
    "当多个命中集中在同一文档、需要核对全文关键词或定位条款，调用 rag_grep_document；需要保留可审查文本时再调用 rag_export_document_text。",
    "复杂问题在最终回答前调用 rag_check_sufficient_context；若返回 needs_more_context，按建议补搜、扩展或筛查，不要带着证据缺口硬答。",
    "引用采用段落级合并标记：同一段落末尾集中写 [1] 或 [1][2]，不要每个句子都插角标。",
    "引用编号必须且只能来自最近一次 rag_retrieve 返回的 [1]…[N]；不要使用文档切片序号、上下文扩展 offset、历史对话中的编号，也不要在多次检索后累加编号。",
    "最终回答末尾可加「资料来源」小节，用文件名列出用到的来源；不要生成 Markdown 链接。",
    "涉及「当前、今天、最近、今年」等相对时间时，以系统注入的当前时间为准；不要把文章时间、上传时间、解析时间或切片时间当作当前时间。",
    "只有当用户问题需要分钟/秒级精确当前时间时，才调用 rag_get_current_time；一般时间判断使用按小时截断的上下文以利用缓存。",
    "使用中文回答，条理清晰；不要把完整切片正文复制到最终回答。",
    "多轮对话可参考历史，但话题变化时应重新检索。",
]


def _snip(text: str, limit: int) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "…（已截断）"


def _load_agents_context() -> str:
    agents_path = KNOWLEDGE_STUDIO_RESOURCE_DIR / AGENTS_FILE_NAME
    try:
        safe_parent = KNOWLEDGE_STUDIO_RESOURCE_DIR.resolve()
        resolved = agents_path.resolve()
        if resolved.parent != safe_parent or not resolved.is_file():
            return ""
        content = resolved.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        logger.warning("Failed to read knowledge studio AGENTS.md", exc_info=True)
        return ""
    if not content:
        return ""
    truncated = content[:AGENTS_CONTEXT_MAX_CHARS]
    suffix = "\n[AGENTS.md 内容已截断]" if len(content) > len(truncated) else ""
    return truncated + suffix


_CITATION_MARKER_RE = re.compile(r"[\[［【](\d+)[\]］】]")
QA_CITATION_INDEX_CAP = 50


def _strip_citation_markers(text: str) -> str:
    """Remove [n] markers from prior assistant answers to avoid carry-over numbering."""

    def repl(match: re.Match[str]) -> str:
        num = int(match.group(1))
        if 1 <= num <= QA_CITATION_INDEX_CAP:
            return ""
        return match.group(0)

    cleaned = _CITATION_MARKER_RE.sub(repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def sanitize_out_of_range_citations(text: str, max_index: int) -> str:
    """Remove hallucinated RAG citation markers outside [1]…[max_index].

    Out-of-range markers are deleted from the answer text (not kept as plain text).
    Markers with n > QA_CITATION_INDEX_CAP are left intact (e.g. statute-like numbers).
    """
    if not text:
        return text
    max_n = max(0, int(max_index))

    def repl(match: re.Match[str]) -> str:
        num = int(match.group(1))
        if max_n > 0 and 1 <= num <= max_n:
            return match.group(0)
        if 1 <= num <= QA_CITATION_INDEX_CAP:
            return ""
        return match.group(0)

    cleaned = _CITATION_MARKER_RE.sub(repl, text)
    return re.sub(r"[ \t]{2,}", " ", cleaned)


def _format_conversation_context(
    conversation_history: list[dict[str, str]] | None,
) -> str:
    if not conversation_history:
        return ""
    lines: list[str] = []
    for item in conversation_history[-CONVERSATION_KEEP_RECENT:]:
        role = str(item.get("role") or "").strip().lower()
        raw_content = str(item.get("content") or "")
        if role == "assistant":
            raw_content = _strip_citation_markers(raw_content)
        content = _snip(raw_content, CONVERSATION_CONTEXT_MAX_CHARS_PER_MESSAGE)
        if not content:
            continue
        label = "用户" if role == "user" else "助手"
        lines.append(f"{label}: {content}")
    if not lines:
        return ""
    return "对话历史：\n" + "\n\n".join(lines)


def _decompose_question(question: str) -> list[str]:
    clean = str(question or "").strip()
    if not clean:
        return []

    range_match = re.search(r"(\d{4})\s*[至\-~]\s*(\d{4})", clean)
    if range_match:
        start_year = int(range_match.group(1))
        end_year = int(range_match.group(2))
        if 0 <= end_year - start_year <= 8:
            base = re.sub(r"\d{4}\s*[至\-~]\s*\d{4}", "", clean)
            base = re.sub(r"[年,，、]", " ", base)
            base = re.sub(r"\s+", " ", base).strip()
            return [
                f"{year}年 {base}".strip() for year in range(start_year, end_year + 1)
            ]

    years = sorted(set(int(y) for y in re.findall(r"(\d{4})年", clean)))
    if len(years) >= 2 and max(years) - min(years) <= 8:
        base = re.sub(r"\d{4}年", "", clean)
        base = re.sub(r"[至\-~]\s*\d{4}", "", base)
        base = re.sub(r"[年,，、]", " ", base)
        base = re.sub(r"\s+", " ", base).strip()
        return [
            f"{year}年 {base}".strip() for year in range(min(years), max(years) + 1)
        ]

    for sep in ("以及", "及", "和", "与", "、", ",", "，"):
        parts = [part.strip() for part in clean.split(sep) if len(part.strip()) > 4]
        if 2 <= len(parts) <= 6:
            return parts
    return [clean]


def _coverage_terms(question: str) -> list[str]:
    text = str(question or "").strip().lower()
    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        term = term.strip().lower()
        if len(term) < 2 or term in seen:
            return
        seen.add(term)
        terms.append(term)

    for year in re.findall(r"\d{4}", text):
        add(year)
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text):
        add(token)
    for seg in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if len(seg) <= 6:
            add(seg)
        else:
            for size in (4, 3, 2):
                for idx in range(0, max(len(seg) - size + 1, 0), size):
                    add(seg[idx : idx + size])
    return terms[:24]


def _term_coverage(
    question: str, refs: list[dict[str, Any]]
) -> tuple[float, list[str]]:
    terms = _coverage_terms(question)
    if not terms:
        return 1.0, []
    evidence_text = "\n".join(str(ref.get("text") or "") for ref in refs).lower()
    missing = [term for term in terms if term not in evidence_text]
    coverage = 1.0 - (len(missing) / max(len(terms), 1))
    return round(coverage, 3), missing


def _strong_ref_count(refs: list[dict[str, Any]]) -> int:
    count = 0
    for ref in refs:
        score = ref.get("score")
        text = str(ref.get("text") or "").strip()
        if len(text) >= 80 and (not isinstance(score, (int, float)) or score >= 0.15):
            count += 1
    return count


def _ref_key(ref: dict[str, Any]) -> str:
    return str(ref.get("chunk_id") or ref.get("text") or "")[:160]


def _merge_references(
    groups: list[list[dict[str, Any]]], top_k: int
) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for refs in groups:
        for ref in refs:
            key = _ref_key(ref)
            if not key:
                continue
            prev = best.get(key)
            prev_score = prev.get("score") if prev else None
            score = ref.get("score")
            is_better = prev is None
            if isinstance(score, (int, float)):
                is_better = is_better or not isinstance(prev_score, (int, float))
                is_better = is_better or (
                    isinstance(prev_score, (int, float)) and score > prev_score
                )
            if is_better:
                best[key] = ref
    refs = list(best.values())
    refs.sort(
        key=lambda item: (
            item.get("score") if isinstance(item.get("score"), (int, float)) else -1
        ),
        reverse=True,
    )
    return refs[:top_k]


def _chunk_sort_key(chunk_id: str, fallback: int) -> tuple[str, int]:
    text = str(chunk_id or "")
    match = re.search(r"#(?:preview-|rag-\d+-)?(\d+)$", text)
    if match:
        return text.split("#", 1)[0], int(match.group(1))
    return text, fallback


def _collect_document_chunks(
    service: KnowledgeBackend,
    dataset_id: str,
    file_id: str,
    *,
    page_size: int = DOCUMENT_SCAN_PAGE_SIZE,
    max_pages: int = DOCUMENT_SCAN_MAX_PAGES,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        data = list_file_chunks(
            service,
            dataset_id,
            file_id,
            page=page,
            page_size=page_size,
        )
        page_chunks = data.get("chunks") or []
        if not page_chunks:
            break
        for idx, chunk in enumerate(page_chunks):
            text = str(chunk.get("content") or "").strip()
            chunk_id = str(chunk.get("id") or chunk.get("chunk_id") or "")
            if not text or not chunk_id or not parse_chunk_available(chunk):
                continue
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "content": text,
                    "document_offset": len(chunks),
                    "sort_key": _chunk_sort_key(chunk_id, len(chunks) + idx),
                }
            )
        total = data.get("total")
        if isinstance(total, int) and len(chunks) >= total:
            break
        if len(page_chunks) < page_size:
            break
    chunks.sort(key=lambda item: item["sort_key"])
    for idx, chunk in enumerate(chunks):
        chunk["document_offset"] = idx
    return chunks


def _file_name(service: KnowledgeBackend, dataset_id: str, file_id: str) -> str:
    try:
        record = service.get_knowledge(dataset_id)
        for file_row in record.get("files") or []:
            if str(file_row.get("id") or "") == str(file_id):
                return str(file_row.get("name") or file_id)
    except Exception:
        logger.debug(
            "failed to lookup file name %s/%s", dataset_id, file_id, exc_info=True
        )
    return str(file_id)


def _create_agno_model(
    llm: QaLlmConfig,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> OpenAILike:
    kwargs: dict[str, Any] = {
        "id": llm.model,
        "base_url": llm.base_url,
        "api_key": llm.api_key,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if enable_thinking is not None:
        kwargs["extra_body"] = {"enable_thinking": enable_thinking}
    return OpenAILike(**kwargs)


class KnowledgeRAGToolkit(Toolkit):
    """RAG retrieval tool bound to a knowledge backend and dataset scope."""

    def __init__(
        self,
        service: KnowledgeBackend,
        dataset_ids: list[str],
        top_k: int = 5,
        rerank_id: str | None = None,
        tenant_rerank_id: str | int | None = None,
        cross_languages: list[str] | None = None,
    ) -> None:
        self.service = service
        self.dataset_ids = list(dataset_ids)
        self.top_k = max(1, min(top_k, 50))
        self.rerank_id = rerank_id
        self.tenant_rerank_id = tenant_rerank_id
        self.cross_languages = cross_languages
        self.last_references: list[dict[str, Any]] = []
        self.last_question = ""
        super().__init__(
            name="knowledge_rag",
            tools=[
                self.rag_retrieve,
                self.rag_check_sufficient_context,
                self.rag_get_current_time,
                self.rag_expand_context,
                self.rag_grep_document,
                self.rag_export_document_text,
            ],
            instructions=(
                "Use rag_retrieve to search knowledge bases before answering. "
                "Use rag_check_sufficient_context before answering complex questions. "
                "Use rag_get_current_time only when exact current time is required. "
                "Use rag_expand_context for neighboring chunks, rag_grep_document "
                "for document-level keyword checks, and rag_export_document_text "
                "only when a saved audit text is useful."
            ),
            add_instructions=True,
            auto_register=False,
        )
        self.register(self.rag_retrieve)
        self.register(self.rag_check_sufficient_context)
        self.register(self.rag_get_current_time)
        self.register(self.rag_expand_context)
        self.register(self.rag_grep_document)
        self.register(self.rag_export_document_text)

    def rag_retrieve(self, question: str, top_k: int | None = None) -> str:
        """Retrieve ranked document chunks from configured knowledge bases.

        Args:
            question: User question or focused search query.
            top_k: Optional override for number of chunks (default from session).
        """
        clean_q = str(question or "").strip()
        if not clean_q:
            return "检索失败：question 不能为空。"

        err = _validate_datasets(self.service, self.dataset_ids)
        if err:
            return f"检索失败：{err}"

        limit = self.top_k
        if top_k is not None:
            try:
                limit = max(1, min(int(top_k), 50))
            except (TypeError, ValueError):
                limit = self.top_k

        queries = _decompose_question(clean_q)
        try:
            groups = [
                _collect_references(
                    self.service,
                    query,
                    self.dataset_ids,
                    limit,
                    rerank_id=self.rerank_id,
                    tenant_rerank_id=self.tenant_rerank_id,
                    cross_languages=self.cross_languages,
                )
                for query in queries
            ]
            refs = _merge_references(groups, limit)
        except Exception as exc:
            logger.exception("rag_retrieve failed")
            return f"检索失败：{exc}"

        self.last_question = clean_q
        self.last_references = refs
        if not refs:
            return (
                "未检索到与问题匹配的文档切片。"
                "请告知用户知识库中暂无相关内容，不要编造答案。"
            )

        ref_count = len(refs)
        blocks: list[str] = [
            (
                f"引用编号说明：本轮检索共 {ref_count} 条，回答中只能使用 [1] 至 [{ref_count}]；"
                "不要使用文档内切片序号、上下文扩展 offset 或历史对话编号。"
            )
        ]
        for i, ref in enumerate(refs, 1):
            fname = ref.get("file_name") or "未知文件"
            score = ref.get("score")
            score_txt = f"{score:.4f}" if isinstance(score, (int, float)) else "—"
            text = _snip(str(ref.get("text") or ""), 1800)
            dataset_id = ref.get("dataset_id") or ""
            file_id = ref.get("file_id") or ""
            chunk_id = ref.get("chunk_id") or ""
            blocks.append(
                f"[{i}] 来源：{fname}（score={score_txt}）\n"
                f"dataset_id={dataset_id}; file_id={file_id}; chunk_id={chunk_id}\n"
                f"{text}"
            )
        searched = ""
        if queries and queries != [clean_q]:
            searched = "已拆分并检索查询：" + "；".join(queries) + "\n\n"
        coverage, missing = _term_coverage(clean_q, refs)
        review = (
            "\n\ncontext_review:\n"
            f"- coverage: {coverage}\n"
            f"- strong_refs: {_strong_ref_count(refs)}\n"
            f"- missing_terms: {', '.join(missing[:8]) if missing else '[]'}\n"
            "- next_action: 复杂问题请调用 rag_check_sufficient_context；若缺上下文再扩展或补搜。"
        )
        return searched + "检索到以下文档切片：\n\n" + "\n\n".join(blocks) + review

    def rag_check_sufficient_context(
        self,
        question: str | None = None,
        answer_plan: str | None = None,
    ) -> str:
        """Check whether current retrieved evidence is enough to answer.

        Args:
            question: User question. Defaults to the last rag_retrieve question.
            answer_plan: Optional brief answer outline to validate against evidence.
        """
        q = str(question or self.last_question or "").strip()
        if not q:
            return (
                "status: needs_retrieval\n"
                "reason: 尚未提供问题；请先调用 rag_retrieve。"
            )
        refs = self.last_references
        if not refs:
            return (
                "status: no_evidence\n"
                f"question: {q}\n"
                "reason: 当前没有可用召回片段。\n"
                "recommended_next_actions:\n"
                "  - 使用更短、更具体的关键词重新调用 rag_retrieve\n"
                "  - 若仍无结果，告知用户知识库未找到相关切片"
            )

        coverage, missing = _term_coverage(q + " " + str(answer_plan or ""), refs)
        strong_refs = _strong_ref_count(refs)
        unique_docs = {
            (str(ref.get("dataset_id") or ""), str(ref.get("file_id") or ""))
            for ref in refs
            if ref.get("file_id")
        }
        needs_context = any(
            cue in str(ref.get("text") or "")
            for ref in refs[:3]
            for cue in (
                "如下",
                "上述",
                "以下",
                "本条",
                "本政策",
                "见下",
                "表",
                "如下：",
            )
        )

        if strong_refs >= CONTEXT_MIN_STRONG_REFS and coverage >= CONTEXT_MIN_COVERAGE:
            status = "sufficient"
            reason = "已有可引用片段覆盖主要问题词。"
            if needs_context:
                status = "needs_more_context"
                reason = "命中片段可能依赖邻近上下文。"
        else:
            status = "needs_more_context"
            reason = "当前片段对问题关键词或计划回答覆盖不足。"

        lines = [
            f"status: {status}",
            f"question: {q}",
            f"coverage: {coverage}",
            f"strong_refs: {strong_refs}",
            f"unique_documents: {len(unique_docs)}",
            "missing_terms:",
        ]
        if missing:
            lines.extend(f"  - {term}" for term in missing[:12])
        else:
            lines.append("  []")
        lines.extend(["reason: " + reason, "recommended_next_actions:"])
        if status == "sufficient":
            lines.append("  - 可以基于当前证据回答；每个关键事实保留引用标记")
            if len(unique_docs) == 1 and len(refs) >= 3:
                lines.append(
                    "  - 如答案依赖精确条款/金额/日期，可对该文档调用 rag_grep_document 复核"
                )
        else:
            if missing:
                lines.append(
                    "  - 用 missing_terms 中的关键实体/年份组合重新调用 rag_retrieve"
                )
            if needs_context:
                lines.append("  - 对相关 chunk 调用 rag_expand_context 获取上下文窗口")
            lines.append("  - 若补搜后仍无强证据，明确说明知识库证据不足")
        return "\n".join(lines)

    def rag_get_current_time(self, include_seconds: bool = False) -> str:
        """Get exact current system time on demand.

        Args:
            include_seconds: Include seconds only when the user explicitly needs
                second-level precision.
        """
        return (
            "当前系统时间（按需精确获取，不用于默认 prompt cache）："
            f"{exact_current_time_context(include_seconds=bool(include_seconds))}"
        )

    def rag_expand_context(
        self,
        dataset_id: str,
        file_id: str,
        chunk_id: str,
        before: int = 2,
        after: int = 2,
    ) -> str:
        """Fetch neighboring chunks around a retrieved chunk in the same document.

        Args:
            dataset_id: Knowledge base ID returned by rag_retrieve.
            file_id: Document/file ID returned by rag_retrieve.
            chunk_id: Focus chunk ID returned by rag_retrieve.
            before: Number of preceding chunks to include.
            after: Number of following chunks to include.
        """
        dataset_id = str(dataset_id or "").strip()
        file_id = str(file_id or "").strip()
        chunk_id = str(chunk_id or "").strip()
        if not dataset_id or not file_id or not chunk_id:
            return "上下文扩展失败：dataset_id、file_id、chunk_id 不能为空。"
        err = _validate_datasets(self.service, [dataset_id])
        if err:
            return f"上下文扩展失败：{err}"

        try:
            chunks = _collect_document_chunks(self.service, dataset_id, file_id)
        except Exception as exc:
            logger.exception("rag_expand_context failed")
            return f"上下文扩展失败：{exc}"

        focus_index = next(
            (idx for idx, chunk in enumerate(chunks) if chunk["chunk_id"] == chunk_id),
            None,
        )
        if focus_index is None:
            return "上下文扩展失败：未在该文档切片列表中找到目标 chunk_id。"

        before = max(0, min(int(before), 10))
        after = max(0, min(int(after), 10))
        start = max(0, focus_index - before)
        end = min(len(chunks), focus_index + after + 1)
        fname = _file_name(self.service, dataset_id, file_id)
        blocks: list[str] = [
            f"已获取同文档上下文：{fname}",
            f"dataset_id={dataset_id}; file_id={file_id}; focus_chunk_id={chunk_id}; focus_offset={focus_index}",
        ]
        for idx in range(start, end):
            chunk = chunks[idx]
            if idx < focus_index:
                pos = "before"
            elif idx == focus_index:
                pos = "focus"
            else:
                pos = "after"
            blocks.append(
                f"[context:{pos}:{idx}] chunk_id={chunk['chunk_id']}\n"
                f"{_snip(chunk['content'], 1800)}"
            )
        return "\n\n".join(blocks)

    def rag_grep_document(
        self,
        dataset_id: str,
        file_id: str,
        pattern: str,
        case_sensitive: bool = False,
        max_matches: int = 20,
    ) -> str:
        """Search a document's parsed chunks with a regex or plain keyword.

        Args:
            dataset_id: Knowledge base ID.
            file_id: Document/file ID.
            pattern: Regex or plain keyword to search.
            case_sensitive: Whether matching is case-sensitive.
            max_matches: Maximum matching lines/chunks to return.
        """
        dataset_id = str(dataset_id or "").strip()
        file_id = str(file_id or "").strip()
        pattern = str(pattern or "").strip()
        if not dataset_id or not file_id or not pattern:
            return "全文筛查失败：dataset_id、file_id、pattern 不能为空。"
        err = _validate_datasets(self.service, [dataset_id])
        if err:
            return f"全文筛查失败：{err}"

        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error:
            regex = re.compile(
                re.escape(pattern), 0 if case_sensitive else re.IGNORECASE
            )

        try:
            chunks = _collect_document_chunks(self.service, dataset_id, file_id)
        except Exception as exc:
            logger.exception("rag_grep_document failed")
            return f"全文筛查失败：{exc}"

        max_matches = max(1, min(int(max_matches), 80))
        matches: list[str] = []
        for chunk in chunks:
            lines = str(chunk["content"]).splitlines() or [str(chunk["content"])]
            for line_no, line in enumerate(lines, 1):
                if not regex.search(line):
                    continue
                matches.append(
                    f"- chunk_id={chunk['chunk_id']}; line={line_no}; offset={chunk['document_offset']}\n"
                    f"  {_snip(line, 500)}"
                )
                if len(matches) >= max_matches:
                    break
            if len(matches) >= max_matches:
                break

        fname = _file_name(self.service, dataset_id, file_id)
        if not matches:
            return f"文档全文筛查无匹配：{fname}；pattern={pattern}"
        return (
            f"文档全文筛查结果：{fname}；pattern={pattern}；matches={len(matches)}\n\n"
            + "\n".join(matches)
        )

    def rag_export_document_text(
        self,
        dataset_id: str,
        file_id: str,
        filename: str | None = None,
    ) -> str:
        """Export a document's parsed chunks to a UTF-8 text file for audit.

        Args:
            dataset_id: Knowledge base ID.
            file_id: Document/file ID.
            filename: Optional output filename; .txt is appended when omitted.
        """
        dataset_id = str(dataset_id or "").strip()
        file_id = str(file_id or "").strip()
        if not dataset_id or not file_id:
            return "导出失败：dataset_id、file_id 不能为空。"
        err = _validate_datasets(self.service, [dataset_id])
        if err:
            return f"导出失败：{err}"

        try:
            chunks = _collect_document_chunks(self.service, dataset_id, file_id)
            fname = _file_name(self.service, dataset_id, file_id)
            safe_name = re.sub(
                r'[<>:"/\\|?*\x00-\x1f]', "_", filename or f"{fname}.txt"
            )
            safe_name = re.sub(r"\s+", " ", safe_name).strip(" .") or f"{file_id}.txt"
            if not safe_name.lower().endswith(".txt"):
                safe_name += ".txt"
            DOCUMENT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            path = DOCUMENT_EXPORT_DIR / safe_name
            lines = [
                f"dataset_id: {dataset_id}",
                f"file_id: {file_id}",
                f"file_name: {fname}",
                "",
            ]
            for idx, chunk in enumerate(chunks, 1):
                lines.append(f"--- chunk {idx} ---")
                lines.append(f"chunk_id: {chunk['chunk_id']}")
                lines.append("")
                lines.append(str(chunk["content"]))
                lines.append("")
            path.write_text("\n".join(lines), encoding="utf-8")
        except Exception as exc:
            logger.exception("rag_export_document_text failed")
            return f"导出失败：{exc}"

        return (
            f"已导出解析文本：{path.resolve()}\n"
            f"chunks={len(chunks)}；可用于人工复核或外部 grep。"
        )


def create_knowledge_qa_agent(
    llm: QaLlmConfig,
    toolkit: KnowledgeRAGToolkit,
    *,
    dataset_ids: list[str],
    conversation_context: str = "",
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> Agent:
    agents_context = _load_agents_context()
    additional_parts: list[str] = [
        f"当前检索范围知识库 ID：{', '.join(dataset_ids)}",
        (
            "当前系统时间（按小时截断，用于解释相对时间，不代表文档时间）："
            f"{current_time_context()}"
        ),
    ]
    if conversation_context:
        additional_parts.append(conversation_context)
    if agents_context:
        additional_parts.append(
            "<knowledge-qa-environment-instructions>\n"
            + agents_context
            + "\n</knowledge-qa-environment-instructions>"
        )

    return Agent(
        model=_create_agno_model(llm, temperature, enable_thinking),
        tools=[toolkit],
        instructions=KNOWLEDGE_AGNO_INSTRUCTIONS,
        additional_context="\n\n".join(additional_parts),
        markdown=True,
        stream=True,
        stream_events=True,
        tool_call_limit=8,
        telemetry=False,
    )
