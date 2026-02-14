"""WebSocket endpoint for device connections."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import decode_token
from ..database import Device, Skill, get_db
from ..protocol import PROTOCOL_VERSION_HEADER, SUPPORTED_VERSIONS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


class ConnectionManager:
    """Manages active WebSocket connections for devices.

    Tracks connections by device_id and provides methods for:
    - Adding/removing connections
    - Sending skill requests to devices
    - Broadcasting messages
    """

    def __init__(self):
        # Map device_id -> WebSocket connection
        self._connections: Dict[str, WebSocket] = {}
        # Map request_id -> Future for pending skill requests
        self._pending_requests: Dict[str, asyncio.Future] = {}
        # Map request_id -> target device_id for cleanup on disconnect
        self._request_device_ids: Dict[str, str] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    async def connect(self, device_id: str, websocket: WebSocket):
        """Register a new device connection.

        Args:
            device_id: Device identifier
            websocket: WebSocket connection
        """
        async with self._lock:
            # Close existing connection if any
            if device_id in self._connections:
                old_ws = self._connections[device_id]
                try:
                    await old_ws.close()
                except Exception:
                    pass

            self._connections[device_id] = websocket
            logger.info(f"Device {device_id} connected via WebSocket")

    async def disconnect(self, device_id: str):
        """Unregister a device connection.

        Args:
            device_id: Device identifier
        """
        async with self._lock:
            if device_id in self._connections:
                del self._connections[device_id]
                logger.info(f"Device {device_id} disconnected")

            # Fail any in-flight requests targeting this device immediately
            # instead of waiting for per-request timeout.
            for request_id, target_device_id in list(self._request_device_ids.items()):
                if target_device_id != device_id:
                    continue
                future = self._pending_requests.get(request_id)
                if future and not future.done():
                    future.set_exception(
                        ConnectionError(
                            f"Device {device_id} disconnected before replying"
                        )
                    )
                self._pending_requests.pop(request_id, None)
                self._request_device_ids.pop(request_id, None)

    def is_connected(self, device_id: str) -> bool:
        """Check if a device is currently connected.

        Args:
            device_id: Device identifier

        Returns:
            True if connected, False otherwise
        """
        return device_id in self._connections

    async def send_skill_request(
        self,
        device_id: str,
        skill_name: str,
        method_name: str,
        args: list,
        kwargs: dict,
        timeout: float = 30.0,
    ) -> Any:
        """Send a skill execution request to a device and wait for response.

        Args:
            device_id: Target device identifier
            skill_name: Skill class name
            method_name: Method name to call
            args: Positional arguments
            kwargs: Keyword arguments
            timeout: Maximum time to wait for response (seconds)

        Returns:
            Result from skill execution

        Raises:
            ValueError: If device is not connected
            TimeoutError: If device doesn't respond in time
            RuntimeError: If skill execution fails
        """
        # Generate unique request ID
        request_id = str(uuid.uuid4())

        # Atomically resolve the socket and register the pending future.
        async with self._lock:
            websocket = self._connections.get(device_id)
            if websocket is None:
                raise ValueError(f"Device {device_id} is not connected")
            future = asyncio.get_running_loop().create_future()
            self._pending_requests[request_id] = future
            self._request_device_ids[request_id] = device_id

        try:
            # Send request
            message = {
                "type": "skill_request",
                "request_id": request_id,
                "skill_name": skill_name,
                "method_name": method_name,
                "args": args,
                "kwargs": kwargs,
            }

            await websocket.send_json(message)
            logger.debug(f"Sent skill request {request_id} to device {device_id}")

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            logger.error(f"Skill request {request_id} timed out after {timeout}s")
            raise TimeoutError(f"Device {device_id} did not respond in time")

        finally:
            # Clean up pending request
            async with self._lock:
                self._pending_requests.pop(request_id, None)
                self._request_device_ids.pop(request_id, None)

    async def handle_skill_response(self, response: dict):
        """Handle a skill response from a device.

        Args:
            response: Response message with request_id, success, result/error
        """
        request_id = response.get("request_id")
        if not request_id:
            logger.warning("Received skill response without request_id")
            return

        async with self._lock:
            future = self._pending_requests.get(request_id)
            if not future:
                logger.warning(f"Received response for unknown request {request_id}")
                return

            if future.done():
                logger.debug(
                    f"Received response for already-completed request {request_id}"
                )
                return

            # Resolve the future
            if response.get("success"):
                future.set_result(response.get("result"))
            else:
                error = response.get("error", "Unknown error")
                future.set_exception(RuntimeError(error))

    def get_connected_devices(self) -> list[str]:
        """Get list of currently connected device IDs.

        Returns:
            List of device IDs
        """
        return list(self._connections.keys())

    async def shutdown(self) -> None:
        """Gracefully shutdown all connections and cancel pending requests.

        This should be called during application shutdown to ensure clean exit.
        """
        logger.info("Shutting down WebSocket connection manager...")

        # Cancel all pending futures
        for request_id, future in list(self._pending_requests.items()):
            if not future.done():
                future.cancel()
        self._pending_requests.clear()
        self._request_device_ids.clear()

        # Close all WebSocket connections
        for device_id, websocket in list(self._connections.items()):
            try:
                await websocket.close(code=1001, reason="Server shutdown")
                logger.debug(f"Closed WebSocket for device {device_id}")
            except Exception as e:
                logger.debug(f"Error closing WebSocket for {device_id}: {e}")
        self._connections.clear()

        logger.info("WebSocket connection manager shutdown complete")


# Global connection manager instance
connection_manager = ConnectionManager()


def get_connection_manager(request: Request) -> ConnectionManager:
    """Return the Hub connection manager from application state."""
    manager = getattr(request.app.state, "connection_manager", None)
    if manager is None:
        raise RuntimeError("Connection manager is not configured on app.state")
    return manager


def get_ws_connection_manager(websocket: WebSocket) -> ConnectionManager:
    """Return the Hub connection manager for WebSocket handlers."""
    manager = getattr(websocket.app.state, "connection_manager", None)
    if manager is None:
        raise RuntimeError("Connection manager is not configured on app.state")
    return manager


def _resolve_ws_protocol_version(websocket: WebSocket) -> str | None:
    """Resolve protocol version declared by the WebSocket client.

    Supports both:
    - HTTP header: X-Protocol-Version
    - Query param: protocol_version

    If both are present and disagree, raises HTTPException.

    Args:
        websocket: Incoming WebSocket connection.

    Returns:
        The declared protocol version, or ``None`` if omitted.

    Raises:
        HTTPException: If header/query versions conflict.
    """
    header_version = websocket.headers.get(PROTOCOL_VERSION_HEADER)
    query_version = websocket.query_params.get("protocol_version")

    if header_version and query_version and header_version != query_version:
        raise HTTPException(
            status_code=400,
            detail=(
                "Conflicting protocol versions between "
                f"{PROTOCOL_VERSION_HEADER}='{header_version}' and "
                f"query protocol_version='{query_version}'"
            ),
        )

    return header_version or query_version


async def get_device_from_token(
    websocket: WebSocket,
    token: str,
    db: AsyncSession,
) -> Device:
    """Authenticate device from WebSocket token parameter.

    Args:
        websocket: WebSocket connection
        token: JWT token
        db: Database session

    Returns:
        Authenticated Device

    Raises:
        HTTPException: If authentication fails
    """
    try:
        # Decode token
        payload = decode_token(token)
        device_id = payload.get("sub")

        if not device_id:
            await websocket.close(code=1008, reason="Invalid token payload")
            raise HTTPException(status_code=401, detail="Invalid token")

        # Look up device
        result = await db.execute(select(Device).where(Device.id == device_id))
        device = result.scalar_one_or_none()

        if not device or not device.is_active:
            await websocket.close(code=1008, reason="Device not found or inactive")
            raise HTTPException(status_code=401, detail="Device not found")

        return device

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"WebSocket authentication error: {e}")
        await websocket.close(code=1008, reason="Authentication failed")
        raise HTTPException(status_code=401, detail="Authentication failed")


@router.websocket("/device")
async def websocket_device_endpoint(
    websocket: WebSocket,
    token: str,
    device_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    manager: ConnectionManager = Depends(get_ws_connection_manager),
):
    """WebSocket endpoint for device connections.

    Devices connect to this endpoint and maintain a persistent connection.
    The Hub can push skill execution requests to devices via this connection.

    Query params:
        token: JWT authentication token
        device_id: Optional Hub-assigned device ID (overrides JWT device).
            Used when multiple Spokes share one auth token.
        protocol_version: Optional wire protocol version (e.g., v1).
    """
    # Validate wire protocol version when provided.
    try:
        version = _resolve_ws_protocol_version(websocket)
    except HTTPException as exc:
        await websocket.close(code=1008, reason=exc.detail)
        return

    if version is not None and version not in SUPPORTED_VERSIONS:
        await websocket.close(
            code=1008,
            reason=(
                f"Unsupported protocol version: {version}. "
                f"Supported: {', '.join(sorted(SUPPORTED_VERSIONS))}"
            ),
        )
        return

    # Authenticate via JWT
    device = await get_device_from_token(websocket, token, db)

    # If a device_id override is provided, look it up and verify ownership.
    if device_id and device_id != device.id:
        result = await db.execute(select(Device).where(Device.id == device_id))
        target = result.scalar_one_or_none()
        if target and target.user_id == device.user_id and target.is_active:
            device = target
        else:
            logger.warning(
                "WebSocket device_id override %s denied for JWT device %s",
                device_id,
                device.id,
            )
            await websocket.close(code=1008, reason="Invalid device_id override")
            return

    # Accept connection
    await websocket.accept()

    # Register connection
    await manager.connect(device.id, websocket)

    # Update last_seen
    device.last_seen = datetime.now(timezone.utc)
    await db.commit()

    try:
        # Listen for messages
        while True:
            message = await websocket.receive_json()

            # Handle different message types
            msg_type = message.get("type")

            if msg_type == "skill_response":
                # Response to a skill execution request
                await manager.handle_skill_response(message)

            elif msg_type == "ping":
                # Heartbeat ping
                await websocket.send_json({"type": "pong"})

            else:
                logger.warning(f"Unknown message type from {device.id}: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"Device {device.id} disconnected")

    except Exception as e:
        logger.error(f"WebSocket error for device {device.id}: {e}")

    finally:
        # Unregister connection
        await manager.disconnect(device.id)

        # Remove stale skills — the Spoke re-registers them on reconnect.
        try:
            await db.execute(delete(Skill).where(Skill.device_id == device.id))
            await db.commit()
        except Exception:
            logger.exception("Failed to clean up skills for device %s", device.id)
