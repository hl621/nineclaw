"""Agno agent that explores one WebSearch source and iterates its extractor."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import httpx
from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.run.agent import RunEvent
from agno.tools import Toolkit

from app.core.config import settings
from app.services.knowledge_llm_service import QaLlmConfig
from app.services.skill_studio_chat import (
    ITERATION_BUDGET_FALLBACK,
    _create_agno_model,
)

logger = logging.getLogger(__name__)

KEEP_RECENT_MESSAGES = 8
MAX_MESSAGE_CHARS = 4000
MAX_TOOL_RESULT_CHARS = 12000
MAX_TOOL_DISPLAY_CHARS = 12000
SESSION_TTL_SECONDS = 6 * 60 * 60
TOOL_COMPRESSION_TRIGGER_COUNT = 5
TOOL_COMPRESSION_TRIGGER_CHARS = 24_000
TOOL_COMPRESSION_KEEP_RECENT = 2
TOOL_CAPSULE_MAX_CHARS = 2400
TOOL_MEMORY_MAX_ITEMS = 6
TOOL_MEMORY_MAX_CHARS = 9000
EXECUTION_RESULT_SAMPLE_LIMIT = 3
AGENT_ITERATION_BUDGET = 20

AGENT_INSTRUCTIONS = [
    "你是 WebSearch 提取器研发 Agent，只处理当前已绑定的一个网页信源。",
    "若用户没有明确说明采集对象，应默认理解其使用场景是为一个搜索框接入网页信源，目标是提取提交 query 后返回的主体搜索结果列表，而不是导航、推荐、热榜、分页、广告或其他辅助栏目。默认每条搜索结果提取 title、url，并尽可能提取同一结果项中的 desc；用户明确指定其他对象或字段时，以用户要求为准。",
    "如果用户给出想采集内容中的字符串、关键词、标题片段或示例文本，优先调用 grep_link_blocks，将这些线索组成尽量稳健的 Python 正则来匹配 <a> 的完整 string(.) 文本。单个线索按字面量搜索时要转义正则特殊字符；多个可选线索可用非捕获分支组合。不要构造过于宽泛或容易灾难性回溯的正则。",
    "如果用户反馈采集结果不对、不满意或目标栏目不明确，而现有描述不足以判断目标，应简短询问：想抓取的区域里能看到什么文字，并提示用户提供其中一两个关键词或一小段示例文本；收到后使用 grep_link_blocks 直接定位。已有信息足够判断时不要重复追问。",
    "采用工程化的最短路径：读取当前提取器；用户已给出文本线索时调用一次 grep_link_blocks，否则调用一次 list_link_blocks；根据 link_titles 选择一个最有价值的主体 block_xpath；仅对这个完整 block_xpath 调用一次 inspect_dom_tree；然后直接编写、保存和测试代码。正则无命中时才退回 list_link_blocks 查看整体栏目。",
    "block_xpath 代表包含多条搜索结果的完整价值区域。DOM 树中每条重复结果通常同时包含 title、url 和 desc；应在同一个结果 item 内定位三者，不要为了寻找 desc 再向下试探 p、a、li、标题或其他子 XPath。",
    "inspect_dom_tree 必须原样使用 grep_link_blocks 或 list_link_blocks 返回的 block_xpath，禁止自行拼接、缩短、扩展或构造新的 XPath。不要重复观察同一个 DOM，也不要逐个探索候选块。",
    "如果选中的主体块明显不符合用户需求，应停止并说明判断；只有用户在后续消息中指出采集对象不对、要求额外字段或明确要求探索其他栏目时，才开启新一轮并选择另一个 block。",
    "你的目标是编写 extract(html: str) -> list[dict]；每项必须包含字符串 url、title，并应尽可能包含字符串 desc。",
    "desc 是默认抽取目标，不是可随意忽略的附加项。它应来自同一结果块中的摘要、简介、正文片段、说明或其他能帮助判断结果价值的描述文本。只有页面对应结果块确实不存在这类内容时，才允许省略 desc。",
    "不要用 title 重复填充 desc，不要虚构描述，也不要把整个结果块的标题、导航文字和无关元数据混在 desc 中。提取后应 strip 并过滤空字符串。",
    "观察主体 DOM 时，必须分别确认 title、url、desc 的节点，以及它们共同所属的单条结果节点。",
    "标题应从链接节点的完整 string(.) 获取，避免只取 strong/span 导致残缺；相对 URL 可以直接返回。",
    "页面分析是离线的：grep_link_blocks、list_link_blocks、inspect_dom_tree 和 run_extractor 都由 NineClaw-WebSearch 读取该信源已保存的 response.html，不会重新请求网站。",
    "开发环境依赖受限。提取代码只可使用 Python 标准库及已提供的 parsel/lxml；不要安装包，不要使用浏览器自动化。",
    "读取现有代码后，优先使用 edit_extractor 做精确的局部修改：old_text 必须与当前代码中的一处内容完全匹配，包含空白和缩进；匹配零处或多处时应先重新读取代码或补充上下文，不要盲目重试。只有新建或确需整体重写时才使用 save_extractor。修改后调用 run_extractor 在保存的 HTML 上验证；成功后检查每条结果的 title、url 和 desc 质量，并确认只有确实无摘要的页面才缺少 desc。",
    "工具调用要服务于清晰的工作思路，不要为了显得在工作而连续试探。每次测试后先判断具体结果；只有发现明确的代码或数据问题时才再次保存并运行，禁止无依据地重复调用工具。",
    "上下文中的较早工具结果可能已被压缩成结构化摘要，... 表示原始大字段已省略，不得把省略内容当成事实推测。如果当前修改依赖精确代码或 DOM 细节，应重新调用对应读取或探索工具；已保留的 XPath、状态、数量和错误信息可直接使用。",
    "在开始一个新的重要阶段前，用一句简短、自然、面向用户的说明交代接下来要做什么，例如“好的，我先确认当前提取器和页面栏目。”；它是过程旁白，不是隐藏思考。不要为每个细小动作都写旁白。",
    "只有确有必要验证真实搜索流程时才调用 test_search；该工具会发起网络请求，query 应使用用户当前测试词。",
    "最多进行有限轮工具调用；不要重复观察同一个结构。若信息不足，清楚说明需要用户补充什么。",
    "用户可在后续消息中纠正目标；结合会话摘要和最近消息继续，不要从头重复探索。",
    "最终回答简短说明结果、是否已保存、离线/在线测试情况，不要粘贴完整代码。",
]


@dataclass
class Message:
    role: str
    content: str


@dataclass
class Session:
    session_id: str
    source_id: str
    tenant_id: str
    messages: list[Message] = field(default_factory=list)
    summary: str = ""
    tool_memory: list[str] = field(default_factory=list)
    touched_at: float = field(default_factory=time.time)


@dataclass
class Run:
    run_id: str
    session_id: str
    source_id: str
    tenant_id: str
    queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    task: asyncio.Task[None] | None = None


_sessions: dict[str, Session] = {}
_runs: dict[str, Run] = {}


def _prune() -> None:
    cutoff = time.time() - SESSION_TTL_SECONDS
    active_sessions = {
        run.session_id for run in _runs.values() if run.task and not run.task.done()
    }
    for session_id, session in list(_sessions.items()):
        if session.touched_at < cutoff and session_id not in active_sessions:
            _sessions.pop(session_id, None)


def create_session(source_id: str, tenant_id: str) -> str:
    _prune()
    session_id = str(uuid.uuid4())
    _sessions[session_id] = Session(session_id, source_id, tenant_id)
    return session_id


def cancel_run(source_id: str, tenant_id: str, session_id: str, run_id: str) -> bool:
    run = _runs.get(run_id)
    if not run or (run.source_id, run.tenant_id, run.session_id) != (
        source_id,
        tenant_id,
        session_id,
    ):
        return False
    if not run.task or run.task.done():
        return False
    run.task.cancel()
    return True


def _json_text(value: Any, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    return text if len(text) <= limit else text[:limit] + "\n[结果已截断]"


def _clip_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    head = max(int(limit * 0.72), 1)
    tail = max(limit - head - 30, 0)
    suffix = text[-tail:] if tail else ""
    return f"{text[:head]}\n... [中间内容已省略] ...\n{suffix}".strip()


def _compact_value(value: Any, *, depth: int = 0) -> Any:
    """Bound arbitrary tool data while retaining identifiers and examples."""
    if depth >= 3:
        if isinstance(value, (dict, list)):
            return f"... [{len(value)} 项已省略]"
        return _clip_text(value, 240)
    if isinstance(value, dict):
        items = list(value.items())
        result = {
            str(key): _compact_value(item, depth=depth + 1)
            for key, item in items[:12]
        }
        if len(items) > 12:
            result["..."] = f"还有 {len(items) - 12} 个字段已省略"
        return result
    if isinstance(value, list):
        result = [_compact_value(item, depth=depth + 1) for item in value[:3]]
        if len(value) > 3:
            result.append(f"... [还有 {len(value) - 3} 项已省略]")
        return result
    if isinstance(value, str):
        return _clip_text(value, 600)
    return value


def _compact_tool_args(tool_name: str, args: Any) -> Any:
    if not isinstance(args, dict):
        return _compact_value(args)
    compacted: dict[str, Any] = {}
    for key, value in args.items():
        if key in {"code", "old_text", "new_text"}:
            text = str(value or "")
            compacted[key] = {
                "chars": len(text),
                "preview": _clip_text(text, 220),
            }
        else:
            compacted[key] = _compact_value(value, depth=1)
    return compacted


def _parse_tool_content(content: Any) -> Any:
    if isinstance(content, (dict, list)):
        return content
    text = str(content or "").strip()
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text


def _compact_link_blocks(payload: dict[str, Any]) -> dict[str, Any]:
    blocks = payload.get("link_blocks")
    compact_blocks = []
    if isinstance(blocks, list):
        for block in blocks[:8]:
            if not isinstance(block, dict):
                continue
            titles = block.get("link_titles")
            compact_blocks.append(
                {
                    "block_xpath": block.get("block_xpath"),
                    "link_xpath": block.get("link_xpath"),
                    "link_total": block.get("link_total"),
                    "link_titles": (
                        [_clip_text(title, 180) for title in titles[:2]]
                        + (["..."] if len(titles) > 2 else [])
                        if isinstance(titles, list)
                        else []
                    ),
                }
            )
    return {
        "query": payload.get("query"),
        "pattern": payload.get("pattern"),
        "ignore_case": payload.get("ignore_case"),
        "desc_for_ai": _clip_text(payload.get("desc_for_ai"), 360),
        "link_blocks": compact_blocks,
        "error": payload.get("error"),
    }


def _compact_tool_result(tool_name: str, content: Any) -> Any:
    payload = _parse_tool_content(content)
    if not isinstance(payload, dict):
        return _clip_text(payload, 1400)
    if tool_name in {"list_link_blocks", "grep_link_blocks"}:
        return _compact_link_blocks(payload)
    if tool_name == "inspect_dom_tree":
        dom_tree = payload.get("dom_tree")
        return {
            "block_xpath": payload.get("block_xpath"),
            "desc_for_ai": _clip_text(payload.get("desc_for_ai"), 360),
            "dom_tree": _clip_text(dom_tree, 1500) if dom_tree else None,
            "error": payload.get("error"),
        }
    if tool_name == "read_extractor":
        code = str(payload.get("extractor_code") or "")
        return {
            "source_id": payload.get("source_id"),
            "name": payload.get("name"),
            "request_config": _compact_value(payload.get("request_config"), depth=1),
            "response_info": _compact_value(payload.get("response_info"), depth=1),
            "url_base": payload.get("url_base"),
            "extractor_code": {
                "chars": len(code),
                "preview": _clip_text(code, 500),
            },
        }
    if tool_name in {"run_extractor", "test_search"}:
        compacted = {
            key: _compact_value(payload.get(key), depth=1)
            for key in (
                "success",
                "exit_code",
                "status_code",
                "result_count",
                "time_ms",
                "request_time_ms",
                "parse_time_ms",
                "error",
                "stdout",
                "stderr",
            )
            if key in payload
        }
        if "result" in payload:
            compacted["result"] = _compact_value(payload.get("result"), depth=1)
        if "results" in payload:
            compacted["results"] = _compact_value(payload.get("results"), depth=1)
        return compacted
    return _compact_value(payload)


def _sample_result_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return _compact_value(item, depth=1)
    sampled: dict[str, Any] = {}
    for key in ("url", "title", "desc"):
        if key in item:
            limit = 900 if key == "desc" else 500
            value = item.get(key)
            sampled[key] = None if value is None else _clip_text(value, limit)
    for key, value in item.items():
        if key not in sampled and len(sampled) < 8:
            sampled[key] = _compact_value(value, depth=1)
    return sampled


def _sample_run_extractor_response(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    sampled = dict(data)
    sampled["stdout"] = _clip_text(sampled.get("stdout"), 2400)
    sampled["stderr"] = _clip_text(sampled.get("stderr"), 2400)
    result = sampled.get("result")
    if isinstance(result, dict):
        compact_result = dict(result)
        items = result.get("items")
        if isinstance(items, list):
            compact_result["items"] = [
                _sample_result_item(item)
                for item in items[:EXECUTION_RESULT_SAMPLE_LIMIT]
            ]
            total = result.get("count")
            total_count = total if isinstance(total, int) else len(items)
            compact_result["items_omitted"] = max(
                total_count - len(compact_result["items"]),
                0,
            )
        sampled["result"] = compact_result
    return sampled


def _sample_test_search_response(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    sampled = dict(data)
    results = data.get("results")
    if isinstance(results, list):
        sampled["results"] = [
            _sample_result_item(item)
            for item in results[:EXECUTION_RESULT_SAMPLE_LIMIT]
        ]
        total = data.get("result_count")
        total_count = total if isinstance(total, int) else len(results)
        sampled["results_omitted"] = max(
            total_count - len(sampled["results"]),
            0,
        )
    return sampled


def _tool_capsule(
    tool_name: str,
    args: Any,
    content: Any,
    *,
    status: str = "success",
) -> str:
    capsule = {
        "tool": tool_name,
        "status": status,
        "input": _compact_tool_args(tool_name, args),
        "result_summary": _compact_tool_result(tool_name, content),
        "note": "较早工具结果已分层压缩，原始大字段以 ... 省略；必要时重新调用工具。",
    }
    return _clip_text(
        "[较早工具结果已压缩]\n"
        + json.dumps(capsule, ensure_ascii=False, indent=2),
        TOOL_CAPSULE_MAX_CHARS,
    )


class WebSearchToolCompressionManager(CompressionManager):
    """Deterministically age WebSearch tool results without extra LLM calls."""

    def _tool_messages(self, messages: list[AgnoMessage]) -> list[AgnoMessage]:
        return [message for message in messages if message.role == "tool"]

    def _compression_candidates(
        self,
        messages: list[AgnoMessage],
    ) -> list[AgnoMessage]:
        tool_messages = self._tool_messages(messages)
        uncompressed = [
            message for message in tool_messages if message.compressed_content is None
        ]
        if not uncompressed:
            return []

        protected_ids = {
            id(message) for message in uncompressed[-TOOL_COMPRESSION_KEEP_RECENT:]
        }

        # DOM structure and the newest execution feedback remain useful while
        # coding; preserve their latest snapshots even if they are not recent.
        for names in (
            {"inspect_dom_tree"},
            {"run_extractor", "test_search"},
        ):
            latest = next(
                (message for message in reversed(uncompressed) if message.tool_name in names),
                None,
            )
            if latest is not None:
                protected_ids.add(id(latest))

        # Current code must stay intact until it has been edited or replaced.
        latest_read_index = next(
            (
                index
                for index in range(len(uncompressed) - 1, -1, -1)
                if uncompressed[index].tool_name == "read_extractor"
            ),
            None,
        )
        if latest_read_index is not None:
            has_later_write = any(
                message.tool_name in {"edit_extractor", "save_extractor"}
                for message in uncompressed[latest_read_index + 1:]
            )
            if not has_later_write:
                protected_ids.add(id(uncompressed[latest_read_index]))

        return [
            message for message in uncompressed if id(message) not in protected_ids
        ]

    def should_compress(
        self,
        messages: list[AgnoMessage],
        tools: Any = None,
        model: Any = None,
        response_format: Any = None,
    ) -> bool:
        candidates = self._compression_candidates(messages)
        if not candidates:
            return False
        tool_messages = self._tool_messages(messages)
        uncompressed_chars = sum(
            len(message.get_content_string())
            for message in tool_messages
            if message.compressed_content is None
        )
        return (
            len(tool_messages) >= TOOL_COMPRESSION_TRIGGER_COUNT
            or uncompressed_chars >= TOOL_COMPRESSION_TRIGGER_CHARS
        )

    async def ashould_compress(
        self,
        messages: list[AgnoMessage],
        tools: Any = None,
        model: Any = None,
        response_format: Any = None,
    ) -> bool:
        return self.should_compress(messages, tools, model, response_format)

    def compress(
        self,
        messages: list[AgnoMessage],
        run_metrics: Any = None,
    ) -> None:
        for message in self._compression_candidates(messages):
            original_size = len(message.get_content_string())
            message.compressed_content = _tool_capsule(
                message.tool_name or "unknown",
                message.tool_args,
                message.content,
            )
            self.stats["tool_results_compressed"] = (
                self.stats.get("tool_results_compressed", 0) + 1
            )
            self.stats["original_size"] = (
                self.stats.get("original_size", 0) + original_size
            )
            self.stats["compressed_size"] = (
                self.stats.get("compressed_size", 0)
                + len(message.compressed_content)
            )

    async def acompress(
        self,
        messages: list[AgnoMessage],
        run_metrics: Any = None,
    ) -> None:
        self.compress(messages, run_metrics=run_metrics)


def _remember_tool_result(session: Session, tool: Any, status: str) -> None:
    capsule = _tool_capsule(
        getattr(tool, "tool_name", None) or "tool",
        getattr(tool, "tool_args", None),
        getattr(tool, "result", None),
        status=status,
    )
    session.tool_memory.append(capsule)
    session.tool_memory = session.tool_memory[-TOOL_MEMORY_MAX_ITEMS:]
    while (
        len("\n\n".join(session.tool_memory)) > TOOL_MEMORY_MAX_CHARS
        and len(session.tool_memory) > 1
    ):
        session.tool_memory.pop(0)


class WebSearchExploreToolkit(Toolkit):
    def __init__(self, source_id: str):
        self.source_id = source_id
        self.base_url = settings.resolved_websearch_api_url
        self._list_result: dict[str, Any] | None = None
        self._discovered_block_xpaths: set[str] = set()
        self._inspected_block_xpath: str | None = None
        self._inspected_dom_result: str | None = None
        tools = [
            self.list_link_blocks,
            self.grep_link_blocks,
            self.inspect_dom_tree,
            self.read_extractor,
            self.edit_extractor,
            self.save_extractor,
            self.run_extractor,
            self.test_search,
        ]
        super().__init__(name="websearch_explore", tools=tools, auto_register=False)
        for tool in tools:
            self.register(tool)

    async def _post(self, path: str, body: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            response = await client.post(f"{self.base_url}{path}", json=body)
        response.raise_for_status()
        return response.json()

    async def list_link_blocks(
        self,
        query: str = "",
        limit: int = 7,
        min_link_count: int = 6,
    ) -> str:
        """发现重复链接栏目；min_link_count 是过滤后同组链接的最小数量。"""
        if self._list_result is not None:
            return _json_text(
                {
                    "notice": "本轮已识别过链接栏目，请直接从已有结果选择一个主体 block_xpath，不要重复探索。",
                    **self._list_result,
                }
            )
        data = await self._post(
            "/sources/explore/listlink",
            {
                "source_id": self.source_id,
                "query": query,
                "limit": limit,
                "min_link_count": min_link_count,
            },
        )
        self._list_result = data
        self._discovered_block_xpaths |= {
            str(block.get("block_xpath", "")).strip()
            for block in data.get("link_blocks", [])
            if isinstance(block, dict) and str(block.get("block_xpath", "")).strip()
        }
        return _json_text(data)

    async def grep_link_blocks(
        self,
        pattern: str,
        ignore_case: bool = True,
        limit: int = 7,
    ) -> str:
        """用 Python 正则搜索 <a> 的完整文本并返回 XPath。"""
        data = await self._post(
            "/sources/explore/greplink",
            {
                "source_id": self.source_id,
                "pattern": pattern,
                "ignore_case": ignore_case,
                "limit": limit,
            },
        )
        self._discovered_block_xpaths |= {
            str(block.get("block_xpath", "")).strip()
            for block in data.get("link_blocks", [])
            if isinstance(block, dict) and str(block.get("block_xpath", "")).strip()
        }
        return _json_text(data)

    async def inspect_dom_tree(self, block_xpath: str) -> str:
        """仅查看链接探索工具返回的一个完整主体 block_xpath。"""
        normalized_xpath = block_xpath.strip()
        if not self._discovered_block_xpaths:
            return _json_text(
                {
                    "error": "请先调用 grep_link_blocks 或 list_link_blocks，再从返回结果中选择一个主体 block_xpath。"
                }
            )
        if normalized_xpath not in self._discovered_block_xpaths:
            return _json_text(
                {
                    "error": (
                        "拒绝观察自行构造的 XPath。请原样使用 grep_link_blocks 或 list_link_blocks 返回的 "
                        "block_xpath；title、url、desc 应在该完整块的同一结果 item 内判断。"
                    ),
                    "allowed_block_xpaths": sorted(self._discovered_block_xpaths),
                }
            )
        if self._inspected_block_xpath is not None:
            if normalized_xpath == self._inspected_block_xpath:
                return _json_text(
                    {
                        "notice": "本轮已观察过这个主体块，请使用已有 DOM 结果编写并测试代码，不要重复观察。"
                    }
                )
            return _json_text(
                {
                    "error": (
                        "本轮已经确定并观察了一个主体块。请在该块内同时提取 title、url、desc；"
                        "只有用户后续明确纠正目标时，才在新一轮探索其他块。"
                    ),
                    "inspected_block_xpath": self._inspected_block_xpath,
                }
            )
        data = await self._post(
            "/sources/explore/domtree",
            {"source_id": self.source_id, "block_xpath": normalized_xpath},
        )
        result = _json_text(data)
        self._inspected_block_xpath = normalized_xpath
        self._inspected_dom_result = result
        return result

    async def read_extractor(self) -> str:
        """读取当前信源配置和 extract.py。"""
        data = await self._read_source_detail()
        return _json_text(
            {
                "source_id": data.get("source_id"),
                "name": data.get("name"),
                "request_config": data.get("request_config"),
                "response_info": data.get("response_info"),
                "url_base": data.get("url_base"),
                "extractor_code": data.get("extractor_code"),
            }
        )

    async def _read_source_detail(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.get(f"{self.base_url}/sources/{self.source_id}")
        response.raise_for_status()
        return response.json()

    async def save_extractor(self, code: str) -> str:
        """校验语法并把完整 extract.py 保存到当前信源。"""
        data = await self._post(
            "/sources/save_extractor", {"source_id": self.source_id, "code": code}
        )
        return _json_text(data)

    async def edit_extractor(self, old_text: str, new_text: str) -> str:
        """仅当 old_text 在当前 extract.py 中精确匹配一处时替换并返回 diff。"""
        try:
            data = await self._post(
                "/sources/edit_extractor",
                {
                    "source_id": self.source_id,
                    "old_text": old_text,
                    "new_text": new_text,
                },
            )
            return _json_text(data)
        except httpx.HTTPStatusError as exc:
            response = exc.response
            try:
                payload: Any = response.json()
            except (TypeError, ValueError, json.JSONDecodeError):
                payload = response.text
            raise RuntimeError(
                _json_text(
                    {
                        "edited": False,
                        "status_code": response.status_code,
                        "error": payload,
                        "next_action": (
                            "重新读取当前代码；若匹配多处，为 old_text 补充更多上下文，"
                            "确保它精确匹配一处后再编辑。"
                        ),
                    }
                )
            ) from exc

    async def run_extractor(self) -> str:
        """在已保存的 response.html 上运行 extract.py，并一次性返回日志和结果。"""
        data = await self._post("/sources/run_extractor", {"source_id": self.source_id})
        return _json_text(_sample_run_extractor_response(data))

    async def test_search(self, query: str) -> str:
        """用 query 发起真实请求并运行提取器，验证完整搜索流程。"""
        data = await self._post(
            "/sources/test", {"source_id": self.source_id, "query": query}
        )
        return _json_text(_sample_test_search_response(data))


def _context(session: Session, *, exclude_latest: bool = False) -> str:
    parts = [
        f"当前绑定 source_id: {session.source_id}。所有工具已自动绑定，无需也不能另填 source_id。"
    ]
    if session.summary:
        parts.append("较早会话压缩摘要：\n" + session.summary)
    if session.tool_memory:
        parts.append(
            "近期工具结论（原始大字段已用 ... 省略，必要时可重新调用）：\n"
            + "\n\n".join(session.tool_memory)
        )
    messages = session.messages[:-1] if exclude_latest else session.messages
    if messages:
        lines = []
        for message in messages[-KEEP_RECENT_MESSAGES:]:
            label = "用户" if message.role == "user" else "助手"
            lines.append(f"{label}: {message.content[:MAX_MESSAGE_CHARS]}")
        parts.append("最近会话：\n" + "\n\n".join(lines))
    return "\n\n".join(parts)


def _compact(session: Session) -> None:
    if len(session.messages) <= KEEP_RECENT_MESSAGES:
        return
    old = session.messages[:-KEEP_RECENT_MESSAGES]
    digest = "\n".join(f"{m.role}: {m.content[:800]}" for m in old)
    session.summary = (session.summary + "\n" + digest).strip()[-10000:]
    session.messages = session.messages[-KEEP_RECENT_MESSAGES:]


async def _emit(run: Run, event: str, data: Any) -> None:
    await run.queue.put(
        f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    )


def _tool_payload(tool: Any, status: str) -> dict[str, Any]:
    name = getattr(tool, "tool_name", None) or "tool"
    args = getattr(tool, "tool_args", None)
    result = getattr(tool, "result", None)
    preview = ""
    if result is not None:
        preview = str(result).strip()
        try:
            preview = json.dumps(
                json.loads(preview),
                ensure_ascii=False,
                indent=2,
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        if len(preview) > MAX_TOOL_DISPLAY_CHARS:
            preview = preview[:MAX_TOOL_DISPLAY_CHARS].rstrip() + "\n[显示已截断]"
    safe_args = dict(args) if isinstance(args, dict) else {}
    return {
        "name": name,
        "preview": preview,
        "args": safe_args,
        "status": status,
        "tool_call_id": getattr(tool, "tool_call_id", None),
    }


async def _produce(
    run: Run,
    message: str,
    llm: QaLlmConfig,
    temperature: float | None,
    enable_thinking: bool | None,
) -> None:
    session = _sessions[run.session_id]
    session.messages.append(Message("user", message.strip()))
    session.touched_at = time.time()
    final_answer = ""
    pending_content = ""
    reasoning_delta_seen = False
    model = _create_agno_model(
        llm,
        temperature,
        enable_thinking,
        iteration_budget=AGENT_ITERATION_BUDGET,
    )
    try:
        agent = Agent(
            model=model,
            tools=[WebSearchExploreToolkit(run.source_id)],
            compress_tool_results=True,
            compression_manager=WebSearchToolCompressionManager(),
            instructions=AGENT_INSTRUCTIONS,
            additional_context=_context(session, exclude_latest=True),
            markdown=False,
            stream=True,
            stream_events=True,
            telemetry=False,
        )
        async for event in agent.arun(
            message, stream=True, stream_events=True, session_id=run.session_id
        ):
            event_type = getattr(event, "event", "")
            if event_type == RunEvent.run_content.value:
                content = getattr(event, "content", None)
                if content:
                    final_answer += str(content)
                    pending_content += str(content)
                    await _emit(run, "token", {"content": str(content)})
            elif event_type == RunEvent.run_intermediate_content.value:
                content = getattr(event, "content", None)
                if content:
                    final_answer += str(content)
                    await _emit(run, "process", {"content": str(content)})
            elif event_type == RunEvent.reasoning_started.value:
                reasoning_delta_seen = False
            elif event_type == RunEvent.reasoning_content_delta.value:
                reasoning_content = getattr(event, "reasoning_content", None)
                if reasoning_content:
                    reasoning_delta_seen = True
                    await _emit(
                        run,
                        "reasoning",
                        {"type": "model_delta", "message": str(reasoning_content)},
                    )
            elif event_type == RunEvent.reasoning_step.value:
                # Some providers emit one completed reasoning step instead of
                # deltas. Do not replay the full step after streamed deltas.
                reasoning_content = getattr(event, "reasoning_content", None)
                if not reasoning_delta_seen and reasoning_content:
                    await _emit(
                        run,
                        "reasoning",
                        {"type": "model", "message": str(reasoning_content)},
                    )
            elif event_type == RunEvent.tool_call_started.value:
                tool = getattr(event, "tool", None)
                if tool is not None:
                    if pending_content:
                        await _emit(
                            run,
                            "interim_assistant",
                            {"content": pending_content, "already_streamed": True},
                        )
                        pending_content = ""
                    await _emit(run, "tool", _tool_payload(tool, "running"))
            elif event_type == RunEvent.tool_call_completed.value:
                tool = getattr(event, "tool", None)
                if tool is not None:
                    _remember_tool_result(session, tool, "success")
                    await _emit(run, "tool", _tool_payload(tool, "success"))
            elif event_type == RunEvent.tool_call_error.value:
                tool = getattr(event, "tool", None)
                if tool is not None:
                    _remember_tool_result(session, tool, "error")
                    await _emit(run, "tool", _tool_payload(tool, "error"))
            elif event_type == RunEvent.run_error.value:
                raise RuntimeError(
                    str(getattr(event, "content", None) or "Agent 运行失败")
                )
        if model.iteration_budget_exhausted:
            final_answer = pending_content.strip() or (
                ITERATION_BUDGET_FALLBACK
            )
        else:
            final_answer = final_answer.strip() or "处理完成。"
        session.messages.append(Message("assistant", final_answer))
        _compact(session)
        await _emit(run, "complete", {"type": "complete", "message": final_answer})
    except asyncio.CancelledError:
        await _emit(
            run,
            "reasoning",
            {"type": "canceled", "message": "运行已取消，可继续补充要求"},
        )
    except Exception as exc:
        logger.exception("WebSearch studio agent failed for %s", run.source_id)
        await _emit(run, "reasoning", {"type": "error", "message": str(exc)})
    finally:
        await run.queue.put("event: reasoning\ndata: [DONE]\n\n")
        await run.queue.put(None)


async def stream_chat(
    source_id: str,
    tenant_id: str,
    session_id: str,
    message: str,
    llm: QaLlmConfig,
    temperature: float | None,
    enable_thinking: bool | None,
) -> AsyncGenerator[str, None]:
    session = _sessions.get(session_id)
    if not session or (session.source_id, session.tenant_id) != (source_id, tenant_id):
        raise RuntimeError("会话不存在或不属于当前信源")
    run = Run(str(uuid.uuid4()), session_id, source_id, tenant_id)
    _runs[run.run_id] = run
    run.task = asyncio.create_task(
        _produce(run, message, llm, temperature, enable_thinking)
    )
    yield f"event: run\ndata: {json.dumps({'run_id': run.run_id})}\n\n"
    try:
        while True:
            chunk = await run.queue.get()
            if chunk is None:
                break
            yield chunk
    finally:
        if run.task and not run.task.done():
            run.task.cancel()
            await asyncio.gather(run.task, return_exceptions=True)
        _runs.pop(run.run_id, None)
