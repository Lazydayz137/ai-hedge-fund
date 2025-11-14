"""Decision-related models for agent decisions and signals."""

import uuid
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Date, Index, Text, UUID
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship

from app.backend.database.base import Base


class Decision(Base):
    """Decision tracking table - stores hedge fund run information."""

    __tablename__ = "decisions"
    __table_args__ = (Index("idx_decisions_run_id", "run_id"),)

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False, index=True)
    decision_date = Column(Date, nullable=False)
    tickers = Column(ARRAY(String), nullable=False)
    model_name = Column(String(50), nullable=True)
    model_provider = Column(String(50), nullable=True)
    status = Column(String(20), default="pending", nullable=False)  # pending, executing, completed, failed
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    portfolio = relationship("Portfolio", back_populates="decisions")
    agent_signals = relationship("AgentSignal", back_populates="decision", cascade="all, delete-orphan")
    portfolio_decisions = relationship("PortfolioDecision", back_populates="decision", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="decision")

    def __repr__(self):
        return f"<Decision(id={self.id}, run_id={self.run_id}, date={self.decision_date}, status='{self.status}')>"


class AgentSignal(Base):
    """Agent signals table - stores individual agent analysis and signals."""

    __tablename__ = "agent_signals"
    __table_args__ = (Index("idx_agent_signals_decision", "decision_id"),)

    id = Column(Integer, primary_key=True, index=True)
    decision_id = Column(Integer, ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False)
    agent_name = Column(String(100), nullable=False)
    ticker = Column(String(10), nullable=False)
    signal = Column(String(20), nullable=False)  # bullish, bearish, neutral
    confidence = Column(Integer, nullable=False)  # 0-100
    reasoning = Column(Text, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    decision = relationship("Decision", back_populates="agent_signals")

    def __repr__(self):
        return f"<AgentSignal(agent='{self.agent_name}', ticker='{self.ticker}', signal='{self.signal}', confidence={self.confidence})>"


class PortfolioDecision(Base):
    """Portfolio manager decisions table - stores final trading decisions."""

    __tablename__ = "portfolio_decisions"

    id = Column(Integer, primary_key=True, index=True)
    decision_id = Column(Integer, ForeignKey("decisions.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(10), nullable=False)
    action = Column(String(10), nullable=False)  # buy, sell, short, cover, hold
    quantity = Column(Integer, nullable=False)
    reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    decision = relationship("Decision", back_populates="portfolio_decisions")

    def __repr__(self):
        return f"<PortfolioDecision(ticker='{self.ticker}', action='{self.action}', quantity={self.quantity})>"
