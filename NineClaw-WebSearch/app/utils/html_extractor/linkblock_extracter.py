# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2026/5/30 上午11:12
import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

from .content_extracter import gpath
from .utils import uax29_word_count
from .schema import LinkExtractResult, LinkItem


@dataclass(frozen=True)
class RegexLinkBlock:
    """A group of anchor texts matched by a regular expression."""

    block_xpath: str
    link_xpath: str
    link_titles: list[str]


def _nearest_unique_parent_gpath(dom, xpath: str) -> str:
    """Return a valid unique ancestor when the legacy refiner cannot."""
    candidate = xpath.rsplit('/', 1)[0]
    while candidate not in ('', '/', '//'):
        try:
            count = len(dom.xpath(candidate))
        except Exception:
            count = 0
        if count == 1:
            try:
                return gpath.refine_short_gpath(dom, candidate)
            except Exception:
                return candidate
        candidate = candidate.rsplit('/', 1)[0]
    return xpath


def _regex_block_xpath(dom, raw_xpath: str) -> str:
    """Refine a common ancestor without letting one weak gpath abort grep."""
    try:
        # With one structurally unique anchor, return a useful containing node
        # instead of using the link itself as its own "block".
        if len(dom.xpath(raw_xpath)) == 1:
            return _nearest_unique_parent_gpath(dom, raw_xpath)
        return gpath.refine_unique_gpath(dom, raw_xpath)
    except Exception:
        return _nearest_unique_parent_gpath(dom, raw_xpath)


def _regex_link_xpath(dom, raw_xpath: str) -> str:
    """Shorten a link gpath when possible, otherwise keep the valid original."""
    try:
        return gpath.refine_short_gpath(dom, raw_xpath)
    except Exception:
        return raw_xpath


def _is_valuable_url(url: str) -> bool:
    """过滤掉网站根路径、纯锚点、无实质路径的链接。"""
    try:
        p = urlparse(url)
        path = p.path.rstrip('/')
        return bool(path) and p.scheme in ('http', 'https')
    except Exception:
        return False


def parser_linkblock(
        html_text,
        url_base=None,
        min_text_length=7,
        min_exclusive_item_count=5
) -> list[LinkExtractResult]:
    """利用 xpath 提取 linkblock；有效链接数必须严格超过数量阈值。"""
    dom = gpath.fromstring_with_gpath(html_text)

    # 第一遍：按 gpath 分组，统计候选，同时完成 urljoin 和价值过滤
    groups = defaultdict(list)
    for elem_a in dom.xpath('//a[@href and string-length() > 5]'):
        url = urljoin(url_base, elem_a.get('href')) if url_base else elem_a.get('href')
        text = gpath.get_text(elem_a)
        if url and _is_valuable_url(url) and uax29_word_count(text) > min_text_length:
            groups[gpath.get_gpath(elem_a)].append((text, url))

    # 第二遍：过滤数量不足的组，精化 xpath 后收集结果
    _return = []
    for raw_xpath, items in groups.items():
        # 此处判断的是完成 URL、文本等过滤后的同组链接数。
        # 阈值是排他的：默认必须 > 5，即至少 6 条有效链接才会激发。
        if len(items) <= min_exclusive_item_count:
            continue
        xpath = gpath.refine_short_gpath(dom, raw_xpath)
        # raw_xpath 命中同组的多个链接；unique 精炼会逐级向上收缩，
        # 直到得到唯一的公共祖先节点。
        block_xpath = gpath.refine_unique_gpath(dom, raw_xpath)
        result = LinkExtractResult(link_xpath=xpath, block_xpath=block_xpath)
        for text, url in items:
            result.link_items.add(LinkItem(title=text, url=url))
        _return.append(result)
    return _return


def grep_linkblock(
        html_text: str,
        pattern: str,
        ignore_case: bool = True,
) -> list[RegexLinkBlock]:
    """Group anchors whose complete ``string(.)`` text matches ``pattern``.

    Unlike :func:`parser_linkblock`, this exploratory search has no minimum
    group-size or title-length activation threshold. A group is returned even
    when only one anchor in it matches.
    """
    flags = re.IGNORECASE if ignore_case else 0
    regex = re.compile(pattern, flags)
    dom = gpath.fromstring_with_gpath(html_text)

    groups: dict[str, list[str]] = defaultdict(list)
    seen_titles: dict[str, set[str]] = defaultdict(set)
    for elem_a in dom.xpath('//a[@href]'):
        # text_content() is the lxml equivalent of XPath string(.), so nested
        # strong/span text remains part of the title used for matching.
        text = gpath.get_text(elem_a)
        if not text or regex.search(text) is None:
            continue
        raw_xpath = gpath.get_gpath(elem_a)
        if text in seen_titles[raw_xpath]:
            continue
        seen_titles[raw_xpath].add(text)
        groups[raw_xpath].append(text)

    return [
        RegexLinkBlock(
            block_xpath=_regex_block_xpath(dom, raw_xpath),
            link_xpath=_regex_link_xpath(dom, raw_xpath),
            link_titles=titles,
        )
        for raw_xpath, titles in groups.items()
    ]
