"""Tests for skill registry."""

import pytest
from sqlalchemy import text

from hub.database import get_engine


@pytest.mark.asyncio
async def test_register_skills(auth_client):
    """Test registering skills."""
    skills = [
        {
            "class_name": "MusicSkill",
            "function_name": "play_song",
            "signature": "play_song(name: str) -> bool",
            "docstring": "Play a song by name",
            "device_agnostic": False,
        },
        {
            "class_name": "MusicSkill",
            "function_name": "stop",
            "signature": "stop() -> None",
            "docstring": "Stop playback",
            "device_agnostic": False,
        },
    ]

    response = await auth_client.post(
        "/skills/register",
        json={"skills": skills},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Registered 2 skills"


@pytest.mark.asyncio
async def test_list_skills(auth_client):
    """Test listing skills after registration."""
    # Register first
    skills = [
        {
            "class_name": "TestSkill",
            "function_name": "do_thing",
            "signature": "do_thing() -> None",
            "docstring": None,
            "device_agnostic": True,
        },
    ]

    await auth_client.post("/skills/register", json={"skills": skills})

    # List
    response = await auth_client.get("/skills")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["skills"][0]["function_name"] == "do_thing"
    assert data["skills"][0]["device_agnostic"] is True


@pytest.mark.asyncio
async def test_heartbeat(auth_client):
    """Test skill heartbeat."""
    # Register first
    skills = [
        {
            "class_name": "TestSkill",
            "function_name": "test",
            "signature": "test()",
            "docstring": None,
            "device_agnostic": False,
        },
    ]
    await auth_client.post("/skills/register", json={"skills": skills})

    # Heartbeat
    response = await auth_client.post("/skills/heartbeat")

    assert response.status_code == 200
    data = response.json()
    assert "Heartbeat updated for 1 skills" in data["message"]


@pytest.mark.asyncio
async def test_search_skills(auth_client):
    """Test skill search."""
    # Register some skills
    skills = [
        {
            "class_name": "MusicSkill",
            "function_name": "play_song",
            "signature": "play_song(name: str) -> bool",
            "docstring": "Play music",
            "device_agnostic": False,
        },
        {
            "class_name": "LightSkill",
            "function_name": "turn_on",
            "signature": "turn_on() -> None",
            "docstring": "Turn on the light",
            "device_agnostic": False,
        },
    ]
    await auth_client.post("/skills/register", json={"skills": skills})

    # Search for music
    response = await auth_client.get("/skills/search", params={"query": "music"})

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert (
        "music" in data["results"][0]["path"].lower()
        or "music" in data["results"][0]["summary"].lower()
    )


@pytest.mark.asyncio
async def test_skills_table_has_device_agnostic_column(client):
    """DB initialization includes the skills.device_agnostic column."""
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(text("PRAGMA table_info(skills)"))
        columns = {row[1] for row in result.fetchall()}
    assert "device_agnostic" in columns
