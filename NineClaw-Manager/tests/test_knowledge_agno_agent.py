"""Tests for AGNO knowledge Q&A agent resources."""

from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.services.knowledge_agno_agent import (
    KNOWLEDGE_STUDIO_RESOURCE_DIR,
    KnowledgeRAGToolkit,
    _coverage_terms,
    _decompose_question,
    _merge_references,
    _load_agents_context,
    _format_conversation_context,
    _strip_citation_markers,
    _create_agno_model,
)
from app.services.knowledge_llm_service import (
    QaLlmConfig,
    RAG_SYSTEM_PROMPT,
    _chat_completions_url,
    build_rag_messages,
)
from app.services.knowledge_time_context import current_time_context
from app.services.knowledge_time_context import exact_current_time_context


def test_agents_md_exists():
    path = KNOWLEDGE_STUDIO_RESOURCE_DIR / "AGENTS.md"
    assert path.is_file()
    content = path.read_text(encoding="utf-8")
    assert "Knowledge Q&A Agent" in content
    assert "rag_retrieve" in content
    assert "rag_check_sufficient_context" in content
    assert "rag_get_current_time" in content
    assert "rag_expand_context" in content
    assert "rag_grep_document" in content
    assert "Working Loop" in content
    assert "Answer Rules" in content
    assert "Time Awareness" in content
    assert "paragraph-level merged citations" in content
    assert "source chips/cards" in content


def test_load_agents_context():
    ctx = _load_agents_context()
    assert "rag_retrieve" in ctx
    assert "rag_check_sufficient_context" in ctx
    assert "rag_export_document_text" in ctx
    assert "context_review" in ctx
    assert "资料来源" in ctx
    assert "当前系统时间" in ctx
    assert "Citation Rules" in ctx or "引用" in ctx


def test_current_time_context_is_hour_precision():
    now = datetime(2026, 6, 24, 20, 37, 58, tzinfo=timezone(timedelta(hours=8)))
    assert current_time_context(now) == "2026-06-24 20:00 UTC+08:00"


def test_exact_current_time_context_can_include_seconds():
    now = datetime(2026, 6, 24, 20, 37, 58, tzinfo=timezone(timedelta(hours=8)))
    assert exact_current_time_context(now) == "2026-06-24 20:37 UTC+08:00"
    assert (
        exact_current_time_context(now, include_seconds=True)
        == "2026-06-24 20:37:58 UTC+08:00"
    )


def test_knowledge_toolkit_can_get_exact_current_time():
    toolkit = KnowledgeRAGToolkit(DummyKnowledgeService(), ["kb1"])

    result = toolkit.rag_get_current_time()

    assert "当前系统时间" in result
    assert "prompt cache" in result


def test_legacy_rag_messages_include_hour_precision_time_context():
    messages = build_rag_messages("今天有什么政策？", [])
    user_content = messages[-1]["content"]
    assert "当前系统时间（按小时截断" in user_content
    assert "用户问题：今天有什么政策？" in user_content


def test_knowledge_chat_url_does_not_infer_v1_prefix():
    assert _chat_completions_url("http://model-server:8000") == (
        "http://model-server:8000/chat/completions"
    )
    assert _chat_completions_url("http://model-server:8000/v1/") == (
        "http://model-server:8000/v1/chat/completions"
    )


def test_legacy_rag_prompt_uses_paragraph_level_citations():
    assert "段落级合并标记" in RAG_SYSTEM_PROMPT
    assert "不要每个句子都插角标" in RAG_SYSTEM_PROMPT
    assert "不要使用文档切片序号" in RAG_SYSTEM_PROMPT
    assert (
        "不要把文章时间、上传时间、解析时间或切片时间当作当前时间" in RAG_SYSTEM_PROMPT
    )
    assert "每条关键事实后都应附带" not in RAG_SYSTEM_PROMPT


def test_decompose_question_expands_year_range():
    queries = _decompose_question("2023至2025年 销售政策变化")
    assert queries == [
        "2023年 销售政策变化",
        "2024年 销售政策变化",
        "2025年 销售政策变化",
    ]


def test_merge_references_deduplicates_and_keeps_best_score():
    refs = _merge_references(
        [
            [{"chunk_id": "a", "text": "old", "score": 0.2}],
            [{"chunk_id": "a", "text": "new", "score": 0.8}],
            [{"chunk_id": "b", "text": "other", "score": 0.5}],
        ],
        top_k=5,
    )
    assert [item["chunk_id"] for item in refs] == ["a", "b"]
    assert refs[0]["score"] == 0.8


def test_coverage_terms_extracts_years_and_keywords():
    terms = _coverage_terms("2024年 合同 SLA 赔付规则是什么")
    assert "2024" in terms
    assert "sla" in terms
    assert any("合同" in term for term in terms)


class DummyKnowledgeService:
    def ensure_exists(self, kb_id: str) -> None:
        return None


def test_check_sufficient_context_reports_no_evidence():
    toolkit = KnowledgeRAGToolkit(DummyKnowledgeService(), ["kb1"])
    result = toolkit.rag_check_sufficient_context("2024年 合同 SLA 赔付规则")
    assert "status: no_evidence" in result


def test_check_sufficient_context_reports_missing_terms():
    toolkit = KnowledgeRAGToolkit(DummyKnowledgeService(), ["kb1"])
    toolkit.last_references = [
        {
            "dataset_id": "kb1",
            "file_id": "doc1",
            "chunk_id": "c1",
            "text": "2024年合同规则要求服务可用性达到约定标准。",
            "score": 0.3,
        }
    ]
    result = toolkit.rag_check_sufficient_context("2024年 合同 SLA 赔付规则")
    assert "status: needs_more_context" in result
    assert "sla" in result.lower()


def test_format_conversation_context():
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮您？[1][2]"},
    ]
    text = _format_conversation_context(history)
    assert "用户" in text
    assert "助手" in text
    assert "[1]" not in text
    assert "[2]" not in text


def test_strip_citation_markers():
    assert _strip_citation_markers("依据资料[1][2]说明。") == "依据资料说明。"
    assert _strip_citation_markers("无角标") == "无角标"


def test_create_agno_model_omits_temperature_by_default():
    llm = QaLlmConfig(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="moonshot-test",
    )
    model = _create_agno_model(llm)
    assert model.temperature is None
    assert model.extra_body is None


def test_create_agno_model_sets_enable_thinking_when_requested():
    llm = QaLlmConfig(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="qwen-test",
    )
    model = _create_agno_model(llm, enable_thinking=True)
    assert model.extra_body == {"enable_thinking": True}
