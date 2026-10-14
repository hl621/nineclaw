"""Naver web search result extractor."""

from parsel import Selector


def extract(html: str) -> list[dict]:
    sel = Selector(text=html)
    results = []
    for item in sel.xpath('//div[contains(@class, "fds-web-normal-doc-root")]'):
        title = "".join(
            item.xpath(
                './/span[contains(@class, "sds-comps-text-type-headline1")]//text()'
            ).getall()
        ).strip()
        url = item.xpath(
            './/span[contains(@class, "sds-comps-text-type-headline1")]/ancestor::a[1]/@href'
        ).get("")
        desc = "".join(
            item.xpath(
                './/span[contains(@class, "sds-comps-text-type-body1")]//text()'
            ).getall()
        ).strip()
        if url:
            results.append({"url": url, "title": title, "desc": desc})
    return results
