"""RAGFlow-compatible retrieval (检索测试) for local filesystem knowledge bases.

Reference: https://ragflow.io/docs/http_api_reference#retrieve-chunks
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.schemas.retrieval import MetadataCondition, RetrievalRequest
from app.services.chunk_availability import filter_chunks_for_retrieval, parse_chunk_available
from app.services.knowledge_factory import KnowledgeBackend
from app.services.knowledge_service import (
    KnowledgeError,
    KnowledgeService,
    _chunk_relevance_score,
    _compute_term_idf,
    _query_clean_phrase,
    _query_terms,
    _split_preview_chunks,
)
from app.services.ragflow_client import get_ragflow_client
from app.services.ragflow_client import RagflowError
from app.services.ragflow_knowledge_service import RagflowKnowledgeService

logger = logging.getLogger(__name__)


def _passes_recall_threshold(
    similarity: float,
    *,
    similarity_threshold: float,
) -> bool:
    """Recall test filters solely by the configured similarity threshold."""
    if similarity < similarity_threshold:
        return False
    return True


def _filter_recall_chunks(
    chunks: list[dict[str, Any]],
    body: RetrievalRequest,
) -> list[dict[str, Any]]:
    return [
        ck
        for ck in chunks
        if _passes_recall_threshold(
            _coerce_float(ck.get("similarity")),
            similarity_threshold=body.similarity_threshold,
        )
    ]


@dataclass
class _ScoredChunk:
    kb_id: str
    document_id: str
    document_name: str
    chunk_index: int
    content: str
    similarity: float
    term_similarity: float
    vector_similarity: float


def _chunk_uuid(kb_id: str, document_id: str, chunk_index: int) -> str:
    raw = f"{kb_id}:{document_id}:{chunk_index}"
    return hashlib.md5(raw.encode()).hexdigest()


def _highlight_content(content: str, terms: list[str]) -> str:
    if not terms:
        return content
    highlighted = content
    for term in sorted(set(terms), key=len, reverse=True):
        if len(term) < 2:
            continue
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        highlighted = pattern.sub(lambda m: f"<em>{m.group(0)}</em>", highlighted)
    return highlighted


def _match_metadata(_condition: MetadataCondition | None) -> bool:
    return True


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_float(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_positions(raw: Any) -> list[str]:
    """RAGFlow may return positions as int lists, e.g. ``[[1,0,0,0,0], ...]``."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [str(raw)]
    out: list[str] = []
    for item in raw:
        if isinstance(item, list):
            out.append(",".join(str(x) for x in item))
        elif isinstance(item, dict):
            out.append(str(item))
        else:
            out.append(str(item))
    return out


def _finalize_retrieval_result(result: dict[str, Any]) -> dict[str, Any]:
    """Drop disabled chunks so Q&A and recall tests never use them."""
    chunks_out = filter_chunks_for_retrieval(result.get("chunks") or [])
    doc_counts: dict[str, dict[str, Any]] = {}
    for ck in chunks_out:
        doc_id = str(ck.get("document_id") or "")
        doc_name = (
            ck.get("document_keyword")
            or ck.get("doc_name")
            or ck.get("document_name")
            or ""
        )
        agg = doc_counts.setdefault(
            doc_id,
            {"doc_id": doc_id, "doc_name": doc_name, "count": 0},
        )
        agg["count"] += 1
    return {
        "chunks": chunks_out,
        "doc_aggs": sorted(doc_counts.values(), key=lambda d: d["count"], reverse=True),
        "total": len(chunks_out),
        "rerank_applied": bool(result.get("rerank_applied", False)),
        "rerank_warning": result.get("rerank_warning"),
    }


