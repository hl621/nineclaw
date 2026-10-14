# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/7/13 上午9:07
from functools import partial
from itertools import chain, zip_longest
from typing import List
from collections import deque
import lxml.html as lxml_html
from w3lib.html import replace_entities
from lxml.etree import iselement, Element
from app.utils.html_cleaner import clean_html_to_text
from functools import lru_cache
import regex as re

RE_CHINESE = re.compile(r'[\u4e00-\u9fa5]')
RE_CHINESE_OR_SIGN = re.compile(r'''(?=[\u4e00-\u9fa5])|[！!，,。.？?、\-|；;：:“”‘’<>《》（）()\[\]【】'"%\s]+''')
RE_EMOJI = re.compile("["
                      u"\U0001F600-\U0001F64F"  # emoticons
                      u"\U0001F300-\U0001F5FF"  # symbols & pictographs
                      u"\U0001F680-\U0001F6FF"  # transport & map symbols
                      u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                      "]+", flags=re.UNICODE)

# \X 匹配一个扩展字形集群（Grapheme Cluster，处理复杂的 Emoji 和组合字符）
# \p{WB:ALetter} 匹配 UAX #29 定义的字母类属性
# \p{WB:Hebrew_Letter} 匹配希伯来语特有边界
# \p{WB:Numeric} 匹配数字
# \p{Script=Han} / \p{Script=Hiragana} / \p{Script=Katakana} 显式捕获中日韩等“单字即词”的特征
RE_UAX29 = re.compile(r"""
        (
            \p{WB:ALetter}+      # 连续的西方字母
            | \p{WB:Numeric}+    # 连续的数字
            | \p{Script=Han}     # 单个汉字（中文一字一词）
            | \p{Script=Hiragana}+  # 平假名片段
            | \p{Script=Katakana}+  # 外来语片假名连续片段
            | \p{Script=Thai}+   # 泰语片段（注意：UAX #29 对泰语只能切到语族边界，深层断词仍需字典）
        )
    """, re.VERBOSE)


def tokenizer_chinese_or_sign(text):
    """ 按照中文和标点符号进行分词 """
    return RE_CHINESE_OR_SIGN.split(text)


def is_chinese(text, ratio=0.6) -> bool:
    """ 判断是否为中文为主体 """
    chinese_char_count = len(RE_CHINESE.findall(text))
    tokenizer_result_count = len(tokenizer_chinese_or_sign(text))
    if isinstance(text, str):
        return (chinese_char_count / tokenizer_result_count) > ratio
    else:
        return False


def uax29_word_count(text: str) -> int:
    """
    基于 Unicode UAX #29 标准的通用字数/词数统计
    """
    return len(RE_UAX29.findall(text)) if text else 0


def remove_emojis(text):
    """ 移除表情符号 """
    # TODO: 表情符号有可能蕴含语义，未来看看怎么调整不要这么简单粗暴的删除
    return RE_EMOJI.sub(r'', text)


def fromstring(html_text: str):
    """ 用来增强 lxml_html.fromstring 用法 """
    html_text = remove_emojis(html_text)  # 经验发现，如果文本中包含表情符号会直接导致解析为空文档
    parser = lxml_html.HTMLParser(remove_comments=True)  # 设置默认的解析器
    safe_html_text = html_text[html_text.find('<'):html_text.rfind('>') + 1]  # html 一定是 < 开头 > 结尾
    return lxml_html.fromstring(html=replace_entities(safe_html_text), parser=parser)


tostring = partial(lxml_html.tostring, encoding='unicode', with_tail=True)


def get_text_by_xpath(root, xpath):
    """ 获取单条文本 """
    x = root.xpath(xpath)
    if len(x) >= 1:
        if isinstance(x[0], str):
            return x[0]
        else:
            return x[0].text_content()
    else:
        return None


def __postorder_traversal(elem: Element, preceding=True):
    """ 后序遍历: preceding 控制遍历方向 """
    for sub_elem in elem.iterchildren(reversed=preceding):
        yield from __postorder_traversal(sub_elem)
    yield elem


def iter_prev(elem: Element):
    """ 向前迭代 """
    prev_elem = elem.getprevious()
    parent_elem = elem.getparent()
    if prev_elem is not None:  # 有前向前
        yield from __postorder_traversal(prev_elem)
        yield from iter_prev(prev_elem)
    elif parent_elem is not None:  # 没前向上
        yield parent_elem
        yield from iter_prev(parent_elem)


