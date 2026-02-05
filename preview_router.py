"""Preview router that proxies HTTP/S traffic into sandboxes and spins up fallback containers."""

from typing import Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, HttpUrl

from serverless_workers_router.orchestrator import FallbackOrchestrator
from serverless_workers_router.registry import HealthChecker, PreviewRegistry


class PreviewRegistration(BaseModel):
    sandbox_id: str
    port: int
    backend_url: HttpUrl
    metadata: Optional[Dict[str, str]] = None


class PreviewStatus(BaseModel):
    sandbox_id: str
    port: int
    url: str
    use_fallback: bool
    metadata: Dict[str, str]


def _strip_path_prefix(base_url: str, path: str) -> str:
    return base_url.rstrip('/') + (f"/{path.lstrip('/')}" if path else '')


class PreviewRouter:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(follow_redirects=False, timeout=30)
        self.health_checker = HealthChecker(self.client)
        self.registry = PreviewRegistry(self.health_checker)
        self.fallback = FallbackOrchestrator()

    async def proxy(self, url: str, request: Request) -> StreamingResponse:
        headers = {k: v for k, v in request.headers.items() if k.lower() != "host"}
        body = await request.body()
        try:
            upstream = self.client.build_request(
                request.method,
                url,
                headers=headers,
                content=body,
                params=request.query_params,
            )
            response = await self.client.send(upstream, stream=True)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

        excluded_headers = {"content-encoding", "transfer-encoding", "connection"}
        response_headers = {
            name: value
            for name, value in response.headers.items()
            if name.lower() not in excluded_headers
        }
        return StreamingResponse(
            response.aiter_raw(),
            status_code=response.status_code,
            headers=response_headers,
        )

    async def route(self, sandbox_id: str, port: int, path: str, request: Request) -> StreamingResponse:
        target = await self.registry.resolve(sandbox_id, port)
        if not target:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview target not registered")

        path_url = _strip_path_prefix(target.effective_url, path)
        try:
            return await self.proxy(path_url, request)
        except HTTPException as http_exc:
            if http_exc.status_code != status.HTTP_502_BAD_GATEWAY or target.use_fallback:
                raise
            fallback_url = await self.fallback.promote_to_container(sandbox_id)
            await self.registry.mark_fallback(sandbox_id, port, fallback_url)
            path_url = _strip_path_prefix(fallback_url, path)
            return await self.proxy(path_url, request)

    async def shutdown(self) -> None:
        await self.client.aclose()
        await self.fallback.cleanup_stale()


app = FastAPI(title="Sandbox Preview Router", version="1.0")
router = PreviewRouter()


@app.post("/preview/register", response_model=PreviewStatus)
async def register_preview(payload: PreviewRegistration) -> PreviewStatus:
    target = await router.registry.register(
        sandbox_id=payload.sandbox_id,
        port=payload.port,
        backend_url=str(payload.backend_url),
        metadata=payload.metadata,
    )
    return PreviewStatus(
        sandbox_id=target.sandbox_id,
        port=target.port,
        url=target.backend_url,
        use_fallback=target.use_fallback,
        metadata=target.metadata,
    )


@app.get("/preview/list", response_model=Dict[str, PreviewStatus])
async def list_previews() -> Dict[str, PreviewStatus]:
    targets = await router.registry.list_targets()
    response = {}
    for (sandbox_id, port), target in targets.items():
        response[f"{sandbox_id}:{port}"] = PreviewStatus(
            sandbox_id=sandbox_id,
            port=port,
            url=target.effective_url,
            use_fallback=target.use_fallback,
            metadata=target.metadata,
        )
    return response


@app.api_route("/preview/{sandbox_id}/{port}/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def proxy_preview(sandbox_id: str, port: int, path: str, request: Request) -> StreamingResponse:
    return await router.route(sandbox_id, port, path, request)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await router.shutdown()
