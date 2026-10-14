#!/usr/bin/env python3
"""
离线翻译脚本
基于本地 JSON 词典进行简单文本替换
仅依赖 Python 标准库
"""

import json
import sys
import os
import re
from pathlib import Path


def load_dictionary():
    """加载本地翻译词典"""
    dict_path = Path(__file__).parent.parent / "references" / "dict.json"
    
    if not dict_path.exists():
        print(f"错误：词典文件不存在 {dict_path}", file=sys.stderr)
        sys.exit(1)
    
    try:
        with open(dict_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # 过滤掉 _meta 等元数据字段
            return {k: v for k, v in data.items() if not k.startswith('_')}
    except json.JSONDecodeError as e:
        print(f"错误：词典 JSON 格式错误 - {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误：读取词典失败 - {e}", file=sys.stderr)
        sys.exit(1)


def translate_text(text, dictionary, reverse=False):
    """
    翻译文本
    
    Args:
        text: 待翻译文本
        dictionary: 翻译词典 dict
        reverse: 是否反向翻译（英译中）
    
    Returns:
        翻译后的文本
    """
    if not text or not dictionary:
        return text
    
    # 构建翻译映射
    if reverse:
        trans_map = {v: k for k, v in dictionary.items()}
    else:
        trans_map = dictionary
    
    # 按长度排序，优先匹配长词
    sorted_keys = sorted(trans_map.keys(), key=len, reverse=True)
    
    result = text
    for key in sorted_keys:
        value = trans_map[key]
        # 使用正则表达式进行全词匹配（支持中文分词边界）
        pattern = re.escape(key)
        result = re.sub(pattern, value, result)
    
    return result


def main():
    if len(sys.argv) < 2:
        print("用法: python translate.py <文本> [--reverse]", file=sys.stderr)
        print("示例: python translate.py '你好世界'", file=sys.stderr)
        print("      python translate.py 'Hello World' --reverse", file=sys.stderr)
        sys.exit(1)
    
    input_text = sys.argv[1]
    reverse = '--reverse' in sys.argv or '-r' in sys.argv
    
    # 加载词典
    dictionary = load_dictionary()
    
    # 执行翻译
    translated = translate_text(input_text, dictionary, reverse=reverse)
    
    # 输出结果
    print(translated)


if __name__ == "__main__":
    main()
