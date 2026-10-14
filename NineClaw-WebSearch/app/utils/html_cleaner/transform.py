# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/29 下午2:57
from . import utils


def refine_html_text(html_text):
    """ 删除正文无关的标签 """
    # 清洗掉注释
    html_text = utils.remove_comments(html_text)

    # 删除不含正文价值的标签（有些网站会把正文放 textarea 中）
    return utils.remove_tags_with_content(html_text, which_ones=[
        'script', 'noscript', 'link', 'meta', 'head', 'style',  # 铁定不是的
        'video', 'audio', 'figure', 'table', 'aside', 'nav', 'template',  # 有明确含义的或处理不了的
        'input', 'select', 'button', 'datalist', 'keygen', 'meter', 'output'  # 功能性明确的标签('textarea'被广泛误用，不能删)
    ])


def remove_html_tags(html_text):
    # 保留有换行意义的标签
    html_text = utils.remove_tags(html_text, keep=[
        'div', 'br', 'hr', 'tr', 'p', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',  # html
        'pre', 'article', 'header', 'section', 'code', 'main'  # html5
    ])

    # 将这些标签转换成 \n
    html_text = utils.replace_tags(html_text, '\n')

    # 符号紧凑化
    html_text = utils.sign_compaction(html_text)
    return html_text


def clean_html_to_text(html_text, remove_invisible=True, fix_unpaired=False):
    """ 将 html 转换为 text, 若 soft=True 速度会快十倍 """
    if not html_text:
        return html_text
    # 符号标准化
    html_text = utils.normalize_html_text(html_text)

    # 修复破损标签(非常耗时)
    if fix_unpaired:
        html_text = utils.fix_html_unpaired_tags(html_text)

    # 复原有转义的 html 标签
    html_text = utils.replace_entities(html_text)

    # 清除不可见标签(比较耗时)
    if remove_invisible:
        html_text = utils.clean_invisible_tags(html_text)

    # 删除解析不了标签
    html_text = refine_html_text(html_text)

    # 删除 html 标签
    html_text = remove_html_tags(html_text)

    return html_text.strip()
