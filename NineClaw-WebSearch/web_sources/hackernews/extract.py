"""Hacker News 搜索提取器（Algolia 官方 API）。参照 SearXNG hackernews 引擎移植。"""

import json

from parsel import Selector


def _strip_html(text: str) -> str:
    if not text or "<" not in text:
        return (text or "").strip()
    return Selector(text=f"<div>{text}</div>").xpath("string()").get("").strip()


def extract(html: str) -> list[dict]:
    try:
        data = json.loads(html)
    except (json.JSONDecodeError, ValueError):
        return []
    results = []
    for hit in data.get("hits", []):
        title = (hit.get("title") or "").strip()
        if not title and hit.get("author"):
            title = f"author: {hit['author']}"
        url = hit.get("url") or ""
        if not url and hit.get("objectID"):
            url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        points = hit.get("points") or 0
        comments = hit.get("num_comments") or 0
        meta = f"{points} points | {comments} comments"
        story = _strip_html(hit.get("story_text") or "")
        desc = f"{meta} | {story[:200]}" if story else meta
        if url and title:
            results.append({"url": url, "title": title, "desc": desc})
    return results
