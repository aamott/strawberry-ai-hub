"""Tests for POST /api/devices/register endpoint.

Covers:
- First-time registration (no device_id) -> Hub assigns UUID
- Reconnect with known device_id -> same ID returned
- Reconnect with unknown device_id -> new device created
- Display name collision -> auto-suffix applied
- Multiple registrations under same token -> different device_ids
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_new_device(auth_client: AsyncClient):
    """First registration without device_id gets a Hub-assigned UUID."""
    response = await auth_client.post(
        "/api/devices/register",
        json={"device_name": "Kitchen PC"},
    )
    assert response.status_code == 200
    data = response.json()

    assert "device_id" in data
    assert "display_name" in data
    assert len(data["device_id"]) == 36  # UUID format
    assert data["display_name"] == "Kitchen PC"


@pytest.mark.asyncio
async def test_reconnect_with_known_device_id(auth_client: AsyncClient):
    """Reconnecting with a known device_id returns the same ID."""
    # First registration
    r1 = await auth_client.post(
        "/api/devices/register",
        json={"device_name": "Living Room"},
    )
    assert r1.status_code == 200
    device_id = r1.json()["device_id"]

    # Reconnect with the same device_id
    r2 = await auth_client.post(
        "/api/devices/register",
        json={"device_name": "Living Room", "device_id": device_id},
    )
    assert r2.status_code == 200
    assert r2.json()["device_id"] == device_id
    assert r2.json()["display_name"] == "Living Room"


@pytest.mark.asyncio
async def test_reconnect_with_unknown_device_id(auth_client: AsyncClient):
    """Unknown device_id falls through to create a new device."""
    response = await auth_client.post(
        "/api/devices/register",
        json={
            "device_name": "Ghost Device",
            "device_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert response.status_code == 200
    data = response.json()

    # Should get a brand-new UUID, not the bogus one
    assert data["device_id"] != "00000000-0000-0000-0000-000000000000"
    assert data["display_name"] == "Ghost Device"


@pytest.mark.asyncio
async def test_display_name_collision_auto_suffix(auth_client: AsyncClient):
    """Second device with same display name gets auto-suffixed."""
    # Register first device
    r1 = await auth_client.post(
        "/api/devices/register",
        json={"device_name": "Office PC"},
    )
    assert r1.status_code == 200
    assert r1.json()["display_name"] == "Office PC"

    # Register second device with same name (no device_id -> new device)
    r2 = await auth_client.post(
        "/api/devices/register",
        json={"device_name": "Office PC"},
    )
    assert r2.status_code == 200
    assert r2.json()["display_name"] == "Office PC 2"
    assert r2.json()["device_id"] != r1.json()["device_id"]


@pytest.mark.asyncio
async def test_multiple_registrations_different_ids(auth_client: AsyncClient):
    """Multiple registrations under the same token get distinct device_ids."""
    ids = set()
    for i in range(3):
        response = await auth_client.post(
            "/api/devices/register",
            json={"device_name": f"Device {i}"},
        )
        assert response.status_code == 200
        ids.add(response.json()["device_id"])

    assert len(ids) == 3, "Each registration should produce a unique device_id"


@pytest.mark.asyncio
async def test_reconnect_updates_display_name(auth_client: AsyncClient):
    """Reconnecting with a new display name updates it."""
    r1 = await auth_client.post(
        "/api/devices/register",
        json={"device_name": "Old Name"},
    )
    device_id = r1.json()["device_id"]

    r2 = await auth_client.post(
        "/api/devices/register",
        json={"device_name": "New Name", "device_id": device_id},
    )
    assert r2.json()["device_id"] == device_id
    assert r2.json()["display_name"] == "New Name"


@pytest.mark.asyncio
async def test_unauthenticated_register_rejected(client: AsyncClient):
    """Registration without auth token is rejected."""
    response = await client.post(
        "/api/devices/register",
        json={"device_name": "No Auth"},
    )
    # HTTPBearer returns 401 for missing credentials, or 403
    assert response.status_code in (401, 403)
