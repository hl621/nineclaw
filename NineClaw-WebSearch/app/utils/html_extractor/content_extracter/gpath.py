# -*- coding: utf-8 -*-
# @Author: ZhangYaowu
# @Email: BiarFordlander@gmail.com
# @Time: 2023/6/28 下午3:52
import re

from lxml.html import Element
from pygments.lexers import math
import math
from . import feature
from .. import utils, errors

__all__ = (
    'is_high_quality_xapth',  # 判断是否为高质量标签
    'get_gpath',  # 获取 gpath
    'fromstring_with_gpath',  # 得到 gpath dom
    'get_unique_gpath',  # 利用 gpath dom 寻宗唯一根
    'refine_unique_gpath',  # 利用 gpath dom 精炼 xpath (前提条件是 gpath 是唯一的)
)

RE_LONGEST_HEAD = re.compile(r'^(.+?(?=__|\d| |$))')  # 从头部起最长非数字,双下滑，空格匹配
RE_CLEAR_MEANING = re.compile('content|article|@id=|@data-testid=')  # 寓意明确


def is_high_quality_xapth(xpath) -> bool:
    """ 判断是否是高质量 xpath """
    m = re.search(r'.+/(\w+)(\[.+?\])?$', xpath)  # 监测最后一个对象
    if m:
        tag, meta = m.groups()
        if tag in ['p']:
            return False
        elif tag in ['main', 'article']:
            return True
        elif meta and '@' in meta:
            return True
        else:
            return False
    else:
        return False


def get_elem_feature(elem: Element) -> str:
    """ 获取 元素属性 的特征 hash """
    if not isinstance(elem.tag, str):
        raise errors.InvalidTagError(f'invalid elem.tag is {elem.tag}')
    parent = elem.getparent()
    if elem.tag in ('html', 'body'):  # 特殊标签不需要标记
        return elem.tag
    elif elem.attrib.get('id'):  # 如果有 id
        id_text = elem.attrib.get('id')
        if feature.is_robot_create_name(id_text):
            return '{}[@id]'.format(elem.tag)
        else:
            return "{}[@id='{}']".format(elem.tag, id_text)
    elif elem.attrib.get('data-testid'):  # 如果有 data-testid
        id_text = elem.attrib.get('data-testid')
        if feature.is_robot_create_name(id_text):
            return '{}[@data-testid]'.format(elem.tag)
        else:
            return "{}[@data-testid='{}']".format(elem.tag, id_text)
    elif len(parent) == 1:  # 没有兄弟标签（意味着没有歧义可以缩短）
        return elem.tag
    elif elem.attrib.get('class'):  # 把最长的 class 拿出来当特征
        class_name = elem.attrib.get('class', '')
        if not class_name:  # 有 class 标签就意味着有 @class
            return '{}[@class]'.format(elem.tag)

        # 只有一个类且是高质量
        class_name_split = class_name.split(' ')
        if len(class_name_split) == 1 and not feature.is_robot_create_name(class_name):
            return "{}[@class='{}']".format(elem.tag, class_name)

        # 包含非机器创建名称
        high_quality_names = feature.filter_not_robot_created_names(class_name_split)
        if high_quality_names:  # 取出长度最长的高质量名称
            return "{}[contains(@class, '{}')]".format(elem.tag, max(high_quality_names, key=len))

        # 头部非最长匹配
        m = RE_LONGEST_HEAD.search(class_name)
        if m:
            text = m.group(1).rstrip('-_ ')
            if text:
                return "{}[starts-with(@class, '{}')]".format(elem.tag, text)
            else:
                return '{}[@class]'.format(elem.tag)
    elif elem.text and not len(elem) and not elem.attrib:  # 有文本、无子节点、无属性
        return '{}[text()]'.format(elem.tag)
    else:
        return elem.tag


def get_gpath(elem: Element) -> str:
    """ 获取 gpath(有一定泛化能力又有代表性的xpath) """
    gpath = elem.attrib.get('gpath', None)  # 提取 xpath 路径
    if gpath is None:
        parent = elem.getparent()
        if parent is None:
            parent_path = '/'
        else:
            parent_path = parent.attrib.get('gpath', '/')
        return '{}/{}'.format(parent_path, get_elem_feature(elem))  # 利用父节点路径与本元素代表构成 gpath
    else:
        return gpath


def get_text(elem: Element) -> str:
    """ 获取内容 """
    return elem.text_content().strip(' \n\r\t')


