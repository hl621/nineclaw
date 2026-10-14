"""Sina search result extractor (JSON API)."""

import json
import re

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def extract(html: str) -> list[dict]:
    try:
        data = json.loads(html)
    except (json.JSONDecodeError, ValueError):
        return []
    results = []
    for item in (data.get("data") or {}).get("list") or []:
        url = item.get("url") or ""
        title = _clean(item.get("title") or "")
        if not url or not title:
            continue
        results.append({
            "url": url,
            "title": title,
            "desc": _clean(item.get("intro") or item.get("searchSummary") or ""),
        })
    return results
