"""Device management endpoints."""

from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import Device, Skill, get_db
from ..auth import get_current_device

router = APIRouter(prefix="/devices", tags=["devices"])


class DeviceResponse(BaseModel):
    """Device information."""
    id: str
    name: str
    is_active: bool
    is_online: bool
    last_seen: Optional[datetime]
    skill_count: int


class DeviceListResponse(BaseModel):
    """List of devices."""
    devices: List[DeviceResponse]
    total: int


@router.get("", response_model=DeviceListResponse)
async def list_devices(
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """List all devices for the current user."""
    # Get all devices for this user
    result = await db.execute(
        select(Device).where(Device.user_id == device.user_id)
    )
    devices = result.scalars().all()
    
    # Get skill counts
    expiry_time = datetime.utcnow() - timedelta(seconds=settings.skill_expiry_seconds)
    
    device_responses = []
    for d in devices:
        # Count non-expired skills
        result = await db.execute(
            select(Skill)
            .where(Skill.device_id == d.id)
            .where(Skill.last_heartbeat > expiry_time)
        )
        skill_count = len(result.scalars().all())
        
        # Determine if device is "online" (seen recently)
        is_online = False
        if d.last_seen:
            is_online = (datetime.utcnow() - d.last_seen).total_seconds() < 300  # 5 min
        
        device_responses.append(DeviceResponse(
            id=d.id,
            name=d.name,
            is_active=d.is_active,
            is_online=is_online,
            last_seen=d.last_seen,
            skill_count=skill_count,
        ))
    
    return DeviceListResponse(
        devices=device_responses,
        total=len(device_responses),
    )


@router.get("/{device_id}")
async def get_device(
    device_id: str,
    current_device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Get details for a specific device."""
    result = await db.execute(
        select(Device).where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    # Check access (must be same user)
    if device.user_id != current_device.user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Get skills
    expiry_time = datetime.utcnow() - timedelta(seconds=settings.skill_expiry_seconds)
    result = await db.execute(
        select(Skill)
        .where(Skill.device_id == device.id)
        .where(Skill.last_heartbeat > expiry_time)
    )
    skills = result.scalars().all()
    
    is_online = False
    if device.last_seen:
        is_online = (datetime.utcnow() - device.last_seen).total_seconds() < 300
    
    return {
        "id": device.id,
        "name": device.name,
        "user_id": device.user_id,
        "is_active": device.is_active,
        "is_online": is_online,
        "last_seen": device.last_seen,
        "created_at": device.created_at,
        "skills": [
            {
                "class_name": s.class_name,
                "function_name": s.function_name,
                "signature": s.signature,
            }
            for s in skills
        ],
    }

