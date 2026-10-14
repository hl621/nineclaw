# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/28 下午3:14
# 网页清洗
from .transform import clean_html_to_text, refine_html_text, remove_html_tags

__all__ = (
    'clean_html_to_text',  # 将 html 转换为 text
    'remove_html_tags',  # 删除 html 标签
    'refine_html_text',  # 删除正文无关的标签
)
