"""搜狗微信文章搜索结果提取器。参照 SearXNG sogou_wechat 引擎移植。"""

import re
from datetime import datetime

from parsel import Selector


def extract(html: str) -> list[dict]:
    sel = Selector(text=html)
    results = []
    for item in sel.xpath('//li[contains(@id, "sogou_vr_")]'):
        title = item.xpath("string(.//h3/a)").get("").strip()
        url = item.xpath(".//h3/a/@href").get("").strip()
        snippet = item.xpath('string(.//p[contains(@class, "txt-info")])').get("").strip()
        ts = item.xpath('.//script[contains(text(), "timeConvert")]/text()').re_first(
            r"timeConvert\('(\d+)'\)"
        )
        date_str = (
            datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d") if ts else ""
        )
        desc = f"{date_str} {snippet}".strip() or None
        if title and url:
            results.append({"url": url, "title": title, "desc": desc})
    return results
