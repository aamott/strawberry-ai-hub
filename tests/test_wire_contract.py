"""Contract tests: Hub Pydantic models must parse canonical wire payloads.

These tests load sample payloads from docs/test-fixtures/wire_schema_v1.json
and validate that the Hub's router models can deserialize them without error.
If a model field is renamed or removed, these tests will catch the drift.
"""

import json
from pathlib import Path

import pytest

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]  # repo root
    / "docs"
    / "test-fixtures"
    / "wire_schema_v1.json"
)


@pytest.fixture(scope="module")
def fixtures() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


# ── Import Hub router models ───────────────────────────────────────────────

from hub.routers.skills import (  # noqa: E402
    SkillExecuteRequest,
    SkillInfo,
    SkillRegisterRequest,
)

# ── Contract tests ─────────────────────────────────────────────────────────


def test_skill_register_request(fixtures: dict):
    """SkillRegisterRequest must parse the canonical fixture."""
    payload = fixtures["skill_register_request"]
    req = SkillRegisterRequest(**payload)
    assert len(req.skills) == 2
    assert req.skills[0].class_name == "WeatherSkill"
    assert req.skills[1].docstring is None


def test_skill_info(fixtures: dict):
    """Individual SkillInfo must parse."""
    skill_data = fixtures["skill_register_request"]["skills"][0]
    info = SkillInfo(**skill_data)
    assert info.function_name == "get_current_weather"
    assert info.signature.startswith("get_current_weather")


def test_skill_execute_request(fixtures: dict):
    """SkillExecuteRequest must parse the canonical fixture."""
    payload = fixtures["skill_execute_request"]
    req = SkillExecuteRequest(**payload)
    assert req.device_name == "living_room_pc"
    assert req.skill_name == "WeatherSkill"
    assert req.kwargs == {"location": "Seattle"}


def test_skill_execute_response_shape(fixtures: dict):
    """Skill execute response must have required keys."""
    for key in ("skill_execute_response_success",
                "skill_execute_response_failure"):
        resp = fixtures[key]
        assert "success" in resp
        assert "result" in resp
        assert "error" in resp


def test_skill_search_response_shape(fixtures: dict):
    """Skill search response must have results and total."""
    resp = fixtures["skill_search_response"]
    assert "results" in resp
    assert "total" in resp
    result = resp["results"][0]
    for field in ("path", "signature", "summary", "devices",
                  "device_count", "is_local"):
        assert field in result, f"Missing field: {field}"


def test_ws_skill_request_shape(fixtures: dict):
    """WebSocket skill_request must have required keys."""
    msg = fixtures["ws_skill_request"]
    assert msg["v"] == 1
    assert msg["type"] == "skill_request"
    for field in ("request_id", "skill_name", "method_name"):
        assert field in msg


def test_ws_skill_response_shape(fixtures: dict):
    """WebSocket skill_response must have required keys."""
    msg = fixtures["ws_skill_response"]
    assert msg["v"] == 1
    assert msg["type"] == "skill_response"
    assert "request_id" in msg
    assert "success" in msg
