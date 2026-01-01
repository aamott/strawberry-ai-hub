"""Tests for authentication."""

import pytest


@pytest.mark.asyncio
async def test_register_device(client):
    """Test device registration."""
    response = await client.post(
        "/auth/register",
        json={"name": "Test Device", "user_id": "user123"},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "device_id" in data
    assert "access_token" in data
    assert data["message"] == "Device 'Test Device' registered successfully"


@pytest.mark.asyncio
async def test_get_current_device(auth_client):
    """Test getting current device info."""
    response = await auth_client.get("/auth/me")
    
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test Device"
    assert data["user_id"] == "test_user"


@pytest.mark.asyncio
async def test_unauthorized_access(client):
    """Test that endpoints require authentication."""
    response = await client.get("/auth/me")
    
    # Should fail without auth (401 or 403)
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_refresh_token(auth_client):
    """Test token refresh."""
    response = await auth_client.post("/auth/refresh")
    
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
