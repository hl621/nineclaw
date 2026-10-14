# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/28 下午3:08
# 正文抽取
from typing import List, Literal

from app.utils.html_extractor.utils import get_text_from_html_by_xpath
from .extract import (parse_content_xpath_by_fast_desc,
                      parse_content_xpath_by_sign_density,
                      parse_content_xpath_by_max_length)
from ..schema import ContentExtractResult

__all__ = (
    'parse_content_xpath_by_fast_desc',  # 快速匹配法获取正文 xpath
    'parse_content_xpath_by_sign_density',  # 符号密度法获取正文 xpath
    'parse_content_xpath_by_max_length',  # 最大长度获取正文 xpath
    'parse_content',  # 综合抽取
)


def parse_content(
        html_text: str,
        allow_algos: List[Literal["fast", "sign"]] = None  # 允许使用的算法
) -> ContentExtractResult | None:
    if allow_algos is None:
        allow_algos = ['fast', 'sign', 'maxlen']  # 默认使用的算法

    for algo_name in allow_algos:
        if algo_name == 'fast':
            content_xpath = parse_content_xpath_by_fast_desc(html_text)
        elif algo_name == 'maxlen':
            content_xpath = parse_content_xpath_by_max_length(html_text)
        elif algo_name == 'sign':
            content_xpath = parse_content_xpath_by_sign_density(html_text)
        else:
            content_xpath = None

        if content_xpath:
            return ContentExtractResult(
                algorithm=algo_name,
                content_xpath=content_xpath,
                content_text=get_text_from_html_by_xpath(
                    html_text,
                    xpath=content_xpath,
                    noise_xpaths=[])
            )
