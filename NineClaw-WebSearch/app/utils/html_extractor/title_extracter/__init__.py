from .parser import get_title_from_html


def parse_title(
        html_text: str,
) -> str | None:
    """ 从给定的 html_text 与 url 中抽取发布时间 """
    return get_title_from_html(html_text)
