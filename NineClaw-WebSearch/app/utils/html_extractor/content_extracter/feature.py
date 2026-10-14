# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/28 下午3:45
import re
from typing import List

RE_DISPLAY_NONE = re.compile(r'display[ ]*:[ ]*none', flags=re.I)
RE_MATCH_HASH = re.compile(r'^[0-9A-Fa-f]{32,}$')
RE_MATCH_UUID = re.compile(r'[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}')
RE_MATCH_STRING = re.compile(r'^[0-9A-z]{8,}$')
RE_MATCH_UPPER = re.compile(r'[A-Z]')
RE_MATCH_LOWER = re.compile(r'[a-z]')
RE_MATCH_DIGITAL = re.compile(r'[0-9]')


def is_robot_create_name(text: str) -> bool:
    """ 判断是否由是机器生成的标签: SzZmKb R9GLFb BY2RHc _2ssoa1 _3dvb2i d0hShY
    机器标签特征：
    1. 由于 数字、大写字母、小写字母构成
    2. strip 去掉 _ 符号后, 长度不超过6位
    3. 全小写、首字母大写、字符串内部含有 “-_” 的正常情况之外的其他情况
    """
    if text and (text.startswith('_') or text[0].isdigit()):
        return True  # 直接判断情况(一般 _打头是约定的私有变量, 数字开头一般是机器生成)
    elif RE_MATCH_UUID.search(text):  # 有明显的 uuid 格式
        return True
    substrs = re.split(r'[_-]', text)
    if len(substrs) > 1:  # 如果有多个子串
        return any(is_robot_create_name(sub) for sub in substrs)  # 递归判断各个子成分
    else:
        if not (text.isupper() or text.islower() or text.istitle()):  # 排除正常情况
            return True
        elif RE_MATCH_HASH.match(text):  # 有强烈16特征的长序列,md5至少有32位,其他算法更长
            return True
        elif RE_MATCH_STRING.match(text):  # 由于 数字、大写字母、小写字母构成的长序列
            has_upper = bool(RE_MATCH_UPPER.search(text))
            has_lower = bool(RE_MATCH_LOWER.search(text))
            has_digital = bool(RE_MATCH_DIGITAL.search(text))
            if [has_upper, has_lower, has_digital].count(True) >= 2:  # 三个满足两个
                return True
    return False


def filter_not_robot_created_names(texts: List[str]) -> List[str]:
    """ 过滤出非机器创造的标签 """
    _return = []
    for text in texts:
        if not is_robot_create_name(text):
            _return.append(text)
    return _return


if __name__ == '__main__':
    from sheen import Str

    texts = ['SzZmKb', 'R9GLFb', '_2ssoa1', 'd0hShY', 'ma1n', 'a-slo1', 'ep2nwvo0',
             'CMbE8bzmif0CFdeC6QUd4HYOdQ', '75e13bfa8ccca9a6fb50df6c30a4bfb1', 'u1',
             '4CA6DE6A', 'Main-Content', 'tts-title', '1ocoo3l', 'ssrcss-1ocoo3l-Wrap',
             'caas-art-6452e2f8-3be1-3708-b008-1c84a465c9ae', 'dpu8C', '_2kCxD']
    # texts = ['ssrcss-1ocoo3l-Wrap']
    for text in texts:
        is_robot = is_robot_create_name(text)
        print(Str.red(text) if is_robot else Str.green(text))
    else:
        print(filter_not_robot_created_names(texts))
