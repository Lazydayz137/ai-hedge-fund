"""System-related models for logging and configuration."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from sqlalchemy.dialects.postgresql import JSONB

from app.backend.database.base import Base


class SystemLog(Base):
    """System logs table - for monitoring and debugging."""

    __tablename__ = "system_logs"
    __table_args__ = (
        Index("idx_logs_created", "created_at"),
        Index("idx_logs_level", "level"),
    )

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(20), nullable=False)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    component = Column(String(100), nullable=True)
    message = Column(Text, nullable=False)
    context = Column(JSONB, nullable=True)  # Additional context as JSON
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<SystemLog(level='{self.level}', component='{self.component}', message='{self.message[:50]}...')>"


class Setting(Base):
    """Settings table - for configuration management."""

    __tablename__ = "settings"

    key = Column(String(100), primary_key=True)
    value = Column(JSONB, nullable=False)
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Setting(key='{self.key}', description='{self.description}')>"
