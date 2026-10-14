"""ResultHunter search result extractor."""

from parsel import Selector


def extract(html: str) -> list[dict]:
    sel = Selector(text=html)
    results = []
    for item in sel.xpath(
        '//div[contains(@class, "organic-results-container")]/div/div[contains(@class, "group")]'
    ):
        url = item.xpath(".//a/@href").get("")
        title = "".join(item.xpath(".//a/h3//text()").getall()).strip()
        desc = "".join(item.xpath(".//p//text()").getall()).strip()
        if url:
            results.append({"url": url, "title": title, "desc": desc})
    return results
