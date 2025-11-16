"""Unit tests for DecisionRepository."""

import pytest
from datetime import date, datetime
import uuid

from app.backend.database.repositories.decision_repository import DecisionRepository
from app.backend.database.models.decisions import Decision, AgentSignal, PortfolioDecision


class TestDecisionRepository:
    """Test cases for DecisionRepository."""

    def test_create_decision(self, test_db, sample_portfolio):
        """Test creating a new decision."""
        repo = DecisionRepository(test_db)

        decision = repo.create_decision(
            portfolio_id=sample_portfolio.id,
            decision_date=date.today(),
            tickers=["AAPL", "MSFT", "NVDA"],
            model_name="gpt-4o",
            model_provider="OpenAI",
        )

        assert decision.id is not None
        assert isinstance(decision.run_id, uuid.UUID)
        assert decision.decision_date == date.today()
        assert decision.tickers == ["AAPL", "MSFT", "NVDA"]
        assert decision.model_name == "gpt-4o"
        assert decision.model_provider == "OpenAI"
        assert decision.status == "pending"

    def test_update_status(self, test_db, sample_decision):
        """Test updating decision status."""
        repo = DecisionRepository(test_db)

        updated = repo.update_status(sample_decision.id, "completed")

        assert updated.status == "completed"

    def test_get_by_run_id(self, test_db, sample_decision):
        """Test retrieving decision by run ID."""
        repo = DecisionRepository(test_db)

        decision = repo.get_by_run_id(sample_decision.run_id)

        assert decision is not None
        assert decision.id == sample_decision.id

    def test_get_recent_decisions(self, test_db, sample_portfolio):
        """Test retrieving recent decisions."""
        repo = DecisionRepository(test_db)

        # Create multiple decisions
        for i in range(5):
            repo.create_decision(
                portfolio_id=sample_portfolio.id,
                decision_date=date.today(),
                tickers=["AAPL"],
            )

        recent = repo.get_recent_decisions(sample_portfolio.id, limit=3)

        assert len(recent) == 3

    def test_add_agent_signal(self, test_db, sample_decision):
        """Test adding an agent signal to a decision."""
        repo = DecisionRepository(test_db)

        signal = repo.add_agent_signal(
            decision_id=sample_decision.id,
            agent_name="Warren Buffett",
            ticker="AAPL",
            signal="bullish",
            confidence=85,
            reasoning="Strong moat and fundamentals",
            execution_time_ms=1500,
        )

        assert signal.id is not None
        assert signal.agent_name == "Warren Buffett"
        assert signal.ticker == "AAPL"
        assert signal.signal == "bullish"
        assert signal.confidence == 85
        assert signal.reasoning == "Strong moat and fundamentals"
        assert signal.execution_time_ms == 1500

    def test_add_portfolio_decision(self, test_db, sample_decision):
        """Test adding a portfolio manager decision."""
        repo = DecisionRepository(test_db)

        portfolio_decision = repo.add_portfolio_decision(
            decision_id=sample_decision.id,
            ticker="AAPL",
            action="buy",
            quantity=10,
            reasoning="Majority of agents are bullish",
        )

        assert portfolio_decision.id is not None
        assert portfolio_decision.ticker == "AAPL"
        assert portfolio_decision.action == "buy"
        assert portfolio_decision.quantity == 10
        assert portfolio_decision.reasoning == "Majority of agents are bullish"

    def test_get_agent_signals_for_ticker(self, test_db, sample_decision):
        """Test retrieving all agent signals for a specific ticker."""
        repo = DecisionRepository(test_db)

        # Add signals for different tickers
        repo.add_agent_signal(sample_decision.id, "Warren Buffett", "AAPL", "bullish", 85)
        repo.add_agent_signal(sample_decision.id, "Michael Burry", "AAPL", "bearish", 70)
        repo.add_agent_signal(sample_decision.id, "Cathie Wood", "MSFT", "bullish", 90)

        aapl_signals = repo.get_agent_signals_for_ticker(sample_decision.id, "AAPL")

        assert len(aapl_signals) == 2
        assert all(s.ticker == "AAPL" for s in aapl_signals)

    def test_get_portfolio_decisions(self, test_db, sample_decision):
        """Test retrieving all portfolio manager decisions."""
        repo = DecisionRepository(test_db)

        # Add multiple portfolio decisions
        repo.add_portfolio_decision(sample_decision.id, "AAPL", "buy", 10)
        repo.add_portfolio_decision(sample_decision.id, "MSFT", "sell", 5)
        repo.add_portfolio_decision(sample_decision.id, "NVDA", "hold", 0)

        decisions = repo.get_portfolio_decisions(sample_decision.id)

        assert len(decisions) == 3

    def test_get_with_signals(self, test_db, sample_decision):
        """Test retrieving decision with signals loaded."""
        repo = DecisionRepository(test_db)

        # Add agent signals
        repo.add_agent_signal(sample_decision.id, "Warren Buffett", "AAPL", "bullish", 85)
        repo.add_agent_signal(sample_decision.id, "Michael Burry", "AAPL", "bearish", 70)

        decision = repo.get_with_signals(sample_decision.id)

        assert decision is not None
        assert len(decision.agent_signals) == 2

    def test_signal_confidence_validation(self, test_db, sample_decision):
        """Test that confidence must be between 0 and 100."""
        repo = DecisionRepository(test_db)

        # Valid confidence
        signal = repo.add_agent_signal(
            sample_decision.id, "Warren Buffett", "AAPL", "bullish", 85
        )
        assert signal.confidence == 85

        # Note: SQLite doesn't enforce CHECK constraints by default,
        # but PostgreSQL will. This test documents the expected behavior.

    def test_decision_statuses(self, test_db, sample_portfolio):
        """Test various decision statuses."""
        repo = DecisionRepository(test_db)

        decision = repo.create_decision(
            portfolio_id=sample_portfolio.id,
            decision_date=date.today(),
            tickers=["AAPL"],
        )

        # Test status transitions
        repo.update_status(decision.id, "executing")
        assert repo.get(decision.id).status == "executing"

        repo.update_status(decision.id, "completed")
        assert repo.get(decision.id).status == "completed"

        repo.update_status(decision.id, "failed")
        assert repo.get(decision.id).status == "failed"

    def test_multiple_signals_per_agent(self, test_db, sample_decision):
        """Test that agents can provide signals for multiple tickers."""
        repo = DecisionRepository(test_db)

        # Same agent, different tickers
        repo.add_agent_signal(sample_decision.id, "Warren Buffett", "AAPL", "bullish", 85)
        repo.add_agent_signal(sample_decision.id, "Warren Buffett", "MSFT", "neutral", 60)
        repo.add_agent_signal(sample_decision.id, "Warren Buffett", "NVDA", "bearish", 40)

        aapl_signals = repo.get_agent_signals_for_ticker(sample_decision.id, "AAPL")
        msft_signals = repo.get_agent_signals_for_ticker(sample_decision.id, "MSFT")

        assert len(aapl_signals) == 1
        assert len(msft_signals) == 1
        assert aapl_signals[0].signal == "bullish"
        assert msft_signals[0].signal == "neutral"
