"""Comprehensive tests for circuit breaker implementation."""

import pytest
import asyncio

from serverless_workers_sdk.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
    CircuitBreakerRegistry,
    get_circuit_breaker_registry,
)


class TestCircuitBreaker:
    """Test suite for CircuitBreaker class."""

    @pytest.fixture
    def breaker(self):
        """Create a circuit breaker with test-friendly settings."""
        return CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=1.0,  # 1 second for fast tests
            half_open_max_calls=2,
            name="test-breaker",
        )

    @pytest.mark.asyncio
    async def test_initial_state_closed(self, breaker):
        """Test circuit breaker starts in CLOSED state."""
        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0

    @pytest.mark.asyncio
    async def test_successful_call_resets_failure_count(self, breaker):
        """Test that successful calls reset the failure count."""
        async def success_func():
            return "success"

        # Simulate some failures
        breaker._failure_count = 2

        # Successful call should reset count
        result = await breaker.call(success_func)
        assert result == "success"
        assert breaker._failure_count == 0

    @pytest.mark.asyncio
    async def test_failure_increments_count(self, breaker):
        """Test that failures increment the failure count."""
        async def fail_func():
            raise Exception("Simulated failure")

        for i in range(3):
            with pytest.raises(Exception):
                await breaker.call(fail_func)
            assert breaker._failure_count == i + 1

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self, breaker):
        """Test circuit opens after reaching failure threshold."""
        async def fail_func():
            raise Exception("Simulated failure")

        # Trigger threshold failures
        for i in range(3):
            with pytest.raises(Exception):
                await breaker.call(fail_func)

        # Circuit should be OPEN
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self, breaker):
        """Test that OPEN circuit rejects calls immediately."""
        async def fail_func():
            raise Exception("Simulated failure")

        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await breaker.call(fail_func)

        assert breaker.state == CircuitState.OPEN

        # Next call should be rejected without executing function
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await breaker.call(fail_func)

        assert "is OPEN" in str(exc_info.value)
        assert "Retry after" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self, breaker):
        """Test circuit transitions from OPEN to HALF_OPEN after recovery timeout."""
        async def fail_func():
            raise Exception("Simulated failure")

        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await breaker.call(fail_func)

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(1.1)  # recovery_timeout is 1.0s

        # Next call should transition to HALF_OPEN and execute function
        with pytest.raises(Exception):
            await breaker.call(fail_func)

        assert breaker.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_transitions_to_closed_after_half_open_successes(self, breaker):
        """Test circuit transitions from HALF_OPEN to CLOSED after successful calls."""
        call_count = 0

        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise Exception("Simulated failure")
            return "success"

        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await breaker.call(fail_then_succeed)

        assert breaker.state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(1.1)

        # First call in HALF_OPEN (will fail, back to OPEN)
        with pytest.raises(Exception):
            await breaker.call(fail_then_succeed)

        # Wait again
        await asyncio.sleep(1.1)

        # Now succeed twice to close circuit
        for i in range(2):
            result = await breaker.call(fail_then_succeed)
            assert result == "success"

        assert breaker.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_immediately_opens(self, breaker):
        """Test that any failure in HALF_OPEN immediately opens circuit."""
        async def fail_func():
            raise Exception("Simulated failure")

        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await breaker.call(fail_func)

        # Wait for recovery timeout
        await asyncio.sleep(1.1)

        # First call transitions to HALF_OPEN and fails
        with pytest.raises(Exception):
            await breaker.call(fail_func)

        assert breaker.state == CircuitState.HALF_OPEN

        # Failure should immediately open circuit
        assert breaker.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_manual_reset(self, breaker):
        """Test manual reset to CLOSED state."""
        async def fail_func():
            raise Exception("Simulated failure")

        # Open the circuit
        for i in range(3):
            with pytest.raises(Exception):
                await breaker.call(fail_func)

        assert breaker.state == CircuitState.OPEN

        # Manual reset
        await breaker.reset()

        assert breaker.state == CircuitState.CLOSED
        assert breaker._failure_count == 0

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, breaker):
        """Test metrics are properly tracked."""
        async def success_func():
            return "success"

        async def fail_func():
            raise Exception("Simulated failure")

        # Make some calls
        await breaker.call(success_func)
        await breaker.call(success_func)

        with pytest.raises(Exception):
            await breaker.call(fail_func)

        metrics = breaker.metrics
        assert metrics["name"] == "test-breaker"
        assert metrics["total_calls"] == 3
        assert metrics["total_successes"] == 2
        assert metrics["total_failures"] == 1
        assert metrics["state"] == CircuitState.CLOSED.value

    @pytest.mark.asyncio
    async def test_concurrent_calls_thread_safe(self, breaker):
        """Test circuit breaker handles concurrent calls safely."""
        async def slow_success():
            await asyncio.sleep(0.1)
            return "success"

        # Make concurrent calls
        results = await asyncio.gather(
            *[breaker.call(slow_success) for _ in range(10)],
            return_exceptions=True,
        )

        # All should succeed
        successes = [r for r in results if not isinstance(r, Exception)]
        assert len(successes) == 10

    @pytest.mark.asyncio
    async def test_exception_propagated_to_caller(self, breaker):
        """Test that exceptions from func are propagated to caller."""
        class CustomError(Exception):
            pass

        async def raise_custom_error():
            raise CustomError("Custom error message")

        with pytest.raises(CustomError, match="Custom error message"):
            await breaker.call(raise_custom_error)

    @pytest.mark.asyncio
    async def test_repr(self, breaker):
        """Test string representation."""
        assert "test-breaker" in repr(breaker)
        assert "closed" in repr(breaker)


