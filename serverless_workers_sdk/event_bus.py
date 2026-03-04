"""Event bus for cross-service communication and event-driven architecture."""

import asyncio
from typing import Callable, Dict, Any, List, Optional, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """
    Represents an event in the system.
    
    Attributes:
        type: Event type identifier (e.g., "sandbox.created", "snapshot.restored").
        payload: Event data as a dictionary.
        timestamp: When the event occurred (UTC).
        source: Service or component that emitted the event.
        id: Unique event identifier.
        correlation_id: ID for tracing related events across services.
    """
    type: str
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    source: str = ""
    id: str = field(default_factory=lambda: f"evt_{datetime.utcnow().timestamp()}")
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for serialization."""
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "correlation_id": self.correlation_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Create event from dictionary."""
        return cls(
            id=data.get("id", f"evt_{datetime.utcnow().timestamp()}"),
            type=data["type"],
            payload=data.get("payload", {}),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.utcnow(),
            source=data.get("source", ""),
            correlation_id=data.get("correlation_id"),
        )


class EventBus:
    """
    In-memory event bus for pub/sub communication between services.
    
    Features:
    - Synchronous and asynchronous event handlers
    - Event history for debugging and replay
    - Error handling with graceful degradation
    - Thread-safe operations
    
    Usage:
        event_bus = EventBus()
        
        # Subscribe to events
        @event_bus.subscribe("sandbox.created")
        async def on_sandbox_created(event: Event):
            logger.info(f"Sandbox created: {event.payload}")
        
        # Publish events
        await event_bus.publish(Event(
            type="sandbox.created",
            payload={"sandbox_id": "abc123", "user_id": "user1"},
            source="sandbox-api",
        ))
    """
    
    def __init__(self, max_history: int = 1000):
        """
        Initialize the event bus.
        
        Args:
            max_history: Maximum number of events to keep in history (default: 1000).
        """
        self._subscribers: Dict[str, List[Callable]] = {}
        self._event_history: deque = deque(maxlen=max_history)
        self._max_history = max_history
        self._lock = asyncio.Lock()
        
        # Event processing statistics
        self._stats = {
            "published": 0,
            "delivered": 0,
            "failed": 0,
        }
    
    def subscribe(self, event_type: str) -> Callable:
        """
        Decorator to subscribe a handler to an event type.
        
        Args:
            event_type: The event type to subscribe to (e.g., "sandbox.created").
            
        Returns:
            Decorator function that registers the handler.
            
        Example:
            @event_bus.subscribe("sandbox.created")
            async def handle_sandbox_created(event: Event):
                print(f"New sandbox: {event.payload['sandbox_id']}")
        """
        def decorator(handler: Callable) -> Callable:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(handler)
            logger.debug(f"Registered handler for event type: {event_type}")
            return handler
        return decorator
    
    def unsubscribe(self, event_type: str, handler: Callable) -> bool:
        """
        Unsubscribe a handler from an event type.
        
        Args:
            event_type: The event type to unsubscribe from.
            handler: The handler function to remove.
            
        Returns:
            True if the handler was found and removed, False otherwise.
        """
        if event_type not in self._subscribers:
            return False
        
        try:
            self._subscribers[event_type].remove(handler)
            if not self._subscribers[event_type]:
                del self._subscribers[event_type]
            logger.debug(f"Unregistered handler for event type: {event_type}")
            return True
        except ValueError:
            return False
    
    async def publish(self, event: Event) -> Dict[str, Any]:
        """
        Publish an event to all subscribed handlers.
        
        Args:
            event: The event to publish.
            
        Returns:
            Dictionary with delivery statistics:
            - published: True if event was published
            - handlers_called: Number of handlers that were called
            - successful: Number of handlers that succeeded
            - failed: Number of handlers that failed
        """
        async with self._lock:
            # Store in history
            self._event_history.append(event)
            self._stats["published"] += 1
        
        # Get handlers for this event type
        handlers = self._subscribers.get(event.type, [])
        
        if not handlers:
            logger.debug(f"No handlers for event type: {event.type}")
            return {
                "published": True,
                "handlers_called": 0,
                "successful": 0,
                "failed": 0,
            }
        
        # Call all handlers concurrently
        results = await asyncio.gather(
            *[self._safe_call(handler, event) for handler in handlers],
            return_exceptions=True,
        )
        
        successful = sum(1 for r in results if not isinstance(r, Exception))
        failed = len(results) - successful
        
        self._stats["delivered"] += successful
        self._stats["failed"] += failed
        
        if failed > 0:
            logger.warning(
                f"Event {event.id} delivery: {successful} succeeded, {failed} failed"
            )
        
        return {
            "published": True,
            "handlers_called": len(handlers),
            "successful": successful,
            "failed": failed,
        }
    
    async def _safe_call(
        self, 
        handler: Callable, 
        event: Event
    ) -> Any:
        """
        Call a handler safely, catching and logging any exceptions.
        
        Args:
            handler: The handler function to call.
            event: The event to pass to the handler.
            
        Returns:
            The handler's return value, or None if an exception occurred.
        """
        try:
            if asyncio.iscoroutinefunction(handler):
                return await handler(event)
            else:
                return handler(event)
        except Exception as e:
            logger.error(
                f"Event handler error for {event.type}: {e}",
                exc_info=True,
                extra={
                    "event_id": event.id,
                    "event_type": event.type,
                    "handler": handler.__name__,
                }
            )
            return e
    
    def get_history(
        self, 
        event_type: Optional[str] = None, 
        limit: int = 100,
        since: Optional[datetime] = None,
    ) -> List[Event]:
        """
        Get recent event history, optionally filtered.
        
        Args:
            event_type: Filter by event type (None for all types).
            limit: Maximum number of events to return.
            since: Only return events after this timestamp.
            
        Returns:
            List of events matching the criteria, newest first.
        """
        history = list(self._event_history)
        
        # Filter by type
        if event_type:
            history = [e for e in history if e.type == event_type]
        
        # Filter by timestamp
        if since:
            history = [e for e in history if e.timestamp > since]
        
        # Return most recent first, limited
        return list(reversed(history[-limit:]))
    
    def get_stats(self) -> Dict[str, int]:
        """
        Get event bus statistics.
        
        Returns:
            Dictionary with:
            - published: Total events published
            - delivered: Total successful deliveries
            - failed: Total failed deliveries
            - subscribers: Number of event types with subscribers
        """
        return {
            **self._stats,
            "subscribers": len(self._subscribers),
        }
    
    def clear_history(self) -> None:
        """Clear all event history."""
        self._event_history.clear()
        logger.info("Event history cleared")


