from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from serverless_workers_sdk.runtime import SandboxManager


@dataclass
class BackgroundJob:
    job_id: str
    command: str
    args: list[str]
    interval: int
    task: asyncio.Task


class BackgroundExecutor:
    def __init__(self, manager: 'SandboxManager') -> None:
        self.manager = manager
        self._running: Dict[str, BackgroundJob] = {}

    async def start_job(
        self,
        sandbox_id: str,
        command: str,
        args: Optional[list[str]] = None,
        interval: int = 5,
    ) -> BackgroundJob:
        args = args or []
        job_id = uuid.uuid4().hex

        async def loop() -> None:
            while True:
                await self.manager.exec_command(
                    sandbox_id=sandbox_id,
                    command=command,
                    args=args,
                    timeout=10,
                )
                await asyncio.sleep(interval)

        task = asyncio.create_task(loop())
        job = BackgroundJob(job_id=job_id, command=command, args=args, interval=interval, task=task)
        self._running[job_id] = job
        await self.manager.ensure_background(sandbox_id, job)
        return job

    async def stop_job(self, sandbox_id: str, job_id: str) -> bool:
        job = self._running.pop(job_id, None)
        if not job:
            return False
        job.task.cancel()
        await self.manager.remove_background(sandbox_id, job_id)
        return True
