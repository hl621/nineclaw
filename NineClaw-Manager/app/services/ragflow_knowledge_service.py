"""Knowledge base operations backed by RAGFlow datasets/documents."""

from __future__ import annotations

import logging
import mimetypes
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import status

from app.core.config import settings
from app.schemas.knowledge import CreateKnowledgeRequest, UpdateKnowledgeRequest
from app.services.chunk_availability import parse_chunk_available
from app.services.knowledge_service import KnowledgeError, KnowledgeService
from app.services.ragflow_client import RagflowClient, RagflowError, get_ragflow_client

logger = logging.getLogger(__name__)

_RUN_PARSED = {"DONE", "3"}
_RUN_FAILED = {"FAIL", "4"}
_LIST_STATUS_MAX_WORKERS = 8


def _normalize_doc_run(run: Any) -> str:
    if run is None:
        return "UNSTART"
    if isinstance(run, int):
        return {0: "UNSTART", 1: "RUNNING", 2: "CANCEL", 3: "DONE", 4: "FAIL"}.get(
            run, str(run)
        )
    text = str(run).strip().upper()
    if text.isdigit():
        return _normalize_doc_run(int(text))
    return text


def _doc_parsed(run: Any) -> bool:
    return _normalize_doc_run(run) in _RUN_PARSED


def _doc_parse_failed(run: Any) -> bool:
    return _normalize_doc_run(run) in _RUN_FAILED


