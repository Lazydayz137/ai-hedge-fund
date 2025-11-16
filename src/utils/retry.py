"""Retry logic with exponential backoff."""

import time
import logging
from typing import Callable, TypeVar, Optional, Type
from functools import wraps

from src.utils.errors import APIError

T = TypeVar("T")

logger = logging.getLogger(__name__)


def retry_with_backoff(
    max_attempts: int = 4,
    initial_delay: float = 2.0,
    max_delay: float = 16.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (APIError, ConnectionError, TimeoutError),
):
    """
    Decorator to retry a function with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_factor: Multiplier for delay between retries
        exceptions: Tuple of exceptions to catch and retry

    Example:
        @retry_with_backoff(max_attempts=3, initial_delay=1.0)
        def fetch_data():
            # API call that might fail
            return requests.get(url)
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            delay = initial_delay
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts: {str(e)}",
                            exc_info=True,
                        )
                        raise

                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: {str(e)}. "
                        f"Retrying in {delay:.1f}s...",
                        extra={"attempt": attempt, "delay": delay},
                    )

                    time.sleep(delay)
                    delay = min(delay * backoff_factor, max_delay)

            # Should never reach here, but just in case
            raise last_exception

        return wrapper

    return decorator


class RetryContext:
    """Context manager for retrying operations with backoff."""

    def __init__(
        self,
        max_attempts: int = 4,
        initial_delay: float = 2.0,
        max_delay: float = 16.0,
        backoff_factor: float = 2.0,
        exceptions: tuple = (APIError, ConnectionError, TimeoutError),
        operation_name: str = "operation",
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.exceptions = exceptions
        self.operation_name = operation_name
        self.attempt = 0
        self.delay = initial_delay

    def __enter__(self):
        self.attempt += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            return True

        if not issubclass(exc_type, self.exceptions):
            return False

        if self.attempt >= self.max_attempts:
            logger.error(
                f"{self.operation_name} failed after {self.max_attempts} attempts: {str(exc_val)}",
                exc_info=True,
            )
            return False

        logger.warning(
            f"{self.operation_name} attempt {self.attempt}/{self.max_attempts} failed: "
            f"{str(exc_val)}. Retrying in {self.delay:.1f}s...",
            extra={"attempt": self.attempt, "delay": self.delay},
        )

        time.sleep(self.delay)
        self.delay = min(self.delay * self.backoff_factor, self.max_delay)

        return True


def retry_operation(
    operation: Callable[[], T],
    max_attempts: int = 4,
    initial_delay: float = 2.0,
    max_delay: float = 16.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (APIError, ConnectionError, TimeoutError),
    operation_name: str = "operation",
) -> T:
    """
    Retry an operation with exponential backoff.

    Args:
        operation: Function to retry
        max_attempts: Maximum number of attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        backoff_factor: Multiplier for delay
        exceptions: Exceptions to catch
        operation_name: Name for logging

    Returns:
        Result of the operation

    Example:
        result = retry_operation(
            lambda: api.get_data(),
            max_attempts=3,
            operation_name="fetch data"
        )
    """
    delay = initial_delay
    last_exception = None

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except exceptions as e:
            last_exception = e

            if attempt == max_attempts:
                logger.error(
                    f"{operation_name} failed after {max_attempts} attempts: {str(e)}",
                    exc_info=True,
                )
                raise

            logger.warning(
                f"{operation_name} attempt {attempt}/{max_attempts} failed: {str(e)}. "
                f"Retrying in {delay:.1f}s...",
                extra={"attempt": attempt, "delay": delay},
            )

            time.sleep(delay)
            delay = min(delay * backoff_factor, max_delay)

    raise last_exception
