"""Performance tracking models."""

from datetime import datetime, date
from sqlalchemy import Column, Integer, Numeric, DateTime, ForeignKey, Date, UniqueConstraint, Index
from sqlalchemy.orm import relationship

from app.backend.database.base import Base


class PerformanceSnapshot(Base):
    """Performance snapshots table - daily portfolio performance tracking."""

    __tablename__ = "performance_snapshots"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "snapshot_date", name="uq_portfolio_snapshot_date"),
        Index("idx_performance_date", "portfolio_id", "snapshot_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    snapshot_date = Column(Date, nullable=False)
    total_value = Column(Numeric(15, 2), nullable=False)
    cash = Column(Numeric(15, 2), nullable=False)
    long_value = Column(Numeric(15, 2), nullable=False)
    short_value = Column(Numeric(15, 2), nullable=False)
    realized_gains = Column(Numeric(15, 2), nullable=False)
    unrealized_gains = Column(Numeric(15, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    portfolio = relationship("Portfolio", back_populates="performance_snapshots")

    def __repr__(self):
        return f"<PerformanceSnapshot(date={self.snapshot_date}, total_value={self.total_value})>"

    @property
    def total_gains(self) -> float:
        """Total gains (realized + unrealized)."""
        return float(self.realized_gains) + float(self.unrealized_gains)

    @property
    def return_pct(self) -> float:
        """Return percentage since inception."""
        initial_value = float(self.cash) - float(self.total_gains)
        if initial_value == 0:
            return 0.0
        return (float(self.total_gains) / initial_value) * 100
