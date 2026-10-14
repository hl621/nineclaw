# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/30 上午11:16
import re
from datetime import datetime
from typing import Optional

import dateparser

RE_YEAR = re.compile(r'\D*([1-2][90]\d\d|[2-3]\d)\D*', flags=re.IGNORECASE | re.DOTALL)  # 这个 [2-3]\d 代表 2020~2039 年
RE_MONTH = re.compile(r'\D*(\d|0\d|1[0-2])\D*', flags=re.IGNORECASE | re.DOTALL)
RE_DAY = re.compile(r'\D*(\d|[0-2]\d|3[0-1])\D*', flags=re.IGNORECASE | re.DOTALL)
RE_TIME = re.compile(r'\D*([0-2]?\d):[0-6]\d\D*', flags=re.IGNORECASE | re.DOTALL)

# 当做词语来处理
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'January', 'February',
          'Febr', 'March', 'April', 'May', 'June', 'July', 'August', 'Sept', 'October', 'November', 'December',
          'September']
WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
            'Saturday', 'Sunday', 'Thurs', 'Tues']
HMS = ["hour", "hours", "minute", "minutes", "second", "seconds"]
PREPOSITION = ["at", "on", "and", "ad", "m", "t", "of", "st", "nd", "rd", "th", 'of']
RE_PATTERN_WORDS = [rf'\b{re.escape(i)}\b' for i in MONTHS + WEEKDAYS + HMS + PREPOSITION]

# 处理含有正则内容
AMPM = [rf'\b{i}\b' for i in ['A', 'AM', 'a', 'am', 'P', 'PM', 'p', 'pm']]
UTCZONE = ['UTC', 'GMT', r'\dT\d', r'\dz', r'\dZ', '[A-Z]{1,3}T']
DATE_PATTERN = [r'\d+', r'\d*:\d*', r"\dm", r"\dh", r"\ds", '[年月日]', r'[ .,;\-\\/\'+-]']
RE_PATTERN_SIGNS = AMPM + DATE_PATTERN + UTCZONE

# 凡是匹配到这些词语都能留下
RE_DATE_STRIP = re.compile('|'.join(RE_PATTERN_WORDS + RE_PATTERN_SIGNS), flags=re.DOTALL)


def check_overlap(intervals):
    """ 判断区域之间是否有重叠 """
    intervals.sort(key=lambda x: x[0])  # 按照起始位置排序
    for i in range(1, len(intervals)):
        if intervals[i][0] <= intervals[i - 1][1]:  # 存在重叠
            return True
    return False


def is_exist_time_in_text(time_text: str) -> bool:
    """ 判断 text 中是否可能存在时间 """
    matched_year = RE_YEAR.search(time_text)
    matched_month = RE_MONTH.search(time_text)
    matched_day = RE_DAY.search(time_text)
    matched_time = RE_TIME.search(time_text)
    digit_count = sum(char.isdigit() for char in time_text)

    if digit_count <= 4:  # 如果数字个数太少就不用尝试了
        return False
    elif all([matched_year, matched_month, matched_day]) \
            and check_overlap([matched_year.span(1), matched_month.span(1), matched_day.span(1)]) is False:
        return True
    elif matched_time and any([matched_year, matched_month, matched_day]):
        return True
    else:
        return False


def filter_time_text(text: str) -> str:
    """ 过滤出时间相关的数据 """
    time_text = ''
    for each in RE_DATE_STRIP.finditer(text):
        time_text += each.group(0)
    else:
        return time_text.strip(' /\\-:.')


def text_to_date(text: str) -> Optional[datetime]:
    """ 将文本时间字符转换为 date """
    if text:
        time_text = filter_time_text(f' {text} ')  # 只保留与时间相关的字符串
        time_obj = dateparser.parse(time_text)  # 解析时间字符串
        if time_obj:
            return time_obj


def is_valid_time(target_date: Optional[datetime] = None) -> bool:
    """ 判断时间合法性 """
    if target_date:  # 时间合法性检测
        if target_date < datetime(1970, 1, 2, tzinfo=target_date.tzinfo):
            return False  # 1970-01-01 很多时候是缺省数据, 没有价值(我们认为只要是这天的数据都没有价值)
        elif target_date > datetime.now(tz=target_date.tzinfo):
            return False  # 未来时间默认为错误数据，爬虫采集的新闻不可能是未来发布的
        else:
            return True
    else:
        return False


if __name__ == '__main__':
    time_text = '— (Little) Think Tank (@L_ThinkTank) 2023-12-27 07:22'
    print(time_text)
    time_text = text_to_date(time_text)
