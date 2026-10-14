"""Dogpile search result extractor (JSON API)."""

import json
import re

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text):
    return _TAG_RE.sub("", text or "").strip()


def extract(html: str) -> list[dict]:
    try:
        data = json.loads(html)
    except (json.JSONDecodeError, ValueError):
        return []
    results = []
    for item in data.get("results", []):
        url = item.get("clickUrl", "")
        title = _clean(item.get("title", ""))
        desc = _clean(item.get("description", ""))
        if url:
            results.append({"url": url, "title": title, "desc": desc})
    return results
