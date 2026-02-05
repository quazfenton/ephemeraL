from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


class VirtualFS:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.mounts: Dict[str, Path] = {}

    def _resolve(self, path: str) -> Path:
        if path.startswith("/"):
            path = path[1:]
        if ".." in path:
            raise ValueError("directory traversal prevented")
        return self.root / path

    def write(self, path: str, data: bytes) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read(self, path: str) -> bytes:
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(path)
        return target.read_bytes()

    def list_dir(self, path: str = "") -> list[str]:
        target = self._resolve(path)
        if not target.exists():
            return []
        return [str(p) for p in target.iterdir()]

    def mount(self, alias: str, target: Path) -> None:
        if not target.exists():
            raise FileNotFoundError(f"mount target does not exist: {target}")
        self.mounts[alias] = target
