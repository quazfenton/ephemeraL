"""Helpers for interacting with the preview router."""

from __future__ import annotations

import httpx
import os

PREVIEW_GATEWAY = os.getenv("PREVIEW_ROUTER_URL", "http://127.0.0.1:8001")


class PreviewRegistrar:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=10)

    async def register(self, sandbox_id: str, port: int, backend: str, metadata: dict | None = None) -> str:
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
        resp = await self.client.get(f"{PREVIEW_GATEWAY}/preview/list")
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self.client.aclose()
