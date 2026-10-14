# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/28 下午4:13
from typing import Optional

from app.utils.algo import ngram, picker
from .. import gpath
from ...utils import get_text_by_xpath


def _get_desc_text(dom):
    """ 获取描述信息 """
    root = dom.getroottree()
    desc_xpath = '//meta[contains(@name,"description") or contains(@property,"description")]/@content'
    desc_text = get_text_by_xpath(root, desc_xpath)
    if not desc_text:
        return None
    elif len(desc_text) < 15:
        return None
    else:
        return desc_text


def _get_content_elems(dom, desc_text: str):
    """ 获取正文元素 """
    root = dom.getroottree()
    result = {}
    A = set(ngram(desc_text, 5))
    for elem in root.xpath('(//article | //div[@id or @class])//p'):
        if elem.tag == 'p':
            elem_text = elem.text_content()
            B = set(ngram(elem_text[:len(desc_text)], 5))
            score = len(A & B) / len(A | B)
            if score > 0.1:
                result[elem] = score

    return picker(result, min_value=0.1)


def parse_content_xpath(html_text) -> Optional[str]:
    """ 解析出正文 xpath """
    dom = gpath.fromstring_with_gpath(html_text)
    desc_text = _get_desc_text(dom)  # 获取描述信息
    if desc_text:
        for elem in _get_content_elems(dom, desc_text):
            xpath = gpath.get_gpath(elem)  # 提取 gpath
            xpath = gpath.refine_unique_gpath(dom, xpath)  # 精炼 gpath
            # 因为快速语意抽取虽然能把正文抽对，但给出xpath通用性很不靠谱，所以需要检查下 xpath 的质量
            if gpath.is_high_quality_xapth(xpath):
                # print(xpath)
                return xpath
