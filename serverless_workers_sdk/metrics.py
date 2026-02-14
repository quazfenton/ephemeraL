"""Lightweight Prometheus-compatible metrics for the ephemeral platform."""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

DEFAULT_BUCKETS: Tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
    float("inf"),
)
SIZE_BUCKETS: Tuple[float, ...] = (
    1024,            # 1 KB
    10240,           # 10 KB
    102400,          # 100 KB
    1048576,         # 1 MB
    10485760,        # 10 MB
    104857600,       # 100 MB
    1073741824,      # 1 GB
    float("inf"),
)

def _label_key(labels: Dict[str, str]) -> Tuple[Tuple[str, str], ...]:
    return tuple(sorted(labels.items()))

def _format_labels(labels: Dict[str, str]) -> str:
    if not labels:
        return ""
    def escape_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace("\n", "\\n").replace("\"", "\\\"")
    pairs = ",".join(f'{k}="{escape_value(v)}"' for k, v in sorted(labels.items()))
    return "{" + pairs + "}"

# ---------------------------------------------------------------------------
# Metric types
# ---------------------------------------------------------------------------

class _LabeledChild:
    """Base for a labeled child metric instance."""


class Counter:
    def __init__(self, name: str, help_text: str, label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._lock = threading.Lock()
        self._value = 0.0
        self._children: Dict[Tuple[Tuple[str, str], ...], Counter] = {}

    def labels(self, **kwargs: str) -> Counter:
        if not self.label_names:
            raise ValueError(f"Counter {self.name} has no label names defined")
        missing = set(self.label_names) - set(kwargs)
        if missing:
            raise ValueError(f"Missing label(s): {missing}")
        key = _label_key(kwargs)
        with self._lock:
            if key not in self._children:
                child = Counter(self.name, self.help_text)
                child._labels = kwargs
                self._children[key] = child
            return self._children[key]

    def inc(self, amount: float = 1) -> None:
        if amount < 0:
            raise ValueError("Counter can only be incremented")
        with self._lock:
            self._value += amount

    def _collect(self) -> List[Tuple[str, Dict[str, str], float]]:
        samples: List[Tuple[str, Dict[str, str], float]] = []
        with self._lock:
            if self._children:
                for _key, child in self._children.items():
                    labels = getattr(child, "_labels", {})
                    samples.append((self.name + "_total", labels, child._value))
            else:
                samples.append((self.name + "_total", {}, self._value))
        return samples


class Gauge:
    def __init__(self, name: str, help_text: str, label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._lock = threading.Lock()
        self._value = 0.0
        self._children: Dict[Tuple[Tuple[str, str], ...], Gauge] = {}

    def labels(self, **kwargs: str) -> Gauge:
        if not self.label_names:
            raise ValueError(f"Gauge {self.name} has no label names defined")
        missing = set(self.label_names) - set(kwargs)
        if missing:
            raise ValueError(f"Missing label(s): {missing}")
        key = _label_key(kwargs)
        with self._lock:
            if key not in self._children:
                child = Gauge(self.name, self.help_text)
                child._labels = kwargs
                self._children[key] = child
            return self._children[key]

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1) -> None:
        with self._lock:
            self._value -= amount

    def _collect(self) -> List[Tuple[str, Dict[str, str], float]]:
        samples: List[Tuple[str, Dict[str, str], float]] = []
        with self._lock:
            if self._children:
                for _key, child in self._children.items():
                    labels = getattr(child, "_labels", {})
                    samples.append((self.name, labels, child._value))
            else:
                samples.append((self.name, {}, self._value))
        return samples


class Histogram:
    def __init__(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
        buckets: Tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._buckets = buckets if buckets[-1] == float("inf") else (*buckets, float("inf"))
        self._lock = threading.Lock()
        self._bucket_counts: List[int] = [0] * len(self._buckets)
        self._sum = 0.0
        self._count = 0
        self._children: Dict[Tuple[Tuple[str, str], ...], Histogram] = {}

    def labels(self, **kwargs: str) -> Histogram:
        if not self.label_names:
            raise ValueError(f"Histogram {self.name} has no label names defined")
        missing = set(self.label_names) - set(kwargs)
        if missing:
            raise ValueError(f"Missing label(s): {missing}")
        key = _label_key(kwargs)
        with self._lock:
            if key not in self._children:
                child = Histogram(self.name, self.help_text, buckets=self._buckets)
                child._labels = kwargs
                self._children[key] = child
            return self._children[key]

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._count += 1
            for i, bound in enumerate(self._buckets):
                if value <= bound:
                    self._bucket_counts[i] += 1
                    break

    def _collect_one(self, base_labels: Dict[str, str]) -> List[Tuple[str, Dict[str, str], float]]:
        samples: List[Tuple[str, Dict[str, str], float]] = []
        with self._lock:
            cumulative = 0
            for i, bound in enumerate(self._buckets):
                cumulative += self._bucket_counts[i]
                le = "+Inf" if math.isinf(bound) else str(bound)
                bucket_labels = {**base_labels, "le": le}
                samples.append((self.name + "_bucket", bucket_labels, float(cumulative)))
            samples.append((self.name + "_count", base_labels, float(self._count)))
            samples.append((self.name + "_sum", base_labels, self._sum))
        return samples

    def _collect(self) -> List[Tuple[str, Dict[str, str], float]]:
        if self._children:
            samples: List[Tuple[str, Dict[str, str], float]] = []
            with self._lock:
                children = list(self._children.values())
            for child in children:
                labels = getattr(child, "_labels", {})
                samples.extend(child._collect_one(labels))
            return samples
        return self._collect_one({})


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class MetricsRegistry:
    _instance: Optional[MetricsRegistry] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> MetricsRegistry:
        with cls._init_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._metrics: List[Counter | Gauge | Histogram] = []
                inst._lock = threading.Lock()
                cls._instance = inst
            return cls._instance

    def register(self, metric: Counter | Gauge | Histogram) -> Counter | Gauge | Histogram:
        with self._lock:
            self._metrics.append(metric)
        return metric

    def render(self) -> str:
    def render(self) -> str:
        lines: List[str] = []
        with self._lock:
            metrics = list(self._metrics)
        for metric in metrics:
            type_name = type(metric).__name__.lower()
            prom_type = {"counter": "counter", "gauge": "gauge", "histogram": "histogram"}[type_name]
            lines.append(f"# HELP {metric.name} {metric.help_text}")
            lines.append(f"# TYPE {metric.name} {prom_type}")
            for sample_name, labels, value in metric._collect():
                label_str = _format_labels(labels)
                if not (isinstance(value, float) and (value != value or value == float("inf") or value == float("-inf"))) and value == int(value):
                    lines.append(f"{sample_name}{label_str} {int(value)}")
                else:
                    lines.append(f"{sample_name}{label_str} {value}")
        lines.append("")
        return "\n".join(lines)

# ---------------------------------------------------------------------------
# Pre-defined application metrics
# ---------------------------------------------------------------------------

registry = MetricsRegistry()

sandbox_created_total = registry.register(
    Counter("sandbox_created", "Total sandboxes created"),
)

sandbox_active = registry.register(
    Gauge("sandbox_active", "Currently active sandboxes"),
)

sandbox_exec_total = registry.register(
    Counter("sandbox_exec", "Total sandbox executions", label_names=("sandbox_id", "command")),
)

sandbox_exec_duration_seconds = registry.register(
    Histogram("sandbox_exec_duration_seconds", "Sandbox execution duration in seconds"),
)

snapshot_created_total = registry.register(
    Counter("snapshot_created", "Total snapshots created"),
)

snapshot_restored_total = registry.register(
    Counter("snapshot_restored", "Total snapshots restored"),
)

snapshot_size_bytes = registry.register(
    Histogram("snapshot_size_bytes", "Snapshot sizes in bytes", buckets=SIZE_BUCKETS),
)

http_requests_total = registry.register(
    Counter("http_requests", "Total HTTP requests", label_names=("method", "path", "status")),
)

http_request_duration_seconds = registry.register(
    Histogram(
        "http_request_duration_seconds",
        "HTTP request duration in seconds",
        label_names=("method", "path"),
    ),
)

quota_violations_total = registry.register(
    Counter("quota_violations", "Total quota violations", label_names=("quota_type",)),
)


# ---------------------------------------------------------------------------
# FastAPI integration
# ---------------------------------------------------------------------------

class MetricsMiddleware:
    """Starlette / FastAPI middleware that records request metrics."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path == "/metrics":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        start = time.monotonic()
        status_code = 500  # default if something goes wrong

        async def send_wrapper(message: Dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.monotonic() - start
            http_requests_total.labels(
                method=method, path=path, status=str(status_code),
            ).inc()
            http_request_duration_seconds.labels(
                method=method, path=path,
            ).observe(duration)


def create_metrics_endpoint(app: Any) -> None:
    """Add a GET /metrics route to a FastAPI application."""
    from fastapi import Response

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        return Response(
            content=registry.render(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )
