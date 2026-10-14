# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/28 下午4:30

from copy import deepcopy
from typing import Optional

from gne import ContentExtractor
from gne.utils import pre_parse

from .. import gpath


def _remove_known_noise(dom):
    """ 移除已知的不是正文的内容 """
    # aside 标签是通常是新闻网站的侧栏推荐（这个 gne 处理不好，所以单拧出来处理一下） (comment)
    for elem in dom.xpath('//aside | //figure | //*[re:match(@class, "[cC]opy[rR]ight|[cC]omment|[sS]hare")]',
                          namespaces={"re": "http://exslt.org/regular-expressions"}):
        parent = elem.getparent()
        parent.remove(elem)
    return dom


def _get_content_element(dom):
    """ 获取正文元素 """
    try:
        dom = pre_parse(dom)
        content = ContentExtractor().extract(dom,
                                             host='',
                                             body_xpath='',
                                             with_body_html=True,
                                             use_visiable_info=False)
        return content[0][1]['node']
    except Exception:
        return None


def parse_content_xpath(html_text) -> Optional[str]:
    """ 基于符号密度实现正文解析 """
    dom = gpath.fromstring_with_gpath(html_text)
    _dom = deepcopy(dom)  # 创建一个副本供之后的函数去对dom有操作的算法
    # 移除噪音
    _remove_known_noise(_dom)
    # gne 的方法获取正文元素
    elem = _get_content_element(_dom)
    if elem is not None:
        xpath = gpath.get_gpath(elem)  # 提取 gpath
        xpath = gpath.refine_unique_gpath(dom, xpath)  # 精炼 gpath
        if gpath.is_high_quality_xapth(xpath):
            return xpath
