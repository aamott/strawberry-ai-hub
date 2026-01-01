"""Skill registry endpoints."""

from datetime import datetime, timedelta
from typing import List, Optional, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import Device, Skill, get_db
from ..auth import get_current_device

router = APIRouter(prefix="/skills", tags=["skills"])


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
    args: List[Any] = []
    kwargs: dict = {}


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
    now = datetime.utcnow()
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
    now = datetime.utcnow()
    
    # Update all skills for this device
    result = await db.execute(
        select(Skill).where(Skill.device_id == device.id)
    )
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
):
    """Execute a skill on a remote device via WebSocket.
    
    Routes the skill call to the target device through the WebSocket connection.
    """
    # Import here to avoid circular dependency
    from .websocket import connection_manager
    
    # Find target device by name (must be same user)
    result = await db.execute(
        select(Device)
        .where(Device.name == request.device_name)
        .where(Device.user_id == device.user_id)
    )
    target_device = result.scalar_one_or_none()
    
    if not target_device:
        raise HTTPException(
            status_code=404,
            detail=f"Device '{request.device_name}' not found or not accessible"
        )
    
    # Check if device is connected
    if not connection_manager.is_connected(target_device.id):
        raise HTTPException(
            status_code=503,
            detail=f"Device '{request.device_name}' is not currently connected"
        )
    
    # Execute skill via WebSocket
    try:
        result = await connection_manager.send_skill_request(
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
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


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
    result = await db.execute(
        select(Device).where(Device.user_id == device.user_id)
    )
    user_devices = {d.id: d for d in result.scalars().all()}
    
    # Get skills from those devices
    query = select(Skill).where(Skill.device_id.in_(user_devices.keys()))
    
    if not include_expired:
        expiry_time = datetime.utcnow() - timedelta(seconds=settings.skill_expiry_seconds)
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
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Search for skills by name or docstring."""
    # Get all devices for this user
    result = await db.execute(
        select(Device).where(Device.user_id == device.user_id)
    )
    user_devices = {d.id: d for d in result.scalars().all()}
    
    # Get non-expired skills
    expiry_time = datetime.utcnow() - timedelta(seconds=settings.skill_expiry_seconds)
    result = await db.execute(
        select(Skill)
        .where(Skill.device_id.in_(user_devices.keys()))
        .where(Skill.last_heartbeat > expiry_time)
    )
    skills = result.scalars().all()
    
    # Filter by query (simple substring match)
    if query:
        query_lower = query.lower()
        skills = [
            s for s in skills
            if query_lower in s.function_name.lower()
            or query_lower in s.class_name.lower()
            or (s.docstring and query_lower in s.docstring.lower())
        ]
    
    # Format results (current device skills first)
    results = []
    for s in sorted(skills, key=lambda x: (x.device_id != device.id, x.class_name)):
        # Get first line of docstring as summary
        summary = ""
        if s.docstring:
            lines = s.docstring.strip().split("\n")
            summary = lines[0] if lines else ""
        
        results.append({
            "path": f"{user_devices[s.device_id].name}.{s.class_name}.{s.function_name}",
            "signature": s.signature,
            "summary": summary,
            "device": user_devices[s.device_id].name,
            "device_id": s.device_id,
        })
    
    return {"results": results, "total": len(results)}