def __iter_next(elem: Element):
    next_elem = elem.getnext()
    parent_elem = elem.getparent()
    if next_elem is not None:  # 有后向后
        yield from iter_next(next_elem)
    elif parent_elem is not None:  # 没前向上再向后
        yield from __iter_next(parent_elem)


def iter_next(elem: Element):
    """ 向后迭代 """
    yield from __postorder_traversal(elem, False)
    yield from __iter_next(elem)


def iter_limit(elems: Element, max_count: int = None):
    """ 限制迭代数量 """
    if max_count is None:
        return elems
    else:
        for index, elem in enumerate(elems, start=1):
            if index > max_count:  # 控制迭代长度
                break
            yield elem


def iter_diffusion_by_grow(elem: Element, prev_max_count=30, next_max_count=10):
    """ 弥漫展开：按照叶子节点向根节点生长(好处是见到的文本都是逐渐变大的) """
    before = iter_limit(iter_prev(elem), max_count=prev_max_count)  # 向前迭代
    after = iter_limit(iter_next(elem), max_count=next_max_count)  # 向后迭代
    return filter(iselement, chain(*zip_longest(before, after)))  # 弥漫展开


def iter_diffusion_by_order(elem: Element, prev_max_count=15, next_max_count=15):
    """ 弥漫展开：按照 first deep 的顺序(与 iter 整体遍历效果一致) """
    before = deque(maxlen=prev_max_count)  # 向前可视长度
    after = []  # 正文后观察几个
    match_after_max_count = next_max_count
    match_content = False  # 匹配到正文
    root = elem.getroottree()
    for e in root.iter():
        # 获取标签内文本与尾部跟着的文本
        if e == elem:
            match_content = True

        if match_content is False:  # 匹配之前
            before.append(e)
        elif len(after) < match_after_max_count:  # 匹配之后
            after.append(e)
        else:  # match_after 记录满了就退出
            break

    before.reverse()  # 序列翻转
    return filter(iselement, chain(*zip_longest(before, after)))  # 从中间向两边展开


@lru_cache()
def get_text_with_cache(elem: Element) -> str:
    """ 有缓存加速的提取文本 """
    prefix_text = elem.text or ''
    suffix_text = elem.tail or ''
    if len(elem):  # 如果有子节点
        text = ''
        for sub_elem in elem.iterchildren():
            text += get_text_with_cache(sub_elem)
        else:
            return ' '.join([prefix_text.strip(), text.strip(), suffix_text.strip()])
    else:
        return prefix_text.strip() + ' ' + suffix_text.strip()


def get_code_from_html_by_xpath(html_text: str, xpath: str, noise_xpaths: List[str] = None) -> str:
    """ 利用 html 中利用 xpath 获取部分代码 """
    try:
        dom = fromstring(html_text)
        # 获取正文
        target = dom.xpath(xpath)[0]

        # 删除噪音(在正文范围上操作)
        if noise_xpaths:
            for noise_xpath in noise_xpaths:
                for elem in target.xpath(noise_xpath):
                    elem.drop_tree()
    except IndexError:
        return ''
    else:
        return tostring(target)


def get_codes_from_html_by_xpath(html_text: str, xpath: str) -> List[str]:
    """返回 xpath 命中的全部局部 HTML；标量结果转换为字符串。"""
    dom = fromstring(html_text)
    matches = dom.xpath(xpath)
    if not isinstance(matches, list):
        matches = [matches]
    return [tostring(item) if iselement(item) else str(item) for item in matches]


def clean_html_for_structure(
        html_text: str,
        allowed_attributes=('class', 'id', 'href', 'data-testid'),
        max_attribute_length=30,
) -> str:
    """精简局部 HTML 属性，保留 DOM 层级和文本以便观察结构。"""
    try:
        root = fromstring(html_text)
    except Exception:
        # XPath 也可能返回字符串、数字等标量，此时保持原值。
        return html_text

    allowed = set(allowed_attributes)
    for elem in root.iter():
        for attribute in list(elem.attrib):
            if attribute not in allowed:
                del elem.attrib[attribute]
                continue
            value = elem.attrib[attribute]
            if len(value) > max_attribute_length:
                elem.attrib[attribute] = value[:max_attribute_length] + '...'
        if isinstance(elem.tag, str) and elem.tag.lower() == 'script':
            # 保留脚本节点在 DOM 中的位置，但省略无助于观察结构的代码。
            for child in list(elem):
                elem.remove(child)
            elem.text = '...'
    return tostring(root)


