"""Custom exceptions and error handling for AI Hedge Fund."""

from typing import Optional


class HedgeFundError(Exception):
    """Base exception for all hedge fund errors."""

    def __init__(self, message: str, context: Optional[dict] = None):
        self.message = message
        self.context = context or {}
        super().__init__(self.message)


class TradingError(HedgeFundError):
    """Base exception for trading-related errors."""

    pass


class InsufficientFundsError(TradingError):
    """Raised when trying to trade without enough cash or margin."""

    def __init__(self, required: float, available: float, ticker: str = ""):
        self.required = required
        self.available = available
        self.ticker = ticker
        message = f"Insufficient funds: need ${required:,.2f}, have ${available:,.2f}"
        if ticker:
            message = f"{message} for {ticker}"
        super().__init__(message, {"required": required, "available": available, "ticker": ticker})


class PositionLimitError(TradingError):
    """Raised when trying to exceed position limits."""

    def __init__(self, ticker: str, requested: float, limit: float):
        self.ticker = ticker
        self.requested = requested
        self.limit = limit
        message = f"Position limit exceeded for {ticker}: requested ${requested:,.2f}, limit ${limit:,.2f}"
        super().__init__(message, {"ticker": ticker, "requested": requested, "limit": limit})


class InsufficientSharesError(TradingError):
    """Raised when trying to sell more shares than owned."""

    def __init__(self, ticker: str, requested: int, available: int):
        self.ticker = ticker
        self.requested = requested
        self.available = available
        message = f"Insufficient shares of {ticker}: need {requested}, have {available}"
        super().__init__(message, {"ticker": ticker, "requested": requested, "available": available})


class MarginCallError(TradingError):
    """Raised when margin requirements are not met."""

    def __init__(self, required_margin: float, available_margin: float):
        self.required_margin = required_margin
        self.available_margin = available_margin
        message = f"Margin call: need ${required_margin:,.2f}, have ${available_margin:,.2f}"
        super().__init__(message, {"required": required_margin, "available": available_margin})


class CircuitBreakerTriggered(TradingError):
    """Raised when a circuit breaker is triggered (e.g., daily loss limit)."""

    def __init__(self, reason: str, value: float, limit: float):
        self.reason = reason
        self.value = value
        self.limit = limit
        message = f"Circuit breaker triggered - {reason}: {value:.2f} exceeds limit of {limit:.2f}"
        super().__init__(message, {"reason": reason, "value": value, "limit": limit})


class DataError(HedgeFundError):
    """Base exception for data-related errors."""

    pass


class APIError(DataError):
    """Raised when external API calls fail."""

    def __init__(self, api: str, status_code: Optional[int] = None, message: str = ""):
        self.api = api
        self.status_code = status_code
        error_message = f"API error from {api}"
        if status_code:
            error_message += f" (status {status_code})"
        if message:
            error_message += f": {message}"
        super().__init__(error_message, {"api": api, "status_code": status_code})


class DataValidationError(DataError):
    """Raised when data fails validation."""

    def __init__(self, field: str, value: any, reason: str):
        self.field = field
        self.value = value
        self.reason = reason
        message = f"Validation error for {field}={value}: {reason}"
        super().__init__(message, {"field": field, "value": str(value), "reason": reason})


class MissingDataError(DataError):
    """Raised when required data is missing."""

    def __init__(self, data_type: str, identifier: str = ""):
        self.data_type = data_type
        self.identifier = identifier
        message = f"Missing data: {data_type}"
        if identifier:
            message += f" for {identifier}"
        super().__init__(message, {"data_type": data_type, "identifier": identifier})


class DatabaseError(HedgeFundError):
    """Base exception for database-related errors."""

    pass


class PortfolioNotFoundError(DatabaseError):
    """Raised when a portfolio is not found."""

    def __init__(self, portfolio_id: Optional[int] = None, portfolio_name: Optional[str] = None):
        self.portfolio_id = portfolio_id
        self.portfolio_name = portfolio_name
        if portfolio_id:
            message = f"Portfolio not found: ID {portfolio_id}"
        elif portfolio_name:
            message = f"Portfolio not found: {portfolio_name}"
        else:
            message = "Portfolio not found"
        super().__init__(message, {"portfolio_id": portfolio_id, "portfolio_name": portfolio_name})


class ReconciliationError(DatabaseError):
    """Raised when portfolio reconciliation fails."""

    def __init__(self, portfolio_id: int, expected: dict, actual: dict):
        self.portfolio_id = portfolio_id
        self.expected = expected
        self.actual = actual
        message = f"Portfolio {portfolio_id} reconciliation failed: expected != actual"
        super().__init__(message, {"portfolio_id": portfolio_id, "expected": expected, "actual": actual})


class ConfigurationError(HedgeFundError):
    """Base exception for configuration errors."""

    pass


class MissingAPIKeyError(ConfigurationError):
    """Raised when required API key is missing."""

    def __init__(self, key_name: str):
        self.key_name = key_name
        message = f"Missing required API key: {key_name}"
        super().__init__(message, {"key_name": key_name})


class InvalidConfigurationError(ConfigurationError):
    """Raised when configuration is invalid."""

    def __init__(self, config_key: str, reason: str):
        self.config_key = config_key
        self.reason = reason
        message = f"Invalid configuration for {config_key}: {reason}"
        super().__init__(message, {"config_key": config_key, "reason": reason})
