from __future__ import annotations

import asyncio

import pytest
from agno.models.message import Message as AgnoMessage
from agno.models.openai.like import OpenAILike

from app.services import skill_studio_chat as chat


@pytest.fixture(autouse=True)
def clear_studio_state():
    chat._sessions.clear()
    chat._runs.clear()
    yield
    chat._sessions.clear()
    chat._runs.clear()


def test_extract_user_request_unwraps_tagged_payload() -> None:
    message = "prefix <user-request>\n请修改 SKILL.md\n</user-request> suffix"

    assert chat._extract_user_request(message) == "请修改 SKILL.md"


def test_skill_agents_md_includes_time_awareness() -> None:
    path = chat.SKILL_STUDIO_RESOURCE_DIR / "AGENTS.md"
    content = path.read_text(encoding="utf-8")

    assert "Time Awareness" in content
    assert "当前系统时间（按小时截断）" in content
    assert "get_current_time" in content
    assert "file modification time" in content


def test_current_time_context_block_is_hour_precision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        chat, "current_time_context", lambda: "2026-06-24 20:00 UTC+08:00"
    )

    block = chat._current_time_context_block()

    assert (
        block
        == "当前系统时间（按小时截断，用于解释相对时间，不代表文件时间）：2026-06-24 20:00 UTC+08:00"
    )
    assert ":00 UTC" in block


def test_skill_qa_system_prompt_mentions_current_time_boundary() -> None:
    assert "当前系统时间" in chat.QA_SYSTEM_PROMPT
    assert "不要把文件修改时间" in chat.QA_SYSTEM_PROMPT


def test_chat_url_does_not_infer_v1_prefix() -> None:
    assert chat._chat_completions_url("http://model-server:8000") == (
        "http://model-server:8000/chat/completions"
    )
    assert chat._chat_completions_url("http://model-server:8000/v1/") == (
        "http://model-server:8000/v1/chat/completions"
    )


def test_current_time_tool_returns_exact_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        chat,
        "exact_current_time_context",
        lambda include_seconds=False: "2026-06-24 20:37 UTC+08:00",
    )
    toolkit = chat.CurrentTimeToolkit()

    result = toolkit.get_current_time()

    assert "当前系统时间" in result
    assert "2026-06-24 20:37 UTC+08:00" in result
    assert "prompt cache" in result


