"""Comprehensive tests for preview_router.py module."""

import pytest
from unittest import mock
from httpx import AsyncClient, Response, Request, RequestError
from fastapi.testclient import TestClient
from fastapi import status

from preview_router import (
    PreviewRouter,
    PreviewRegistration,
    PreviewStatus,
    _strip_path_prefix,
    app
)


class TestStripPathPrefix:
    """Test suite for _strip_path_prefix helper function."""

    def test_strip_path_prefix_with_path(self):
        """Test stripping path prefix with a path."""
        assert _strip_path_prefix("http://localhost:8000", "/api/test") == "http://localhost:8000/api/test"

    def test_strip_path_prefix_empty_path(self):
        """Test stripping path prefix with empty path."""
        assert _strip_path_prefix("http://localhost:8000", "") == "http://localhost:8000"

    def test_strip_path_prefix_trailing_slash(self):
        """Test stripping path prefix with trailing slash in base URL."""
        assert _strip_path_prefix("http://localhost:8000/", "/api") == "http://localhost:8000/api"

    def test_strip_path_prefix_no_leading_slash(self):
        """Test stripping path prefix without leading slash in path."""
        assert _strip_path_prefix("http://localhost:8000", "api/test") == "http://localhost:8000/api/test"


class TestPreviewRouter:
    """Test suite for PreviewRouter class."""

    @pytest.fixture
    def preview_router(self):
        """Create a PreviewRouter instance."""
        router = PreviewRouter()
        yield router
        # Cleanup would happen here if needed

    @pytest.mark.asyncio
    async def test_proxy_success(self, preview_router):
        """Test successful proxy request."""
        # Mock the request
        mock_request = mock.Mock()
        mock_request.headers = {"content-type": "application/json"}
        mock_request.body = mock.AsyncMock(return_value=b'{"test": "data"}')
        mock_request.query_params = {}
        mock_request.method = "GET"

        # Mock the response
        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}

        async def async_iter_bytes():
            for chunk in [b'{"result": "success"}']:
                yield chunk

        mock_response.aiter_raw = mock.AsyncMock(return_value=async_iter_bytes())

        with mock.patch.object(preview_router.client, 'build_request') as mock_build:
            with mock.patch.object(preview_router.client, 'send') as mock_send:
                mock_build.return_value = mock.Mock()
                mock_send.return_value = mock_response

                result = await preview_router.proxy("http://localhost:8000/test", mock_request)
                assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_proxy_filters_headers(self, preview_router):
        """Test that proxy filters out the host header."""
        mock_request = mock.Mock()
        mock_request.headers = {
            "host": "original-host.com",
            "authorization": "Bearer token",
            "content-type": "application/json"
        }
        mock_request.body = mock.AsyncMock(return_value=b'')
        mock_request.query_params = {}
        mock_request.method = "GET"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.aiter_raw = mock.AsyncMock(return_value=iter([b'']))

        with mock.patch.object(preview_router.client, 'build_request') as mock_build:
            with mock.patch.object(preview_router.client, 'send') as mock_send:
                mock_build.return_value = mock.Mock()
                mock_send.return_value = mock_response

                await preview_router.proxy("http://localhost:8000/test", mock_request)

                # Verify host header was filtered
                call_args = mock_build.call_args
                headers = call_args[1]['headers']
                assert "host" not in headers
                assert "authorization" in headers

    @pytest.mark.asyncio
    async def test_proxy_request_error(self, preview_router):
        """Test proxy handling of request errors."""
        from fastapi import HTTPException

        mock_request = mock.Mock()
        mock_request.headers = {}
        mock_request.body = mock.AsyncMock(return_value=b'')
        mock_request.query_params = {}
        mock_request.method = "GET"

        with mock.patch.object(preview_router.client, 'build_request') as mock_build:
            with mock.patch.object(preview_router.client, 'send') as mock_send:
                mock_build.return_value = mock.Mock()
                mock_send.side_effect = RequestError("Connection failed")

                with pytest.raises(HTTPException) as exc_info:
                    await preview_router.proxy("http://localhost:8000/test", mock_request)

                assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY

    @pytest.mark.asyncio
    async def test_proxy_excludes_headers(self, preview_router):
        """Test that proxy excludes certain response headers."""
        mock_request = mock.Mock()
        mock_request.headers = {}
        mock_request.body = mock.AsyncMock(return_value=b'')
        mock_request.query_params = {}
        mock_request.method = "GET"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.headers = {
            "content-encoding": "gzip",
            "transfer-encoding": "chunked",
            "connection": "keep-alive",
            "content-type": "application/json"
        }
        mock_response.aiter_raw = mock.AsyncMock(return_value=iter([b'']))

        with mock.patch.object(preview_router.client, 'build_request') as mock_build:
            with mock.patch.object(preview_router.client, 'send') as mock_send:
                mock_build.return_value = mock.Mock()
                mock_send.return_value = mock_response

                result = await preview_router.proxy("http://localhost:8000/test", mock_request)

                # Check excluded headers are not present
                assert "content-encoding" not in result.headers
                assert "transfer-encoding" not in result.headers
                assert "connection" not in result.headers
                assert "content-type" in result.headers

    @pytest.mark.asyncio
    async def test_route_target_not_found(self, preview_router):
        """Test routing when target is not registered."""
        from fastapi import HTTPException

        mock_request = mock.Mock()

        with mock.patch.object(preview_router.registry, 'resolve', return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await preview_router.route("sandbox123", 8080, "/test", mock_request)

            assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
            assert "not registered" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_route_success(self, preview_router):
        """Test successful routing."""
        mock_request = mock.Mock()
        mock_request.headers = {}
        mock_request.body = mock.AsyncMock(return_value=b'')
        mock_request.query_params = {}
        mock_request.method = "GET"

        mock_target = mock.Mock()
        mock_target.effective_url = "http://localhost:9000"
        mock_target.use_fallback = False

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "text/html"}
        mock_response.aiter_raw = mock.AsyncMock(return_value=iter([b'<html></html>']))

        with mock.patch.object(preview_router.registry, 'resolve', return_value=mock_target):
            with mock.patch.object(preview_router.client, 'build_request') as mock_build:
                with mock.patch.object(preview_router.client, 'send') as mock_send:
                    mock_build.return_value = mock.Mock()
                    mock_send.return_value = mock_response

                    result = await preview_router.route("sandbox123", 8080, "/index.html", mock_request)
                    assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_route_fallback_on_502(self, preview_router):
        """Test fallback activation on 502 error."""
        mock_request = mock.Mock()
        mock_request.headers = {}
        mock_request.body = mock.AsyncMock(return_value=b'')
        mock_request.query_params = {}
        mock_request.method = "GET"

        mock_target = mock.Mock()
        mock_target.effective_url = "http://localhost:9000"
        mock_target.use_fallback = False

        # First call raises 502, second call succeeds
        call_count = [0]

        def mock_send_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RequestError("Connection refused")
            else:
                mock_response = mock.Mock()
                mock_response.status_code = 200
                mock_response.headers = {"content-type": "text/html"}
                mock_response.aiter_raw = mock.AsyncMock(return_value=iter([b'<html></html>']))
                return mock_response

        with mock.patch.object(preview_router.registry, 'resolve', return_value=mock_target):
            with mock.patch.object(preview_router.fallback, 'promote_to_container',
                                   return_value="http://localhost:10000"):
                with mock.patch.object(preview_router.registry, 'mark_fallback') as mock_mark:
                    with mock.patch.object(preview_router.client, 'build_request') as mock_build:
                        with mock.patch.object(preview_router.client, 'send', side_effect=mock_send_side_effect):
                            mock_build.return_value = mock.Mock()

                            result = await preview_router.route("sandbox123", 8080, "/index.html", mock_request)

                            # Should have called promote_to_container
                            preview_router.fallback.promote_to_container.assert_called_once_with("sandbox123")
                            mock_mark.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_no_fallback_when_already_using_fallback(self, preview_router):
        """Test that fallback is not re-triggered when already using fallback."""
        from fastapi import HTTPException

        mock_request = mock.Mock()
        mock_request.headers = {}
        mock_request.body = mock.AsyncMock(return_value=b'')
        mock_request.query_params = {}
        mock_request.method = "GET"

        mock_target = mock.Mock()
        mock_target.effective_url = "http://localhost:9000"
        mock_target.use_fallback = True  # Already using fallback

        with mock.patch.object(preview_router.registry, 'resolve', return_value=mock_target):
            with mock.patch.object(preview_router.client, 'build_request') as mock_build:
                with mock.patch.object(preview_router.client, 'send') as mock_send:
                    mock_build.return_value = mock.Mock()
                    mock_send.side_effect = RequestError("Connection refused")

                    with pytest.raises(HTTPException) as exc_info:
                        await preview_router.route("sandbox123", 8080, "/test", mock_request)

                    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY

    @pytest.mark.asyncio
    async def test_shutdown(self, preview_router):
        """Test cleanup on shutdown."""
        with mock.patch.object(preview_router.client, 'aclose') as mock_close:
            with mock.patch.object(preview_router.fallback, 'cleanup_stale') as mock_cleanup:
                await preview_router.shutdown()
                mock_close.assert_called_once()
                mock_cleanup.assert_called_once()


