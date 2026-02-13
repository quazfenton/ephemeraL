"""
Snapshot Manager Module
Pure-Python snapshot creation, restoration, and lifecycle management
with retry logic and optional remote storage backend support.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import shutil
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

import zstandard as zstd

logger = logging.getLogger(__name__)

_VALID_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_id(value: str, label: str = "ID") -> None:
    if not _VALID_ID_RE.match(value):
        raise ValueError(
            f"Invalid {label} format: {value!r}. "
            "Only alphanumeric characters, underscores, and hyphens are allowed."
        )


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    backoff_multiplier: float = 2.0


@dataclass
class SnapshotResult:
    snapshot_id: str
    path: Path
    size_bytes: int
    created_at: datetime


@dataclass
class SnapshotInfo:
    snapshot_id: str
    size_bytes: int
    created_at: datetime
    path: Path


# ---------------------------------------------------------------------------
# Storage backend protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class StorageBackend(Protocol):
    async def upload(self, local_path: Path, remote_key: str) -> None: ...
    async def download(self, remote_key: str, local_path: Path) -> None: ...
    async def list(self, prefix: str) -> list[str]: ...


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

async def with_retry(
    func,
    config: RetryConfig | None = None,
    operation_name: str = "operation",
):
    cfg = config or RetryConfig()
    last_exc: Exception | None = None
    delay = cfg.base_delay

    for attempt in range(1, cfg.max_retries + 1):
        try:
            logger.info("%s: attempt %d/%d", operation_name, attempt, cfg.max_retries)
            return await func()
        except Exception as exc:
            last_exc = exc
            if attempt == cfg.max_retries:
                logger.error(
                    "%s: failed after %d attempts: %s", operation_name, cfg.max_retries, exc,
                )
                raise
            logger.warning(
                "%s: attempt %d failed (%s), retrying in %.1fs",
                operation_name, attempt, exc, delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * cfg.backoff_multiplier, cfg.max_delay)


# ---------------------------------------------------------------------------
# Snapshot manager
# ---------------------------------------------------------------------------

class SnapshotManager:
    def __init__(
        self,
        workspace_dir: Path = Path("/srv/workspaces"),
        snapshot_dir: Path = Path("/srv/snapshots"),
        storage_backend: StorageBackend | None = None,
    ) -> None:
        self.workspace_dir = workspace_dir
        self.snapshot_dir = snapshot_dir
        self.storage_backend = storage_backend

    # -- helpers --------------------------------------------------------------

    def _user_workspace(self, user_id: str) -> Path:
        _validate_id(user_id, "user_id")
        return self.workspace_dir / user_id

    def _snapshot_path(self, user_id: str, snapshot_id: str) -> Path:
        _validate_id(user_id, "user_id")
        _validate_id(snapshot_id, "snapshot_id")
        return self.snapshot_dir / user_id / f"{snapshot_id}.tar.zst"

    @staticmethod
    def _generate_snapshot_id() -> str:
        return f"snap_{datetime.now().strftime('%Y_%m_%d_%H%M%S')}"

    # -- create ---------------------------------------------------------------

    async def create_snapshot(
        self,
        user_id: str,
        snapshot_id: str | None = None,
        retry_config: RetryConfig | None = None,
    ) -> SnapshotResult:
        _validate_id(user_id, "user_id")
        snapshot_id = snapshot_id or self._generate_snapshot_id()
        _validate_id(snapshot_id, "snapshot_id")

        workspace = self._user_workspace(user_id)
        if not workspace.exists():
            raise FileNotFoundError(f"Workspace not found: {workspace}")

        snapshot_path = self._snapshot_path(user_id, snapshot_id)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)

        async def _compress() -> None:
            await asyncio.to_thread(self._compress_workspace, workspace, snapshot_path, user_id)

        await with_retry(_compress, retry_config, f"create_snapshot({user_id}/{snapshot_id})")

        stat = snapshot_path.stat()
        result = SnapshotResult(
            snapshot_id=snapshot_id,
            path=snapshot_path,
            size_bytes=stat.st_size,
            created_at=datetime.fromtimestamp(stat.st_mtime),
        )
        logger.info(
            "Snapshot created: %s (%d bytes)", snapshot_path, result.size_bytes,
        )
        return result

    @staticmethod
    def _compress_workspace(workspace: Path, dest: Path, user_id: str) -> None:
        cctx = zstd.ZstdCompressor()
        with open(dest, "wb") as fh:
            with cctx.stream_writer(fh) as compressor:
                with tarfile.open(fileobj=compressor, mode="w|") as tar:
                    tar.add(str(workspace), arcname=user_id)

    # -- restore --------------------------------------------------------------

    async def restore_snapshot(
        self,
        user_id: str,
        snapshot_id: str,
        retry_config: RetryConfig | None = None,
    ) -> bool:
        _validate_id(user_id, "user_id")
        _validate_id(snapshot_id, "snapshot_id")

        snapshot_path = self._snapshot_path(user_id, snapshot_id)
        if not snapshot_path.exists():
            raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

        workspace = self._user_workspace(user_id)

        async def _extract() -> None:
            await asyncio.to_thread(
                self._extract_snapshot, snapshot_path, workspace,
            )

        await with_retry(_extract, retry_config, f"restore_snapshot({user_id}/{snapshot_id})")

        logger.info("Snapshot restored: %s -> %s", snapshot_path, workspace)
        return True

    @staticmethod
    def _extract_snapshot(snapshot_path: Path, workspace: Path) -> None:
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True, exist_ok=True)

        workspace_parent = os.path.realpath(str(workspace.parent))
        dctx = zstd.ZstdDecompressor()
        with open(snapshot_path, "rb") as src:
            with dctx.stream_reader(src) as decompressor:
                with tarfile.open(fileobj=decompressor, mode="r|") as tar:
                    for member in tar:
                        if ".." in member.path or member.path.startswith("/"):
                            logger.warning("Skipping unsafe path: %s", member.path)
                            continue
                        dest = os.path.realpath(
                            os.path.join(workspace_parent, member.path),
                        )
                        if not dest.startswith(workspace_parent):
                            logger.warning(
                                "Skipping path outside target directory: %s", member.path,
                            )
                            continue
                        tar.extract(member, path=workspace_parent)

    # -- list -----------------------------------------------------------------

    async def list_snapshots(self, user_id: str) -> list[SnapshotInfo]:
        _validate_id(user_id, "user_id")
        user_snapshot_dir = self.snapshot_dir / user_id
        if not user_snapshot_dir.exists():
            return []

        snapshots: list[SnapshotInfo] = []
        for path in user_snapshot_dir.glob("*.tar.zst"):
            stat = path.stat()
            snapshots.append(
                SnapshotInfo(
                    snapshot_id=path.name.removesuffix(".tar.zst"),
                    size_bytes=stat.st_size,
                    created_at=datetime.fromtimestamp(stat.st_mtime),
                    path=path,
                )
            )

        snapshots.sort(key=lambda s: s.created_at, reverse=True)
        return snapshots

    # -- delete ---------------------------------------------------------------

    async def delete_snapshot(self, user_id: str, snapshot_id: str) -> bool:
        _validate_id(user_id, "user_id")
        _validate_id(snapshot_id, "snapshot_id")

        snapshot_path = self._snapshot_path(user_id, snapshot_id)
        if not snapshot_path.exists():
            logger.warning("Snapshot not found for deletion: %s", snapshot_path)
            return False

        snapshot_path.unlink()
        logger.info("Deleted snapshot: %s", snapshot_path)
        return True

    # -- retention ------------------------------------------------------------

    async def enforce_retention(self, user_id: str, keep_count: int = 5) -> None:
        snapshots = await self.list_snapshots(user_id)
        to_delete = snapshots[keep_count:]
        for snap in to_delete:
            await self.delete_snapshot(user_id, snap.snapshot_id)
            logger.info("Retention: deleted %s/%s", user_id, snap.snapshot_id)

    # -- remote storage -------------------------------------------------------

    async def upload_to_storage(self, user_id: str, snapshot_id: str) -> None:
        if self.storage_backend is None:
            logger.warning("No storage backend configured; skipping upload")
            return
        snapshot_path = self._snapshot_path(user_id, snapshot_id)
        remote_key = f"{user_id}/{snapshot_id}.tar.zst"
        await self.storage_backend.upload(snapshot_path, remote_key)
        logger.info("Uploaded snapshot to remote storage: %s", remote_key)

    async def download_from_storage(self, user_id: str, snapshot_id: str) -> None:
        if self.storage_backend is None:
            logger.warning("No storage backend configured; skipping download")
            return
        snapshot_path = self._snapshot_path(user_id, snapshot_id)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        remote_key = f"{user_id}/{snapshot_id}.tar.zst"
        await self.storage_backend.download(remote_key, snapshot_path)
        logger.info("Downloaded snapshot from remote storage: %s", remote_key)
