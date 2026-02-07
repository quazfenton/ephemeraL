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
    """
    Construct a URL by appending `path` to `base_url`, ensuring there is exactly one slash between them.
    
    Parameters:
        base_url (str): The base URL to use as the prefix; any trailing slashes are removed.
        path (str): The path to append; leading slashes are removed. If empty, nothing is appended.
    
    Returns:
        str: The combined URL. If `path` is empty, returns `base_url` without a trailing slash; otherwise returns `base_url` + '/' + `path` with no duplicate slashes.
    """
    return base_url.rstrip('/') + (f"/{path.lstrip('/')}" if path else '')


class PreviewRouter:
    def __init__(self) -> None:
        """
        Initialize the PreviewRouter and its core components.
        
        Initializes:
            - client: an AsyncClient configured to not follow redirects and with a 30-second timeout.
            - health_checker: a HealthChecker that uses the HTTP client.
            - registry: a PreviewRegistry that uses the health checker.
            - fallback: a FallbackOrchestrator for managing fallback containers.
        """
        self.client = httpx.AsyncClient(follow_redirects=False, timeout=30)
        self.health_checker = HealthChecker(self.client)
        self.registry = PreviewRegistry(self.health_checker)
        self.fallback = FallbackOrchestrator()

    async def proxy(self, url: str, request: Request) -> StreamingResponse:
        """
        Forward the incoming FastAPI request to the specified upstream URL and stream the upstream response back to the client.
        
        This removes the incoming Host header when sending the request upstream and filters the upstream response headers to exclude `content-encoding`, `transfer-encoding`, and `connection`.
        
        Parameters:
            url (str): The full upstream URL to proxy the request to.
            request (Request): The incoming FastAPI request to forward.
        
        Returns:
            StreamingResponse: A response that streams the upstream response body, using the upstream status code and headers (excluding `content-encoding`, `transfer-encoding`, and `connection`).
        """
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
        """
        Route an incoming request to the registered preview target for a sandbox and port, falling back to a promoted container if the upstream is unavailable.
        
        If no target is registered for the given sandbox_id and port, an HTTP 404 is raised. The function attempts to proxy the request to the target's effective URL; if that proxy call raises an HTTP 502 and the registered target is not already using a fallback, a fallback container is promoted, the registry is updated to use the fallback URL, and the request is retried against the fallback.
        
        Parameters:
            sandbox_id (str): Identifier of the sandbox.
            port (int): Port number of the registered preview target.
            path (str): Request path to append to the target URL.
            request (Request): The incoming FastAPI request to forward.
        
        Returns:
            StreamingResponse: The proxied response streamed back to the client.
        
        Raises:
            HTTPException: 404 if no preview target is registered for the sandbox and port.
            HTTPException: 502 from the upstream proxy; re-raised unless a fallback is promoted and retried.
        """
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
        """
        Shut down router resources by closing the HTTP client and cleaning up stale fallback containers.
        
        Performs any necessary cleanup for network and fallback-orchestration resources.
        """
        await self.client.aclose()
        await self.fallback.cleanup_stale()


app = FastAPI(title="Sandbox Preview Router", version="1.0")
router = PreviewRouter()


@app.post("/preview/register", response_model=PreviewStatus)
async def register_preview(payload: PreviewRegistration) -> PreviewStatus:
    """
    Register a preview target for a sandbox and return its status.
    
    Parameters:
        payload (PreviewRegistration): Registration payload containing the sandbox ID, port, backend URL, and optional metadata.
    
    Returns:
        PreviewStatus: Status of the registered preview including `sandbox_id`, `port`, effective `url`, `use_fallback` flag, and `metadata`.
    """
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
    """
    Return a mapping of registered preview targets keyed by "sandbox_id:port".
    
    Each entry maps the string key "sandbox_id:port" to a PreviewStatus describing that target's sandbox_id, port, effective URL, whether it uses a fallback, and its metadata.
    
    Returns:
        Dict[str, PreviewStatus]: Dictionary where keys are "sandbox_id:port" and values are the corresponding PreviewStatus objects.
    """
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
    """
    Proxy an incoming HTTP request to the registered preview target for the given sandbox and port and return the upstream response stream.
    
    Parameters:
        sandbox_id (str): Identifier of the sandbox whose preview target should handle the request.
        port (int): Port number of the registered preview target.
        path (str): Path portion to append to the target's base URL.
        request (Request): Original FastAPI request to forward (method, headers, body, and query parameters preserved).
    
    Returns:
        StreamingResponse: The upstream target's response streamed back to the client, including status code and filtered headers.
    """
    return await router.route(sandbox_id, port, path, request)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """
    Perform application shutdown tasks for the preview router.
    
    Closes the router's HTTP client and performs cleanup of any stale fallback containers.
    """
    await router.shutdown()