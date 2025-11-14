"""Repository for trade and realized gains management."""

from typing import List, Optional
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from app.backend.database.models.trading import Trade, RealizedGain
from app.backend.database.repositories.base_repository import BaseRepository


class TradeRepository(BaseRepository[Trade]):
    """Repository for trade operations."""

    def __init__(self, db: Session):
        super().__init__(Trade, db)

    def create_trade(
        self,
        portfolio_id: int,
        ticker: str,
        action: str,
        quantity: int,
        price: float,
        executed_at: datetime,
        decision_id: Optional[int] = None,
        commission: float = 0.0,
    ) -> Trade:
        """
        Create a new trade record.

        Args:
            portfolio_id: Portfolio ID
            ticker: Stock ticker
            action: Trade action (buy, sell, short, cover)
            quantity: Number of shares
            price: Price per share
            executed_at: Execution timestamp
            decision_id: Related decision ID
            commission: Trade commission

        Returns:
            Created trade
        """
        total_value = quantity * price + commission

        trade = Trade(
            portfolio_id=portfolio_id,
            ticker=ticker,
            action=action,
            quantity=quantity,
            price=price,
            total_value=total_value,
            commission=commission,
            executed_at=executed_at,
            decision_id=decision_id,
        )

        self.db.add(trade)
        self.db.commit()
        self.db.refresh(trade)
        return trade

    def get_portfolio_trades(
        self, portfolio_id: int, skip: int = 0, limit: int = 100
    ) -> List[Trade]:
        """
        Get all trades for a portfolio.

        Args:
            portfolio_id: Portfolio ID
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List of trades
        """
        return (
            self.db.query(Trade)
            .filter(Trade.portfolio_id == portfolio_id)
            .order_by(desc(Trade.executed_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_ticker_trades(
        self, portfolio_id: int, ticker: str, skip: int = 0, limit: int = 100
    ) -> List[Trade]:
        """
        Get all trades for a specific ticker.

        Args:
            portfolio_id: Portfolio ID
            ticker: Stock ticker
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List of trades
        """
        return (
            self.db.query(Trade)
            .filter(and_(Trade.portfolio_id == portfolio_id, Trade.ticker == ticker))
            .order_by(desc(Trade.executed_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def get_trades_by_date_range(
        self,
        portfolio_id: int,
        start_date: datetime,
        end_date: datetime,
        skip: int = 0,
        limit: int = 100,
    ) -> List[Trade]:
        """
        Get trades within a date range.

        Args:
            portfolio_id: Portfolio ID
            start_date: Start datetime
            end_date: End datetime
            skip: Number of records to skip
            limit: Maximum number of records

        Returns:
            List of trades
        """
        return (
            self.db.query(Trade)
            .filter(
                and_(
                    Trade.portfolio_id == portfolio_id,
                    Trade.executed_at >= start_date,
                    Trade.executed_at <= end_date,
                )
            )
            .order_by(desc(Trade.executed_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

    def record_realized_gain(
        self,
        portfolio_id: int,
        ticker: str,
        position_type: str,
        realized_gain: float,
        trade_id: int,
    ) -> RealizedGain:
        """
        Record a realized gain/loss.

        Args:
            portfolio_id: Portfolio ID
            ticker: Stock ticker
            position_type: Position type (long or short)
            realized_gain: Realized gain amount
            trade_id: Related trade ID

        Returns:
            Created realized gain record
        """
        gain = RealizedGain(
            portfolio_id=portfolio_id,
            ticker=ticker,
            position_type=position_type,
            realized_gain=realized_gain,
            trade_id=trade_id,
        )

        self.db.add(gain)
        self.db.commit()
        self.db.refresh(gain)
        return gain

    def get_total_realized_gains(self, portfolio_id: int) -> float:
        """
        Get total realized gains for a portfolio.

        Args:
            portfolio_id: Portfolio ID

        Returns:
            Total realized gains
        """
        result = (
            self.db.query(RealizedGain)
            .filter(RealizedGain.portfolio_id == portfolio_id)
            .all()
        )
        return sum(float(gain.realized_gain) for gain in result)

    def get_realized_gains_by_ticker(self, portfolio_id: int, ticker: str) -> float:
        """
        Get realized gains for a specific ticker.

        Args:
            portfolio_id: Portfolio ID
            ticker: Stock ticker

        Returns:
            Total realized gains for ticker
        """
        result = (
            self.db.query(RealizedGain)
            .filter(
                and_(
                    RealizedGain.portfolio_id == portfolio_id, RealizedGain.ticker == ticker
                )
            )
            .all()
        )
        return sum(float(gain.realized_gain) for gain in result)
