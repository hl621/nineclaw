# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/30 上午11:18
import datetime
import re
from datetime import datetime
from typing import Optional, Iterator
from zoneinfo import ZoneInfo
from loguru import logger
import dateparser
from lxml.etree import Element

from app.utils.html_extractor import utils
from .timeutils import text_to_date, is_valid_time, is_exist_time_in_text
from .. import errors

RE_DATE_FROM_SCRIPT = re.compile(r'datePublished" *: *"(([1-2][90]\d\d)[\-/]?([01]\d)[\-/]?([0-3]\d).*?)"')
RE_DATE_FROM_URL = re.compile(r'(?<=[/-])(?P<year>[1-2][90]\d\d)[\-/]?(?P<month>[01]\d)[\-/]?(?P<day>[0-3]\d)')

HTML_META_TIME_XPATHS = [
    # 包含时区
    '//meta[@name="article:published_time" or @property="article:published_time"]/@content',
    # 不含时区
    '//meta[starts-with(@property, "article:published")]/@content',
    '//meta[starts-with(@property, "publish_time")]/@content',
    '//meta[starts-with(@property, "rnews:datePublished")]/@content',
    '//meta[starts-with(@property, "og:published_time")]/@content',
    '//meta[starts-with(@property, "og:release_date")]/@content',
    '//meta[starts-with(@itemprop, "datePublished")]/@content',
    '//meta[starts-with(@itemprop, "dateUpdate")]/@content',
    '//meta[starts-with(@name, "OriginalPublicationDate")]/@content',
    '//meta[starts-with(@name, "article_date_original")]/@content',
    '//meta[starts-with(@name, "og:time")]/@content',
    '//meta[starts-with(@name, "apub:time")]/@content',
    '//meta[starts-with(@name, "publication_date")]/@content',
    '//meta[starts-with(@name, "sailthru.date")]/@content',
    '//meta[starts-with(@name, "PublishDate")]/@content',
    '//meta[starts-with(@name, "publishdate")]/@content',
    '//meta[starts-with(@name, "PubDate")]/@content',
    '//meta[starts-with(@name, "pubtime")]/@content',
    '//meta[starts-with(@name, "_pubtime")]/@content',
    '//meta[starts-with(@name, "weibo: article:create_at")]/@content',
    '//meta[starts-with(@pubdate, "pubdate")]/@content',
    '//meta[starts-with(@property, "og:updated_time")]/@content',
    '//meta[@name="DC.date.created" or @property="DC.date.created"]/@content',  # Dublin Core name title
    '//meta[@name="dc.date.created" or @property="dc.date.created"]/@content',  # Dublin Core name title
    '//meta[@name="dcterms.date" or @property="dcterms.date"]/@content',  # Dublin Core name title
]  # 高质量 xpath

TIME_VALID_TAGS = ['time', 'div', 'span', 'a', 'i', 'b', 'strong', 'em']  # 时间通常存在于这些标签


def get_date_from_url(url: Optional[str]) -> Optional[datetime]:
    """ 从 url 中提取时间信息, 这个默认时区为 UTC """
    if not url:
        return None
    m = RE_DATE_FROM_URL.search(url)
    if m:
        time_text = "{year}-{month}-{day}".format(**m.groupdict())
        return datetime.fromisoformat(time_text).replace(tzinfo=ZoneInfo('UTC'))


def get_data_from_script(html_text) -> Optional[datetime]:
    """ 从 application/ld+json 中提取时间信息 """
    dom = utils.fromstring(html_text)
    for elem in dom.xpath('//script[@type="application/ld+json"]'):
        script_text = utils.get_text_by_xpath(elem, './text()')
        if script_text:
            script_text = script_text.replace('\n', '')  # 变成一整行
            m = RE_DATE_FROM_SCRIPT.search(script_text)
            if m:
                return dateparser.parse(m.group(1))


def get_data_from_html_meta(html_text: str) -> Optional[datetime]:
    """ 从 <meta> 标签中提取时间信息 """
    dom = utils.fromstring(html_text)
    for xpath in HTML_META_TIME_XPATHS:
        time_text = utils.get_text_by_xpath(dom, xpath)
        if time_text:
            return dateparser.parse(time_text)


def filter_time_text_from_elems(elems: Iterator[Element]) -> Iterator[str]:
    """ 过滤出时间元素文本 """
    for elem in elems:
        if elem.tag in TIME_VALID_TAGS or any('time' in v for v in elem.attrib.values()):  # 标签正确或含有时间概念
            elem_text = utils.get_text_with_cache(elem)  # 需要包含子元素一起判断, 因为有些时间按照年、月、日分别拆成元素的情况
            if 4 < len(elem_text) < 50:  # 文本长度正确
                yield elem_text


def get_date_by_guess(html_text: str, content_xpath: str) -> Optional[datetime]:
    """ 从特殊类名标签中获取时间 """
    try:
        dom = utils.fromstring(html_text)
        content_elem = dom.xpath(content_xpath)[0]  # 正文元素
    except IndexError:
        raise errors.XpathElementIsNotFound(f'content_xpath={content_xpath!r} 找不到对应正文元素')
    else:
        # see more: https://lxml.de/apidoc/lxml.html.html#lxml.html.HtmlElement

        for time_text in filter_time_text_from_elems(
                utils.iter_diffusion_by_grow(content_elem, prev_max_count=40, next_max_count=10)
        ):  # 过滤出有效时间字符串
            if is_exist_time_in_text(time_text):
                time_obj = text_to_date(time_text)
                if time_obj:
                    logger.debug(f"guess publish_time from text `{time_text!r}` to `{time_obj!r}`")
                    if is_valid_time(time_obj):
                        return time_obj
