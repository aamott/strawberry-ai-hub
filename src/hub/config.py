"""Hub configuration using Pydantic Settings."""

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


HUB_ROOT = Path(__file__).resolve().parents[2]


def get_default_database_url() -> str:
    """Return the default database URL anchored to the hub directory.

    Returns:
        The sqlite connection URL pointing at the hub.db file in the hub root.
    """
    database_path = HUB_ROOT / "hub.db"
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"


class Settings(BaseSettings):
    """Hub configuration settings.
    
    Loads from environment variables and .env file.
    """
    
    model_config = SettingsConfigDict(
        env_file=str(HUB_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    
    # Security
    secret_key: str = Field(
        default="CHANGE-ME-IN-PRODUCTION",
        description="Secret key for JWT signing",
    )
    access_token_expire_minutes: int = 43200  # 30 days
    
    # Database
    database_url: str = Field(default_factory=get_default_database_url)
    
    # LLM
    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    default_model: str = "gpt-4o-mini"
    
    # Google AI Studio (alternative)
    google_ai_studio_api_key: Optional[str] = None
    
    # Skill Registry
    skill_expiry_seconds: int = 1800  # 30 minutes without heartbeat

    # Agent loop (online tools)
    agent_max_iterations: int = Field(
        default=5,
        ge=1,
        le=50,
        description=(
            "Maximum number of agent-loop iterations when enable_tools=true. "
            "Higher values allow multi-step tool use but may increase latency."
        ),
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        """Normalize sqlite URLs to be anchored to the hub directory.

        Args:
            value: The configured database URL.

        Returns:
            A database URL with a hub-root-relative sqlite path resolved.
        """
        sqlite_prefix = "sqlite+aiosqlite:///"
        absolute_prefix = "sqlite+aiosqlite:////"
        if value.startswith(sqlite_prefix) and not value.startswith(absolute_prefix):
            relative_path = value.split(sqlite_prefix, 1)[1]
            database_path = (HUB_ROOT / relative_path).resolve()
            return f"{sqlite_prefix}{database_path.as_posix()}"
        return value


# Global settings instance
settings = Settings()

