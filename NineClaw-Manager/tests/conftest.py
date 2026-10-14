"""Pytest configuration and fixtures."""

import pytest
import pytest_asyncio
import asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
import uuid
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app
from app.services.docker_service import DockerService


# Configure pytest-asyncio
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def mock_docker_service():
    """Mock DockerService for testing."""
    mock = MagicMock(spec=DockerService)
    mock.create_nineclaw = AsyncMock(return_value="abc123containerid")
    mock.start_container = AsyncMock()
    mock.stop_container = AsyncMock()
    mock.restart_container = AsyncMock()
    mock.remove_container = AsyncMock()
    mock.get_container_status = AsyncMock(return_value="running")
    mock.list_containers = AsyncMock(return_value=[])
    return mock


@pytest_asyncio.fixture(scope="session")
async def client(mock_docker_service):
    """Create an async test client with mocked docker service."""
    app.state.docker_service = mock_docker_service
    
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def sample_instance():
    """Create a sample instance for testing."""
    from app.models.instance import ServiceInstance
    
    return ServiceInstance(
        id="test-instance-id",
        tenant_id="default",
        template_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        name="test-nineclaw",
        desired_state="running",
        actual_state="running",
        container_id="abc123containerid",
        config={"image": "nineclaw:latest"},
        port_mappings={"api": {"host_port": 8500, "container_port": 8642}},
        network_name="qiyuan_net",
        health_status="healthy",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
