"""Small, model-friendly helpers for exploring unfamiliar websites."""

from __future__ import annotations

import re

from app.schemas.explore import (
    ColumnRecognitionRequest,
    ColumnRecognitionResponse,
    ColumnSample,
    DOMTreeRequest,
    DOMTreeResponse,
    LinkGrepRequest,
    LinkGrepResponse,
)
from app.services.source_loader import WEB_SOURCES_DIR, get_source
from app.utils.algo import lcs_ratio
from app.utils.html_extractor import (
    get_codes_from_html_by_xpath,
    html_to_compact_dom_tree,
    grep_linkblock,
    parser_linkblock,
)


def _describe_for_ai(query: str, blocks: list[ColumnSample]) -> str:
    if not blocks:
        return "当前 source 中检索不到相关值得跟进的链接。"
    ordering = (
        "并已按照与 query 的相关性排序"
        if query
        else "并保留原始提取顺序"
    )
    return (
        f"每组 link_titles 均由对应的 link_xpath 从当前 source 的 HTML 中提取，{ordering}；"
        "block_xpath 用于获取这些链接节点的最近公共祖先；"
        "link_total 表示该组去重后的有效链接标题总数；"
        "link_titles 末尾的 '...' 表示还有部分内容被省略。"
        "请根据各组 link_titles 判断哪个 link_xpath 或 block_xpath 符合需求。"
    )


def _read_source_html(
    source_id: str,
    query: str,
) -> tuple[str | None, str | None, str | None]:
    """Return saved response.html, its URL base, and an error without networking."""
    source = get_source(source_id)
    if source is None:
        return None, None, "Source not found"

    response_path = WEB_SOURCES_DIR / source_id / "response.html"
    if not response_path.is_file():
        return None, None, "response.html not found"

    try:
        html = response_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, None, f"读取 response.html 失败：{exc}"
    if not html.strip():
        return None, None, "response.html is empty"

    request_url = source.request_config.get("url", "")
    url_base = source.url_base or request_url.replace("{query}", query)
    return html, url_base or None, None


async def recognize_columns(
    req: ColumnRecognitionRequest,
) -> ColumnRecognitionResponse:
    """Read one source's response.html and reduce its repeated link blocks."""
    html, url_base, error = _read_source_html(req.source_id, req.query)
    if error or html is None:
        return ColumnRecognitionResponse(
            source_id=req.source_id,
            query=req.query,
            desc_for_ai="当前 source 的 response.html 不可用，无法识别值得跟进的链接。",
            error=error,
        )

    try:
        parsed_blocks = parser_linkblock(
            html,
            url_base=url_base,
            # parser_linkblock 的历史参数是排他阈值（count > threshold）；
            # 接口对外暴露为更直观的包含式最小数量。
            min_exclusive_item_count=req.min_link_count - 1,
        )
    except Exception as exc:
        return ColumnRecognitionResponse(
            source_id=req.source_id,
            query=req.query,
            desc_for_ai="当前 source 的 response.html 无法解析，无法识别值得跟进的链接。",
            error=str(exc),
        )

    blocks: list[ColumnSample] = []
    for block in parsed_blocks:
        titles = list(dict.fromkeys(
            item.title.strip()
            for item in block.link_items
            if item.title and item.title.strip()
        ))
        ranked_titles = (
            sorted(
                titles,
                key=lambda title: (-lcs_ratio(req.query, title), title),
            )
            if req.query
            else titles
        )
        if len(ranked_titles) > req.limit:
            link_titles = ranked_titles[: max(req.limit - 1, 0)] + ["..."]
        else:
            link_titles = ranked_titles
        if link_titles:
            blocks.append(ColumnSample(
                block_xpath=block.block_xpath,
                link_xpath=block.link_xpath,
                link_total=len(ranked_titles),
                link_titles=link_titles,
            ))

    return ColumnRecognitionResponse(
        source_id=req.source_id,
        query=req.query,
        desc_for_ai=_describe_for_ai(req.query, blocks),
        link_blocks=blocks,
        error=None,
    )


