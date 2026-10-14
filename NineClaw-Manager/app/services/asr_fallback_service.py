"""Local DashScope / provider ASR fallback when RAGFlow transcription fails."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider import Provider

logger = logging.getLogger(__name__)

_DASHSCOPE_ASR_MAX_BYTES = 7 * 1024 * 1024
_DEFAULT_QWEN_ASR = "qwen3-asr-flash"


def _is_dashscope_base(base_url: str) -> bool:
    lower = (base_url or "").lower()
    return "dashscope.aliyuncs.com" in lower or "dashscope-intl.aliyuncs.com" in lower


def _is_qwen_asr_model(model: str) -> bool:
    name = (model or "").lower()
    return ("qwen" in name and "asr" in name) or "qwen-audio" in name


def _asr_audio_mime(filename: str, content_type: str | None) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".wav"):
        return "audio/wav"
    if lower.endswith(".mp3"):
        return "audio/mpeg"
    if lower.endswith(".m4a"):
        return "audio/mp4"
    if lower.endswith(".webm"):
        return "audio/webm"
    if lower.endswith(".ogg"):
        return "audio/ogg"
    if lower.endswith(".flac"):
        return "audio/flac"
    if lower.endswith(".aac"):
        return "audio/aac"
    if content_type and content_type.startswith("audio/"):
        return content_type
    return "application/octet-stream"


def _pick_asr_model(provider: Provider) -> str | None:
    models = list(provider.models or [])
    for m in models:
        if _is_qwen_asr_model(m) or "asr" in m.lower() or "whisper" in m.lower():
            return m
    if _is_dashscope_base(provider.base_url):
        # 与 RAGFlow 默认 ASR 对齐；即使未写入 models 列表也可试
        return _DEFAULT_QWEN_ASR
    return None


async def find_dashscope_asr_provider(
    session: AsyncSession,
    tenant_id: str,
) -> tuple[Provider, str] | None:
    stmt = (
        select(Provider)
        .where(Provider.tenant_id == tenant_id, Provider.enabled.is_(True))
        .order_by(Provider.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    for provider in rows:
        if not _is_dashscope_base(provider.base_url):
            continue
        if not (provider.api_key or "").strip():
            continue
        model = _pick_asr_model(provider)
        if model:
            return provider, model
    return None


async def transcribe_via_dashscope_provider(
    *,
    base_url: str,
    api_key: str,
    model: str,
    audio_bytes: bytes,
    filename: str,
    content_type: str | None = None,
) -> str:
    if len(audio_bytes) > _DASHSCOPE_ASR_MAX_BYTES:
        raise ValueError(
            "百炼 Qwen-ASR 单段过大（建议 ≤7MB）。请缩短录音或由前端切段后再试。"
        )
    base = base_url.rstrip("/")
    upstream_url = (
        f"{base}/chat/completions"
        if base.lower().endswith("/v1")
        else f"{base}/v1/chat/completions"
    )
    mime = _asr_audio_mime(filename, content_type)
    data_uri = f"data:{mime};base64,{base64.b64encode(audio_bytes).decode('ascii')}"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "nineclaw-manager/0.1",
    }
    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_uri},
                    }
                ],
            }
        ],
        "asr_options": {"enable_itn": False},
    }
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(180.0),
        follow_redirects=True,
        trust_env=False,
    ) as client:
        res = await client.post(upstream_url, headers=headers, json=payload)
    if res.status_code >= 400:
        raise ValueError(f"百炼 ASR HTTP {res.status_code}: {res.text[:400]}")
    try:
        body = res.json()
    except Exception as exc:
        raise ValueError(f"百炼 ASR 返回非 JSON: {res.text[:200]}") from exc
    # OpenAI-compatible
    choices = body.get("choices") if isinstance(body, dict) else None
    if isinstance(choices, list) and choices:
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                texts: list[str] = []
                for part in content:
                    if isinstance(part, dict):
                        t = part.get("text") or part.get("content")
                        if t:
                            texts.append(str(t))
                    elif isinstance(part, str):
                        texts.append(part)
                joined = "".join(texts).strip()
                if joined:
                    return joined
    # DashScope native-ish
    if isinstance(body, dict):
        output = body.get("output")
        if isinstance(output, dict):
            text = output.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    raise ValueError("百炼 ASR 未返回有效转写文本")


async def try_provider_asr_fallback(
    session: AsyncSession,
    tenant_id: str,
    *,
    audio_bytes: bytes,
    filename: str,
) -> tuple[str, str] | None:
    """Return (text, source_note) or None if no usable provider."""
    found = await find_dashscope_asr_provider(session, tenant_id)
    if found is None:
        return None
    provider, model = found
    text = await transcribe_via_dashscope_provider(
        base_url=provider.base_url,
        api_key=provider.api_key,
        model=model,
        audio_bytes=audio_bytes,
        filename=filename,
    )
    note = f"nineclaw-models/{provider.name}/{model}"
    logger.info(
        "ASR fallback ok tenant=%s provider=%s model=%s chars=%d",
        tenant_id,
        provider.name,
        model,
        len(text),
    )
    return text, note
