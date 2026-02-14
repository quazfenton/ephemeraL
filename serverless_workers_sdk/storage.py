"""S3/MinIO-compatible storage backend for snapshots."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MULTIPART_THRESHOLD = 100 * 1024 * 1024  # 100MB


@dataclass
class StorageConfig:
    endpoint_url: Optional[str]
    access_key: str
    secret_key: str
    bucket: str = "ephemeral-snapshots"
    region: str = "us-east-1"
    prefix: str = "snapshots/"

    @classmethod
    def from_env(cls) -> StorageConfig:
        return cls(
            endpoint_url=os.getenv("S3_ENDPOINT"),
            access_key=os.getenv("S3_ACCESS_KEY", ""),
            secret_key=os.getenv("S3_SECRET_KEY", ""),
            bucket=os.getenv("S3_BUCKET", "ephemeral-snapshots"),
            region=os.getenv("S3_REGION", "us-east-1"),
            prefix=os.getenv("S3_PREFIX", "snapshots/"),
        )

@dataclass
class StorageObject:
    key: str
    size: int
    last_modified: datetime
    etag: str

class StorageBackend(ABC):
    @abstractmethod
    async def upload(self, local_path: Path, remote_key: str) -> None: ...

    @abstractmethod
    async def download(self, remote_key: str, local_path: Path) -> None: ...

    @abstractmethod
    async def delete(self, remote_key: str) -> bool: ...

    @abstractmethod
    async def list_keys(self, prefix: str) -> list[str]: ...

    @abstractmethod
    async def exists(self, remote_key: str) -> bool: ...

    @abstractmethod
    async def exists(self, remote_key: str) -> bool: ...


class S3StorageBackend(StorageBackend):
    def __init__(self, config: StorageConfig) -> None:
        self._config = config
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3

            kwargs: dict = {
                "service_name": "s3",
                "aws_access_key_id": self._config.access_key,
                "aws_secret_access_key": self._config.secret_key,
                "region_name": self._config.region,
            }
            if self._config.endpoint_url:
                kwargs["endpoint_url"] = self._config.endpoint_url
            self._client = boto3.client(**kwargs)
        return self._client

    def _full_key(self, remote_key: str) -> str:
        return f"{self._config.prefix}{remote_key}"

    async def upload(self, local_path: Path, remote_key: str) -> None:
        full_key = self._full_key(remote_key)
        file_size = local_path.stat().st_size

        if file_size > MULTIPART_THRESHOLD:
            logger.info(
                "Using multipart upload for %s (%d bytes)", local_path, file_size
            )
            await asyncio.to_thread(self._multipart_upload, local_path, full_key)
        else:
            await asyncio.to_thread(self._simple_upload, local_path, full_key)

        logger.info("Uploaded %s -> s3://%s/%s", local_path, self._config.bucket, full_key)

    def _simple_upload(self, local_path: Path, full_key: str) -> None:
        client = self._get_client()
        client.upload_file(str(local_path), self._config.bucket, full_key)

    def _multipart_upload(self, local_path: Path, full_key: str) -> None:
        from boto3.s3.transfer import TransferConfig

        client = self._get_client()
        transfer_config = TransferConfig(
            multipart_threshold=MULTIPART_THRESHOLD,
            multipart_chunksize=MULTIPART_THRESHOLD,
        )
        client.upload_file(
            str(local_path),
            self._config.bucket,
            full_key,
            Config=transfer_config,
        )

    async def download(self, remote_key: str, local_path: Path) -> bool:
        full_key = self._full_key(remote_key)
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                self._get_client().download_file,
                self._config.bucket,
                full_key,
                str(local_path),
            )
            logger.info("Downloaded s3://%s/%s -> %s", self._config.bucket, full_key, local_path)
            return True
        except Exception as e:
            logger.exception("Failed to download %s: %s", full_key, e)
            return False

    async def delete(self, remote_key: str) -> bool:
        full_key = self._full_key(remote_key)
        try:
            await asyncio.to_thread(
                self._get_client().delete_object,
                Bucket=self._config.bucket,
                Key=full_key,
            )
            logger.info("Deleted s3://%s/%s", self._config.bucket, full_key)
            return True
        except Exception:
            logger.exception("Failed to delete %s", full_key)
            return False

    async def list_objects(self, prefix: str) -> list[StorageObject]:
        full_prefix = self._full_key(prefix)
        objects: list[StorageObject] = []
        continuation_token = None
        try:
            while True:
                response = await asyncio.to_thread(
                    self._get_client().list_objects_v2,
                    Bucket=self._config.bucket,
                    Prefix=full_prefix,
                    ContinuationToken=continuation_token,
                )
                for obj in response.get("Contents", []):
                    key = obj["Key"]
                    if key.startswith(self._config.prefix):
                        key = key[len(self._config.prefix) :]
                    objects.append(
                        StorageObject(
                            key=key,
                            size=obj["Size"],
                            last_modified=obj["LastModified"],
                            etag=obj.get("ETag", ""),
                        )
                    )
                if not response.get("IsTruncated"):
                    break
                continuation_token = response.get("NextContinuationToken")
            return objects
        except Exception:
            logger.exception("Failed to list objects with prefix %s", full_prefix)
            return []
            return objects
        except Exception:
            logger.exception("Failed to list objects with prefix %s", full_prefix)
            return []

    async def exists(self, remote_key: str) -> bool:
        full_key = self._full_key(remote_key)
        try:
            await asyncio.to_thread(
                self._get_client().head_object,
                Bucket=self._config.bucket,
                Key=full_key,
            )
            return True
        except Exception:
            return False


class LocalStorageBackend(StorageBackend):
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _full_path(self, remote_key: str) -> Path:
        if Path(remote_key).is_absolute():
            raise ValueError(f"Absolute path not allowed for remote_key: {remote_key!r}")

        base_resolved = self._base_dir.resolve()
        candidate_resolved = (self._base_dir / remote_key).resolve()

        try:
            # This will raise a ValueError if candidate_resolved is not a child of base_resolved
            candidate_resolved.relative_to(base_resolved)
        except ValueError as e:
            raise ValueError(
                f"Path traversal detected or path outside base directory: {remote_key!r}"
            ) from e

        return candidate_resolved

    async def upload(self, local_path: Path, remote_key: str) -> str:
        target = self._full_path(remote_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, local_path, target)
        logger.info("Copied %s -> %s", local_path, target)
        return str(target)

    async def download(self, remote_key: str, local_path: Path) -> bool:
        source = self._full_path(remote_key)
        if not source.exists():
            logger.warning("Local object not found: %s", source)
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, source, local_path)
        logger.info("Copied %s -> %s", source, local_path)
        return True

    async def delete(self, remote_key: str) -> bool:
        target = self._full_path(remote_key)
        if not target.exists():
            return True
        try:
            target.unlink()
            logger.info("Deleted %s", target)
            return True
        except OSError:
            logger.exception("Failed to delete %s", target)
            return False

    async def list_objects(self, prefix: str) -> list[StorageObject]:
        search_dir = self._full_path(prefix)
        if not search_dir.exists():
            return []
        parent = search_dir if search_dir.is_dir() else search_dir.parent
        pattern = "*" if search_dir.is_dir() else search_dir.name + "*"
        objects: list[StorageObject] = []
        for p in parent.glob(pattern):
            if not p.is_file():
                continue
            stat = p.stat()
            objects.append(
                StorageObject(
                    key=str(p.relative_to(self._base_dir)),
                    size=stat.st_size,
                    last_modified=datetime.fromtimestamp(stat.st_mtime),
                    etag="",
                )
            )
        return objects

    async def exists(self, remote_key: str) -> bool:
        return self._full_path(remote_key).exists()


def create_storage(backend: str = "auto") -> Optional[StorageBackend]:
    if backend == "s3" or (backend == "auto" and os.getenv("S3_ACCESS_KEY")):
        config = StorageConfig.from_env()
        logger.info("Using S3 storage backend (bucket=%s)", config.bucket)
        return S3StorageBackend(config)

    if backend == "local":
        base_dir = Path(os.getenv("LOCAL_STORAGE_DIR", "/tmp/ephemeral-storage"))
        logger.info("Using local storage backend (%s)", base_dir)
        return LocalStorageBackend(base_dir)

    logger.debug("No storage backend configured")
    return None
