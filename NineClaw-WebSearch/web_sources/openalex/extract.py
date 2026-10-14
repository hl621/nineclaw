"""OpenAlex works search result extractor."""

import json


def extract(html: str) -> list[dict]:
    try:
        data = json.loads(html)
    except (json.JSONDecodeError, ValueError):
        return []
    results = []
    for item in data.get("results", []):
        title = item.get("display_name") or ""
        primary = item.get("primary_location") or {}
        url = primary.get("landing_page_url")
        if not url:
            url = item.get("id", "")
        year = item.get("publication_year")
        cited = item.get("cited_by_count", 0)
        desc = f"Published {year}, cited {cited} times" if year else f"Cited {cited} times"
        if url and title:
            results.append({"url": url, "title": title, "desc": desc})
    return results
