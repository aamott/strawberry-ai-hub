
from unittest.mock import AsyncMock, MagicMock

import pytest

from hub.database import Device, Skill
from hub.skill_service import HubSkillService


@pytest.fixture
def mock_db_session():
    """Return an async mock database session."""
    return AsyncMock()

@pytest.fixture
def mock_connection_manager():
    """Return a mock connection manager."""
    cm = MagicMock()
    cm.is_connected = MagicMock(return_value=False)
    return cm

@pytest.mark.asyncio
async def test_search_skills_prioritizes_connected_devices(
    mock_db_session,
    mock_connection_manager,
):
    # Setup devices: "spoke two" (disconnected) and "strawberry spoke" (connected)
    # Alphabetically, "spoke two" comes before "strawberry spoke"
    device_disconnected = Device(
        id="d1",
        name="spoke two",
        user_id="u1",
        is_active=True,
    )
    device_connected = Device(
        id="d2",
        name="strawberry spoke",
        user_id="u1",
        is_active=True,
    )

    # Mock DB returning devices
    mock_db_session.execute.return_value.scalars.return_value.all.return_value = [
        device_disconnected,
        device_connected,
    ]

    # Mock ConnectionManager: only "strawberry spoke" (d2) is connected
    mock_connection_manager.is_connected.side_effect = (
        lambda device_id: device_id == "d2"
    )
    mock_connection_manager.get_connected_devices.return_value = ["d2"]

    service = HubSkillService(mock_db_session, "u1", mock_connection_manager)

    # Mock search_skills database query for skills
    # We need to mock the second execute call in search_skills (the one for skills)
    # The first one is for _get_user_devices which we handled above.

    # Actually, _get_user_devices caches the result, so we only need to
    # handle the first call?
    # No, wait. HubSkillService.devices is a property that creates a DevicesProxy.
    # DevicesProxy._get_user_devices calls db.execute.

    # Let's mock the internal methods to avoid complex DB mocking if possible,
    # but we want to test the logic in search_skills.

    # Let's construct the skill response manually
    skill1 = Skill(
        device_id="d1",
        class_name="TestSkill",
        function_name="test",
        signature="test()",
        docstring="test",
        device=device_disconnected
    )
    skill2 = Skill(
        device_id="d2",
        class_name="TestSkill",
        function_name="test",
        signature="test()",
        docstring="test",
        device=device_connected
    )

    # We need to handle multiple await db.execute calls.
    # 1. _get_user_devices -> returns devices
    # 2. search_skills -> returns skills

    # Create distinct mocks for the results
    devices_result = MagicMock()
    devices_result.scalars.return_value.all.return_value = [
        device_disconnected,
        device_connected,
    ]

    skills_result = MagicMock()
    skills_result.scalars.return_value.all.return_value = [skill1, skill2]

    mock_db_session.execute.side_effect = [devices_result, skills_result]

    results = await service.devices.search_skills("test")

    assert len(results) == 1
    assert results[0]["path"] == "TestSkill.test"
    # IMPORTANT: This assertion will FAIL before the fix, because it sorts
    # alphabetically. "spoke two" vs "strawberry spoke" -> "spoke two" wins
    # if we don't prioritize connection.
    # Or actually, "strawberry spoke" vs "spoke two". "spoke two" is
    # alphabetically first?
    # "s", "p", "o", "k", "e", " " "t"...
    # "s", "t", "r", "a", "w"...
    # "spoke" comes before "strawberry". So "spoke two" is preferred by default sort.

    # We want "strawberry spoke" to be the preferred device because it is connected.
    # Note: search_skills returns normalized device names
    assert results[0]["preferred_device"] == "strawberry_spoke"
    assert results[0]["devices"][0] == "strawberry_spoke"

