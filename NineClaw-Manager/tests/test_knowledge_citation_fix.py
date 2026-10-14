"""Regression tests for RAG citation index stability."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agno.run.agent import RunEvent

from app.services.knowledge_agno_agent import (
    KnowledgeRAGToolkit,
    _format_conversation_context,
    _strip_citation_markers,
    sanitize_out_of_range_citations,
)
from app.services.knowledge_llm_service import QaLlmConfig


def _ref(chunk_id: str, *, score: float = 0.9) -> dict:
    return {
        "dataset_id": "kb1",
        "file_id": "doc1",
        "file_name": "中美贸易战来龙去脉.docx",
        "chunk_id": chunk_id,
        "text": f"chunk {chunk_id}",
        "score": score,
        "available": True,
    }


class DummyKnowledgeService:
    def ensure_exists(self, kb_id: str) -> None:
        return None


def test_sanitize_removes_out_of_range_citation_not_as_plain_text():
    text = "贸易战依据1974年贸易法第301条发起[3]，另见[11]。"
    cleaned = sanitize_out_of_range_citations(text, max_index=6)
    assert "[3]" in cleaned
    assert "[11]" not in cleaned
    assert "另见。" in cleaned or "另见" in cleaned


def test_sanitize_keeps_valid_range_only():
    cleaned = sanitize_out_of_range_citations("结论[1][2][5][7]", max_index=5)
    assert cleaned == "结论[1][2][5]"


def test_rag_retrieve_output_includes_citation_range_header():
    toolkit = KnowledgeRAGToolkit(DummyKnowledgeService(), ["kb1"], top_k=5)
    toolkit.service = DummyKnowledgeService()

    def fake_collect(*_args, **_kwargs):
        return [_ref(f"c{i}") for i in range(1, 4)]

    from app.services import knowledge_agno_agent as mod

    original = mod._collect_references
    mod._collect_references = fake_collect
    try:
        result = toolkit.rag_retrieve("贸易战依据什么法条发起")
    finally:
        mod._collect_references = original

    assert "引用编号说明" in result
    assert "[1] 至 [3]" in result
    assert "不要使用文档内切片序号" in result


def test_conversation_history_strips_old_citation_markers():
    history = [
        {"role": "user", "content": "上一轮问题"},
        {
            "role": "assistant",
            "content": "上一轮回答末尾有引用[8][2]。",
        },
        {"role": "user", "content": "新问题"},
    ]
    text = _format_conversation_context(history)
    assert "[1]" not in text
    assert "[2]" not in text
    assert "上一轮回答末尾有引用" in text


@pytest.mark.asyncio
async def test_run_agno_qa_agent_uses_last_rag_retrieve_references(monkeypatch):
    from app.services import knowledge_agno_qa_runtime as mod

    toolkit_holder: dict[str, KnowledgeRAGToolkit] = {}
    emitted_reference_batches: list[list[dict]] = []
    tool_events: list[dict] = []

    def capture_create(_llm, toolkit, **_kwargs):
        toolkit_holder["toolkit"] = toolkit

        async def fake_arun(*_args, **_kwargs):
            toolkit.last_references = [_ref("c1"), _ref("c2")]
            yield SimpleNamespace(
                event=RunEvent.tool_call_completed.value,
                tool=SimpleNamespace(
                    tool_name="rag_retrieve",
                    tool_args={"question": "第一次检索"},
                    tool_call_id="call-1",
                ),
            )
            toolkit.last_references = [_ref("c3"), _ref("c4"), _ref("c5")]
            yield SimpleNamespace(
                event=RunEvent.tool_call_completed.value,
                tool=SimpleNamespace(
                    tool_name="rag_retrieve",
                    tool_args={"question": "第二次检索"},
                    tool_call_id="call-2",
                ),
            )
            yield SimpleNamespace(
                event=RunEvent.run_content.value,
                content="依据301条款发起[3][11]。",
            )

        return SimpleNamespace(arun=fake_arun)

    async def capture_emit(_run, references):
        emitted_reference_batches.append(list(references))

    async def capture_tool_event(run, tool, status, *, args_overlay=None):
        args = dict(getattr(tool, "tool_args", {}) or {})
        if args_overlay:
            args.update(args_overlay)
        tool_events.append(
            {
                "name": getattr(tool, "tool_name", ""),
                "status": status,
                "references": args.get("references"),
            }
        )

    token_events: list[str] = []

    async def capture_studio_event(run, event):
        run.events.append(event)
        if '"content":' in event and "依据" in event:
            token_events.append(event)

    monkeypatch.setattr(mod, "create_knowledge_qa_agent", capture_create)
    monkeypatch.setattr(mod, "_emit_studio_references", capture_emit)
    monkeypatch.setattr(mod, "_append_agno_tool_event", capture_tool_event)
    monkeypatch.setattr(mod, "_append_studio_event", capture_studio_event)

    llm = QaLlmConfig(base_url="https://example.test/v1", api_key="key", model="m")
    references_out: list[dict] = []
    studio_run = mod._StudioRun(
        run_id="run-1",
        session_id="sess-1",
        kb_id="kb1",
    )

    answer = await mod._run_agno_qa_agent(
        llm=llm,
        service=DummyKnowledgeService(),  # type: ignore[arg-type]
        question="贸易战依据什么法条发起",
        dataset_ids=["kb1"],
        top_k=5,
        rerank_id=None,
        tenant_rerank_id=None,
        temperature=None,
        enable_thinking=None,
        conversation_history=None,
        session_id="sess-1",
        studio_run=studio_run,
        references_out=references_out,
    )

    assert answer == "依据301条款发起[3]。"
    assert "[11]" not in answer
    assert any("[3]" in e and "[11]" not in e for e in token_events)
    assert [item["chunk_id"] for item in references_out] == ["c3", "c4", "c5"]
    assert emitted_reference_batches[-1] == references_out
    assert len(emitted_reference_batches) == 2
    assert tool_events[-1]["references"] == references_out


def test_strip_citation_markers_preserves_non_citation_brackets():
    assert _strip_citation_markers("法条[301]与引用[1]") == "法条[301]与引用"
