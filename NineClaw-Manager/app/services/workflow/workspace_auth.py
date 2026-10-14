"""Authentication helpers for a Runtime-local workflow workspace bridge."""

from __future__ import annotations

import hashlib
import hmac

from app.core.config import settings


class WorkspaceBridgeConfigurationError(RuntimeError):
    pass


def bridge_token_for_instance(instance_id: str) -> str:
    """Derive a scoped bridge token without persisting a plaintext secret."""
    secret = settings.workflow_workspace_bridge_secret.encode("utf-8")
    if not secret:
        raise WorkspaceBridgeConfigurationError("未配置工作流 Bridge 密钥")
    return hmac.new(secret, instance_id.encode("utf-8"), hashlib.sha256).hexdigest()


def bridge_token_is_valid(*, instance_id: str, token: str) -> bool:
    if not token or not settings.workflow_workspace_bridge_secret:
        return False
    expected = bridge_token_for_instance(instance_id)
    return hmac.compare_digest(expected, token)


def workspace_token_for_execution(*, execution_id: str, instance_id: str) -> str:
    """Derive an opaque capability for exactly one active workflow Attempt.

    The Runtime Bridge has a long-lived, instance-scoped credential.  This
    second token prevents one Hermes run on that instance from reusing a
    leaked execution ID to operate on another concurrent Attempt.
    """

    secret = settings.workflow_workspace_bridge_secret.encode("utf-8")
    if not secret:
        raise WorkspaceBridgeConfigurationError("未配置工作流 Bridge 密钥")
    if not execution_id or not instance_id:
        raise WorkspaceBridgeConfigurationError("工作区执行身份无效")
    payload = f"workflow-workspace-attempt:v1\0{instance_id}\0{execution_id}"
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def workspace_token_is_valid(
    *, execution_id: str, instance_id: str, token: str | None
) -> bool:
    if (
        not token
        or not execution_id
        or not instance_id
        or not settings.workflow_workspace_bridge_secret
    ):
        return False
    expected = workspace_token_for_execution(
        execution_id=execution_id, instance_id=instance_id
    )
    return hmac.compare_digest(expected, token)
