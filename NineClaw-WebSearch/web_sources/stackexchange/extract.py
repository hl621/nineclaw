"""StackOverflow (Stack Exchange API) search result extractor."""

import html as html_lib
import json


def extract(html: str) -> list[dict]:
    try:
        data = json.loads(html)
    except (json.JSONDecodeError, ValueError):
        return []
    results = []
    for item in data.get("items", []):
        url = item.get("link", "")
        title = html_lib.unescape(item.get("title", ""))
        tags = item.get("tags", [])
        desc = " ".join(tags)
        if url and title:
            results.append({"url": url, "title": title, "desc": desc})
    return results
