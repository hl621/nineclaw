"""夸克搜索结果提取器。参照 SearXNG quark 引擎移植：从内嵌 hydrate JSON 块中提取结果。"""

import json
import re

from parsel import Selector

HYDRATE_RE = re.compile(
    r'<script\s+type="application/json"\s+id="s-data-[^"]+"\s+data-used-by="hydrate">(.*?)</script>',
    re.DOTALL,
)
CAPTCHA_RE = re.compile(
    r'\{[^{]*?"action"\s*:\s*"captcha"\s*,\s*"url"\s*:\s*"([^"]+)"[^{]*?\}'
)

# 非网页结果的卡片类型（词典/翻译卡片等），跳过不提取。
SKIP_SC_TYPES = {"dict_jinshan"}


def _strip_html(text: str) -> str:
    """字段值可能含 HTML 标签，用 parsel 取纯文本。非字符串输入安全返回 ""。"""
    if not isinstance(text, str):
        return ""
    if not text or "<" not in text:
        return text.strip()
    return Selector(text=f"<div>{text}</div>").xpath("string()").get("").strip()


def _get(d: dict, *path):
    """安全取嵌套字段，任一环节缺失返回 None。"""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _extract_block(block: dict) -> list[dict]:
    """按 extraData.sc 类型分发提取。返回 0..N 条结果。"""
    sc = _get(block, "extraData", "sc")
    if sc in SKIP_SC_TYPES:
        return []
    init = _get(block, "data", "initialData") or {}
    results = []
    if sc == "news_uchq":
        for item in init.get("feed") or []:
            if not isinstance(item, dict):
                continue
            title = _strip_html(item.get("title") or "")
            url = item.get("url") or ""
            desc = _strip_html(item.get("summary") or "") or None
            if title and url:
                results.append({"url": url, "title": title, "desc": desc})
    else:
        title = _strip_html(
            _get(init, "titleProps", "content") or init.get("title") or ""
        )
        url = (
            _get(init, "sourceProps", "dest_url")
            or init.get("normal_url")
            or init.get("url")
            or ""
        )
        desc = _strip_html(
            _get(init, "summaryProps", "content") or init.get("desc") or ""
        ) or None
        if title and url:
            results.append({"url": url, "title": title, "desc": desc})
    return results


def extract(html: str) -> list[dict]:
    if CAPTCHA_RE.search(html):
        return []
    results = []
    seen = set()
    for m in HYDRATE_RE.finditer(html):
        try:
            block = json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        for item in _extract_block(block):
            if not isinstance(item["url"], str):
                continue
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            results.append(item)
    return results
