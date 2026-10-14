import re
from typing import Optional
from zoneinfo import ZoneInfo

from .content_extracter import parse_content
from .media_extracter import parse_media
from .publish_extracter import parse_publish_date
from .schema import ExtractResult
from .title_extracter import parse_title
from .utils import is_chinese


def clean_title(title_text: Optional[str]) -> Optional[str]:
    """ 清洗标题：合并空白与换行、去除首尾空格 """
    if not title_text:
        return title_text
    return re.sub(r'\s+', ' ', title_text).strip()


def detect_language(title_text: str) -> Optional[str]:
    """ 对标题文本检测语言 """
    return 'zh' if is_chinese(title_text, ratio=0.45) else None


def detect_tzinfo(language: str) -> ZoneInfo:
    """ 根据语言类型推断默认时区 """
    return ZoneInfo('Asia/Shanghai') if language == 'zh' else ZoneInfo('UTC')


def extract_info_from_html(html_text: str, url: str = None) -> ExtractResult:
    """ 从网页中提取信息"""
    # extract title
    title_text = clean_title(parse_title(html_text))
    _return = ExtractResult(url=url, title=title_text)

    # extract content
    _return.content = parse_content(html_text)

    if _return.content:
        # detect language
        _return.language = detect_language((title_text or '') + (_return.content.content_text or '')[:200])

        # extract publish
        default_tzinfo = detect_tzinfo(_return.language)
        _return.publish_date = parse_publish_date(html_text=html_text, url=url,
                                                  content_xpath=_return.content.content_xpath,
                                                  default_tzinfo=default_tzinfo)

        # extract media
        _return.media = parse_media(html_text, url=url, content_xpath=_return.content.content_xpath)
    return _return