def _describe_grep_for_ai(blocks: list[ColumnSample]) -> str:
    if not blocks:
        return "当前 source 中没有链接的完整文本能够匹配 pattern。"
    return (
        "每组 link_titles 都是用 pattern 匹配对应 <a> 节点的 string(.) 完整文本得到的；"
        "link_xpath 用于提取该组同类链接节点；"
        "block_xpath 用于获取这组链接节点的最近公共祖先；"
        "link_total 表示该组去重后的正则命中标题总数；"
        "link_titles 末尾的 '...' 表示还有部分命中内容被省略。"
        "请根据命中文本判断哪个 link_xpath 或 block_xpath 符合需求。"
    )


async def grep_source_links(req: LinkGrepRequest) -> LinkGrepResponse:
    """Regex-search complete anchor text in a source's saved response.html."""
    html, _, error = _read_source_html(req.source_id, "")
    if error or html is None:
        return LinkGrepResponse(
            source_id=req.source_id,
            pattern=req.pattern,
            ignore_case=req.ignore_case,
            desc_for_ai="当前 source 的 response.html 不可用，无法搜索链接文本。",
            error=error,
        )

    try:
        matched_blocks = grep_linkblock(
            html,
            pattern=req.pattern,
            ignore_case=req.ignore_case,
        )
    except re.error as exc:
        return LinkGrepResponse(
            source_id=req.source_id,
            pattern=req.pattern,
            ignore_case=req.ignore_case,
            desc_for_ai="pattern 不是有效的 Python 正则表达式。",
            error=str(exc),
        )
    except Exception as exc:
        return LinkGrepResponse(
            source_id=req.source_id,
            pattern=req.pattern,
            ignore_case=req.ignore_case,
            desc_for_ai="当前 source 的 response.html 无法解析，未能搜索链接文本。",
            error=str(exc),
        )

    blocks: list[ColumnSample] = []
    for matched in matched_blocks:
        titles = matched.link_titles
        if len(titles) > req.limit:
            visible_titles = titles[: max(req.limit - 1, 0)] + ["..."]
        else:
            visible_titles = titles
        blocks.append(ColumnSample(
            block_xpath=matched.block_xpath,
            link_xpath=matched.link_xpath,
            link_total=len(titles),
            link_titles=visible_titles,
        ))

    return LinkGrepResponse(
        source_id=req.source_id,
        pattern=req.pattern,
        ignore_case=req.ignore_case,
        desc_for_ai=_describe_grep_for_ai(blocks),
        link_blocks=blocks,
    )


async def extract_dom_tree(
    req: DOMTreeRequest,
) -> DOMTreeResponse:
    """Read response.html and return DOM fragments matched by a block XPath."""
    html, _, error = _read_source_html(req.source_id, "")
    if error or html is None:
        return DOMTreeResponse(
            source_id=req.source_id,
            block_xpath=req.block_xpath,
            desc_for_ai="当前 source 的 response.html 不可用，无法使用 block_xpath 观察局部 DOM 结构。",
            error=error,
        )

    try:
        fragments = get_codes_from_html_by_xpath(html, req.block_xpath)
    except Exception as exc:
        return DOMTreeResponse(
            source_id=req.source_id,
            block_xpath=req.block_xpath,
            desc_for_ai="block_xpath 解析或执行失败，未能提取局部 DOM 结构。",
            error=str(exc),
        )

    if not fragments:
        dom_tree = None
        desc_for_ai = "当前 block_xpath 在 source 的 HTML 中没有匹配到局部 DOM。"
    else:
        dom_tree = html_to_compact_dom_tree(fragments[0])
        desc_for_ai = (
            "dom_tree 是当前 block_xpath 命中的紧凑 DOM 树；"
            "同构兄弟节点已折叠，关键属性和文本已精简；"
            "string(.) 表示该节点包含所有后代的完整文本，编写 XPath 时应从标注的父节点提取，"
            "不要只提取其 strong、span 等局部子节点。"
        )

    return DOMTreeResponse(
        source_id=req.source_id,
        block_xpath=req.block_xpath,
        desc_for_ai=desc_for_ai,
        dom_tree=dom_tree,
    )
