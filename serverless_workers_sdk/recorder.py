"""Event recorder for auditing sandbox operations."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

RECORD_FILE = Path(os.getenv("SERVERLESS_RECORDER_FILE", "./serverless_events.log"))
_RECORD_LOCK = threading.Lock()


class EventRecorder:
    def __init__(self) -> None:
        """
        Ensure the recorder's log directory exists.
        
        Creates the parent directory for RECORD_FILE if it does not already exist, including any intermediate directories.
        """
        RECORD_FILE.parent.mkdir(parents=True, exist_ok=True)

    async def record(self, event: str, sandbox_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Append a JSON-formatted audit event line to the recorder file.
        
        Constructs a payload containing a timestamp, the provided event name, sandbox identifier, and metadata (uses an empty dict when None), then appends the payload as a newline-delimited JSON line to the module-level RECORD_FILE under a module-level lock to ensure thread-safe writes.
        
        Parameters:
            event (str): Event name or type to record.
            sandbox_id (str): Identifier of the sandbox associated with the event.
            metadata (Optional[Dict[str, Any]]): Additional event data; stored as an object in the payload (defaults to an empty dict).
        """
        payload = {
            "timestamp": time.time(),
            "event": event,
            "sandbox_id": sandbox_id,
            "metadata": metadata or {},
        }
        line = json.dumps(payload)
        # Offload the file write to a thread to avoid blocking the event loop
        await asyncio.to_thread(self._write_log_line, line)
    
    def _write_log_line(self, line: str) -> None:
        """Write a log line to the file in a separate thread."""
        with _RECORD_LOCK:
            with RECORD_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")