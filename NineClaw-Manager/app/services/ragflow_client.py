"""HTTP client for RAGFlow ``/api/v1`` REST API."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx


logger = logging.getLogger(__name__)

MAX_RAGFLOW_PAGE_SIZE = 100
MAX_RAGFLOW_LIST_PAGES = 1000
# Return an upstream error before WebUI's 15-second request deadline.  This also
# releases the RAGFlow bulkhead slot instead of leaving an abandoned 120-second
# HTTP request running after the browser has already given up.
RAGFLOW_RETRIEVAL_TIMEOUT_SECONDS = 14.0


def _normalize_page_size(page_size: int) -> int:
    return max(1, min(MAX_RAGFLOW_PAGE_SIZE, int(page_size)))


class RagflowError(Exception):
    """Raised when RAGFlow returns a non-zero code or HTTP error."""

    def __init__(self, message: str, *, status_code: int = 502, code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class RagflowClient:
    """Thin synchronous wrapper around RAGFlow HTTP API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        if not self.api_key:
            raise RagflowError(
                "未配置 RAGFlow API Key，请在知识库设置中填写",
                status_code=500,
            )

    def _sync_client(self, *, timeout: float | None = None) -> httpx.Client:
        # 内网 RAGFlow 不应走系统 HTTP_PROXY，否则常见 502
        return httpx.Client(
            timeout=self.timeout if timeout is None else timeout,
            trust_env=False,
        )

    @property
    def api_prefix(self) -> str:
        return f"{self.base_url}/api/v1"

    def _headers(self, *, json_body: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

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
        url = f"{self.api_prefix}{path}"
        try:
            with self._sync_client(timeout=timeout) as client:
                resp = client.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    data=data,
                    files=files,
                    headers=self._headers(json_body=json is not None and files is None),
                )
        except httpx.RequestError as exc:
            logger.exception("RAGFlow request failed: %s %s", method, url)
            raise RagflowError(f"无法连接 RAGFlow：{exc}", status_code=502) from exc

        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise RagflowError(
                f"RAGFlow HTTP {resp.status_code}：{detail}",
                status_code=resp.status_code,
            )

        if not expect_json or resp.status_code == 204:
            return resp.content

        payload = resp.json()
        if isinstance(payload, dict) and payload.get("code", 0) != 0:
            raise RagflowError(
                str(payload.get("message") or "RAGFlow 请求失败"),
                status_code=502,
                code=int(payload.get("code", 0)),
            )
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    def get_document_image(self, image_id: str) -> tuple[bytes, str]:
        """Fetch one chunk image (``GET /documents/images/<image_id>``).

        Returns ``(bytes, content_type)``. image_id 形如 ``{dataset_id}-{object_key}``，
        由 RAGFlow 切片 ``image_id`` 字段原样透传。
        """

        url = f"{self.api_prefix}/documents/images/{quote(image_id, safe='')}"
        try:
            with self._sync_client(timeout=30.0) as client:
                resp = client.get(url, headers=self._headers(json_body=False))
        except httpx.RequestError as exc:
            logger.exception("RAGFlow image request failed: GET %s", url)
            raise RagflowError(f"无法连接 RAGFlow：{exc}", status_code=502) from exc

        if resp.status_code >= 400:
            raise RagflowError(
                f"RAGFlow HTTP {resp.status_code}", status_code=resp.status_code
            )
        content_type = (
            resp.headers.get("Content-Type", "application/octet-stream")
            .split(";")[0]
            .strip()
            or "application/octet-stream"
        )
        return resp.content, content_type

    def list_datasets(self, *, page: int = 1, page_size: int = 100) -> list[dict[str, Any]]:
        page_size = _normalize_page_size(page_size)
        data = self._request(
            "GET",
            "/datasets",
            params={"page": page, "page_size": page_size},
        )
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("datasets", "items", "kbs", "data", "docs"):
                nested = data.get(key)
                if isinstance(nested, list):
                    return [item for item in nested if isinstance(item, dict)]
            if "id" in data:
                return [data]
        return []

    def list_all_datasets(self, *, page_size: int = 100) -> list[dict[str, Any]]:
        page_size = _normalize_page_size(page_size)
        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for page in range(1, MAX_RAGFLOW_LIST_PAGES + 1):
            page_items = self.list_datasets(page=page, page_size=page_size)
            if not page_items:
                break
            for item in page_items:
                item_id = str(item.get("id") or "")
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                items.append(item)
            if len(page_items) < page_size:
                break
        return items

    def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Fetch one dataset by id (direct GET, query filter, or list scan)."""
        last_error: RagflowError | None = None
        for path, params in (
            (f"/datasets/{dataset_id}", None),
            ("/datasets", {"id": dataset_id, "page": 1, "page_size": 1}),
        ):
            try:
                data = self._request("GET", path, params=params)
            except RagflowError as exc:
                last_error = exc
                continue
            if isinstance(data, dict):
                if str(data.get("id", "")) == dataset_id:
                    return data
                for key in ("datasets", "items", "kbs", "data"):
                    nested = data.get(key)
                    if isinstance(nested, list):
                        for item in nested:
                            if isinstance(item, dict) and str(item.get("id")) == dataset_id:
                                return item
                if "id" in data and not data.get("datasets"):
                    return data
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and str(item.get("id")) == dataset_id:
                        return item
                if len(data) == 1 and isinstance(data[0], dict):
                    return data[0]

        for ds in self.list_all_datasets():
            if str(ds.get("id")) == dataset_id:
                return ds

        if last_error and last_error.status_code not in (404,):
            raise last_error
        raise RagflowError("数据集不存在", status_code=404)

    def create_dataset(self, body: dict[str, Any]) -> dict[str, Any]:
        data = self._request("POST", "/datasets", json=body)
        if isinstance(data, dict):
            return data
        raise RagflowError("创建数据集失败：响应格式异常", status_code=502)

    def update_dataset(self, dataset_id: str, body: dict[str, Any]) -> dict[str, Any]:
        data = self._request("PUT", f"/datasets/{dataset_id}", json=body)
        if isinstance(data, dict):
            return data
        return self.get_dataset(dataset_id)

    def get_user_models(self) -> dict[str, Any]:
        data = self._request("GET", "/users/me/models")
        if isinstance(data, dict):
            return data
        return {}

    def delete_datasets(self, dataset_ids: list[str]) -> None:
        self._request("DELETE", "/datasets", json={"ids": dataset_ids})

    def list_documents(
        self,
        dataset_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
        keywords: str | None = None,
    ) -> list[dict[str, Any]]:
        data = self.list_documents_page(
            dataset_id,
            page=page,
            page_size=page_size,
            keywords=keywords,
        )
        return data["docs"]

    def list_documents_page(
        self,
        dataset_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
        keywords: str | None = None,
    ) -> dict[str, Any]:
        page_size = _normalize_page_size(page_size)
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if keywords:
            params["keywords"] = keywords
        data = self._request(
            "GET",
            f"/datasets/{dataset_id}/documents",
            params=params,
        )
        docs: list[dict[str, Any]] = []
        total = 0
        if isinstance(data, dict) and isinstance(data.get("docs"), list):
            docs = [item for item in data["docs"] if isinstance(item, dict)]
            total = int(
                data.get("total")
                or data.get("total_docs")
                or data.get("total_documents")
                or data.get("total_datasets")
                or len(docs)
            )
        elif isinstance(data, list):
            docs = [item for item in data if isinstance(item, dict)]
            total = len(docs)
        return {"docs": docs, "total": total}

    def list_all_documents(
        self,
        dataset_id: str,
        *,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        page_size = _normalize_page_size(page_size)
        items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for page in range(1, MAX_RAGFLOW_LIST_PAGES + 1):
            page_items = self.list_documents(dataset_id, page=page, page_size=page_size)
            if not page_items:
                break
            for item in page_items:
                item_id = str(item.get("id") or "")
                if item_id and item_id in seen_ids:
                    continue
                if item_id:
                    seen_ids.add(item_id)
                items.append(item)
            if len(page_items) < page_size:
                break
        return items

    def upload_documents(
        self,
        dataset_id: str,
        files: list[tuple[str, bytes]],
    ) -> list[dict[str, Any]]:
        if not files:
            return []
        multipart: list[tuple[str, tuple[str, bytes, str]]] = []
        for filename, content in files:
            multipart.append(("file", (filename, content, "application/octet-stream")))
        url = f"{self.api_prefix}/datasets/{dataset_id}/documents"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            with self._sync_client() as client:
                resp = client.post(url, files=multipart, headers=headers)
        except httpx.RequestError as exc:
            raise RagflowError(f"无法连接 RAGFlow：{exc}", status_code=502) from exc
        if resp.status_code >= 400:
            raise RagflowError(
                f"RAGFlow HTTP {resp.status_code}：{resp.text[:500]}",
                status_code=resp.status_code,
            )
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("code", 0) != 0:
            raise RagflowError(str(payload.get("message") or "上传失败"))
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("docs", "documents", "data"):
                if isinstance(data.get(key), list):
                    return data[key]
            if "id" in data:
                return [data]
        return []

    def delete_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        self._request(
            "DELETE",
            f"/datasets/{dataset_id}/documents",
            json={"ids": document_ids},
        )

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        self._request(
            "POST",
            f"/datasets/{dataset_id}/chunks",
            json={"document_ids": document_ids},
        )

    def update_document(
        self,
        dataset_id: str,
        document_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Update document config (chunk_method / parser_config / name)."""
        last_error: RagflowError | None = None
        for method in ("PUT", "PATCH"):
            try:
                data = self._request(
                    method,
                    f"/datasets/{dataset_id}/documents/{document_id}",
                    json=body,
                )
                if isinstance(data, dict):
                    return data
                return {}
            except RagflowError as exc:
                last_error = exc
                # 部分版本仅支持 PUT 或仅支持 PATCH
                if exc.status_code not in (404, 405):
                    raise
        if last_error:
            raise last_error
        return {}

    def add_document_chunk(
        self,
        dataset_id: str,
        document_id: str,
        content: str,
        *,
        important_keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"content": content}
        if important_keywords:
            body["important_keywords"] = important_keywords
        data = self._request(
            "POST",
            f"/datasets/{dataset_id}/documents/{document_id}/chunks",
            json=body,
        )
        if isinstance(data, dict):
            return data
        return {}

    @staticmethod
    def _raise_if_asr_error_text(text: str) -> str:
        """RAGFlow ASR providers often return ``**ERROR**: …`` as fake success text."""
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        upper = cleaned.upper()
        if upper.startswith("**ERROR**") or upper.startswith("ERROR:"):
            detail = cleaned
            for prefix in ("**ERROR**:", "**ERROR**", "ERROR:"):
                if cleaned.upper().startswith(prefix.upper()):
                    detail = cleaned[len(prefix) :].strip(" :-")
                    break
            raise RagflowError(
                f"RAGFlow 默认 ASR 转写失败：{detail or cleaned}。"
                "请在 RAGFlow「模型设置」检查 ASR；部分音频格式/时长可能导致空响应。",
                status_code=502,
            )
        return cleaned

    def transcribe_audio(
        self,
        filename: str,
        content: bytes,
        *,
        stream: bool = False,
    ) -> str:
        """Call RAGFlow tenant default ASR: POST /chat/audio/transcription."""
        url = f"{self.api_prefix}/chat/audio/transcription"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        mime = "application/octet-stream"
        lower = filename.lower()
        if lower.endswith(".wav"):
            mime = "audio/wav"
        elif lower.endswith(".mp3"):
            mime = "audio/mpeg"
        elif lower.endswith(".m4a"):
            mime = "audio/mp4"
        elif lower.endswith(".webm"):
            mime = "audio/webm"
        elif lower.endswith(".ogg"):
            mime = "audio/ogg"
        elif lower.endswith(".flac"):
            mime = "audio/flac"
        elif lower.endswith(".aac"):
            mime = "audio/aac"
        files = {"file": (filename, content, mime)}
        data = {"stream": "true" if stream else "false"}
        # 长音频 ASR 可能远超普通 API 超时
        try:
            with httpx.Client(timeout=600.0, trust_env=False) as client:
                resp = client.post(url, headers=headers, files=files, data=data)
        except httpx.TimeoutException as exc:
            raise RagflowError(
                "RAGFlow ASR 转写超时（文件可能过长）。请稍后重试或换较短音频。",
                status_code=504,
            ) from exc
        except httpx.RequestError as exc:
            raise RagflowError(f"无法连接 RAGFlow：{exc}", status_code=502) from exc
        if resp.status_code >= 400:
            raise RagflowError(
                f"RAGFlow 转写失败 HTTP {resp.status_code}：{resp.text[:500]}",
                status_code=resp.status_code,
            )
        # 部分版本流式返回 SSE
        content_type = (resp.headers.get("content-type") or "").lower()
        if "text/event-stream" in content_type or (
            isinstance(resp.text, str) and resp.text.lstrip().startswith("data:")
        ):
            texts: list[str] = []
            for line in resp.text.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    import json as _json

                    evt = _json.loads(raw)
                except Exception:
                    continue
                if isinstance(evt, dict):
                    piece = evt.get("text") or evt.get("content") or ""
                    if piece:
                        texts.append(str(piece))
            return self._raise_if_asr_error_text("".join(texts).strip())
        try:
            payload = resp.json()
        except Exception as exc:
            raise RagflowError(
                f"RAGFlow 转写返回非 JSON：{resp.text[:300]}",
                status_code=502,
            ) from exc
        if isinstance(payload, dict) and payload.get("code", 0) != 0:
            raise RagflowError(
                str(payload.get("message") or "RAGFlow 转写失败"),
                status_code=502,
                code=int(payload.get("code", 0)),
            )
        data_obj = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data_obj, dict):
            text = data_obj.get("text") or data_obj.get("content") or ""
            return self._raise_if_asr_error_text(str(text).strip())
        if isinstance(data_obj, str):
            return self._raise_if_asr_error_text(data_obj.strip())
        return ""

    def retrieve(self, body: dict[str, Any]) -> dict[str, Any]:
        data = self._request(
            "POST",
            "/retrieval",
            json=body,
            timeout=RAGFLOW_RETRIEVAL_TIMEOUT_SECONDS,
        )
        if isinstance(data, dict):
            return data
        return {"chunks": [], "doc_aggs": [], "total": 0}

    def list_document_chunks(
        self,
        dataset_id: str,
        document_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        page_size = _normalize_page_size(page_size)
        return self._request(
            "GET",
            f"/datasets/{dataset_id}/documents/{document_id}/chunks",
            params={"page": page, "page_size": page_size},
        )

    def update_document_chunk(
        self,
        dataset_id: str,
        document_id: str,
        chunk_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._request(
            "PATCH",
            f"/datasets/{dataset_id}/documents/{document_id}/chunks/{chunk_id}",
            json=body,
        )
        if isinstance(data, dict):
            return data
        return {}

    def switch_document_chunks(
        self,
        dataset_id: str,
        document_id: str,
        chunk_ids: list[str],
        *,
        available: bool,
    ) -> dict[str, Any]:
        data = self._request(
            "PATCH",
            f"/datasets/{dataset_id}/documents/{document_id}/chunks",
            json={"chunk_ids": chunk_ids, "available": available},
        )
        if isinstance(data, dict):
            return data
        return {}

    def download_document(self, dataset_id: str, document_id: str) -> bytes:
        url = f"{self.api_prefix}/datasets/{dataset_id}/documents/{document_id}"
        try:
            with self._sync_client() as client:
                resp = client.get(url, headers=self._headers(json_body=False))
        except httpx.RequestError as exc:
            raise RagflowError(f"无法下载文档：{exc}", status_code=502) from exc
        if resp.status_code >= 400:
            raise RagflowError(
                f"下载文档失败 HTTP {resp.status_code}",
                status_code=resp.status_code,
            )
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("code", 0) != 0:
                raise RagflowError(str(payload.get("message") or "下载失败"))
            raise RagflowError("RAGFlow 未返回文件内容，请使用切片预览", status_code=400)
        return resp.content


_client: RagflowClient | None = None


def set_ragflow_client(client: RagflowClient) -> None:
    global _client
    _client = client


def get_ragflow_client() -> RagflowClient:
    if _client is None:
        raise RagflowError("RAGFlow 客户端未初始化，请先配置知识库后端", status_code=500)
    return _client
