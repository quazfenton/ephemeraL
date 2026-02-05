"""Event recorder for auditing sandbox operations."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

RECORD_FILE = Path(os.getenv("SERVERLESS_RECORDER_FILE", "/tmp/serverless_events.log"))
_RECORD_LOCK = threading.Lock()


class EventRecorder:
    def __init__(self) -> None:
        RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)

    async def record(self, event: str, sandbox_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        payload = {
            "timestamp": time.time(),
            "event": event,
            "sandbox_id": sandbox_id,
            "metadata": metadata or {},
        }
        line = json.dumps(payload)
        with _RECORD_LOCK:
            with RECORD_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
