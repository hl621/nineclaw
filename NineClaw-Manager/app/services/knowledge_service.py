"""File-based knowledge base (RAG) registry service.

The filesystem is the only source of truth — same design as
:class:`app.services.skill_service.SkillService`.
"""

from __future__ import annotations

import json
import logging
import math
import mimetypes
import re
import shutil
import uuid
from collections import Counter
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.schemas.knowledge import (
    CreateKnowledgeRequest,
    KnowledgeStatus,
    RecallChunk,
    UpdateKnowledgeRequest,
)

logger = logging.getLogger(__name__)

SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$") 
PREVIEW_EXTS = {".txt", ".md", ".markdown", ".json", ".csv", ".log"}
PREVIEW_MAX = 4000
DOCX_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DOCX_TEXT_TAG = f"{DOCX_NS}t"
DOCX_PARA_TAG = f"{DOCX_NS}p"
DOCX_BR_TAG = f"{DOCX_NS}br"
DOCX_TAB_TAG = f"{DOCX_NS}tab"
_QUERY_STOPWORDS = (
    "如何",
    "怎么",
    "怎样",
    "什么",
    "为什么",
    "哪些",
    "哪个",
    "是否",
    "能否",
    "可以",
    "请问",
    "吗",
    "呢",
    "啊",
)


def _query_terms(query: str) -> list[str]:
    """Extract Chinese/English keywords (longest-first) for retrieval."""
    raw = query.strip().lower()
    for w in _QUERY_STOPWORDS:
        raw = raw.replace(w, "")
    raw = re.sub(r"[^\w\u4e00-\u9fff]+", "", raw)

    terms: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        if len(term) >= 2 and term not in seen:
            seen.add(term)
            terms.append(term)

    if len(raw) >= 2:
        add(raw)

    for seg in re.findall(r"[\u4e00-\u9fff]+", raw):
        if len(seg) >= 3:
            add(seg[:3])
            if len(seg) >= 4:
                add(seg[:4])
                add(seg[-4:])
            add(seg[-3:])
        for i in range(len(seg) - 1):
            add(seg[i : i + 2])

    terms.sort(key=len, reverse=True)
    return terms


def _query_clean_phrase(query: str) -> str:
    raw = query.strip().lower()
    for w in _QUERY_STOPWORDS:
        raw = raw.replace(w, "")
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", raw)


def _chunk_relevance_score(
    text: str,
    terms: list[str],
    phrase: str,
    idf: dict[str, float],
    similarity_threshold: float,
    vector_weight: float,
) -> tuple[float, float, float]:
    """Return (similarity, term_similarity, vector_similarity); zeros if irrelevant."""
    if not terms:
        return 0.0, 0.0, 0.0

    text_l = text.lower()

    if len(phrase) >= 3 and phrase in text_l:
        return 1.0, 1.0, 1.0

    hit_terms = [t for t in terms if t in text_l]
    if not hit_terms:
        return 0.0, 0.0, 0.0

    num = sum(idf.get(t, 1.0) for t in hit_terms)
    den = sum(idf.get(t, 1.0) for t in terms) or 1.0
    term_sim = round(min(1.0, num / den), 4)

    vec_sim = round(min(1.0, term_sim * (0.45 + vector_weight * 0.55)), 4)
    combined = round(
        min(1.0, term_sim * (1.0 - vector_weight * 0.35) + vec_sim * vector_weight * 0.65),
        4,
    )
    if combined < similarity_threshold:
        return 0.0, 0.0, 0.0
    return combined, term_sim, vec_sim


def _compute_term_idf(chunk_texts: list[str], terms: list[str]) -> dict[str, float]:
    total = max(len(chunk_texts), 1)
    df: dict[str, int] = {t: 0 for t in terms}
    for text in chunk_texts:
        tl = text.lower()
        for term in terms:
            if term in tl:
                df[term] += 1
    return {t: math.log(1.0 + total / max(1, df[t])) for t in terms}


