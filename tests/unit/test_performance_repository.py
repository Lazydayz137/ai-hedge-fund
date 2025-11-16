"""Unit tests for PerformanceRepository."""

import pytest
from datetime import date, timedelta

from app.backend.database.repositories.performance_repository import PerformanceRepository
from app.backend.database.models.performance import PerformanceSnapshot


class TestPerformanceRepository:
    """Test cases for PerformanceRepository."""

    def test_create_snapshot(self, test_db, sample_portfolio):
        """Test creating a performance snapshot."""
        repo = PerformanceRepository(test_db)

        snapshot = repo.create_snapshot(
            portfolio_id=sample_portfolio.id,
            snapshot_date=date.today(),
            total_value=105000.00,
            cash=95000.00,
            long_value=15000.00,
            short_value=-5000.00,
            realized_gains=1000.00,
            unrealized_gains=4000.00,
        )

        assert snapshot.id is not None
        assert snapshot.snapshot_date == date.today()
        assert float(snapshot.total_value) == 105000.00
        assert float(snapshot.cash) == 95000.00
        assert float(snapshot.long_value) == 15000.00
        assert float(snapshot.short_value) == -5000.00
        assert float(snapshot.realized_gains) == 1000.00
        assert float(snapshot.unrealized_gains) == 4000.00

    def test_get_latest_snapshot(self, test_db, sample_portfolio):
        """Test retrieving the most recent snapshot."""
        repo = PerformanceRepository(test_db)
        today = date.today()

        # Create snapshots on different days
        repo.create_snapshot(
            sample_portfolio.id, today - timedelta(days=2), 100000, 100000, 0, 0, 0, 0
        )
        repo.create_snapshot(
            sample_portfolio.id, today - timedelta(days=1), 102000, 98000, 4000, 0, 0, 2000
        )
        latest_snapshot = repo.create_snapshot(
            sample_portfolio.id, today, 105000, 95000, 10000, 0, 0, 5000
        )

        retrieved = repo.get_latest_snapshot(sample_portfolio.id)

        assert retrieved.id == latest_snapshot.id
        assert retrieved.snapshot_date == today

    def test_get_snapshot_by_date(self, test_db, sample_portfolio):
        """Test retrieving a snapshot for a specific date."""
        repo = PerformanceRepository(test_db)
        target_date = date.today() - timedelta(days=5)

        snapshot = repo.create_snapshot(
            sample_portfolio.id, target_date, 100000, 100000, 0, 0, 0, 0
        )

        retrieved = repo.get_snapshot_by_date(sample_portfolio.id, target_date)

        assert retrieved is not None
        assert retrieved.id == snapshot.id
        assert retrieved.snapshot_date == target_date

    def test_get_snapshots_by_date_range(self, test_db, sample_portfolio):
        """Test retrieving snapshots within a date range."""
        repo = PerformanceRepository(test_db)
        today = date.today()

        # Create snapshots over 10 days
        for i in range(10):
            snapshot_date = today - timedelta(days=i)
            repo.create_snapshot(
                sample_portfolio.id, snapshot_date, 100000, 100000, 0, 0, 0, 0
            )

        # Get snapshots from last 5 days
        start_date = today - timedelta(days=4)
        snapshots = repo.get_snapshots_by_date_range(sample_portfolio.id, start_date, today)

        assert len(snapshots) == 5
        # Should be ordered by date ascending
        assert snapshots[0].snapshot_date == start_date
        assert snapshots[-1].snapshot_date == today

    def test_get_recent_snapshots(self, test_db, sample_portfolio):
        """Test retrieving recent snapshots."""
        repo = PerformanceRepository(test_db)
        today = date.today()

        # Create snapshots over 45 days
        for i in range(45):
            snapshot_date = today - timedelta(days=i)
            repo.create_snapshot(
                sample_portfolio.id, snapshot_date, 100000, 100000, 0, 0, 0, 0
            )

        # Get last 30 days
        recent = repo.get_recent_snapshots(sample_portfolio.id, days=30)

        assert len(recent) == 30

    def test_calculate_return_since_inception(self, test_db, sample_portfolio):
        """Test calculating total return since inception."""
        repo = PerformanceRepository(test_db)
        today = date.today()

        # Initial value: 100,000
        repo.create_snapshot(
            sample_portfolio.id, today - timedelta(days=30), 100000, 100000, 0, 0, 0, 0
        )

        # Current value: 110,000 (10% gain)
        repo.create_snapshot(
            sample_portfolio.id, today, 110000, 95000, 15000, 0, 5000, 5000
        )

        return_pct = repo.calculate_return_since_inception(sample_portfolio.id)

        assert return_pct == pytest.approx(10.0, rel=0.01)  # 10% return

    def test_calculate_period_return(self, test_db, sample_portfolio):
        """Test calculating return for a specific period."""
        repo = PerformanceRepository(test_db)
        today = date.today()
        start = today - timedelta(days=10)
        end = today

        # Start value: 100,000
        repo.create_snapshot(
            sample_portfolio.id, start, 100000, 100000, 0, 0, 0, 0
        )

        # End value: 105,000 (5% gain)
        repo.create_snapshot(
            sample_portfolio.id, end, 105000, 95000, 10000, 0, 2000, 3000
        )

        return_pct = repo.calculate_period_return(sample_portfolio.id, start, end)

        assert return_pct == pytest.approx(5.0, rel=0.01)  # 5% return

    def test_snapshot_properties(self, test_db, sample_portfolio):
        """Test snapshot model properties."""
        repo = PerformanceRepository(test_db)

        snapshot = repo.create_snapshot(
            portfolio_id=sample_portfolio.id,
            snapshot_date=date.today(),
            total_value=110000.00,
            cash=95000.00,
            long_value=15000.00,
            short_value=0.0,
            realized_gains=3000.00,
            unrealized_gains=7000.00,
        )

        # Test total_gains property
        assert snapshot.total_gains == pytest.approx(10000.00)  # 3000 + 7000

        # Test return_pct property (gains / (cash - gains))
        # Initial: 95000 - 10000 = 85000
        # Return: 10000 / 85000 * 100 = 11.76%
        assert snapshot.return_pct == pytest.approx(11.76, rel=0.01)

    def test_zero_initial_value_return(self, test_db, sample_portfolio):
        """Test return calculation with zero initial value."""
        repo = PerformanceRepository(test_db)

        snapshot = repo.create_snapshot(
            portfolio_id=sample_portfolio.id,
            snapshot_date=date.today(),
            total_value=0.0,
            cash=0.0,
            long_value=0.0,
            short_value=0.0,
            realized_gains=0.0,
            unrealized_gains=0.0,
        )

        # Should handle division by zero
        assert snapshot.return_pct == 0.0

    def test_negative_returns(self, test_db, sample_portfolio):
        """Test calculating negative returns."""
        repo = PerformanceRepository(test_db)
        today = date.today()

        # Start: 100,000
        repo.create_snapshot(
            sample_portfolio.id, today - timedelta(days=7), 100000, 100000, 0, 0, 0, 0
        )

        # End: 90,000 (-10% loss)
        repo.create_snapshot(
            sample_portfolio.id, today, 90000, 95000, 5000, -10000, -5000, -5000
        )

        return_pct = repo.calculate_period_return(
            sample_portfolio.id, today - timedelta(days=7), today
        )

        assert return_pct == pytest.approx(-10.0, rel=0.01)

    def test_unique_constraint(self, test_db, sample_portfolio):
        """Test that duplicate snapshots for same date are prevented."""
        repo = PerformanceRepository(test_db)
        today = date.today()

        # Create first snapshot
        repo.create_snapshot(
            sample_portfolio.id, today, 100000, 100000, 0, 0, 0, 0
        )

        # Attempting to create duplicate should raise error
        # Note: SQLite may not enforce this, but PostgreSQL will
        with pytest.raises(Exception):
            repo.create_snapshot(
                sample_portfolio.id, today, 105000, 105000, 0, 0, 0, 0
            )

    def test_no_snapshots_return(self, test_db, sample_portfolio):
        """Test return calculation with no snapshots."""
        repo = PerformanceRepository(test_db)

        return_pct = repo.calculate_return_since_inception(sample_portfolio.id)

        assert return_pct is None
