"""Rate limiting middleware for API protection."""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
import time
from typing import Dict, List, Optional


class RateLimiter(BaseHTTPMiddleware):
    """
    Token bucket rate limiting middleware for FastAPI applications.
    
    Implements both:
    - Sustained rate limiting (requests per minute)
    - Burst rate limiting (requests per second)
    
    Uses a sliding window algorithm with per-client tracking based on
    IP address and User-Agent combination.
    """
    
    def __init__(
        self, 
        app,
        requests_per_minute: int = 60,
        burst_limit: int = 10,
        window_size: int = 60,
        enabled: bool = True,
        whitelist: Optional[List[str]] = None,
    ):
        """
        Initialize the rate limiter.
        
        Args:
            app: The FastAPI application instance.
            requests_per_minute: Maximum sustained requests per minute (default: 60).
            burst_limit: Maximum requests per second (default: 10).
            window_size: Size of the sliding window in seconds (default: 60).
            enabled: Whether rate limiting is enabled (default: True).
            whitelist: List of IP addresses to exempt from rate limiting.
        """
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self.window_size = window_size
        self.enabled = enabled
        self.whitelist = set(whitelist or [])
        
        # Per-client request timestamps
        # Key: f"{ip}:{user_agent}"
        # Value: list of timestamps
        self._request_counts: Dict[str, List[float]] = defaultdict(list)
        
        # Cleanup interval (seconds)
        self._cleanup_interval = 300  # 5 minutes
        self._last_cleanup = time.time()
    
    def _get_client_key(self, request: Request) -> str:
        """Generate a unique key for the client based on IP and User-Agent."""
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Check for X-Forwarded-For header (for proxied requests)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take the first IP in the chain
            client_ip = forwarded_for.split(",")[0].strip()
        
        return f"{client_ip}:{user_agent}"
    
    def _cleanup_old_entries(self, now: float) -> None:
        """Remove expired request timestamps to prevent memory leaks."""
        # Only cleanup periodically
        if now - self._last_cleanup < self._cleanup_interval:
            return
        
        window_start = now - self.window_size
        
        # Find keys with no recent requests
        keys_to_remove = []
        for key, timestamps in self._request_counts.items():
            # Remove old timestamps
            self._request_counts[key] = [ts for ts in timestamps if ts > window_start]
            # Mark empty keys for removal
            if not self._request_counts[key]:
                keys_to_remove.append(key)
        
        # Remove empty keys
        for key in keys_to_remove:
            del self._request_counts[key]
        
        self._last_cleanup = now
    
    async def dispatch(self, request: Request, call_next):
        """
        Process incoming requests and enforce rate limits.
        
        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or endpoint handler.
            
        Returns:
            HTTP response (either 429 Too Many Requests or the result of call_next).
        """
        # Skip rate limiting if disabled
        if not self.enabled:
            return await call_next(request)
        
        client_key = self._get_client_key(request)
        
        # Skip whitelisted clients
        if client_key.split(":")[0] in self.whitelist:
            return await call_next(request)
        
        now = time.time()
        window_start = now - self.window_size
        
        # Clean up old entries periodically
        self._cleanup_old_entries(now)
        
        # Get client's request history
        timestamps = self._request_counts[client_key]
        
        # Remove timestamps outside the current window
        timestamps = [ts for ts in timestamps if ts > window_start]
        
        # Check sustained rate limit (requests per minute)
        if len(timestamps) >= self.requests_per_minute:
            # Calculate retry-after
            oldest_timestamp = min(timestamps) if timestamps else now
            retry_after = int(oldest_timestamp + self.window_size - now) + 1
            
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded. Maximum {self.requests_per_minute} requests per minute.",
                    "retry_after": retry_after,
                    "limit": self.requests_per_minute,
                    "window_seconds": self.window_size,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self.requests_per_minute),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(oldest_timestamp + self.window_size)),
                },
            )
        
        # Check burst limit (requests per second)
        recent_burst = [ts for ts in timestamps if now - ts < 1.0]
        if len(recent_burst) >= self.burst_limit:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "burst_limit_exceeded",
                    "message": f"Burst limit exceeded. Maximum {self.burst_limit} requests per second.",
                    "limit": self.burst_limit,
                },
                headers={
                    "Retry-After": "1",
                    "X-RateLimit-Burst-Limit": str(self.burst_limit),
                    "X-RateLimit-Burst-Remaining": "0",
                },
            )
        
        # Record this request
        timestamps.append(now)
        self._request_counts[client_key] = timestamps
        
        # Calculate remaining requests
        remaining = max(0, self.requests_per_minute - len(timestamps))
        
        # Process the request
        response = await call_next(request)
        
        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(now + self.window_size))
        
        return response


