"""Mwmbl search result extractor.

Mwmbl returns title/extract as a list of ``{"value": str, "is_bold": bool}``
segments; this flattens them into plain strings.
"""

import json


def _flatten(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(str(seg.get("value", "")) for seg in value if isinstance(seg, dict))
    return str(value or "")


def extract(html: str) -> list[dict]:
    try:
        data = json.loads(html)
    except (json.JSONDecodeError, ValueError):
        return []
    results = []
    if not isinstance(data, list):
        return results
    for item in data:
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        title = _flatten(item.get("title"))
        desc = _flatten(item.get("extract"))
        if url and title:
            results.append({"url": url, "title": title, "desc": desc})
    return results
