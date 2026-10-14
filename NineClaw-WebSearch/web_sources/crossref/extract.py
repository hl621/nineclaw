"""Crossref works search result extractor."""

import json


def extract(html: str) -> list[dict]:
    try:
        data = json.loads(html)
    except (json.JSONDecodeError, ValueError):
        return []
    results = []
    for item in data.get("message", {}).get("items", []):
        titles = item.get("title") or []
        title = titles[0] if titles else ""
        url = item.get("resource", {}).get("primary", {}).get("URL", "")
        if not url:
            url = item.get("URL", "")
        container = item.get("container-title") or []
        journal = container[0] if container else ""
        year = ""
        date_parts = item.get("published", {}).get("date-parts", [])
        if date_parts and date_parts[0]:
            year = str(date_parts[0][0])
        desc_parts = [p for p in (journal, year) if p]
        desc = " ".join(desc_parts)
        if url and title:
            results.append({"url": url, "title": title, "desc": desc})
    return results
