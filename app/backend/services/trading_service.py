"""Trading service for managing trades and portfolio state."""

from datetime import datetime, date
from typing import Dict, List, Optional
import uuid

from sqlalchemy.orm import Session

from app.backend.database.repositories import (
    PortfolioRepository,
    TradeRepository,
    DecisionRepository,
    PerformanceRepository,
)
from app.backend.database.models.portfolio import Portfolio, Position
from app.backend.database.models.trading import Trade
from app.backend.database.models.decisions import Decision
from src.utils.errors import (
    InsufficientFundsError,
    InsufficientSharesError,
    PositionLimitError,
    PortfolioNotFoundError,
)
from src.utils.logging_config import get_logger, log_trade, log_error

logger = get_logger(__name__)


class TradingService:
    """Service for handling trading operations with database persistence."""

    def __init__(
        self,
        db: Session,
        max_position_pct: float = 0.20,  # 20% max per position
        min_cash_reserve_pct: float = 0.10,  # 10% cash reserve
    ):
        """
        Initialize trading service.

        Args:
            db: Database session
            max_position_pct: Maximum position size as percentage of portfolio
            min_cash_reserve_pct: Minimum cash reserve as percentage
        """
        self.db = db
        self.portfolio_repo = PortfolioRepository(db)
        self.trade_repo = TradeRepository(db)
        self.decision_repo = DecisionRepository(db)
        self.performance_repo = PerformanceRepository(db)
        self.max_position_pct = max_position_pct
        self.min_cash_reserve_pct = min_cash_reserve_pct

    def get_or_create_portfolio(
        self, name: str, initial_cash: float = 100000.00, margin_requirement: float = 0.0
    ) -> Portfolio:
        """
        Get existing portfolio or create new one.

        Args:
            name: Portfolio name
            initial_cash: Initial cash balance
            margin_requirement: Margin requirement (0.5 = 50%)

        Returns:
            Portfolio instance
        """
        portfolio = self.portfolio_repo.get_by_name(name)

        if not portfolio:
            logger.info(f"Creating new portfolio: {name} with ${initial_cash:,.2f}")
            portfolio = self.portfolio_repo.create(
                name=name,
                initial_cash=initial_cash,
                current_cash=initial_cash,
                margin_requirement=margin_requirement,
            )

        return portfolio

    def execute_trade(
        self,
        portfolio_id: int,
        ticker: str,
        action: str,
        quantity: int,
        price: float,
        decision_id: Optional[int] = None,
        commission: float = 0.0,
    ) -> Trade:
        """
        Execute a trade with validation and persistence.

        Args:
            portfolio_id: Portfolio ID
            ticker: Stock ticker
            action: Trade action (buy, sell, short, cover)
            quantity: Number of shares
            price: Price per share
            decision_id: Related decision ID
            commission: Trade commission

        Returns:
            Created trade record

        Raises:
            InsufficientFundsError: Not enough cash
            InsufficientSharesError: Not enough shares to sell
            PositionLimitError: Would exceed position limits
        """
        portfolio = self.portfolio_repo.get(portfolio_id)
        if not portfolio:
            raise PortfolioNotFoundError(portfolio_id=portfolio_id)

        # Validate trade
        self._validate_trade(portfolio, ticker, action, quantity, price, commission)

        # Execute trade logic
        executed_at = datetime.now()

        if action == "buy":
            self._execute_buy(portfolio, ticker, quantity, price, commission)
        elif action == "sell":
            self._execute_sell(portfolio, ticker, quantity, price, commission)
        elif action == "short":
            self._execute_short(portfolio, ticker, quantity, price, commission)
        elif action == "cover":
            self._execute_cover(portfolio, ticker, quantity, price, commission)
        else:
            raise ValueError(f"Invalid action: {action}")

        # Record trade
        trade = self.trade_repo.create_trade(
            portfolio_id=portfolio_id,
            ticker=ticker,
            action=action,
            quantity=quantity,
            price=price,
            executed_at=executed_at,
            decision_id=decision_id,
            commission=commission,
        )

        log_trade(logger, portfolio_id, ticker, action, quantity, price)

        return trade

    def _validate_trade(
        self,
        portfolio: Portfolio,
        ticker: str,
        action: str,
        quantity: int,
        price: float,
        commission: float,
    ):
        """Validate trade before execution."""
        total_cost = quantity * price + commission

        if action == "buy":
            # Check sufficient funds
            available_cash = float(portfolio.current_cash)
            min_reserve = float(portfolio.initial_cash) * self.min_cash_reserve_pct

            if available_cash - total_cost < min_reserve:
                raise InsufficientFundsError(
                    required=total_cost + min_reserve,
                    available=available_cash,
                    ticker=ticker,
                )

            # Check position limit
            position = self.portfolio_repo.get_position(portfolio.id, ticker)
            current_value = 0
            if position:
                current_value = position.long_shares * price

            new_value = current_value + total_cost
            max_value = float(portfolio.initial_cash) * self.max_position_pct

            if new_value > max_value:
                raise PositionLimitError(
                    ticker=ticker, requested=new_value, limit=max_value
                )

        elif action == "sell":
            # Check sufficient shares
            position = self.portfolio_repo.get_position(portfolio.id, ticker)
            if not position or position.long_shares < quantity:
                available = position.long_shares if position else 0
                raise InsufficientSharesError(
                    ticker=ticker, requested=quantity, available=available
                )

    def _execute_buy(
        self, portfolio: Portfolio, ticker: str, quantity: int, price: float, commission: float
    ):
        """Execute buy trade."""
        total_cost = quantity * price + commission

        # Update cash
        self.portfolio_repo.update_cash(portfolio.id, -total_cost)

        # Update position
        position = self.portfolio_repo.get_position(portfolio.id, ticker)

        if position:
            # Calculate new average cost basis
            old_shares = position.long_shares
            old_cost_basis = float(position.long_cost_basis)
            new_shares = quantity
            total_shares = old_shares + new_shares

            total_old_cost = old_cost_basis * old_shares
            new_cost_basis = (total_old_cost + total_cost) / total_shares

            self.portfolio_repo.update_position(
                portfolio.id,
                ticker,
                long_shares=total_shares,
                long_cost_basis=new_cost_basis,
            )
        else:
            # Create new position
            self.portfolio_repo.update_position(
                portfolio.id, ticker, long_shares=quantity, long_cost_basis=price
            )

    def _execute_sell(
        self, portfolio: Portfolio, ticker: str, quantity: int, price: float, commission: float
    ):
        """Execute sell trade."""
        position = self.portfolio_repo.get_position(portfolio.id, ticker)

        # Calculate realized gain
        avg_cost = float(position.long_cost_basis)
        realized_gain = (price - avg_cost) * quantity

        # Update cash
        proceeds = quantity * price - commission
        self.portfolio_repo.update_cash(portfolio.id, proceeds)

        # Update position
        new_shares = position.long_shares - quantity
        self.portfolio_repo.update_position(
            portfolio.id, ticker, long_shares=new_shares
        )

        # Record realized gain (will be done after trade is created)
        # Store in position for now

    def _execute_short(
        self, portfolio: Portfolio, ticker: str, quantity: int, price: float, commission: float
    ):
        """Execute short trade."""
        proceeds = quantity * price
        margin_required = proceeds * float(portfolio.margin_requirement)

        # Update cash (get proceeds minus commission, post margin)
        net_cash_change = proceeds - margin_required - commission
        self.portfolio_repo.update_cash(portfolio.id, net_cash_change)

        # Update position
        position = self.portfolio_repo.get_position(portfolio.id, ticker)

        if position:
            new_short_shares = position.short_shares + quantity
            self.portfolio_repo.update_position(
                portfolio.id,
                ticker,
                short_shares=new_short_shares,
                short_cost_basis=price,
                short_margin_used=margin_required,
            )
        else:
            self.portfolio_repo.update_position(
                portfolio.id,
                ticker,
                short_shares=quantity,
                short_cost_basis=price,
                short_margin_used=margin_required,
            )

    def _execute_cover(
        self, portfolio: Portfolio, ticker: str, quantity: int, price: float, commission: float
    ):
        """Execute cover (close short) trade."""
        position = self.portfolio_repo.get_position(portfolio.id, ticker)

        # Calculate realized gain (inverse for short)
        avg_cost = float(position.short_cost_basis)
        realized_gain = (avg_cost - price) * quantity

        # Update cash (pay to cover + commission, release margin)
        cost = quantity * price + commission
        margin_released = float(position.short_margin_used) * (
            quantity / position.short_shares
        )
        net_cash_change = -cost + margin_released

        self.portfolio_repo.update_cash(portfolio.id, net_cash_change)

        # Update position
        new_short_shares = position.short_shares - quantity
        new_margin = (
            float(position.short_margin_used) - margin_released
            if new_short_shares > 0
            else 0
        )

        self.portfolio_repo.update_position(
            portfolio.id,
            ticker,
            short_shares=new_short_shares,
            short_margin_used=new_margin,
        )

    def create_decision(
        self,
        portfolio_id: int,
        tickers: List[str],
        model_name: str,
        model_provider: str,
        decision_date: Optional[date] = None,
    ) -> Decision:
        """
        Create a new decision record.

        Args:
            portfolio_id: Portfolio ID
            tickers: List of tickers analyzed
            model_name: LLM model name
            model_provider: LLM provider
            decision_date: Date of decision (defaults to today)

        Returns:
            Created decision
        """
        if decision_date is None:
            decision_date = date.today()

        decision = self.decision_repo.create_decision(
            portfolio_id=portfolio_id,
            decision_date=decision_date,
            tickers=tickers,
            model_name=model_name,
            model_provider=model_provider,
        )

        logger.info(
            f"Created decision {decision.id} for {', '.join(tickers)} using {model_name}",
            extra={"decision_id": decision.id},
        )

        return decision

    def record_agent_signals(
        self, decision_id: int, signals: List[Dict]
    ):
        """
        Record agent signals for a decision.

        Args:
            decision_id: Decision ID
            signals: List of signal dicts with agent_name, ticker, signal, confidence, reasoning
        """
        for signal_data in signals:
            self.decision_repo.add_agent_signal(
                decision_id=decision_id,
                agent_name=signal_data.get("agent_name"),
                ticker=signal_data.get("ticker"),
                signal=signal_data.get("signal"),
                confidence=signal_data.get("confidence"),
                reasoning=signal_data.get("reasoning"),
                execution_time_ms=signal_data.get("execution_time_ms"),
            )

    def create_performance_snapshot(
        self, portfolio_id: int, current_prices: Dict[str, float]
    ):
        """
        Create a daily performance snapshot.

        Args:
            portfolio_id: Portfolio ID
            current_prices: Dictionary of ticker -> current price
        """
        # Get portfolio value
        value = self.portfolio_repo.get_total_value(portfolio_id, current_prices)

        # Get realized gains
        total_realized = self.trade_repo.get_total_realized_gains(portfolio_id)

        # Calculate unrealized gains
        portfolio = self.portfolio_repo.get_with_positions(portfolio_id)
        unrealized = 0.0

        for position in portfolio.positions:
            price = current_prices.get(position.ticker, 0)

            if position.long_shares > 0:
                unrealized += (price - float(position.long_cost_basis)) * position.long_shares

            if position.short_shares > 0:
                unrealized += (float(position.short_cost_basis) - price) * position.short_shares

        # Create snapshot
        snapshot = self.performance_repo.create_snapshot(
            portfolio_id=portfolio_id,
            snapshot_date=date.today(),
            total_value=value["total_value"],
            cash=value["cash"],
            long_value=value["long_value"],
            short_value=value["short_value"],
            realized_gains=total_realized,
            unrealized_gains=unrealized,
        )

        logger.info(
            f"Created performance snapshot: Total=${value['total_value']:,.2f}, "
            f"Realized=${total_realized:,.2f}, Unrealized=${unrealized:,.2f}",
            extra={"portfolio_id": portfolio_id},
        )

        return snapshot

    def get_portfolio_summary(self, portfolio_id: int, current_prices: Dict[str, float]) -> Dict:
        """
        Get comprehensive portfolio summary.

        Args:
            portfolio_id: Portfolio ID
            current_prices: Current prices for all tickers

        Returns:
            Dictionary with portfolio state and performance
        """
        portfolio = self.portfolio_repo.get_with_positions(portfolio_id)
        if not portfolio:
            raise PortfolioNotFoundError(portfolio_id=portfolio_id)

        value = self.portfolio_repo.get_total_value(portfolio_id, current_prices)
        latest_snapshot = self.performance_repo.get_latest_snapshot(portfolio_id)

        return {
            "portfolio_id": portfolio.id,
            "name": portfolio.name,
            "cash": value["cash"],
            "long_value": value["long_value"],
            "short_value": value["short_value"],
            "total_value": value["total_value"],
            "initial_value": float(portfolio.initial_cash),
            "positions": [
                {
                    "ticker": p.ticker,
                    "long_shares": p.long_shares,
                    "short_shares": p.short_shares,
                    "long_cost_basis": float(p.long_cost_basis),
                    "short_cost_basis": float(p.short_cost_basis),
                    "current_price": current_prices.get(p.ticker, 0),
                }
                for p in portfolio.positions
                if p.has_position
            ],
            "return_pct": latest_snapshot.return_pct if latest_snapshot else 0.0,
        }
