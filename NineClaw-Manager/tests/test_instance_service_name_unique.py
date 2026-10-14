"""Unit tests for InstanceService name-uniqueness checks.

These mock the DB session so they run without a live Postgres. They
verify the pre-persistence duplicate-name guard added for the
tenant-scoped unique constraint on service_instances.name.
"""

import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.models.instance import ServiceInstance
from app.services.instance_service import (
    InstanceConflictError,
    InstanceNotFoundError,
    InstanceService,
)


_DEFAULT_TEMPLATE_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _make_existing(name: str = "dup", iid: str = "existing-id") -> ServiceInstance:
    return ServiceInstance(
        id=iid,
        tenant_id="default",
        template_id=_DEFAULT_TEMPLATE_ID,
        name=name,
    )


def _mock_session(scalars_per_call):
    """Return an AsyncMock session whose execute() returns results with
    ``scalar_one_or_none`` resolving to successive items of *scalars_per_call*.
    """
    session = MagicMock()
    results = []
    for value in scalars_per_call:
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=value)
        results.append(result)
    session.execute = AsyncMock(side_effect=results)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _mock_docker():
    docker = MagicMock()
    docker.create_nineclaw = AsyncMock(return_value="container-id")
    docker.start_container = AsyncMock()
    docker.get_container_status = AsyncMock(return_value="running")
    return docker


@pytest.mark.asyncio
async def test_create_instance_rejects_duplicate_name():
    session = _mock_session([_make_existing("dup")])
    svc = InstanceService(session=session, docker_service=_mock_docker())

    with pytest.raises(InstanceConflictError) as exc:
        await svc.create_instance(name="dup", image="nineclaw:v2026.7.7.2", tenant_id="default")
    assert "dup" in str(exc.value)
    # Must bail out before touching docker.
    svc._docker.create_nineclaw.assert_not_called()


@pytest.mark.asyncio
async def test_create_instance_proceeds_past_guard_when_name_free():
    # When no existing row matches, the guard must NOT raise
    # InstanceConflictError and must hand off to docker create.
    session = MagicMock()
    guard_result = MagicMock()
    guard_result.scalar_one_or_none = MagicMock(return_value=None)
    port_result = MagicMock()
    port_result.__iter__ = MagicMock(return_value=iter([]))  # no used ports
    session.execute = AsyncMock(side_effect=[guard_result, port_result])
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    docker = _mock_docker()
    svc = InstanceService(session=session, docker_service=docker)
    try:
        await svc.create_instance(name="fresh", image="nineclaw:v2026.7.7.2", tenant_id="default")
    except InstanceConflictError:
        pytest.fail("name guard fired on a free name")
    except Exception:
        pass  # downstream (bootstrap/etc.) failures are out of scope
    docker.create_nineclaw.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_instance_rejects_rename_conflict():
    current = _make_existing("old-name", iid="inst-1")
    # 1st execute: _get_or_raise → current; 2nd execute: clash → other row.
    session = _mock_session([current, _make_existing("taken", iid="inst-2")])
    svc = InstanceService(session=session, docker_service=_mock_docker())

    with pytest.raises(InstanceConflictError):
        await svc.update_instance("inst-1", name="taken")


@pytest.mark.asyncio
async def test_update_instance_allows_rename_to_free_name():
    current = _make_existing("old-name", iid="inst-1")
    session = _mock_session([current, None])
    svc = InstanceService(session=session, docker_service=_mock_docker())
    updated = await svc.update_instance("inst-1", name="new-name")
    assert updated.name == "new-name"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_instance_same_name_is_noop():
    # Renaming to the same name should not run a clash query nor error.
    current = _make_existing("same", iid="inst-1")
    session = _mock_session([current])  # only _get_or_raise is called
    svc = InstanceService(session=session, docker_service=_mock_docker())
    updated = await svc.update_instance("inst-1", name="same")
    assert updated.name == "same"
    assert session.execute.await_count == 1  # no clash query
