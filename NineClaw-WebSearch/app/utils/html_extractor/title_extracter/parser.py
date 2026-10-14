import re
from typing import Optional

from .. import utils

__all__ = (
    'get_title_from_html',  # 解析出 title
)

RE_STR_STRIP = re.compile(r'[\n\t\r\xa0\u3000 ]+')
RE_SPLIT_TITLE = re.compile(r'(?:[ ][|\-_–>][ ])|(?:\:[ ])')
TITLE_XPATHS = [
    '//meta[@name="title" or @property="title"]/@content',  # Meta name title
    '//meta[@name="og:title" or @property="og:title"]/@content',  # Open Graph name title
    '//meta[@name="twitter:title" or @property="twitter:title"]/@content',  # Twitter name title
    '//meta[@name="dc.title" or @property="dc.title"]/@content',  # Dublin Core name title
    '//meta[@name="DC.title" or @property="DC.title"]/@content',  # Dublin Core name title
    '//title//text()',
    '(//h1)[1]',
]  # 高质量 xpath


def get_title_from_html(html_text: str) -> Optional[str]:
    """ 从 <meta> 标签中提取标题 """
    dom = utils.fromstring(html_text)
    for xpath in TITLE_XPATHS:
        title_text = utils.get_text_by_xpath(dom, xpath)
        if title_text:
            return title_text