class TestCircuitBreakerRegistry:
    """Test suite for CircuitBreakerRegistry class."""

    @pytest.mark.asyncio
    async def test_get_or_create_new(self):
        """Test creating new circuit breaker via registry."""
        registry = CircuitBreakerRegistry()

        breaker = await registry.get_or_create(
            name="test-service",
            failure_threshold=5,
            recovery_timeout=30.0,
        )

        assert breaker.name == "test-service"
        assert breaker.failure_threshold == 5
        assert breaker.recovery_timeout == 30.0

    @pytest.mark.asyncio
    async def test_get_or_create_existing(self):
        """Test getting existing circuit breaker via registry."""
        registry = CircuitBreakerRegistry()

        # Create first
        breaker1 = await registry.get_or_create(name="test-service")

        # Get existing
        breaker2 = await registry.get_or_create(name="test-service")

        assert breaker1 is breaker2

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        """Test getting non-existent circuit breaker."""
        registry = CircuitBreakerRegistry()

        breaker = await registry.get("nonexistent")

        assert breaker is None

    @pytest.mark.asyncio
    async def test_get_all_metrics(self):
        """Test getting metrics for all breakers."""
        registry = CircuitBreakerRegistry()

        # Create multiple breakers
        await registry.get_or_create("breaker1")
        await registry.get_or_create("breaker2")

        metrics = await registry.get_all_metrics()

        assert "breaker1" in metrics
        assert "breaker2" in metrics

    @pytest.mark.asyncio
    async def test_reset_all(self):
        """Test resetting all breakers."""
        registry = CircuitBreakerRegistry()

        breaker = await registry.get_or_create("test-breaker")

        # Manually set to OPEN
        breaker._state = CircuitState.OPEN

        # Reset all
        await registry.reset_all()

        assert breaker.state == CircuitState.CLOSED


class TestGlobalRegistry:
    """Test global registry singleton."""

    def test_get_circuit_breaker_registry_singleton(self):
        """Test that get_circuit_breaker_registry returns singleton."""
        registry1 = get_circuit_breaker_registry()
        registry2 = get_circuit_breaker_registry()

        assert registry1 is registry2


class TestCircuitBreakerIntegration:
    """Integration tests for circuit breaker with realistic scenarios."""

    @pytest.mark.asyncio
    async def test_realistic_service_call_with_retry(self):
        """Test circuit breaker with realistic service call pattern."""
        breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=0.5,
            half_open_max_calls=2,
            name="http-service",
        )

        call_attempts = [0]

        async def flaky_service():
            call_attempts[0] += 1
            if call_attempts[0] <= 2:
                raise ConnectionError("Service temporarily unavailable")
            return {"status": "ok"}

        # First two calls fail
        for i in range(2):
            with pytest.raises(ConnectionError):
                await breaker.call(flaky_service)

        # Circuit should still be CLOSED (threshold not reached)
        assert breaker.state == CircuitState.CLOSED

        # Third call succeeds
        result = await breaker.call(flaky_service)
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_cascading_failures_open_circuit(self):
        """Test that cascading failures properly open circuit."""
        breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=1.0,
            name="database",
        )

        async def db_query():
            raise TimeoutError("Database query timeout")

        # Simulate cascading failures
        failure_count = 0
        for i in range(10):
            try:
                await breaker.call(db_query)
            except CircuitBreakerOpenError:
                failure_count += 1
            except TimeoutError:
                failure_count += 1

        # Circuit should be OPEN
        assert breaker.state == CircuitState.OPEN

        # Most calls should be rejected without executing
        assert failure_count == 10  # 5 actual failures + 5 rejected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
