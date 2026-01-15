"""Hub configuration using Pydantic Settings."""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Hub configuration settings.
    
    Loads from environment variables and .env file.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
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
    database_url: str = "sqlite+aiosqlite:///./hub.db"
    
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


# Global settings instance
settings = Settings()

