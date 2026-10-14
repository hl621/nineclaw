"""Recall threshold filtering for RAGFlow hybrid retrieval."""

import pytest

from app.schemas.retrieval import RetrievalRequest
from app.services.knowledge_retrieval_service import (
    _passes_recall_threshold,
    _retrieve_chunks_ragflow,
)
from app.services.ragflow_client import RagflowError


@pytest.fixture(autouse=True)
def _skip_dataset_embedding_repair(monkeypatch):
    """These retrieval payload tests do not exercise dataset repair."""
    monkeypatch.setattr(
        "app.services.knowledge_retrieval_service._ensure_ragflow_dataset_embeddings",
        lambda client, dataset_ids: None,
    )


def test_rejects_below_threshold():
    assert not _passes_recall_threshold(
        0.15,
        similarity_threshold=0.2,
    )


def test_accepts_at_or_above_threshold():
    assert _passes_recall_threshold(
        0.42,
        similarity_threshold=0.2,
    )


def test_threshold_zero_passes_any_positive_similarity():
    assert _passes_recall_threshold(
        0.01,
        similarity_threshold=0.0,
    )


def test_ragflow_rerank_provider_error_retries_without_reranker(monkeypatch):
    calls = []

    class FakeRagflowClient:
        def retrieve(self, payload):
            calls.append(payload)
            if len(calls) == 1:
                raise RagflowError("LookupError('Provider  not found for model gte-rerank.')")
            return {"chunks": [], "doc_aggs": [], "total": 0}

    monkeypatch.setattr(
        "app.services.knowledge_retrieval_service.get_ragflow_client",
        lambda: FakeRagflowClient(),
    )

    result = _retrieve_chunks_ragflow(
        RetrievalRequest(
            question="贸易战",
            dataset_ids=["kb-demo"],
            rerank_id="gte-rerank",
        )
    )

    assert result["chunks"] == []
    assert result["doc_aggs"] == []
    assert result["total"] == 0
    assert result["rerank_applied"] is False
    assert "不可用" in result["rerank_warning"]
    assert calls[0]["rerank_id"] == "gte-rerank"
    assert "rerank_id" not in calls[1]


def test_ragflow_rerank_score_is_preserved(monkeypatch):
    class FakeRagflowClient:
        def retrieve(self, payload):
            return {
                "chunks": [
                    {
                        "id": "chunk-1",
                        "content": "贸易战内容",
                        "document_id": "doc-1",
                        "document_keyword": "贸易战.docx",
                        "dataset_id": "kb-demo",
                        "similarity": 0.42,
                        "term_similarity": 0.3,
                        "vector_similarity": 0.7,
                        "rerank_score": 0.91,
                    }
                ],
                "doc_aggs": [],
                "total": 1,
            }

    monkeypatch.setattr(
        "app.services.knowledge_retrieval_service.get_ragflow_client",
        lambda: FakeRagflowClient(),
    )

    result = _retrieve_chunks_ragflow(
        RetrievalRequest(
            question="贸易战",
            dataset_ids=["kb-demo"],
            rerank_id="BAAI/gte-rerank",
        )
    )

    assert result["rerank_applied"] is True
    assert result["rerank_warning"] is None
    assert result["chunks"][0]["similarity"] == 0.42
    assert result["chunks"][0]["rerank_score"] == 0.91


@pytest.mark.parametrize("keyword,use_kg", [(False, False), (True, True)])
def test_ragflow_retrieval_preserves_optional_search_choices(
    monkeypatch, keyword, use_kg
):
    calls = []

    class FakeRagflowClient:
        def retrieve(self, payload):
            calls.append(payload)
            return {"chunks": [], "doc_aggs": [], "total": 0}

    monkeypatch.setattr(
        "app.services.knowledge_retrieval_service.get_ragflow_client",
        lambda: FakeRagflowClient(),
    )

    _retrieve_chunks_ragflow(
        RetrievalRequest(
            question="贸易战",
            dataset_ids=["kb-demo"],
            keyword=keyword,
            use_kg=use_kg,
        )
    )

    assert calls[0]["keyword"] is keyword
    assert calls[0]["use_kg"] is use_kg
