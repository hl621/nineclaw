"""SSE streaming knowledge Q&A — filesystem recall + LLM answer."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from app.schemas.retrieval import RetrievalRequest
from app.services.chunk_availability import parse_chunk_available
from app.services.knowledge_llm_service import QaLlmConfig, QaLlmError, stream_llm_answer
from app.services.knowledge_retrieval_service import retrieve_chunks
from app.services.knowledge_factory import KnowledgeBackend
from app.services.knowledge_service import (
    KnowledgeError,
    _chunk_relevance_score,
    _compute_term_idf,
    _query_clean_phrase,
    _query_terms,
)

logger = logging.getLogger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_data(payload: Any) -> str:
    if payload == "[DONE]":
        return "data: [DONE]\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _collect_qa_references_from_file_chunks(
    service: KnowledgeBackend,
    question: str,
    dataset_ids: list[str],
    top_k: int,
) -> list[dict[str, Any]]:
    """问答专用：向量检索无结果时，遍历各文档已入库切片做关键词匹配（非预览原文）。"""
    from app.services import knowledge_chunk_service

    terms = _query_terms(question)
    phrase = _query_clean_phrase(question)
    if not terms:
        return []

    pending: list[tuple[str, str, str, str, str]] = []
    all_texts: list[str] = []

    for kb_id in dataset_ids:
        try:
            service.ensure_exists(kb_id)
            record = service.get_knowledge(kb_id)
        except KnowledgeError:
            continue
        for file_row in record.get("files") or []:
            if file_row.get("parsed") is False:
                continue
            file_id = str(file_row.get("id") or "")
            file_name = str(file_row.get("name") or file_id)
            if not file_id:
                continue
            try:
                page = 1
                while page <= 10:
                    data = knowledge_chunk_service.list_file_chunks(
                        service,
                        kb_id,
                        file_id,
                        page=page,
                        page_size=100,
                    )
                    chunks = data.get("chunks") or []
                    if not chunks:
                        break
                    for ck in chunks:
                        if not parse_chunk_available(ck):
                            continue
                        text = str(ck.get("content") or "").strip()
                        chunk_id = str(ck.get("id") or "")
                        if not text or not chunk_id:
                            continue
                        pending.append((kb_id, file_id, file_name, chunk_id, text))
                        all_texts.append(text)
                    if len(chunks) < 100:
                        break
                    page += 1
            except Exception:
                logger.debug(
                    "qa chunk fallback skip file %s/%s", kb_id, file_id, exc_info=True
                )

    if not pending:
        return []

    idf = _compute_term_idf(all_texts, terms)
    scored: list[tuple[float, dict[str, Any]]] = []
    for kb_id, file_id, file_name, chunk_id, text in pending:
        sim, term_sim, _ = _chunk_relevance_score(
            text, terms, phrase, idf, 0.0, 0.3
        )
        if term_sim <= 0:
            continue
        scored.append(
            (
                sim,
                {
                    "dataset_id": kb_id,
                    "file_id": file_id,
                    "file_name": file_name,
                    "chunk_id": chunk_id,
                    "text": text[:2000],
                    "score": sim,
                    "available": True,
                },
            )
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored[:top_k]]


def _collect_references(
    service: KnowledgeBackend,
    question: str,
    dataset_ids: list[str],
    top_k: int,
    rerank_id: str | None = None,
    tenant_rerank_id: str | int | None = None,
    *,
    allow_file_chunk_fallback: bool | None = None,
    cross_languages: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Retrieve top chunks via RAGFlow-compatible retrieval."""
    # RAGFlow default candidate pool is 1024 (slow). Bound it near page_size.
    candidate_top_k = min(256, max(32, int(top_k) * 8))
    # Multi-KB full-corpus IDF scan is catastrophic; only keep for single KB miss.
    if allow_file_chunk_fallback is None:
        allow_file_chunk_fallback = len(dataset_ids) <= 1

    def _run_retrieval(
        *,
        similarity_threshold: float,
        keyword: bool,
    ) -> list[dict[str, Any]]:
        body = RetrievalRequest(
            question=question,
            dataset_ids=dataset_ids,
            page=1,
            page_size=top_k,
            similarity_threshold=similarity_threshold,
            vector_similarity_weight=0.3,
            top_k=candidate_top_k,
            rerank_id=rerank_id,
            tenant_rerank_id=tenant_rerank_id,
            keyword=keyword,
            highlight=False,
            cross_languages=cross_languages,
        )
        raw = retrieve_chunks(service, body)
        references: list[dict[str, Any]] = []
        for chunk in raw.get("chunks", []):
            if not parse_chunk_available(chunk):
                continue
            references.append(
                {
                    "dataset_id": chunk.get("kb_id", ""),
                    "file_id": chunk.get("document_id") or "",
                    "file_name": chunk.get("document_keyword"),
                    "chunk_id": chunk.get("id"),
                    "text": chunk.get("content"),
                    "score": chunk.get("similarity"),
                    "available": parse_chunk_available(chunk),
                }
            )
        return references[:top_k]

    # 向量检索 → 放宽阈值；单库仍无结果再退回遍历文件切片
    refs = _run_retrieval(similarity_threshold=0.15, keyword=True)
    if not refs:
        refs = _run_retrieval(similarity_threshold=0.0, keyword=True)
    if not refs and allow_file_chunk_fallback:
        refs = _collect_qa_references_from_file_chunks(
            service, question, dataset_ids, top_k
        )
    return refs