def _doc_progress(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _doc_progress_msg(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


_VALID_KB_STATUS = {
    "pending",
    "building",
    "success",
    "part_success",
    "fail",
}

_AUDIO_SUFFIXES = (
    ".wav",
    ".mp3",
    ".m4a",
    ".aac",
    ".flac",
    ".ogg",
    ".opus",
    ".wma",
)
_VIDEO_SUFFIXES = (
    ".mp4",
    ".webm",
    ".mov",
    ".mkv",
    ".avi",
    ".wmv",
    ".flv",
    ".mpeg",
    ".mpg",
    ".m4v",
)


def _is_audio_name(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(s) for s in _AUDIO_SUFFIXES)


def _is_video_name(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(s) for s in _VIDEO_SUFFIXES)


def _is_media_name(name: str) -> bool:
    return _is_audio_name(name) or _is_video_name(name)


def _normalize_kb_status(
    raw: Any,
    docs: list[dict[str, Any]] | None = None,
) -> str:
    # 有文档列表时以文档解析状态为准
    if docs is not None:
        return _dataset_status(docs)
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in _VALID_KB_STATUS:
            return lowered
        # 兼容旧值
        if lowered in ("done", "active", "success", "ready", "1", "true"):
            return "success"
        if lowered in ("fail", "failed", "error", "0"):
            return "fail"
        if lowered in ("part_success", "partial", "partial_success", "part-success"):
            return "part_success"
        if lowered in ("running", "indexing", "building", "cancel"):
            return "building"
        if lowered in ("unstart", "pending"):
            return "pending"
    return "pending"


def _parse_timestamp(value: Any) -> datetime:
    if value is None:
        return datetime.now(tz=timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(tz=timezone.utc)


def _dataset_status(docs: list[dict[str, Any]]) -> str:
    """Derive KB card status from document parse runs.

    - no documents → pending（待构建）
    - any非终态 → building（构建中）；若全部仍为 UNSTART → pending
    - all FAIL → fail（构建失败）
    - mix DONE + FAIL → part_success（界面：部分异常）
    - all DONE → success（已就绪）
    """
    if not docs:
        return "pending"
    runs = [_normalize_doc_run(d.get("run")) for d in docs]
    parsed_flags = [r in _RUN_PARSED for r in runs]
    failed_flags = [r in _RUN_FAILED for r in runs]
    unfinished = [
        r
        for r, p, f in zip(runs, parsed_flags, failed_flags, strict=False)
        if not p and not f
    ]

    if unfinished:
        if (
            all(r == "UNSTART" for r in unfinished)
            and not any(parsed_flags)
            and not any(failed_flags)
        ):
            return "pending"
        return "building"

    if any(failed_flags) and any(parsed_flags):
        return "part_success"
    if any(failed_flags) and not any(parsed_flags):
        return "fail"
    if all(parsed_flags):
        return "success"
    return "pending"


def _map_document(doc: dict[str, Any]) -> dict[str, Any]:
    run = _normalize_doc_run(doc.get("run"))
    # RAGFlow HTTP API 使用 chunk_num（内部字段），Python SDK 包装为 chunk_count
    chunk_count = int(
        doc.get("chunk_count")
        or doc.get("chunk_num")
        or 0
    )
    logger.debug(
        "[RAGFlow doc] id=%s name=%s run_raw=%r run=%s chunk_count=%d keys=%s",
        doc.get("id"),
        doc.get("name") or doc.get("location"),
        doc.get("run"),
        run,
        chunk_count,
        list(doc.keys()),
    )
    return {
        "id": str(doc.get("id", "")),
        "name": str(doc.get("name") or doc.get("location") or doc.get("id", "")),
        "size_bytes": int(doc.get("size") or 0),
        "parsed": _doc_parsed(run),
        "parse_failed": _doc_parse_failed(run),
        "chunk_count": chunk_count,
        "progress": _doc_progress(doc.get("progress")),
        "progress_msg": _doc_progress_msg(doc.get("progress_msg")),
        "preview": None,
        "uploaded_at": _parse_timestamp(doc.get("create_time") or doc.get("create_date")),
    }


def _map_dataset(
    ds: dict[str, Any],
    *,
    docs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    doc_list = docs if docs is not None else []
    doc_count = int(ds.get("document_count") or ds.get("doc_count") or len(doc_list))
    return {
        "id": str(ds.get("id", "")),
        "dataset_id": str(ds.get("id", "")),
        "name": str(ds.get("name") or ds.get("id", "")),
        "description": str(ds.get("description") or ""),
        "group": str(ds.get("group") or ""),
        "owner": str(ds.get("created_by") or ds.get("owner") or ""),
        "serial": ds.get("serial"),
        "status": _normalize_kb_status(ds.get("status"), docs=doc_list if docs is not None else None),
        "doc_count": doc_count,
        "updated_at": _parse_timestamp(
            ds.get("update_time") or ds.get("update_date") or ds.get("updated_at")
        ),
        "avatar": ds.get("avatar"),
        "embedding_model": ds.get("embedding_model"),
        "chunk_method": ds.get("chunk_method"),
        "permission": ds.get("permission"),
        "parser_config": ds.get("parser_config"),
    }


def _ragflow_to_http_error(exc: RagflowError) -> KnowledgeError:
    code = exc.status_code if exc.status_code in (400, 404, 409, 413) else 502
    message = exc.message
    if exc.status_code == 404:
        message = "知识库不存在"
    return KnowledgeError(status_code=code, detail=message)


PREVIEW_MAX = 4000
MEDIA_CONTENT_MAX = 50_000


def _is_asr_error_text(text: str) -> bool:
    """RAGFlow Sequence2Txt often embeds provider failures as ``**ERROR**: …``."""
    cleaned = (text or "").strip().upper()
    return cleaned.startswith("**ERROR**") or cleaned.startswith("ERROR:")


def _collect_chunk_texts(data: Any) -> list[str]:
    """Parse RAGFlow list-chunks response into plain text blocks."""
    chunks: list[Any] = []
    if isinstance(data, dict):
        nested_data = data.get("data")
        if isinstance(data.get("chunks"), list):
            chunks = data["chunks"]
        elif isinstance(nested_data, dict) and isinstance(
            nested_data.get("chunks"), list
        ):
            chunks = nested_data["chunks"]
        elif isinstance(nested_data, list):
            chunks = nested_data
        elif isinstance(data.get("items"), list):
            chunks = data["items"]
    elif isinstance(data, list):
        chunks = data

    parts: list[str] = []
    for ck in chunks:
        if isinstance(ck, str):
            text = ck.strip()
            if text and not _is_asr_error_text(text):
                parts.append(text)
            continue
        if not isinstance(ck, dict):
            continue
        text = (
            ck.get("content")
            or ck.get("content_with_weight")
            or ck.get("content_ltks")
            or ck.get("text")
            or ck.get("question")
            or ck.get("answer")
            or ""
        )
        text = str(text).strip()
        if text and not _is_asr_error_text(text):
            parts.append(text)
    return parts


def _extract_chunk_list(data: Any) -> list[dict[str, Any]]:
    from app.services.knowledge_chunk_service import extract_chunk_list

    return extract_chunk_list(data)


def _map_chunk_item(ck: dict[str, Any]) -> dict[str, Any]:
    from app.services.knowledge_chunk_service import map_chunk_item

    return map_chunk_item(ck)


class RagflowKnowledgeService:
    """Adapter: NineClaw knowledge API → RAGFlow dataset/document API."""

    def __init__(self, client: RagflowClient | None = None) -> None:
        self._client = client or get_ragflow_client()
        self.max_upload_size = settings.knowledge_max_upload_size

    def ensure_storage(self) -> None:
        return None

    def ensure_exists(self, kb_id: str) -> None:
        try:
            self._client.get_dataset(kb_id)
        except RagflowError as exc:
            raise _ragflow_to_http_error(exc) from exc

    def list_knowledge(self) -> list[dict[str, Any]]:
        try:
            datasets = self._client.list_all_datasets()
        except RagflowError as exc:
            raise _ragflow_to_http_error(exc) from exc

        # 列表卡片状态必须看文档解析进度；并行拉取各库文档 run 状态
        # None = 拉取失败（勿当成空库 ready）
        docs_by_id: dict[str, list[dict[str, Any]] | None] = {}

        def _fetch_docs(
            dataset_id: str,
        ) -> tuple[str, list[dict[str, Any]] | None]:
            try:
                return dataset_id, self._client.list_all_documents(dataset_id)
            except RagflowError:
                logger.warning(
                    "list_knowledge: failed to list documents for %s",
                    dataset_id,
                    exc_info=True,
                )
                return dataset_id, None

        dataset_ids = [
            str(ds.get("id") or "").strip()
            for ds in datasets
            if str(ds.get("id") or "").strip()
        ]
        if dataset_ids:
            workers = min(_LIST_STATUS_MAX_WORKERS, len(dataset_ids))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_fetch_docs, kid) for kid in dataset_ids]
                for fut in as_completed(futures):
                    kid, docs = fut.result()
                    docs_by_id[kid] = docs

        items: list[dict[str, Any]] = []
        for ds in datasets:
            kid = str(ds.get("id") or "").strip()
            docs = docs_by_id.get(kid)
            if docs is None:
                # 文档列表拉取失败时：有文档数则保守显示解析中，避免误报已就绪
                doc_count = int(ds.get("document_count") or ds.get("doc_count") or 0)
                record = _map_dataset(ds, docs=None)
                if doc_count > 0:
                    record["status"] = "building"
                items.append(record)
            else:
                items.append(_map_dataset(ds, docs=docs))
        items.sort(key=lambda k: k["updated_at"], reverse=True)
        return items

    def get_knowledge(self, kb_id: str) -> dict[str, Any]:
        try:
            ds = self._client.get_dataset(kb_id)
            docs = self._client.list_all_documents(kb_id)
        except RagflowError as exc:
            raise _ragflow_to_http_error(exc) from exc
        record = _map_dataset(ds, docs=docs)
        record["files"] = [_map_document(d) for d in docs]
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
        try:
            data = self._client.list_documents_page(
                kb_id,
                page=page,
                page_size=page_size,
                keywords=keywords,
            )
        except RagflowError as exc:
            raise _ragflow_to_http_error(exc) from exc
        docs = data.get("docs", [])
        return {
            "items": [_map_document(d) for d in docs if isinstance(d, dict)],
            "total": int(data.get("total") or 0),
        }

    def create_knowledge(self, body: CreateKnowledgeRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": body.name,
            "description": body.description or "",
            "permission": body.permission or "me",
        }
        if body.embedding_model:
            payload["embedding_model"] = body.embedding_model
        else:
            default_embedding = str(self._client.get_user_models().get("embd_id") or "").strip()
            if default_embedding:
                payload["embedding_model"] = default_embedding
        if body.chunk_method:
            payload["chunk_method"] = body.chunk_method
        if body.parser_config:
            payload["parser_config"] = body.parser_config
        try:
            ds = self._client.create_dataset(payload)
        except RagflowError as exc:
            raise _ragflow_to_http_error(exc) from exc
        return _map_dataset(ds, docs=[])

    def update_knowledge(
        self, kb_id: str, body: UpdateKnowledgeRequest
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for field in (
            "name",
            "description",
            "embedding_model",
            "chunk_method",
            "permission",
            "parser_config",
        ):
            val = getattr(body, field)
            if val is not None:
                payload[field] = val
        try:
            if payload:
                ds = self._client.update_dataset(kb_id, payload)
            else:
                ds = self._client.get_dataset(kb_id)
        except RagflowError as exc:
            raise _ragflow_to_http_error(exc) from exc
        return _map_dataset(ds)

    def delete_knowledge(self, kb_id: str) -> str:
        try:
            self._client.delete_datasets([kb_id])
        except RagflowError as exc:
            raise _ragflow_to_http_error(exc) from exc
        return kb_id

    def upload_file(self, kb_id: str, filename: str, content: bytes) -> dict[str, Any]:
        self.ensure_exists(kb_id)
        if len(content) > self.max_upload_size:
            raise KnowledgeError(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="文件超过大小限制",
            )
        safe_name = Path(filename).name or "upload.bin"
        try:
            uploaded = self._client.upload_documents(kb_id, [(safe_name, content)])
        except RagflowError as exc:
            raise _ragflow_to_http_error(exc) from exc
        if not uploaded:
            raise KnowledgeError(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="RAGFlow 上传未返回文档信息",
            )
        doc = uploaded[0]
        doc_id = str(doc.get("id") or "")
        # 视频走 picture 解析器（RAGFlow picture.py 内用默认 VLM 描述视频）
        if doc_id and _is_video_name(safe_name):
            try:
                self._client.update_document(
                    kb_id, doc_id, {"chunk_method": "picture"}
                )
            except RagflowError as exc:
                logger.warning(
                    "RAGFlow update video parser failed kb=%s file=%s: %s",
                    kb_id,
                    doc_id,
                    exc.message,
                )
        return _map_document(doc)

    def get_media_content(self, kb_id: str, file_id: str) -> dict[str, Any]:
        """音视频预览文本：优先 RAGFlow 切片，否则调用租户默认 ASR 转写并回写切片。"""
        self.ensure_exists(kb_id)
        docs = self._client.list_all_documents(kb_id)
        doc = next((d for d in docs if str(d.get("id")) == file_id), None)
        if doc is None:
            raise KnowledgeError(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="文件不存在",
            )
        filename = str(doc.get("name") or doc.get("location") or file_id)
        if not _is_media_name(filename):
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="仅支持音频/视频文件",
            )

        # 1) 已有切片
        parts: list[str] = []
        page = 1
        while page <= 20:
            try:
                data = self._client.list_document_chunks(
                    kb_id, file_id, page=page, page_size=50
                )
            except RagflowError:
                break
            page_parts = _collect_chunk_texts(data)
            if not page_parts:
                break
            parts.extend(page_parts)
            if len(page_parts) < 50:
                break
            page += 1
        if parts:
            text = "\n\n".join(parts)
            # 音频短切片多为整文件 ASR 残缺/跑偏，不作为最终正文
            if _is_audio_name(filename) and len(text.replace(" ", "")) < 100:
                parts = []
            else:
                return {
                    "filename": filename,
                    "text": text[:MEDIA_CONTENT_MAX],
                    "source": "ragflow-chunks",
                    "truncated": len(text) > MEDIA_CONTENT_MAX,
                }

        # 2) 调用 RAGFlow 默认 ASR（与 user-setting/model 中 ASR 一致）
        try:
            raw = self._client.download_document(kb_id, file_id)
        except RagflowError as exc:
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=exc.message or "无法下载文件以转写",
            ) from exc

        # mp4 等容器不被 transcription 接口接受；交给前端抽音轨后再调 ASR
        if _is_video_name(filename):
            return {
                "filename": filename,
                "text": "",
                "source": "pending-video",
                "truncated": False,
                "message": (
                    "RAGFlow 尚无视频切片。正在由前端抽取音轨并用 RAGFlow ASR 转写。"
                ),
            }

        # 长音频整文件 ASR 极易只返回一句且内容不准 → 交前端切段
        if _is_audio_name(filename) and len(raw) > 500_000:
            return {
                "filename": filename,
                "text": "",
                "source": "pending-audio-segments",
                "truncated": False,
                "message": (
                    "音频较长，整文件 ASR 不可靠。正在由前端按段转写全文。"
                ),
            }

        try:
            text = self._client.transcribe_audio(filename, raw)
        except RagflowError as exc:
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    exc.message
                    or "RAGFlow ASR 转写失败。请在 RAGFlow「模型设置」确认已配置默认 ASR。"
                ),
            ) from exc

        if text and len(text.replace(" ", "")) < 100 and len(raw) > 300_000:
            return {
                "filename": filename,
                "text": "",
                "source": "pending-audio-segments",
                "truncated": False,
                "message": (
                    "整文件 ASR 结果过短，疑似残缺。正在由前端按段转写全文。"
                ),
            }

        if not text:
            return {
                "filename": filename,
                "text": "",
                "source": "ragflow-asr",
                "truncated": False,
                "message": "ASR 未识别到有效语音内容",
            }

        # 回写切片，保持 NineClaw RAG 与 RAGFlow 互通
        try:
            self._client.add_document_chunk(
                kb_id,
                file_id,
                text,
                important_keywords=["asr", "audio"],
            )
        except RagflowError as exc:
            logger.warning(
                "RAGFlow add ASR chunk failed kb=%s file=%s: %s",
                kb_id,
                file_id,
                exc.message,
            )

        return {
            "filename": filename,
            "text": text[:MEDIA_CONTENT_MAX],
            "source": "ragflow-asr",
            "truncated": len(text) > MEDIA_CONTENT_MAX,
        }

    def transcribe_uploaded_audio(
        self,
        kb_id: str,
        file_id: str,
        filename: str,
        content: bytes,
        *,
        write_chunk: bool = True,
    ) -> dict[str, Any]:
        """对前端抽取的音轨（如从视频导出的 webm/wav）调用 RAGFlow ASR。"""
        self.ensure_exists(kb_id)
        safe_name = Path(filename).name or "audio.webm"
        try:
            text = self._client.transcribe_audio(safe_name, content)
        except RagflowError as exc:
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    exc.message
                    or "RAGFlow ASR 转写失败。请在 RAGFlow「模型设置」确认已配置默认 ASR。"
                ),
            ) from exc
        if write_chunk and text.strip():
            try:
                self._client.add_document_chunk(
                    kb_id,
                    file_id,
                    text.strip(),
                    important_keywords=["asr", "video-audio"],
                )
            except RagflowError as exc:
                logger.warning(
                    "RAGFlow add video-audio chunk failed kb=%s file=%s: %s",
                    kb_id,
                    file_id,
                    exc.message,
                )
        return {
            "filename": safe_name,
            "text": (text or "")[:MEDIA_CONTENT_MAX],
            "source": "ragflow-asr",
            "truncated": len(text or "") > MEDIA_CONTENT_MAX,
        }

    def delete_file(self, kb_id: str, file_id: str) -> None:
        try:
            self._client.delete_documents(kb_id, [file_id])
        except RagflowError as exc:
            # 文档已不存在，视为幂等删除成功
            if exc.status_code == 404 or "not found" in exc.message.lower() or "not exist" in exc.message.lower():
                return
            raise _ragflow_to_http_error(exc) from exc

    def parse_documents(self, kb_id: str, document_ids: list[str]) -> None:
        if not document_ids:
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="`document_ids` is required",
            )
        self.ensure_exists(kb_id)
        try:
            self._client.parse_documents(kb_id, document_ids)
        except RagflowError as exc:
            raise _ragflow_to_http_error(exc) from exc

    def reindex(self, kb_id: str) -> dict[str, Any]:
        record = self.get_knowledge(kb_id)
        doc_ids = [str(f["id"]) for f in record.get("files", [])]
        if doc_ids:
            self.parse_documents(kb_id, doc_ids)
        return self.get_knowledge(kb_id)

    def get_file_preview_text(self, kb_id: str, file_id: str) -> dict[str, Any]:
        self.ensure_exists(kb_id)
        docs = self._client.list_all_documents(kb_id)
        doc = next((d for d in docs if str(d.get("id")) == file_id), None)
        if doc is None:
            raise KnowledgeError(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="文件不存在",
            )
        filename = str(doc.get("name") or doc.get("location") or file_id)
        parts: list[str] = []
        page = 1
        while page <= 20:
            try:
                data = self._client.list_document_chunks(
                    kb_id, file_id, page=page, page_size=50
                )
            except RagflowError:
                break
            page_parts = _collect_chunk_texts(data)
            if not page_parts:
                break
            parts.extend(page_parts)
            if len(page_parts) < 50:
                break
            page += 1

        if parts:
            text = "\n\n".join(parts)
            truncated = len(text) > PREVIEW_MAX
            return {
                "filename": filename,
                "text": text[:PREVIEW_MAX],
                "truncated": truncated,
            }

        # 音视频内容完全依赖 RAGFlow 切片；无切片时不要回退到本地二进制抽文本
        lower_name = filename.lower()
        media_suffixes = (
            ".wav",
            ".mp3",
            ".m4a",
            ".aac",
            ".flac",
            ".ogg",
            ".webm",
            ".opus",
            ".wma",
            ".mp4",
            ".mov",
            ".mkv",
            ".avi",
        )
        if lower_name.endswith(media_suffixes):
            return {
                "filename": filename,
                "text": "",
                "truncated": False,
            }

        try:
            raw = self._client.download_document(kb_id, file_id)
            text = KnowledgeService.extract_text_from_bytes(filename, raw)
            truncated = len(text) > PREVIEW_MAX
            return {
                "filename": filename,
                "text": text[:PREVIEW_MAX],
                "truncated": truncated,
            }
        except KnowledgeError:
            raise
        except RagflowError as exc:
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=exc.message or "该文件暂无可预览内容，请等待解析完成",
            ) from exc
        except Exception as exc:
            raise KnowledgeError(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无法预览该文件：{exc}",
            ) from exc

    def get_file_for_download(self, kb_id: str, file_id: str) -> tuple[Path, str, str]:
        self.ensure_exists(kb_id)
        docs = self._client.list_all_documents(kb_id)
        doc = next((d for d in docs if str(d.get("id")) == file_id), None)
        if doc is None:
            raise KnowledgeError(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="文件不存在",
            )
        filename = str(doc.get("name") or doc.get("location") or file_id)
        try:
            content = self._client.download_document(kb_id, file_id)
        except RagflowError as exc:
            preview = self.get_file_preview_text(kb_id, file_id)
            content = preview["text"].encode("utf-8")
            if not filename.lower().endswith(".txt"):
                filename = f"{Path(filename).stem}.txt"

        suffix = Path(filename).suffix or ".bin"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(content)
        tmp.close()
        media_type, _ = mimetypes.guess_type(filename)
        return Path(tmp.name), filename, media_type or "application/octet-stream"

    def list_file_chunks(
        self,
        kb_id: str,
        file_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        from app.services import knowledge_chunk_service

        return knowledge_chunk_service.list_file_chunks(
            self, kb_id, file_id, page=page, page_size=page_size
        )

    def set_chunk_available(
        self,
        kb_id: str,
        file_id: str,
        chunk_id: str,
        available: bool,
    ) -> dict[str, Any]:
        from app.services import knowledge_chunk_service

        return knowledge_chunk_service.update_chunk_available(
            self, kb_id, file_id, chunk_id, available
        )
