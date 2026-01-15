"""Session management endpoints for chat history."""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_device
from ..database import Device, Session, Message, get_db

router = APIRouter(prefix="/sessions", tags=["sessions"])


# --- Models ---


class SessionCreate(BaseModel):
    """Request to create a new session.
    
    Note: Title is auto-generated from the first user message.
    """
    pass


class SessionInfo(BaseModel):
    """Session information."""

    id: str
    device_id: str
    user_id: str
    title: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_activity: datetime
    message_count: int = 0


class SessionListResponse(BaseModel):
    """Response containing list of sessions."""

    sessions: List[SessionInfo]
    total: int


class MessageInfo(BaseModel):
    """Message information."""

    id: int
    role: str
    content: str
    created_at: datetime


class SessionMessagesResponse(BaseModel):
    """Response containing session messages."""

    session_id: str
    messages: List[MessageInfo]
    total: int


class MessageCreate(BaseModel):
    """Request to add a message to a session."""

    role: str
    content: str


# --- Endpoints ---


@router.post("", response_model=SessionInfo)
async def create_session(
    request: SessionCreate,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat session."""
    session_id = str(uuid.uuid4())[:12]
    now = datetime.utcnow()

    session = Session(
        id=session_id,
        device_id=device.id,
        user_id=device.user_id,
        is_active=True,
        created_at=now,
        last_activity=now,
    )
    db.add(session)
    await db.commit()

    return SessionInfo(
        id=session.id,
        device_id=session.device_id,
        user_id=session.user_id,
        title=None,  # Auto-generated from first user message
        is_active=session.is_active,
        created_at=session.created_at,
        last_activity=session.last_activity,
        message_count=0,
    )


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
    days: Optional[int] = Query(None, description="Filter to sessions from last N days"),
):
    """List sessions for the current user.

    Returns sessions from all devices belonging to the same user,
    ordered by last activity (most recent first).

    Args:
        limit: Maximum number of sessions to return
        offset: Number of sessions to skip
        days: If provided, only return sessions with activity in the last N days
    """
    # Build query for this user's sessions
    query = select(Session).where(Session.user_id == device.user_id)

    # Apply date filter if requested
    if days is not None:
        cutoff = datetime.utcnow() - timedelta(days=days)
        query = query.where(Session.last_activity >= cutoff)

    # Get sessions ordered by last activity
    result = await db.execute(
        query.order_by(Session.last_activity.desc()).limit(limit).offset(offset)
    )
    sessions = result.scalars().all()

    # Use cached title and message_count (no N+1 queries)
    session_infos = [
        SessionInfo(
            id=s.id,
            device_id=s.device_id,
            user_id=s.user_id,
            title=s.title,
            is_active=s.is_active,
            created_at=s.created_at,
            last_activity=s.last_activity,
            message_count=s.message_count,
        )
        for s in sessions
    ]

    return SessionListResponse(sessions=session_infos, total=len(session_infos))


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(
    session_id: str,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific session."""
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == device.user_id,
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Use cached title and message_count
    return SessionInfo(
        id=session.id,
        device_id=session.device_id,
        user_id=session.user_id,
        title=session.title,
        is_active=session.is_active,
        created_at=session.created_at,
        last_activity=session.last_activity,
        message_count=session.message_count,
    )


@router.get("/{session_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(
    session_id: str,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Get all messages for a session."""
    # Verify session access
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == device.user_id,
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get messages
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return SessionMessagesResponse(
        session_id=session_id,
        messages=[
            MessageInfo(
                id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
            )
            for m in messages
        ],
        total=len(messages),
    )


@router.post("/{session_id}/messages", response_model=MessageInfo)
async def add_message(
    session_id: str,
    request: MessageCreate,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Add a message to a session."""
    # Verify session access
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == device.user_id,
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Create message
    now = datetime.utcnow()
    message = Message(
        session_id=session_id,
        role=request.role,
        content=request.content,
        created_at=now,
    )
    db.add(message)

    # Update session metadata
    session.last_activity = now
    session.message_count += 1
    
    # Set title from first user message if not already set
    if session.title is None and request.role == "user":
        session.title = request.content[:50] + ("..." if len(request.content) > 50 else "")
    
    await db.commit()
    await db.refresh(message)

    return MessageInfo(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
    )



@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Delete a session and all its messages."""
    # Verify session access
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == device.user_id,
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(session)
    await db.commit()

    return {"status": "deleted"}


class SessionUpdate(BaseModel):
    """Request to update a session."""
    title: Optional[str] = None


@router.patch("/{session_id}", response_model=SessionInfo)
async def update_session(
    session_id: str,
    request: SessionUpdate,
    device: Device = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Update session details (e.g. title)."""
    # Verify session access
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == device.user_id,
        )
    )
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if request.title is not None:
        session.title = request.title

    await db.commit()
    await db.refresh(session)

    return SessionInfo(
        id=session.id,
        device_id=session.device_id,
        user_id=session.user_id,
        title=session.title,
        is_active=session.is_active,
        created_at=session.created_at,
        last_activity=session.last_activity,
        message_count=session.message_count,
    )
