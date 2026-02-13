"""Authentication utilities for JWT tokens."""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import Device, User, get_db

logger = logging.getLogger(__name__)

# JWT settings
ALGORITHM = "HS256"

# Security scheme
security = HTTPBearer()

# Header used by Spokes to identify themselves when sharing a token.
DEVICE_ID_HEADER = "X-Device-Id"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return _bcrypt.checkpw(
        plain_password.encode("utf-8"), hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    """Generate password hash."""
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")


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

    expire = datetime.now(timezone.utc) + expires_delta

    to_encode = {
        "sub": subject,
        "type": subject_type,
        "name": name,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
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


async def _resolve_device_token(
    payload: dict,
    db: AsyncSession,
    device_id_override: Optional[str] = None,
) -> Device:
    """Resolve a device-type JWT to a Device row.

    Supports two modes:
    1. **Legacy (single-device token):** JWT ``sub`` is the device ID.
    2. **Multi-device token:** The caller passes ``device_id_override``
       (from the ``X-Device-Id`` header). The JWT ``sub`` device is used
       to determine the owning ``user_id``, and the override device is
       looked up and verified to belong to the same user.

    Args:
        payload: Decoded JWT payload.
        db: Database session.
        device_id_override: Optional device ID from X-Device-Id header.

    Returns:
        The resolved Device.

    Raises:
        HTTPException: On auth/lookup failures.
    """
    jwt_device_id = payload.get("sub")
    if not jwt_device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    # Look up the device that the JWT was originally issued for.
    result = await db.execute(select(Device).where(Device.id == jwt_device_id))
    jwt_device = result.scalar_one_or_none()

    if not jwt_device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Device not found",
        )

    if not jwt_device.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is deactivated",
        )

    # If no override, use the JWT device directly (legacy path).
    if not device_id_override or device_id_override == jwt_device_id:
        jwt_device.last_seen = datetime.now(timezone.utc)
        await db.commit()
        return jwt_device

    # Override present: look up the target device and verify ownership.
    result = await db.execute(
        select(Device).where(Device.id == device_id_override)
    )
    target_device = result.scalar_one_or_none()

    if not target_device:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Device '{device_id_override}' not found",
        )

    if target_device.user_id != jwt_device.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device does not belong to your account",
        )

    if not target_device.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is deactivated",
        )

    target_device.last_seen = datetime.now(timezone.utc)
    await db.commit()
    return target_device


async def get_current_device(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> Device:
    """Dependency to get the authenticated device.

    Supports:
    - Device tokens (JWT sub = device_id), with optional X-Device-Id
      header override for multi-device-per-token scenarios.
    - User tokens (Dashboard) — returns a virtual Dashboard device.
    """
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except HTTPException:
        raise  # Re-raise validation errors

    token_type = payload.get("type")

    # Case 1: Device Token
    if token_type == "device":
        device_id_header = request.headers.get(DEVICE_ID_HEADER)
        return await _resolve_device_token(payload, db, device_id_header)

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
        dashboard_device_id = f"dashboard-{user_id}"

        result = await db.execute(
            select(Device).where(Device.id == dashboard_device_id)
        )
        device = result.scalar_one_or_none()

        if not device:
            dummy_hash = get_password_hash("internal-dashboard-access")
            device = Device(
                id=dashboard_device_id,
                name="Strawberry Dashboard",
                user_id=user_id,
                hashed_token=dummy_hash,
                is_active=True,
                last_seen=datetime.now(timezone.utc),
            )
            db.add(device)
            await db.commit()
        else:
            device.last_seen = datetime.now(timezone.utc)

        return device

    # Case 3: Invalid Type
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token type: {token_type}",
        )


async def get_user_id_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> tuple[str, str]:
    """Extract the owning user_id and token's device_id from a device JWT.

    Used by the registration endpoint which doesn't need a specific
    device context — it just needs to know which user is registering.

    Returns:
        Tuple of (user_id, jwt_device_id).
    """
    token = credentials.credentials
    payload = decode_token(token)
    token_type = payload.get("type")

    if token_type == "device":
        device_id = payload.get("sub")
        if not device_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        result = await db.execute(select(Device).where(Device.id == device_id))
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Device not found",
            )
        return (device.user_id, device.id)

    elif token_type == "user":
        user_id = payload.get("sub")
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or inactive user",
            )
        return (user_id, "")

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
