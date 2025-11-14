"""Database configuration settings."""

import os
from typing import Optional
from pydantic import BaseModel


class DatabaseSettings(BaseModel):
    """Database configuration settings."""

    # Database connection
    database_url: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_hedge_fund")

    # Connection pool settings
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600  # Recycle connections after 1 hour
    pool_pre_ping: bool = True  # Verify connections before using them

    # Echo SQL statements (development only)
    echo_sql: bool = os.getenv("DATABASE_ECHO", "false").lower() == "true"

    # Migration settings
    alembic_ini_path: str = "alembic.ini"

    class Config:
        env_prefix = "DATABASE_"
        case_sensitive = False


# Global settings instance
db_settings = DatabaseSettings()
