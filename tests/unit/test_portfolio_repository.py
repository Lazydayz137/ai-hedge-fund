"""Unit tests for PortfolioRepository."""

import pytest
from datetime import datetime

from app.backend.database.repositories.portfolio_repository import PortfolioRepository
from app.backend.database.models.portfolio import Portfolio, Position


class TestPortfolioRepository:
    """Test cases for PortfolioRepository."""

    def test_create_portfolio(self, test_db):
        """Test creating a new portfolio."""
        repo = PortfolioRepository(test_db)

        portfolio = repo.create(
            name="My Portfolio",
            initial_cash=50000.00,
            current_cash=50000.00,
            margin_requirement=0.5,
        )

        assert portfolio.id is not None
        assert portfolio.name == "My Portfolio"
        assert float(portfolio.initial_cash) == 50000.00
        assert float(portfolio.current_cash) == 50000.00
        assert float(portfolio.margin_requirement) == 0.5

    def test_get_portfolio(self, test_db, sample_portfolio):
        """Test retrieving a portfolio by ID."""
        repo = PortfolioRepository(test_db)

        portfolio = repo.get(sample_portfolio.id)

        assert portfolio is not None
        assert portfolio.id == sample_portfolio.id
        assert portfolio.name == "Test Portfolio"

    def test_get_portfolio_by_name(self, test_db, sample_portfolio):
        """Test retrieving a portfolio by name."""
        repo = PortfolioRepository(test_db)

        portfolio = repo.get_by_name("Test Portfolio")

        assert portfolio is not None
        assert portfolio.id == sample_portfolio.id

    def test_get_nonexistent_portfolio(self, test_db):
        """Test retrieving a non-existent portfolio."""
        repo = PortfolioRepository(test_db)

        portfolio = repo.get(999)

        assert portfolio is None

    def test_update_cash(self, test_db, sample_portfolio):
        """Test updating portfolio cash balance."""
        repo = PortfolioRepository(test_db)
        initial_cash = float(sample_portfolio.current_cash)

        # Add cash
        repo.update_cash(sample_portfolio.id, 5000.00)
        portfolio = repo.get(sample_portfolio.id)
        assert float(portfolio.current_cash) == initial_cash + 5000.00

        # Subtract cash
        repo.update_cash(sample_portfolio.id, -3000.00)
        portfolio = repo.get(sample_portfolio.id)
        assert float(portfolio.current_cash) == initial_cash + 5000.00 - 3000.00

    def test_create_position(self, test_db, sample_portfolio):
        """Test creating a new position."""
        repo = PortfolioRepository(test_db)

        position = repo.update_position(
            portfolio_id=sample_portfolio.id,
            ticker="MSFT",
            long_shares=50,
            long_cost_basis=300.00,
        )

        assert position is not None
        assert position.ticker == "MSFT"
        assert position.long_shares == 50
        assert float(position.long_cost_basis) == 300.00

    def test_update_existing_position(self, test_db, sample_portfolio, sample_position):
        """Test updating an existing position."""
        repo = PortfolioRepository(test_db)

        # Update the position
        updated = repo.update_position(
            portfolio_id=sample_portfolio.id,
            ticker="AAPL",
            long_shares=150,
            long_cost_basis=155.00,
        )

        assert updated.id == sample_position.id
        assert updated.long_shares == 150
        assert float(updated.long_cost_basis) == 155.00

    def test_get_position(self, test_db, sample_portfolio, sample_position):
        """Test retrieving a position."""
        repo = PortfolioRepository(test_db)

        position = repo.get_position(sample_portfolio.id, "AAPL")

        assert position is not None
        assert position.id == sample_position.id
        assert position.ticker == "AAPL"

    def test_get_all_positions(self, test_db, sample_portfolio):
        """Test retrieving all positions for a portfolio."""
        repo = PortfolioRepository(test_db)

        # Create multiple positions
        repo.update_position(sample_portfolio.id, "AAPL", long_shares=100)
        repo.update_position(sample_portfolio.id, "MSFT", long_shares=50)
        repo.update_position(sample_portfolio.id, "NVDA", short_shares=25)

        positions = repo.get_all_positions(sample_portfolio.id)

        assert len(positions) == 3
        tickers = [p.ticker for p in positions]
        assert "AAPL" in tickers
        assert "MSFT" in tickers
        assert "NVDA" in tickers

    def test_get_active_positions(self, test_db, sample_portfolio):
        """Test retrieving only active positions."""
        repo = PortfolioRepository(test_db)

        # Create positions
        repo.update_position(sample_portfolio.id, "AAPL", long_shares=100)
        repo.update_position(sample_portfolio.id, "MSFT", long_shares=0)  # Inactive
        repo.update_position(sample_portfolio.id, "NVDA", short_shares=25)

        active = repo.get_active_positions(sample_portfolio.id)

        assert len(active) == 2
        tickers = [p.ticker for p in active]
        assert "AAPL" in tickers
        assert "NVDA" in tickers
        assert "MSFT" not in tickers

    def test_get_total_value(self, test_db, sample_portfolio):
        """Test calculating total portfolio value."""
        repo = PortfolioRepository(test_db)

        # Create positions
        repo.update_position(sample_portfolio.id, "AAPL", long_shares=100)
        repo.update_position(sample_portfolio.id, "MSFT", long_shares=50)

        current_prices = {"AAPL": 150.00, "MSFT": 300.00}

        value = repo.get_total_value(sample_portfolio.id, current_prices)

        # 100000 cash + 100*150 + 50*300 = 100000 + 15000 + 15000 = 130000
        assert value["cash"] == 100000.00
        assert value["long_value"] == 30000.00
        assert value["short_value"] == 0.0
        assert value["total_value"] == 130000.00

    def test_get_total_value_with_short(self, test_db, sample_portfolio):
        """Test calculating total portfolio value with short positions."""
        repo = PortfolioRepository(test_db)

        # Update cash
        repo.update_cash(sample_portfolio.id, -5000)  # Reduce cash

        # Create positions (long and short)
        repo.update_position(sample_portfolio.id, "AAPL", long_shares=100)
        repo.update_position(sample_portfolio.id, "TSLA", short_shares=20)

        current_prices = {"AAPL": 150.00, "TSLA": 200.00}

        value = repo.get_total_value(sample_portfolio.id, current_prices)

        # 95000 cash + 100*150 - 20*200 = 95000 + 15000 - 4000 = 106000
        assert value["cash"] == 95000.00
        assert value["long_value"] == 15000.00
        assert value["short_value"] == -4000.00
        assert value["total_value"] == 106000.00

    def test_get_with_positions(self, test_db, sample_portfolio):
        """Test retrieving portfolio with positions loaded."""
        repo = PortfolioRepository(test_db)

        # Create positions
        repo.update_position(sample_portfolio.id, "AAPL", long_shares=100)
        repo.update_position(sample_portfolio.id, "MSFT", long_shares=50)

        portfolio = repo.get_with_positions(sample_portfolio.id)

        assert portfolio is not None
        assert len(portfolio.positions) == 2

    def test_position_properties(self, test_db, sample_portfolio):
        """Test position model properties."""
        repo = PortfolioRepository(test_db)

        position = repo.update_position(
            sample_portfolio.id, "AAPL", long_shares=100, short_shares=25
        )

        assert position.net_shares == 75  # 100 - 25
        assert position.has_position is True

        # Position with no shares
        empty = repo.update_position(
            sample_portfolio.id, "TSLA", long_shares=0, short_shares=0
        )
        assert empty.has_position is False
