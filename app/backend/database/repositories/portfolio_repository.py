"""Repository for portfolio and position management."""

from typing import List, Optional, Dict
from datetime import datetime
from sqlalchemy.orm import Session, joinedload

from app.backend.database.models.portfolio import Portfolio, Position
from app.backend.database.repositories.base_repository import BaseRepository


class PortfolioRepository(BaseRepository[Portfolio]):
    """Repository for portfolio operations."""

    def __init__(self, db: Session):
        super().__init__(Portfolio, db)

    def get_with_positions(self, portfolio_id: int) -> Optional[Portfolio]:
        """
        Get portfolio with all positions loaded.

        Args:
            portfolio_id: Portfolio ID

        Returns:
            Portfolio with positions or None
        """
        return (
            self.db.query(Portfolio)
            .filter(Portfolio.id == portfolio_id)
            .options(joinedload(Portfolio.positions))
            .first()
        )

    def get_by_name(self, name: str) -> Optional[Portfolio]:
        """
        Get portfolio by name.

        Args:
            name: Portfolio name

        Returns:
            Portfolio or None
        """
        return self.db.query(Portfolio).filter(Portfolio.name == name).first()

    def get_position(self, portfolio_id: int, ticker: str) -> Optional[Position]:
        """
        Get position for a specific ticker.

        Args:
            portfolio_id: Portfolio ID
            ticker: Stock ticker

        Returns:
            Position or None
        """
        return (
            self.db.query(Position)
            .filter(Position.portfolio_id == portfolio_id, Position.ticker == ticker)
            .first()
        )

    def get_all_positions(self, portfolio_id: int) -> List[Position]:
        """
        Get all positions for a portfolio.

        Args:
            portfolio_id: Portfolio ID

        Returns:
            List of positions
        """
        return self.db.query(Position).filter(Position.portfolio_id == portfolio_id).all()

    def get_active_positions(self, portfolio_id: int) -> List[Position]:
        """
        Get all active positions (with non-zero shares).

        Args:
            portfolio_id: Portfolio ID

        Returns:
            List of active positions
        """
        return (
            self.db.query(Position)
            .filter(
                Position.portfolio_id == portfolio_id,
                (Position.long_shares > 0) | (Position.short_shares > 0),
            )
            .all()
        )

    def update_position(
        self,
        portfolio_id: int,
        ticker: str,
        long_shares: Optional[int] = None,
        short_shares: Optional[int] = None,
        long_cost_basis: Optional[float] = None,
        short_cost_basis: Optional[float] = None,
        short_margin_used: Optional[float] = None,
    ) -> Position:
        """
        Update or create a position.

        Args:
            portfolio_id: Portfolio ID
            ticker: Stock ticker
            long_shares: Number of long shares
            short_shares: Number of short shares
            long_cost_basis: Long position cost basis
            short_cost_basis: Short position cost basis
            short_margin_used: Margin used for short position

        Returns:
            Updated or created position
        """
        position = self.get_position(portfolio_id, ticker)

        if position:
            # Update existing position
            if long_shares is not None:
                position.long_shares = long_shares
            if short_shares is not None:
                position.short_shares = short_shares
            if long_cost_basis is not None:
                position.long_cost_basis = long_cost_basis
            if short_cost_basis is not None:
                position.short_cost_basis = short_cost_basis
            if short_margin_used is not None:
                position.short_margin_used = short_margin_used
            position.updated_at = datetime.utcnow()
        else:
            # Create new position
            position = Position(
                portfolio_id=portfolio_id,
                ticker=ticker,
                long_shares=long_shares or 0,
                short_shares=short_shares or 0,
                long_cost_basis=long_cost_basis or 0.0,
                short_cost_basis=short_cost_basis or 0.0,
                short_margin_used=short_margin_used or 0.0,
            )
            self.db.add(position)

        self.db.commit()
        self.db.refresh(position)
        return position

    def update_cash(self, portfolio_id: int, cash_delta: float) -> Portfolio:
        """
        Update portfolio cash by delta amount.

        Args:
            portfolio_id: Portfolio ID
            cash_delta: Amount to add (positive) or subtract (negative)

        Returns:
            Updated portfolio
        """
        portfolio = self.get(portfolio_id)
        if portfolio:
            portfolio.current_cash = float(portfolio.current_cash) + cash_delta
            portfolio.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(portfolio)
        return portfolio

    def get_total_value(self, portfolio_id: int, current_prices: Dict[str, float]) -> Dict[str, float]:
        """
        Calculate total portfolio value.

        Args:
            portfolio_id: Portfolio ID
            current_prices: Dictionary of ticker -> current price

        Returns:
            Dictionary with cash, long_value, short_value, total_value
        """
        portfolio = self.get_with_positions(portfolio_id)
        if not portfolio:
            return {"cash": 0, "long_value": 0, "short_value": 0, "total_value": 0}

        long_value = 0.0
        short_value = 0.0

        for position in portfolio.positions:
            price = current_prices.get(position.ticker, 0)

            if position.long_shares > 0:
                long_value += position.long_shares * price

            if position.short_shares > 0:
                # Short value is negative (liability)
                short_value -= position.short_shares * price

        total_value = float(portfolio.current_cash) + long_value + short_value

        return {
            "cash": float(portfolio.current_cash),
            "long_value": long_value,
            "short_value": short_value,
            "total_value": total_value,
        }
