"""arXiv API (Atom XML) search result extractor."""

import re

from lxml.etree import XMLSyntaxError
from parsel import Selector


def extract(html: str) -> list[dict]:
    if not html:
        return []
    try:
        sel = Selector(text=html, type="xml")
    except XMLSyntaxError:
        return []
    sel.remove_namespaces()
    results = []
    for entry in sel.xpath("//entry"):
        title = entry.xpath("title/text()").get("")
        title = re.sub(r"\s+", " ", title).strip()
        url = entry.xpath("id/text()").get("").strip()
        desc = entry.xpath("summary/text()").get("")
        desc = re.sub(r"\s+", " ", desc).strip()
        if len(desc) > 300:
            desc = desc[:300] + "..."
        if url and title:
            results.append({"url": url, "title": title, "desc": desc})
    return results
