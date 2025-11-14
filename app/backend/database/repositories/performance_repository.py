"""Repository for performance tracking."""

from typing import List, Optional
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.backend.database.models.performance import PerformanceSnapshot
from app.backend.database.repositories.base_repository import BaseRepository


class PerformanceRepository(BaseRepository[PerformanceSnapshot]):
    """Repository for performance snapshot operations."""

    def __init__(self, db: Session):
        super().__init__(PerformanceSnapshot, db)

    def create_snapshot(
        self,
        portfolio_id: int,
        snapshot_date: date,
        total_value: float,
        cash: float,
        long_value: float,
        short_value: float,
        realized_gains: float,
        unrealized_gains: float,
    ) -> PerformanceSnapshot:
        """
        Create a performance snapshot.

        Args:
            portfolio_id: Portfolio ID
            snapshot_date: Date of snapshot
            total_value: Total portfolio value
            cash: Cash balance
            long_value: Long positions value
            short_value: Short positions value
            realized_gains: Realized gains
            unrealized_gains: Unrealized gains

        Returns:
            Created snapshot
        """
        snapshot = PerformanceSnapshot(
            portfolio_id=portfolio_id,
            snapshot_date=snapshot_date,
            total_value=total_value,
            cash=cash,
            long_value=long_value,
            short_value=short_value,
            realized_gains=realized_gains,
            unrealized_gains=unrealized_gains,
        )

        self.db.add(snapshot)
        self.db.commit()
        self.db.refresh(snapshot)
        return snapshot

    def get_latest_snapshot(self, portfolio_id: int) -> Optional[PerformanceSnapshot]:
        """
        Get the most recent snapshot for a portfolio.

        Args:
            portfolio_id: Portfolio ID

        Returns:
            Latest snapshot or None
        """
        return (
            self.db.query(PerformanceSnapshot)
            .filter(PerformanceSnapshot.portfolio_id == portfolio_id)
            .order_by(desc(PerformanceSnapshot.snapshot_date))
            .first()
        )

    def get_snapshot_by_date(
        self, portfolio_id: int, snapshot_date: date
    ) -> Optional[PerformanceSnapshot]:
        """
        Get snapshot for a specific date.

        Args:
            portfolio_id: Portfolio ID
            snapshot_date: Date to query

        Returns:
            Snapshot or None
        """
        return (
            self.db.query(PerformanceSnapshot)
            .filter(
                and_(
                    PerformanceSnapshot.portfolio_id == portfolio_id,
                    PerformanceSnapshot.snapshot_date == snapshot_date,
                )
            )
            .first()
        )

    def get_snapshots_by_date_range(
        self, portfolio_id: int, start_date: date, end_date: date
    ) -> List[PerformanceSnapshot]:
        """
        Get snapshots within a date range.

        Args:
            portfolio_id: Portfolio ID
            start_date: Start date
            end_date: End date

        Returns:
            List of snapshots
        """
        return (
            self.db.query(PerformanceSnapshot)
            .filter(
                and_(
                    PerformanceSnapshot.portfolio_id == portfolio_id,
                    PerformanceSnapshot.snapshot_date >= start_date,
                    PerformanceSnapshot.snapshot_date <= end_date,
                )
            )
            .order_by(PerformanceSnapshot.snapshot_date)
            .all()
        )

    def get_recent_snapshots(
        self, portfolio_id: int, days: int = 30
    ) -> List[PerformanceSnapshot]:
        """
        Get recent snapshots for a portfolio.

        Args:
            portfolio_id: Portfolio ID
            days: Number of days to look back

        Returns:
            List of recent snapshots
        """
        start_date = date.today() - timedelta(days=days)
        return self.get_snapshots_by_date_range(portfolio_id, start_date, date.today())

    def calculate_return_since_inception(self, portfolio_id: int) -> Optional[float]:
        """
        Calculate total return since portfolio inception.

        Args:
            portfolio_id: Portfolio ID

        Returns:
            Return percentage or None
        """
        snapshots = (
            self.db.query(PerformanceSnapshot)
            .filter(PerformanceSnapshot.portfolio_id == portfolio_id)
            .order_by(PerformanceSnapshot.snapshot_date)
            .all()
        )

        if not snapshots:
            return None

        initial_value = float(snapshots[0].total_value)
        current_value = float(snapshots[-1].total_value)

        if initial_value == 0:
            return 0.0

        return ((current_value - initial_value) / initial_value) * 100

    def calculate_period_return(
        self, portfolio_id: int, start_date: date, end_date: date
    ) -> Optional[float]:
        """
        Calculate return for a specific period.

        Args:
            portfolio_id: Portfolio ID
            start_date: Period start date
            end_date: Period end date

        Returns:
            Return percentage or None
        """
        start_snapshot = self.get_snapshot_by_date(portfolio_id, start_date)
        end_snapshot = self.get_snapshot_by_date(portfolio_id, end_date)

        if not start_snapshot or not end_snapshot:
            return None

        start_value = float(start_snapshot.total_value)
        end_value = float(end_snapshot.total_value)

        if start_value == 0:
            return 0.0

        return ((end_value - start_value) / start_value) * 100
