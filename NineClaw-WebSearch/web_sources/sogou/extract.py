"""
    解析 response.html，返回结构化列表。
    每项是一个 dict，对应 SearchItem 结构：
      - url:   str        （必填）
      - title: str        （必填）
      - desc:  str | None （选填）
    框架会用 pydantic 校验，类型不对会立即报错。
    只能使用沙箱预装的库：requests / parsel / httpx / pydantic
    """

from parsel import Selector


def extract(html: str) -> list[dict]:

    sel = Selector(html)
    results = []
    # TODO: 实现提取逻辑，例如：
    for item in sel.xpath('//h3[contains(@class, "vr-title")]/a[@href]'):
        url = item.css("a::attr(href)").get()
        title = item.xpath("string(.)").get("").strip()
        results.append({"url": url, "title": title})
    return results
