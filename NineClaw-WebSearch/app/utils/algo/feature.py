# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/28 下午3:11

from collections import Counter
from typing import Sequence, Dict, Any


def lcs_length(a: Sequence, b: Sequence) -> int:
    """Return the longest common subsequence length using linear memory."""
    if not a or not b:
        return 0
    if len(a) < len(b):
        a, b = b, a

    previous = [0] * (len(b) + 1)
    for value_a in a:
        current = [0] * (len(b) + 1)
        for index_b, value_b in enumerate(b, start=1):
            if value_a == value_b:
                current[index_b] = previous[index_b - 1] + 1
            else:
                current[index_b] = max(previous[index_b], current[index_b - 1])
        previous = current
    return previous[-1]


def lcs_ratio(a: Sequence, b: Sequence) -> float:
    """Return LCS similarity normalized by the longer sequence length."""
    if not a or not b:
        return 0.0
    return lcs_length(a, b) / max(len(a), len(b))


def LCSubstr(x: Sequence, y: Sequence) -> Sequence:
    """ 最长连续公共子序列 """
    # 相当于 np.zeros((len(X) + 1, len(Y) + 1) 不借助第三方库会更快,但也更浪费内存
    matrix = [[0] * (len(y) + 1) for _ in range(len(x) + 1)]
    max_length = 0
    start_position = 0
    for i, iv in enumerate(x, 1):
        for j, jv in enumerate(y, 1):
            if iv == jv:
                temp = matrix[i - 1][j - 1] + 1  # 比较到相同的所以+1.txt
                matrix[i][j] = temp  # 利用 _ 减少索引寻址时间
                if temp > max_length:
                    max_length = temp
                    start_position = i - max_length
            # else:
            #     matrix[i][j] = 0  # 默认就是 0
    return x[start_position:start_position + max_length]


def ngram(seq: Sequence, length: int = 2):
    """ 生成 ngram 序列 """
    return (seq[i:i + length] for i in range(len(seq) - length + 1))


def picker(S: Sequence, min_value=1) -> Dict[Any, int]:
    """ 用来挑选主分支: 可以得知大概有几条主分支,以及选中了哪些分支,每条分支支持度多少（在曲线中画一个面积最大的矩形） """
    max_score = 0
    result = {}
    solt = sorted([(k, v) for k, v in Counter(S).items() if v > min_value], key=lambda x: x[-1])
    for index, (k, v) in enumerate(solt, start=0):
        score = v * (len(solt) - index)
        if max_score < score:
            max_score = score
            result.clear()
        result[k] = v
    else:
        return result
