"""One fully mocked MCP round trip for every registered Yoast tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import respx
from mcp import Client

from yoast_mcp.server import mcp


@dataclass(frozen=True)
class ToolCase:
    name: str
    arguments: dict[str, Any]
    path: str
    response: httpx.Response
    expected_key: str


TOOL_CASES = [
    ToolCase(
        "get_url_seo_metadata",
        {"url": "https://law.example/practice/tax"},
        "yoast/v1/get_head",
        httpx.Response(
            200,
            json={
                "html": "&lt;title&gt;Tax&lt;/title&gt;",
                "json": {"title": "Tax"},
                "status": 200,
            },
        ),
        "metadata",
    ),
    ToolCase(
        "get_post_seo_by_id",
        {"id": 42},
        "wp/v2/posts/42",
        httpx.Response(200, json={"id": 42, "yoast_head": "&lt;title&gt;"}),
        "post",
    ),
    ToolCase(
        "get_post_seo_by_slug",
        {"slug": "tax-law", "limit": 10},
        "wp/v2/posts",
        httpx.Response(
            200,
            headers={"X-WP-Total": "1", "X-WP-TotalPages": "1"},
            json=[{"id": 42, "slug": "tax-law", "yoast_head_json": {}}],
        ),
        "posts",
    ),
    ToolCase(
        "get_recent_seo_scores",
        {"number_of_posts": 5},
        "wp-abilities/v1/abilities/yoast-seo/get-seo-scores/run",
        httpx.Response(
            200,
            json=[{"title": "Tax Law", "score": "good", "label": "Good", "focus_keyphrase": "tax"}],
        ),
        "scores",
    ),
    ToolCase(
        "get_recent_readability_scores",
        {"number_of_posts": 5},
        "wp-abilities/v1/abilities/yoast-seo/get-readability-scores/run",
        httpx.Response(200, json=[{"title": "Tax Law", "score": "ok", "label": "OK"}]),
        "scores",
    ),
    ToolCase(
        "get_recent_inclusive_language_scores",
        {"number_of_posts": 5},
        "wp-abilities/v1/abilities/yoast-seo/get-inclusive-language-scores/run",
        httpx.Response(200, json=[{"title": "Tax Law", "score": "good", "label": "Good"}]),
        "scores",
    ),
    ToolCase(
        "get_post_type_schema",
        {"post_type": "posts", "page": 2},
        "yoast/v1/schema-aggregator/get-schema/posts/2",
        httpx.Response(200, json={"@context": "https://schema.org", "@graph": []}),
        "body",
    ),
    ToolCase(
        "get_schema_map",
        {},
        "yoast/v1/schema-aggregator/get-xml",
        httpx.Response(
            200,
            headers={"Content-Type": "application/xml"},
            text='<?xml version="1.0"?><schemamap />',
        ),
        "xml",
    ),
    ToolCase(
        "get_custom_post_archive_seo",
        {"post_type": "attorney"},
        "wp/v2/types/attorney",
        httpx.Response(200, json={"slug": "attorney", "yoast_head_json": {"title": "Attorneys"}}),
        "post_type",
    ),
    ToolCase(
        "list_yoast_abilities",
        {"limit": 50},
        "wp-abilities/v1/abilities",
        httpx.Response(
            200,
            headers={"X-WP-Total": "3", "X-WP-TotalPages": "1"},
            json=[{"name": "yoast-seo/get-seo-scores"}],
        ),
        "abilities",
    ),
]


@pytest.mark.parametrize("case", TOOL_CASES, ids=lambda case: case.name)
@respx.mock
async def test_tool_makes_mocked_round_trip(case: ToolCase) -> None:
    route = respx.get(f"https://law.example/wp-json/{case.path}").mock(return_value=case.response)

    async with Client(mcp, raise_exceptions=True) as client:
        result = await client.call_tool(case.name, case.arguments)

    assert result.is_error is False
    assert result.structured_content is not None
    assert case.expected_key in result.structured_content
    assert route.call_count == 1


async def test_tool_catalog_is_read_only_typed_and_described() -> None:
    tools = await mcp.list_tools()

    assert {tool.name for tool in tools} == {case.name for case in TOOL_CASES}
    for tool in tools:
        assert tool.description
        assert "\n" not in tool.description.strip()
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        for property_schema in tool.input_schema.get("properties", {}).values():
            assert property_schema.get("description")
