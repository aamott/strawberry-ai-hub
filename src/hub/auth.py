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
import bcrypt as _bcrypt
from .database import Device, User, get_db


# JWT settings
ALGORITHM = "HS256"

# Security scheme
security = HTTPBearer()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return _bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def get_password_hash(password: str) -> str:
    """Generate password hash."""
    return _bcrypt.hashpw(password.encode('utf-8'), _bcrypt.gensalt()).decode('utf-8')


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
    subject: str,
    subject_type: str,  # "device" or "user"
    name: str,
    expires_delta: Optional[timedelta] = None,
    extra_claims: dict = None,
) -> str:
    """Create a JWT access token.
    
    Args:
        subject: Unique identifier (device_id or user_id)
        subject_type: Type of subject ("device" or "user")
        name: Human-readable name
        expires_delta: Token expiration time
        extra_claims: Additional claims to include
        
    Returns:
        Encoded JWT token
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    
    expire = datetime.utcnow() + expires_delta
    
    to_encode = {
        "sub": subject,
        "type": subject_type,
        "name": name,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    
    if extra_claims:
        to_encode.update(extra_claims)
    
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
    
    If the token is a USER token (e.g. from Dashboard), returns a virtual
    'Dashboard' device linked to that user to allow chat/admin actions.
    """
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except HTTPException:
        raise # Re-raise validation errors
    
    token_type = payload.get("type")
    
    # Case 1: Standard Device Token
    if token_type == "device":
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

    # Case 2: User Token (Dashboard/Admin access)
    elif token_type == "user":
        user_id = payload.get("sub")
        
        # Verify user validity
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or inactive user",
            )

        # Find or create specific 'Dashboard' device for this user
        # We use a deterministic ID so it persists
        dashboard_device_id = f"dashboard-{user_id}"
        
        result = await db.execute(select(Device).where(Device.id == dashboard_device_id))
        device = result.scalar_one_or_none()
        
        if not device:
            # Create the virtual dashboard device
            # It needs a hashed_token, but we won't use it for auth (we use User token)
            # We just need a placeholder that verifies (conceptually)
            dummy_hash = get_password_hash("internal-dashboard-access")
            
            device = Device(
                id=dashboard_device_id,
                name="Strawberry Dashboard",
                user_id=user_id,
                hashed_token=dummy_hash, 
                is_active=True,
                last_seen=datetime.utcnow()
            )
            db.add(device)
            await db.commit()
        else:
            # Update last seen
            device.last_seen = datetime.utcnow()
            # await db.commit() # Not strictly necessary every time, but keeps last_seen fresh
            
        return device

    # Case 3: Invalid Type
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type: {token_type}",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency to get the authenticated user."""
    token = credentials.credentials
    payload = decode_token(token)
    
    if payload.get("type") != "user":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type (user expected)",
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user token",
        )
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
        
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )
        
    return user

