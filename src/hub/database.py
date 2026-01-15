"""Database setup and models."""

from datetime import datetime
from typing import Optional
from sqlalchemy import text
from sqlalchemy import String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Device(Base):
    """Registered device (Spoke)."""
    
    __tablename__ = "devices"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    
    # Authentication
    hashed_token: Mapped[str] = mapped_column(String(255))
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    skills: Mapped[list["Skill"]] = relationship(back_populates="device", cascade="all, delete-orphan")


class Skill(Base):
    """Registered skill from a device."""
    
    __tablename__ = "skills"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    
    # Skill info
    class_name: Mapped[str] = mapped_column(String(255))
    function_name: Mapped[str] = mapped_column(String(255))
    signature: Mapped[str] = mapped_column(Text)
    docstring: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Status
    last_heartbeat: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    device: Mapped["Device"] = relationship(back_populates="skills")


class Session(Base):
    """Conversation session."""
    
    __tablename__ = "sessions"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    
    # Cached metadata (updated on message insert to avoid N+1 queries)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message_count: Mapped[int] = mapped_column(default=0)
    
    # Mode tracking for tool execution (online/offline)
    # Tracks which mode prompt was last sent to avoid duplicates when
    # conversations switch between Hub (online) and Spoke (offline) execution
    last_mode_prompt: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_activity: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    messages: Mapped[list["Message"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Message(Base):
    """Message in a conversation session."""
    
    __tablename__ = "messages"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    
    # Content
    role: Mapped[str] = mapped_column(String(32))  # user, assistant, system
    content: Mapped[str] = mapped_column(Text)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    session: Mapped["Session"] = relationship(back_populates="messages")


class User(Base):
    """Admin user."""
    
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    
    # Permissions
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


# Database engine and session factory (created lazily)
_engine = None
_session_factory = None


def get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, echo=settings.debug)
    return _engine


def get_session_factory():
    """Get or create the session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db():
    """Initialize database tables."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Lightweight schema migration for existing SQLite databases.
        # The project uses create_all (no Alembic), so we must handle the case
        # where hub.db was created before new columns were added.
        try:
            result = await conn.execute(text("PRAGMA table_info(sessions)"))
            existing_cols = {row[1] for row in result.fetchall()}

            if "title" not in existing_cols:
                await conn.execute(text("ALTER TABLE sessions ADD COLUMN title VARCHAR(255)"))

            if "message_count" not in existing_cols:
                await conn.execute(
                    text(
                        "ALTER TABLE sessions "
                        "ADD COLUMN message_count INTEGER NOT NULL DEFAULT 0"
                    )
                )
            
            if "last_mode_prompt" not in existing_cols:
                await conn.execute(
                    text("ALTER TABLE sessions ADD COLUMN last_mode_prompt VARCHAR(32)")
                )
        except Exception:
            # Best-effort: if PRAGMA/ALTER fails (non-SQLite, permissions, etc.),
            # allow startup to proceed and surface errors during normal operations.
            pass


async def get_db() -> AsyncSession:
    """Dependency to get database session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose the global SQLAlchemy engine (if created)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def reset_engine():
    """Reset engine for testing - allows reconfiguration."""
    global _engine, _session_factory
    if _engine is not None:
        try:
            _engine.sync_engine.dispose()
        except Exception:
            pass
    _engine = None
    _session_factory = None


# For backwards compatibility
@property
def engine():
    return get_engine()

