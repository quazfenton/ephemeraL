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
        user_id = workspace.name  # e.g., 'user1' if workspace is Path('/srv/workspaces/user1')

        # Create a temporary staging directory to extract into.
        # `tempfile.TemporaryDirectory` handles unique naming and automatic cleanup on scope exit.
        # It's created under `workspace.parent` to ensure it's on the same filesystem for atomic ops.
        with tempfile.TemporaryDirectory(dir=workspace.parent, prefix=f"{user_id}_extract_") as stage_dir_str:
            stage_dir = Path(stage_dir_str)
            logger.debug("Created temporary staging directory for restoration: %s", stage_dir)

            # This will be the new workspace directory after contents are moved and atomic swap.
            # It's created next to the original `workspace` path.
            final_tmp_workspace = workspace.with_suffix(".new_restore")
            # Ensure any previous temporary directory from a failed attempt is cleaned.
            if final_tmp_workspace.exists():
                shutil.rmtree(final_tmp_workspace)
            final_tmp_workspace.mkdir(parents=True, exist_ok=True)
            logger.debug("Created final temporary workspace for atomic swap: %s", final_tmp_workspace)

            try:
                dctx = zstd.ZstdDecompressor()
                with open(snapshot_path, "rb") as src:
                    with dctx.stream_reader(src) as decompressor:
                        with tarfile.open(fileobj=decompressor, mode="r|") as tar:
                            archive_root_dir_found = False
                            for member in tar:
                                # Path safety checks: absolute paths or path traversal (e.g., '..' components)
                                if ".." in Path(member.path).parts or member.path.startswith("/"):
                                    logger.warning("Skipping unsafe path in archive: %s", member.path)
                                    continue

                                # Identify the expected top-level directory in the archive.
                                # It should match the user_id for this workspace.
                                if not archive_root_dir_found:
                                    first_path_component = Path(member.path).parts[0]
                                    if first_path_component != user_id:
                                        raise tarfile.ExtractError(
                                            f"Archive root directory mismatch: expected '{user_id}', "
                                            f"found '{first_path_component}' in member '{member.path}'"
                                        )
                                    archive_root_dir_found = True
                                
                                # Ensure all members are strictly within the identified root (user_id).
                                # This also handles the case where member.path *is* user_id (the directory entry itself).
                                if not member.path.startswith(f"{user_id}{os.sep}") and member.path != user_id:
                                    logger.warning(
                                        "Skipping member outside expected archive root '%s': %s",
                                        user_id, member.path
                                    )
                                    continue

                                # Calculate the full intended destination path within the staging directory.
                                # This accounts for the archive's structure (`user_id/content`).
                                dest_full_path = Path(os.path.join(stage_dir, member.path))
                                
                                # Resolve the real path to guard against symlink attacks.
                                real_dest_full_path = Path(os.path.realpath(str(dest_full_path)))

                                # Check if the real resolved path is still within our designated staging directory.
                                if not str(real_dest_full_path).startswith(str(stage_dir)):
                                    logger.warning(
                                        "Skipping path outside target staging directory (symlink attack?): %s -> %s",
                                        member.path, real_dest_full_path
                                    )
                                    continue
                                
                                # Perform the extraction of the member to the staging directory.
                                # This will create `stage_dir/user_id/...`
                                tar.extract(member, path=stage_dir)
                            
                            logger.debug("Extracted archive members to staging directory: %s", stage_dir)

                if not archive_root_dir_found:
                    raise tarfile.ExtractError(f"No top-level directory '{user_id}' found in the archive.")

                # The content is now in `stage_dir / user_id`.
                # Move these contents to `final_tmp_workspace`.
                extracted_content_root = stage_dir / user_id
                if not extracted_content_root.is_dir():
                    raise RuntimeError(f"Extracted content root not found or not a directory: {extracted_content_root}")

                for item in os.listdir(extracted_content_root):
                    shutil.move(extracted_content_root / item, final_tmp_workspace)
                logger.debug("Moved contents from %s to %s", extracted_content_root, final_tmp_workspace)

                # Atomically replace the old workspace with the new, fully extracted one.
                # os.replace handles both cases: if workspace exists (replaces it) or not (renames).
                if workspace.exists() and not workspace.is_dir():
                    raise RuntimeError(f"Existing workspace {workspace} is not a directory.")

                os.replace(final_tmp_workspace, workspace)
                logger.info("Snapshot restored successfully to %s", workspace)

            except Exception as e:
                logger.error("Failed to extract snapshot for workspace %s: %s", workspace, e)
                # `tempfile.TemporaryDirectory` will clean up `stage_dir` automatically.
                # `final_tmp_workspace` needs explicit cleanup if it was created and `os.replace` failed.
                if final_tmp_workspace.exists():
                    shutil.rmtree(final_tmp_workspace)
                raise  # Re-raise the exception
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
