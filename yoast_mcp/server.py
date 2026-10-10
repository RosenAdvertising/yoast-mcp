"""MCP tool registration and stdio or Streamable HTTP entry point for Yoast SEO."""

from __future__ import annotations

import asyncio
import os
import re
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette

from yoast_mcp import __version__
from yoast_mcp.client import JsonValue, YoastAPIError, YoastClient
from yoast_mcp.config import ConfigurationError, Settings
from yoast_mcp.paths import path_id
from yoast_mcp.runtime import SafeMCPServer as MCPServer
from yoast_mcp.runtime import safe_error
from yoast_mcp.urls import site_https

PROTOCOL_VERSION = "2026-07-28"
STREAMABLE_HTTP_TRANSPORT = "streamable-http"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_POST_TYPE_PATTERN = re.compile(r"^[a-z0-9_-]+$")
_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

mcp = MCPServer(
    name="yoast-seo",
    title="Yoast SEO",
    version=__version__,
    description="Read-only access to Yoast SEO metadata on a WordPress site.",
    instructions=(
        "Use these read-only tools to audit public WordPress content, Yoast scores, "
        "social metadata, canonical URLs, indexing directives, and structured data."
    ),
)


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
async def get_url_seo_metadata(
    url: Annotated[
        str,
        Field(
            description=(
                "Absolute public URL whose Yoast title, description, and other metadata "
                "to retrieve."
            )
        ),
    ],
) -> dict[str, JsonValue]:
    """Get all Yoast SEO metadata for a public web page."""
    _validate_absolute_url(url)
    payload = await _get_json(
        "yoast/v1/get_head",
        params={"url": url},
        accept_yoast_metadata_error=True,
    )
    return {"metadata": payload}


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
async def get_post_seo_by_id(
    id: Annotated[int, Field(ge=1, description="Numeric WordPress post ID.")],
) -> dict[str, JsonValue]:
    """Get a WordPress post and its Yoast SEO metadata by post ID."""
    payload = await _get_json(f"wp/v2/posts/{path_id(id, 'id')}")
    return {"post": payload}


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
async def get_post_seo_by_slug(
    slug: Annotated[str, Field(min_length=1, description="Exact WordPress post slug to find.")],
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Maximum matching posts to return; WordPress permits at most 100 per page.",
        ),
    ] = 10,
    page: Annotated[
        int,
        Field(ge=1, description="WordPress result page to start from."),
    ] = 1,
) -> dict[str, JsonValue]:
    """Find posts by slug and include each post's Yoast SEO metadata."""
    posts = await _paginate(
        "wp/v2/posts",
        limit=limit,
        page=page,
        params={"slug": slug},
    )
    return {"posts": posts, "count": len(posts)}


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
async def get_recent_seo_scores(
    number_of_posts: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Number of recently modified posts to audit, from 1 to 100.",
        ),
    ] = 10,
) -> dict[str, JsonValue]:
    """Review Yoast SEO scores and focus keyphrases for recently changed posts."""
    scores = await _get_list(
        "wp-abilities/v1/abilities/yoast-seo/get-seo-scores/run",
        params={"input[number_of_posts]": number_of_posts},
    )
    return {"scores": scores, "count": len(scores)}


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
async def get_recent_readability_scores(
    number_of_posts: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Number of recently modified posts to audit, from 1 to 100.",
        ),
    ] = 10,
) -> dict[str, JsonValue]:
    """Review Yoast readability scores for recently changed posts."""
    scores = await _get_list(
        "wp-abilities/v1/abilities/yoast-seo/get-readability-scores/run",
        params={"input[number_of_posts]": number_of_posts},
    )
    return {"scores": scores, "count": len(scores)}


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
async def get_recent_inclusive_language_scores(
    number_of_posts: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Number of recently modified posts to audit, from 1 to 100.",
        ),
    ] = 10,
) -> dict[str, JsonValue]:
    """Review Yoast inclusive-language scores for recently changed posts."""
    scores = await _get_list(
        "wp-abilities/v1/abilities/yoast-seo/get-inclusive-language-scores/run",
        params={"input[number_of_posts]": number_of_posts},
    )
    return {"scores": scores, "count": len(scores)}


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
async def get_post_type_schema(
    post_type: Annotated[
        str,
        Field(
            description=(
                "Registered public WordPress post-type name, such as posts, pages, or product."
            )
        ),
    ],
    page: Annotated[
        int,
        Field(ge=1, description="Schema Aggregator page number to retrieve."),
    ] = 1,
) -> dict[str, JsonValue]:
    """Get combined Schema.org data for one WordPress content type and page."""
    _validate_post_type(post_type)
    result = await _get_schema_page(
        f"yoast/v1/schema-aggregator/get-schema/{path_id(post_type, 'post_type')}"
        f"/{path_id(page, 'page')}"
    )
    return {"post_type": post_type, "page": page, **result}


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
async def get_schema_map() -> dict[str, JsonValue]:
    """Get the XML map of enabled Yoast Schema Aggregator endpoints."""
    xml, content_type = await _get_text("yoast/v1/schema-aggregator/get-xml")
    return {"xml": xml, "content_type": content_type}


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
async def get_custom_post_archive_seo(
    post_type: Annotated[
        str,
        Field(
            description=(
                "Registered custom post-type name, which may differ from its public archive slug."
            )
        ),
    ],
) -> dict[str, JsonValue]:
    """Get Yoast SEO metadata for a custom post type's archive."""
    _validate_post_type(post_type)
    payload = await _get_json(f"wp/v2/types/{path_id(post_type, 'post_type')}")
    return {"post_type": payload}


