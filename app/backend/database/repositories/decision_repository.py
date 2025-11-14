"""Repository for decision and agent signal management."""

from typing import List, Optional
import uuid
from datetime import date, datetime
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, desc

from app.backend.database.models.decisions import Decision, AgentSignal, PortfolioDecision
from app.backend.database.repositories.base_repository import BaseRepository


class DecisionRepository(BaseRepository[Decision]):
    """Repository for decision operations."""

    def __init__(self, db: Session):
        super().__init__(Decision, db)

    def create_decision(
        self,
        portfolio_id: int,
        decision_date: date,
        tickers: List[str],
        model_name: Optional[str] = None,
        model_provider: Optional[str] = None,
    ) -> Decision:
        """
        Create a new decision record.

        Args:
            portfolio_id: Portfolio ID
            decision_date: Date of decision
            tickers: List of tickers analyzed
            model_name: LLM model name
            model_provider: LLM provider

        Returns:
            Created decision
        """
        decision = Decision(
            portfolio_id=portfolio_id,
            run_id=uuid.uuid4(),
            decision_date=decision_date,
            tickers=tickers,
            model_name=model_name,
            model_provider=model_provider,
            status="pending",
        )

        self.db.add(decision)
        self.db.commit()
        self.db.refresh(decision)
        return decision

    def update_status(self, decision_id: int, status: str) -> Optional[Decision]:
        """
        Update decision status.

        Args:
            decision_id: Decision ID
            status: New status (pending, executing, completed, failed)

        Returns:
            Updated decision or None
        """
        return self.update(decision_id, status=status)

    def get_with_signals(self, decision_id: int) -> Optional[Decision]:
        """
        Get decision with all agent signals loaded.

        Args:
            decision_id: Decision ID

        Returns:
            Decision with signals or None
        """
        return (
            self.db.query(Decision)
            .filter(Decision.id == decision_id)
            .options(joinedload(Decision.agent_signals))
            .first()
        )

    def get_by_run_id(self, run_id: uuid.UUID) -> Optional[Decision]:
        """
        Get decision by run ID.

        Args:
            run_id: Run UUID

        Returns:
            Decision or None
        """
        return self.db.query(Decision).filter(Decision.run_id == run_id).first()

    def get_recent_decisions(
        self, portfolio_id: int, limit: int = 10
    ) -> List[Decision]:
        """
        Get recent decisions for a portfolio.

        Args:
            portfolio_id: Portfolio ID
            limit: Maximum number of decisions

        Returns:
            List of recent decisions
        """
        return (
            self.db.query(Decision)
            .filter(Decision.portfolio_id == portfolio_id)
            .order_by(desc(Decision.created_at))
            .limit(limit)
            .all()
        )

    def add_agent_signal(
        self,
        decision_id: int,
        agent_name: str,
        ticker: str,
        signal: str,
        confidence: int,
        reasoning: Optional[str] = None,
        execution_time_ms: Optional[int] = None,
    ) -> AgentSignal:
        """
        Add an agent signal to a decision.

        Args:
            decision_id: Decision ID
            agent_name: Name of the agent
            ticker: Stock ticker
            signal: Signal type (bullish, bearish, neutral)
            confidence: Confidence level (0-100)
            reasoning: Agent's reasoning
            execution_time_ms: Execution time in milliseconds

        Returns:
            Created agent signal
        """
        agent_signal = AgentSignal(
            decision_id=decision_id,
            agent_name=agent_name,
            ticker=ticker,
            signal=signal,
            confidence=confidence,
            reasoning=reasoning,
            execution_time_ms=execution_time_ms,
        )

        self.db.add(agent_signal)
        self.db.commit()
        self.db.refresh(agent_signal)
        return agent_signal

    def add_portfolio_decision(
        self,
        decision_id: int,
        ticker: str,
        action: str,
        quantity: int,
        reasoning: Optional[str] = None,
    ) -> PortfolioDecision:
        """
        Add a portfolio manager decision.

        Args:
            decision_id: Decision ID
            ticker: Stock ticker
            action: Action (buy, sell, short, cover, hold)
            quantity: Number of shares
            reasoning: Decision reasoning

        Returns:
            Created portfolio decision
        """
        portfolio_decision = PortfolioDecision(
            decision_id=decision_id,
            ticker=ticker,
            action=action,
            quantity=quantity,
            reasoning=reasoning,
        )

        self.db.add(portfolio_decision)
        self.db.commit()
        self.db.refresh(portfolio_decision)
        return portfolio_decision

    def get_agent_signals_for_ticker(
        self, decision_id: int, ticker: str
    ) -> List[AgentSignal]:
        """
        Get all agent signals for a specific ticker in a decision.

        Args:
            decision_id: Decision ID
            ticker: Stock ticker

        Returns:
            List of agent signals
        """
        return (
            self.db.query(AgentSignal)
            .filter(
                and_(AgentSignal.decision_id == decision_id, AgentSignal.ticker == ticker)
            )
            .all()
        )

    def get_portfolio_decisions(self, decision_id: int) -> List[PortfolioDecision]:
        """
        Get all portfolio manager decisions for a decision.

        Args:
            decision_id: Decision ID

        Returns:
            List of portfolio decisions
        """
        return (
            self.db.query(PortfolioDecision)
            .filter(PortfolioDecision.decision_id == decision_id)
            .all()
        )