def _compact_dom_selector(elem: Element) -> str:
    selector = str(elem.tag)
    if elem.attrib.get('id'):
        selector += '#' + elem.attrib['id']
    if elem.attrib.get('class'):
        selector += ''.join(
            '.' + class_name
            for class_name in elem.attrib['class'].split()
        )
    markers = [
        name
        for name in ('href', 'data-testid')
        if elem.attrib.get(name) is not None
    ]
    if markers:
        selector += ' [' + ', '.join(markers) + ']'
    return selector


def _compact_dom_signature(elem: Element, depth=3):
    """生成忽略文本和属性值的结构签名，用于折叠同构兄弟节点。"""
    selector = _compact_dom_selector(elem)
    # 有明确 id/class/data-testid 的节点以自身语义特征分组，允许其内部
    # 存在广告、徽标等细微差异；无特征包装节点再通过子结构区分。
    if any(elem.attrib.get(name) for name in ('id', 'class', 'data-testid')):
        return selector
    if depth <= 0:
        return selector
    return (
        selector,
        tuple(
            _compact_dom_signature(child, depth - 1)
            for child in elem
            if isinstance(child.tag, str)
        ),
    )


def _compact_dom_text(elem: Element, max_text_length=75) -> str:
    children = [child for child in elem if isinstance(child.tag, str)]
    # 链接、段落等文本语义节点即使包含 strong/span 等后代，也展示完整
    # string(.)，避免模型误把强调节点当作标题或正文提取目标。
    full_text_tags = {
        'a', 'p', 'cite', 'button', 'label', 'time', 'option',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'td', 'th',
    }
    uses_full_text = not children or str(elem.tag).lower() in full_text_tags
    text = elem.text_content() if uses_full_text else (elem.text or '')
    text = ' '.join(text.split())
    if not text:
        return ''
    if len(text) > max_text_length:
        text = text[:max_text_length] + '...'
    text = text.replace('\\', '\\\\').replace('"', '\\"')
    operator = ' -> string(.) ' if children and uses_full_text else ' -> '
    return f'{operator}"{text}"'


def _compact_dom_chain(elem: Element):
    """压缩无属性、无文本的简单包装节点，如 nav > ul.xxx。"""
    labels = [_compact_dom_selector(elem)]
    current = elem
    compressible_tags = {'nav', 'li', 'div', 'span'}
    while (
        current.tag in compressible_tags
        and not current.attrib
        and not (current.text or '').strip()
    ):
        children = [child for child in current if isinstance(child.tag, str)]
        if len(children) != 1:
            break
        current = children[0]
        labels.append(_compact_dom_selector(current))
    return ' > '.join(labels), current


def html_to_compact_dom_tree(html_text: str, max_depth=10) -> str:
    """将局部 HTML 转换为带重复节点折叠的紧凑 DOM 树。"""
    cleaned_html = clean_html_for_structure(html_text)
    try:
        root = fromstring(cleaned_html)
    except Exception:
        return cleaned_html

    lines = []

    def render(elem, prefix='', is_last=True, depth=0, count=1, is_root=False):
        label, display_elem = _compact_dom_chain(elem)
        if count > 1:
            label += f' (x{count} 节点折叠)'
        label += _compact_dom_text(display_elem)
        connector = '' if is_root else ('└─ ' if is_last else '├─ ')
        lines.append(prefix + connector + label)

        children = [
            child for child in display_elem
            if isinstance(child.tag, str)
        ]
        if not children:
            return
        child_prefix = prefix if is_root else prefix + ('   ' if is_last else '│  ')
        if depth >= max_depth:
            lines.append(child_prefix + '└─ ...')
            return

        grouped = []
        positions = {}
        for child in children:
            signature = _compact_dom_signature(child)
            if signature in positions:
                grouped[positions[signature]][1] += 1
            else:
                positions[signature] = len(grouped)
                grouped.append([child, 1])

        for index, (child, child_count) in enumerate(grouped):
            render(
                child,
                prefix=child_prefix,
                is_last=index == len(grouped) - 1,
                depth=depth + 1,
                count=child_count,
            )

    render(root, is_root=True)
    return '\n'.join(lines)


def get_text_from_html_by_xpath(html_text: str, xpath: str, noise_xpaths: List[str] = None):
    """ 利用 xpath 从 html 中提取文本 """
    html = get_code_from_html_by_xpath(html_text, xpath, noise_xpaths=noise_xpaths)
    return clean_html_to_text(html)
