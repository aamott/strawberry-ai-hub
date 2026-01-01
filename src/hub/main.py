"""Main FastAPI application for Strawberry AI Hub."""

import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from .config import settings
from .database import init_db
from .routers import auth_router, chat_router, skills_router, devices_router


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


@app.get("/")
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

