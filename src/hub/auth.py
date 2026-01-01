"""Authentication utilities for JWT tokens."""

from datetime import datetime, timedelta
from typing import Optional
import secrets
import hashlib

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import Device, get_db


# JWT settings
ALGORITHM = "HS256"

# Security scheme
security = HTTPBearer()


def generate_device_token() -> str:
    """Generate a secure random device token."""
    return secrets.token_urlsafe(16)  # Shorter token


def hash_token(token: str) -> str:
    """Hash a token for storage using SHA256."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_token(plain_token: str, hashed_token: str) -> bool:
    """Verify a token against its hash."""
    return hash_token(plain_token) == hashed_token


def create_access_token(
    device_id: str,
    user_id: str,
    device_name: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT access token for a device.
    
    Args:
        device_id: Unique device identifier
        user_id: User who owns the device
        device_name: Human-readable device name
        expires_delta: Token expiration time
        
    Returns:
        Encoded JWT token
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    
    expire = datetime.utcnow() + expires_delta
    
    to_encode = {
        "sub": device_id,
        "user_id": user_id,
        "device_name": device_name,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded token payload
        
    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_device(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Device:
    """Dependency to get the authenticated device.
    
    Args:
        credentials: Bearer token from request
        db: Database session
        
    Returns:
        Authenticated Device object
        
    Raises:
        HTTPException: If authentication fails
    """
    token = credentials.credentials
    payload = decode_token(token)
    
    device_id = payload.get("sub")
    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    
    # Get device from database
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    
    if not device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device not found",
        )
    
    if not device.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is deactivated",
        )
    
    # Update last seen
    device.last_seen = datetime.utcnow()
    await db.commit()
    
    return device

