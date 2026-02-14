import logging
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..auth import create_access_token, get_current_user, get_user_id_from_token
from ..config import settings
from ..database import Device, User, get_db
from ..utils import normalize_device_name
from .websocket import (
    ConnectionManager,
    get_connection_manager,
)
from .websocket import (
    connection_manager as _legacy_connection_manager,
)

# Backwards-compatibility alias for tests that patch
# ``hub.routers.devices.connection_manager`` directly.
connection_manager = _legacy_connection_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices", tags=["devices"])

# --- Models ---


class DeviceCreate(BaseModel):
    name: str


class DeviceResponse(BaseModel):
    id: str
    name: str
    is_active: bool
    last_seen: datetime | None = None
    created_at: datetime
    skill_names: list[str] = []
    skill_count: int = 0


class DeviceTokenResponse(BaseModel):
    device: DeviceResponse
    token: str
    command: str


class DeviceRegisterRequest(BaseModel):
    """Request from a Spoke to register/reconnect a device."""

    device_name: str
    device_id: Optional[str] = None  # Previously assigned ID (reconnect)


class DeviceRegisterResponse(BaseModel):
    """Response with the Hub-assigned device identity."""

    device_id: str
    display_name: str


# --- Helpers ---


async def _resolve_display_name(
    db: AsyncSession,
    user_id: str,
    desired_name: str,
    exclude_device_id: Optional[str] = None,
) -> str:
    """Pick a unique display name within the user's device scope.

    If ``desired_name`` is already taken by another device, append
    ``_2``, ``_3``, etc. until a free slot is found.

    Args:
        db: Database session.
        user_id: Owner user ID.
        desired_name: Requested display name.
        exclude_device_id: Device ID to exclude from collision check
            (the device being registered itself).

    Returns:
        A display name guaranteed unique within the user scope.
    """
    # Fetch existing normalized names for the user's devices.
    result = await db.execute(
        select(Device.id, Device.name).where(Device.user_id == user_id)
    )
    existing = {
        row.id: normalize_device_name(row.name) for row in result.all()
    }

    desired_normalized = normalize_device_name(desired_name)

    # Check if any *other* device already has this normalized name.
    collision = any(
        norm == desired_normalized
        for did, norm in existing.items()
        if did != exclude_device_id
    )

    if not collision:
        return desired_name

    # Auto-suffix: try _2, _3, ...
    suffix = 2
    while True:
        candidate = f"{desired_name} {suffix}"
        candidate_norm = normalize_device_name(candidate)
        collision = any(
            norm == candidate_norm
            for did, norm in existing.items()
            if did != exclude_device_id
        )
        if not collision:
            return candidate
        suffix += 1

# --- Endpoints ---


@router.post("/register", response_model=DeviceRegisterResponse)
async def register_device(
    request: DeviceRegisterRequest,
    user_info: tuple[str, str] = Depends(get_user_id_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Register (or reconnect) a Spoke device.

    This is the primary endpoint Spokes call on connect. It replaces
    the old model where one JWT = one device. Now multiple Spokes can
    share the same auth token and each gets its own device_id.

    Logic:
    - If ``device_id`` is provided and belongs to this user -> reconnect
      (update name, last_seen). Return the same device_id.
    - Otherwise -> create a new device, assign a UUID, return it.
    - Display name collisions within the same user scope are resolved
      by auto-suffixing (``_2``, ``_3``, etc.).
    """
    user_id, _jwt_device_id = user_info
    now = datetime.now(timezone.utc)

    # --- Reconnect path ---
    if request.device_id:
        result = await db.execute(
            select(Device).where(
                Device.id == request.device_id,
                Device.user_id == user_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            # Resolve display name (may change if another device took the name)
            resolved_name = await _resolve_display_name(
                db, user_id, request.device_name, exclude_device_id=existing.id
            )
            existing.name = resolved_name
            existing.last_seen = now
            existing.is_active = True
            await db.commit()

            logger.info(
                "Device reconnected: %s (%s) for user %s",
                existing.id,
                resolved_name,
                user_id,
            )
            return DeviceRegisterResponse(
                device_id=existing.id,
                display_name=resolved_name,
            )

        # device_id provided but not found — fall through to create new.
        logger.info(
            "Device ID %s not found for user %s, creating new device",
            request.device_id,
            user_id,
        )

    # --- New device path ---
    new_device_id = str(uuid.uuid4())
    resolved_name = await _resolve_display_name(
        db, user_id, request.device_name, exclude_device_id=new_device_id
    )

    device = Device(
        id=new_device_id,
        name=resolved_name,
        user_id=user_id,
        hashed_token="spoke-registered",
        is_active=True,
        last_seen=now,
    )
    db.add(device)
    await db.commit()

    logger.info(
        "New device registered: %s (%s) for user %s",
        new_device_id,
        resolved_name,
        user_id,
    )
    return DeviceRegisterResponse(
        device_id=new_device_id,
        display_name=resolved_name,
    )


@router.get("", response_model=List[DeviceResponse])
async def get_my_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    """List devices owned by the current user."""
    # Admins see ALL devices? Or just their own?
    # Requirement: "Regular users only get access to their own settings"
    # Let's start strict: You only see YOUR devices.
    # Admins can use the separate admin router if they need a global view.

    # Eager-load skills to avoid N+1 queries when building the response.
    result = await db.execute(
        select(Device)
        .where(Device.user_id == current_user.id)
        .options(selectinload(Device.skills))
    )
    devices_db = result.scalars().all()

    # Compute is_active based on WebSocket connection status
    devices = []
    status_manager: Any = manager
    if connection_manager is not _legacy_connection_manager:
        status_manager = connection_manager

    for device in devices_db:
        is_connected = status_manager.is_connected(device.id)
        # Deduplicate and sort skill class names for this device.
        unique_skills = sorted({s.class_name for s in device.skills})
        devices.append(
            DeviceResponse(
                id=device.id,
                name=device.name,
                is_active=is_connected,
                last_seen=device.last_seen,
                created_at=device.created_at,
                skill_names=unique_skills,
                skill_count=len(unique_skills),
            )
        )
    return devices


@router.post("/token", response_model=DeviceTokenResponse)
async def create_device_token(
    device_in: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Register a new device for the current user."""

    # Create device linked to current_user
    device_id = str(uuid.uuid4())
    device = Device(
        id=device_id,
        name=device_in.name,
        user_id=current_user.id,  # Link to creator
        hashed_token="jwt-auth",
        is_active=True,
    )
    db.add(device)
    await db.commit()

    # Generate JWT for the device
    access_token = create_access_token(
        subject=device.id,
        subject_type="device",
        name=device.name,
        expires_delta=None,  # Long-lived
    )

    # Generate connection command using configured host/port
    hub_url = f"http://{settings.host}:{settings.port}"

    # Command supporting the new Spoke loader
    command = (
        f"export STRAWBERRY_HUB_URL={hub_url}"
        f" STRAWBERRY_DEVICE_TOKEN={access_token}"
        " && python -m strawberry.main"
    )

    return {"device": device, "token": access_token, "command": command}


@router.delete("/{device_id}")
async def delete_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a device owned by the current user."""

    # Find device checking ownership
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.user_id == current_user.id)
    )
    device = result.scalar_one_or_none()

    if not device:
        # If admin, maybe allow deleting any device?
        # For now, stick to ownership rules or 404 to avoid leaking existence
        raise HTTPException(status_code=404, detail="Device not found")

    await db.delete(device)
    await db.commit()
    return {"status": "deleted"}
