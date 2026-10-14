# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/30 上午11:12
from typing import Optional, Literal, List
from zoneinfo import ZoneInfo

from .parser import get_data_from_script, get_data_from_html_meta, get_date_from_url, get_date_by_guess
from .timeutils import text_to_date, is_valid_time
from ..schema import PublishDateExtractResult

__all__ = (
    'parse_publish_date',  # 解析出发布时间
    'text_to_date',  # 从文本中解析出时间
)


def parse_publish_date(
        html_text: str,
        url: Optional[str] = None,
        content_xpath: Optional[str] = None,
        allow_algos: List[Literal["meta", "script", "url", "guess"]] = None,  # 允许使用的算法
        default_tzinfo: ZoneInfo = ZoneInfo('UTC'),
) -> PublishDateExtractResult | None:
    """ 从给定的 html_text 与 url 中抽取发布时间 """
    if allow_algos is None:
        allow_algos = ["meta", "script", "url", "guess"]

    for algo_name in allow_algos:
        if algo_name == "meta":
            publish_date = get_data_from_html_meta(html_text)
        elif algo_name == 'script':
            publish_date = get_data_from_script(html_text)
        elif algo_name == 'url' and url:
            publish_date = get_date_from_url(url)
        elif algo_name == 'guess' and content_xpath:
            publish_date = get_date_by_guess(html_text, content_xpath=content_xpath)
        else:
            publish_date = None

        if publish_date:
            if not publish_date.tzinfo:  # 设置默认时区
                publish_date = publish_date.replace(tzinfo=default_tzinfo)

            if is_valid_time(publish_date):  # 如果是合法时间才采纳
                return PublishDateExtractResult(algorithm=algo_name, datetime=publish_date)
