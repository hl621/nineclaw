"""iQiyi search result extractor (JSON API)."""

import json
import re

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text) -> str:
    if not isinstance(text, str):
        return ""
    return _TAG_RE.sub("", text).strip()


def extract(html: str) -> list[dict]:
    try:
        data = json.loads(html)
    except (json.JSONDecodeError, ValueError):
        return []
    results = []
    for item in (data.get("data") or {}).get("templates") or []:
        album = item.get("albumInfo")
        if not album:
            continue
        url = (album.get("pageUrl") or "").replace("http://", "https://", 1)
        title = _clean(album.get("title") or "")
        if not url or not title:
            continue
        desc = _clean(
            album.get("subtitle") or album.get("brief") or album.get("introduction") or ""
        )
        results.append({"url": url, "title": title, "desc": desc})
    return results
