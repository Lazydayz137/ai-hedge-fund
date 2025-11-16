"""Structured logging configuration for AI Hedge Fund."""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
import json


class StructuredFormatter(logging.Formatter):
    """Custom formatter that outputs structured JSON logs."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add custom fields from extra
        if hasattr(record, "portfolio_id"):
            log_data["portfolio_id"] = record.portfolio_id
        if hasattr(record, "ticker"):
            log_data["ticker"] = record.ticker
        if hasattr(record, "agent"):
            log_data["agent"] = record.agent
        if hasattr(record, "decision_id"):
            log_data["decision_id"] = record.decision_id
        if hasattr(record, "trade_id"):
            log_data["trade_id"] = record.trade_id

        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """Colored formatter for console output."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format with colors for terminal output."""
        levelname = record.levelname
        if levelname in self.COLORS:
            colored_levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
            record.levelname = colored_levelname

        return super().format(record)


def setup_logging(
    level: str = "INFO",
    log_to_file: bool = True,
    log_to_console: bool = True,
    log_dir: Optional[Path] = None,
    structured: bool = False,
) -> logging.Logger:
    """
    Set up structured logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Whether to log to file
        log_to_console: Whether to log to console
        log_dir: Directory for log files (default: logs/)
        structured: Use structured JSON logging

    Returns:
        Configured root logger
    """
    # Get root logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    logger.handlers = []

    # Console handler
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level.upper()))

        if structured:
            console_formatter = StructuredFormatter()
        else:
            console_formatter = ColoredFormatter(
                "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

    # File handler
    if log_to_file:
        if log_dir is None:
            log_dir = Path("logs")

        log_dir.mkdir(exist_ok=True)

        # Create log file with timestamp
        log_file = log_dir / f"hedge_fund_{datetime.now().strftime('%Y%m%d')}.log"

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)  # Log everything to file

        if structured:
            file_formatter = StructuredFormatter()
        else:
            file_formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s - %(message)s - "
                "%(filename)s:%(lineno)d",
                datefmt="%Y-%m-%d %H:%M:%S",
            )

        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


# Convenience functions for common logging patterns
def log_trade(logger: logging.Logger, portfolio_id: int, ticker: str, action: str, quantity: int, price: float):
    """Log a trade execution."""
    logger.info(
        f"Trade executed: {action} {quantity} shares of {ticker} at ${price:.2f}",
        extra={"portfolio_id": portfolio_id, "ticker": ticker},
    )


def log_agent_signal(logger: logging.Logger, agent: str, ticker: str, signal: str, confidence: int):
    """Log an agent signal."""
    logger.info(
        f"Agent signal: {agent} → {ticker} = {signal} ({confidence}% confidence)",
        extra={"agent": agent, "ticker": ticker},
    )


def log_decision(logger: logging.Logger, decision_id: int, tickers: list, model: str):
    """Log a hedge fund decision."""
    logger.info(
        f"Decision {decision_id} created for {', '.join(tickers)} using {model}",
        extra={"decision_id": decision_id},
    )


def log_error(logger: logging.Logger, error: Exception, context: str = ""):
    """Log an error with context."""
    logger.error(f"{context}: {str(error)}", exc_info=True)


def log_performance(logger: logging.Logger, portfolio_id: int, total_value: float, returns: float):
    """Log performance metrics."""
    logger.info(
        f"Performance: Total Value=${total_value:,.2f}, Return={returns:.2f}%",
        extra={"portfolio_id": portfolio_id},
    )
