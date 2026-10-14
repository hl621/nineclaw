"""Filesystem-based source loader with hot-reload via mtime checking."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

WEB_SOURCES_DIR = Path(__file__).resolve().parent.parent.parent / "web_sources"

# Written on create so the card is immediately listable / openable.
# Users replace it in the detail-page extractor step.
DEFAULT_EXTRACTOR_CODE = '''\
# 目标：编写 extract 函数，解析 response.html，返回结构化列表。
# 返回值每项须包含：url (str, 必填)、title (str, 必填)、desc (str, 选填)
from parsel import Selector


def extract(html: str) -> list[dict]:
    sel = Selector(text=html)
    results = []
    for item in sel.css(".result, .b_algo, .vrwrap, li"):
        title = (item.css("h3 a::text, h2 a::text, a::text").get() or "").strip()
        url = (item.css("h3 a::attr(href), h2 a::attr(href), a::attr(href)").get() or "").strip()
        desc = item.css("p::text, .b_caption p::text").get()
        if url and title:
            results.append({"url": url, "title": title, "desc": desc})
    return results
'''


@dataclass
class WebSource:
    source_id: str
    config: dict
    extractor_code: str
    _extract_fn: Callable | None = field(default=None, repr=False)

    @property
    def name(self) -> str:
        return self.config.get("name", self.source_id)

    @property
    def description(self) -> str | None:
        return self.config.get("description")

    @property
    def enabled(self) -> bool:
        return self.config.get("enabled", True)

    @property
    def weight(self) -> float:
        return self.config.get("weight", 0.5)

    @property
    def tags(self) -> list[str]:
        return self.config.get("tags", [])

    @property
    def request_config(self) -> dict:
        # Prefer nested "request"; accept legacy/top-level "request_config".
        req = self.config.get("request")
        if isinstance(req, dict):
            return req
        legacy = self.config.get("request_config")
        return legacy if isinstance(legacy, dict) else {}

    @property
    def response_info(self) -> dict:
        response = self.config.get("response")
        if not isinstance(response, dict):
            return {}
        content_type = response.get("content_type")
        if not content_type:
            headers = response.get("headers")
            if isinstance(headers, dict):
                content_type = headers.get("content-type")
        return {"content_type": content_type} if content_type else {}

    @property
    def url_base(self) -> str:
        return self.config.get("url_base", "")

    @property
    def extractor_code_safe(self) -> str:
        return self.extractor_code or DEFAULT_EXTRACTOR_CODE

    @property
    def extract_fn(self) -> Callable:
        if self._extract_fn is None:
            ns: dict = {}
            code = self.extractor_code_safe
            exec(compile(code, f"{self.source_id}/extract.py", "exec"), ns)  # noqa: S102
            self._extract_fn = ns["extract"]
        return self._extract_fn


@dataclass
class _CacheEntry:
    source: WebSource
    config_mtime: float
    extract_mtime: float


_cache: dict[str, _CacheEntry] = {}


def ensure_default_extractor(source_dir: Path) -> Path:
    """Create extract.py with a starter template when missing."""
    extract_path = source_dir / "extract.py"
    if not extract_path.exists():
        extract_path.write_text(DEFAULT_EXTRACTOR_CODE, encoding="utf-8")
        logger.info("Wrote default extract.py for source %s", source_dir.name)
    return extract_path


def _load_source(source_dir: Path) -> WebSource | None:
    config_path = source_dir / "config.json"
    if not config_path.exists():
        return None
    extract_path = ensure_default_extractor(source_dir)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        extractor_code = extract_path.read_text(encoding="utf-8")
    except Exception:
        logger.exception("Failed to load source %s", source_dir.name)
        return None
    return WebSource(source_id=source_dir.name, config=config, extractor_code=extractor_code)


def get_source(source_id: str) -> WebSource | None:
    """Get a single source by id, hot-reloading if files changed."""
    source_dir = WEB_SOURCES_DIR / source_id
    if not source_dir.is_dir():
        _cache.pop(source_id, None)
        return None

    config_path = source_dir / "config.json"
    if not config_path.exists():
        return None

    extract_path = ensure_default_extractor(source_dir)

    config_mt = config_path.stat().st_mtime
    extract_mt = extract_path.stat().st_mtime

    cached = _cache.get(source_id)
    if cached and cached.config_mtime == config_mt and cached.extract_mtime == extract_mt:
        return cached.source

    source = _load_source(source_dir)
    if source:
        _cache[source_id] = _CacheEntry(source=source, config_mtime=config_mt, extract_mtime=extract_mt)
    return source


def get_all_sources() -> list[WebSource]:
    """List all valid sources, hot-reloading any changed ones."""
    if not WEB_SOURCES_DIR.is_dir():
        return []
    sources = []
    seen = set()
    for source_dir in sorted(WEB_SOURCES_DIR.iterdir()):
        if not source_dir.is_dir():
            continue
        s = get_source(source_dir.name)
        if s:
            sources.append(s)
            seen.add(source_dir.name)
    # Clean stale cache entries
    for stale in set(_cache) - seen:
        del _cache[stale]
    return sources