def fromstring_with_gpath(html_text: str):
    """ 用来替代 fromstring 用法，增强 gpath 路径 """
    dom = utils.fromstring(html_text)
    for elem in dom.iter():  # 完成增强路径赋值
        try:
            elem.attrib.update({'gpath': get_gpath(elem)})
        except errors.InvalidTagError:
            pass
    else:
        return dom


def _split_gpath(xpath) -> int:
    """ 标签拆分 """
    return [i for i in re.split(r'(//|/)', xpath) if i != '']


def _truncate_gpath(xpath) -> str:
    """ 缩短一级 """
    return ''.join(_split_gpath(xpath)[:-2])


def get_unique_gpath(dom, xpath: str) -> str:
    """ 从 dom 的 xpath 开始寻找唯一根 """
    _xpath = xpath
    while _xpath:
        if len(dom.xpath(_xpath)) > 1:
            _xpath = _truncate_gpath(_xpath)  # 缩短一级
        elif RE_CLEAR_MEANING.search(_xpath.split('/')[-1]):  # 如果标签具备明确清晰的标记
            break
        elif len(dom.xpath(_xpath)) == 1:
            _parent = _truncate_gpath(_xpath)  # 假设再缩短一次
            elem_current = dom.xpath(_xpath)[0]
            elem_parent = dom.xpath(_parent)[0]
            # 它的孩子只有单个属于叶子节点 or 明显不是正文根的标签
            if len(elem_parent) == 1 or elem_current.tag in ('p', 'ul', 'ol', 'li'):
                _xpath = _parent  # 缩短一级
            else:
                break
        else:
            break
    if not _xpath:
        raise errors.UniqueXpathIsNotFound('不存在唯一正文根')
    return _xpath


def _refine_unimportant_path(dom, xpath, count=1):
    """ 删除不重要的路径 """
    _xpath = xpath
    _segment = _xpath.split('/')
    for index in range(0, len(_segment) - 1):
        tag = _segment[index]
        if RE_CLEAR_MEANING.search(tag):  # 关键节点与标签不参与缩减
            continue
        else:
            _parent = _segment.copy()
            _parent[index] = ''  # 假设该处被精简
            _temp_xpath = '/'.join(_parent)
            _temp_xpath = re.sub(r'//+', '//', _temp_xpath)
            if len(dom.xpath(_temp_xpath)) == count:  # 精简后正文根不变
                _segment[index] = ''  # 正式精简
    else:
        _xpath = re.sub('//+', '//', '/'.join(_segment))
    return _xpath


def _refine_forward_path(dom, xpath, count=1):
    """ 从后向前精简路径 """
    _xpath = xpath
    _segment = _xpath.split('/')
    for index in range(len(_segment) - 2, 2, -1):
        pos = _segment[index].find('[')
        # 尝试去描述
        _parent = _segment.copy()
        _parent[index] = _segment[index][:pos]
        _temp_xpath = '/'.join(_parent)
        _temp_xpath = re.sub(r'//+', '//', _temp_xpath)
        if len(dom.xpath(_temp_xpath)) == count:
            _segment[index] = _segment[index][:pos]
        # 尝试去标签
        _parent = _segment.copy()
        _parent[index] = ''  # 假设该处被精简
        _temp_xpath = '/'.join(_parent)
        _temp_xpath = re.sub(r'//+', '//', _temp_xpath)
        if len(dom.xpath(_temp_xpath)) == count:  # 精简后正文根不变
            _segment[index] = ''  # 正式精简

    else:
        _xpath = _temp_xpath = re.sub(r'//+', '//', '/'.join(_segment))
    return _xpath


def refine_unique_gpath(dom, xpath: str) -> str:
    """ 提炼出正文根 """
    _xpath = xpath

    # 第一阶段找到唯一根
    _xpath = get_unique_gpath(dom, _xpath)

    # 第二阶段，从前往后精简掉非关键节点、标签
    _xpath = _refine_unimportant_path(dom, _xpath, count=1)

    # 第三阶段，排除最左与最右，从后向前精简
    _xpath = _refine_forward_path(dom, _xpath, count=1)

    return _xpath


def refine_short_gpath(dom, xpath: str) -> str:
    """ 只是变得更短一些 """
    _xpath = xpath
    count = len(dom.xpath(_xpath))

    # 第一阶段，从前往后精简掉非关键节点、标签
    _xpath = _refine_unimportant_path(dom, _xpath, count=count)

    # 第二阶段，排除最左与最右，从后向前精简
    _xpath = _refine_forward_path(dom, _xpath, count=count)

    return _xpath
