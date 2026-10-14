"""Tests for the file-based knowledge base API."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def knowledge_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.core.config import settings

    root = tmp_path / "knowledge_storage"
    monkeypatch.setattr(settings, "knowledge_storage_path", str(root))
    return root


@pytest.mark.asyncio
async def test_knowledge_crud(client, knowledge_storage: Path) -> None:
    create = await client.post(
        "/v1/knowledge",
        json={
            "name": "测试库",
            "description": "demo",
            "group": "测试",
            "chunk_method": "naive",
            "embedding_model": "bge-large@local",
        },
    )
    assert create.status_code == 201
    body = create.json()
    assert body["code"] == 0
    kb_id = body["data"]["id"]
    assert body["data"]["name"] == "测试库"
    assert body["data"]["chunk_method"] == "naive"

    listed = await client.get("/v1/knowledge")
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1

    detail = await client.get(f"/v1/knowledge/{kb_id}")
    assert detail.status_code == 200
    assert detail.json()["data"]["files"] == []

    upload = await client.post(
        f"/v1/knowledge/{kb_id}/files",
        files={"file": ("note.md", b"# hello\n\nworld", "text/markdown")},
    )
    assert upload.status_code == 201
    assert upload.json()["data"]["parsed"] is True

    deleted = await client.delete(f"/v1/knowledge/{kb_id}")
    assert deleted.status_code == 200

    missing = await client.get(f"/v1/knowledge/{kb_id}")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_parse_documents(client, knowledge_storage: Path) -> None:
    create = await client.post(
        "/v1/knowledge",
        json={"name": "解析测试", "group": "测试", "chunk_method": "naive"},
    )
    assert create.status_code == 201
    kb_id = create.json()["data"]["id"]

    upload = await client.post(
        f"/v1/knowledge/{kb_id}/files",
        files={"file": ("note.md", b"# hello\n\nworld", "text/markdown")},
    )
    assert upload.status_code == 201
    doc_id = upload.json()["data"]["id"]

    empty = await client.post(
        f"/v1/datasets/{kb_id}/chunks",
        json={"document_ids": []},
    )
    assert empty.status_code == 200
    assert empty.json() == {"code": 102, "message": "`document_ids` is required"}

    parsed = await client.post(
        f"/v1/datasets/{kb_id}/chunks",
        json={"document_ids": [doc_id]},
    )
    assert parsed.status_code == 200
    assert parsed.json() == {"code": 0}

    detail = await client.get(f"/v1/knowledge/{kb_id}")
    assert detail.json()["data"]["status"] == "success"
    assert detail.json()["data"]["files"][0]["parsed"] is True

    missing_doc = await client.post(
        f"/v1/datasets/{kb_id}/chunks",
        json={"document_ids": ["nonexistent_doc_id"]},
    )
    assert missing_doc.status_code == 404

    missing_kb = await client.post(
        "/v1/datasets/no-such-kb/chunks",
        json={"document_ids": [doc_id]},
    )
    assert missing_kb.status_code == 404


@pytest.mark.asyncio
async def test_knowledge_deploy_route_accepts_post(client, monkeypatch) -> None:
    """POST deploy endpoints must not return 405."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ragflow_base_url", "http://ragflow.test:8513")
    monkeypatch.setattr(settings, "ragflow_api_key", "test-key")

    for path in ("/v1/knowledge-deploy", "/v1/rag/deploy", "/v1/knowledge/deploy"):
        resp = await client.post(
            path,
            json={"knowledge_ids": ["kb-demo"], "instance_ids": ["no-such-instance"]},
            headers={"Accept": "text/event-stream", "X-Tenant-ID": "default"},
        )
        assert resp.status_code != 405, f"{path}: {resp.text}"
    assert resp.status_code == 404
