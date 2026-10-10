"""In-process Streamable HTTP checks against create_serve_app()."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
import respx
from mcp.server import MCPServer

from yoast_mcp import server

PROTOCOL_VERSION = "2026-07-28"
PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"


def _headers(method: str, params: dict[str, Any] | None = None) -> dict[str, str]:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "mcp-protocol-version": PROTOCOL_VERSION,
        "mcp-method": method,
    }
    if method == "tools/call":
        headers["mcp-name"] = str((params or {})["name"])
    return headers


def _body(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    request_id: int = 1,
) -> dict[str, Any]:
    request_params = dict(params or {})
    request_params["_meta"] = {
        PROTOCOL_VERSION_META_KEY: PROTOCOL_VERSION,
        CLIENT_CAPABILITIES_META_KEY: {},
        CLIENT_INFO_META_KEY: {"name": "yoast-http-test", "version": "0"},
    }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": request_params,
    }


def _payload(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("text/event-stream"):
        data_lines = [
            line.removeprefix("data: ")
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]
        assert data_lines, response.text
        parsed = json.loads(data_lines[-1])
    else:
        parsed = response.json()
    assert parsed["jsonrpc"] == "2.0"
    return parsed


@asynccontextmanager
async def _http_client(
    app: Any,
    *,
    base_url: str = "http://127.0.0.1:8080",
) -> AsyncIterator[httpx.AsyncClient]:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=base_url) as client:
            yield client


async def _post(
    client: httpx.AsyncClient,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    header_overrides: dict[str, str] | None = None,
    request_id: int = 1,
) -> httpx.Response:
    headers = _headers(method, params)
    if header_overrides:
        headers.update(header_overrides)
    return await client.post(
        "/mcp",
        headers=headers,
        json=_body(method, params, request_id=request_id),
    )


def _loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YOAST_MCP_HOST", raising=False)
    monkeypatch.delenv("YOAST_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("YOAST_MCP_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("YOAST_MCP_TRANSPORT", raising=False)


async def test_tools_list_matches_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    _loopback(monkeypatch)
    stdio_tools = await server.mcp.list_tools()
    app = server.create_serve_app()
    async with _http_client(app) as client:
        response = await _post(client, "tools/list")

    result = _payload(response)["result"]
    http_tools = result["tools"]
    assert [tool["name"] for tool in http_tools] == [tool.name for tool in stdio_tools]
    for http_tool, stdio_tool in zip(http_tools, stdio_tools, strict=True):
        assert http_tool["inputSchema"] == stdio_tool.input_schema
    assert "mcp-session-id" not in response.headers


@respx.mock
async def test_read_tool_runs_over_http(monkeypatch: pytest.MonkeyPatch) -> None:
    _loopback(monkeypatch)
    route = respx.get("https://law.example/wp-json/wp/v2/posts/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "yoast_head": "<title>Tax</title>"})
    )
    app = server.create_serve_app()
    async with _http_client(app) as client:
        response = await _post(
            client,
            "tools/call",
            {"name": "get_post_seo_by_id", "arguments": {"id": 42}},
        )

    result = _payload(response)["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["post"]["id"] == 42
    assert route.call_count == 1


async def test_requests_share_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _loopback(monkeypatch)
    app = server.create_serve_app()
    async with _http_client(app) as client:
        first = await _post(client, "tools/list", request_id=1)
        second = await _post(
            client,
            "tools/list",
            header_overrides={"mcp-session-id": "not-a-session"},
            request_id=2,
        )

    assert "mcp-session-id" not in first.headers
    assert "mcp-session-id" not in second.headers
    assert _payload(first)["result"]["tools"] == _payload(second)["result"]["tools"]


def test_bogus_transport_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOAST_MCP_TRANSPORT", "bogus")
    with pytest.raises(SystemExit, match="stdio") as exc_info:
        server.main()
    message = str(exc_info.value)
    assert "streamable-http" in message
    assert "bogus" in message


def test_default_transport_is_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YOAST_MCP_TRANSPORT", raising=False)
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(server.MCPServer, "run", lambda self, **kwargs: seen.append(kwargs))
    server.main()
    assert seen == [{"transport": "stdio"}]


async def test_allowed_hosts_refuse_other_host_and_bad_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOAST_MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("YOAST_MCP_ALLOWED_HOSTS", "yoast.example")
    monkeypatch.setenv("YOAST_MCP_ALLOWED_ORIGINS", "https://yoast.example")
    app = server.create_serve_app()
    async with _http_client(app, base_url="http://yoast.example") as client:
        refused = await _post(client, "tools/list", header_overrides={"host": "other.example"})
        forbidden = await _post(
            client,
            "tools/list",
            header_overrides={"origin": "https://evil.example"},
            request_id=2,
        )

    assert refused.status_code == 421
    assert "Invalid Host" in refused.text
    assert forbidden.status_code == 403
    assert "Invalid Origin" in forbidden.text


def test_non_loopback_host_without_allowed_hosts_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOAST_MCP_HOST", "0.0.0.0")
    monkeypatch.delenv("YOAST_MCP_ALLOWED_HOSTS", raising=False)
    with pytest.raises(SystemExit, match="YOAST_MCP_ALLOWED_HOSTS"):
        server.create_serve_app()


async def test_get_delete_and_discover(monkeypatch: pytest.MonkeyPatch) -> None:
    _loopback(monkeypatch)
    app = server.create_serve_app()
    modern_headers = {
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": PROTOCOL_VERSION,
    }
    async with _http_client(app) as client:
        get_response = await client.get("/mcp", headers=modern_headers)
        delete_response = await client.delete("/mcp", headers=modern_headers)
        discover = await _post(client, "server/discover")

    assert get_response.status_code == 405
    assert delete_response.status_code == 405
    result = _payload(discover)["result"]
    assert PROTOCOL_VERSION in result["supportedVersions"]
    version = result["_meta"][SERVER_INFO_META_KEY]["version"]
    assert isinstance(version, str) and version


def test_non_integer_port_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "nope")
    with pytest.raises(SystemExit, match="PORT must be an integer"):
        server._port()


async def test_stateless_lifespan_runs_once_per_app_not_per_request() -> None:
    """create_serve_app() uses this same stateless app; the manager enters lifespan once."""
    entries = 0

    @asynccontextmanager
    async def lifespan(_app: MCPServer[Any]) -> AsyncIterator[dict[str, int]]:
        nonlocal entries
        entries += 1
        yield {"entries": entries}

    probe = MCPServer(
        name="lifespan-probe",
        title="Lifespan probe",
        version="0",
        lifespan=lifespan,
    )
    app = probe.streamable_http_app(
        streamable_http_path="/mcp",
        host="0.0.0.0",
        stateless_http=True,
    )
    async with _http_client(app, base_url="http://spec-test") as client:
        first = await _post(client, "tools/list", request_id=1)
        second = await _post(client, "tools/list", request_id=2)

    assert first.status_code == 200
    assert second.status_code == 200
    assert entries == 1


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_transport_selects_stdio(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("YOAST_MCP_TRANSPORT", raw)
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(server.MCPServer, "run", lambda self, **kwargs: seen.append(kwargs))
    server.main()
    assert seen == [{"transport": "stdio"}]


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_host_yields_loopback(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("YOAST_MCP_HOST", raw)
    assert server._host() == "127.0.0.1"
    monkeypatch.delenv("YOAST_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("YOAST_MCP_ALLOWED_ORIGINS", raising=False)
    server.create_serve_app()


def test_uppercase_localhost_is_non_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOAST_MCP_HOST", "LOCALHOST")
    assert server._host() == "LOCALHOST"
    monkeypatch.delenv("YOAST_MCP_ALLOWED_HOSTS", raising=False)
    with pytest.raises(SystemExit, match="YOAST_MCP_ALLOWED_HOSTS"):
        server.create_serve_app()


def test_server_import_without_installed_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib
    import importlib.metadata

    def _missing(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", _missing)
    importlib.reload(server)