@mcp.tool(annotations=_READ_ONLY, structured_output=True)
async def list_yoast_abilities(
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=500,
            description="Maximum Yoast ability definitions to return across pages.",
        ),
    ] = 50,
    page: Annotated[
        int,
        Field(ge=1, description="WordPress Abilities result page to start from."),
    ] = 1,
) -> dict[str, JsonValue]:
    """List available Yoast abilities and the inputs and outputs they support."""
    abilities = await _paginate(
        "wp-abilities/v1/abilities",
        limit=limit,
        page=page,
        params={"category": "yoast-seo"},
    )
    return {"abilities": abilities, "count": len(abilities)}


async def _get_json(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    accept_yoast_metadata_error: bool = False,
) -> JsonValue:
    try:
        async with YoastClient(Settings.from_env()) as client:
            return await client.get_json(
                path,
                params=params,
                accept_yoast_metadata_error=accept_yoast_metadata_error,
            )
    except (ConfigurationError, YoastAPIError) as exc:
        raise safe_error(exc) from None


async def _get_list(path: str, *, params: dict[str, Any]) -> list[Any]:
    payload = await _get_json(path, params=params)
    if not isinstance(payload, list):
        raise ToolError("The WordPress endpoint returned JSON that was not an array.")
    return payload


async def _get_text(path: str) -> tuple[str, str]:
    try:
        async with YoastClient(Settings.from_env()) as client:
            return await client.get_text(path)
    except (ConfigurationError, YoastAPIError) as exc:
        raise safe_error(exc) from None


async def _get_schema_page(path: str) -> dict[str, JsonValue]:
    try:
        async with YoastClient(Settings.from_env()) as client:
            return await client.get_schema_page(path)
    except (ConfigurationError, YoastAPIError) as exc:
        raise safe_error(exc) from None


async def _paginate(
    path: str,
    *,
    limit: int,
    page: int,
    params: dict[str, Any],
) -> list[Any]:
    try:
        async with YoastClient(Settings.from_env()) as client:
            return await client.paginate(path, limit=limit, page=page, params=params)
    except (ConfigurationError, YoastAPIError, ValueError) as exc:
        raise safe_error(exc) from None


def _validate_post_type(post_type: str) -> None:
    if not _POST_TYPE_PATTERN.fullmatch(post_type):
        raise ToolError(
            "post_type must use the registered WordPress name and contain only "
            "lowercase letters, numbers, underscores, or hyphens."
        )


def _validate_absolute_url(url: str) -> None:
    site_https(url)


def _requested_transport() -> str:
    return os.environ.get("YOAST_MCP_TRANSPORT", "stdio").strip().lower() or "stdio"


def _host() -> str:
    return os.environ.get("YOAST_MCP_HOST", "127.0.0.1").strip() or "127.0.0.1"


def _port() -> int:
    raw = os.environ.get("PORT", "8080").strip()
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"PORT must be an integer, got {raw!r}") from None


def _comma_list(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _transport_security() -> TransportSecuritySettings | None:
    """Origin checks are required off loopback. The SDK covers loopback itself."""
    host = _host()
    if host in _LOOPBACK_HOSTS:
        return None
    allowed_hosts = _comma_list("YOAST_MCP_ALLOWED_HOSTS")
    if not allowed_hosts:
        raise SystemExit(
            "YOAST_MCP_ALLOWED_HOSTS must list at least one host when "
            f"YOAST_MCP_HOST is {host!r}, which is not a loopback address."
        )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=_comma_list("YOAST_MCP_ALLOWED_ORIGINS"),
    )


def create_serve_app() -> Starlette:
    """Build the stateless Streamable HTTP app. SSE stays the default so disconnect cancels work."""
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        host=_host(),
        stateless_http=True,
        transport_security=_transport_security(),
    )


async def _serve_streamable_http() -> None:
    import uvicorn

    config = uvicorn.Config(
        create_serve_app(),
        host=_host(),
        port=_port(),
        access_log=False,
    )
    await uvicorn.Server(config).serve()


def main() -> None:
    """Run stdio, or stateless Streamable HTTP. Tools read credentials from the environment."""
    transport = _requested_transport()
    if transport == "stdio":
        mcp.run(transport="stdio")
        return
    if transport == STREAMABLE_HTTP_TRANSPORT:
        asyncio.run(_serve_streamable_http())
        return
    raise SystemExit(
        "Unsupported YOAST_MCP_TRANSPORT "
        f"{transport!r}; expected 'stdio' or '{STREAMABLE_HTTP_TRANSPORT}'."
    )


if __name__ == "__main__":
    main()
