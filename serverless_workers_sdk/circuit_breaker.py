"""Circuit breaker pattern implementation for fault tolerance."""

import asyncio
import time
from enum import Enum
from typing import Callable, Any, Optional
import logging

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreakerError(Exception):
    """Base exception for circuit breaker."""
    pass


class CircuitBreakerOpenError(CircuitBreakerError):
    """Raised when circuit breaker is open and rejecting requests."""
    pass


class CircuitBreaker:
    """
    Circuit breaker implementation for resilient service calls.

    The circuit breaker has three states:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Service is failing, requests are rejected immediately
    - HALF_OPEN: Testing if service has recovered

    State transitions:
    - CLOSED -> OPEN: When failure count exceeds threshold
    - OPEN -> HALF_OPEN: After recovery timeout expires
    - HALF_OPEN -> CLOSED: When success count exceeds threshold
    - HALF_OPEN -> OPEN: On any failure

    Usage:
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

        async def call_service():
            return await breaker.call(my_async_function, arg1, arg2)

        try:
            result = await call_service()
        except CircuitBreakerOpenError:
            # Service is temporarily unavailable
            logger.warning("Service unavailable, retry later")
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
        name: Optional[str] = None,
    ):
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of consecutive failures before opening circuit.
            recovery_timeout: Seconds to wait before transitioning from OPEN to HALF_OPEN.
            half_open_max_calls: Successful calls needed to transition from HALF_OPEN to CLOSED.
            name: Optional name for logging (useful when multiple breakers exist).
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.name = name or "unnamed"

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_successes = 0
        self._lock = asyncio.Lock()

        # Metrics
        self._total_calls = 0
        self._total_failures = 0
        self._total_successes = 0
        self._last_state_change = time.time()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def metrics(self) -> dict:
        """Get circuit breaker metrics."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "last_state_change": self._last_state_change,
        }

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to execute.
            *args: Positional arguments for func.
            **kwargs: Keyword arguments for func.

        Returns:
            Result from func.

        Raises:
            CircuitBreakerOpenError: If circuit is OPEN and rejecting requests.
            Exception: Any exception from func is re-raised and counted as failure.
        """
        async with self._lock:
            self._total_calls += 1

            # Check if we should transition from OPEN to HALF_OPEN
            if self._state == CircuitState.OPEN:
                time_since_failure = time.time() - (self._last_failure_time or 0)
                if time_since_failure >= self.recovery_timeout:
                    logger.info(
                        f"Circuit breaker '{self.name}' transitioning from OPEN to HALF_OPEN "
                        f"(recovery timeout {self.recovery_timeout}s elapsed)"
                    )
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_successes = 0
                    self._last_state_change = time.time()
                else:
                    # Still in recovery timeout, reject request
                    self._total_failures += 1
                    remaining_wait = self.recovery_timeout - time_since_failure
                    raise CircuitBreakerOpenError(
                        f"Circuit breaker '{self.name}' is OPEN. "
                        f"Retry after {remaining_wait:.1f}s."
                    )

        try:
            # Execute the function
            result = await func(*args, **kwargs)

            # Record success
            async with self._lock:
                self._total_successes += 1

                if self._state == CircuitState.HALF_OPEN:
                    self._half_open_successes += 1
                    if self._half_open_successes >= self.half_open_max_calls:
                        logger.info(
                            f"Circuit breaker '{self.name}' transitioning from HALF_OPEN to CLOSED "
                            f"({self._half_open_successes} successful calls)"
                        )
                        self._state = CircuitState.CLOSED
                        self._failure_count = 0
                        self._last_state_change = time.time()
                else:
                    # Reset failure count on success in CLOSED state
                    self._failure_count = 0

            return result

        except Exception as e:
            # Record failure
            async with self._lock:
                self._failure_count += 1
                self._total_failures += 1
                self._last_failure_time = time.time()

                if self._state == CircuitState.HALF_OPEN:
                    # Any failure in HALF_OPEN immediately opens circuit
                    logger.warning(
                        f"Circuit breaker '{self.name}' transitioning from HALF_OPEN to OPEN "
                        f"(failure during recovery test)"
                    )
                    self._state = CircuitState.OPEN
                    self._last_state_change = time.time()
                elif self._failure_count >= self.failure_threshold:
                    # Threshold reached, open circuit
                    logger.warning(
                        f"Circuit breaker '{self.name}' transitioning from CLOSED to OPEN "
                        f"({self._failure_count} consecutive failures, threshold={self.failure_threshold})"
                    )
                    self._state = CircuitState.OPEN
                    self._last_state_change = time.time()

            # Re-raise the exception
            raise

    async def reset(self) -> None:
        """
        Manually reset circuit breaker to CLOSED state.

        Useful for administrative reset after known service recovery.
        """
        async with self._lock:
            old_state = self._state
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_successes = 0
            self._last_state_change = time.time()

            if old_state != CircuitState.CLOSED:
                logger.info(f"Circuit breaker '{self.name}' manually reset from {old_state.value} to CLOSED")

    def __repr__(self) -> str:
        return f"CircuitBreaker(name={self.name!r}, state={self._state.value})"


class CircuitBreakerRegistry:
    """
    Registry for managing multiple circuit breakers.

    Provides centralized access to circuit breakers by name,
    useful for dependency injection and monitoring.
    """

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
    ) -> CircuitBreaker:
        """
        Get existing circuit breaker or create new one.

        Args:
            name: Unique name for the circuit breaker.
            failure_threshold: Passed to CircuitBreaker constructor.
            recovery_timeout: Passed to CircuitBreaker constructor.
            half_open_max_calls: Passed to CircuitBreaker constructor.

        Returns:
            Existing or newly created CircuitBreaker.
        """
        async with self._lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    half_open_max_calls=half_open_max_calls,
                    name=name,
                )
                logger.info(f"Created circuit breaker '{name}'")
            return self._breakers[name]

    async def get(self, name: str) -> Optional[CircuitBreaker]:
        """Get circuit breaker by name, or None if not found."""
        async with self._lock:
            return self._breakers.get(name)

    async def get_all_metrics(self) -> dict[str, dict]:
        """Get metrics for all registered circuit breakers."""
        async with self._lock:
            return {name: breaker.metrics for name, breaker in self._breakers.items()}

    async def reset_all(self) -> None:
        """Reset all circuit breakers to CLOSED state."""
        async with self._lock:
            for breaker in self._breakers.values():
                await breaker.reset()


# Global registry instance for application-wide use
_registry: Optional[CircuitBreakerRegistry] = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    """Get or create global circuit breaker registry."""
    global _registry
    if _registry is None:
        _registry = CircuitBreakerRegistry()
    return _registry
