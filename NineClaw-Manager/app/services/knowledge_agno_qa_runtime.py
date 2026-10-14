"""SSE streaming for AGNO-based knowledge Q&A (legacy + studio formats)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Awaitable, Callable

import httpx
from agno.run.agent import RunEvent

from app.services.knowledge_agno_agent import (
    KnowledgeRAGToolkit,
    create_knowledge_qa_agent,
    sanitize_out_of_range_citations,
)
from app.services.knowledge_factory import KnowledgeBackend
from app.services.knowledge_llm_service import (
    QaLlmConfig,
    QaLlmError,
    _chat_completions_url,
)
from app.services.knowledge_qa_service import SSE_HEADERS, _sse_data

logger = logging.getLogger(__name__)

LLM_PROGRESS_INTERVAL_S = 2.0
CANCEL_GRACE_S = 5.0
CONVERSATION_KEEP_RECENT = 8
CONVERSATION_SUMMARIZE_AT_MESSAGES = 14
CONVERSATION_SUMMARIZE_AT_CHARS = 32000
CONVERSATION_SUMMARY_MAX_SOURCE_CHARS = 24000
CONVERSATION_CONTEXT_MAX_CHARS_PER_MESSAGE = 3000
RUN_RETENTION_S = 30 * 60
SESSION_IDLE_RETENTION_S = 6 * 60 * 60
MAX_RETAINED_RUNS = 200


@dataclass
class _ChatMessage:
    role: str
    content: str


@dataclass
class _StudioSession:
    session_id: str
    kb_id: str
    category: str | None = None
    tenant_id: str = ""
    messages: list[_ChatMessage] = field(default_factory=list)
    summary: str = ""
    compressed_turns: int = 0
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)


def _sse_event(event: str, data: Any) -> str:
    if data == "[DONE]":
        return f"event: {event}\ndata: [DONE]\n\n"
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _tool_preview(name: str, args: Any) -> str:
    if name == "rag_retrieve":
        if isinstance(args, dict) and args.get("question"):
            q = str(args["question"]).strip()
            if len(q) > 60:
                q = q[:57] + "..."
            return f"查询：{q}"
        return "查询知识库切片"
    return name


def _friendly_model_error(message: str) -> str:
    lowered = message.lower()
    if "invalid temperature" in lowered and "only 1" in lowered:
        return (
            "当前模型只接受 temperature=1。请点击问答输入框左侧齿轮，"
            "在「温度」中填入 1 后重试。"
        )
    return message


def _mark_run_finished(run: _StudioRun, status: str) -> None:
    run.status = status
    run.completed_at = time.time()


def _prune_state(now: float | None = None) -> None:
    current = time.time() if now is None else now
    removable_run_ids = [
        run_id
        for run_id, run in _studio_runs.items()
        if run.status in ("completed", "error", "canceled")
        and run.completed_at is not None
        and current - run.completed_at > RUN_RETENTION_S
    ]
    for run_id in removable_run_ids:
        _studio_runs.pop(run_id, None)

    if len(_studio_runs) > MAX_RETAINED_RUNS:
        finished = sorted(
            (
                (run.completed_at or run.created_at, run_id)
                for run_id, run in _studio_runs.items()
                if run.status in ("completed", "error", "canceled")
            )
        )
        overflow = len(_studio_runs) - MAX_RETAINED_RUNS
        for _finished_at, run_id in finished[:overflow]:
            _studio_runs.pop(run_id, None)

    active_session_ids = {
        run.session_id
        for run in _studio_runs.values()
        if run.status not in ("completed", "error", "canceled")
    }
    removable_session_ids = [
        session_id
        for session_id, session in _studio_sessions.items()
        if session_id not in active_session_ids
        and current - session.last_accessed_at > SESSION_IDLE_RETENTION_S
    ]
    for session_id in removable_session_ids:
        _studio_sessions.pop(session_id, None)


def create_studio_session(
    kb_id: str, category: str | None = None, tenant_id: str = ""
) -> dict[str, Any]:
    _prune_state()
    session_id = str(uuid.uuid4())
    _studio_sessions[session_id] = _StudioSession(
        session_id=session_id,
        kb_id=kb_id,
        category=category,
        tenant_id=tenant_id,
    )
    return {"session_id": session_id, "kb_id": kb_id, "category": category}


def _get_studio_session(session_id: str, kb_id: str, tenant_id: str) -> _StudioSession:
    session = _studio_sessions.get(session_id)
    if not session:
        session = _StudioSession(session_id=session_id, kb_id=kb_id, tenant_id=tenant_id)
        _studio_sessions[session_id] = session
    elif session.kb_id != kb_id or session.tenant_id != tenant_id:
        raise RuntimeError("会话不属于当前 tenant 或知识库")
    session.last_accessed_at = time.time()
    return session


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


def _session_context_size(messages: list[_ChatMessage]) -> int:
    return sum(len(message.content or "") for message in messages)


def _flatten_messages_for_summary(messages: list[_ChatMessage]) -> str:
    parts: list[str] = []
    for idx, message in enumerate(messages, 1):
        role = "用户" if message.role == "user" else "助手"
        content = _snip_context_text(message.content, 2500)
        if content:
            parts.append(f"## {idx}. {role}\n{content}")
    return "\n\n".join(parts)


def _extract_fallback_summary(
    existing_summary: str, messages: list[_ChatMessage]
) -> str:
    files_seen: set[str] = set()
    user_intents: list[str] = []
    for message in messages:
        text = message.content or ""
        for match in re.finditer(
            r"[\w./-]+\.(?:docx|pdf|md|txt|xlsx|pptx|html?)", text
        ):
            files_seen.add(match.group(0).lstrip("./"))
        if message.role == "user":
            stripped = text.strip()
            if stripped:
                user_intents.append(stripped[:180])

    parts: list[str] = []
    if existing_summary:
        parts.append(existing_summary)
    if files_seen:
        parts.append("涉及资料：" + "、".join(sorted(files_seen)[:30]))
    if user_intents:
        parts.append("用户近期问题/关注点：" + "；".join(user_intents[-8:]))
    return "\n".join(parts).strip() or "旧对话已压缩；无可提取的关键上下文。"


async def _chat_once(
    messages: list[dict[str, str]],
    system_prompt: str,
    llm: QaLlmConfig,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> str:
    payload: dict[str, Any] = {
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
        resp = await client.post(
            _chat_completions_url(llm.base_url), json=payload, headers=headers
        )
    if resp.status_code != 200:
        raise RuntimeError(f"LLM 调用失败 ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    return str(
        data.get("choices", [{}])[0].get("message", {}).get("content") or ""
    ).strip()


async def _summarize_session_history(
    session: _StudioSession,
    old_messages: list[_ChatMessage],
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
        "你负责压缩知识库问答智能体的长期对话上下文。\n"
        "保留：用户正在追问的主题、指代关系、已经确认的事实、关键资料名、"
        "未解决问题、用户偏好、需要继续遵守的限定条件。\n"
        "丢弃：寒暄、重复说明、大段引用原文、完整工具输出、已经过期的过程。\n"
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
        logger.exception("Knowledge studio session summarization failed")
        return _extract_fallback_summary(session.summary, old_messages)


async def _compact_session_if_needed(
    session: _StudioSession,
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
    session.summary = await _summarize_session_history(
        session, old_messages, llm, temperature, enable_thinking
    )
    session.compressed_turns += len(old_messages)
    session.messages = recent_messages
    return True


def _build_session_conversation_history(
    session: _StudioSession,
    *,
    exclude_latest: bool = False,
) -> list[dict[str, str]]:
    messages = session.messages[:-1] if exclude_latest else session.messages
    history: list[dict[str, str]] = []
    if session.summary:
        history.append(
            {
                "role": "assistant",
                "content": (
                    "长期压缩摘要：\n"
                    + session.summary
                    + f"\n（已压缩旧消息 {session.compressed_turns} 条）"
                ),
            }
        )
    for message in messages[-CONVERSATION_KEEP_RECENT:]:
        content = _snip_context_text(message.content)
        if content:
            history.append({"role": message.role, "content": content})
    return history


@dataclass
class _StudioRun:
    run_id: str
    session_id: str
    kb_id: str
    tenant_id: str = ""
    events: list[str] = field(default_factory=list)
    status: str = "running"
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    completed_at: float | None = None


_studio_sessions: dict[str, _StudioSession] = {}
_studio_runs: dict[str, _StudioRun] = {}


async def _append_studio_event(run: _StudioRun, event: str) -> None:
    async with run.lock:
        run.events.append(event)


def _get_authorized_studio_run(
    run_id: str,
    *,
    tenant_id: str | None = None,
    kb_id: str | None = None,
    session_id: str | None = None,
) -> _StudioRun | None:
    run = _studio_runs.get(run_id)
    if not run:
        return None
    if tenant_id is not None and run.tenant_id != tenant_id:
        return None
    if kb_id is not None and run.kb_id != kb_id:
        return None
    if session_id is not None and run.session_id != session_id:
        return None
    run.last_accessed_at = time.time()
    return run


def _close_canceled_studio_run_if_needed(run: _StudioRun) -> None:
    if run.done.is_set():
        return
    run.events.append(
        _sse_event("reasoning", {"type": "canceled", "message": "运行已取消"})
    )
    run.events.append(_sse_event("reasoning", "[DONE]"))
    _mark_run_finished(run, "canceled")
    run.done.set()


def _bind_studio_task_lifecycle(run: _StudioRun, task: asyncio.Task) -> asyncio.Task:
    def _on_done(done_task: asyncio.Task) -> None:
        if done_task.cancelled():
            _close_canceled_studio_run_if_needed(run)

    task.add_done_callback(_on_done)
    return task


async def _force_cancel_after_grace(run: _StudioRun) -> None:
    try:
        await asyncio.wait_for(run.done.wait(), timeout=CANCEL_GRACE_S)
        return
    except asyncio.TimeoutError:
        pass
    if run.status == "canceling" and not run.done.is_set():
        _close_canceled_studio_run_if_needed(run)


async def _emit_studio_references(
    run: _StudioRun,
    references: list[dict[str, Any]],
) -> None:
    if not references:
        return
    await _append_studio_event(
        run,
        _sse_event("references", {"references": references}),
    )


async def _append_agno_tool_event(
    run: _StudioRun,
    tool: Any,
    status: str,
    *,
    args_overlay: dict[str, Any] | None = None,
) -> None:
    name = getattr(tool, "tool_name", None) or "tool"
    args = getattr(tool, "tool_args", None)
    merged_args = dict(args) if isinstance(args, dict) else {}
    if args_overlay:
        merged_args.update(args_overlay)
    tool_data = {
        "name": name,
        "preview": _tool_preview(name, args),
        "args": merged_args,
        "status": status,
        "tool_call_id": getattr(tool, "tool_call_id", None),
    }
    await _append_studio_event(run, _sse_event("tool", tool_data))


async def _run_agno_qa_agent(
    *,
    llm: QaLlmConfig,
    service: KnowledgeBackend,
    question: str,
    dataset_ids: list[str],
    top_k: int,
    rerank_id: str | None,
    tenant_rerank_id: str | int | None,
    temperature: float | None,
    enable_thinking: bool | None,
    conversation_history: list[dict[str, str]] | None,
    session_id: str | None,
    studio_run: _StudioRun | None,
    references_out: list[dict[str, Any]],
    legacy_emit: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    cross_languages: list[str] | None = None,
) -> str:
    from app.services.knowledge_agno_agent import _format_conversation_context

    toolkit = KnowledgeRAGToolkit(
        service,
        dataset_ids,
        top_k=top_k,
        rerank_id=rerank_id,
        tenant_rerank_id=tenant_rerank_id,
        cross_languages=cross_languages,
    )
    conversation_context = _format_conversation_context(conversation_history)
    agent = create_knowledge_qa_agent(
        llm,
        toolkit,
        dataset_ids=dataset_ids,
        conversation_context=conversation_context,
        temperature=temperature,
        enable_thinking=enable_thinking,
    )

    final_answer = ""

    if studio_run:
        await _append_studio_event(
            studio_run,
            _sse_event("reasoning", {"type": "start", "message": "正在分析您的问题…"}),
        )

    async for event in agent.arun(
        question,
        stream=True,
        stream_events=True,
        session_id=session_id or f"kb-qa-{uuid.uuid4()}",
    ):
        if studio_run and studio_run.status == "canceling":
            raise asyncio.CancelledError()

        event_type = getattr(event, "event", "")

        if event_type == RunEvent.tool_call_started.value:
            tool = getattr(event, "tool", None)
            if tool is not None and studio_run:
                await _append_agno_tool_event(studio_run, tool, "running")

        elif event_type == RunEvent.tool_call_completed.value:
            tool = getattr(event, "tool", None)
            if tool is not None:
                name = getattr(tool, "tool_name", None) or ""
                is_rag_retrieve = (
                    "rag_retrieve" in name.lower() or name == "rag_retrieval"
                )
                if is_rag_retrieve and toolkit.last_references:
                    references_out[:] = list(toolkit.last_references)
                    if studio_run:
                        await _emit_studio_references(
                            studio_run, toolkit.last_references
                        )
                    elif legacy_emit is not None:
                        # 全局检索：检索一完成立刻下发资料来源，不必等整段回答生成完
                        await legacy_emit(
                            {
                                "type": "references",
                                "references": list(toolkit.last_references),
                            }
                        )
                if studio_run:
                    overlay = None
                    if is_rag_retrieve and toolkit.last_references:
                        overlay = {
                            "references": toolkit.last_references,
                            "dataset_ids": dataset_ids,
                        }
                    await _append_agno_tool_event(
                        studio_run,
                        tool,
                        "success",
                        args_overlay=overlay,
                    )

        elif event_type == RunEvent.tool_call_error.value:
            tool = getattr(event, "tool", None)
            if tool is not None and studio_run:
                await _append_agno_tool_event(studio_run, tool, "error")

        elif event_type == RunEvent.run_content.value:
            content = getattr(event, "content", None)
            if content:
                piece = str(content)
                # Agno 可能下发增量或累计全文；统一收成最终答案后再 sanitize 下发
                if final_answer and piece.startswith(final_answer):
                    final_answer = piece
                else:
                    final_answer += piece

        elif event_type == RunEvent.run_error.value:
            content = getattr(event, "content", None) or "知识问答 Agent 运行失败"
            raise RuntimeError(_friendly_model_error(str(content)))

    if not references_out and toolkit.last_references:
        references_out[:] = list(toolkit.last_references)
        if studio_run:
            await _emit_studio_references(studio_run, toolkit.last_references)
        elif legacy_emit is not None:
            await legacy_emit(
                {
                    "type": "references",
                    "references": list(toolkit.last_references),
                }
            )

    cleaned = sanitize_out_of_range_citations(
        final_answer.strip(), len(references_out)
    )
    if studio_run and cleaned:
        await _append_studio_event(
            studio_run,
            _sse_event("token", {"content": cleaned}),
        )
    return cleaned


async def knowledge_agno_qa_stream(
    service: KnowledgeBackend,
    question: str,
    dataset_ids: list[str],
    top_k: int = 5,
    rerank_id: str | None = None,
    tenant_rerank_id: str | int | None = None,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
    llm: QaLlmConfig | None = None,
) -> AsyncGenerator[str, None]:
    """Legacy SSE: references (as soon as retrieved) → content chunks → [DONE]."""
    if not dataset_ids:
        yield _sse_data({"type": "error", "message": "dataset_ids 不能为空"})
        yield _sse_data("[DONE]")
        return

    if llm is None:
        yield _sse_data(
            {
                "type": "error",
                "message": (
                    "未配置可用的大模型：请在「模型管理」中添加 Provider"
                ),
            }
        )
        yield _sse_data("[DONE]")
        return

    references: list[dict[str, Any]] = []
    event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    refs_emitted = False

    async def legacy_emit(payload: dict[str, Any]) -> None:
        nonlocal refs_emitted
        if payload.get("type") == "references":
            refs_emitted = True
        await event_queue.put(payload)

    run_error: BaseException | None = None
    final_answer = ""

    async def _runner() -> None:
        nonlocal run_error, final_answer
        try:
            final_answer = await _run_agno_qa_agent(
                llm=llm,
                service=service,
                question=question,
                dataset_ids=dataset_ids,
                top_k=top_k,
                rerank_id=rerank_id,
                tenant_rerank_id=tenant_rerank_id,
                temperature=temperature,
                enable_thinking=enable_thinking,
                conversation_history=None,
                session_id=None,
                studio_run=None,
                references_out=references,
                legacy_emit=legacy_emit,
            )
        except BaseException as exc:
            run_error = exc
        finally:
            await event_queue.put(None)

    task = asyncio.create_task(_runner())
    try:
        while True:
            item = await event_queue.get()
            if item is None:
                break
            yield _sse_data(item)
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        else:
            await task

    if run_error is not None:
        if isinstance(run_error, QaLlmError):
            yield _sse_data({"type": "error", "message": str(run_error)})
        elif isinstance(run_error, asyncio.CancelledError):
            raise run_error
        else:
            logger.error(
                "knowledge agno QA stream failed: %s",
                run_error,
                exc_info=run_error,
            )
            yield _sse_data(
                {"type": "error", "message": f"问答处理失败：{run_error}"}
            )
        yield _sse_data("[DONE]")
        return

    if not refs_emitted:
        yield _sse_data({"type": "references", "references": references})
    if final_answer:
        yield _sse_data({"type": "content", "content": final_answer})
    else:
        yield _sse_data(
            {
                "type": "content",
                "content": "未能生成回答，请检查模型配置或重试。",
            }
        )

    yield _sse_data("[DONE]")


async def _produce_studio_agno_run(
    run: _StudioRun,
    user_message: str,
    service: KnowledgeBackend,
    llm: QaLlmConfig,
    top_k: int,
    rerank_id: str | None,
    tenant_rerank_id: str | int | None,
    temperature: float | None,
    enable_thinking: bool | None,
    cross_languages: list[str] | None = None,
) -> None:
    session = _get_studio_session(run.session_id, run.kb_id, run.tenant_id)
    session.messages.append(_ChatMessage(role="user", content=user_message))
    history_for_agent = _build_session_conversation_history(
        session, exclude_latest=True
    )
    references: list[dict[str, Any]] = []
    try:
        await _append_studio_event(
            run,
            _sse_event("reasoning", {"type": "progress", "message": "正在查询知识库…"}),
        )
        final_answer = await _run_agno_qa_agent(
            llm=llm,
            service=service,
            question=user_message,
            dataset_ids=[run.kb_id],
            top_k=top_k,
            rerank_id=rerank_id,
            tenant_rerank_id=tenant_rerank_id,
            temperature=temperature,
            enable_thinking=enable_thinking,
            conversation_history=history_for_agent,
            session_id=run.session_id,
            studio_run=run,
            references_out=references,
            cross_languages=cross_languages,
        )
        session.messages.append(_ChatMessage(role="assistant", content=final_answer))
        compacted = await _compact_session_if_needed(
            session, llm, temperature, enable_thinking
        )
        if compacted:
            await _append_studio_event(
                run,
                _sse_event(
                    "reasoning",
                    {"type": "progress", "message": "已压缩旧会话上下文"},
                ),
            )
        await _append_studio_event(
            run,
            _sse_event(
                "reasoning",
                {
                    "type": "complete",
                    "message": "回答完成",
                    "references": references,
                },
            ),
        )
        if not final_answer:
            await _append_studio_event(
                run,
                _sse_event("token", {"content": "未能生成回答，请重试。"}),
            )
        await _append_studio_event(run, _sse_event("reasoning", "[DONE]"))
        _mark_run_finished(run, "completed")
    except asyncio.CancelledError:
        _close_canceled_studio_run_if_needed(run)
        raise
    except Exception as exc:
        logger.exception("Knowledge agno studio QA failed for kb %s", run.kb_id)
        run.error_message = str(exc)
        _mark_run_finished(run, "error")
        await _append_studio_event(
            run,
            _sse_event("reasoning", {"type": "error", "message": str(exc)}),
        )
        await _append_studio_event(run, _sse_event("reasoning", "[DONE]"))
    finally:
        run.done.set()


async def stream_studio_run_events(
    run_id: str,
    from_index: int | None = None,
    tenant_id: str | None = None,
    kb_id: str | None = None,
    session_id: str | None = None,
) -> AsyncGenerator[str, None]:
    run = _get_authorized_studio_run(
        run_id, tenant_id=tenant_id, kb_id=kb_id, session_id=session_id
    )
    if not run:
        yield _sse_event("reasoning", {"type": "error", "message": "流式任务不存在或已过期"})
        yield _sse_event("reasoning", "[DONE]")
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


def cancel_studio_run(
    run_id: str,
    *,
    tenant_id: str | None = None,
    kb_id: str | None = None,
    session_id: str | None = None,
) -> bool:
    run = _get_authorized_studio_run(
        run_id, tenant_id=tenant_id, kb_id=kb_id, session_id=session_id
    )
    if not run or run.status in ("completed", "error", "canceled"):
        return False
    run.status = "canceling"
    if run.task and not run.task.done():
        run.task.cancel()
        try:
            asyncio.get_running_loop().create_task(_force_cancel_after_grace(run))
        except RuntimeError:
            _close_canceled_studio_run_if_needed(run)
    else:
        _close_canceled_studio_run_if_needed(run)
    return True


async def process_agno_studio_qa_stream(
    tenant_id: str,
    kb_id: str,
    session_id: str,
    user_message: str,
    service: KnowledgeBackend,
    *,
    resume_run_id: str | None = None,
    from_index: int | None = None,
    llm: QaLlmConfig | None = None,
    top_k: int = 5,
    rerank_id: str | None = None,
    tenant_rerank_id: str | int | None = None,
    temperature: float | None = None,
    enable_thinking: bool | None = None,
    cross_languages: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    _prune_state()
    if resume_run_id:
        async for chunk in stream_studio_run_events(
            resume_run_id,
            from_index=from_index,
            tenant_id=tenant_id,
            kb_id=kb_id,
            session_id=session_id,
        ):
            yield chunk
        return

    if not llm:
        raise QaLlmError("未配置可用的大模型")

    _get_studio_session(session_id, kb_id, tenant_id)
    run_id = str(uuid.uuid4())
    run = _StudioRun(
        run_id=run_id, tenant_id=tenant_id, session_id=session_id, kb_id=kb_id
    )
    _studio_runs[run_id] = run
    await _append_studio_event(run, _sse_event("run", {"run_id": run_id, "status": "running"}))
    run.task = _bind_studio_task_lifecycle(
        run,
        asyncio.create_task(
            _produce_studio_agno_run(
                run,
                user_message,
                service,
                llm,
                top_k,
                rerank_id,
                tenant_rerank_id,
                temperature,
                enable_thinking,
                cross_languages,
            )
        ),
    )
    try:
        async for chunk in stream_studio_run_events(run_id, from_index=0):
            yield chunk
    finally:
        if not run.done.is_set() and run.status == "running":
            cancel_studio_run(
                run.run_id,
                tenant_id=tenant_id,
                kb_id=kb_id,
                session_id=session_id,
            )


LEGACY_SSE_HEADERS = SSE_HEADERS
