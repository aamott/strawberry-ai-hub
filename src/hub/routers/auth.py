"""Authentication endpoints."""

from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..database import Device
from ..auth import (
    create_access_token,
    get_current_device,
)

router = APIRouter(prefix="/auth", tags=["auth"])

class DeviceInfoResponse(BaseModel):
    """Device information."""
    device_id: str
    name: str
    user_id: str
    is_active: bool
    last_seen: datetime | None
    created_at: datetime


@router.get("/me", response_model=DeviceInfoResponse)
async def get_current_device_info(
    device: Device = Depends(get_current_device),
):
    """Get information about the authenticated device."""
    return DeviceInfoResponse(
        device_id=device.id,
        name=device.name,
        user_id=device.user_id,
        is_active=device.is_active,
        last_seen=device.last_seen,
        created_at=device.created_at,
    )


@router.post("/refresh")
async def refresh_token(
    device: Device = Depends(get_current_device),
):
    """Refresh the access token."""
    access_token = create_access_token(
        subject=device.id,
        subject_type="device",
        name=device.name,
    )
    
    return {"access_token": access_token}

