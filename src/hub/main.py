"""Main FastAPI application for Strawberry AI Hub."""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import HUB_ROOT, settings
from .database import dispose_engine, init_db
from .logging_config import configure_logging
from .protocol import ProtocolVersionMiddleware
from .routers import (
    admin_router,
    auth_router,
    chat_router,
    device_discovery_router,
    devices_router,
    sessions_router,
    skills_router,
    websocket_router,
)
from .routers.websocket import connection_manager
from .tensorzero_gateway import get_gateway, shutdown_gateway

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    app.state.connection_manager = connection_manager

    # Startup - skip if in test mode (tables already created)
    if "pytest" not in sys.modules:
        # Load .env file from project root (ai-hub/.env) before initializing TensorZero.
        # TensorZero reads credentials from os.environ.
        project_root = Path(__file__).parent.parent.parent
        load_dotenv(project_root / ".env", override=False)

        log_file = configure_logging(
            settings.log_dir,
            settings.log_max_bytes,
            settings.log_retention_days,
            settings.debug,
            settings.uvicorn_log_level,
        )
        logger.info("Logging to %s", log_file)
        logger.info("Initializing database...")
        await init_db()
        logger.info("Initializing TensorZero gateway...")
        await get_gateway()
        logger.info("Hub ready!")

    yield

    # Shutdown - close all resources to ensure clean exit
    if "pytest" not in sys.modules:
        logger.info("Shutting down...")

    # Shutdown TensorZero gateway
    try:
        await shutdown_gateway()
    except Exception:
        logger.exception("Error while shutting down TensorZero gateway")

    # Close WebSocket connections and cancel pending requests
    try:
        manager = getattr(app.state, "connection_manager", connection_manager)
        await manager.shutdown()
    except Exception:
        logger.exception("Error while shutting down WebSocket connection manager")

    # Dispose database engine
    try:
        await dispose_engine()
    except Exception:
        logger.exception("Error while disposing database engine")


# Create FastAPI app
app = FastAPI(
    title="Strawberry AI Hub",
    description="Central server for the Strawberry AI voice assistant platform",
    version="0.1.0",
    lifespan=lifespan,
)

# Protocol version middleware — reject unsupported Spoke protocol versions
app.add_middleware(ProtocolVersionMiddleware)

# CORS middleware (allow all for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(skills_router)
app.include_router(devices_router)
app.include_router(device_discovery_router)
# Support both API-prefixed and legacy/non-prefixed session routes.
# - Frontend uses an axios client rooted at /api, so it calls /api/sessions/...
# - Tests and some clients call /sessions/...
app.include_router(sessions_router)
app.include_router(sessions_router, prefix="/api")
app.include_router(websocket_router)
app.include_router(admin_router)


# Serve frontend static files
frontend_dir = Path(__file__).parent.parent.parent / "frontend" / "dist"

if frontend_dir.exists():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="assets")


@app.get("/api/health")
async def root():
    """Root endpoint - basic info."""
    return {
        "name": "Strawberry AI Hub",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# Serve SPA - catch all other routes
# Must be defined LAST locally to avoid shadowing other routes
if os.path.exists(frontend_dir):

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Allow API calls to pass through (if they weren't caught by routers above)
        passthrough = ("api", "docs", "openapi.json")
        if full_path.startswith(passthrough):
            raise HTTPException(status_code=404)

        # Serve index.html for all other routes
        return FileResponse(os.path.join(frontend_dir, "index.html"))


def main():
    """Run the server."""
    print(f"Starting Strawberry AI Hub on {settings.host}:{settings.port}")
    reload_dirs = [str(HUB_ROOT)] if settings.debug else None
    uvicorn.run(
        "hub.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        reload_dirs=reload_dirs,
    )


if __name__ == "__main__":
    main()
