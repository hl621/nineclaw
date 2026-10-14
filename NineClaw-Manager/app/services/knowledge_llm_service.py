"""Resolve LLM provider and stream RAG answers via OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.provider import Provider
from app.services.knowledge_time_context import current_time_context

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = """你是一个知识库问答助手。请严格根据提供的参考资料回答用户问题。
- 优先使用参考资料中的事实，不要编造资料中不存在的内容。
- 若资料不足以回答，请明确说明知识库中未找到相关信息。
- 回答使用中文，条理清晰、简洁准确。
- 引用采用段落级合并标记：同一段落末尾集中写 [1] 或 [1][2]，编号与参考资料中的 [n] 一致；不要每个句子都插角标。
- 引用编号必须且只能来自本轮参考资料的 [1]…[N]；不要使用文档切片序号或历史对话中的编号。
- 最终回答末尾可加「资料来源」小节，用文件名列出用到的来源；不要生成 Markdown 链接，也不要暴露原始分数或内部诊断。
- 涉及「当前、今天、最近、今年」等相对时间时，以用户消息中的当前系统时间为准；不要把文章时间、上传时间、解析时间或切片时间当作当前时间。"""


@dataclass(frozen=True)
class QaLlmConfig:
    base_url: str
    api_key: str
    model: str
    provider_name: str = ""


class QaLlmError(Exception):
    pass


def _chat_completions_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    return f"{base}/chat/completions"


def build_rag_messages(
    question: str,
    references: list[dict[str, Any]],
) -> list[dict[str, str]]:
    if references:
        blocks: list[str] = []
        for i, ref in enumerate(references, 1):
            fname = ref.get("file_name") or "未知文件"
            text = str(ref.get("text") or "").strip()
            blocks.append(f"[{i}] 来源：{fname}\n{text}")
        context = "\n\n".join(blocks)
    else:
        context = "（未检索到与问题高度相关的文档片段）"

    user_content = (
        "当前系统时间（按小时截断，用于解释相对时间，不代表文档时间）："
        f"{current_time_context()}\n\n"
        f"参考资料：\n{context}\n\n用户问题：{question}"
    )
    return [
        {"role": "system", "content": RAG_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


async def resolve_qa_llm(
    session: AsyncSession,
    tenant_id: str,
    provider_id: str | None,
    model: str | None,
) -> QaLlmConfig:
    """Pick LLM from an explicit provider_id."""
    if provider_id:
        try:
            pid = UUID(provider_id)
        except ValueError as exc:
            raise QaLlmError("无效的 provider_id") from exc
        result = await session.execute(
            select(Provider).where(Provider.id == pid, Provider.tenant_id == tenant_id)
        )
        provider = result.scalar_one_or_none()
        if not provider:
            raise QaLlmError("Provider 不存在")
        if not provider.api_key:
            raise QaLlmError(f"Provider「{provider.name}」未配置 API Key")
        picked_model = model or (provider.models[0] if provider.models else None)
        if not picked_model:
            raise QaLlmError(
                f"Provider「{provider.name}」未配置模型，请在模型管理中添加"
            )
        return QaLlmConfig(
            base_url=provider.base_url,
            api_key=provider.api_key,
            model=picked_model,
            provider_name=provider.name,
        )

    raise QaLlmError("未传入 provider_id")


async def resolve_qa_llm_with_db_fallback(
    session: AsyncSession,
    tenant_id: str,
    provider_id: str | None,
    model: str | None,
) -> QaLlmConfig:
    """Explicit provider first; then first enabled provider in DB."""
    if provider_id:
        return await resolve_qa_llm(session, tenant_id, provider_id, model)

    result = await session.execute(
        select(Provider)
        .where(Provider.tenant_id == tenant_id, Provider.enabled.is_(True))
        .order_by(Provider.created_at.asc())
    )
    for provider in result.scalars():
        if not provider.api_key:
            continue
        picked_model = model or (provider.models[0] if provider.models else None)
        if not picked_model:
            continue
        return QaLlmConfig(
            base_url=provider.base_url,
            api_key=provider.api_key,
            model=picked_model,
            provider_name=provider.name,
        )

    raise QaLlmError(
        "未配置可用的大模型：请在「模型管理」中添加 Provider 并填写 API Key"
    )


async def stream_llm_answer(
    llm: QaLlmConfig,
    question: str,
    references: list[dict[str, Any]],
    temperature: float | None = None,
    enable_thinking: bool | None = None,
) -> Any:
    """Async generator yielding text deltas from upstream chat/completions SSE."""
    url = _chat_completions_url(llm.base_url)
    messages = build_rag_messages(question, references)
    headers = {
        "Authorization": f"Bearer {llm.api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    payload = {
        "model": llm.model,
        "messages": messages,
        "stream": True,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if enable_thinking is not None:
        payload["enable_thinking"] = enable_thinking

    timeout = httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            async with client.stream(
                "POST", url, headers=headers, json=payload
            ) as resp:
                if resp.is_error:
                    body = await resp.aread()
                    text = body.decode(errors="replace")[:500]
                    raise QaLlmError(f"大模型请求失败 HTTP {resp.status_code}: {text}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content
        except httpx.RequestError as exc:
            raise QaLlmError(f"无法连接大模型服务：{exc}") from exc
