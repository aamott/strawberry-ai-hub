"""Pytest fixtures for Hub tests."""

import os
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport

# Set test database BEFORE importing any hub modules
TEST_DB_PATH = Path(__file__).parent / "test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"

# Now import hub modules
from hub import database  # noqa: E402 - ignore import order so we can set test database
from hub.database import dispose_engine, reset_engine  # noqa: E402 - ignore import order


@pytest.fixture(scope="function")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="function", autouse=True)
async def setup_test_db():
    """Set up and tear down test database for each test."""
    # Remove old test db if exists
    if TEST_DB_PATH.exists():
        await dispose_engine()
        TEST_DB_PATH.unlink()
    
    # Reset engine to pick up test DATABASE_URL
    reset_engine()
    
    # Initialize database tables
    await database.init_db()
    
    yield
    
    # Cleanup - reset engine and remove test db
    await dispose_engine()
    reset_engine()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture(scope="function")
async def client(setup_test_db):
    """Create test client."""
    from hub.main import app
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_client(client):
    """Create authenticated test client."""
    # Register a device first
    response = await client.post(
        "/auth/register",
        json={"name": "Test Device", "user_id": "test_user"},
    )
    assert response.status_code == 200, f"Registration failed: {response.text}"
    data = response.json()
    token = data["access_token"]
    
    # Return client with auth header set
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