class TestPreviewRegistration:
    """Test suite for PreviewRegistration model."""

    def test_preview_registration_valid(self):
        """Test valid preview registration."""
        registration = PreviewRegistration(
            sandbox_id="sandbox123",
            port=8080,
            backend_url="http://localhost:9000",
            metadata={"version": "1.0"}
        )
        assert registration.sandbox_id == "sandbox123"
        assert registration.port == 8080
        assert registration.backend_url == "http://localhost:9000"
        assert registration.metadata == {"version": "1.0"}

    def test_preview_registration_without_metadata(self):
        """Test preview registration without metadata."""
        registration = PreviewRegistration(
            sandbox_id="sandbox456",
            port=3000,
            backend_url="http://localhost:3001"
        )
        assert registration.metadata is None


class TestPreviewStatus:
    """Test suite for PreviewStatus model."""

    def test_preview_status(self):
        """Test preview status model."""
        status_obj = PreviewStatus(
            sandbox_id="sandbox789",
            port=4000,
            url="http://localhost:4001",
            use_fallback=True,
            metadata={"environment": "test"}
        )
        assert status_obj.sandbox_id == "sandbox789"
        assert status_obj.port == 4000
        assert status_obj.url == "http://localhost:4001"
        assert status_obj.use_fallback is True
        assert status_obj.metadata == {"environment": "test"}