def _validate_datasets(
    service: KnowledgeBackend,
    dataset_ids: list[str],
) -> str | None:
    for kb_id in dataset_ids:
        try:
            service.ensure_exists(kb_id)
        except KnowledgeError as exc:
            return str(exc.detail) if hasattr(exc, "detail") else str(exc)
    return None


async def knowledge_qa_stream(
    service: KnowledgeBackend,
    question: str,
    dataset_ids: list[str],
    top_k: int = 5,
    rerank_id: str | None = None,
    tenant_rerank_id: str | int | None = None,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
    llm: QaLlmConfig | None = None,
) -> AsyncGenerator[str, None]:
    """Yield SSE: references → LLM content chunks → [DONE]."""
    if not dataset_ids:
        yield _sse_data({"type": "error", "message": "dataset_ids 不能为空"})
        yield _sse_data("[DONE]")
        return

    try:
        err = await asyncio.to_thread(_validate_datasets, service, dataset_ids)
        if err:
            yield _sse_data({"type": "error", "message": err})
            yield _sse_data("[DONE]")
            return

        references = await asyncio.to_thread(
            _collect_references,
            service,
            question,
            dataset_ids,
            top_k,
            rerank_id,
            tenant_rerank_id,
        )
        yield _sse_data({"type": "references", "references": references})

        if llm is None:
            yield _sse_data(
                {
                    "type": "error",
                    "message": (
                        "未配置可用的大模型：请在「模型管理」中添加 Provider 并填写 API Key"
                    ),
                }
            )
            yield _sse_data("[DONE]")
            return

        got_content = False
        async for delta in stream_llm_answer(
            llm,
            question,
            references,
            temperature=temperature,
            enable_thinking=enable_thinking,
        ):
            got_content = True
            yield _sse_data({"type": "content", "content": delta})

        if not got_content:
            yield _sse_data({"type": "content", "content": "大模型未返回内容，请检查模型配置。"})

    except QaLlmError as exc:
        logger.warning("knowledge QA LLM error: %s", exc)
        yield _sse_data({"type": "error", "message": str(exc)})
    except Exception as exc:
        logger.exception("knowledge QA stream failed")
        yield _sse_data({"type": "error", "message": f"问答处理失败：{exc}"})

    yield _sse_data("[DONE]")
