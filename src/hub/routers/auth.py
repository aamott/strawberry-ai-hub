"""Authentication endpoints."""

from datetime import datetime
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import Device, get_db
from ..auth import (
    generate_device_token,
    hash_token,
    create_access_token,
    get_current_device,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class DeviceRegisterRequest(BaseModel):
    """Request to register a new device."""
    name: str
    user_id: str


class DeviceRegisterResponse(BaseModel):
    """Response with device credentials."""
    device_id: str
    access_token: str
    message: str


class DeviceInfoResponse(BaseModel):
    """Device information."""
    device_id: str
    name: str
    user_id: str
    is_active: bool
    last_seen: datetime | None
    created_at: datetime


@router.post("/register", response_model=DeviceRegisterResponse)
async def register_device(
    request: DeviceRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new device and get access token.
    
    In production, this would require user authentication first.
    For now, we allow open registration with a user_id.
    """
    device_id = str(uuid.uuid4())[:8]
    device_token = generate_device_token()
    
    # Create device in database
    device = Device(
        id=device_id,
        name=request.name,
        user_id=request.user_id,
        hashed_token=hash_token(device_token),
        is_active=True,
        last_seen=datetime.utcnow(),
    )
    
    db.add(device)
    await db.commit()
    
    # Create JWT access token
    access_token = create_access_token(
        subject=device_id,
        subject_type="device",
        name=request.name,
    )
    
    return DeviceRegisterResponse(
        device_id=device_id,
        access_token=access_token,
        message=f"Device '{request.name}' registered successfully",
    )


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

