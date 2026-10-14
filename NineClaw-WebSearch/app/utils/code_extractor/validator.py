"""校验 AI 生成的抽取代码：能否执行成功 + 输出是否符合 list[{name,url,desc}] 格式。

注意：这里会 exec 由大模型生成的代码，请仅在可信环境中运行。
"""
from __future__ import annotations

import traceback
from typing import Optional

from pydantic import BaseModel, TypeAdapter, ValidationError


class ListItem(BaseModel):
    name: str
    url: str
    desc: Optional[str] = None


_ITEMS = TypeAdapter(list[ListItem])


def run_extractor_code(code: str, html_text: str) -> tuple[bool, str, list[dict]]:
    """执行候选代码并校验输出。

    code 必须定义 ``def extract(html_text: str) -> list[dict]``。
    返回 (是否通过, 反馈信息, 结果列表)。
    """
    ns: dict = {}
    try:
        exec(code, ns)
        fn = ns.get("extract")
        if not callable(fn):
            return False, "代码必须定义 `def extract(html_text: str) -> list[dict]` 函数", []
        items = _ITEMS.validate_python(fn(html_text))
    except ValidationError as e:
        return False, f"输出格式不符合要求(需 list[{{name,url,desc}}]):\n{e}", []
    except Exception:
        return False, f"代码执行报错:\n{traceback.format_exc()}", []
    if not items:
        return False, "抽取结果为空，请检查 xpath/jmespath 是否匹配到列表项", []
    return True, f"成功抽取 {len(items)} 条", [i.model_dump() for i in items]
