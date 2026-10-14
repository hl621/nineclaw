from .content_extracter import parse_content
from .extract import extract_info_from_html
from .media_extracter import parse_media
from .linkblock_extracter import grep_linkblock, parser_linkblock
from .publish_extracter import parse_publish_date
from .title_extracter import parse_title
from .utils import (
    clean_html_for_structure,
    get_code_from_html_by_xpath,
    get_codes_from_html_by_xpath,
    get_text_from_html_by_xpath,
    html_to_compact_dom_tree,
)

__all__ = (
    'parse_content',  # 提取正文
    'parse_publish_date',  # 提取发布时间
    'parse_title',  # 提取标题
    'parse_media',  # 提取媒体
    'parser_linkblock',  # 提取列表
    'grep_linkblock',  # 用正则匹配完整链接文本
    'extract_info_from_html',  # 综合提取
    'clean_html_for_structure',  # 清洗用于观察结构的 HTML
    'get_code_from_html_by_xpath',  # 提取代码
    'get_codes_from_html_by_xpath',  # 提取多段代码
    'get_text_from_html_by_xpath',  # 提取文本
    'html_to_compact_dom_tree',  # HTML 转紧凑 DOM 树
)
