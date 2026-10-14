"""In-memory chat sessions + LLM streaming for skill studio."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator

import httpx
from agno.agent import Agent
from agno.compression.manager import CompressionManager
from agno.models.message import Message as AgnoMessage
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.run.agent import RunEvent
from agno.tools import Toolkit
from agno.tools.coding import CodingTools

from app.services.knowledge_llm_service import QaLlmConfig
from app.services.knowledge_time_context import (
    current_time_context,
    exact_current_time_context,
)
from app.services.skill_studio_files import list_skill_files, read_skill_file
from app.services.skill_studio_tools import SkillManageToolkit

logger = logging.getLogger(__name__)

LLM_PROGRESS_INTERVAL_S = 2.0
FILE_WRITE_EVENT_DELAY_S = 0.05
AGENTS_FILE_NAME = "AGENTS.md"
AGENTS_CONTEXT_MAX_CHARS = 24000
SKILL_STUDIO_RESOURCE_DIR = (
    Path(__file__).resolve().parents[1] / "resources" / "skill_studio"
)
SKILL_CREATOR_RESOURCE_DIR = SKILL_STUDIO_RESOURCE_DIR / "skill-creator"
SKILL_CREATOR_CONTEXT_MAX_CHARS = 36000
CONVERSATION_KEEP_RECENT = 8
CONVERSATION_SUMMARIZE_AT_MESSAGES = 14
CONVERSATION_SUMMARIZE_AT_CHARS = 32000
CONVERSATION_SUMMARY_MAX_SOURCE_CHARS = 24000
CONVERSATION_CONTEXT_MAX_CHARS_PER_MESSAGE = 3000
SUBTASK_RESULT_MAX_CHARS = 5000
AGENT_ITERATION_BUDGET = 20
SUBTASK_ITERATION_BUDGET = 14
TOOL_DISPLAY_MAX_CHARS = 12000
TOOL_COMPRESSION_TRIGGER_COUNT = 5
TOOL_COMPRESSION_TRIGGER_CHARS = 24000
TOOL_COMPRESSION_KEEP_RECENT = 2
TOOL_CAPSULE_MAX_CHARS = 2400
TOOL_MEMORY_MAX_ITEMS = 6
TOOL_MEMORY_MAX_CHARS = 9000
RUN_RETENTION_S = 30 * 60
SESSION_IDLE_RETENTION_S = 6 * 60 * 60
MAX_RETAINED_RUNS = 200
CANCEL_GRACE_S = 5.0
CURRENT_TIME_CONTEXT_LABEL = (
    "当前系统时间（按小时截断，用于解释相对时间，不代表文件时间）"
)

AGNO_DEV_INSTRUCTIONS = [
    "你是 Skill Creator Agent，只负责创建、维护和改进当前 Skill 项目。",
    "当前工作目录就是当前 Skill 根目录。所有路径都必须相对当前 Skill 根目录。",
    "你必须使用工具查看和修改文件，不要要求用户粘贴 SKILL.md 或其他当前文件内容。",
    "所有 Skill 文件读取和写入都使用 skill_manage；不确定文件位置时先使用 ls/find/grep 定位。",
    "修改已有文件时优先使用 skill_manage(action='patch')；old_text 默认必须精确且唯一匹配，失败后重新 read 或 grep，再补足上下文。",
    "完整重写 SKILL.md 仅使用 skill_manage(action='edit')；新建支持文件使用 write_file，且只放入 references/templates/scripts/assets。",
    "已有文件必须在本轮先用 skill_manage(action='read') 读取，工具才允许 patch、edit 或覆盖；完成修改后必须调用 validate。",
    "不要使用未提供的工具，不要假装执行 shell 命令；当前不允许 shell。",
    "脚本必须适合离线运行，只能依赖标准库、当前 skill 内文件、或用户明确约定的依赖。",
    "如果确实需要新增第三方依赖，先在最终回答中说明原因并等待用户确认，不要直接写入依赖代码。",
    "不要把完整文件内容复制到最终回答。最终回答只给简短结论、改了哪些文件、还需要用户注意什么。",
    "复杂任务可以调用 skill_subtask，把局部研究或局部编辑交给独立子智能体；子智能体结果会以短总结返回，不要用它处理需要持续和用户确认的决策。",
    "在开始一个新的重要阶段前，可以用一句简短、自然、面向用户的说明交代接下来要做什么；这是过程旁白，不是隐藏思考。不要为每个细小动作都写旁白，也不要使用固定模板开场。",
    "工具调用要服务于清晰的工作思路。每次读取或修改后先判断结果，禁止无依据地反复读取、搜索、编辑或重试。",
    "上下文中的较早工具结果可能已压缩为结构化摘要，... 表示大字段已省略。如果当前修改依赖精确文件内容，应重新读取对应文件；已保留的路径、状态和错误可直接使用。",
    "涉及「当前、今天、最近、今年」等相对时间时，以系统注入的当前时间为准；不要把文件修改时间、评测时间戳、报告生成时间或日志时间当作当前时间。",
    "只有当用户问题或生成内容需要分钟/秒级精确当前时间时，才调用 get_current_time；一般时间判断使用按小时截断的上下文以利用缓存。",
]

SUBTASK_INSTRUCTIONS = [
    "你是 Skill Creator Subtask Agent，只处理父智能体交给你的单个明确子任务。",
    "当前工作目录就是当前 Skill 根目录。所有路径都必须相对当前 Skill 根目录。",
    "你必须使用工具查看和修改文件，不要要求用户粘贴当前文件内容。",
    "优先 grep/find/ls 定位，再用 skill_manage(action='read') 读取；所有修改都通过 skill_manage，优先使用唯一匹配 patch，并在完成后 validate。",
    "脚本必须离线运行，只能依赖标准库、当前 skill 内文件、或用户明确约定的依赖。",
    "涉及相对时间时，以系统注入的当前时间为准；文件时间戳、报告时间戳和日志时间不是当前时间。",
    "只有需要分钟/秒级精确当前时间时，才调用 get_current_time。",
    "完成后只返回简短总结：做了什么、改了哪些文件、还有什么风险或待确认事项。不要粘贴完整文件内容。",
]

QA_SYSTEM_PROMPT = """你是 Skill 文档问答助手。只能基于提供的 Skill 文件内容回答问题。
若资料不足请明确说明。回答使用中文，引用具体文件路径。
涉及「当前、今天、最近、今年」等相对时间时，以用户消息中的当前系统时间为准；不要把文件修改时间、评测时间戳、报告生成时间或日志时间当作当前时间。"""


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatSession:
    session_id: str
    slug: str
    category: str | None = None
    tenant_id: str = ""
    messages: list[ChatMessage] = field(default_factory=list)
    summary: str = ""
    tool_memory: list[str] = field(default_factory=list)
    compressed_turns: int = 0
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)


@dataclass
class StreamRun:
    run_id: str
    session_id: str
    slug: str
    mode: str
    tenant_id: str = ""
    llm: QaLlmConfig | None = None
    temperature: float | None = None
    enable_thinking: bool | None = None
    events: list[str] = field(default_factory=list)
    status: str = "running"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    completed_at: float | None = None


_sessions: dict[str, ChatSession] = {}
_runs: dict[str, StreamRun] = {}


def _mark_run_finished(run: StreamRun, status: str) -> None:
    run.status = status
    run.completed_at = time.time()


def _prune_state(now: float | None = None) -> None:
    current = time.time() if now is None else now
    removable_run_ids = [
        run_id
        for run_id, run in _runs.items()
        if run.status in ("completed", "error", "canceled")
        and run.completed_at is not None
        and current - run.completed_at > RUN_RETENTION_S
    ]
    for run_id in removable_run_ids:
        _runs.pop(run_id, None)

    if len(_runs) > MAX_RETAINED_RUNS:
        finished = sorted(
            (
                (run.completed_at or run.created_at, run_id)
                for run_id, run in _runs.items()
                if run.status in ("completed", "error", "canceled")
            )
        )
        overflow = len(_runs) - MAX_RETAINED_RUNS
        for _finished_at, run_id in finished[:overflow]:
            _runs.pop(run_id, None)

    active_session_ids = {
        run.session_id
        for run in _runs.values()
        if run.status not in ("completed", "error", "canceled")
    }
    removable_session_ids = [
        session_id
        for session_id, session in _sessions.items()
        if session_id not in active_session_ids
        and current - session.last_accessed_at > SESSION_IDLE_RETENTION_S
    ]
    for session_id in removable_session_ids:
        _sessions.pop(session_id, None)


def create_session(
    slug: str, category: str | None = None, tenant_id: str = ""
) -> dict[str, Any]:
    _prune_state()
    session_id = str(uuid.uuid4())
    _sessions[session_id] = ChatSession(
        session_id=session_id, tenant_id=tenant_id, slug=slug, category=category
    )
    return {"session_id": session_id, "category": category}


def _get_session(session_id: str, slug: str, tenant_id: str) -> ChatSession:
    session = _sessions.get(session_id)
    if not session:
        session = ChatSession(session_id=session_id, tenant_id=tenant_id, slug=slug)
        _sessions[session_id] = session
    elif session.slug != slug or session.tenant_id != tenant_id:
        raise RuntimeError("会话不属于当前 tenant 或 skill")
    session.last_accessed_at = time.time()
    return session


def get_run(run_id: str) -> StreamRun | None:
    _prune_state()
    run = _runs.get(run_id)
    if run:
        run.last_accessed_at = time.time()
    return run


def _run_matches(
    run: StreamRun,
    *,
    tenant_id: str | None = None,
    slug: str | None = None,
    session_id: str | None = None,
    mode: str | None = None,
) -> bool:
    if tenant_id is not None and run.tenant_id != tenant_id:
        return False
    if slug is not None and run.slug != slug:
        return False
    if session_id is not None and run.session_id != session_id:
        return False
    if mode is not None and run.mode != mode:
        return False
    return True


def _get_authorized_run(
    run_id: str,
    *,
    tenant_id: str | None = None,
    slug: str | None = None,
    session_id: str | None = None,
    mode: str | None = None,
) -> StreamRun | None:
    run = _runs.get(run_id)
    if not run:
        return None
    if not _run_matches(
        run, tenant_id=tenant_id, slug=slug, session_id=session_id, mode=mode
    ):
        return None
    run.last_accessed_at = time.time()
    return run


def cancel_run(
    run_id: str,
    *,
    tenant_id: str | None = None,
    slug: str | None = None,
    session_id: str | None = None,
) -> bool:
    run = _get_authorized_run(
        run_id, tenant_id=tenant_id, slug=slug, session_id=session_id
    )
    if not run or run.status in ("completed", "error", "canceled"):
        return False
    run.status = "canceling"
    if run.task and not run.task.done():
        run.task.cancel()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_force_cancel_after_grace(run))
        except RuntimeError:
            _close_canceled_run_if_needed(run)
    else:
        _mark_run_finished(run, "canceled")
        run.done.set()
    return True


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/chat/completions"


def _build_agents_context(skill_root: Path) -> str:
    del skill_root
    agents_path = SKILL_STUDIO_RESOURCE_DIR / AGENTS_FILE_NAME
    try:
        safe_parent = SKILL_STUDIO_RESOURCE_DIR.resolve()
        resolved = agents_path.resolve()
        if resolved.parent != safe_parent or not resolved.is_file():
            return ""
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    content = content.strip()
    if not content:
        return ""
    truncated = content[:AGENTS_CONTEXT_MAX_CHARS]
    suffix = "\n[AGENTS.md 内容已截断]" if len(content) > len(truncated) else ""
    return truncated + suffix


def _current_time_context_block() -> str:
    return f"{CURRENT_TIME_CONTEXT_LABEL}：{current_time_context()}"


def _build_skill_creator_context() -> str:
    skill_md = SKILL_CREATOR_RESOURCE_DIR / "SKILL.md"
    try:
        resolved = skill_md.resolve()
        resource_root = SKILL_CREATOR_RESOURCE_DIR.resolve()
        if resource_root not in resolved.parents or not resolved.is_file():
            return ""
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    content = content.strip()
    if not content:
        return ""
    truncated = content[:SKILL_CREATOR_CONTEXT_MAX_CHARS]
    suffix = (
        "\n[skill-creator/SKILL.md 内容已截断]" if len(content) > len(truncated) else ""
    )
    return truncated + suffix


async def _append_event(run: StreamRun, event: str) -> None:
    async with run.lock:
        run.events.append(event)


def _close_canceled_run_if_needed(run: StreamRun) -> None:
    if run.done.is_set():
        return
    run.events.append(
        f"event: reasoning\ndata: "
        f"{json.dumps({'type': 'canceled', 'message': '运行已取消'}, ensure_ascii=False)}\n\n"
    )
    run.events.append("event: reasoning\ndata: [DONE]\n\n")
    _mark_run_finished(run, "canceled")
    run.done.set()


def _bind_task_lifecycle(run: StreamRun, task: asyncio.Task) -> asyncio.Task:
    def _on_done(done_task: asyncio.Task) -> None:
        if done_task.cancelled():
            _close_canceled_run_if_needed(run)

    task.add_done_callback(_on_done)
    return task


async def _force_cancel_after_grace(run: StreamRun) -> None:
    try:
        await asyncio.wait_for(run.done.wait(), timeout=CANCEL_GRACE_S)
        return
    except asyncio.TimeoutError:
        pass
    if run.status == "canceling" and not run.done.is_set():
        _close_canceled_run_if_needed(run)


async def _chat_stream(
    messages: list[dict[str, str]],
    system_prompt: str,
    llm: QaLlmConfig,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> AsyncGenerator[str, None]:
    url = _chat_completions_url(llm.base_url)
    payload = {
        "model": llm.model,
        "messages": [{"role": "system", "content": system_prompt}, *messages],
        "stream": True,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if enable_thinking is not None:
        payload["enable_thinking"] = enable_thinking
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {llm.api_key}",
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                raise RuntimeError(
                    f"LLM 调用失败 ({resp.status_code}): {body.decode()[:200]}"
                )
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content
                except json.JSONDecodeError:
                    continue


async def _chat_once(
    messages: list[dict[str, str]],
    system_prompt: str,
    llm: QaLlmConfig,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> str:
    url = _chat_completions_url(llm.base_url)
    payload = {
        "model": llm.model,
        "messages": [{"role": "system", "content": system_prompt}, *messages],
        "stream": False,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if enable_thinking is not None:
        payload["enable_thinking"] = enable_thinking
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {llm.api_key}",
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"LLM 调用失败 ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    return str(
        data.get("choices", [{}])[0].get("message", {}).get("content") or ""
    ).strip()


def _snip_context_text(
    text: str, max_chars: int = CONVERSATION_CONTEXT_MAX_CHARS_PER_MESSAGE
) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    lines = text.splitlines()
    if len(lines) > 10:
        head = "\n".join(lines[:5])
        tail = "\n".join(lines[-5:])
        return (
            f"{head}\n"
            f"...（已省略 {max(0, len(lines) - 10)} 行用于上下文压缩）...\n"
            f"{tail}"
        )[:max_chars]
    keep = max(200, max_chars // 2)
    return f"{text[:keep]}\n...（已省略中间内容用于上下文压缩）...\n{text[-keep:]}"


def _session_context_size(messages: list[ChatMessage]) -> int:
    return sum(len(message.content or "") for message in messages)


def _flatten_messages_for_summary(messages: list[ChatMessage]) -> str:
    parts: list[str] = []
    for idx, message in enumerate(messages, 1):
        role = "用户" if message.role == "user" else "助手"
        content = _snip_context_text(message.content, 2500)
        if content:
            parts.append(f"## {idx}. {role}\n{content}")
    return "\n\n".join(parts)


def _extract_fallback_summary(
    existing_summary: str, messages: list[ChatMessage]
) -> str:
    files_seen: set[str] = set()
    errors: list[str] = []
    constraints: list[str] = []
    for message in messages:
        text = message.content or ""
        for match in re.finditer(
            r"[\w./-]+\.(?:md|py|json|ya?ml|toml|txt|ts|tsx|js|jsx|css|html)", text
        ):
            files_seen.add(match.group(0).lstrip("./"))
        for line in text.splitlines():
            stripped = line.strip()
            lowered = stripped.lower()
            if any(
                key in lowered for key in ("error", "exception", "失败", "报错", "错误")
            ):
                errors.append(stripped[:180])
            if any(
                key in stripped
                for key in ("不要", "必须", "只能", "离线", "确认", "用户希望")
            ):
                constraints.append(stripped[:180])

    parts: list[str] = []
    if existing_summary:
        parts.append(existing_summary)
    if files_seen:
        parts.append("涉及文件：" + "、".join(sorted(files_seen)[:30]))
    if constraints:
        parts.append("用户约束/偏好：" + "；".join(constraints[:12]))
    if errors:
        parts.append("历史错误/风险：" + "；".join(errors[:8]))
    return "\n".join(parts).strip() or "旧对话已压缩；无可提取的关键上下文。"


async def _summarize_session_history(
    session: ChatSession,
    old_messages: list[ChatMessage],
    llm: QaLlmConfig,
    temperature: float | None,
    enable_thinking: bool | None,
) -> str:
    source_parts: list[str] = []
    if session.summary:
        source_parts.append("已有长期摘要：\n" + session.summary)
    source_parts.append(
        "待压缩旧对话：\n" + _flatten_messages_for_summary(old_messages)
    )
    source = "\n\n".join(source_parts)[:CONVERSATION_SUMMARY_MAX_SOURCE_CHARS]
    prompt = (
        "你负责压缩 Skill Studio 的长期对话上下文。\n"
        "保留：用户长期目标、明确约束、已经做过的关键决策、改过或重点关注的文件路径、"
        "未解决问题、用户偏好、离线依赖要求、需要后续继续遵守的事项。\n"
        "丢弃：寒暄、重复说明、大段代码、完整文件内容、冗长工具输出、已经过期的中间过程。\n"
        "输出中文，结构紧凑，控制在 1200 字以内。"
    )
    try:
        summary = await _chat_once(
            [{"role": "user", "content": source}],
            prompt,
            llm,
            temperature,
            enable_thinking,
        )
        return (
            summary[:4000]
            if summary
            else _extract_fallback_summary(session.summary, old_messages)
        )
    except Exception:
        logger.exception("Skill studio session summarization failed")
        return _extract_fallback_summary(session.summary, old_messages)


async def _compact_session_if_needed(
    session: ChatSession,
    llm: QaLlmConfig | None,
    temperature: float | None,
    enable_thinking: bool | None,
) -> bool:
    if not llm:
        return False
    if len(session.messages) <= CONVERSATION_SUMMARIZE_AT_MESSAGES and (
        _session_context_size(session.messages) <= CONVERSATION_SUMMARIZE_AT_CHARS
    ):
        return False
    if len(session.messages) <= CONVERSATION_KEEP_RECENT:
        return False

    old_messages = session.messages[:-CONVERSATION_KEEP_RECENT]
    recent_messages = session.messages[-CONVERSATION_KEEP_RECENT:]
    summary = await _summarize_session_history(
        session, old_messages, llm, temperature, enable_thinking
    )
    session.summary = summary
    session.compressed_turns += len(old_messages)
    session.messages = recent_messages
    return True


def _extract_user_request(message: str) -> str:
    match = re.search(r"<user-request>\s*([\s\S]*?)\s*</user-request>", message)
    if match:
        return match.group(1).strip()
    return message.strip()


def _build_skill_tree_context(skill_root: Path) -> str:
    if not skill_root.exists():
        return "当前 Skill 目录不存在。"

    paths = [
        str(path.relative_to(skill_root)).replace("\\", "/")
        for path in sorted(skill_root.rglob("*"))
        if path.is_file()
    ]
    if not paths:
        return "当前 Skill 文件树为空。"
    visible = paths[:200]
    suffix = "\n[文件列表已截断]" if len(paths) > len(visible) else ""
    return "当前 Skill 文件树：\n" + "\n".join(visible) + suffix


def _build_conversation_context(
    session: ChatSession, exclude_latest: bool = False
) -> str:
    messages = session.messages[:-1] if exclude_latest else session.messages
    if not messages and not session.summary and not session.tool_memory:
        return ""
    lines: list[str] = []
    if session.summary:
        lines.append(
            "长期压缩摘要：\n"
            + session.summary
            + f"\n（已压缩旧消息 {session.compressed_turns} 条）"
        )
    if session.tool_memory:
        lines.append(
            "近期工具结论（较早的大字段已用 ... 省略，必要时重新读取文件）：\n"
            + "\n\n".join(session.tool_memory)
        )
    for message in messages[-CONVERSATION_KEEP_RECENT:]:
        role = "用户" if message.role == "user" else "助手"
        content = _snip_context_text(message.content)
        if not content:
            continue
        lines.append(f"{role}: {content}")
    if not lines:
        return ""
    return "会话上下文：\n" + "\n\n".join(lines)


ITERATION_BUDGET_SUMMARY_REQUEST = (
    "本次 Agent 运行的迭代预算已经用完。现在禁止调用任何工具，也不要尝试等待或重试。"
    "请仅根据上方已经完成的工具结果，给用户一段简短、诚实的收尾说明："
    "说明已经完成、保存和验证了什么，哪些内容仍未完成或未经验证，并给出明确的下一步建议。"
    "不得把尚未执行的修改或验证描述成成功。"
)
ITERATION_BUDGET_FALLBACK = (
    "本次运行已达到 Agent 迭代预算，工具执行已经停止，但模型未能生成有效总结。"
    "上方已完成的结果仍然保留；请回复“继续”，我会从未完成的步骤接着处理。"
)


@dataclass
class IterationBudgetOpenAILike(OpenAILike):
    """Add a model-request budget around Agno's otherwise unbounded tool loop."""

    iteration_budget: int | None = None
    iteration_count: int = field(default=0, init=False)
    iteration_budget_exhausted: bool = field(default=False, init=False)

    async def aprocess_response_stream(
        self,
        messages: list[AgnoMessage],
        assistant_message: AgnoMessage,
        stream_data: Any,
        response_format: Any = None,
        tools: Any = None,
        tool_choice: Any = None,
        run_response: Any = None,
        compress_tool_results: bool = False,
    ) -> AsyncIterator[Any]:
        self.iteration_count += 1
        summarizing = (
            self.iteration_budget is not None
            and self.iteration_count > self.iteration_budget
        )
        request_messages = messages
        request_tools = tools
        request_tool_choice = tool_choice
        if summarizing:
            self.iteration_budget_exhausted = True
            # Keep the synthetic summary request out of Agno's persisted/live
            # message list. The final assistant answer remains part of the run.
            request_messages = list(messages)
            request_messages.append(
                AgnoMessage(role="user", content=ITERATION_BUDGET_SUMMARY_REQUEST)
            )
            request_tools = []
            request_tool_choice = "none"

        try:
            async for response in super().aprocess_response_stream(
                messages=request_messages,
                assistant_message=assistant_message,
                stream_data=stream_data,
                response_format=response_format,
                tools=request_tools,
                tool_choice=request_tool_choice,
                run_response=run_response,
                compress_tool_results=compress_tool_results,
            ):
                yield response
        except Exception:
            if not summarizing:
                raise
            # The final synthesis is best-effort. A provider failure here must
            # not turn already completed work into a generic Agent run error.
            assistant_message.role = self.assistant_message_role
            assistant_message.content = ITERATION_BUDGET_FALLBACK
            yield ModelResponse(content=ITERATION_BUDGET_FALLBACK)

        if summarizing:
            # Some OpenAI-compatible providers may still emit a tool-shaped
            # payload even without tool schemas. Never let that reopen the loop.
            assistant_message.tool_calls = None


