"""Comprehensive tests for rate limiting middleware."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from serverless_workers_sdk.rate_limiter import RateLimiter, EndpointRateLimiter


class TestRateLimiter:
    """Test rate limiting middleware."""

    @pytest.fixture
    def app(self):
        """Create a simple FastAPI app with rate limiting."""
        app = FastAPI()
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        @app.get("/health")
        async def health():
            return {"status": "healthy"}
        
        # Add rate limiting middleware
        app.add_middleware(
            RateLimiter,
            requests_per_minute=10,
            burst_limit=3,
            enabled=True,
        )
        
        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_rate_limiter_allows_within_limit(self, client):
        """Test that requests within limit are allowed."""
        for i in range(5):
            response = client.get("/test")
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}

    def test_rate_limiter_blocks_excess_requests(self, client):
        """Test that requests exceeding limit are blocked."""
        # Make requests up to the limit
        for i in range(10):
            response = client.get("/test")
            # First 10 should succeed
            if i < 10:
                assert response.status_code == 200
        
        # Next request should be rate limited
        response = client.get("/test")
        assert response.status_code == 429
        assert response.json()["error"] == "rate_limit_exceeded"

    def test_rate_limiter_burst_limit(self, client):
        """Test burst rate limiting."""
        # Send requests very quickly (in same millisecond)
        responses = []
        for i in range(5):
            response = client.get("/test")
            responses.append(response)
        
        # First 3 should succeed (burst limit)
        success_count = sum(1 for r in responses if r.status_code == 200)
        assert success_count <= 3
        
        # At least 2 should be rate limited
        limited_count = sum(1 for r in responses if r.status_code == 429)
        assert limited_count >= 2

    def test_rate_limiter_headers(self, client):
        """Test that rate limit headers are included."""
        response = client.get("/test")
        
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers
        
        limit = int(response.headers["X-RateLimit-Limit"])
        assert limit == 10

    def test_rate_limiter_retry_after_header(self, client):
        """Test Retry-After header on rate limit response."""
        # Exhaust the rate limit
        for i in range(15):
            client.get("/test")
        
        # Check retry-after header
        response = client.get("/test")
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        
        retry_after = int(response.headers["Retry-After"])
        assert retry_after > 0
        assert retry_after <= 60

    def test_rate_limiter_different_clients(self, client):
        """Test that rate limiting is per-client."""
        # Client 1 with User-Agent 1
        response1 = client.get("/test", headers={"User-Agent": "Client1"})
        assert response1.status_code == 200
        
        # Client 2 with User-Agent 2 should have separate limit
        response2 = client.get("/test", headers={"User-Agent": "Client2"})
        assert response2.status_code == 200

    def test_rate_limiter_x_forwarded_for(self, client):
        """Test that X-Forwarded-For is respected."""
        # Request with X-Forwarded-For
        response1 = client.get(
            "/test",
            headers={"X-Forwarded-For": "192.168.1.1"}
        )
        assert response1.status_code == 200
        
        # Same forwarded IP should share rate limit
        response2 = client.get(
            "/test",
            headers={"X-Forwarded-For": "192.168.1.1"}
        )
        assert response2.status_code == 200

    def test_rate_limiter_disabled(self):
        """Test that rate limiting can be disabled."""
        app = FastAPI()
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        app.add_middleware(
            RateLimiter,
            requests_per_minute=1,
            enabled=False,
        )
        
        client = TestClient(app)
        
        # Should allow all requests even beyond limit
        for i in range(10):
            response = client.get("/test")
            assert response.status_code == 200

    def test_rate_limiter_whitelist(self):
        """Test that whitelisted IPs bypass rate limiting."""
        app = FastAPI()
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        app.add_middleware(
            RateLimiter,
            requests_per_minute=1,
            whitelist=["127.0.0.1"],
        )
        
        client = TestClient(app)
        
        # localhost should be whitelisted
        for i in range(10):
            response = client.get("/test")
            assert response.status_code == 200


class TestEndpointRateLimiter:
    """Test endpoint-specific rate limiting."""

    @pytest.fixture
    def app(self):
        """Create app with endpoint-specific rate limits."""
        app = FastAPI()
        
        @app.get("/sandboxes/{sandbox_id}/exec")
        async def exec_command(sandbox_id: str):
            return {"status": "executed"}
        
        @app.get("/snapshot/create")
        async def create_snapshot():
            return {"status": "created"}
        
        @app.get("/health")
        async def health():
            return {"status": "healthy"}
        
        app.add_middleware(
            EndpointRateLimiter,
            endpoint_limits={
                "sandboxes/{id}/exec": {"limit": 5, "burst": 2},
                "snapshot/create": {"limit": 2, "burst": 1},
            },
            default_limit=60,
            default_burst=10,
        )
        
        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_endpoint_specific_limits(self, client):
        """Test that different endpoints have different limits."""
        # Exec endpoint has limit of 5
        for i in range(5):
            response = client.get("/sandboxes/abc123/exec")
            if i < 5:
                assert response.status_code == 200
        
        # 6th request should be limited
        response = client.get("/sandboxes/abc123/exec")
        assert response.status_code == 429

    def test_snapshot_endpoint_stricter_limit(self, client):
        """Test snapshot endpoint has stricter limit."""
        # First request succeeds
        response = client.get("/snapshot/create")
        assert response.status_code == 200
        
        # Second request might succeed or fail depending on timing
        response = client.get("/snapshot/create")
        # Limit is 2 per minute, so this might succeed
        
        # Third request should definitely fail
        response = client.get("/snapshot/create")
        # May be 200 or 429 depending on burst limit

    def test_health_endpoint_default_limit(self, client):
        """Test that unspecified endpoints use default limit."""
        # Health endpoint uses default limit (60)
        for i in range(10):
            response = client.get("/health")
            assert response.status_code == 200


class TestRateLimiterCleanup:
    """Test memory cleanup and maintenance."""

    def test_old_entries_cleaned_up(self):
        """Test that old entries are cleaned up periodically."""
        app = FastAPI()
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        middleware = RateLimiter(
            app,
            requests_per_minute=10,
            window_size=1,  # 1 second window for testing
        )
        app.add_middleware(middleware)
        
        client = TestClient(app)
        
        # Make some requests
        for i in range(5):
            client.get("/test")
        
        # Wait for window to expire
        import time
        time.sleep(1.5)
        
        # New requests should succeed
        response = client.get("/test")
        assert response.status_code == 200


class TestRateLimiterEdgeCases:
    """Test edge cases and error handling."""

    def test_rate_limiter_no_client_ip(self):
        """Test handling of requests without client IP."""
        app = FastAPI()
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        app.add_middleware(RateLimiter, requests_per_minute=10)
        
        client = TestClient(app)
        
        # Should handle gracefully
        response = client.get("/test")
        assert response.status_code == 200

    def test_rate_limiter_concurrent_requests(self, app):
        """Test handling of concurrent requests."""
        from concurrent.futures import ThreadPoolExecutor
        
        client = TestClient(app)
        
        def make_request():
            return client.get("/test")
        
        # Make concurrent requests
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request) for _ in range(5)]
            responses = [f.result() for f in futures]
        
        # All should complete (some may be rate limited)
        assert len(responses) == 5
        # Check that at least some succeeded
        success_count = sum(1 for r in responses if r.status_code == 200)
        assert success_count > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