@pytest.mark.asyncio
async def test_iteration_budget_uses_one_toolless_summary_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict] = []

    async def fake_process(
        self,
        messages,
        assistant_message,
        stream_data,
        response_format=None,
        tools=None,
        tool_choice=None,
        run_response=None,
        compress_tool_results=False,
    ):
        requests.append(
            {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        assistant_message.tool_calls = [{"id": "hallucinated-tool-call"}]
        yield "chunk"

    monkeypatch.setattr(OpenAILike, "aprocess_response_stream", fake_process)
    model = chat.IterationBudgetOpenAILike(
        id="test",
        api_key="test",
        iteration_budget=1,
    )
    original_messages = [AgnoMessage(role="user", content="请修改")]

    first_assistant = AgnoMessage(role="assistant")
    first = model.aprocess_response_stream(
        original_messages,
        first_assistant,
        stream_data=object(),
        tools=[{"type": "function"}],
        tool_choice="auto",
    )
    assert [item async for item in first] == ["chunk"]
    assert model.iteration_budget_exhausted is False
    assert requests[0]["tools"] == [{"type": "function"}]

    summary_assistant = AgnoMessage(role="assistant")
    summary = model.aprocess_response_stream(
        original_messages,
        summary_assistant,
        stream_data=object(),
        tools=[{"type": "function"}],
        tool_choice="auto",
    )
    assert [item async for item in summary] == ["chunk"]
    assert model.iteration_budget_exhausted is True
    assert requests[1]["tools"] == []
    assert requests[1]["tool_choice"] == "none"
    assert "迭代预算已经用完" in requests[1]["messages"][-1].content
    assert len(original_messages) == 1
    assert summary_assistant.tool_calls is None


@pytest.mark.asyncio
async def test_iteration_budget_summary_failure_returns_fixed_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_process(self, *args, **kwargs):
        raise RuntimeError("provider unavailable")
        yield  # pragma: no cover - keeps this an async generator

    monkeypatch.setattr(OpenAILike, "aprocess_response_stream", failing_process)
    model = chat.IterationBudgetOpenAILike(
        id="test",
        api_key="test",
        iteration_budget=0,
    )
    assistant = AgnoMessage(role="assistant")

    stream = model.aprocess_response_stream(
        [AgnoMessage(role="user", content="继续")],
        assistant,
        stream_data=object(),
        tools=[{"type": "function"}],
    )

    responses = [item async for item in stream]
    assert responses[0].content == chat.ITERATION_BUDGET_FALLBACK
    assert assistant.content == chat.ITERATION_BUDGET_FALLBACK
    assert assistant.tool_calls is None


@pytest.mark.asyncio
async def test_cancel_run_stops_dev_task_and_streams_canceled_event(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def slow_agent(*args, **kwargs) -> str:
        await asyncio.sleep(60)
        return "should not finish"

    monkeypatch.setattr(chat, "_run_agno_dev_agent", slow_agent)

    run = await chat.start_dev_run(
        "tenant-a",
        "demo-skill",
        "session-1",
        "make a change",
        tmp_path,
    )
    await asyncio.sleep(0)

    assert chat.cancel_run(run.run_id, tenant_id="tenant-a", slug="demo-skill") is True
    await asyncio.wait_for(run.done.wait(), timeout=1)

    assert run.status == "canceled"
    assert run.completed_at is not None
    events = [
        event
        async for event in chat.stream_run_events(
            run.run_id, from_index=0, tenant_id="tenant-a", slug="demo-skill"
        )
    ]
    joined = "".join(events)
    assert '"type": "canceled"' in joined
    assert "data: [DONE]" in joined


def test_cancel_run_rejects_finished_run() -> None:
    run = chat._create_run("tenant-a", "session-1", "demo-skill", "dev")
    chat._mark_run_finished(run, "completed")
    run.done.set()

    assert chat.cancel_run(run.run_id) is False
    assert run.status == "completed"


def test_prune_state_removes_expired_finished_runs_and_idle_sessions() -> None:
    session = chat.ChatSession(
        session_id="old-session", tenant_id="tenant-a", slug="demo-skill"
    )
    session.last_accessed_at = 100.0
    chat._sessions[session.session_id] = session

    run = chat._create_run("tenant-a", "old-session", "demo-skill", "dev")
    chat._mark_run_finished(run, "completed")
    run.completed_at = 100.0

    now = 100.0 + max(chat.RUN_RETENTION_S, chat.SESSION_IDLE_RETENTION_S) + 1
    chat._prune_state(now=now)

    assert run.run_id not in chat._runs
    assert session.session_id not in chat._sessions


def test_guarded_coding_tools_block_writes_after_cancel(tmp_path) -> None:
    target = tmp_path / "SKILL.md"
    target.write_text("before", encoding="utf-8")
    canceled = False
    tools = chat._create_skill_coding_tools(tmp_path, is_canceled=lambda: canceled)

    assert "Wrote" in tools.write_file("new.txt", "created")
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "created"

    canceled = True
    write_result = tools.write_file("blocked.txt", "blocked")
    edit_result = tools.edit_file("SKILL.md", "before", "after")

    assert "file writes are blocked" in write_result
    assert "file writes are blocked" in edit_result
    assert not (tmp_path / "blocked.txt").exists()
    assert target.read_text(encoding="utf-8") == "before"


def test_get_session_rejects_cross_skill_or_tenant_reuse() -> None:
    chat.create_session("demo-skill", tenant_id="tenant-a")
    session_id = next(iter(chat._sessions))

    with pytest.raises(RuntimeError, match="tenant 或 skill"):
        chat._get_session(session_id, "other-skill", "tenant-a")

    with pytest.raises(RuntimeError, match="tenant 或 skill"):
        chat._get_session(session_id, "demo-skill", "tenant-b")


def test_tool_display_keeps_real_input_and_bounds_large_text() -> None:
    args = chat._display_tool_args(
        {"file_path": "SKILL.md", "old_text": "before-" + "x" * 5000}
    )

    assert args["file_path"] == "SKILL.md"
    assert args["old_text"].startswith("before-")
    assert "中间内容已省略" in args["old_text"]


def test_tool_memory_is_injected_into_follow_up_context() -> None:
    session = chat.ChatSession(
        session_id="session-1",
        tenant_id="tenant-a",
        slug="demo-skill",
        tool_memory=["[较早工具结果已压缩]\n{\"tool\": \"read_file\"}"],
    )

    context = chat._build_conversation_context(session)

    assert "近期工具结论" in context
    assert '"tool": "read_file"' in context


@pytest.mark.asyncio
async def test_stream_run_events_validates_run_ownership() -> None:
    run = chat._create_run("tenant-a", "session-1", "demo-skill", "dev")
    await chat._append_event(run, "event: run\ndata: {}\n\n")
    chat._mark_run_finished(run, "completed")
    run.done.set()

    wrong_slug_events = [
        event
        async for event in chat.stream_run_events(
            run.run_id,
            tenant_id="tenant-a",
            slug="other-skill",
            session_id="session-1",
            mode="dev",
        )
    ]
    assert "流式任务不存在或已过期" in "".join(wrong_slug_events)

    owned_events = [
        event
        async for event in chat.stream_run_events(
            run.run_id,
            tenant_id="tenant-a",
            slug="demo-skill",
            session_id="session-1",
            mode="dev",
        )
    ]
    assert owned_events == ["event: run\ndata: {}\n\n"]


@pytest.mark.asyncio
async def test_stream_run_events_uses_per_call_from_index() -> None:
    run = chat._create_run("tenant-a", "session-1", "demo-skill", "dev")
    await chat._append_event(run, "event: one\ndata: 1\n\n")
    await chat._append_event(run, "event: two\ndata: 2\n\n")
    chat._mark_run_finished(run, "completed")
    run.done.set()

    first = [event async for event in chat.stream_run_events(run.run_id, from_index=0)]
    second = [event async for event in chat.stream_run_events(run.run_id, from_index=1)]

    assert first == ["event: one\ndata: 1\n\n", "event: two\ndata: 2\n\n"]
    assert second == ["event: two\ndata: 2\n\n"]


@pytest.mark.asyncio
async def test_force_cancel_after_grace_closes_canceling_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chat, "CANCEL_GRACE_S", 0)
    run = chat._create_run("tenant-a", "session-1", "demo-skill", "dev")
    run.status = "canceling"

    await chat._force_cancel_after_grace(run)

    assert run.status == "canceled"
    assert run.done.is_set()
    assert "运行已取消" in "".join(run.events)
