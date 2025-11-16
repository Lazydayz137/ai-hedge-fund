#!/usr/bin/env python3
"""Initialize database with migrations and optionally create default portfolio."""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alembic.config import Config
from alembic import command
from sqlalchemy import create_engine, text

from app.backend.database.config import db_settings
from app.backend.database.session import get_db_context
from app.backend.database.repositories import PortfolioRepository
from src.utils.logging_config import setup_logging, get_logger

# Setup logging
setup_logging(level="INFO", log_to_file=False)
logger = get_logger(__name__)


def check_database_exists():
    """Check if database exists and is accessible."""
    try:
        engine = create_engine(db_settings.database_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✓ Database connection successful")
        return True
    except Exception as e:
        logger.error(f"✗ Database connection failed: {e}")
        return False


def run_migrations():
    """Run database migrations."""
    try:
        # Get alembic config
        alembic_ini_path = project_root / "alembic.ini"
        alembic_cfg = Config(str(alembic_ini_path))

        # Run upgrade
        logger.info("Running database migrations...")
        command.upgrade(alembic_cfg, "head")
        logger.info("✓ Migrations completed successfully")
        return True
    except Exception as e:
        logger.error(f"✗ Migration failed: {e}")
        return False


def create_default_portfolio(name: str = "Main Portfolio", initial_cash: float = 100000.00):
    """Create default portfolio if it doesn't exist."""
    try:
        with get_db_context() as db:
            repo = PortfolioRepository(db)

            # Check if portfolio exists
            portfolio = repo.get_by_name(name)

            if portfolio:
                logger.info(f"✓ Portfolio '{name}' already exists (ID: {portfolio.id})")
                return portfolio

            # Create new portfolio
            portfolio = repo.create(
                name=name,
                initial_cash=initial_cash,
                current_cash=initial_cash,
                margin_requirement=0.0,
            )

            logger.info(
                f"✓ Created portfolio '{name}' with ${initial_cash:,.2f} initial cash "
                f"(ID: {portfolio.id})"
            )
            return portfolio

    except Exception as e:
        logger.error(f"✗ Failed to create portfolio: {e}")
        return None


def main():
    """Main initialization function."""
    logger.info("=" * 60)
    logger.info("AI Hedge Fund - Database Initialization")
    logger.info("=" * 60)

    # Check database connection
    logger.info("\n1. Checking database connection...")
    if not check_database_exists():
        logger.error("\nInitialization failed: Cannot connect to database")
        logger.info("\nPlease check:")
        logger.info("  - PostgreSQL is running")
        logger.info("  - DATABASE_URL is correct in .env")
        logger.info(f"  - Current DATABASE_URL: {db_settings.database_url}")
        sys.exit(1)

    # Run migrations
    logger.info("\n2. Running database migrations...")
    if not run_migrations():
        logger.error("\nInitialization failed: Migration errors")
        sys.exit(1)

    # Create default portfolio (optional)
    logger.info("\n3. Setting up default portfolio...")
    portfolio = create_default_portfolio()

    if portfolio:
        logger.info("\n" + "=" * 60)
        logger.info("✓ Database initialization complete!")
        logger.info("=" * 60)
        logger.info(f"\nDefault Portfolio: {portfolio.name} (ID: {portfolio.id})")
        logger.info(f"Initial Cash: ${float(portfolio.current_cash):,.2f}")
        logger.info(f"\nDatabase URL: {db_settings.database_url}")
        logger.info("\nYou can now run the hedge fund:")
        logger.info("  poetry run python src/main.py --ticker AAPL,MSFT,NVDA")
        logger.info("\nOr start backtesting:")
        logger.info("  poetry run python src/backtester.py --ticker AAPL,MSFT,NVDA")
    else:
        logger.warning("\nWarning: Could not create default portfolio")
        logger.info("You can create one manually later")

    logger.info("")


if __name__ == "__main__":
    main()