def _create_agno_model(
    llm: QaLlmConfig,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
    iteration_budget: int | None = None,
) -> IterationBudgetOpenAILike:
    kwargs: dict[str, Any] = {
        "id": llm.model,
        "base_url": llm.base_url,
        "api_key": llm.api_key,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if enable_thinking is not None:
        kwargs["extra_body"] = {"enable_thinking": enable_thinking}
    return IterationBudgetOpenAILike(
        **kwargs,
        iteration_budget=iteration_budget,
    )


class GuardedSkillCodingTools(CodingTools):
    def __init__(self, *args: Any, is_canceled: Any = None, **kwargs: Any):
        self._is_canceled = is_canceled or (lambda: False)
        super().__init__(*args, **kwargs)

    def _reject_if_canceled(self) -> str | None:
        if self._is_canceled():
            return "Error: run was canceled; file writes are blocked."
        return None

    def edit_file(self, file_path: str, old_text: str, new_text: str) -> str:
        rejected = self._reject_if_canceled()
        if rejected:
            return rejected
        return super().edit_file(file_path, old_text, new_text)

    def write_file(self, file_path: str, contents: str) -> str:
        rejected = self._reject_if_canceled()
        if rejected:
            return rejected
        return super().write_file(file_path, contents)


def _create_skill_coding_tools(
    skill_root: Path,
    is_canceled: Any = None,
    *,
    enable_file_tools: bool = True,
) -> CodingTools:
    return GuardedSkillCodingTools(
        base_dir=skill_root,
        is_canceled=is_canceled,
        restrict_to_base_dir=True,
        max_lines=1200,
        max_bytes=50000,
        enable_read_file=enable_file_tools,
        enable_edit_file=enable_file_tools,
        enable_write_file=enable_file_tools,
        enable_run_shell=False,
        enable_grep=True,
        enable_find=True,
        enable_ls=True,
    )


def _truncate_subtask_result(text: str) -> str:
    text = text.strip()
    if len(text) <= SUBTASK_RESULT_MAX_CHARS:
        return text
    head = text[: SUBTASK_RESULT_MAX_CHARS - 300]
    return head + "\n...（子智能体输出已截断，只保留摘要进入主上下文）"


class SkillSubtaskToolkit(Toolkit):
    def __init__(
        self,
        skill_root: Path,
        llm: QaLlmConfig,
        temperature: float | None,
        enable_thinking: bool | None = None,
        is_canceled: Any = None,
    ):
        self.skill_root = skill_root
        self.llm = llm
        self.temperature = temperature
        self.enable_thinking = enable_thinking
        self.is_canceled = is_canceled or (lambda: False)
        super().__init__(
            name="skill_subtask",
            tools=[self.skill_subtask],
            instructions=(
                "Use skill_subtask for a self-contained research or editing sub-task. "
                "The sub-agent has its own context window and the same restricted file tools. "
                "Do not use it for decisions that require asking the user first."
            ),
            add_instructions=True,
            auto_register=False,
        )
        self.register(self.skill_subtask)

    async def skill_subtask(self, task: str) -> str:
        """Run an independent sub-agent for one self-contained Skill editing or research task."""
        clean_task = str(task or "").strip()
        if not clean_task:
            return "Subtask failed: task is empty."
        if self.is_canceled():
            return "Subtask canceled before start."

        sub_model = _create_agno_model(
            self.llm,
            self.temperature,
            self.enable_thinking,
            iteration_budget=SUBTASK_ITERATION_BUDGET,
        )
        sub_agent = Agent(
            model=sub_model,
            tools=[
                CurrentTimeToolkit(),
                SkillManageToolkit(
                    self.skill_root, is_canceled=self.is_canceled
                ),
                _create_skill_coding_tools(
                    self.skill_root,
                    is_canceled=self.is_canceled,
                    enable_file_tools=False,
                ),
            ],
            instructions=SUBTASK_INSTRUCTIONS,
            additional_context="\n\n".join(
                [
                    _current_time_context_block(),
                    _build_skill_tree_context(self.skill_root),
                ]
            ),
            markdown=False,
            stream=True,
            stream_events=True,
            compress_tool_results=True,
            compression_manager=SkillToolCompressionManager(),
            telemetry=False,
        )

        result = ""
        async for event in sub_agent.arun(
            clean_task,
            stream=True,
            stream_events=True,
            session_id=f"subtask-{uuid.uuid4()}",
        ):
            event_type = getattr(event, "event", "")
            if event_type == RunEvent.run_content.value:
                content = getattr(event, "content", None)
                if content:
                    result += str(content)
            elif event_type == RunEvent.run_error.value:
                content = getattr(event, "content", None) or "子智能体运行失败"
                return f"Subtask error: {content}"

        if sub_model.iteration_budget_exhausted and not result.strip():
            return (
                "[Subtask iteration budget reached]\n"
                "子任务已停止工具执行，但未能生成有效的收尾摘要；未完成工作不能视为成功。"
            )
        return "[Subtask completed]\n" + _truncate_subtask_result(
            result or "子任务完成，但没有返回摘要。"
        )


class CurrentTimeToolkit(Toolkit):
    """Small time tool for exact on-demand system time checks."""

    def __init__(self) -> None:
        super().__init__(
            name="current_time",
            tools=[self.get_current_time],
            instructions=(
                "Use get_current_time only when minute- or second-level current "
                "system time is required. Prefer cached hour-level context for "
                "ordinary relative-time reasoning."
            ),
            add_instructions=True,
            auto_register=False,
        )
        self.register(self.get_current_time)

    def get_current_time(self, include_seconds: bool = False) -> str:
        """Get exact current system time on demand.

        Args:
            include_seconds: Include seconds only when explicitly needed.
        """
        return (
            "当前系统时间（按需精确获取，不用于默认 prompt cache）："
            f"{exact_current_time_context(include_seconds=bool(include_seconds))}"
        )


def _clip_tool_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    head = max(int(limit * 0.7), 1)
    tail = max(limit - head - 36, 0)
    suffix = text[-tail:] if tail else ""
    return f"{text[:head]}\n... [中间内容已省略] ...\n{suffix}".strip()


def _compact_tool_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 3:
        if isinstance(value, (dict, list)):
            return f"... [{len(value)} 项已省略]"
        return _clip_tool_text(value, 240)
    if isinstance(value, dict):
        items = list(value.items())
        compacted = {
            str(key): _compact_tool_value(item, depth=depth + 1)
            for key, item in items[:12]
        }
        if len(items) > 12:
            compacted["..."] = f"还有 {len(items) - 12} 个字段已省略"
        return compacted
    if isinstance(value, list):
        compacted = [_compact_tool_value(item, depth=depth + 1) for item in value[:4]]
        if len(value) > 4:
            compacted.append(f"... [还有 {len(value) - 4} 项已省略]")
        return compacted
    if isinstance(value, str):
        return _clip_tool_text(value, 700)
    return value


def _display_tool_args(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    displayed: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            displayed[str(key)] = _clip_tool_text(value, 4000)
        else:
            displayed[str(key)] = _compact_tool_value(value)
    return displayed


def _format_tool_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, (dict, list)):
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        text = str(result).strip()
        try:
            text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    if len(text) > TOOL_DISPLAY_MAX_CHARS:
        return text[:TOOL_DISPLAY_MAX_CHARS].rstrip() + "\n[显示已截断]"
    return text


def _tool_capsule(
    tool_name: str,
    args: Any,
    result: Any,
    *,
    status: str = "success",
) -> str:
    capsule = {
        "tool": tool_name,
        "status": status,
        "input": _compact_tool_value(args),
        "result_summary": _clip_tool_text(result, 1400),
        "note": "较早工具结果已分层压缩，原始大字段以 ... 省略；必要时重新调用工具。",
    }
    return _clip_tool_text(
        "[较早工具结果已压缩]\n"
        + json.dumps(capsule, ensure_ascii=False, indent=2),
        TOOL_CAPSULE_MAX_CHARS,
    )


class SkillToolCompressionManager(CompressionManager):
    """Deterministically age Skill coding-tool results without another LLM call."""

    def _candidates(self, messages: list[AgnoMessage]) -> list[AgnoMessage]:
        uncompressed = [
            message
            for message in messages
            if message.role == "tool" and message.compressed_content is None
        ]
        if not uncompressed:
            return []
        protected_ids = {
            id(message) for message in uncompressed[-TOOL_COMPRESSION_KEEP_RECENT:]
        }

        def _skill_action(message: AgnoMessage) -> str:
            args = message.tool_args
            if message.tool_name == "skill_manage" and isinstance(args, dict):
                return str(args.get("action") or "").lower()
            return ""

        # Preserve the newest file read until a later mutation supersedes it.
        for index in range(len(uncompressed) - 1, -1, -1):
            message = uncompressed[index]
            is_read = message.tool_name == "read_file" or _skill_action(message) == "read"
            if not is_read:
                continue
            has_later_write = any(
                later.tool_name in {"edit_file", "write_file"}
                or _skill_action(later) in {"patch", "edit", "write_file"}
                for later in uncompressed[index + 1 :]
            )
            if not has_later_write:
                protected_ids.add(id(message))
            break
        return [message for message in uncompressed if id(message) not in protected_ids]

    def should_compress(
        self,
        messages: list[AgnoMessage],
        tools: Any = None,
        model: Any = None,
        response_format: Any = None,
    ) -> bool:
        candidates = self._candidates(messages)
        if not candidates:
            return False
        tool_messages = [message for message in messages if message.role == "tool"]
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
        for message in self._candidates(messages):
            original_size = len(message.get_content_string())
            message.compressed_content = _tool_capsule(
                message.tool_name or "unknown",
                message.tool_args,
                message.content,
            )
            self.stats["tool_results_compressed"] = (
                self.stats.get("tool_results_compressed", 0) + 1
            )
            self.stats["original_size"] = self.stats.get("original_size", 0) + original_size
            self.stats["compressed_size"] = (
                self.stats.get("compressed_size", 0) + len(message.compressed_content)
            )

    async def acompress(
        self,
        messages: list[AgnoMessage],
        run_metrics: Any = None,
    ) -> None:
        self.compress(messages, run_metrics=run_metrics)


def _remember_tool_result(session: ChatSession, tool: Any, status: str) -> None:
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


async def _append_agno_tool_event(run: StreamRun, tool: Any, status: str) -> None:
    name = getattr(tool, "tool_name", None) or "tool"
    args = getattr(tool, "tool_args", None)
    result = getattr(tool, "result", None)
    tool_call_id = getattr(tool, "tool_call_id", None)
    display_args = _display_tool_args(args)
    if name == "skill_manage" and "file_path" not in display_args:
        display_args["file_path"] = "SKILL.md"
    tool_data = {
        "name": name,
        "preview": _format_tool_result(result),
        "args": display_args,
        "status": status,
        "tool_call_id": tool_call_id,
    }
    await _append_event(
        run,
        f"event: tool\ndata: {json.dumps(tool_data, ensure_ascii=False)}\n\n",
    )
    if name in {"edit_file", "write_file"}:
        await asyncio.sleep(FILE_WRITE_EVENT_DELAY_S)


async def _run_agno_dev_agent(
    run: StreamRun,
    user_message: str,
    skill_root: Path,
    session: ChatSession,
) -> str:
    if not run.llm:
        raise RuntimeError("未配置 Skill Studio 大模型")

    agents_context = _build_agents_context(skill_root)
    skill_creator_context = _build_skill_creator_context()
    additional_context_parts = [
        _current_time_context_block(),
        _build_skill_tree_context(skill_root),
        _build_conversation_context(session, exclude_latest=True),
    ]
    if agents_context:
        additional_context_parts.append(
            "<skill-studio-environment-instructions>\n"
            + agents_context
            + "\n</skill-studio-environment-instructions>"
        )
    if skill_creator_context:
        additional_context_parts.append(
            "<builtin-skill-creator-instructions>\n"
            + skill_creator_context
            + "\n</builtin-skill-creator-instructions>"
        )

    model = _create_agno_model(
        run.llm,
        run.temperature,
        run.enable_thinking,
        iteration_budget=AGENT_ITERATION_BUDGET,
    )

    agent = Agent(
        model=model,
        tools=[
            SkillManageToolkit(
                skill_root, is_canceled=lambda: run.status == "canceling"
            ),
            _create_skill_coding_tools(
                skill_root,
                is_canceled=lambda: run.status == "canceling",
                enable_file_tools=False,
            ),
            CurrentTimeToolkit(),
            SkillSubtaskToolkit(
                skill_root,
                run.llm,
                run.temperature,
                run.enable_thinking,
                is_canceled=lambda: run.status == "canceling",
            ),
        ],
        instructions=AGNO_DEV_INSTRUCTIONS,
        additional_context="\n\n".join(
            part for part in additional_context_parts if part
        ),
        markdown=False,
        stream=True,
        stream_events=True,
        compress_tool_results=True,
        compression_manager=SkillToolCompressionManager(),
        telemetry=False,
    )

    final_answer = ""
    pending_content = ""
    reasoning_delta_seen = False

    async for event in agent.arun(
        user_message,
        stream=True,
        stream_events=True,
        session_id=run.session_id,
    ):
        event_type = getattr(event, "event", "")
        if event_type == RunEvent.run_content.value:
            content = getattr(event, "content", None)
            if content:
                text = str(content)
                final_answer += text
                pending_content += text
                await _append_event(
                    run,
                    f"event: token\ndata: {json.dumps({'content': text}, ensure_ascii=False)}\n\n",
                )
        elif event_type == RunEvent.run_intermediate_content.value:
            content = getattr(event, "content", None)
            if content:
                await _append_event(
                    run,
                    f"event: process\ndata: {json.dumps({'content': str(content)}, ensure_ascii=False)}\n\n",
                )
        elif event_type == RunEvent.reasoning_started.value:
            reasoning_delta_seen = False
        elif event_type == RunEvent.reasoning_content_delta.value:
            reasoning_content = getattr(event, "reasoning_content", None)
            if reasoning_content:
                reasoning_delta_seen = True
                await _append_event(
                    run,
                    f"event: reasoning\ndata: {json.dumps({'type': 'model_delta', 'message': str(reasoning_content)}, ensure_ascii=False)}\n\n",
                )
        elif event_type == RunEvent.reasoning_step.value:
            reasoning_content = getattr(event, "reasoning_content", None)
            if not reasoning_delta_seen and reasoning_content:
                await _append_event(
                    run,
                    f"event: reasoning\ndata: {json.dumps({'type': 'model', 'message': str(reasoning_content)}, ensure_ascii=False)}\n\n",
                )
        elif event_type == RunEvent.tool_call_started.value:
            tool = getattr(event, "tool", None)
            if tool is not None:
                if pending_content:
                    await _append_event(
                        run,
                        f"event: interim_assistant\ndata: {json.dumps({'content': pending_content, 'already_streamed': True}, ensure_ascii=False)}\n\n",
                    )
                    pending_content = ""
                await _append_agno_tool_event(run, tool, "running")
        elif event_type == RunEvent.tool_call_completed.value:
            tool = getattr(event, "tool", None)
            if tool is not None:
                _remember_tool_result(session, tool, "success")
                await _append_agno_tool_event(run, tool, "success")
        elif event_type == RunEvent.tool_call_error.value:
            tool = getattr(event, "tool", None)
            if tool is not None:
                _remember_tool_result(session, tool, "error")
                await _append_agno_tool_event(run, tool, "error")
            error = getattr(event, "error", None)
            if error:
                await _append_event(
                    run,
                    f"event: reasoning\ndata: {json.dumps({'type': 'progress', 'message': str(error)}, ensure_ascii=False)}\n\n",
                )
        elif event_type == RunEvent.run_error.value:
            content = getattr(event, "content", None) or "Skill Agent 运行失败"
            raise RuntimeError(str(content))

    if model.iteration_budget_exhausted:
        if pending_content.strip():
            return pending_content.strip()
        return (
            ITERATION_BUDGET_FALLBACK
        )
    # Content emitted after the final tool call is the user-facing conclusion;
    # earlier content has already been shown as interleaved process narration.
    return pending_content.strip() or final_answer.strip()


async def _produce_dev_run(
    run: StreamRun,
    user_message: str,
    skill_root: Path,
    category: str | None,
) -> None:
    session = _get_session(run.session_id, run.slug, run.tenant_id)
    if category:
        session.category = category
    clean_user_message = _extract_user_request(user_message)
    session.messages.append(ChatMessage(role="user", content=clean_user_message))

    try:
        final_answer = await _run_agno_dev_agent(
            run, clean_user_message, skill_root, session
        )
        session.messages.append(ChatMessage(role="assistant", content=final_answer))
        compacted = await _compact_session_if_needed(
            session, run.llm, run.temperature, run.enable_thinking
        )
        if compacted:
            await _append_event(
                run,
                f"event: reasoning\ndata: {json.dumps({'type': 'progress', 'message': '已压缩旧会话上下文'}, ensure_ascii=False)}\n\n",
            )
        message = final_answer or "处理完成。"
        await _append_event(
            run,
            f"event: complete\ndata: {json.dumps({'type': 'complete', 'message': message}, ensure_ascii=False)}\n\n",
        )

        await _append_event(run, "event: reasoning\ndata: [DONE]\n\n")
        _mark_run_finished(run, "completed")
    except asyncio.CancelledError:
        await _append_event(
            run,
            f"event: reasoning\ndata: {json.dumps({'type': 'canceled', 'message': '运行已取消'}, ensure_ascii=False)}\n\n",
        )
        await _append_event(run, "event: reasoning\ndata: [DONE]\n\n")
        _mark_run_finished(run, "canceled")
    except Exception as exc:
        logger.exception("Skill studio chat failed")
        run.error_message = str(exc)
        _mark_run_finished(run, "error")
        await _append_event(
            run,
            f"event: reasoning\ndata: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n",
        )
        await _append_event(run, "event: reasoning\ndata: [DONE]\n\n")
    finally:
        run.done.set()


async def _produce_qa_run(
    run: StreamRun,
    user_message: str,
    skill_root: Path,
    service,
) -> None:
    del skill_root
    session = _get_session(run.session_id, run.slug, run.tenant_id)
    session.messages.append(ChatMessage(role="user", content=user_message))

    context_parts: list[str] = []
    for entry in list_skill_files(service, run.slug):
        if entry["type"] != "file":
            continue
        try:
            detail = read_skill_file(service, run.slug, entry["path"])
            if not detail["is_binary"] and detail["content"]:
                context_parts.append(f"### {entry['path']}\n{detail['content'][:8000]}")
        except Exception:
            continue

    context = "\n\n".join(context_parts[:20]) or "（暂无文件内容）"
    conversation_context = _build_conversation_context(session, exclude_latest=True)
    system = (
        QA_SYSTEM_PROMPT
        + f"\n\n{_current_time_context_block()}"
        + f"\n\nSkill 文件：\n{context}"
        + (f"\n\n{conversation_context}" if conversation_context else "")
        + f"\n\n用户问题：{user_message}"
    )

    await _append_event(
        run,
        f"event: reasoning\ndata: {json.dumps({'type': 'start', 'message': '正在思考...'}, ensure_ascii=False)}\n\n",
    )
    await _append_event(
        run,
        f"event: reasoning\ndata: {json.dumps({'type': 'progress', 'message': '正在思考...（0 字符）'}, ensure_ascii=False)}\n\n",
    )

    full_response = ""
    last_progress_at = time.monotonic()
    if not run.llm:
        raise RuntimeError("未配置 Skill Studio 大模型")

    try:
        async for chunk in _chat_stream(
            [{"role": "user", "content": user_message}],
            system,
            run.llm,
            run.temperature,
            run.enable_thinking,
        ):
            full_response += chunk
            now = time.monotonic()
            if now - last_progress_at >= LLM_PROGRESS_INTERVAL_S:
                await _append_event(
                    run,
                    f"event: reasoning\ndata: {json.dumps({'type': 'progress', 'message': f'正在思考...（{len(full_response)} 字符）'}, ensure_ascii=False)}\n\n",
                )
                last_progress_at = now
            if chunk:
                await _append_event(
                    run,
                    f"event: token\ndata: {json.dumps({'content': chunk}, ensure_ascii=False)}\n\n",
                )
        session.messages.append(ChatMessage(role="assistant", content=full_response))
        compacted = await _compact_session_if_needed(
            session, run.llm, run.temperature, run.enable_thinking
        )
        if compacted:
            await _append_event(
                run,
                f"event: reasoning\ndata: {json.dumps({'type': 'progress', 'message': '已压缩旧会话上下文'}, ensure_ascii=False)}\n\n",
            )
        await _append_event(
            run,
            f"event: reasoning\ndata: {json.dumps({'type': 'complete', 'message': '回答完成'}, ensure_ascii=False)}\n\n",
        )
        await _append_event(run, "event: reasoning\ndata: [DONE]\n\n")
        _mark_run_finished(run, "completed")
    except asyncio.CancelledError:
        await _append_event(
            run,
            f"event: reasoning\ndata: {json.dumps({'type': 'canceled', 'message': '运行已取消'}, ensure_ascii=False)}\n\n",
        )
        await _append_event(run, "event: reasoning\ndata: [DONE]\n\n")
        _mark_run_finished(run, "canceled")
    except Exception as exc:
        run.error_message = str(exc)
        _mark_run_finished(run, "error")
        await _append_event(
            run,
            f"event: reasoning\ndata: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n",
        )
        await _append_event(run, "event: reasoning\ndata: [DONE]\n\n")
    finally:
        run.done.set()


def _create_run(
    tenant_id: str,
    session_id: str,
    slug: str,
    mode: str,
    llm: QaLlmConfig | None = None,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> StreamRun:
    _prune_state()
    run_id = str(uuid.uuid4())
    run = StreamRun(
        run_id=run_id,
        session_id=session_id,
        tenant_id=tenant_id,
        slug=slug,
        mode=mode,
        llm=llm,
        temperature=temperature,
        enable_thinking=enable_thinking,
    )
    _runs[run_id] = run
    return run


async def start_dev_run(
    tenant_id: str,
    slug: str,
    session_id: str,
    user_message: str,
    skill_root: Path,
    category: str | None = None,
    llm: QaLlmConfig | None = None,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> StreamRun:
    run = _create_run(
        tenant_id,
        session_id,
        slug,
        "dev",
        llm=llm,
        temperature=temperature,
        enable_thinking=enable_thinking,
    )
    await _append_event(
        run,
        f"event: run\ndata: {json.dumps({'run_id': run.run_id, 'status': 'running'}, ensure_ascii=False)}\n\n",
    )
    run.task = _bind_task_lifecycle(
        run,
        asyncio.create_task(_produce_dev_run(run, user_message, skill_root, category)),
    )
    return run


async def start_qa_run(
    tenant_id: str,
    slug: str,
    session_id: str,
    user_message: str,
    skill_root: Path,
    service,
    llm: QaLlmConfig | None = None,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> StreamRun:
    run = _create_run(
        tenant_id,
        session_id,
        slug,
        "qa",
        llm=llm,
        temperature=temperature,
        enable_thinking=enable_thinking,
    )
    await _append_event(
        run,
        f"event: run\ndata: {json.dumps({'run_id': run.run_id, 'status': 'running'}, ensure_ascii=False)}\n\n",
    )
    run.task = _bind_task_lifecycle(
        run,
        asyncio.create_task(_produce_qa_run(run, user_message, skill_root, service)),
    )
    return run


async def stream_run_events(
    run_id: str,
    from_index: int | None = None,
    tenant_id: str | None = None,
    slug: str | None = None,
    session_id: str | None = None,
    mode: str | None = None,
) -> AsyncGenerator[str, None]:
    run = _get_authorized_run(
        run_id, tenant_id=tenant_id, slug=slug, session_id=session_id, mode=mode
    )
    if not run:
        yield (
            f"event: reasoning\ndata: "
            f"{json.dumps({'type': 'error', 'message': '流式任务不存在或已过期'}, ensure_ascii=False)}\n\n"
        )
        yield "event: reasoning\ndata: [DONE]\n\n"
        return

    idx = max(0, from_index or 0)

    while True:
        batch: list[str] = []
        async with run.lock:
            while idx < len(run.events):
                batch.append(run.events[idx])
                idx += 1

        for event in batch:
            yield event

        if run.done.is_set():
            async with run.lock:
                while idx < len(run.events):
                    yield run.events[idx]
                    idx += 1
            break

        await asyncio.sleep(0.02)


async def process_studio_chat_stream(
    tenant_id: str,
    slug: str,
    session_id: str,
    user_message: str,
    skill_root: Path,
    category: str | None = None,
    resume_run_id: str | None = None,
    from_index: int | None = None,
    llm: QaLlmConfig | None = None,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> AsyncGenerator[str, None]:
    if resume_run_id:
        async for chunk in stream_run_events(
            resume_run_id,
            from_index=from_index,
            tenant_id=tenant_id,
            slug=slug,
            session_id=session_id,
            mode="dev",
        ):
            yield chunk
        return

    run = await start_dev_run(
        tenant_id,
        slug,
        session_id,
        user_message,
        skill_root,
        category,
        llm=llm,
        temperature=temperature,
        enable_thinking=enable_thinking,
    )
    async for chunk in stream_run_events(run.run_id, from_index=0):
        yield chunk


async def process_studio_qa_stream(
    tenant_id: str,
    slug: str,
    session_id: str,
    user_message: str,
    skill_root: Path,
    service,
    resume_run_id: str | None = None,
    from_index: int | None = None,
    llm: QaLlmConfig | None = None,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> AsyncGenerator[str, None]:
    if resume_run_id:
        async for chunk in stream_run_events(
            resume_run_id,
            from_index=from_index,
            tenant_id=tenant_id,
            slug=slug,
            session_id=session_id,
            mode="qa",
        ):
            yield chunk
        return

    run = await start_qa_run(
        tenant_id,
        slug,
        session_id,
        user_message,
        skill_root,
        service,
        llm=llm,
        temperature=temperature,
        enable_thinking=enable_thinking,
    )
    async for chunk in stream_run_events(run.run_id, from_index=0):
        yield chunk
