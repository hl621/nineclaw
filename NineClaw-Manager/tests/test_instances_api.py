"""Tests for the Nineclaw Instance API endpoints.

Run with: pytest tests/test_instances_api.py -v
"""

import pytest


class TestHealthCheck:
    """Test health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Test health check endpoint."""
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestInstancesAPI:
    """Test cases for Instances API endpoints with real database."""

    @pytest.mark.asyncio
    async def test_list_instances_empty(self, client):
        """Test listing instances when empty."""
        # First clean up any existing instances
        response = await client.get("/api/nineclaw")
        assert response.status_code == 200
        data = response.json()
        # Clean up any existing instances
        for item in data.get("data", {}).get("items", []):
            await client.delete(f"/api/nineclaw/{item['id']}")
        
        # Now test empty list
        response = await client.get("/api/nineclaw")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["items"] == []
        assert data["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_create_and_list_instance(self, client):
        """Test creating and listing an instance."""
        # Create
        response = await client.post(
            "/api/nineclaw",
            json={"name": "test-instance"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["name"] == "test-instance"
        instance_id = data["data"]["id"]
        
        # List
        response = await client.get("/api/nineclaw")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["total"] >= 1
        
        # Cleanup
        await client.delete(f"/api/nineclaw/{instance_id}")

    @pytest.mark.asyncio
    async def test_get_instance(self, client):
        """Test getting a specific instance."""
        # Create first
        response = await client.post(
            "/api/nineclaw",
            json={"name": "test-get-instance"}
        )
        assert response.status_code == 201
        instance_id = response.json()["data"]["id"]
        
        # Get
        response = await client.get(f"/api/nineclaw/{instance_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 0
        assert data["data"]["id"] == instance_id
        assert data["data"]["name"] == "test-get-instance"
        
        # Cleanup
        await client.delete(f"/api/nineclaw/{instance_id}")

    @pytest.mark.asyncio
    async def test_get_instance_not_found(self, client):
        """Test getting a non-existent instance."""
        response = await client.get("/api/nineclaw/nonexistent-id-12345")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_stop_and_start_instance(self, client):
        """Test stopping and starting an instance."""
        # Create
        response = await client.post(
            "/api/nineclaw",
            json={"name": "test-stop-start"}
        )
        assert response.status_code == 201
        instance_id = response.json()["data"]["id"]
        
        # Stop
        response = await client.post(f"/api/nineclaw/{instance_id}/stop")
        assert response.status_code == 200
        assert response.json()["data"]["actual_state"] == "exited"
        
        # Start
        response = await client.post(f"/api/nineclaw/{instance_id}/start")
        assert response.status_code == 200
        assert response.json()["data"]["actual_state"] == "running"
        
        # Cleanup
        await client.delete(f"/api/nineclaw/{instance_id}")

    @pytest.mark.asyncio
    async def test_restart_instance(self, client):
        """Test restarting an instance."""
        # Create
        response = await client.post(
            "/api/nineclaw",
            json={"name": "test-restart"}
        )
        assert response.status_code == 201
        instance_id = response.json()["data"]["id"]
        
        # Restart
        response = await client.post(f"/api/nineclaw/{instance_id}/restart")
        assert response.status_code == 200
        assert response.json()["data"]["actual_state"] == "running"
        
        # Cleanup
        await client.delete(f"/api/nineclaw/{instance_id}")

    @pytest.mark.asyncio
    async def test_delete_instance(self, client):
        """Test deleting an instance."""
        # Create
        response = await client.post(
            "/api/nineclaw",
            json={"name": "test-delete"}
        )
        assert response.status_code == 201
        instance_id = response.json()["data"]["id"]
        
        # Delete
        response = await client.delete(f"/api/nineclaw/{instance_id}")
        assert response.status_code == 200
        assert response.json()["data"]["deleted"] == instance_id
        
        # Verify deleted
        response = await client.get(f"/api/nineclaw/{instance_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_instance_not_found(self, client):
        """Test deleting a non-existent instance."""
        response = await client.delete("/api/nineclaw/nonexistent-id-12345")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_instances_batch(self, client):
        """Test batch delete instances."""
        # Create two instances
        ids = []
        for i in range(2):
            response = await client.post(
                "/api/nineclaw",
                json={"name": f"test-batch-{i}"}
            )
            assert response.status_code == 201
            ids.append(response.json()["data"]["id"])
        
        # Batch delete using request method
        response = await client.request(
            "DELETE",
            "/api/nineclaw",
            json={"ids": ids}
        )
        assert response.status_code == 200
        assert response.json()["code"] == 0
        assert len(response.json()["data"]["deleted"]) == 2

    @pytest.mark.asyncio
    async def test_create_instance_with_env(self, client):
        """Test creating an instance with custom environment."""
        response = await client.post(
            "/api/nineclaw",
            json={
                "name": "test-with-env",
                "environment": {"CUSTOM_VAR": "custom_value"}
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert "CUSTOM_VAR" in data["data"]["config"]["environment"]
        
        # Cleanup
        await client.delete(f"/api/nineclaw/{data['data']['id']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
