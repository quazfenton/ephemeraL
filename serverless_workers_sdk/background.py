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
        """
        Initialize the BackgroundExecutor with its SandboxManager and an empty job registry.
        
        Parameters:
            manager (SandboxManager): Manager used to execute commands and manage background jobs.
        """
        self.manager = manager
        self._running: Dict[str, BackgroundJob] = {}

    async def start_job(
        self,
        sandbox_id: str,
        command: str,
        args: Optional[list[str]] = None,
        interval: int = 5,
    ) -> BackgroundJob:
        """
        Start a repeating background job that executes a command inside the specified sandbox.
        
        Parameters:
            sandbox_id (str): Identifier of the target sandbox where the command will run.
            command (str): Command to execute on each iteration.
            args (list[str], optional): Arguments to pass to the command. Defaults to an empty list.
            interval (int): Number of seconds to wait between command executions.

        Returns:
            BackgroundJob: A BackgroundJob instance representing the scheduled job (includes its generated job_id and the asyncio Task).
        """
        args = args or []
        job_id = uuid.uuid4().hex

        async def loop() -> None:
            """
            Continuously executes the configured command inside the sandbox at the given interval.

            Each iteration calls the manager's exec_command with a 10-second timeout using the captured
            sandbox_id, command, and args, then awaits asyncio.sleep(interval). The loop runs indefinitely
            until the surrounding task is cancelled.
            """
            try:
                while True:
                    await self.manager.exec_command(
                        sandbox_id=sandbox_id,
                        command=command,
                        args=args,
                        timeout=10,
                    )
                    await asyncio.sleep(interval)
            except Exception:
                if job_id in self._running:
                    del self._running[job_id]
                raise
                )
                await asyncio.sleep(interval)

        task = asyncio.create_task(loop())
        job = BackgroundJob(job_id=job_id, command=command, args=args, interval=interval, task=task)
        self._running[job_id] = job
        await self.manager.ensure_background(sandbox_id, job)
        return job

    async def stop_job(self, sandbox_id: str, job_id: str) -> bool:
        """
        Stop and remove a background job for the given sandbox.

        Cancels the background task associated with `job_id`, removes it from the executor's tracking,
        and notifies the manager to remove the background job for `sandbox_id`.

        Parameters:
            sandbox_id (str): Identifier of the sandbox containing the job.
            job_id (str): Identifier of the background job to stop.

        Returns:
            bool: `true` if a job was found and stopped, `false` otherwise.
        """
        job = self._running.pop(job_id, None)
        if not job:
            return False
        job.task.cancel()
        try:
            await job.task  # Wait for the task to be cancelled
        except asyncio.CancelledError:
            pass  # Expected when task is cancelled
        await self.manager.remove_background(sandbox_id, job_id)
        return True

    async def shutdown(self) -> None:
        """
        Shutdown all running background jobs gracefully.

        Cancels all running background tasks and waits for them to finish before returning.
        """
        # Create a copy of the running jobs to avoid modification during iteration
        jobs_copy = self._running.copy()
        
        # Cancel all running tasks
        for job_id, job in jobs_copy.items():
            job.task.cancel()
        
        # Wait for all tasks to complete cancellation
        for job_id, job in jobs_copy.items():
            try:
                await job.task
            except asyncio.CancelledError:
                pass  # Expected when task is cancelled
            
            # Remove from tracking
            self._running.pop(job_id, None)