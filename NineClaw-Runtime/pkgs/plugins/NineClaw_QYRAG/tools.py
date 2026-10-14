"""Tool handlers for the NineClaw-QYRAG plugin."""

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

DEFAULT_BASE_URL = "http://172.18.33.24:8513"
DEFAULT_OUTPUT_DIR = "qyrag_downloads"
CONTEXT_MIN_STRONG_REFS = 2
CONTEXT_MIN_COVERAGE = 0.6
QYRAG_API_KEY_ENV_NAMES = ("QYRAG_API_KEY", "RAGFLOW_API_KEY")
_LAST_RETRIEVAL: dict = {}


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _env_paths() -> list[Path]:
    paths: list[Path] = []
    override = os.environ.get("QYRAG_ENV_FILE", "").strip()
    if override:
        paths.append(Path(os.path.expanduser(override)))
    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        paths.append(Path(os.path.expanduser(hermes_home)) / ".env")
    config_path = os.environ.get("HERMES_CONFIG_PATH", "").strip()
    if config_path:
        paths.append(Path(os.path.expanduser(config_path)).parent / ".env")
    paths.append(Path(os.path.expanduser("~/.hermes/.env")))
    paths.append(Path("/opt/data/.env"))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def _load_env_file(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key:
                loaded[key] = _strip_env_value(value)
    except OSError:
        return {}
    return loaded


def _load_runtime_env() -> dict[str, str]:
    loaded: dict[str, str] = {}
    for path in reversed(_env_paths()):
        loaded.update(_load_env_file(path))
    return loaded


def _load_runtime_env_file() -> None:
    """Import runtime .env values into os.environ, matching WebSearch behavior."""
    for key, value in _load_runtime_env().items():
        os.environ.setdefault(key, value)


_load_runtime_env_file()


def _setting(name: str, default: str = "") -> str:
    file_value = _load_runtime_env().get(name)
    if file_value is not None and file_value.strip():
        return file_value.strip()
    value = os.environ.get(name)
    if value is not None and value.strip():
        return value.strip()
    return default.strip()


def _base_url() -> str:
    return (_setting("QYRAG_BASE_URL") or _setting("RAGFLOW_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")


def _max_retries_hint() -> str:
    return _setting("QYRAG_MAX_RETRIES_HINT", "3")

def _selected_dataset_args() -> dict:
    raw = _setting("QYRAG_SELECTED_DATASETS").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return {"dataset_ids": [str(item) for item in value]}
        if isinstance(value, dict):
            return {"dataset_ids": [str(item) for item in value.values()]}
    except json.JSONDecodeError:
        pass
    if "=" in raw:
        return {"dataset_names": [part.split("=", 1)[0].strip() for part in raw.split(",") if "=" in part]}
    return {"dataset_ids": [item.strip() for item in raw.split(",") if item.strip()]}

def _answer_dataset_args(args: dict) -> dict:
    if args.get("dataset_ids") or args.get("dataset_names"):
        return args
    selected = _selected_dataset_args()
    return {**args, **selected} if selected else args


def _auth_headers(api_key: str, *, json_body: bool = True) -> dict[str, str]:
    """构造携带 QYRAG Bearer 凭据的请求头。"""
    headers = {"Accept": "application/json"}
    key = (api_key or "").strip()
    if key:
        if key.lower().startswith("bearer "):
            headers["Authorization"] = key
        else:
            headers["Authorization"] = f"Bearer {key}"
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _request(method: str, url: str, headers: dict, timeout: int, **kwargs) -> requests.Response:
    """Send one request and preserve Authorization across one redirect."""
    resp = requests.request(
        method,
        url,
        headers=headers,
        timeout=timeout,
        allow_redirects=False,
        **kwargs,
    )
    if resp.is_redirect and resp.headers.get("Location"):
        resp = requests.request(
            method,
            urljoin(url, resp.headers["Location"]),
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
            **kwargs,
        )
    return resp


def _api_key_from_args(args: dict) -> str:
    """优先使用调用参数，否则读取实例持久化环境中的 QYRAG 凭据。"""
    explicit = str(args.get("api_key") or "").strip()
    if explicit:
        return explicit
    for name in QYRAG_API_KEY_ENV_NAMES:
        value = _setting(name)
        if value:
            return value
    return ""


def _missing_api_key_yaml() -> str:
    """返回实例缺少 QYRAG 服务凭据时的安全错误。"""
    return _yaml_error(
        "未配置 QYRAG_API_KEY 或 RAGFLOW_API_KEY，无法调用受保护的 QYRAG 服务。"
    )


def _post(url: str, headers: dict, json_body: dict, timeout: int = 60) -> tuple[str, float]:
    """Make a POST request. Returns (json_string, elapsed_seconds)."""
    start = time.time()
    try:
        resp = _request("POST", url, headers, timeout, json=json_body)
        elapsed = time.time() - start
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.HTTPError as e:
        body = ""
        try:
            body = resp.text[:500]
        except Exception:
            pass
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": f"HTTP {resp.status_code}: {body or str(e)}"}), elapsed
    except requests.exceptions.ConnectionError:
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": f"Cannot connect to QYRAG at {url}"}), elapsed
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": f"Connection timeout to QYRAG at {url}"}), elapsed
    except requests.exceptions.RequestException as e:
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": f"Request failed: {e}"}), elapsed
    except json.JSONDecodeError:
        text = resp.text[:500] if hasattr(resp, "text") else ""
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": "Invalid JSON response from QYRAG", "raw": text}), elapsed

    api_code = result.get("code")
    if api_code is not None and api_code != 0:
        msg = result.get("message", result.get("msg", f"API error code {api_code}"))
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": msg}), elapsed

    elapsed = time.time() - start
    return json.dumps(result), elapsed


def _get(url: str, headers: dict, params: dict | None = None, timeout: int = 30) -> tuple[str, float]:
    """Make a GET request. Returns (json_string, elapsed_seconds)."""
    start = time.time()
    try:
        resp = _request("GET", url, headers, timeout, params=params)
        elapsed = time.time() - start
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.HTTPError as e:
        body = ""
        try:
            body = resp.text[:500]
        except Exception:
            pass
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": f"HTTP {resp.status_code}: {body or str(e)}"}), elapsed
    except requests.exceptions.ConnectionError:
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": f"Cannot connect to QYRAG at {url}"}), elapsed
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": f"Connection timeout to QYRAG at {url}"}), elapsed
    except requests.exceptions.RequestException as e:
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": f"Request failed: {e}"}), elapsed
    except json.JSONDecodeError:
        text = resp.text[:500] if hasattr(resp, "text") else ""
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": "Invalid JSON response from QYRAG", "raw": text}), elapsed

    api_code = result.get("code")
    if api_code is not None and api_code != 0:
        msg = result.get("message", result.get("msg", f"API error code {api_code}"))
        elapsed = time.time() - start
        return json.dumps({"success": False, "error": msg}), elapsed

    elapsed = time.time() - start
    return json.dumps(result), elapsed


def _download(url: str, headers: dict, timeout: int = 120) -> tuple[bytes | None, dict]:
    """Download binary content. Returns (content, metadata)."""
    try:
        resp = _request("GET", url, headers, timeout)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        body = ""
        try:
            body = resp.text[:500]
        except Exception:
            pass
        return None, {"success": False, "error": f"HTTP {resp.status_code}: {body or str(e)}"}
    except requests.exceptions.ConnectionError:
        return None, {"success": False, "error": f"Cannot connect to QYRAG at {url}"}
    except requests.exceptions.Timeout:
        return None, {"success": False, "error": f"Connection timeout to QYRAG at {url}"}
    except requests.exceptions.RequestException as e:
        return None, {"success": False, "error": f"Request failed: {e}"}

    return resp.content, {
        "success": True,
        "content_type": resp.headers.get("Content-Type", ""),
        "content_disposition": resp.headers.get("Content-Disposition", ""),
    }


def _parse_allowed_datasets() -> dict[str, str]:
    """Parse QYRAG_DATASETS as name->id allowlist."""
    raw = _setting("QYRAG_DATASETS").strip()
    # Accept dotenv values such as "{\"name\": \"id\"}" after the outer quotes are stripped.
    raw = raw.replace(chr(92) + chr(34), chr(34))
    if not raw:
        return {}

    def add_dataset(parsed: dict[str, str], name: str, dataset_id: str) -> None:
        name = str(name).strip()
        dataset_id = str(dataset_id).strip()
        if not dataset_id:
            return
        if not name:
            name = dataset_id
        if name in parsed and parsed[name] != dataset_id:
            name = f"{name} ({dataset_id})"
        parsed[name] = dataset_id

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            parsed = {}
            for key, value in data.items():
                add_dataset(parsed, str(key), str(value))
            return parsed
        if isinstance(data, list):
            parsed = {}
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name", "")).strip()
                dataset_id = str(item.get("id", item.get("dataset_id", ""))).strip()
                add_dataset(parsed, name, dataset_id)
            return parsed
    except json.JSONDecodeError:
        pass

    parsed = {}
    for part in raw.split(","):
        if "=" not in part:
            continue
        name, dataset_id = part.split("=", 1)
        add_dataset(parsed, name, dataset_id)
    return parsed


def _allowed_dataset_ids() -> set[str]:
    return set(_parse_allowed_datasets().values())


def _resolve_dataset_ids(args: dict) -> list[str] | None:
    configured = _parse_allowed_datasets()
    allowed_ids = set(configured.values())
    resolved = []

    dataset_names = args.get("dataset_names") or []
    if dataset_names:
        missing = [name for name in dataset_names if name not in configured]
        if missing:
            raise ValueError(f"Dataset name is not authorized by QYRAG_DATASETS: {', '.join(missing)}")
        resolved.extend(configured[name] for name in dataset_names)

    dataset_ids = args.get("dataset_ids") or []
    resolved.extend(str(dataset_id) for dataset_id in dataset_ids)

    if allowed_ids:
        if not resolved:
            resolved = list(allowed_ids)
        blocked = [dataset_id for dataset_id in resolved if dataset_id not in allowed_ids]
        if blocked:
            raise ValueError(f"Dataset id is not authorized by QYRAG_DATASETS: {', '.join(blocked)}")

    if not resolved:
        return None
    return list(dict.fromkeys(resolved))


def _validate_dataset_id(dataset_id: str) -> None:
    allowed_ids = _allowed_dataset_ids()
    if allowed_ids and dataset_id not in allowed_ids:
        raise ValueError(f"Dataset id is not authorized by QYRAG_DATASETS: {dataset_id}")


def _build_payload(args: dict) -> dict:
    """Build the QYRAG API payload from args, excluding defaults."""
    payload = {"question": args.get("question", "")}

    dataset_ids = _resolve_dataset_ids(args)
    if dataset_ids is not None:
        payload["dataset_ids"] = dataset_ids

    document_ids = args.get("document_ids")
    if document_ids is not None:
        payload["document_ids"] = document_ids

    if args.get("page", 1) != 1:
        payload["page"] = args["page"]
    if args.get("page_size", 10) != 10:
        payload["page_size"] = args["page_size"]
    if args.get("similarity_threshold", 0.2) != 0.2:
        payload["similarity_threshold"] = args["similarity_threshold"]
    if args.get("vector_similarity_weight") is not None:
        payload["vector_similarity_weight"] = args["vector_similarity_weight"]
    if args.get("top_k", 1024) != 1024:
        payload["top_k"] = args["top_k"]
    if args.get("rerank_id") is not None:
        payload["rerank_id"] = args["rerank_id"]
    # 固定关闭关键词混合检索，避免调用方改变检索模式。
    payload["keyword"] = False
    if args.get("highlight"):
        payload["highlight"] = True
    if args.get("cross_languages") is not None:
        payload["cross_languages"] = args["cross_languages"]
    if args.get("metadata_condition") is not None:
        payload["metadata_condition"] = args["metadata_condition"]
    # 固定关闭知识图谱增强检索。
    payload["use_kg"] = False
    if args.get("toc_enhance"):
        payload["toc_enhance"] = True

    return payload


def _chunk_id(chunk: dict) -> str:
    return str(chunk.get("id") or chunk.get("chunk_id") or "")


def _dataset_id(chunk: dict) -> str:
    return str(chunk.get("kb_id") or chunk.get("dataset_id") or "")


def _document_id(chunk: dict) -> str:
    return str(chunk.get("document_id") or chunk.get("doc_id") or "")


def _document_name(chunk: dict) -> str:
    return str(chunk.get("document_keyword") or chunk.get("doc_name") or "")


def _nested_value(data: dict, path: str) -> object:
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _time_clues(item: dict) -> list[dict]:
    """Extract available temporal clues without claiming they are content dates."""
    fields = [
        ("metadata.publish_date", "metadata_publish_date"),
        ("metadata.published_at", "metadata_published_at"),
        ("metadata.publish_time", "metadata_publish_time"),
        ("metadata.source_date", "metadata_source_date"),
        ("metadata.event_date", "metadata_event_date"),
        ("metadata.date", "metadata_date"),
        ("metadata.year", "metadata_year"),
        ("doc.publish_date", "doc_publish_date"),
        ("doc.published_at", "doc_published_at"),
        ("doc.source_date", "doc_source_date"),
        ("doc.create_time", "doc_create_time"),
        ("doc.update_time", "doc_update_time"),
        ("doc.create_timestamp", "doc_create_timestamp"),
        ("doc.update_timestamp", "doc_update_timestamp"),
        ("create_time", "chunk_create_time"),
        ("update_time", "chunk_update_time"),
        ("create_timestamp", "chunk_create_timestamp"),
        ("update_timestamp", "chunk_update_timestamp"),
    ]

    clues = []
    seen = set()
    for path, source in fields:
        value = _nested_value(item, path)
        if value in (None, ""):
            continue
        key = (source, str(value))
        if key in seen:
            continue
        seen.add(key)
        clues.append({"source": source, "value": str(value)})
    return clues


def _yaml_scalar(value: object) -> str:
    text = "" if value is None else str(value)
    if text == "":
        return '""'
    if any(ch in text for ch in [":", "#", "{", "}", "[", "]", ",", "&", "*", "!", "|", ">", "'", '"', "%", "@", "`"]):
        return json.dumps(text, ensure_ascii=False)
    if text.strip() != text or "\n" in text:
        return json.dumps(text, ensure_ascii=False)
    return text


def _append_block(lines: list[str], key: str, value: str, indent: int = 0) -> None:
    pad = " " * indent
    lines.append(f"{pad}{key}: |")
    content = (value or "").strip()
    if not content:
        lines.append(f"{pad}  ")
        return
    for line in content.splitlines():
        lines.append(f"{pad}  {line}")


def _append_time_clues(lines: list[str], item: dict, indent: int = 0) -> None:
    pad = " " * indent
    clues = _time_clues(item)
    lines.append(f"{pad}time_clues:")
    if not clues:
        lines.append(f"{pad}  []")
        return
    for clue in clues:
        lines.append(f"{pad}  - source: {_yaml_scalar(clue['source'])}")
        lines.append(f"{pad}    value: {_yaml_scalar(clue['value'])}")


def _yaml_error(message: str) -> str:
    return "\n".join([
        "status: error",
        f"error: {_yaml_scalar(message)}",
    ])


def _yaml_permission_error(message: str) -> str:
    return "\n".join([
        "status: permission_denied",
        f"error: {_yaml_scalar(message)}",
        "reason: dataset is outside QYRAG_DATASETS allowlist",
        "next_action: ask for authorization to access this knowledge base, or choose an already authorized dataset",
    ])


def _format_retrieve_yaml(question: str, sub_queries: list[str], chunks: list[dict]) -> str:
    lines = [
        "status: retrieved" if chunks else "status: no_hits",
        f"query: {_yaml_scalar(question)}",
    ]

    if sub_queries and sub_queries != [question]:
        lines.append("searched_queries:")
        for query in sub_queries:
            lines.append(f"  - {_yaml_scalar(query)}")

    lines.append("retrieved_chunks:")
    if not chunks:
        lines.append("  []")
        lines.append("notes:")
        lines.append(f"  - 未召回可用片段；可换关键词最多约{_max_retries_hint()}次，仍无证据就停止并说明知识库未找到答案。")
        return "\n".join(lines)

    for idx, chunk in enumerate(chunks, 1):
        lines.append(f"  - rank: {idx}")
        lines.append(f"    chunk_id: {_yaml_scalar(_chunk_id(chunk))}")
        lines.append(f"    doc_id: {_yaml_scalar(_document_id(chunk))}")
        lines.append(f"    dataset_id: {_yaml_scalar(_dataset_id(chunk))}")
        lines.append(f"    doc_name: {_yaml_scalar(_document_name(chunk))}")
        _append_time_clues(lines, chunk, indent=4)
        _append_block(lines, "content", chunk.get("content", ""), indent=4)

    lines.append("notes:")
    lines.append("  - rank=召回顺序，不等于可回答。")
    lines.append("  - time_clues仅作时效线索；publish/source类更像内容时间，create/update类多为入库/解析时间，勿当事件时间。")
    lines.append(f"  - 证据不足可换关键词最多约{_max_retries_hint()}次；无新证据就停止并说明知识库未找到答案。上下文不完整才扩展。")
    return "\n".join(lines)


def _format_context_yaml(result: dict) -> str:
    lines = [
        "status: context_retrieved",
        f"focus_chunk_id: {_yaml_scalar(result.get('chunk_id', ''))}",
        f"doc_id: {_yaml_scalar(result.get('document_id', ''))}",
        f"dataset_id: {_yaml_scalar(result.get('dataset_id', ''))}",
        f"focus_offset: {result.get('focus_offset', 0)}",
        "context_chunks:",
    ]

    chunks = result.get("chunks", [])
    if not chunks:
        lines.append("  []")
        return "\n".join(lines)

    for chunk in chunks:
        lines.append(f"  - position: {_yaml_scalar(chunk.get('position', ''))}")
        lines.append(f"    document_offset: {chunk.get('document_offset', 0)}")
        lines.append(f"    chunk_id: {_yaml_scalar(chunk.get('chunk_id', ''))}")
        lines.append(f"    doc_id: {_yaml_scalar(chunk.get('doc_id', ''))}")
        lines.append(f"    dataset_id: {_yaml_scalar(chunk.get('dataset_id', ''))}")
        lines.append(f"    doc_name: {_yaml_scalar(chunk.get('doc_name', ''))}")
        _append_time_clues(lines, chunk, indent=4)
        _append_block(lines, "content", chunk.get("content", ""), indent=4)
    lines.append("notes:")
    lines.append("  - time_clues仅作时效线索；publish/source类更像内容时间，create/update类多为入库/解析时间，勿当事件时间。")
    return "\n".join(lines)


def _format_saved_yaml(status: str, path: Path, mode: str, dataset_id: str, document_id: str, detail: str = "") -> str:
    lines = [
        f"status: {status}",
        f"mode: {_yaml_scalar(mode)}",
        f"saved_path: {_yaml_scalar(str(path.resolve()))}",
        f"dataset_id: {_yaml_scalar(dataset_id)}",
        f"doc_id: {_yaml_scalar(document_id)}",
    ]
    if detail:
        lines.append(f"detail: {_yaml_scalar(detail)}")
    if mode == "parsed_text":
        lines.append("notes:")
        lines.append("  - time_clue仅作时效线索；publish/source类更像内容时间，create/update类多为入库/解析时间，勿当事件时间。")
    return "\n".join(lines)


def _safe_filename(value: str, default: str) -> str:
    name = (value or default).strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or default


def _workspace_output_dir(args: dict) -> Path:
    output_dir = args.get("output_dir") or _setting("QYRAG_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
    path = Path(output_dir).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    workspace = Path.cwd().resolve()
    if workspace not in path.parents and path != workspace:
        raise ValueError("output_dir must be inside the Hermes workspace")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _document_url(base_url: str, dataset_id: str, document_id: str) -> str:
    return f"{base_url}/api/v1/datasets/{dataset_id}/documents/{document_id}"


def _fetch_document_chunks(
    base_url: str,
    headers: dict,
    dataset_id: str,
    document_id: str,
    page_size: int = 100,
    max_pages: int = 200,
) -> tuple[list[dict], str | None]:
    url = _chunks_url(base_url, dataset_id, document_id)
    chunks = []
    total = 0

    for page in range(1, max_pages + 1):
        raw, _elapsed = _get(url, headers, params={"page": page, "page_size": page_size})
        result = json.loads(raw)
        if result.get("success") is False:
            return [], result.get("error", "failed to list chunks")

        page_chunks, total = _extract_chunks_payload(result)
        if not page_chunks:
            break
        chunks.extend(page_chunks)
        if total and len(chunks) >= total:
            break

    return chunks, None


def _write_parsed_text(path: Path, dataset_id: str, document_id: str, chunks: list[dict]) -> None:
    lines = [
        f"dataset_id: {dataset_id}",
        f"doc_id: {document_id}",
        "",
    ]

    for idx, chunk in enumerate(chunks, 1):
        chunk_id = _chunk_id(chunk)
        content = (chunk.get("content") or "").strip()
        lines.append(f"--- chunk {idx} ---")
        lines.append(f"chunk_id: {chunk_id}")
        clues = _time_clues(chunk)
        if clues:
            for clue in clues:
                lines.append(f"time_clue.{clue['source']}: {clue['value']}")
        lines.append("")
        if content:
            lines.append(content)
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _chunks_url(base_url: str, dataset_id: str, document_id: str) -> str:
    return f"{base_url}/api/v1/datasets/{dataset_id}/documents/{document_id}/chunks"


def _extract_chunks_payload(result: dict) -> tuple[list[dict], int]:
    data = result.get("data", {})
    if isinstance(data, list):
        return data, len(data)
    chunks = data.get("chunks") or data.get("items") or []
    total = data.get("total")
    if total is None:
        total = len(chunks)
    return chunks, int(total or 0)


def _fetch_context_window(
    base_url: str,
    headers: dict,
    dataset_id: str,
    document_id: str,
    chunk_id: str,
    before: int,
    after: int,
    page_size: int = 100,
    max_pages: int = 50,
) -> dict:
    """Find a chunk inside a document and return nearby chunks by document order."""
    if not dataset_id or not document_id or not chunk_id:
        return {
            "success": False,
            "error": "dataset_id, document_id and chunk_id are required for context expansion",
        }

    url = _chunks_url(base_url, dataset_id, document_id)
    all_chunks = []
    total = 0
    elapsed_total = 0.0

    for page in range(1, max_pages + 1):
        raw, elapsed = _get(url, headers, params={"page": page, "page_size": page_size})
        elapsed_total += elapsed
        result = json.loads(raw)
        if result.get("success") is False:
            return result

        page_chunks, total = _extract_chunks_payload(result)
        if not page_chunks:
            break

        all_chunks.extend(page_chunks)
        if len(all_chunks) >= total:
            break

    focus_index = None
    for idx, chunk in enumerate(all_chunks):
        if _chunk_id(chunk) == chunk_id:
            focus_index = idx
            break

    if focus_index is None:
        return {
            "success": False,
            "error": "Target chunk was not found in the document chunk list",
            "dataset_id": dataset_id,
            "document_id": document_id,
            "chunk_id": chunk_id,
            "scanned_chunks": len(all_chunks),
            "elapsed_seconds": round(elapsed_total, 3),
        }

    start = max(0, focus_index - before)
    end = min(len(all_chunks), focus_index + after + 1)
    window = []
    for idx in range(start, end):
        chunk = all_chunks[idx]
        if idx < focus_index:
            position = "before"
        elif idx == focus_index:
            position = "focus"
        else:
            position = "after"
        window.append({
            **chunk,
            "position": position,
            "document_offset": idx,
            "chunk_id": _chunk_id(chunk),
            "doc_id": _document_id(chunk) or document_id,
            "dataset_id": _dataset_id(chunk) or dataset_id,
            "doc_name": _document_name(chunk),
            "content": chunk.get("content", ""),
        })

    return {
        "success": True,
        "dataset_id": dataset_id,
        "document_id": document_id,
        "chunk_id": chunk_id,
        "focus_offset": focus_index,
        "before": before,
        "after": after,
        "total_document_chunks": total or len(all_chunks),
        "chunks": window,
        "elapsed_seconds": round(elapsed_total, 3),
    }


def QYRAG_retrieve(args: dict, **kwargs) -> str:
    """Retrieve chunks from QYRAG datasets."""
    question = args.get("question", "")
    if not question:
        return _yaml_error("Missing required parameter: question")

    url = f"{args.get('base_url') or _base_url()}/api/v1/retrieval"
    api_key = _api_key_from_args(args)
    if not api_key:
        return _missing_api_key_yaml()
    headers = _auth_headers(api_key)

    try:
        payload = _build_payload(args)
    except ValueError as exc:
        return _yaml_permission_error(str(exc))
    return _deep_search(args, question, url, headers, payload)

def _format_answer_yaml(question: str, dataset_ids: list[str], result: dict) -> str:
    data = result.get("data", result)
    if not isinstance(data, dict):
        return _yaml_error("QYRAG answer endpoint returned an invalid response")
    answer = data.get("answer") or data.get("content") or data.get("message") or ""
    references = data.get("references") or data.get("citations") or data.get("sources") or []
    if not answer:
        return _yaml_error("QYRAG answer endpoint returned no answer")
    if str(answer).lstrip().startswith("**ERROR**") or str(answer).lstrip().startswith("ERROR"):
        return "\n".join([
            "status: error",
            f"query: {_yaml_scalar(question)}",
            "selected_dataset_ids:",
            *[f"  - {_yaml_scalar(dataset_id)}" for dataset_id in dataset_ids],
            f"error: {_yaml_scalar(str(answer))}",
        ])
    lines = ["status: answered", f"query: {_yaml_scalar(question)}", "selected_dataset_ids:"]
    lines.extend(f"  - {_yaml_scalar(dataset_id)}" for dataset_id in dataset_ids)
    _append_block(lines, "answer", str(answer))
    lines.append("sources:")
    if not references:
        lines.append("  []")
    for reference in references:
        if isinstance(reference, dict):
            lines.append(f"  - doc_id: {_yaml_scalar(reference.get('doc_id') or reference.get('document_id', ''))}")
            lines.append(f"    doc_name: {_yaml_scalar(reference.get('doc_name') or reference.get('document_name', ''))}")
            lines.append(f"    chunk_id: {_yaml_scalar(reference.get('chunk_id') or reference.get('id', ''))}")
        else:
            lines.append(f"  - {_yaml_scalar(reference)}")
    return "\n".join(lines)

def QYRAG_answer(args: dict, **kwargs) -> str:
    """Answer directly using the selected QYRAG knowledge base."""
    question = str(args.get("question") or "").strip()
    if not question:
        return _yaml_error("Missing required parameter: question")
    args = _answer_dataset_args(args)
    try:
        dataset_ids = _resolve_dataset_ids(args)
    except ValueError as exc:
        return _yaml_permission_error(str(exc))
    if not dataset_ids:
        return _yaml_error("No selected knowledge base. Pass dataset_ids/dataset_names or set QYRAG_SELECTED_DATASETS.")
    api_key = _api_key_from_args(args)
    if not api_key:
        return _missing_api_key_yaml()
    base_url = (args.get("base_url") or _base_url()).rstrip("/")
    answer_path = args.get("answer_path") or _setting("QYRAG_ANSWER_PATH", "/api/v1/chat/completions")
    answer_path = "/" + answer_path.lstrip("/")
    payload = {"question": question, "dataset_ids": dataset_ids, "stream": False, "return_references": True}
    raw, _elapsed = _post(base_url + answer_path, _auth_headers(api_key), payload, timeout=90)
    result = json.loads(raw)
    if result.get("success") is False:
        return _yaml_error(result.get("error", "QYRAG answer request failed"))
    return _format_answer_yaml(question, dataset_ids, result)

def QYRAG_health_check(args: dict, **kwargs) -> str:
    """Check if the QYRAG server is reachable."""
    url = f"{args.get('base_url') or _base_url()}/api/v1/retrieval"
    api_key = _api_key_from_args(args)
    if not api_key:
        return json.dumps({
            "success": False,
            "error": "未配置 QYRAG_API_KEY 或 RAGFLOW_API_KEY，无法调用受保护的 QYRAG 服务。",
        })
    headers = _auth_headers(api_key)

    try:
        start = time.time()
        resp = _request("POST", url, headers, 10, json={"question": "health", "page_size": 1})
        elapsed = round(time.time() - start, 3)
        if resp.status_code == 401:
            return json.dumps({
                "success": False,
                "status": "unauthorized",
                "server": args.get("base_url") or _base_url(),
                "status": "reachable",
                "auth": "missing API key (401)",
                "elapsed_seconds": elapsed,
            })
        resp.raise_for_status()
        return json.dumps({
            "success": True,
            "server": args.get("base_url") or _base_url(),
            "status": "healthy",
            "auth": "authenticated",
            "elapsed_seconds": elapsed,
        })
    except requests.exceptions.ConnectionError:
        return json.dumps({"success": False, "error": f"Cannot connect to QYRAG at {args.get('base_url') or _base_url()}"})
    except requests.exceptions.Timeout:
        return json.dumps({"success": False, "error": f"Connection timeout to QYRAG at {args.get('base_url') or _base_url()}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"success": False, "error": str(e)})


def QYRAG_expand_context(args: dict, **kwargs) -> str:
    """Fetch chunks before and after a relevant chunk in the same document."""
    dataset_id = args.get("dataset_id", "")
    document_id = args.get("document_id", "")
    chunk_id = args.get("chunk_id", "")
    before = int(args.get("before", 2))
    after = int(args.get("after", 2))
    page_size = int(args.get("scan_page_size", 100))
    max_pages = int(args.get("max_scan_pages", 50))

    try:
        _validate_dataset_id(dataset_id)
    except ValueError as exc:
        return _yaml_permission_error(str(exc))

    base_url = args.get("base_url") or _base_url()
    api_key = _api_key_from_args(args)
    if not api_key:
        return _missing_api_key_yaml()
    headers = _auth_headers(api_key)

    result = _fetch_context_window(
        base_url=base_url,
        headers=headers,
        dataset_id=dataset_id,
        document_id=document_id,
        chunk_id=chunk_id,
        before=max(0, before),
        after=max(0, after),
        page_size=max(1, page_size),
        max_pages=max(1, max_pages),
    )
    if result.get("success") is False:
        return _yaml_error(result.get("error", "context expansion failed"))
    return _format_context_yaml(result)


def QYRAG_save_document(args: dict, **kwargs) -> str:
    """Save a QYRAG document as parsed text or as the original source file."""
    dataset_id = args.get("dataset_id", "")
    document_id = args.get("document_id", "")
    mode = args.get("mode", "parsed_text")

    if not dataset_id or not document_id:
        return _yaml_error("dataset_id and document_id are required")
    if mode not in {"parsed_text", "source"}:
        return _yaml_error("mode must be 'parsed_text' or 'source'")
    try:
        _validate_dataset_id(dataset_id)
    except ValueError as exc:
        return _yaml_permission_error(str(exc))

    base_url = args.get("base_url") or _base_url()
    api_key = _api_key_from_args(args)
    if not api_key:
        return _missing_api_key_yaml()
    headers = _auth_headers(api_key)
    try:
        output_dir = _workspace_output_dir(args)
    except ValueError as exc:
        return _yaml_error(str(exc))
    filename = args.get("filename")

    if mode == "parsed_text":
        page_size = int(args.get("scan_page_size", 100))
        max_pages = int(args.get("max_scan_pages", 200))
        chunks, error = _fetch_document_chunks(
            base_url=base_url,
            headers=headers,
            dataset_id=dataset_id,
            document_id=document_id,
            page_size=max(1, page_size),
            max_pages=max(1, max_pages),
        )
        if error:
            return _yaml_error(error)

        safe_name = _safe_filename(filename or f"{document_id}.txt", f"{document_id}.txt")
        if not safe_name.lower().endswith(".txt"):
            safe_name += ".txt"
        path = output_dir / safe_name
        _write_parsed_text(path, dataset_id, document_id, chunks)
        return _format_saved_yaml(
            "saved",
            path,
            mode,
            dataset_id,
            document_id,
            detail=f"saved {len(chunks)} parsed chunks as UTF-8 text",
        )

    content, meta = _download(_document_url(base_url, dataset_id, document_id), headers=headers)
    if not meta.get("success"):
        return _yaml_error(meta.get("error", "document download failed"))

    safe_name = _safe_filename(filename or document_id, document_id)
    path = output_dir / safe_name
    path.write_bytes(content or b"")
    return _format_saved_yaml(
        "saved",
        path,
        mode,
        dataset_id,
        document_id,
        detail=f"saved original file, content_type={meta.get('content_type', '')}",
    )


# ======================================================================
# Deep Search: auto-decompose question, multi-round retrieve, merge
# ======================================================================


def _decompose_question(question: str) -> list[str]:
    """Decompose a question into sub-queries.

    Uses rule-based extraction for years, ranges, and conjunctions.
    """
    sub_queries = []

    # Strategy 1: Extract year ranges like "2021-2024" or "2021年至2024年"
    range_match = re.search(r'(\d{4})\s*[至\-~]\s*(\d{4})', question)
    if range_match:
        start_year = int(range_match.group(1))
        end_year = int(range_match.group(2))
        base = re.sub(r'\d{4}\s*[至\-~]\s*\d{4}', '', question).strip()
        base = re.sub(r'[年,，、]', ' ', base).strip()
        base = re.sub(r'\s+', ' ', base).strip()
        for year in range(start_year, end_year + 1):
            sub_queries.append(f"{year}年 {base}".strip())
        if sub_queries:
            return sub_queries

    # Strategy 2: Extract specific years mentioned
    years = sorted(set(int(y) for y in re.findall(r'(\d{4})年', question)))
    if len(years) >= 2:
        if max(years) - min(years) <= 5:
            base = re.sub(r'\d{4}年', '', question).strip()
            base = re.sub(r'[至\-~]\s*\d{4}', '', base).strip()
            base = re.sub(r'[年,，、]', ' ', base).strip()
            base = re.sub(r'\s+', ' ', base).strip()
            for year in range(min(years), max(years) + 1):
                sub_queries.append(f"{year}年 {base}".strip())
        else:
            base = re.sub(r'\d{4}年', '', question).strip()
            base = re.sub(r'[至\-~]\s*\d{4}', '', base).strip()
            base = re.sub(r'[年,，、]', ' ', base).strip()
            base = re.sub(r'\s+', ' ', base).strip()
            for y in years:
                sub_queries.append(f"{y}年 {base}")
        return sub_queries

    # Strategy 3: Single year found
    if len(years) == 1:
        return [question]

    # Strategy 4: Split by conjunctions for multi-topic questions
    for sep in ['及', '和', '与', '、', ',', '，', '以及']:
        parts = [p.strip() for p in question.split(sep) if p.strip() and len(p.strip()) > 4]
        if len(parts) >= 2 and len(parts) <= 6:
            main_topic_parts = [p for p in parts if len(p) > 6]
            if len(main_topic_parts) >= 2:
                return main_topic_parts

    # Fallback: return original
    return [question]


def _deduplicate_chunks(chunks: list[dict]) -> list[dict]:
    """Deduplicate chunks by content hash, keeping highest similarity."""
    seen = {}
    for c in chunks:
        content = c.get("content", "")
        key = content[:100]  # first 100 chars as dedup key
        existing = seen.get(key)
        if existing is None:
            seen[key] = c
        elif c.get("similarity", 0) > existing.get("similarity", 0):
            seen[key] = c
    return list(seen.values())


def _deep_search(args: dict, question: str, url: str, headers: dict, base_payload: dict) -> str:
    """Decompose question, retrieve each sub-query, merge results."""
    sub_queries = _decompose_question(question)
    page_size = args.get("page_size", 5)
    per_query_size = max(3, page_size // max(len(sub_queries), 1))

    all_chunks = []

    for sq in sub_queries:
        payload = dict(base_payload)
        payload["question"] = sq
        payload["page_size"] = per_query_size

        raw, _elapsed = _post(url, headers, payload)
        result = json.loads(raw)
        if result.get("success") is False:
            return _yaml_error(result.get("error", "retrieval failed"))

        data = result.get("data", {})
        all_chunks.extend(data.get("chunks", []))

    merged_chunks = _deduplicate_chunks(all_chunks)
    merged_chunks.sort(key=lambda c: c.get("similarity", 0), reverse=True)
    merged_chunks = merged_chunks[:page_size]
    global _LAST_RETRIEVAL
    _LAST_RETRIEVAL = {"question": question, "chunks": merged_chunks}
    return _format_retrieve_yaml(question, sub_queries, merged_chunks)


def QYRAG_check_sufficient_context(args: dict, **kwargs) -> str:
    """检查最近一次检索的证据是否足以回答复杂问题。"""
    question = str(args.get("question") or _LAST_RETRIEVAL.get("question") or "").strip()
    chunks = _LAST_RETRIEVAL.get("chunks") or []
    if not question:
        return "status: needs_retrieval\nreason: 尚未提供问题；请先调用 QYRAG_retrieve。"
    if not chunks:
        return (
            "status: no_evidence\n"
            f"question: {_yaml_scalar(question)}\n"
            "reason: 当前没有可用检索结果。\n"
            "recommended_next_actions:\n"
            "  - 使用更短、更具体的关键词调用 QYRAG_retrieve"
        )
    terms = list(dict.fromkeys(re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,}", question.lower())))
    corpus = " ".join(str(chunk.get("content") or "").lower() for chunk in chunks)
    matched = [term for term in terms if term in corpus]
    coverage = len(matched) / len(terms) if terms else 1.0
    strong_refs = sum(1 for chunk in chunks if float(chunk.get("similarity") or 0) >= 0.5)
    status = "sufficient" if coverage >= CONTEXT_MIN_COVERAGE and strong_refs >= CONTEXT_MIN_STRONG_REFS else "needs_more_context"
    missing = [term for term in terms if term not in matched]
    lines = [
        f"status: {status}",
        f"question: {_yaml_scalar(question)}",
        f"coverage: {coverage:.2f}",
        f"strong_refs: {strong_refs}",
        "missing_terms:",
    ]
    lines.extend(f"  - {_yaml_scalar(term)}" for term in missing[:12]) if missing else lines.append("  []")
    lines.append("recommended_next_actions:")
    lines.append(
        "  - 可以基于当前证据回答并保留引用"
        if status == "sufficient"
        else "  - 使用 missing_terms 组合关键词重新调用 QYRAG_retrieve，或对命中文档调用 QYRAG_expand_context / QYRAG_grep_document"
    )
    return "\n".join(lines)


def QYRAG_grep_document(args: dict, **kwargs) -> str:
    """在一个授权知识库文档的解析切片中精确核查关键词。"""
    dataset_id = str(args.get("dataset_id") or "").strip()
    document_id = str(args.get("document_id") or "").strip()
    pattern = str(args.get("pattern") or "").strip()
    if not dataset_id or not document_id or not pattern:
        return _yaml_error("dataset_id, document_id and pattern are required")
    try:
        _validate_dataset_id(dataset_id)
    except ValueError as exc:
        return _yaml_permission_error(str(exc))
    api_key = _api_key_from_args(args)
    if not api_key:
        return _missing_api_key_yaml()
    try:
        regex = re.compile(pattern, 0 if args.get("case_sensitive") else re.IGNORECASE)
    except re.error:
        regex = re.compile(re.escape(pattern), 0 if args.get("case_sensitive") else re.IGNORECASE)
    try:
        chunks, error = _fetch_document_chunks(
            (args.get("base_url") or _base_url()).rstrip("/"),
            _auth_headers(api_key),
            dataset_id,
            document_id,
        )
    except (OSError, ValueError, requests.RequestException, json.JSONDecodeError) as exc:
        return _yaml_error(f"document grep failed: {exc}")
    if error:
        return _yaml_error(f"document grep failed: {error}")
    max_matches = max(1, min(int(args.get("max_matches", 20)), 80))
    matches = []
    for chunk in chunks:
        content = str(chunk.get("content") or "")
        for line_no, line in enumerate(content.splitlines() or [content], 1):
            if regex.search(line):
                matches.append((chunk, line_no, line.strip()))
                if len(matches) >= max_matches:
                    break
        if len(matches) >= max_matches:
            break
    lines = [
        "status: matched" if matches else "status: no_matches",
        f"dataset_id: {_yaml_scalar(dataset_id)}",
        f"document_id: {_yaml_scalar(document_id)}",
        f"pattern: {_yaml_scalar(pattern)}",
        "matches:",
    ]
    if not matches:
        lines.append("  []")
    for chunk, line_no, line in matches:
        lines.extend([
            f"  - chunk_id: {_yaml_scalar(_chunk_id(chunk))}",
            f"    line: {line_no}",
            f"    content: {_yaml_scalar(line[:500])}",
        ])
    return "\n".join(lines)
