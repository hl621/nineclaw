from typing import Any

from app.services.ragflow_client import RagflowClient


class DummyRagflowClient(RagflowClient):
    def __init__(self) -> None:
        super().__init__("http://ragflow.test", "test-key")
        self.requests: list[dict[str, Any]] = []

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        data: Any = None,
        files: Any = None,
        expect_json: bool = True,
        timeout: float | None = None,
    ) -> Any:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json": json,
                "timeout": timeout,
            }
        )
        page = int((params or {}).get("page", 1))
        if path == "/datasets":
            if page == 1:
                return [{"id": f"dataset-{i}"} for i in range(100)]
            if page == 2:
                return [{"id": "dataset-100"}]
            return []
        if path.endswith("/documents"):
            if page == 1:
                return {"docs": [{"id": f"doc-{i}"} for i in range(100)]}
            if page == 2:
                return {"docs": [{"id": "doc-100"}]}
            return {"docs": []}
        return []


def test_list_datasets_clamps_page_size_to_ragflow_limit() -> None:
    client = DummyRagflowClient()

    client.list_datasets(page_size=500)

    assert client.requests[-1]["params"]["page_size"] == 100


def test_list_all_datasets_paginates_with_ragflow_limit() -> None:
    client = DummyRagflowClient()

    items = client.list_all_datasets(page_size=500)

    assert len(items) == 101
    assert [req["params"]["page_size"] for req in client.requests] == [100, 100]
    assert [req["params"]["page"] for req in client.requests] == [1, 2]


def test_list_all_documents_paginates_with_ragflow_limit() -> None:
    client = DummyRagflowClient()

    items = client.list_all_documents("dataset-1", page_size=500)

    assert len(items) == 101
    assert [req["params"]["page_size"] for req in client.requests] == [100, 100]
    assert [req["params"]["page"] for req in client.requests] == [1, 2]


def test_retrieve_uses_public_api_with_bounded_timeout() -> None:
    client = DummyRagflowClient()
    body = {"question": "test", "dataset_ids": ["dataset-1"]}

    client.retrieve(body)

    assert client.requests[-1] == {
        "method": "POST",
        "path": "/retrieval",
        "params": None,
        "json": body,
        "timeout": 14.0,
    }
