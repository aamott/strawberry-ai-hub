"""Tests for authentication."""

import pytest


@pytest.mark.asyncio
async def test_setup_admin_user(client):
    """Test admin user setup."""
    response = await client.post(
        "/api/users/setup",
        json={"username": "admin", "password": "password"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_admin_user(client):
    """Test admin user login."""
    # Setup first
    await client.post(
        "/api/users/setup",
        json={"username": "admin", "password": "password"},
    )

    # Login
    response = await client.post(
        "/api/users/login",
        json={"username": "admin", "password": "password"},
    )

    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_unauthorized_access(client):
    """Test that endpoints require authentication."""
    response = await client.get("/api/users/me")

    # Should fail without auth (401 or 403)
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_login_with_wrong_password(client):
    """Test login fails with wrong password."""
    # Setup first
    await client.post(
        "/api/users/setup",
        json={"username": "admin", "password": "password"},
    )

    # Try login with wrong password
    response = await client.post(
        "/api/users/login",
        json={"username": "admin", "password": "wrongpassword"},
    )

    assert response.status_code == 401
