"""Helpers for interacting with the preview router."""

from __future__ import annotations

import httpx
import os

PREVIEW_GATEWAY = os.getenv("PREVIEW_ROUTER_URL", "http://127.0.0.1:8001")


class PreviewRegistrar:
    def __init__(self) -> None:
        """
        Initialize the PreviewRegistrar and prepare its HTTP client.
        
        Creates an httpx.AsyncClient configured with a 10-second timeout and stores it on the instance as `self.client` for use by other methods.
        """
        self.client = httpx.AsyncClient(timeout=10)

    async def register(self, sandbox_id: str, port: int, backend: str, metadata: dict | None = None) -> str:
        """
        Register a preview backend for a sandbox and return the assigned preview URL.
        
        Parameters:
            sandbox_id (str): Identifier of the sandbox to register the preview for.
            port (int): Local port where the preview is served.
            backend (str): Backend URL to which the preview router should proxy.
            metadata (dict | None): Optional metadata to associate with the preview; defaults to an empty dict.
        
        Returns:
            str: The preview URL assigned by the preview router.
        
        Raises:
            httpx.HTTPStatusError: If the preview gateway responds with an error status.
        """
        payload = {
            "sandbox_id": sandbox_id,
            "port": port,
            "backend_url": backend,
            "metadata": metadata or {},
        }
        resp = await self.client.post(f"{PREVIEW_GATEWAY}/preview/register", json=payload)
        resp.raise_for_status()
        body = resp.json()
        return body["url"]

    async def list_previews(self) -> dict:
        """
        Fetches the list of registered previews from the preview gateway.
        
        Returns:
            dict: Parsed JSON response from the gateway containing previews.
        
        Raises:
            httpx.HTTPStatusError: If the HTTP response status indicates failure.
        """
        resp = await self.client.get(f"{PREVIEW_GATEWAY}/preview/list")
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        """
        Close the registrar's underlying HTTP client.
        
        Closes the internal httpx.AsyncClient to release network resources and open connections.
        """
        await self.client.aclose()