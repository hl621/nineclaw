class InvalidTagError(ValueError):
    """ 标签错误 """
    pass


class XpathElementIsNotFound(IndexError):
    """ xpath 找不到对应元素 """
    pass


class UniqueXpathIsNotFound(IndexError):
    """ 找不到唯一正文根 """
    pass
