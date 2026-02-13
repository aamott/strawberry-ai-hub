
import pytest
from starlette.testclient import TestClient

from hub.main import app


@pytest.fixture
def client_sync(setup_test_db):
    """Synchronous client for WebSocket testing."""
    return TestClient(app)

def test_connection_conflict_resolution(client_sync):
    """Test connection handling for multiple devices on same token."""

    # 1. Setup: Create admin user
    resp = client_sync.post(
        "/api/users/setup",
        json={"username": "admin", "password": "password"},
    )
    assert resp.status_code == 200

    login_resp = client_sync.post(
        "/api/users/login",
        json={"username": "admin", "password": "password"},
    )
    user_token = login_resp.json()["access_token"]

    # 2. Create a Device Token (Device T)
    resp = client_sync.post(
        "/api/devices/token",
        json={"name": "Base Device"},
        headers={"Authorization": f"Bearer {user_token}"}
    )
    assert resp.status_code == 200
    device_data = resp.json()
    token = device_data["token"]
    base_device_id = device_data["device"]["id"]

    # 3. Register Device A using Token
    # This simulates Spoke A starting up and registering
    resp_a = client_sync.post(
        "/api/devices/register",
        json={"device_name": "Spoke A"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_a.status_code == 200
    device_id_a = resp_a.json()["device_id"]
    assert device_id_a != base_device_id

    # 4. Register Device B using Token
    # This simulates Spoke B starting up and registering
    resp_b = client_sync.post(
        "/api/devices/register",
        json={"device_name": "Spoke B"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp_b.status_code == 200
    device_id_b = resp_b.json()["device_id"]
    assert device_id_b != base_device_id
    assert device_id_b != device_id_a

    # 5. Connect Device A (Scenario: Correct Configuration)
    with client_sync.websocket_connect(
        f"/ws/device?token={token}&device_id={device_id_a}"
    ) as ws_a:
        # A should be connected
        ws_a.send_json({"type": "ping"})
        assert ws_a.receive_json()["type"] == "pong"

        # 6. Connect Device B (Scenario: Correct Configuration)
        with client_sync.websocket_connect(
            f"/ws/device?token={token}&device_id={device_id_b}"
        ) as ws_b:
            # B should be connected
            ws_b.send_json({"type": "ping"})
            assert ws_b.receive_json()["type"] == "pong"

            # 7. Check if A is still connected (Send ping)
            # If they conflicted, A would be closed/disconnected.
            try:
                ws_a.send_json({"type": "ping"})
                assert ws_a.receive_json()["type"] == "pong"
                print(
                    "\nSUCCESS: Two devices with different IDs can coexist on same token."
                )
            except Exception as e:
                pytest.fail(f"Device A was disconnected when Device B connected: {e}")

def test_connection_conflict_same_id(client_sync):
    """Test that connecting with SAME device ID kicks the previous one."""

    # Setup ...
    resp = client_sync.post(
        "/api/users/setup",
        json={"username": "admin", "password": "password"},
    )
    login_resp = client_sync.post(
        "/api/users/login",
        json={"username": "admin", "password": "password"},
    )
    user_token = login_resp.json()["access_token"]

    resp = client_sync.post(
        "/api/devices/token",
        json={"name": "Base Device"},
        headers={"Authorization": f"Bearer {user_token}"}
    )
    token = resp.json()["token"]
    base_device_id = resp.json()["device"]["id"]

    # Connect Client 1 as Base Device
    with client_sync.websocket_connect(
        f"/ws/device?token={token}&device_id={base_device_id}"
    ) as ws_1:
        # Connect Client 2 as Base Device (SAME ID)
        with client_sync.websocket_connect(
            f"/ws/device?token={token}&device_id={base_device_id}"
        ) as ws_2:

            # Client 2 should be connected
            ws_2.send_json({"type": "ping"})
            assert ws_2.receive_json()["type"] == "pong"

            # Client 1 should be disconnected
            # Note: TestClient WebSocket implementation might behave differently
            # than real network.
            # But underlying ConnectionManager should have closed ws_1.

            with pytest.raises(Exception):  # expecting disconnect
                ws_1.send_json({"type": "ping"})
                ws_1.receive_json()

    print("\nSUCCESS: Same device ID conflict correctly kicks previous connection.")

