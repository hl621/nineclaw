"""Database session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    future=True,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    pool_timeout=60,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async DB session."""
    async with async_session_maker() as session:
        yield session


def _safe_database_url() -> str:
    """Return DATABASE_URL with credentials hidden for logs and API errors."""
    try:
        return make_url(settings.database_url).render_as_string(hide_password=True)
    except Exception:
        return "<DATABASE_URL 解析失败>"


def format_database_connection_error(exc: BaseException) -> str:
    """Build an operator-friendly database connection error message."""
    return (
        "无法连接数据库，请检查 .env 中的 DATABASE_URL 是否填写正确。\n"
        f"当前 DATABASE_URL: {_safe_database_url()}\n"
        f"原始错误: {type(exc).__name__}: {exc}"
    )


async def check_database_connection() -> None:
    """Fail fast with a clear message when DATABASE_URL is wrong or DB is down."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError(format_database_connection_error(exc)) from exc
