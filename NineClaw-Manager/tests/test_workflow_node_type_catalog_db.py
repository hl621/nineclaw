"""PostgreSQL checks for the migrated workflow node-type catalog.

Set ``WORKFLOW_TEST_DATABASE_URL`` to a disposable PostgreSQL database migrated
through revision 025.  Each test uses a rolled-back outer transaction.
"""

from __future__ import annotations

import os

from jsonschema import Draft202012Validator
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.workflow import WorkflowNodeTypeDefinition
from app.services.workflow.node_types import (
    list_node_type_definitions,
    node_type_ids,
)


WORKFLOW_TEST_DATABASE_URL = os.getenv("WORKFLOW_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not WORKFLOW_TEST_DATABASE_URL,
    reason="需要 WORKFLOW_TEST_DATABASE_URL 指向已迁移的 PostgreSQL",
)


@pytest_asyncio.fixture
async def node_type_catalog_sessions():
    engine: AsyncEngine = create_async_engine(WORKFLOW_TEST_DATABASE_URL)
    connection: AsyncConnection = await engine.connect()
    outer_transaction = await connection.begin()
    sessions = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield sessions
    finally:
        await outer_transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_migrated_node_type_catalog_has_complete_seed_rows(
    node_type_catalog_sessions,
):
    async with node_type_catalog_sessions() as session:
        rows = list(
            (
                await session.scalars(
                    select(WorkflowNodeTypeDefinition).order_by(
                        WorkflowNodeTypeDefinition.display_order,
                        WorkflowNodeTypeDefinition.type,
                    )
                )
            ).all()
        )
        items = await list_node_type_definitions(session)

    assert [row.type for row in rows] == [
        "start",
        "end",
        "hermes_agent",
        "condition",
        "loop",
    ]
    assert [row.display_order for row in rows] == list(range(5))
    assert [item["type"] for item in items] == [row.type for row in rows]
    assert {item["type"] for item in items} == node_type_ids()
    for item in items:
        assert {
            "type",
            "name",
            "description",
            "category",
            "type_version",
            "executor_version",
            "input_ports",
            "output_ports",
            "config_schema",
            "default_config",
            "capabilities",
        } <= set(item)
        Draft202012Validator.check_schema(item["config_schema"])

    condition = next(item for item in items if item["type"] == "condition")
    assert condition["output_ports"][0]["source"] == "config.ports[]"
    loop = next(item for item in items if item["type"] == "loop")
    assert loop["executor_version"] == 3
    assert "true" in loop["description"]
    assert "终止" in loop["description"]
    assert loop["capabilities"] == {
        "container": True,
        "nested_loop": False,
        "artifact_workspace": True,
        "variables": True,
        "control_decision": True,
    }
