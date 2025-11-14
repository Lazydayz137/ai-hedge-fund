"""Trading-related models."""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.backend.database.base import Base


class Trade(Base):
    """Trade history table - immutable audit trail of all trades."""

    __tablename__ = "trades"
    __table_args__ = (
        Index("idx_trades_portfolio_ticker", "portfolio_id", "ticker"),
        Index("idx_trades_executed_at", "executed_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(10), nullable=False)
    action = Column(String(10), nullable=False)  # buy, sell, short, cover
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(15, 4), nullable=False)
    total_value = Column(Numeric(15, 2), nullable=False)
    commission = Column(Numeric(10, 2), default=0.0)
    executed_at = Column(DateTime, nullable=False)
    decision_id = Column(Integer, ForeignKey("decisions.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    portfolio = relationship("Portfolio", back_populates="trades")
    decision = relationship("Decision", back_populates="trades")

    def __repr__(self):
        return f"<Trade(ticker='{self.ticker}', action='{self.action}', quantity={self.quantity}, price={self.price})>"


class RealizedGain(Base):
    """Realized gains table - for tax reporting."""

    __tablename__ = "realized_gains"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(10), nullable=False)
    position_type = Column(String(10), nullable=False)  # long or short
    realized_gain = Column(Numeric(15, 2), nullable=False)
    trade_id = Column(Integer, ForeignKey("trades.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    portfolio = relationship("Portfolio", back_populates="realized_gains")
    trade = relationship("Trade")

    def __repr__(self):
        return f"<RealizedGain(ticker='{self.ticker}', type='{self.position_type}', gain={self.realized_gain})>"
