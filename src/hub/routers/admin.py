"""Admin API router."""

import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (
    get_current_user,
    get_password_hash,
    verify_password,
    create_access_token,
)
from ..database import User, get_db

router = APIRouter(prefix="/api", tags=["admin"])


# --- Models ---

class UserCredentials(BaseModel):
    username: str
    password: str

class UserCreate(UserCredentials):
    is_admin: bool = False

class UserResponse(BaseModel):
    id: str
    username: str
    is_admin: bool
    created_at: datetime
    last_login: datetime | None = None

class Token(BaseModel):
    access_token: str
    token_type: str

class ConfigUpdate(BaseModel):
    content: str


# --- User Management ---

@router.get("/users/count", response_model=int)
async def get_user_count(db: AsyncSession = Depends(get_db)):
    """Get total number of users (open endpoint for setup check)."""
    result = await db.execute(select(func.count(User.id)))
    return result.scalar()


@router.post("/users/setup", response_model=Token)
async def setup_admin(user_in: UserCredentials, db: AsyncSession = Depends(get_db)):
    """Create the first admin user (only if no users exist)."""
    # Check if users exist
    count = await get_user_count(db)
    if count > 0:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Setup already completed",
        )
    
    # Create user
    user = User(
        id=str(uuid.uuid4()),
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
        is_admin=True,
    )
    db.add(user)
    await db.commit()
    
    # Create token
    access_token = create_access_token(
        subject=user.id,
        subject_type="user",
        name=user.username,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/users/login", response_model=Token)
async def login(user_in: UserCredentials, db: AsyncSession = Depends(get_db)):
    """Login and get access token."""
    result = await db.execute(select(User).where(User.username == user_in.username))
    user = result.scalar_one_or_none()
    
    if not user or not verify_password(user_in.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account inactive",
        )
    
    # Update last login
    user.last_login = datetime.utcnow()
    await db.commit()
    
    access_token = create_access_token(
        subject=user.id,
        subject_type="user",
        name=user.username,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Get current user info."""
    return user


@router.post("/users", response_model=UserResponse)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new user (admin only)."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")

    # Check for existing user
    result = await db.execute(select(User).where(User.username == user_in.username))
    if result.scalar_one_or_none():
         raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered"
        )

    user = User(
        id=str(uuid.uuid4()),
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
        is_admin=user_in.is_admin,
    )
    db.add(user)
    await db.commit()
    return user


@router.get("/users", response_model=List[UserResponse])
async def get_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all users."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    
    result = await db.execute(select(User))
    return result.scalars().all()


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a user."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
        
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
        
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    await db.delete(user)
    await db.commit()
    return {"status": "deleted"}


# --- Config Management ---

@router.get("/config/env")
async def get_env_config(user: User = Depends(get_current_user)):
    """Get .env file content."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
        
    try:
        with open(".env", "r") as f:
            return {"content": f.read()}
    except FileNotFoundError:
        return {"content": ""}


@router.post("/config/env")
async def update_env_config(
    config: ConfigUpdate,
    user: User = Depends(get_current_user)
):
    """Update .env file content."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
        
    # Safety check: Prevent totally breaking the app?
    # For now, just write it. User beware.
    with open(".env", "w") as f:
        f.write(config.content)
    return {"status": "updated"}


@router.get("/config/tensorzero")
async def get_tensorzero_config(user: User = Depends(get_current_user)):
    """Get tensorzero.toml content."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
        
    try:
        with open("tensorzero.toml", "r") as f:
            return {"content": f.read()}
    except FileNotFoundError:
        # Return default template if missing
        return {"content": "# tensorzero.toml\n[gateway]\n# Add configuration here\n"}



@router.post("/config/tensorzero")
async def update_tensorzero_config(
    config: ConfigUpdate,
    user: User = Depends(get_current_user)
):
    """Update tensorzero.toml content."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
        
    with open("tensorzero.toml", "w") as f:
        f.write(config.content)
        
    return {"status": "updated"}
