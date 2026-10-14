"""360 (so.com) search result extractor."""

from parsel import Selector


def extract(html: str) -> list[dict]:
    sel = Selector(text=html)
    results = []
    for item in sel.xpath('//li[contains(@class, "res-list")]'):
        title = "".join(
            item.xpath('.//h3[contains(@class, "res-title")]/a//text()').getall()
        ).strip()
        url = item.xpath(
            './/h3[contains(@class, "res-title")]/a/@data-mdurl'
        ).get("") or item.xpath(
            './/h3[contains(@class, "res-title")]/a/@href'
        ).get("")
        desc = "".join(item.xpath('.//p[@class="res-desc"]//text()').getall()).strip()
        if not desc:
            desc = "".join(
                item.xpath('.//span[@class="res-list-summary"]//text()').getall()
            ).strip()
        if url:
            results.append({"url": url, "title": title, "desc": desc})
    return results
