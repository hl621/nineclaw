"""用 agno Agent 像爬虫工程师一样自动编写并自校验 html_text -> list[dict] 的单文件抽取器。"""
from __future__ import annotations

import re
from pathlib import Path
from textwrap import dedent
from typing import Union

from agno.agent import Agent

from .validator import run_extractor_code

_PY_BLOCK = re.compile(r"```(?:python)?\s*(.*?)```", re.S)

INSTRUCTIONS = dedent(
    """\
    你是一名资深爬虫工程师。请根据给定的 HTML 编写一个【单文件】Python 抽取器：
    1. 只定义一个函数 `def extract(html_text: str) -> list[dict]`，每项含 name、url、desc 三个键。
    2. 用 parsel 抽取：`from parsel import Selector`，`Selector(text=html_text)` 后用
       `.xpath(...)` 取节点；若页面内嵌 JSON，可用 `.jmespath(...)`。url 尽量补全为绝对地址。
    3. 写好后必须调用 test_extractor_code 工具验证，根据反馈反复修改，直到返回 PASS。
    4. 最终把通过验证的完整代码放进一个 ```python``` 代码块输出。
    """
)


def _build_test_tool(samples: list[str], store: dict):
    def test_extractor_code(code: str) -> str:
        """测试候选抽取代码 code（须定义 extract(html_text)->list[dict]，每项含 name/url/desc）。返回 PASS 或失败原因。"""
        store["code"] = code
        reports = []
        for i, html in enumerate(samples):
            ok, msg, _ = run_extractor_code(code, html)
            reports.append(f"[样本{i}] {msg}")
            if not ok:
                return "FAIL\n" + "\n".join(reports)
        return "PASS\n" + "\n".join(reports)

    return test_extractor_code


def generate_extractor(
    model,
    html_text: Union[str, list[str]],
    prompt: str = "",
    *,
    output_path: Union[str, Path, None] = None,
    tool_call_limit: int = 12,
) -> tuple[str, list[dict]]:
    """自动生成并校验抽取器代码。

    model: agno 模型实例(如 OpenAIChat(...))；html_text: 单个或多个网页样本；
    prompt: 额外的抽取需求描述。返回 (稳定通过校验的单文件代码, 首个样本的抽取结果)。
    若提供 output_path，则把单文件代码写入该路径。
    """
    samples = [html_text] if isinstance(html_text, str) else list(html_text)
    store: dict = {}
    agent = Agent(
        model=model,
        tools=[_build_test_tool(samples, store)],
        instructions=INSTRUCTIONS,
        tool_call_limit=tool_call_limit,
    )
    resp = agent.run(f"{prompt}\n\n样本 HTML：\n{samples[0]}")

    # 候选代码：优先取最终回复里的代码块，其次取最后一次提交给工具的代码。
    candidates = []
    m = _PY_BLOCK.search(resp.content or "")
    if m:
        candidates.append(m.group(1).strip())
    if store.get("code"):
        candidates.append(store["code"])

    for code in candidates:
        results = [run_extractor_code(code, h) for h in samples]
        if all(ok for ok, _, _ in results):
            if output_path:
                Path(output_path).write_text(code, encoding="utf-8")
            return code, results[0][2]

    raise RuntimeError("AI 未能生成稳定通过校验的抽取代码，可增大 tool_call_limit 或补充 prompt")