# =============================================================================
# Pre-defined Event Types
# =============================================================================

class SandboxEvents:
    """Event types for sandbox lifecycle."""
    CREATED = "sandbox.created"
    DESTROYED = "sandbox.destroyed"
    EXECUTED = "sandbox.executed"
    EXECUTION_FAILED = "sandbox.execution_failed"
    QUOTA_EXCEEDED = "sandbox.quota_exceeded"
    PREVIEW_REGISTERED = "sandbox.preview_registered"
    PREVIEW_UNREGISTERED = "sandbox.preview_unregistered"
    BACKGROUND_JOB_STARTED = "sandbox.background_job_started"
    BACKGROUND_JOB_STOPPED = "sandbox.background_job_stopped"
    MOUNT_ADDED = "sandbox.mount_added"
    KEEPALIVE = "sandbox.keepalive"


class SnapshotEvents:
    """Event types for snapshot operations."""
    CREATED = "snapshot.created"
    RESTORED = "snapshot.restored"
    DELETED = "snapshot.deleted"
    UPLOAD_STARTED = "snapshot.upload_started"
    UPLOAD_COMPLETED = "snapshot.upload_completed"
    DOWNLOAD_STARTED = "snapshot.download_started"
    DOWNLOAD_COMPLETED = "snapshot.download_completed"
    RETENTION_ENFORCED = "snapshot.retention_enforced"


class QuotaEvents:
    """Event types for quota management."""
    VIOLATION = "quota.violation"
    WARNING_THRESHOLD = "quota.warning_threshold"
    LIMIT_REACHED = "quota.limit_reached"


class AuthEvents:
    """Event types for authentication."""
    LOGIN_SUCCESS = "auth.login_success"
    LOGIN_FAILED = "auth.login_failed"
    TOKEN_EXPIRED = "auth.token_expired"
    TOKEN_REFRESHED = "auth.token_refreshed"
    LOGOUT = "auth.logout"


class MarketplaceEvents:
    """Event types for worker marketplace."""
    WORKER_PUBLISHED = "marketplace.worker_published"
    WORKER_UPDATED = "marketplace.worker_updated"
    WORKER_DELETED = "marketplace.worker_deleted"
    WORKER_INSTALLED = "marketplace.worker_installed"


# =============================================================================
# Global Event Bus Instance
# =============================================================================

# Singleton event bus instance for application-wide use
event_bus = EventBus(max_history=1000)


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    return event_bus


# =============================================================================
# Example Event Handlers (for documentation)
# =============================================================================

"""
# Example: Log all sandbox creations
@event_bus.subscribe(SandboxEvents.CREATED)
async def log_sandbox_creation(event: Event):
    logger.info(
        f"Sandbox created: {event.payload.get('sandbox_id')} "
        f"for user {event.payload.get('user_id')}"
    )

# Example: Send metrics on snapshot creation
@event_bus.subscribe(SnapshotEvents.CREATED)
async def record_snapshot_metrics(event: Event):
    from serverless_workers_sdk.metrics import snapshot_created_total
    snapshot_created_total.inc()
    
    # Record snapshot size if available
    size_bytes = event.payload.get("size_bytes", 0)
    if size_bytes:
        from serverless_workers_sdk.metrics import snapshot_size_bytes
        snapshot_size_bytes.observe(size_bytes)

# Example: Notify on quota violations
@event_bus.subscribe(QuotaEvents.VIOLATION)
async def handle_quota_violation(event: Event):
    logger.warning(
        f"Quota violation for {event.payload.get('sandbox_id')}: "
        f"{event.payload.get('quota_type')}"
    )
    # Could also send alert to monitoring system here
"""
