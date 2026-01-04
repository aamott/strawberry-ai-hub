"""Tests for session management endpoints."""

import pytest


@pytest.mark.asyncio
async def test_create_session(auth_client):
    """Test creating a new session."""
    response = await auth_client.post("/sessions", json={})

    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["is_active"] is True
    assert data["message_count"] == 0


@pytest.mark.asyncio
async def test_list_sessions(auth_client):
    """Test listing sessions."""
    # Create a session first
    await auth_client.post("/sessions", json={})

    response = await auth_client.get("/sessions")

    assert response.status_code == 200
    data = response.json()
    assert "sessions" in data
    assert "total" in data
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_get_session(auth_client):
    """Test getting a specific session."""
    # Create a session
    create_resp = await auth_client.post("/sessions", json={})
    session_id = create_resp.json()["id"]

    # Get it
    response = await auth_client.get(f"/sessions/{session_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == session_id


@pytest.mark.asyncio
async def test_add_message(auth_client):
    """Test adding a message to a session."""
    # Create a session
    create_resp = await auth_client.post("/sessions", json={})
    session_id = create_resp.json()["id"]

    # Add a message
    response = await auth_client.post(
        f"/sessions/{session_id}/messages",
        json={"role": "user", "content": "Hello, world!"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "user"
    assert data["content"] == "Hello, world!"


@pytest.mark.asyncio
async def test_get_messages(auth_client):
    """Test getting messages for a session."""
    # Create a session
    create_resp = await auth_client.post("/sessions", json={})
    session_id = create_resp.json()["id"]

    # Add messages
    await auth_client.post(
        f"/sessions/{session_id}/messages",
        json={"role": "user", "content": "Hello!"},
    )
    await auth_client.post(
        f"/sessions/{session_id}/messages",
        json={"role": "assistant", "content": "Hi there!"},
    )

    # Get messages
    response = await auth_client.get(f"/sessions/{session_id}/messages")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_delete_session(auth_client):
    """Test deleting a session."""
    # Create a session
    create_resp = await auth_client.post("/sessions", json={})
    session_id = create_resp.json()["id"]

    # Delete it
    response = await auth_client.delete(f"/sessions/{session_id}")
    assert response.status_code == 200

    # Verify it's gone
    get_resp = await auth_client.get(f"/sessions/{session_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_session_title_from_first_message(auth_client):
    """Test that session title is derived from first user message."""
    # Create a session
    create_resp = await auth_client.post("/sessions", json={})
    session_id = create_resp.json()["id"]

    # Add a user message
    await auth_client.post(
        f"/sessions/{session_id}/messages",
        json={"role": "user", "content": "What's the weather like today?"},
    )

    # Get session - should have title from first message
    response = await auth_client.get(f"/sessions/{session_id}")
    data = response.json()
    assert data["title"] is not None
    assert "weather" in data["title"].lower()


@pytest.mark.asyncio
async def test_sessions_requires_auth(client):
    """Test that /sessions requires authentication."""
    response = await client.get("/sessions")
    assert response.status_code in (401, 403)
