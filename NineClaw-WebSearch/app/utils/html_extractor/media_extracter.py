import re

from .schema import MediaExtractResult
from .utils import get_code_from_html_by_xpath, fromstring
from urllib.parse import urljoin, urlparse


def to_full_url(base_url, url):
    if url.startswith('://'):
        return urlparse(base_url).scheme + url
    else:
        return urljoin(base_url, url)


def parse_media(
        html_text: str,
        url: str,
        content_xpath: str,
) -> MediaExtractResult:
    """ 从给定的 html_text 与 url 中抽取发布时间 """
    content_html = get_code_from_html_by_xpath(html_text, content_xpath)
    _return = MediaExtractResult()
    if content_html.strip():
        dom = fromstring(content_html)

        for img_elem in dom.xpath('.//img[not(ancestor::a)]'):  # 文中配图一般不可点击
            img_url = img_elem.attrib.get('src') or img_elem.attrib.get('data-src')
            if isinstance(img_url, str) and not img_url.startswith('data:'):
                _return.image_urls.add(to_full_url(url, img_url))

        for video_elem in dom.xpath('.//video'):
            video_url = video_elem.attrib.get('src') or video_elem.attrib.get('data-src')
            if video_url:
                _return.video_urls.add(to_full_url(url, video_url))

        for file_match in re.finditer(r'https?://\S+?\.pdf', content_html, flags=re.MULTILINE | re.IGNORECASE):
            if file_match:
                file_url = file_match.group()
                if file_url.count('://') == 1:
                    _return.file_urls.add(to_full_url(url, file_url))
    return _return
