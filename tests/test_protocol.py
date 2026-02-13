"""Tests for wire protocol version enforcement and device name normalization."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from hub.main import app
from hub.routers.websocket import _resolve_ws_protocol_version
from hub.utils import normalize_device_name

# ── Normalization parity tests ──────────────────────────────────────────────

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2]  # repo root
    / "docs"
    / "test-fixtures"
    / "normalize_device_name.json"
)


def _load_normalization_cases() -> list:
    """Load test vectors from the shared fixture file."""
    data = json.loads(FIXTURE_PATH.read_text())
    return data["cases"]


@pytest.mark.parametrize(
    "case",
    _load_normalization_cases(),
    ids=[c["input"] or "<empty>" for c in _load_normalization_cases()],
)
def test_normalize_device_name(case: dict):
    """Hub normalize_device_name must match the canonical fixture."""
    assert normalize_device_name(case["input"]) == case["expected"]


# ── Protocol version middleware tests ───────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_no_version_header_allowed():
    """Requests without X-Protocol-Version pass through (browser, curl)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_supported_version_allowed():
    """Requests with a supported version header pass through."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/health",
            headers={"X-Protocol-Version": "v1"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unsupported_version_rejected():
    """Requests with an unsupported version header get 400."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get(
            "/health",
            headers={"X-Protocol-Version": "v99"},
        )
    assert resp.status_code == 400
    assert "v99" in resp.text


def test_ws_protocol_version_from_header():
    """WebSocket protocol version can be resolved from request header."""
    ws = SimpleNamespace(headers={"X-Protocol-Version": "v1"}, query_params={})
    assert _resolve_ws_protocol_version(ws) == "v1"


def test_ws_protocol_version_from_query():
    """WebSocket protocol version can be resolved from query parameter."""
    ws = SimpleNamespace(headers={}, query_params={"protocol_version": "v1"})
    assert _resolve_ws_protocol_version(ws) == "v1"


def test_ws_protocol_version_conflict_rejected():
    """Conflicting header/query protocol versions should fail validation."""
    ws = SimpleNamespace(
        headers={"X-Protocol-Version": "v1"},
        query_params={"protocol_version": "v2"},
    )
    with pytest.raises(HTTPException) as exc_info:
        _resolve_ws_protocol_version(ws)
    assert exc_info.value.status_code == 400
    assert "Conflicting protocol versions" in str(exc_info.value.detail)
