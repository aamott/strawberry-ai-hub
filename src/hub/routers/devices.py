import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user, create_access_token
from ..config import settings
from ..database import get_db, Device, User

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

class DeviceTokenResponse(BaseModel):
    device: DeviceResponse
    token: str
    command: str

# --- Endpoints ---

@router.get("", response_model=List[DeviceResponse])
async def get_my_devices(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List devices owned by the current user."""
    # Admins see ALL devices? Or just their own?
    # Requirement: "Regular users only get access to their own settings"
    # Let's start strict: You only see YOUR devices. 
    # Admins can use the separate admin router if they need a global view.
    
    result = await db.execute(select(Device).where(Device.user_id == current_user.id))
    return result.scalars().all()


@router.post("/token", response_model=DeviceTokenResponse)
async def create_device_token(
    device_in: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Register a new device for the current user."""
    
    # Create device linked to current_user
    device_id = str(uuid.uuid4())
    device = Device(
        id=device_id,
        name=device_in.name,
        user_id=current_user.id, # Link to creator
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
        expires_delta=None # Long-lived
    )
    
    # Generate connection command using configured host/port
    hub_url = f"http://{settings.host}:{settings.port}" 
    
    # Command supporting the new Spoke loader
    command = f"export STRAWBERRY_HUB_URL={hub_url} STRAWBERRY_DEVICE_TOKEN={access_token} && python -m strawberry.main"
    
    return {
        "device": device,
        "token": access_token,
        "command": command
    }


@router.delete("/{device_id}")
async def delete_device(
    device_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a device owned by the current user."""
    
    # Find device checking ownership
    result = await db.execute(
        select(Device).where(
            Device.id == device_id,
            Device.user_id == current_user.id
        )
    )
    device = result.scalar_one_or_none()
    
    if not device:
        # If admin, maybe allow deleting any device?
        # For now, stick to ownership rules or 404 to avoid leaking existence
        raise HTTPException(status_code=404, detail="Device not found")
        
    await db.delete(device)
    await db.commit()
    return {"status": "deleted"}
