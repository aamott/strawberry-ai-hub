from unittest.mock import patch

import pytest

from hub.database import get_session_factory


@pytest.fixture
async def db_session():
    factory = get_session_factory()
    async with factory() as session:
        yield session


@pytest.mark.asyncio
async def test_device_status_lifecycle(client, db_session):
    """
    Test device status lifecycle:
    1. Create device (should be inactive since not connected)
    2. Mock WS connection (should be active)
    3. Mock WS disconnection (should be inactive)
    4. Send heartbeat (should still be inactive without WS)
    """
    # 1. Setup User and Device
    response = await client.post(
        "/api/users/setup", json={"username": "testuser", "password": "password"}
    )
    if response.status_code == 400:
        await client.post(
            "/api/users/login", json={"username": "testuser", "password": "password"}
        )

    response = await client.post(
        "/api/users/login", json={"username": "testuser", "password": "password"}
    )
    assert response.status_code == 200
    user_token = response.json()["access_token"]
    user_auth_headers = {"Authorization": f"Bearer {user_token}"}

    response = await client.post(
        "/api/devices/token", json={"name": "Test Device"}, headers=user_auth_headers
    )
    assert response.status_code == 200
    device_data = response.json()
    device_id = device_data["device"]["id"]
    device_token = device_data["token"]
    device_auth_headers = {"Authorization": f"Bearer {device_token}"}

    # 2. Verify initial status (Inactive - no WS connection)
    response = await client.get("/api/devices", headers=user_auth_headers)
    assert response.status_code == 200
    devices = response.json()
    my_device = next(d for d in devices if d["id"] == device_id)
    assert my_device["is_active"] is False  # No WS connection

    # 3. Mock WS connection - patch the actual module where connection_manager lives
    with patch("hub.routers.devices.connection_manager") as mock_cm:
        mock_cm.is_connected.return_value = True

        response = await client.get("/api/devices", headers=user_auth_headers)
        assert response.status_code == 200
        devices = response.json()
        my_device = next(d for d in devices if d["id"] == device_id)
        assert my_device["is_active"] is True  # WS connected

    # 4. Mock WS disconnection
    with patch("hub.routers.devices.connection_manager") as mock_cm:
        mock_cm.is_connected.return_value = False

        response = await client.get("/api/devices", headers=user_auth_headers)
        assert response.status_code == 200
        devices = response.json()
        my_device = next(d for d in devices if d["id"] == device_id)
        assert my_device["is_active"] is False  # WS disconnected

    # 5. Heartbeat does not change status without WS
    response = await client.post("/skills/heartbeat", headers=device_auth_headers)
    assert response.status_code == 200

    response = await client.get("/api/devices", headers=user_auth_headers)
    assert response.status_code == 200
    devices = response.json()
    my_device = next(d for d in devices if d["id"] == device_id)
    assert my_device["is_active"] is False  # Still inactive