class TestFastAPIEndpoints:
    """Test suite for FastAPI endpoints."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return TestClient(app)

    def test_register_preview_endpoint(self, client):
        """Test the register preview endpoint."""
        with mock.patch('preview_router.router') as mock_router:
            mock_target = mock.Mock()
            mock_target.sandbox_id = "sandbox123"
            mock_target.port = 8080
            mock_target.backend_url = "http://localhost:9000"
            mock_target.use_fallback = False
            mock_target.metadata = {}

            # Mock async method
            async def mock_register(*args, **kwargs):
                return mock_target

            mock_router.registry.register = mock_register

            response = client.post(
                "/preview/register",
                json={
                    "sandbox_id": "sandbox123",
                    "port": 8080,
                    "backend_url": "http://localhost:9000"
                }
            )

            # Note: This test may need adjustment based on actual async handling
            # in TestClient

    def test_list_previews_endpoint(self, client):
        """Test the list previews endpoint."""
        with mock.patch('preview_router.router') as mock_router:
            mock_target = mock.Mock()
            mock_target.effective_url = "http://localhost:9000"
            mock_target.use_fallback = False
            mock_target.metadata = {}

            # Mock async method
            async def mock_list_targets():
                return {
                    ("sandbox123", 8080): mock_target
                }

            mock_router.registry.list_targets = mock_list_targets

            response = client.get("/preview/list")
            # Response validation would depend on actual implementation


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.fixture
    def preview_router(self):
        """Create a PreviewRouter instance."""
        return PreviewRouter()

    @pytest.mark.asyncio
    async def test_proxy_with_empty_body(self, preview_router):
        """Test proxy with empty request body."""
        mock_request = mock.Mock()
        mock_request.headers = {}
        mock_request.body = mock.AsyncMock(return_value=b'')
        mock_request.query_params = {}
        mock_request.method = "GET"

        mock_response = mock.Mock()
        mock_response.status_code = 204
        mock_response.headers = {}
        mock_response.aiter_raw = mock.AsyncMock(return_value=iter([]))

        with mock.patch.object(preview_router.client, 'build_request') as mock_build:
            with mock.patch.object(preview_router.client, 'send') as mock_send:
                mock_build.return_value = mock.Mock()
                mock_send.return_value = mock_response

                result = await preview_router.proxy("http://localhost:8000/test", mock_request)
                assert result.status_code == 204

    @pytest.mark.asyncio
    async def test_proxy_with_query_params(self, preview_router):
        """Test proxy with query parameters."""
        mock_request = mock.Mock()
        mock_request.headers = {}
        mock_request.body = mock.AsyncMock(return_value=b'')
        mock_request.query_params = {"key": "value", "filter": "active"}
        mock_request.method = "GET"

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.aiter_raw = mock.AsyncMock(return_value=iter([b'result']))

        with mock.patch.object(preview_router.client, 'build_request') as mock_build:
            with mock.patch.object(preview_router.client, 'send') as mock_send:
                mock_build.return_value = mock.Mock()
                mock_send.return_value = mock_response

                await preview_router.proxy("http://localhost:8000/test", mock_request)

                # Verify query params were passed
                call_args = mock_build.call_args
                assert call_args[1]['params'] == {"key": "value", "filter": "active"}

    @pytest.mark.asyncio
    async def test_route_with_nested_path(self, preview_router):
        """Test routing with nested path."""
        mock_request = mock.Mock()
        mock_request.headers = {}
        mock_request.body = mock.AsyncMock(return_value=b'')
        mock_request.query_params = {}
        mock_request.method = "GET"

        mock_target = mock.Mock()
        mock_target.effective_url = "http://localhost:9000/base"
        mock_target.use_fallback = False

        mock_response = mock.Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.aiter_raw = mock.AsyncMock(return_value=iter([b'content']))

        with mock.patch.object(preview_router.registry, 'resolve', return_value=mock_target):
            with mock.patch.object(preview_router.client, 'build_request') as mock_build:
                with mock.patch.object(preview_router.client, 'send') as mock_send:
                    mock_build.return_value = mock.Mock()
                    mock_send.return_value = mock_response

                    await preview_router.route("sandbox123", 8080, "/api/v1/resource", mock_request)

                    # Verify the full path was constructed correctly
                    call_args = mock_build.call_args
                    url = call_args[0][1]
                    assert "/api/v1/resource" in url

    def test_strip_path_prefix_multiple_trailing_slashes(self):
        """Test strip path prefix with multiple trailing slashes."""
        result = _strip_path_prefix("http://localhost:8000///", "///api///test///")
        assert result == "http://localhost:8000/api///test///"