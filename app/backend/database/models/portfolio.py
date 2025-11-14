"""Portfolio and Position models."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from app.backend.database.base import Base


class Portfolio(Base):
    """Portfolio tracking table - represents a trading portfolio."""

    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    initial_cash = Column(Numeric(15, 2), nullable=False)
    current_cash = Column(Numeric(15, 2), nullable=False)
    margin_requirement = Column(Numeric(5, 4), default=0.0)
    margin_used = Column(Numeric(15, 2), default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    positions = relationship("Position", back_populates="portfolio", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="portfolio", cascade="all, delete-orphan")
    decisions = relationship("Decision", back_populates="portfolio", cascade="all, delete-orphan")
    performance_snapshots = relationship("PerformanceSnapshot", back_populates="portfolio", cascade="all, delete-orphan")
    realized_gains = relationship("RealizedGain", back_populates="portfolio", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Portfolio(id={self.id}, name='{self.name}', cash={self.current_cash})>"


class Position(Base):
    """Position tracking table - represents current holdings."""

    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("portfolio_id", "ticker", name="uq_portfolio_ticker"),)

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(10), nullable=False, index=True)
    long_shares = Column(Integer, default=0)
    short_shares = Column(Integer, default=0)
    long_cost_basis = Column(Numeric(15, 4), default=0.0)
    short_cost_basis = Column(Numeric(15, 4), default=0.0)
    short_margin_used = Column(Numeric(15, 2), default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    portfolio = relationship("Portfolio", back_populates="positions")

    def __repr__(self):
        return f"<Position(ticker='{self.ticker}', long={self.long_shares}, short={self.short_shares})>"

    @property
    def net_shares(self) -> int:
        """Net position (long - short)."""
        return self.long_shares - self.short_shares

    @property
    def has_position(self) -> bool:
        """Check if position exists."""
        return self.long_shares > 0 or self.short_shares > 0
