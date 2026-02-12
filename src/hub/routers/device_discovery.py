"""Device discovery endpoints (device-authenticated).

These endpoints allow devices to discover other devices belonging to the same user.
This is separate from /api/devices which is for user management via the web UI.
"""

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_device
from ..database import Device, get_db

router = APIRouter(prefix="/api/device-discovery", tags=["device-discovery"])


class DeviceInfo(BaseModel):
    """Public device information for discovery."""

    id: str
    name: str
    is_active: bool
    last_seen: datetime | None = None


class DeviceListResponse(BaseModel):
    """Response containing list of devices."""

    devices: List[DeviceInfo]
    total: int


@router.get("", response_model=DeviceListResponse)
async def list_sibling_devices(
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """List all devices belonging to the same user.

    This allows devices to discover other devices for remote skill calls.
    The requesting device is included in the list.
    """
    result = await db.execute(
        select(Device).where(
            Device.user_id == device.user_id,
            Device.is_active == True,  # noqa: E712
        )
    )
    devices = result.scalars().all()

    return DeviceListResponse(
        devices=[
            DeviceInfo(
                id=d.id,
                name=d.name,
                is_active=d.is_active,
                last_seen=d.last_seen,
            )
            for d in devices
        ],
        total=len(devices),
    )


@router.get("/me", response_model=DeviceInfo)
async def get_current_device_info(
    device: Device = Depends(get_current_device),
):
    """Get information about the current device."""
    return DeviceInfo(
        id=device.id,
        name=device.name,
        is_active=device.is_active,
        last_seen=device.last_seen,
    )