def _score_chunk_text(
    text: str,
    terms: list[str],
    similarity: float,
    vector_weight: float,
    idf: dict[str, float] | None = None,
    phrase: str = "",
) -> float:
    if idf is None:
        idf = {t: 1.0 for t in terms}
    combined, _, _ = _chunk_relevance_score(
        text, terms, phrase, idf, similarity, vector_weight
    )
    return combined


def _split_preview_chunks(preview: str) -> list[str]:
    blocks = [p.strip() for p in str(preview).split("\n\n") if p.strip()]
    if len(blocks) <= 1 and len(preview) > 300:
        lines = [ln.strip() for ln in str(preview).split("\n") if ln.strip()]
        if len(lines) > 1:
            return lines
    return blocks


class KnowledgeError(HTTPException):
    """Raised for predictable client errors."""


class KnowledgeService:
    META_FILE = "meta.json"
    DOCS_DIR = "documents"

    def __init__(self, storage_root: Path | str, max_upload_size: int) -> None:
        self.storage_root = Path(storage_root).expanduser().resolve()
        self.max_upload_size = max_upload_size
        # path -> (mtime, parsed, preview) — 同一次请求内避免重复解析 docx
        self._preview_cache: dict[str, tuple[float, bool, str | None]] = {}

    def ensure_storage(self) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _kb_dir(self, kb_id: str) -> Path:
        if not SLUG_RE.match(kb_id):
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的知识库 ID",
            )
        return self.storage_root / kb_id

    def _docs_dir(self, kb_id: str) -> Path:
        return self._kb_dir(kb_id) / self.DOCS_DIR

    def _meta_path(self, kb_id: str) -> Path:
        return self._kb_dir(kb_id) / self.META_FILE

    def _read_meta(self, kb_id: str) -> dict[str, Any]:
        path = self._meta_path(kb_id)
        if not path.is_file():
            raise KnowledgeError(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="知识库不存在",
            )
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise KnowledgeError(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"meta.json 解析失败：{exc}",
            ) from exc

    def _write_meta(self, kb_id: str, meta: dict[str, Any]) -> None:
        self._meta_path(kb_id).write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _slugify(name: str) -> str:
        s = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-").lower()
        if not s or not SLUG_RE.match(s):
            s = f"kb-{uuid.uuid4().hex[:8]}"
        return s[:128]

    @staticmethod
    def _stored_display_name(stored_name: str) -> str:
        if "_" in stored_name:
            return stored_name.split("_", 1)[-1]
        return stored_name

    @staticmethod
    def _disambiguate_display_name(filename: str, index: int) -> str:
        path = Path(filename)
        return f"{path.stem} ({index}){path.suffix}"

    def _list_doc_files(self, kb_id: str) -> list[Path]:
        docs = self._docs_dir(kb_id)
        if not docs.is_dir():
            return []
        files = [
            p for p in docs.iterdir() if p.is_file() and not p.name.startswith(".")
        ]
        # 先上传的在前（按创建/修改时间升序）
        files.sort(key=lambda p: p.stat().st_mtime)
        return files

    def _build_file_records(self, kb_id: str) -> list[dict[str, Any]]:
        paths = self._list_doc_files(kb_id)
        base_names = [self._stored_display_name(p.name) for p in paths]
        counts = Counter(base_names)
        seen: dict[str, int] = {}
        records: list[dict[str, Any]] = []
        for path, base in zip(paths, base_names, strict=True):
            display = base
            if counts[base] > 1:
                seen[base] = seen.get(base, 0) + 1
                if seen[base] > 1:
                    display = self._disambiguate_display_name(
                        base, seen[base] - 1
                    )
            records.append(self._file_record(path, display_name=display))
        return records

    def _file_preview(self, path: Path) -> tuple[bool, str | None]:
        ext = path.suffix.lower()
        try:
            if ext in PREVIEW_EXTS:
                text = self._normalize_extracted_text(
                    path.read_text(encoding="utf-8", errors="replace")
                )
                return True, text[:PREVIEW_MAX]
            if ext == ".docx":
                text = self._extract_docx_text(path)
                return True, text[:PREVIEW_MAX]
        except (OSError, KnowledgeError):
            return False, None
        return False, None

    def _file_preview_cached(self, path: Path) -> tuple[bool, str | None]:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False, None
        key = str(path)
        cached = self._preview_cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1], cached[2]
        parsed, preview = self._file_preview(path)
        self._preview_cache[key] = (mtime, parsed, preview)
        return parsed, preview

    def _iter_file_previews(self, kb_id: str) -> list[tuple[str, str]]:
        previews: list[tuple[str, str]] = []
        for path in self._list_doc_files(kb_id):
            _, preview = self._file_preview_cached(path)
            if preview:
                previews.append((self._stored_display_name(path.name), preview))
        return previews

    def ensure_exists(self, kb_id: str) -> None:
        self._read_meta(kb_id)

    def _file_record(
        self, path: Path, display_name: str | None = None
    ) -> dict[str, Any]:
        parsed, preview = self._file_preview_cached(path)
        stat = path.stat()
        display = display_name or self._stored_display_name(path.name)
        return {
            "id": path.name,
            "name": display,
            "size_bytes": stat.st_size,
            "parsed": parsed,
            "preview": preview,
            "uploaded_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        }

    def _compute_status(self, meta: dict[str, Any], doc_count: int) -> KnowledgeStatus:
        raw = meta.get("status", "pending")
        if raw in ("pending", "building", "success", "part_success", "fail"):
            return raw  # type: ignore[return-value]
        # 兼容旧值
        if raw in ("ready",):
            return "success"
        if raw in ("failed",):
            return "fail"
        if raw in ("indexing",):
            return "building"
        return "success" if doc_count > 0 else "pending"

    def _to_record(self, kb_id: str, meta: dict[str, Any]) -> dict[str, Any]:
        files = self._list_doc_files(kb_id)
        doc_count = meta.get("doc_count")
        if doc_count is None:
            doc_count = len(files)
        mtime = self._kb_dir(kb_id).stat().st_mtime
        status_val = meta.get("status")
        if not status_val:
            status_val = self._compute_status(meta, doc_count)
        return {
            "id": kb_id,
            "dataset_id": kb_id,
            "name": meta.get("name", kb_id),
            "description": meta.get("description", ""),
            "group": meta.get("group", ""),
            "owner": meta.get("owner", ""),
            "serial": meta.get("serial"),
            "status": status_val,
            "doc_count": doc_count,
            "updated_at": datetime.fromtimestamp(mtime, tz=timezone.utc),
            "avatar": meta.get("avatar"),
            "embedding_model": meta.get("embedding_model"),
            "chunk_method": meta.get("chunk_method"),
            "permission": meta.get("permission"),
            "parser_config": meta.get("parser_config"),
        }

    def list_knowledge(self) -> list[dict[str, Any]]:
        self.ensure_storage()
        items: list[dict[str, Any]] = []
        for entry in sorted(self.storage_root.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not SLUG_RE.match(entry.name):
                continue
            meta_path = entry / self.META_FILE
            if not meta_path.is_file():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping corrupt knowledge base %s: %s", entry.name, exc)
                continue
            items.append(self._to_record(entry.name, meta))
        items.sort(key=lambda k: k["updated_at"], reverse=True)
        return items

    def get_knowledge(self, kb_id: str) -> dict[str, Any]:
        meta = self._read_meta(kb_id)
        record = self._to_record(kb_id, meta)
        record["files"] = self._build_file_records(kb_id)
        return record

    def list_files(
        self,
        kb_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
        keywords: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_exists(kb_id)
        files = self._build_file_records(kb_id)
        query = (keywords or "").strip().lower()
        if query:
            files = [f for f in files if query in str(f.get("name", "")).lower()]
        total = len(files)
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        start = (page - 1) * page_size
        return {
            "items": files[start:start + page_size],
            "total": total,
        }

    def create_knowledge(self, body: CreateKnowledgeRequest) -> dict[str, Any]:
        self.ensure_storage()
        kb_id = body.id or self._slugify(body.name)
        target = self._kb_dir(kb_id)
        if target.exists():
            raise KnowledgeError(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"知识库 {kb_id} 已存在",
            )
        target.mkdir(parents=True)
        (target / self.DOCS_DIR).mkdir()
        meta = self._meta_from_create(body)
        self._write_meta(kb_id, meta)
        return self._to_record(kb_id, meta)

    @staticmethod
    def _meta_from_create(body: CreateKnowledgeRequest) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "name": body.name,
            "description": body.description or "",
            "group": body.group,
            "owner": body.owner,
            "serial": body.serial,
            "status": "pending",
            "avatar": body.avatar,
            "embedding_model": body.embedding_model,
            "chunk_method": body.chunk_method or "naive",
            "permission": body.permission,
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        if body.parser_config is not None:
            meta["parser_config"] = body.parser_config
        elif meta["chunk_method"] == "naive":
            meta["parser_config"] = {
                "chunk_token_num": 128,
                "delimiter": "\n",
                "layout_recognize": "DeepDOC",
                "html4excel": False,
                "raptor": {"use_raptor": False},
                "graphrag": {"use_graphrag": False},
            }
        if body.parse_type is not None:
            meta["parse_type"] = body.parse_type
        if body.pipeline_id is not None:
            meta["pipeline_id"] = body.pipeline_id
        return meta

    def update_knowledge(
        self, kb_id: str, body: UpdateKnowledgeRequest
    ) -> dict[str, Any]:
        meta = self._read_meta(kb_id)
        for field in (
            "name",
            "description",
            "group",
            "owner",
            "serial",
            "status",
            "avatar",
            "embedding_model",
            "chunk_method",
            "permission",
            "parser_config",
        ):
            val = getattr(body, field)
            if val is not None:
                meta[field] = val
        self._write_meta(kb_id, meta)
        return self._to_record(kb_id, meta)

    def delete_knowledge(self, kb_id: str) -> str:
        target = self._kb_dir(kb_id)
        if not target.is_dir():
            raise KnowledgeError(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="知识库不存在",
            )
        shutil.rmtree(target)
        return kb_id

    def upload_file(self, kb_id: str, filename: str, content: bytes) -> dict[str, Any]:
        self._read_meta(kb_id)
        if len(content) > self.max_upload_size:
            raise KnowledgeError(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="文件超过大小限制",
            )
        docs = self._docs_dir(kb_id)
        docs.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name or "upload.bin"
        stored = f"{uuid.uuid4().hex[:12]}_{safe_name}"
        path = docs / stored
        path.write_bytes(content)
        meta = self._read_meta(kb_id)
        meta["status"] = "building"
        self._write_meta(kb_id, meta)
        records = self._build_file_records(kb_id)
        record = next((r for r in records if r["id"] == path.name), None)
        if record is None:
            record = self._file_record(path)
        meta["status"] = "success" if record["parsed"] else "building"
        self._write_meta(kb_id, meta)
        return record

    def _resolve_doc_path(self, kb_id: str, file_id: str) -> Path:
        self._read_meta(kb_id)
        if ".." in file_id or file_id.startswith("/") or file_id.startswith("\\"):
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无效的文件 ID",
            )
        path = self._docs_dir(kb_id) / file_id
        if not path.is_file():
            raise KnowledgeError(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="文件不存在",
            )
        return path

    @staticmethod
    def _download_filename(stored_name: str) -> str:
        if "_" in stored_name:
            return stored_name.split("_", 1)[-1]
        return stored_name

    def get_file_for_download(self, kb_id: str, file_id: str) -> tuple[Path, str, str]:
        """Return (absolute path, download filename, media_type)."""
        path = self._resolve_doc_path(kb_id, file_id)
        filename = self._download_filename(path.name)
        media_type, _ = mimetypes.guess_type(filename)
        if not media_type:
            media_type = "application/octet-stream"
        return path, filename, media_type

    @staticmethod
    def _extract_docx_bytes(content: bytes) -> str:
        try:
            with zipfile.ZipFile(BytesIO(content)) as zf:
                xml_bytes = zf.read("word/document.xml")
        except KeyError as exc:
            raise KnowledgeError(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="docx 中缺少 word/document.xml",
            ) from exc
        except zipfile.BadZipFile as exc:
            raise KnowledgeError(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"无法解析 docx：{exc}",
            ) from exc
        root = ET.fromstring(xml_bytes)
        paragraphs: list[str] = []
        for para in root.iter(DOCX_PARA_TAG):
            parts: list[str] = []
            for node in para.iter():
                tag = node.tag
                if tag == DOCX_TEXT_TAG:
                    if node.text:
                        parts.append(node.text)
                    if node.tail:
                        parts.append(node.tail)
                elif tag in (DOCX_BR_TAG, f"{DOCX_NS}cr"):
                    parts.append("\n")
                elif tag == DOCX_TAB_TAG:
                    parts.append("\t")
            paragraphs.append("".join(parts))
        if not paragraphs:
            return "（文档无文本内容）"
        return KnowledgeService._normalize_extracted_text("\n".join(paragraphs))

    @staticmethod
    def extract_text_from_bytes(filename: str, content: bytes) -> str:
        """Extract plain text from uploaded bytes (txt/md/docx etc.)."""
        ext = Path(filename).suffix.lower()
        if ext == ".docx" or content[:2] == b"PK":
            return KnowledgeService._extract_docx_bytes(content)
        if ext in PREVIEW_EXTS:
            return KnowledgeService._normalize_extracted_text(
                content.decode("utf-8", errors="replace")
            )
        raise KnowledgeError(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该文件格式不支持文本预览，请等待解析完成或使用下载",
        )

    @staticmethod
    def _extract_docx_text(path: Path) -> str:
        return KnowledgeService._extract_docx_bytes(path.read_bytes())

    @staticmethod
    def _normalize_extracted_text(text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if "Q:" in text or "A:" in text:
            if text.lstrip().startswith("#"):
                text = re.sub(
                    r"^#\s*([^\n]+?)(?=Q:|A:|$)",
                    r"# \1\n\n",
                    text.lstrip(),
                    count=1,
                )
            text = re.sub(r"([^\n])(?=Q:)", r"\1\n", text)
            text = re.sub(r"([^\n])(?=A:)", r"\1\n", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def get_file_preview_text(self, kb_id: str, file_id: str) -> dict[str, Any]:
        """Extract plain text for in-browser preview (txt/md/json/csv/log/docx)."""
        path = self._resolve_doc_path(kb_id, file_id)
        filename = self._download_filename(path.name)
        ext = path.suffix.lower()
        if ext in PREVIEW_EXTS:
            text = path.read_text(encoding="utf-8", errors="replace")
        elif ext == ".docx":
            text = self._extract_docx_text(path)
        else:
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该文件格式不支持文本预览，请使用下载接口获取原文件",
            )
        text = self._normalize_extracted_text(text)
        truncated = len(text) > PREVIEW_MAX
        return {
            "filename": filename,
            "text": text[:PREVIEW_MAX],
            "truncated": truncated,
        }

    def list_file_chunks(
        self,
        kb_id: str,
        file_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        path = self._resolve_doc_path(kb_id, file_id)
        _, preview = self._file_preview_cached(path)
        blocks = [b.strip() for b in _split_preview_chunks(preview or "") if b.strip()]
        start = (page - 1) * page_size
        page_blocks = blocks[start : start + page_size]
        chunks = [
            {
                "id": f"{file_id}#{start + i}",
                "content": text,
                "available": True,
                "important_keywords": [],
            }
            for i, text in enumerate(page_blocks)
        ]
        return {"chunks": chunks, "total": len(blocks)}

    def set_chunk_available(
        self,
        kb_id: str,
        file_id: str,
        chunk_id: str,
        available: bool,
    ) -> dict[str, Any]:
        raise KnowledgeError(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="本地文件模式暂不支持切片启用/停用",
        )

    def delete_file(self, kb_id: str, file_id: str) -> None:
        path = self._resolve_doc_path(kb_id, file_id)
        path.unlink()

    def reindex(self, kb_id: str) -> dict[str, Any]:
        meta = self._read_meta(kb_id)
        meta["status"] = "building"
        self._write_meta(kb_id, meta)
        files = self._list_doc_files(kb_id)
        if not files:
            meta["status"] = "building"
        elif all(self._file_preview(p)[0] for p in files):
            meta["status"] = "success"
        else:
            meta["status"] = "building"
        self._write_meta(kb_id, meta)
        return self._to_record(kb_id, meta)

    def parse_documents(self, kb_id: str, document_ids: list[str]) -> None:
        """Parse specified documents in a knowledge base (RAGFlow-compatible).

        Extracts text from each document (txt/md/docx etc.) and refreshes the
        knowledge base index status. ``dataset_id`` maps to ``kb_id``.
        """
        if not document_ids:
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="`document_ids` is required",
            )

        meta = self._read_meta(kb_id)
        meta["status"] = "building"
        self._write_meta(kb_id, meta)

        seen: set[str] = set()
        for doc_id in document_ids:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            path = self._resolve_doc_path(kb_id, doc_id)
            cache_key = str(path)
            self._preview_cache.pop(cache_key, None)
            parsed, preview = self._file_preview(path)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0.0
            self._preview_cache[cache_key] = (mtime, parsed, preview)
            logger.info(
                "parsed document %s in kb %s (parsed=%s)",
                doc_id,
                kb_id,
                parsed,
            )

        self._refresh_kb_status(kb_id, meta)

    def _refresh_kb_status(self, kb_id: str, meta: dict[str, Any]) -> None:
        files = self._list_doc_files(kb_id)
        if not files:
            meta["status"] = "pending"
        elif all(self._file_preview_cached(p)[0] for p in files):
            meta["status"] = "success"
        else:
            meta["status"] = "building"
        meta["doc_count"] = len(files)
        self._write_meta(kb_id, meta)

    def qa(self, kb_id: str, question: str) -> dict[str, Any]:
        self.ensure_exists(kb_id)
        snippets: list[str] = []
        sources: list[str] = []
        for name, preview in self._iter_file_previews(kb_id):
            snippets.append(preview[:500])
            sources.append(name)
        if not snippets:
            return {
                "answer": "知识库中暂无可检索的文本内容，请先上传 .md / .txt 等文档。",
                "sources": [],
            }
        joined = "\n\n".join(snippets[:3])
        return {
            "answer": (
                f"（演示模式：尚未接入向量检索与 LLM）\n\n"
                f"针对问题「{question}」，从知识库摘录如下相关内容：\n\n{joined[:2000]}"
            ),
            "sources": sources[:5],
        }

    def recall(
        self,
        kb_id: str,
        query: str,
        similarity: float,
        vector_weight: float,
    ) -> dict[str, Any]:
        self.ensure_exists(kb_id)
        terms = _query_terms(query)
        phrase = _query_clean_phrase(query)
        if not terms:
            return {"chunks": []}

        all_texts: list[str] = []
        chunk_meta: list[tuple[str, str, int, str]] = []
        for path in self._list_doc_files(kb_id):
            _, preview = self._file_preview_cached(path)
            if not preview:
                continue
            name = self._stored_display_name(path.name)
            for i, para in enumerate(_split_preview_chunks(preview)):
                text = para.strip()
                if not text:
                    continue
                all_texts.append(text)
                chunk_meta.append((path.name, name, i, text))

        idf = _compute_term_idf(all_texts, terms)
        chunks: list[RecallChunk] = []
        for file_id, name, i, text in chunk_meta:
            score = _score_chunk_text(
                text, terms, similarity, vector_weight, idf, phrase
            )
            if score < similarity:
                continue
            chunks.append(
                RecallChunk(
                    chunk_id=f"{file_id}#{i}",
                    text=text[:800],
                    score=round(score, 3),
                    file_name=name,
                )
            )
        chunks.sort(key=lambda c: c.score, reverse=True)
        return {"chunks": [c.model_dump() for c in chunks[:10]]}
