"""Pytest configuration and fixtures."""

import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import date, datetime

from app.backend.database.base import Base
from app.backend.database.models import (
    Portfolio,
    Position,
    Trade,
    RealizedGain,
    Decision,
    AgentSignal,
    PortfolioDecision,
    PerformanceSnapshot,
)

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_engine():
    """Create a test database engine."""
    engine = create_engine(TEST_DATABASE_URL, echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def test_db(test_engine):
    """Create a test database session."""
    TestSessionLocal = sessionmaker(bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def sample_portfolio(test_db):
    """Create a sample portfolio for testing."""
    portfolio = Portfolio(
        name="Test Portfolio",
        initial_cash=100000.00,
        current_cash=100000.00,
        margin_requirement=0.5,
        margin_used=0.0,
    )
    test_db.add(portfolio)
    test_db.commit()
    test_db.refresh(portfolio)
    return portfolio


@pytest.fixture
def sample_position(test_db, sample_portfolio):
    """Create a sample position for testing."""
    position = Position(
        portfolio_id=sample_portfolio.id,
        ticker="AAPL",
        long_shares=100,
        short_shares=0,
        long_cost_basis=150.00,
        short_cost_basis=0.0,
        short_margin_used=0.0,
    )
    test_db.add(position)
    test_db.commit()
    test_db.refresh(position)
    return position


@pytest.fixture
def sample_decision(test_db, sample_portfolio):
    """Create a sample decision for testing."""
    decision = Decision(
        portfolio_id=sample_portfolio.id,
        decision_date=date.today(),
        tickers=["AAPL", "MSFT", "NVDA"],
        model_name="gpt-4o",
        model_provider="OpenAI",
        status="pending",
    )
    test_db.add(decision)
    test_db.commit()
    test_db.refresh(decision)
    return decision


@pytest.fixture
def sample_trade(test_db, sample_portfolio, sample_decision):
    """Create a sample trade for testing."""
    trade = Trade(
        portfolio_id=sample_portfolio.id,
        ticker="AAPL",
        action="buy",
        quantity=10,
        price=150.00,
        total_value=1500.00,
        commission=0.0,
        executed_at=datetime.now(),
        decision_id=sample_decision.id,
    )
    test_db.add(trade)
    test_db.commit()
    test_db.refresh(trade)
    return trade
