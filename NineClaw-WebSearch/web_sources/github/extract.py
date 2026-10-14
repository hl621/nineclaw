"""GitHub repositories search result extractor."""

import json


def extract(html: str) -> list[dict]:
    try:
        data = json.loads(html)
    except (json.JSONDecodeError, ValueError):
        return []
    results = []
    for item in data.get("items", []):
        url = item.get("html_url", "")
        title = item.get("full_name", "")
        desc = item.get("description") or ""
        if url and title:
            results.append({"url": url, "title": title, "desc": desc})
    return results
