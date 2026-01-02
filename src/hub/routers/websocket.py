"""WebSocket endpoint for device connections."""

import asyncio
import logging
import uuid
from typing import Dict, Any
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import Device, get_db
from ..auth import decode_token

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
        if not self.is_connected(device_id):
            raise ValueError(f"Device {device_id} is not connected")
        
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        
        # Create future for response
        future = asyncio.Future()
        self._pending_requests[request_id] = future
        
        try:
            # Send request
            websocket = self._connections[device_id]
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
            self._pending_requests.pop(request_id, None)
    
    async def handle_skill_response(self, response: dict):
        """Handle a skill response from a device.
        
        Args:
            response: Response message with request_id, success, result/error
        """
        request_id = response.get("request_id")
        if not request_id:
            logger.warning("Received skill response without request_id")
            return
        
        future = self._pending_requests.get(request_id)
        if not future:
            logger.warning(f"Received response for unknown request {request_id}")
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


# Global connection manager instance
connection_manager = ConnectionManager()


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
    db: AsyncSession = Depends(get_db),
):
    """WebSocket endpoint for device connections.
    
    Devices connect to this endpoint and maintain a persistent connection.
    The Hub can push skill execution requests to devices via this connection.
    
    Query params:
        token: JWT authentication token
    """
    # Authenticate
    device = await get_device_from_token(websocket, token, db)
    
    # Accept connection
    await websocket.accept()
    
    # Register connection
    await connection_manager.connect(device.id, websocket)
    
    # Update last_seen
    device.last_seen = datetime.utcnow()
    await db.commit()
    
    try:
        # Listen for messages
        while True:
            message = await websocket.receive_json()
            
            # Handle different message types
            msg_type = message.get("type")
            
            if msg_type == "skill_response":
                # Response to a skill execution request
                await connection_manager.handle_skill_response(message)
            
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
        await connection_manager.disconnect(device.id)
