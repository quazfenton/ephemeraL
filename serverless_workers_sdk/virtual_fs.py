from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


class VirtualFS:
    def __init__(self, root: Path) -> None:
        """
        Initialize the VirtualFS with a filesystem root and prepare mount points.
        
        Parameters:
            root (Path): Directory used as the virtual filesystem root; the directory will be created if it does not exist.
        """
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.mounts: Dict[str, Path] = {}

    def _resolve(self, path: str) -> Path:
        """
        Resolve a virtual filesystem path against the instance root, normalizing a leading slash and preventing directory traversal.
        If the first component of the path matches a registered mount alias, resolve to the mounted target.

        Parameters:
            path (str): Path within the virtual filesystem; may begin with a leading '/'.

        Returns:
            Path: The resolved Path object under the instance root corresponding to the given virtual path,
                  or the mounted target if the first component matches a registered alias.

        Raises:
            ValueError: If the provided path contains '..', indicating attempted directory traversal.
        """
        if path.startswith("/"):
            path = path[1:]

        # Check if the first component is a registered mount alias
        parts = path.split("/")
        if parts and parts[0] in self.mounts:
            # If it's a mount alias, resolve to the mounted target
            target_path = str(self.mounts[parts[0]])
            remaining_parts = parts[1:] if len(parts) > 1 else []
            if remaining_parts:
                return Path(target_path).joinpath(*remaining_parts)
            else:
                return Path(target_path)

        # Split path into components and check for directory traversal
        parts = path.split("/")
        normalized_parts = []
        for part in parts:
            if part == "..":
                if not normalized_parts:
                    # Attempting to traverse above the root
                    raise ValueError("directory traversal prevented")
                normalized_parts.pop()  # Go up one level
            elif part != "." and part != "":  # Skip current directory references and empty parts
                normalized_parts.append(part)

        # Join the normalized parts with the root
        result_path = self.root.joinpath(*normalized_parts)
        
        # Verify that the resolved path is still under the root to prevent traversal
        try:
            result_path.resolve().relative_to(self.root.resolve())
        except ValueError:
            raise ValueError("directory traversal prevented")
        
        return result_path

    def write(self, path: str, data: bytes) -> None:
        """
        Write bytes to a virtual file path relative to the filesystem root, creating parent directories as needed.
        
        Parameters:
        	path (str): Virtual path (relative to the VirtualFS root). A leading slash is allowed; paths containing ".." raise ValueError.
        	data (bytes): Byte content to write; existing files will be overwritten.
        
        Raises:
        	ValueError: If `path` contains a parent-directory segment ("..").
        """
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def read(self, path: str) -> bytes:
        """
        Read the contents of a file from the virtual filesystem.
        
        Parameters:
            path (str): Virtual path to the file (leading '/' is allowed). The path must not contain '..'.
        
        Returns:
            bytes: The raw bytes stored at the given path.
        
        Raises:
            FileNotFoundError: If no file exists at the resolved path.
        """
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(path)
        return target.read_bytes()

    def list_dir(self, path: str = "") -> list[str]:
        """
        List entries in the virtual filesystem directory at the given relative path.
        
        Parameters:
            path (str): Relative path within the virtual filesystem; empty string refers to the root.
        
        Returns:
            list[str]: A list of string paths for each entry in the directory. Returns an empty list if the target does not exist.
        
        Raises:
            NotADirectoryError: If the target exists but is not a directory.
        """
        target = self._resolve(path)
        if not target.exists():
            return []
        return [str(p.relative_to(self.root)) for p in target.iterdir()]

    def mount(self, alias: str, target: Path) -> None:
        """
        Register a mount alias for an existing filesystem path.
        
        Parameters:
            alias (str): The name to register for the mount.
            target (Path): The existing filesystem path to associate with the alias.
        
        Raises:
            FileNotFoundError: If `target` does not exist.
        """
        if not target.exists():
            raise FileNotFoundError(f"mount target does not exist: {target}")
        self.mounts[alias] = target