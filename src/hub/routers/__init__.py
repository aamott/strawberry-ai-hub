"""API routers for the Hub."""

from .auth import router as auth_router
from .chat import router as chat_router
from .skills import router as skills_router
from .devices import router as devices_router
from .device_discovery import router as device_discovery_router
from .sessions import router as sessions_router
from .websocket import router as websocket_router
from .admin import router as admin_router

__all__ = [
    "auth_router",
    "chat_router",
    "skills_router",
    "devices_router",
    "device_discovery_router",
    "sessions_router",
    "websocket_router",
    "admin_router",
]

