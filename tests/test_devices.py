"""Tests for device discovery endpoints."""

import pytest


@pytest.mark.asyncio
async def test_list_sibling_devices(auth_client):
    """Test listing sibling devices."""
    response = await auth_client.get("/api/device-discovery")

    assert response.status_code == 200
    data = response.json()
    assert "devices" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_get_current_device_via_discovery(auth_client):
    """Test getting current device info via /devices/me."""
    response = await auth_client.get("/api/device-discovery/me")

    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_device_discovery_requires_auth(client):
    """Test that /api/device-discovery requires authentication."""
    response = await client.get("/api/device-discovery")
    assert response.status_code in (401, 403)