class EndpointRateLimiter(BaseHTTPMiddleware):
    """
    Endpoint-specific rate limiting for different API routes.
    
    Allows different rate limits for different endpoints.
    For example:
    - /sandboxes/{id}/exec: 30 requests/minute
    - /snapshot/create: 10 requests/minute
    - /health: no limit
    """
    
    def __init__(
        self,
        app,
        endpoint_limits: Optional[Dict[str, Dict]] = None,
        default_limit: int = 60,
        default_burst: int = 10,
    ):
        """
        Initialize endpoint-specific rate limiter.
        
        Args:
            app: The FastAPI application.
            endpoint_limits: Dict mapping endpoint patterns to rate limit configs.
                Example: {
                    "/sandboxes/{id}/exec": {"limit": 30, "burst": 5},
                    "/snapshot/create": {"limit": 10, "burst": 2},
                }
            default_limit: Default requests per minute for unspecified endpoints.
            default_burst: Default burst limit for unspecified endpoints.
        """
        super().__init__(app)
        self.endpoint_limits = endpoint_limits or {}
        self.default_limit = default_limit
        self.default_burst = default_burst
        
        # Per-endpoint, per-client tracking
        self._request_counts: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
    
    def _get_endpoint_key(self, request: Request) -> str:
        """Get the rate limit configuration key for the current endpoint."""
        path = request.url.path
        
        # Normalize paths with IDs (e.g., /sandboxes/abc123/exec -> /sandboxes/{id}/exec)
        normalized_path = ""
        parts = path.strip("/").split("/")
        for i, part in enumerate(parts):
            if part.isdigit() or (len(part) == 8 and all(c in "0123456789abcdef" for c in part)):
                normalized_path += "/{id}"
            else:
                normalized_path += "/" + part
        
        return normalized_path.lstrip("/")
    
    def _get_client_key(self, request: Request) -> str:
        """Generate client key."""
        client_ip = request.client.host if request.client else "unknown"
        return client_ip
    
    async def dispatch(self, request: Request, call_next):
        """Process request with endpoint-specific rate limiting."""
        endpoint_key = self._get_endpoint_key(request)
        client_key = self._get_client_key(request)
        
        # Get limits for this endpoint
        limits = self.endpoint_limits.get(endpoint_key, {
            "limit": self.default_limit,
            "burst": self.default_burst,
        })
        
        limit = limits.get("limit", self.default_limit)
        burst = limits.get("burst", self.default_burst)
        
        now = time.time()
        window_start = now - 60  # 1-minute window
        
        # Get request history
        timestamps = self._request_counts[endpoint_key][client_key]
        
        # Remove old timestamps
        timestamps = [ts for ts in timestamps if ts > window_start]
        
        # Check rate limit
        if len(timestamps) >= limit:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Rate limit exceeded for {endpoint_key}. Maximum {limit} requests per minute.",
                    "endpoint": endpoint_key,
                    "limit": limit,
                },
                headers={"Retry-After": "60"},
            )
        
        # Check burst limit
        recent = [ts for ts in timestamps if now - ts < 1.0]
        if len(recent) >= burst:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "burst_limit_exceeded",
                    "message": f"Burst limit exceeded for {endpoint_key}. Maximum {burst} requests per second.",
                    "endpoint": endpoint_key,
                    "burst_limit": burst,
                },
                headers={"Retry-After": "1"},
            )
        
        # Record request
        timestamps.append(now)
        self._request_counts[endpoint_key][client_key] = timestamps
        
        # Process request
        return await call_next(request)
