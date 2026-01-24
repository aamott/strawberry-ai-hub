"""Pytest configuration and fixtures for Hub tests."""

import os
import sys
import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport

# Ensure the repo root is on sys.path so we can import the top-level `shared`
# package when tests are executed from the ai-hub project directory.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load test environment variables
test_env = Path(__file__).parent.parent / ".env.test"
if test_env.exists():
    from dotenv import load_dotenv
    load_dotenv(test_env)

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
    """Create authenticated test client with admin user and device."""
    # Setup admin user if no users exist
    count_response = await client.get("/api/users/count")
    if count_response.json() == 0:
        setup_response = await client.post(
            "/api/users/setup",
            json={"username": "admin", "password": "password"},
        )
        assert setup_response.status_code == 200, f"Setup failed: {setup_response.text}"
    
    # Login with admin credentials
    login_response = await client.post(
        "/api/users/login",
        json={"username": "admin", "password": "password"},
    )
    assert login_response.status_code == 200, f"Login failed: {login_response.text}"
    data = login_response.json()
    user_token = data["access_token"]
    
    # Set user auth header temporarily to create a device
    client.headers["Authorization"] = f"Bearer {user_token}"
    
    # Create a device for the user
    device_response = await client.post(
        "/api/devices/token",
        json={"name": "Test Device"},
    )
    assert device_response.status_code == 200, f"Device creation failed: {device_response.text}"
    device_data = device_response.json()
    device_token = device_data["token"]
    
    # Switch to device auth for the rest of the tests
    client.headers["Authorization"] = f"Bearer {device_token}"
    yield client
