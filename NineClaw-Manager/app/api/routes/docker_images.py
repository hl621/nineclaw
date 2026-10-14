"""Docker image listing endpoints for NineClaw create-instance UI."""

from __future__ import annotations

import logging
from typing import Any

from aiodocker.exceptions import DockerError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.services.docker_service import DockerService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/docker", tags=["docker"])


class ApiResponse(BaseModel):
    code: int = Field(default=0)
    message: str = Field(default="success")
    data: Any = Field(default=None)


def get_docker_service(request: Request) -> DockerService:
    return request.app.state.docker_service


@router.get(
    "/nineclaw-images",
    response_model=ApiResponse,
    summary="List local NineClaw image versions",
)
async def list_nineclaw_images(
    docker_service: DockerService = Depends(get_docker_service),
) -> ApiResponse:
    """Return local Docker tags for the configured NineClaw repository.

    Kept outside ``/container/nineclaw/{instance_id}`` so ``images`` is never
    parsed as an instance id.
    """
    try:
        items = await docker_service.list_nineclaw_images()
    except DockerError as exc:
        logger.exception("Docker error while listing nineclaw images")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Docker operation failed: {exc.message}",
        ) from exc
    except Exception as exc:
        logger.exception("Failed to list nineclaw images")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list nineclaw images: {exc}",
        ) from exc
    return ApiResponse(data={"items": items, "total": len(items)})
