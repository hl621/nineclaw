"""Tests for knowledge studio assistant runtime."""

from __future__ import annotations

import asyncio

import pytest


def test_assistant_runtime_create_session_returns_ids() -> None:
    from app.services import knowledge_agno_qa_runtime as mod

    data = mod.create_studio_session("kb-demo", category="qa", tenant_id="tenant-a")

    assert data["session_id"]
    assert data["kb_id"] == "kb-demo"
    assert data["category"] == "qa"


@pytest.mark.asyncio
async def test_assistant_runtime_persists_session_history(monkeypatch) -> None:
    from app.services import knowledge_agno_qa_runtime as mod
    from app.services.knowledge_llm_service import QaLlmConfig

    mod._studio_sessions.clear()
    mod._studio_runs.clear()
    seen_histories: list[list[dict[str, str]] | None] = []

    async def fake_run_agent(**kwargs) -> str:
        seen_histories.append(kwargs["conversation_history"])
        kwargs["references_out"][:] = []
        return f"回答：{kwargs['question']}"

    monkeypatch.setattr(mod, "_run_agno_qa_agent", fake_run_agent)
    llm = QaLlmConfig(base_url="https://example.test/v1", api_key="key", model="m")
    session = mod.create_studio_session("kb-demo", tenant_id="tenant-a")["session_id"]

    async for _ in mod.process_agno_studio_qa_stream(
        "tenant-a",
        "kb-demo",
        session,
        "第一个问题",
        service=object(),  # type: ignore[arg-type]
        llm=llm,
    ):
        pass
    async for _ in mod.process_agno_studio_qa_stream(
        "tenant-a",
        "kb-demo",
        session,
        "刚才我问的是什么？",
        service=object(),  # type: ignore[arg-type]
        llm=llm,
    ):
        pass

    assert seen_histories[0] == []
    assert seen_histories[1] == [
        {"role": "user", "content": "第一个问题"},
        {"role": "assistant", "content": "回答：第一个问题"},
    ]


@pytest.mark.asyncio
async def test_assistant_runtime_cancel_requires_matching_scope(monkeypatch) -> None:
    from app.services import knowledge_agno_qa_runtime as mod
    from app.services.knowledge_llm_service import QaLlmConfig

    mod._studio_sessions.clear()
    mod._studio_runs.clear()

    async def slow_run_agent(**_kwargs) -> str:
        await asyncio.sleep(30)
        return "done"

    monkeypatch.setattr(mod, "_run_agno_qa_agent", slow_run_agent)
    llm = QaLlmConfig(base_url="https://example.test/v1", api_key="key", model="m")
    session = mod.create_studio_session("kb-demo", tenant_id="tenant-a")["session_id"]
    stream = mod.process_agno_studio_qa_stream(
        "tenant-a",
        "kb-demo",
        session,
        "hello",
        service=object(),  # type: ignore[arg-type]
        llm=llm,
    )
    first = await stream.__anext__()
    assert "event: run" in first
    run = next(reversed(mod._studio_runs.values()))

    assert (
        mod.cancel_studio_run(
            run.run_id, tenant_id="tenant-b", kb_id="kb-demo", session_id=session
        )
        is False
    )
    assert (
        mod.cancel_studio_run(
            run.run_id, tenant_id="tenant-a", kb_id="kb-demo", session_id=session
        )
        is True
    )
    await asyncio.wait_for(run.done.wait(), timeout=1)
    await stream.aclose()

    assert run.status == "canceled"
    assert any('"type": "canceled"' in e for e in run.events)


@pytest.mark.asyncio
async def test_assistant_runtime_compacts_session_history(monkeypatch) -> None:
    from app.services import knowledge_agno_qa_runtime as mod
    from app.services.knowledge_llm_service import QaLlmConfig

    session = mod._StudioSession(session_id="sess-compact", kb_id="kb-demo")
    session.messages = [
        mod._ChatMessage(
            role="user" if i % 2 == 0 else "assistant", content=f"消息 {i}"
        )
        for i in range(mod.CONVERSATION_SUMMARIZE_AT_MESSAGES + 2)
    ]

    async def fake_summarize(*_args, **_kwargs) -> str:
        return "压缩摘要"

    monkeypatch.setattr(mod, "_summarize_session_history", fake_summarize)
    llm = QaLlmConfig(base_url="https://example.test/v1", api_key="key", model="m")

    compacted = await mod._compact_session_if_needed(
        session, llm, temperature=None, enable_thinking=None
    )

    assert compacted is True
    assert session.summary == "压缩摘要"
    assert session.compressed_turns == (
        mod.CONVERSATION_SUMMARIZE_AT_MESSAGES
        + 2
        - mod.CONVERSATION_KEEP_RECENT
    )
    assert len(session.messages) == mod.CONVERSATION_KEEP_RECENT
