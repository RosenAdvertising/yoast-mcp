"""MCP revision conformance checks."""

from __future__ import annotations

from mcp import Client
from mcp_types.version import LATEST_PROTOCOL_VERSION, MODERN_PROTOCOL_VERSIONS

from yoast_mcp.server import PROTOCOL_VERSION, mcp


async def test_server_initialization_declares_2026_07_28_protocol() -> None:
    """The v2 discovery path replacing initialize must select the required revision."""
    async with Client(mcp, mode=PROTOCOL_VERSION) as client:
        assert client.protocol_version == "2026-07-28"

    assert LATEST_PROTOCOL_VERSION == "2026-07-28"
    assert MODERN_PROTOCOL_VERSIONS == ("2026-07-28",)
