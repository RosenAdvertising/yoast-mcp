"""Offline raw-wire regressions for the MCP 2026-07-28 migration."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import respx
from mcp import Client
from mcp_types.version import LATEST_PROTOCOL_VERSION, MODERN_PROTOCOL_VERSIONS

from yoast_mcp import server

PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSION = "2025-11-25"
PROTOCOL_VERSION_META_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_META_KEY = "io.modelcontextprotocol/clientCapabilities"
CLIENT_INFO_META_KEY = "io.modelcontextprotocol/clientInfo"
SERVER_INFO_META_KEY = "io.modelcontextprotocol/serverInfo"
EXPECTED_TOOLS = [
    "get_url_seo_metadata",
    "get_post_seo_by_id",
    "get_post_seo_by_slug",
    "get_recent_seo_scores",
    "get_recent_readability_scores",
    "get_recent_inclusive_language_scores",
    "get_post_type_schema",
    "get_schema_map",
    "get_custom_post_archive_seo",
    "list_yoast_abilities",
]


def _modern_request(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    protocol_version: str = PROTOCOL_VERSION,
    request_id: int = 1,
) -> tuple[dict[str, str], dict[str, Any]]:
    request_params = dict(params or {})
    request_params["_meta"] = {
        PROTOCOL_VERSION_META_KEY: protocol_version,
        CLIENT_CAPABILITIES_META_KEY: {},
        CLIENT_INFO_META_KEY: {"name": "yoast-spec-test", "version": "0"},
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "mcp-protocol-version": protocol_version,
        "mcp-method": method,
    }
    if method == "tools/call":
        headers["mcp-name"] = str(request_params["name"])
    elif method == "prompts/get":
        headers["mcp-name"] = str(request_params["name"])
    elif method == "resources/read":
        headers["mcp-name"] = str(request_params["uri"])
    return headers, {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": request_params,
    }


async def _post_modern(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    protocol_version: str = PROTOCOL_VERSION,
    header_overrides: dict[str, str] | None = None,
) -> httpx.Response:
    app = server.mcp.streamable_http_app(
        host="0.0.0.0",
        stateless_http=True,
        json_response=True,
    )
    headers, body = _modern_request(
        method,
        params,
        protocol_version=protocol_version,
    )
    if header_overrides:
        headers.update(header_overrides)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://spec-test",
        ) as client:
            return await client.post("/mcp", headers=headers, json=body)


def _result(response: httpx.Response) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    return payload["result"]


def test_protocol_revision_is_2026_07_28() -> None:
    """This repo has no tests/spec_check.py; the revision is pinned in-process."""
    assert server.PROTOCOL_VERSION == PROTOCOL_VERSION
    assert LATEST_PROTOCOL_VERSION == PROTOCOL_VERSION
    assert MODERN_PROTOCOL_VERSIONS == (PROTOCOL_VERSION,)


def test_modern_discovery_is_sessionless_and_declares_used_capabilities() -> None:
    response = asyncio.run(_post_modern("server/discover"))
    result = _result(response)

    assert "mcp-session-id" not in response.headers
    assert result["supportedVersions"] == [PROTOCOL_VERSION]
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == 0
    assert result["cacheScope"] == "private"
    assert result["capabilities"] == {
        "prompts": {"listChanged": True},
        "resources": {"listChanged": True, "subscribe": True},
        "tools": {"listChanged": True},
    }
    assert "extensions" not in result["capabilities"]
    assert result["_meta"][SERVER_INFO_META_KEY]["name"] == "yoast-seo"
    assert result["_meta"][SERVER_INFO_META_KEY]["version"]


def test_client_negotiates_modern_and_keeps_legacy_compatibility() -> None:
    async def negotiate() -> tuple[str, str]:
        async with Client(server.mcp, cache=None) as modern:
            modern_version = modern.protocol_version
        async with Client(server.mcp, mode="legacy", cache=None) as legacy:
            legacy_version = legacy.protocol_version
        return modern_version, legacy_version

    modern_version, legacy_version = asyncio.run(negotiate())
    assert modern_version == PROTOCOL_VERSION
    assert legacy_version == LEGACY_PROTOCOL_VERSION


def test_cacheable_results_are_complete_private_and_deterministic() -> None:
    async def list_results() -> list[dict[str, Any]]:
        methods = (
            "tools/list",
            "tools/list",
            "prompts/list",
            "resources/list",
            "resources/templates/list",
        )
        return [_result(await _post_modern(method)) for method in methods]

    first_tools, second_tools, prompts, resources, templates = asyncio.run(list_results())
    for result in (first_tools, second_tools, prompts, resources, templates):
        assert result["resultType"] == "complete"
        assert result["ttlMs"] == 0
        assert result["cacheScope"] == "private"

    first_names = [tool["name"] for tool in first_tools["tools"]]
    second_names = [tool["name"] for tool in second_tools["tools"]]
    assert first_names == second_names == EXPECTED_TOOLS
    assert all(tool["inputSchema"]["type"] == "object" for tool in first_tools["tools"])
    assert prompts["prompts"] == []
    assert resources["resources"] == []
    assert templates["resourceTemplates"] == []


def test_missing_resource_is_invalid_params() -> None:
    missing = asyncio.run(_post_modern("resources/read", {"uri": "yoast://does-not-exist"}))
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == -32602


@respx.mock
def test_modern_tool_results_are_structured_and_complete() -> None:
    respx.get("https://law.example/wp-json/wp/v2/posts/42").mock(
        return_value=httpx.Response(200, json={"id": 42, "yoast_head": "<title>Tax</title>"})
    )
    response = asyncio.run(
        _post_modern(
            "tools/call",
            {"name": "get_post_seo_by_id", "arguments": {"id": 42}},
        )
    )
    result = _result(response)
    assert result["isError"] is False
    assert result["resultType"] == "complete"
    assert result["structuredContent"]["post"]["id"] == 42
    assert '"id": 42' in result["content"][0]["text"] or '"id":42' in result["content"][0]["text"]


def test_modern_http_enforces_routing_headers_versions_and_method_errors() -> None:
    named_headers, _ = _modern_request(
        "tools/call",
        {"name": "get_post_seo_by_id", "arguments": {"id": 1}},
    )
    assert named_headers["mcp-protocol-version"] == PROTOCOL_VERSION
    assert named_headers["mcp-method"] == "tools/call"
    assert named_headers["mcp-name"] == "get_post_seo_by_id"

    mismatch = asyncio.run(
        _post_modern(
            "tools/list",
            header_overrides={"mcp-method": "resources/list"},
        )
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == -32020

    named_mismatch = asyncio.run(
        _post_modern(
            "tools/call",
            {"name": "get_post_seo_by_id", "arguments": {"id": 1}},
            header_overrides={"mcp-name": "get_schema_map"},
        )
    )
    assert named_mismatch.status_code == 400
    assert named_mismatch.json()["error"]["code"] == -32020

    unsupported = asyncio.run(_post_modern("tools/list", protocol_version="2099-01-01"))
    assert unsupported.status_code == 400
    assert unsupported.json()["error"] == {
        "code": -32022,
        "message": "Unsupported protocol version",
        "data": {
            "supported": [PROTOCOL_VERSION],
            "requested": "2099-01-01",
        },
    }

    unknown = asyncio.run(_post_modern("example/unknown"))
    assert unknown.status_code == 404
    assert unknown.json()["error"] == {
        "code": -32601,
        "message": "Method not found",
        "data": "example/unknown",
    }