def _collect_candidates(
    service: KnowledgeBackend,
    dataset_ids: list[str],
    document_ids: list[str],
) -> list[tuple[str, str, str]]:
    if isinstance(service, RagflowKnowledgeService):
        return []

    if not isinstance(service, KnowledgeService):
        return []

    targets: list[tuple[str, str, str]] = []
    doc_filter = set(document_ids) if document_ids else None

    kb_ids = list(dataset_ids)
    if not kb_ids and doc_filter:
        for record in service.list_knowledge():
            kb_ids.append(str(record["id"]))

    seen: set[tuple[str, str]] = set()
    for kb_id in kb_ids:
        try:
            service.ensure_exists(kb_id)
        except KnowledgeError:
            continue
        for path in service._list_doc_files(kb_id):
            file_id = path.name
            if doc_filter and file_id not in doc_filter:
                continue
            key = (kb_id, file_id)
            if key in seen:
                continue
            seen.add(key)
            name = service._stored_display_name(file_id)
            targets.append((kb_id, file_id, name))
    return targets


def _retrieve_chunks_ragflow(body: RetrievalRequest) -> dict[str, Any]:
    client = get_ragflow_client()
    _ensure_ragflow_dataset_embeddings(client, body.dataset_ids)
    rerank_requested = bool(body.rerank_id or body.tenant_rerank_id)
    rerank_applied = rerank_requested
    rerank_warning: str | None = None
    payload: dict[str, Any] = {
        "question": body.question,
        "dataset_ids": body.dataset_ids,
        "document_ids": body.document_ids,
        "page": body.page,
        "page_size": body.page_size,
        "similarity_threshold": body.similarity_threshold,
        "vector_similarity_weight": body.vector_similarity_weight,
        "top_k": body.top_k,
        # `keyword=true` invokes RAGFlow's default chat model for keyword
        # expansion. The UI defaults it to false, but an explicit user choice
        # is preserved here.
        "keyword": body.keyword,
        "highlight": body.highlight,
        "rerank_id": body.rerank_id,
        "tenant_rerank_id": body.tenant_rerank_id,
        "cross_languages": body.cross_languages,
        "use_kg": body.use_kg,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    if body.metadata_condition is not None:
        payload["metadata_condition"] = body.metadata_condition.model_dump(
            exclude_none=True
        )
    try:
        data = client.retrieve(payload)
    except RagflowError as exc:
        if (payload.get("rerank_id") or payload.get("tenant_rerank_id")) and _is_ragflow_rerank_config_error(exc):
            logger.warning(
                "RAGFlow rerank_id %r / tenant_rerank_id %r is not usable, retrying retrieval without reranker: %s",
                payload.get("rerank_id"),
                payload.get("tenant_rerank_id"),
                exc,
            )
            rerank_applied = False
            rerank_warning = (
                f"RAGFlow rerank_id {payload.get('rerank_id')!r} 不可用，"
                "本次已降级为不使用 reranker。"
            )
            fallback_payload = {
                k: v
                for k, v in payload.items()
                if k not in {"rerank_id", "tenant_rerank_id"}
            }
            try:
                data = client.retrieve(fallback_payload)
            except RagflowError as fallback_exc:
                if _is_ragflow_model_config_error(fallback_exc):
                    return _retrieve_chunks_ragflow_by_list_chunks(
                        body,
                        (
                            "RAGFlow 检索模型配置不可用，已降级为基于已解析切片的关键词检索。"
                            f" 原始错误：{fallback_exc}"
                        ),
                    )
                raise
        elif _is_ragflow_model_config_error(exc):
            return _retrieve_chunks_ragflow_by_list_chunks(
                body,
                (
                    "RAGFlow 检索模型配置不可用，已降级为基于已解析切片的关键词检索。"
                    f" 原始错误：{exc}"
                ),
            )
        else:
            raise

    chunks_in = data.get("chunks") or []
    chunks_out: list[dict[str, Any]] = []
    for ck in chunks_in:
        if not isinstance(ck, dict):
            continue
        if not parse_chunk_available(ck):
            continue
        kb_id = ck.get("dataset_id") or ck.get("kb_id") or (
            body.dataset_ids[0] if body.dataset_ids else ""
        )
        chunks_out.append(
            {
                "id": ck.get("id") or ck.get("chunk_id") or "",
                "content": ck.get("content") or ck.get("content_with_weight") or "",
                "content_ltks": ck.get("content_ltks")
                or ck.get("content")
                or ck.get("content_with_weight")
                or "",
                "document_id": ck.get("document_id") or ck.get("doc_id") or "",
                "document_keyword": ck.get("document_keyword")
                or ck.get("docnm_kwd")
                or ck.get("doc_name"),
                "highlight": ck.get("highlight"),
                "image_id": ck.get("image_id") or ck.get("image_id") or "",
                "important_keywords": ck.get("important_keywords")
                or ck.get("important_kwd")
                or [],
                "tag_kwd": ck.get("tag_kwd") or [],
                "kb_id": kb_id,
                "positions": _normalize_positions(ck.get("positions")),
                "similarity": _coerce_float(ck.get("similarity")),
                "term_similarity": _coerce_float(ck.get("term_similarity")),
                "vector_similarity": _coerce_float(ck.get("vector_similarity")),
                "rerank_score": _first_float(
                    ck.get("rerank_score"),
                    ck.get("rerank_similarity"),
                    ck.get("rerank_sim"),
                    ck.get("relevance_score"),
                    ck.get("score"),
                ),
                "available": parse_chunk_available(ck),
            }
        )
    chunks_out = _filter_recall_chunks(chunks_out, body)
    doc_counts: dict[str, dict[str, Any]] = {}
    for ck in chunks_out:
        doc_id = str(ck.get("document_id") or "")
        doc_name = ck.get("document_keyword") or ""
        agg = doc_counts.setdefault(
            doc_id,
            {"doc_id": doc_id, "doc_name": doc_name, "count": 0},
        )
        agg["count"] += 1
    filtered_doc_aggs = sorted(doc_counts.values(), key=lambda d: d["count"], reverse=True)
    return _finalize_retrieval_result(
        {
            "chunks": chunks_out,
            "doc_aggs": filtered_doc_aggs,
            "total": len(chunks_out),
            "rerank_applied": rerank_applied,
            "rerank_warning": rerank_warning,
        }
    )


def _ensure_ragflow_dataset_embeddings(client, dataset_ids: list[str]) -> None:
    missing_ids: list[str] = []
    seen: set[str] = set()
    for dataset_id in dataset_ids:
        if not dataset_id or dataset_id in seen:
            continue
        seen.add(dataset_id)
        try:
            dataset = client.get_dataset(dataset_id)
        except RagflowError as exc:
            logger.warning("Failed to inspect RAGFlow dataset %s embedding: %s", dataset_id, exc)
            continue
        embedding_model = str(
            dataset.get("embedding_model")
            or dataset.get("embd_id")
            or ""
        ).strip()
        if not embedding_model:
            missing_ids.append(dataset_id)

    if not missing_ids:
        return

    default_embedding = str(client.get_user_models().get("embd_id") or "").strip()
    if not default_embedding:
        logger.warning(
            "RAGFlow datasets %s have empty embedding_model, but tenant default embd_id is empty",
            missing_ids,
        )
        return

    for dataset_id in missing_ids:
        try:
            client.update_dataset(dataset_id, {"embedding_model": default_embedding})
            logger.info(
                "Filled empty RAGFlow dataset embedding_model: dataset=%s embedding_model=%s",
                dataset_id,
                default_embedding,
            )
        except RagflowError as exc:
            logger.warning(
                "Failed to fill RAGFlow dataset %s embedding_model=%s: %s",
                dataset_id,
                default_embedding,
                exc,
            )


def _is_ragflow_rerank_config_error(exc: RagflowError) -> bool:
    message = str(exc).lower()
    return (
        "provider" in message
        and "not found" in message
        and ("rerank" in message or "model" in message)
    )


def _is_ragflow_model_config_error(exc: RagflowError) -> bool:
    message = str(exc).lower()
    return "provider" in message and "not found" in message and "model" in message


def _retrieve_chunks_ragflow_by_list_chunks(
    body: RetrievalRequest,
    warning: str,
) -> dict[str, Any]:
    """Fallback when RAGFlow /retrieval fails due to broken model config."""
    client = get_ragflow_client()
    terms = _query_terms(body.question)
    phrase = _query_clean_phrase(body.question)
    if not terms:
        return {
            "chunks": [],
            "doc_aggs": [],
            "total": 0,
            "rerank_applied": False,
            "rerank_warning": warning,
        }

    doc_filter = set(body.document_ids or [])
    pending: list[tuple[str, str, str, int, str, str, list[str], bool]] = []
    all_texts: list[str] = []
    seen_chunks: set[str] = set()

    for kb_id in body.dataset_ids:
        try:
            docs = client.list_all_documents(kb_id)
        except RagflowError as exc:
            logger.warning("RAGFlow fallback list documents failed for %s: %s", kb_id, exc)
            continue

        for doc in docs:
            doc_id = str(doc.get("id") or "")
            if not doc_id or (doc_filter and doc_id not in doc_filter):
                continue
            doc_name = str(doc.get("name") or doc.get("location") or doc_id)
            chunk_index = 0
            for page in range(1, 101):
                try:
                    data = client.list_document_chunks(
                        kb_id,
                        doc_id,
                        page=page,
                        page_size=100,
                    )
                except RagflowError as exc:
                    logger.warning(
                        "RAGFlow fallback list chunks failed for %s/%s page %d: %s",
                        kb_id,
                        doc_id,
                        page,
                        exc,
                    )
                    break

                raw_chunks = _extract_ragflow_chunk_list(data)
                if not raw_chunks:
                    break
                for raw in raw_chunks:
                    if not parse_chunk_available(raw):
                        continue
                    text = str(
                        raw.get("content")
                        or raw.get("content_with_weight")
                        or raw.get("content_ltks")
                        or ""
                    ).strip()
                    if not text:
                        continue
                    raw_id = str(raw.get("id") or raw.get("chunk_id") or "")
                    chunk_id = raw_id or _chunk_uuid(kb_id, doc_id, chunk_index)
                    dedupe_key = f"{kb_id}:{doc_id}:{chunk_id}"
                    if dedupe_key in seen_chunks:
                        continue
                    seen_chunks.add(dedupe_key)
                    positions = _normalize_positions(raw.get("positions")) or [str(chunk_index)]
                    pending.append(
                        (
                            kb_id,
                            doc_id,
                            doc_name,
                            chunk_index,
                            text[:2000],
                            chunk_id,
                            positions,
                            parse_chunk_available(raw),
                        )
                    )
                    all_texts.append(text)
                    chunk_index += 1
                if len(raw_chunks) < 100:
                    break

    idf = _compute_term_idf(all_texts, terms)
    scored: list[dict[str, Any]] = []
    for kb_id, doc_id, doc_name, chunk_index, text, chunk_id, positions, available in pending:
        sim, term_sim, vec_sim = _chunk_relevance_score(
            text,
            terms,
            phrase,
            idf,
            body.similarity_threshold,
            body.vector_similarity_weight,
        )
        if sim < body.similarity_threshold:
            continue
        scored.append(
            {
                "id": chunk_id,
                "content": text,
                "content_ltks": text,
                "document_id": doc_id,
                "document_keyword": doc_name,
                "highlight": _highlight_content(text, terms) if body.highlight else None,
                "image_id": "",
                "important_keywords": [],
                "tag_kwd": [],
                "kb_id": kb_id,
                "positions": positions or [str(chunk_index)],
                "similarity": sim,
                "term_similarity": term_sim,
                "vector_similarity": vec_sim,
                "available": available,
            }
        )

    scored.sort(key=lambda item: item["similarity"], reverse=True)
    max_return = min(body.page_size, body.top_k, 100)
    if max_return < len(scored):
        scored = scored[:max_return]

    result = _finalize_retrieval_result(
        {
            "chunks": scored,
            "total": len(scored),
            "rerank_applied": False,
            "rerank_warning": warning,
        }
    )
    result["rerank_warning"] = warning
    return result


def _extract_ragflow_chunk_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        for key in ("chunks", "data", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def retrieve_chunks(
    service: KnowledgeBackend,
    body: RetrievalRequest,
) -> dict[str, Any]:
    """Retrieve only chunks that truly match the question (IDF-weighted keywords)."""
    if isinstance(service, RagflowKnowledgeService):
        return _retrieve_chunks_ragflow(body)

    if not isinstance(service, KnowledgeService):
        return {"chunks": [], "doc_aggs": [], "total": 0}
    if not _match_metadata(body.metadata_condition):
        return {"chunks": [], "doc_aggs": [], "total": 0}

    terms = _query_terms(body.question)
    phrase = _query_clean_phrase(body.question)
    if not terms:
        return {"chunks": [], "doc_aggs": [], "total": 0}

    candidates = _collect_candidates(service, body.dataset_ids, body.document_ids)

    pending: list[tuple[str, str, str, int, str]] = []
    all_texts: list[str] = []
    for kb_id, file_id, file_name in candidates:
        path = service._docs_dir(kb_id) / file_id
        if not path.is_file():
            continue
        _, preview = service._file_preview_cached(path)
        if not preview:
            continue
        for i, block in enumerate(_split_preview_chunks(preview)):
            text = block.strip()
            if not text:
                continue
            pending.append((kb_id, file_id, file_name, i, text))
            all_texts.append(text)

    idf = _compute_term_idf(all_texts, terms)

    scored: list[_ScoredChunk] = []
    for kb_id, file_id, file_name, i, text in pending:
        sim, term_sim, vec_sim = _chunk_relevance_score(
            text,
            terms,
            phrase,
            idf,
            body.similarity_threshold,
            body.vector_similarity_weight,
        )
        if term_sim <= 0 or sim < body.similarity_threshold:
            continue
        scored.append(
            _ScoredChunk(
                kb_id=kb_id,
                document_id=file_id,
                document_name=file_name,
                chunk_index=i,
                content=text[:2000],
                similarity=sim,
                term_similarity=term_sim,
                vector_similarity=vec_sim,
            )
        )

    scored.sort(key=lambda c: c.similarity, reverse=True)
    max_return = min(body.page_size, body.top_k, 50)
    if max_return < len(scored):
        scored = scored[:max_return]

    total = len(scored)
    start = (body.page - 1) * body.page_size
    end = start + body.page_size
    page_items = scored[start:end]

    doc_counts: dict[str, dict[str, Any]] = {}
    chunks_out: list[dict[str, Any]] = []
    for item in page_items:
        chunk_id = _chunk_uuid(item.kb_id, item.document_id, item.chunk_index)
        highlight = (
            _highlight_content(item.content, terms) if body.highlight else None
        )
        chunks_out.append(
            {
                "id": chunk_id,
                "content": item.content,
                "content_ltks": item.content,
                "document_id": item.document_id,
                "document_keyword": item.document_name,
                "highlight": highlight,
                "image_id": "",
                "important_keywords": [],
                "tag_kwd": [],
                "kb_id": item.kb_id,
                "positions": [str(item.chunk_index)],
                "similarity": item.similarity,
                "term_similarity": item.term_similarity,
                "vector_similarity": item.vector_similarity,
                "available": True,
            }
        )
        agg = doc_counts.setdefault(
            item.document_id,
            {"doc_id": item.document_id, "doc_name": item.document_name, "count": 0},
        )
        agg["count"] += 1

    doc_aggs = sorted(doc_counts.values(), key=lambda d: d["count"], reverse=True)
    return _finalize_retrieval_result(
        {
            "chunks": chunks_out,
            "doc_aggs": doc_aggs,
            "total": total,
        }
    )


def build_retrieval_response(
    service: KnowledgeBackend,
    body: RetrievalRequest,
) -> dict[str, Any]:
    from app.schemas.retrieval import RetrievalDataResponse

    raw = retrieve_chunks(service, body)
    return RetrievalDataResponse.model_validate(raw).model_dump(mode="json")
