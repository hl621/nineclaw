# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/12/26 下午4:47
import re
from collections import defaultdict
from typing import *

from .. import gpath
from ...errors import InvalidTagError

RE_PUNCTUATION = '|'.join(map(re.escape, set('''！!，,。.？?、-|；;：:“”‘’<>《》（）()[]【】'"%''')))
punctuation_match = re.compile(RE_PUNCTUATION)  # 匹配符号


def get_typical_xpaths(dom, xpath: Optional[str] = None) -> Dict[str, List[str]]:
    """ 获取所有文本的典型路径（该算法假定正文仅可能出现的标签为 p） """
    doc = defaultdict(list)
    if xpath is None:
        root = dom.getroottree()
    else:
        _ = dom.xpath(xpath)
        if not _:
            return doc
        root = _[0]
    for elem in root.iter():
        try:
            elem_path = gpath.get_gpath(elem)  # 提取 xpath 路径
        except InvalidTagError:
            pass
        else:
            elem_tag = elem.tag
            if elem_path and elem_tag in ('p', 'pre'):  # 如果路径存在且是正文常见标签
                elem_text = (elem.text or '').strip()  # 提取路径对应的文本
                sign_count = len(punctuation_match.findall(elem_text))
                if 50 < len(elem_text) < 1500 and sign_count >= 2:  # 大部分正文有标点符号且超过一定长度
                    doc[elem_path].append(elem_text)
    else:
        return doc


def _get_max_length_content_xpath(html_text) -> Optional[str]:
    """ 提取最大长度 """
    dom = gpath.fromstring_with_gpath(html_text)  # 配置泛化的 xpath
    typical_xpaths = get_typical_xpaths(dom)

    max_length = 0  # 记录最大长度
    max_length_xpath = None  # 记录最大长度对应的xpath

    for xpath, texts in typical_xpaths.items():
        text_total_length = sum(map(len, texts))  # 文本总长度
        if max_length_xpath is None:
            max_length_xpath = xpath
        elif text_total_length > max_length:
            max_length_xpath = xpath
        else:
            continue
        max_length = text_total_length

    if max_length_xpath is not None:
        return gpath.refine_unique_gpath(dom, max_length_xpath)  # 精炼 gpath


def parse_content_xpath(html_text) -> Optional[str]:
    """ 解析出正文 xpath """
    return _get_max_length_content_xpath(html_text)
