"""Skill registry endpoints."""

from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_device
from ..config import settings
from ..database import Device, Skill, get_db
from ..skill_service import DevicesProxy
from ..utils import normalize_device_name
from .websocket import ConnectionManager, get_connection_manager

router = APIRouter(prefix="/skills", tags=["skills"])


async def _get_user_devices(
    db: AsyncSession,
    user_id: str,
) -> dict[str, Device]:
    """Fetch devices for a user keyed by device ID.

    Args:
        db: Active database session.
        user_id: User identifier to scope devices.

    Returns:
        Mapping of device ID to Device row.
    """
    result = await db.execute(select(Device).where(Device.user_id == user_id))
    return {device.id: device for device in result.scalars().all()}


class SkillInfo(BaseModel):
    """Skill information for registration."""

    class_name: str
    function_name: str
    signature: str
    docstring: Optional[str] = None


class SkillRegisterRequest(BaseModel):
    """Request to register skills."""

    skills: List[SkillInfo]


class SkillExecuteRequest(BaseModel):
    """Request to execute a remote skill."""

    device_name: str
    skill_name: str
    method_name: str
    args: List[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class SkillResponse(BaseModel):
    """Skill information in response."""

    id: int
    device_id: str
    device_name: str
    class_name: str
    function_name: str
    signature: str
    docstring: Optional[str]
    last_heartbeat: datetime


class SkillListResponse(BaseModel):
    """List of skills."""

    skills: List[SkillResponse]
    total: int


@router.post("/register")
async def register_skills(
    request: SkillRegisterRequest,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Register skills from a device.

    This replaces all existing skills for the device.
    """
    # Delete existing skills for this device
    await db.execute(delete(Skill).where(Skill.device_id == device.id))

    # Add new skills
    now = datetime.now(timezone.utc)
    for skill_info in request.skills:
        skill = Skill(
            device_id=device.id,
            class_name=skill_info.class_name,
            function_name=skill_info.function_name,
            signature=skill_info.signature,
            docstring=skill_info.docstring,
            last_heartbeat=now,
        )
        db.add(skill)

    await db.commit()

    return {
        "message": f"Registered {len(request.skills)} skills",
        "device_id": device.id,
    }


@router.post("/heartbeat")
async def heartbeat(
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Update heartbeat for all skills on this device."""
    now = datetime.now(timezone.utc)

    # Update all skills for this device
    result = await db.execute(select(Skill).where(Skill.device_id == device.id))
    skills = result.scalars().all()

    for skill in skills:
        skill.last_heartbeat = now

    await db.commit()

    return {
        "message": f"Heartbeat updated for {len(skills)} skills",
        "timestamp": now.isoformat(),
    }


@router.post("/execute")
async def execute_skill(
    request: SkillExecuteRequest,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    """Execute a skill on a remote device via WebSocket.

    Routes the skill call to the target device through the WebSocket connection.
    """
    # Find target device by normalized name (must be same user)
    # Get all user devices and match by normalized name
    user_devices = await _get_user_devices(db, device.user_id)

    target_device = None
    request_normalized = normalize_device_name(request.device_name)
    for target in user_devices.values():
        if normalize_device_name(target.name) == request_normalized:
            target_device = target
            break

    if not target_device:
        raise HTTPException(
            status_code=404,
            detail=f"Device '{request.device_name}' not found or not accessible",
        )

    # Check if device is connected
    if not manager.is_connected(target_device.id):
        raise HTTPException(
            status_code=503,
            detail=f"Device '{request.device_name}' is not currently connected",
        )

    # Execute skill via WebSocket
    try:
        result = await manager.send_skill_request(
            device_id=target_device.id,
            skill_name=request.skill_name,
            method_name=request.method_name,
            args=request.args,
            kwargs=request.kwargs,
            timeout=30.0,
        )

        return {
            "success": True,
            "result": result,
        }

    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))

    except ValueError as e:
        # Device not connected (checked by send_skill_request)
        raise HTTPException(status_code=503, detail=str(e))

    except RuntimeError as e:
        # Skill execution error on remote device
        raise HTTPException(status_code=500, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


@router.get("", response_model=SkillListResponse)
async def list_skills(
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
    include_expired: bool = False,
):
    """List all skills visible to this device.

    Returns skills from all devices owned by the same user.
    """
    # Get all devices for this user
    user_devices = await _get_user_devices(db, device.user_id)

    # Get skills from those devices
    query = select(Skill).where(Skill.device_id.in_(user_devices.keys()))

    if not include_expired:
        expiry_time = datetime.now(timezone.utc) - timedelta(
            seconds=settings.skill_expiry_seconds
        )
        query = query.where(Skill.last_heartbeat > expiry_time)

    result = await db.execute(query)
    skills = result.scalars().all()

    return SkillListResponse(
        skills=[
            SkillResponse(
                id=s.id,
                device_id=s.device_id,
                device_name=user_devices[s.device_id].name,
                class_name=s.class_name,
                function_name=s.function_name,
                signature=s.signature,
                docstring=s.docstring,
                last_heartbeat=s.last_heartbeat,
            )
            for s in skills
        ],
        total=len(skills),
    )


@router.get("/search")
async def search_skills(
    query: str = "",
    device_limit: int = 10,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
    manager: ConnectionManager = Depends(get_connection_manager),
):
    """Search for skills using the canonical DevicesProxy implementation."""
    proxy = DevicesProxy(db=db, user_id=device.user_id, connection_manager=manager)
    results = await proxy.search_skills(query=query, device_limit=device_limit)
    return {"results": results, "total": len(results)}
