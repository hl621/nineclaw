# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/28 下午3:24
import unicodedata

import html5lib
import lxml.html as lxml_html
from lxml import etree as lxml_etree
from w3lib.html import *

HIDDEN_FEATURE = [
    r'display:none',
    r'visibility:hidden',
    r'opacity:0',
    r'width:0px.*height:0px',
    r'height:0px.*width:0px',
    r'overflow:hidden.*width:0px',
    r'overflow:hidden.*height:0px',
    r'width:0px.*overflow:hidden',
    r'height:0px.*overflow:hidden',
]
RE_DISPLAY_NONE = re.compile('|'.join(map(lambda x: re.sub(r' *: *', r' *: *', x), HIDDEN_FEATURE)),
                             flags=re.IGNORECASE | re.DOTALL)


def clean_invisible_tags(html_text: str):
    """ 清除不可见标签 """
    # 有较为明确的标题、正文含义的不用移除
    exclude_tags = ('p', 'pre', 'article', 'header', 'section', 'code', 'main', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6')
    try:
        dom = lxml_html.fromstring(html_text)
    except lxml_etree.ParserError:
        return ''
    else:
        for elem in dom.iter():
            if elem.tag not in exclude_tags and RE_DISPLAY_NONE.search(elem.attrib.get('style', '')):
                elem.drop_tree()
        return lxml_html.tostring(dom, encoding='unicode', with_tail=True)


def normalize_html_text(text: str):
    """ html 符号标准化 """
    text = unicodedata.normalize('NFKC', text)
    text = replace_escape_chars(text, which_ones=['\xa0', '\u3000', '\u200b'], replace_by=u' ')
    return text


def fix_html_unpaired_tags(html_text: str):
    """ 修理 html 未配对标签 """
    dom = html5lib.parse(html_text)
    omit_optional_tags = False if 'html' in html_text or 'body' in html_text else True
    html_text = html5lib.serialize(dom, omit_optional_tags=omit_optional_tags)
    return html_text


def sign_compaction(text: str):
    """ 符号紧凑化 """
    text = re.sub(r'[ \t]+', r' ', text)
    text = re.sub(r' *[\r\n] *', r'\n', text)
    text = re.sub(r'\n\n+', r'\n\n', text)
    return text


if __name__ == '__main__':
    html_text = '<div><div id="7009502" class="ad" style="visibility:hidden;height:0;overflow:hidden;">hello world!</div>xxx</div>'
    print(clean_invisible_tags(html_text))
