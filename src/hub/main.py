"""Main FastAPI application for Strawberry AI Hub."""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from .config import settings
from .database import init_db
from .routers import (
    auth_router,
    chat_router,
    skills_router,
    devices_router,
    websocket_router,
    admin_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup - skip if in test mode (tables already created)
    import os
    if "pytest" not in sys.modules:
        print("Initializing database...")
        await init_db()
        print("Hub ready!")
    
    yield
    
    # Shutdown
    if "pytest" not in sys.modules:
        print("Shutting down...")


# Create FastAPI app
app = FastAPI(
    title="Strawberry AI Hub",
    description="Central server for the Strawberry AI voice assistant platform",
    version="0.1.0",
    lifespan=lifespan,
)

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
app.include_router(websocket_router)
app.include_router(admin_router)


from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Serve frontend static files
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")

if os.path.exists(frontend_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")

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
        if full_path.startswith("api") or full_path.startswith("docs") or full_path.startswith("openapi.json"):
             raise HTTPException(status_code=404)
        
        # Serve index.html for all other routes
        return FileResponse(os.path.join(frontend_dir, "index.html"))


def main():
    """Run the server."""
    print(f"Starting Strawberry AI Hub on {settings.host}:{settings.port}")
    uvicorn.run(
        "hub.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()

