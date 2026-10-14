"""Bing 新闻搜索结果提取器。参照 SearXNG bing_news 引擎移植。"""

from parsel import Selector


def extract(html: str) -> list[dict]:
    sel = Selector(text=html)
    results = []
    for item in sel.xpath('//div[contains(@class, "newsitem")]'):
        url = item.xpath('.//a[@class="title"]/@href').get("").strip()
        title = item.xpath('string(.//a[@class="title"])').get("").strip()
        snippet = item.xpath('string(.//div[@class="snippet"])').get("").strip()
        # 来源名：div.source 内第一个 <a> 的文本（其 aria-label 为 "Search news from X"，不取）
        source = item.xpath(
            'string(.//div[contains(@class, "source")]//a[1])'
        ).get("").strip()
        # 发布时间：div.source 内第一个带 aria-label 的 <span>（如 "2 hours ago"）
        pub_time = item.xpath(
            './/div[contains(@class, "source")]//span[@aria-label][1]/@aria-label'
        ).get("").strip()
        desc = " | ".join(p for p in (source, pub_time, snippet) if p) or None
        if url and title:
            results.append({"url": url, "title": title, "desc": desc})
    return results
