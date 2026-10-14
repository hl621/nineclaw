"""Bing search result extractor."""

from parsel import Selector


def extract(html: str) -> list[dict]:
    sel = Selector(text=html)
    results = []
    for item in sel.css("li.b_algo"):
        title = item.xpath("string(//h2/a)").get("")
        url = item.css("h2 a::attr(href)").get("")
        desc = item.css(".b_caption p::text").get()
        if url:
            results.append({"url": url, "title": title, "desc": desc})
    return results
