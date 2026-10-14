"""FastAPI application entry point for NineClaw WebSearch."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter

from app.api.routes import authoring, explore, search, sources
from app.core.config import settings

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting NineClaw WebSearch")
    yield
    logger.info("Shutting down NineClaw WebSearch")


app = FastAPI(
    title="NineClaw WebSearch",
    description="Configurable search & extract service",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
api_v1 = APIRouter(prefix="/v1")
api_v1.include_router(sources.router)
api_v1.include_router(search.router)
api_v1.include_router(authoring.router)
api_v1.include_router(explore.router)
app.include_router(api_v1)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
