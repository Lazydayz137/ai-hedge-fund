"""Unit tests for TradeRepository."""

import pytest
from datetime import datetime, timedelta

from app.backend.database.repositories.trade_repository import TradeRepository
from app.backend.database.models.trading import Trade, RealizedGain


class TestTradeRepository:
    """Test cases for TradeRepository."""

    def test_create_trade(self, test_db, sample_portfolio, sample_decision):
        """Test creating a new trade."""
        repo = TradeRepository(test_db)

        trade = repo.create_trade(
            portfolio_id=sample_portfolio.id,
            ticker="AAPL",
            action="buy",
            quantity=10,
            price=150.00,
            executed_at=datetime.now(),
            decision_id=sample_decision.id,
            commission=1.50,
        )

        assert trade.id is not None
        assert trade.ticker == "AAPL"
        assert trade.action == "buy"
        assert trade.quantity == 10
        assert float(trade.price) == 150.00
        assert float(trade.total_value) == 1501.50  # 10 * 150 + 1.50 commission
        assert float(trade.commission) == 1.50

    def test_get_portfolio_trades(self, test_db, sample_portfolio, sample_decision):
        """Test retrieving all trades for a portfolio."""
        repo = TradeRepository(test_db)

        # Create multiple trades
        repo.create_trade(
            sample_portfolio.id, "AAPL", "buy", 10, 150.00, datetime.now(), sample_decision.id
        )
        repo.create_trade(
            sample_portfolio.id, "MSFT", "buy", 5, 300.00, datetime.now(), sample_decision.id
        )
        repo.create_trade(
            sample_portfolio.id, "NVDA", "sell", 3, 500.00, datetime.now(), sample_decision.id
        )

        trades = repo.get_portfolio_trades(sample_portfolio.id)

        assert len(trades) == 3

    def test_get_ticker_trades(self, test_db, sample_portfolio, sample_decision):
        """Test retrieving trades for a specific ticker."""
        repo = TradeRepository(test_db)

        # Create trades for different tickers
        repo.create_trade(
            sample_portfolio.id, "AAPL", "buy", 10, 150.00, datetime.now(), sample_decision.id
        )
        repo.create_trade(
            sample_portfolio.id, "AAPL", "sell", 5, 155.00, datetime.now(), sample_decision.id
        )
        repo.create_trade(
            sample_portfolio.id, "MSFT", "buy", 5, 300.00, datetime.now(), sample_decision.id
        )

        aapl_trades = repo.get_ticker_trades(sample_portfolio.id, "AAPL")

        assert len(aapl_trades) == 2
        assert all(t.ticker == "AAPL" for t in aapl_trades)

    def test_get_trades_by_date_range(self, test_db, sample_portfolio, sample_decision):
        """Test retrieving trades within a date range."""
        repo = TradeRepository(test_db)
        now = datetime.now()

        # Create trades at different times
        repo.create_trade(
            sample_portfolio.id, "AAPL", "buy", 10, 150.00, now - timedelta(days=5), sample_decision.id
        )
        repo.create_trade(
            sample_portfolio.id, "MSFT", "buy", 5, 300.00, now - timedelta(days=2), sample_decision.id
        )
        repo.create_trade(
            sample_portfolio.id, "NVDA", "sell", 3, 500.00, now, sample_decision.id
        )

        # Get trades from last 3 days
        start = now - timedelta(days=3)
        trades = repo.get_trades_by_date_range(sample_portfolio.id, start, now)

        assert len(trades) == 2  # Only MSFT and NVDA

    def test_record_realized_gain(self, test_db, sample_portfolio, sample_trade):
        """Test recording a realized gain."""
        repo = TradeRepository(test_db)

        gain = repo.record_realized_gain(
            portfolio_id=sample_portfolio.id,
            ticker="AAPL",
            position_type="long",
            realized_gain=500.00,
            trade_id=sample_trade.id,
        )

        assert gain.id is not None
        assert gain.ticker == "AAPL"
        assert gain.position_type == "long"
        assert float(gain.realized_gain) == 500.00

    def test_get_total_realized_gains(self, test_db, sample_portfolio, sample_trade):
        """Test calculating total realized gains."""
        repo = TradeRepository(test_db)

        # Record multiple gains
        repo.record_realized_gain(sample_portfolio.id, "AAPL", "long", 500.00, sample_trade.id)
        repo.record_realized_gain(sample_portfolio.id, "MSFT", "long", 300.00, sample_trade.id)
        repo.record_realized_gain(sample_portfolio.id, "NVDA", "long", -100.00, sample_trade.id)  # Loss

        total = repo.get_total_realized_gains(sample_portfolio.id)

        assert total == 700.00  # 500 + 300 - 100

    def test_get_realized_gains_by_ticker(self, test_db, sample_portfolio, sample_trade):
        """Test retrieving realized gains for a specific ticker."""
        repo = TradeRepository(test_db)

        # Record gains for different tickers
        repo.record_realized_gain(sample_portfolio.id, "AAPL", "long", 500.00, sample_trade.id)
        repo.record_realized_gain(sample_portfolio.id, "AAPL", "long", 200.00, sample_trade.id)
        repo.record_realized_gain(sample_portfolio.id, "MSFT", "long", 300.00, sample_trade.id)

        aapl_gains = repo.get_realized_gains_by_ticker(sample_portfolio.id, "AAPL")

        assert aapl_gains == 700.00  # 500 + 200

    def test_trade_ordering(self, test_db, sample_portfolio, sample_decision):
        """Test that trades are ordered by execution time descending."""
        repo = TradeRepository(test_db)
        now = datetime.now()

        # Create trades in specific order
        trade1 = repo.create_trade(
            sample_portfolio.id, "AAPL", "buy", 10, 150.00, now - timedelta(hours=2), sample_decision.id
        )
        trade2 = repo.create_trade(
            sample_portfolio.id, "MSFT", "buy", 5, 300.00, now, sample_decision.id
        )
        trade3 = repo.create_trade(
            sample_portfolio.id, "NVDA", "sell", 3, 500.00, now - timedelta(hours=1), sample_decision.id
        )

        trades = repo.get_portfolio_trades(sample_portfolio.id)

        # Should be ordered by executed_at descending (most recent first)
        assert trades[0].id == trade2.id  # Most recent
        assert trades[1].id == trade3.id
        assert trades[2].id == trade1.id  # Oldest

    def test_pagination(self, test_db, sample_portfolio, sample_decision):
        """Test pagination of trade queries."""
        repo = TradeRepository(test_db)

        # Create 10 trades
        for i in range(10):
            repo.create_trade(
                sample_portfolio.id, "AAPL", "buy", 1, 150.00, datetime.now(), sample_decision.id
            )

        # Get first 5
        page1 = repo.get_portfolio_trades(sample_portfolio.id, skip=0, limit=5)
        assert len(page1) == 5

        # Get next 5
        page2 = repo.get_portfolio_trades(sample_portfolio.id, skip=5, limit=5)
        assert len(page2) == 5

        # Ensure no overlap
        page1_ids = {t.id for t in page1}
        page2_ids = {t.id for t in page2}
        assert len(page1_ids & page2_ids) == 0
