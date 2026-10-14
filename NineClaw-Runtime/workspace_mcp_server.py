"""Local stdio MCP bridge for Manager-owned workflow artifacts.

The bridge owns no object-storage credential. It receives an Attempt-scoped
execution ID and workspace token, then calls Manager with its instance-scoped
Bridge credential.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from mcp.server.fastmcp import FastMCP


class WorkspaceBridgeError(RuntimeError):
    pass


@dataclass
class WorkspaceBridge:
    manager_url: str
    instance_id: str
    token: str
    local_root: Path
    client: httpx.Client

    @classmethod
    def from_environment(cls) -> "WorkspaceBridge":
        manager_url = os.environ.get("NINECLAW_MANAGER_URL", "").rstrip("/")
        instance_id = os.environ.get("NINECLAW_WORKSPACE_INSTANCE_ID", "").strip()
        token = os.environ.get("NINECLAW_WORKSPACE_BRIDGE_TOKEN", "").strip()
        if not manager_url or not instance_id or not token:
            raise WorkspaceBridgeError("工作区 Bridge 缺少 Manager 连接配置")
        root = Path(
            os.environ.get("NINECLAW_WORKSPACE_DIR", "/tmp/nineclaw-workspace")
        ).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return cls(
            manager_url=manager_url,
            instance_id=instance_id,
            token=token,
            local_root=root,
            client=httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0)),
        )

    def _headers(self, workspace_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Nineclaw-Workspace-Instance": self.instance_id,
            "X-Nineclaw-Workspace-Token": _valid_workspace_token(workspace_token),
        }

    def download(
        self,
        *,
        execution_id: str,
        workspace_token: str,
        artifact_id: str,
        destination_path: str,
    ) -> dict[str, str | int]:
        artifact = _valid_uuid(artifact_id, "artifact_id")
        destination = self._local_path(execution_id, destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.downloading")
        try:
            with self.client.stream(
                "GET",
                self._url(f"/artifacts/{artifact}"),
                params={"execution_id": execution_id},
                headers=self._headers(workspace_token),
            ) as response:
                _ensure_success(response)
                size_bytes = 0
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes(64 * 1024):
                        size_bytes += len(chunk)
                        handle.write(chunk)
            temporary.replace(destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return {"path": str(destination), "size_bytes": size_bytes}

    def list_artifacts(
        self, *, execution_id: str, workspace_token: str
    ) -> dict[str, Any]:
        response = self.client.get(
            self._url("/artifacts"),
            params=self._execution_params(execution_id),
            headers=self._headers(workspace_token),
        )
        return _response_data(response)

    def upload(
        self,
        *,
        execution_id: str,
        workspace_token: str,
        source_path: str,
        name: str | None = None,
    ) -> dict[str, Any]:
        source = self._local_path(execution_id, source_path)
        if not source.is_file():
            raise WorkspaceBridgeError("上传源文件不存在")
        upload_name = Path(name or source.name).name or "artifact"
        artifact_id: str | None = None
        try:
            with source.open("rb") as handle:
                response = self.client.post(
                    self._url("/uploads"),
                    data={"execution_id": execution_id},
                    files={"file": (upload_name, handle, "application/octet-stream")},
                    headers=self._headers(workspace_token),
                )
            _ensure_success(response)
            body = response.json()
            artifact_id = str(body["data"]["artifact_id"])
            _valid_uuid(artifact_id, "artifact_id")
            committed = self.client.post(
                self._url(f"/uploads/{artifact_id}/commit"),
                params={"execution_id": execution_id},
                headers=self._headers(workspace_token),
            )
            _ensure_success(committed)
            return dict(committed.json()["data"])
        except BaseException:
            if artifact_id is not None:
                try:
                    self.client.delete(
                        self._url(f"/uploads/{artifact_id}"),
                        params={"execution_id": execution_id},
                        headers=self._headers(workspace_token),
                    )
                except httpx.HTTPError:
                    pass
            raise

    def list_variables(
        self, *, execution_id: str, workspace_token: str
    ) -> dict[str, Any]:
        response = self.client.get(
            self._url("/variables"),
            params=self._execution_params(execution_id),
            headers=self._headers(workspace_token),
        )
        return _response_data(response)

    def get_variable(
        self, *, execution_id: str, workspace_token: str, variable_name: str
    ) -> dict[str, Any]:
        response = self.client.get(
            self._url(self._variable_path(variable_name)),
            params=self._execution_params(execution_id),
            headers=self._headers(workspace_token),
        )
        return _response_data(response)

    def set_variable(
        self,
        *,
        execution_id: str,
        workspace_token: str,
        variable_name: str,
        value: Any,
    ) -> dict[str, Any]:
        response = self.client.put(
            self._url(self._variable_path(variable_name)),
            params=self._execution_params(execution_id),
            json={"value": value},
            headers=self._headers(workspace_token),
        )
        return _response_data(response)

    def set_many_variables(
        self, *, execution_id: str, workspace_token: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(values, dict):
            raise WorkspaceBridgeError("values 必须是对象")
        response = self.client.post(
            self._url("/variables/set-many"),
            params=self._execution_params(execution_id),
            json={"values": values},
            headers=self._headers(workspace_token),
        )
        return _response_data(response)

    def condition_select_port(
        self,
        *,
        execution_id: str,
        workspace_token: str,
        token: str,
        port: str,
    ) -> dict[str, Any]:
        response = self.client.post(
            self._url("/condition-selections"),
            json={
                "execution_id": _valid_execution_id(execution_id),
                "token": token,
                "port": port,
            },
            headers=self._headers(workspace_token),
        )
        return _response_data(response)

    def loop_continue(
        self,
        *,
        execution_id: str,
        workspace_token: str,
        token: str,
        should_continue: bool,
    ) -> dict[str, Any]:
        if not isinstance(should_continue, bool):
            raise WorkspaceBridgeError("should_continue 必须是布尔值")
        response = self.client.post(
            self._url("/loop-decisions"),
            json={
                "execution_id": _valid_execution_id(execution_id),
                "token": token,
                "should_continue": should_continue,
            },
            headers=self._headers(workspace_token),
        )
        return _response_data(response)

    def _url(self, path: str) -> str:
        return f"{self.manager_url}/v1/workflow-workspace{path}"

    def _execution_params(self, execution_id: str) -> dict[str, str]:
        return {"execution_id": _valid_execution_id(execution_id)}

    @staticmethod
    def _variable_path(variable_name: str) -> str:
        if not isinstance(variable_name, str) or not variable_name.strip():
            raise WorkspaceBridgeError("variable_name 无效")
        return f"/variables/{quote(variable_name, safe='')}"

    def close(self) -> None:
        self.client.close()

    def _local_path(self, execution_id: str, raw_path: str) -> Path:
        _valid_execution_id(execution_id)
        execution_root = (self.local_root / execution_id).resolve()
        candidate = (execution_root / raw_path).resolve()
        if candidate == execution_root or execution_root not in candidate.parents:
            raise WorkspaceBridgeError("工作区文件路径必须位于本地工作目录")
        return candidate


def _valid_uuid(value: str, field: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise WorkspaceBridgeError(f"{field} 无效") from exc


def _valid_execution_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", value):
        raise WorkspaceBridgeError("execution_id 无效")
    return value


def _valid_workspace_token(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise WorkspaceBridgeError("workspace_token 无效")
    return value


def _ensure_success(response: httpx.Response) -> None:
    if response.is_error:
        message = f"Manager 工作区请求失败：HTTP {response.status_code}"
        detail = _error_detail(response)
        if detail:
            message = f"{message}，{detail}"
        raise WorkspaceBridgeError(message)


def _error_detail(response: httpx.Response) -> str:
    """Best-effort Manager 错误详情（FastAPI {"detail": ...}），失败时返回空串。"""
    try:
        response.read()
    except httpx.HTTPError:
        return ""
    try:
        data = response.json()
    except ValueError:
        return response.text.strip()[:300]
    if not isinstance(data, dict):
        return ""
    detail = data.get("detail")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()[:300]
    if detail is not None:
        try:
            return json.dumps(detail, ensure_ascii=False)[:300]
        except (TypeError, ValueError):
            return ""
    return ""


def _response_data(response: httpx.Response) -> dict[str, Any]:
    _ensure_success(response)
    try:
        data = response.json()["data"]
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkspaceBridgeError("Manager 工作区响应格式无效") from exc
    if not isinstance(data, dict):
        raise WorkspaceBridgeError("Manager 工作区响应格式无效")
    return dict(data)


mcp = FastMCP("workflow_workspace")


@mcp.tool()
def workspace_download(
    execution_id: str,
    workspace_token: str,
    artifact_id: str,
    destination_path: str,
) -> dict[str, str | int]:
    """将当前节点已授权的输入 Artifact 下载到本地工作目录。"""
    bridge = WorkspaceBridge.from_environment()
    try:
        return bridge.download(
            execution_id=execution_id,
            workspace_token=workspace_token,
            artifact_id=artifact_id,
            destination_path=destination_path,
        )
    finally:
        bridge.close()


@mcp.tool()
def workspace_upload(
    execution_id: str,
    workspace_token: str,
    source_path: str,
    name: str | None = None,
) -> dict[str, Any]:
    """上传本地工作目录文件，并原子提交为当前节点的输出 Artifact。"""
    bridge = WorkspaceBridge.from_environment()
    try:
        return bridge.upload(
            execution_id=execution_id,
            workspace_token=workspace_token,
            source_path=source_path,
            name=name,
        )
    finally:
        bridge.close()


@mcp.tool()
def workspace_list(execution_id: str, workspace_token: str) -> dict[str, Any]:
    """列出当前节点已授权的上游 Artifact 元数据。"""
    bridge = WorkspaceBridge.from_environment()
    try:
        return bridge.list_artifacts(
            execution_id=execution_id, workspace_token=workspace_token
        )
    finally:
        bridge.close()


@mcp.tool()
def variables_list(execution_id: str, workspace_token: str) -> dict[str, Any]:
    """列出当前节点可见的工作流变量及其值。"""
    bridge = WorkspaceBridge.from_environment()
    try:
        return bridge.list_variables(
            execution_id=execution_id, workspace_token=workspace_token
        )
    finally:
        bridge.close()


@mcp.tool()
def variables_get(
    execution_id: str, workspace_token: str, variable_name: str
) -> dict[str, Any]:
    """读取当前节点可见的一个工作流变量。"""
    bridge = WorkspaceBridge.from_environment()
    try:
        return bridge.get_variable(
            execution_id=execution_id,
            workspace_token=workspace_token,
            variable_name=variable_name,
        )
    finally:
        bridge.close()


@mcp.tool()
def variables_set(
    execution_id: str, workspace_token: str, variable_name: str, value: Any
) -> dict[str, Any]:
    """暂存一个工作流变量值；节点成功后才对下游生效。"""
    bridge = WorkspaceBridge.from_environment()
    try:
        return bridge.set_variable(
            execution_id=execution_id,
            workspace_token=workspace_token,
            variable_name=variable_name,
            value=value,
        )
    finally:
        bridge.close()


@mcp.tool()
def variables_set_many(
    execution_id: str, workspace_token: str, values: dict[str, Any]
) -> dict[str, Any]:
    """原子暂存多个工作流变量值；节点成功后才对下游生效。"""
    bridge = WorkspaceBridge.from_environment()
    try:
        return bridge.set_many_variables(
            execution_id=execution_id,
            workspace_token=workspace_token,
            values=values,
        )
    finally:
        bridge.close()


@mcp.tool()
def condition_select_port(
    execution_id: str, workspace_token: str, token: str, port: str
) -> dict[str, Any]:
    """用一次性控制令牌提交 Agent Condition 的目标端口。"""
    bridge = WorkspaceBridge.from_environment()
    try:
        return bridge.condition_select_port(
            execution_id=execution_id,
            workspace_token=workspace_token,
            token=token,
            port=port,
        )
    finally:
        bridge.close()


@mcp.tool()
def loop_continue(
    execution_id: str, workspace_token: str, token: str, should_continue: bool
) -> dict[str, Any]:
    """用一次性控制令牌提交 Agent Loop 的继续或终止决定。"""
    bridge = WorkspaceBridge.from_environment()
    try:
        return bridge.loop_continue(
            execution_id=execution_id,
            workspace_token=workspace_token,
            token=token,
            should_continue=should_continue,
        )
    finally:
        bridge.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
