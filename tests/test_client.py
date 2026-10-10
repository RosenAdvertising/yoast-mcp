"""Fully mocked tests for authentication, retries, errors, and pagination."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from yoast_mcp.client import YoastAPIError, YoastClient
from yoast_mcp.config import Settings


@respx.mock
async def test_client_happy_path_sends_basic_auth(settings: Settings) -> None:
    route = respx.get("https://law.example/wp-json/wp/v2/posts/17").mock(
        return_value=httpx.Response(200, json={"id": 17, "yoast_head_json": {"title": "Tax"}})
    )

    async with YoastClient(settings) as client:
        result = await client.get_json("wp/v2/posts/17")

    assert result == {"id": 17, "yoast_head_json": {"title": "Tax"}}
    expected = base64.b64encode(b"seo_auditor:test application password").decode()
    assert route.calls[0].request.headers["Authorization"] == f"Basic {expected}"


@respx.mock
async def test_client_surfaces_vendor_auth_failure(settings: Settings) -> None:
    respx.get("https://law.example/wp-json/wp-abilities/v1/abilities").mock(
        return_value=httpx.Response(
            403,
            json={
                "code": "ability_invalid_permissions",
                "message": "You are not allowed to execute this ability.",
                "data": {"status": 403},
            },
        )
    )

    async with YoastClient(settings) as client:
        with pytest.raises(YoastAPIError) as exc_info:
            await client.get_json("wp-abilities/v1/abilities")

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "ability_invalid_permissions"
    assert "You are not allowed to execute this ability." in str(exc_info.value)


@respx.mock
async def test_client_retries_429_and_honors_retry_after(settings: Settings) -> None:
    route = respx.get("https://law.example/wp-json/yoast/v1/get_head").mock(
        side_effect=[
            httpx.Response(
                429,
                headers={"Retry-After": "1.25"},
                json={"code": "rest_rate_limited", "message": "Slow down."},
            ),
            httpx.Response(200, json={"html": "&lt;title&gt;", "json": {}, "status": 200}),
        ]
    )
    delays: list[float] = []

    async def record_delay(seconds: float) -> None:
        delays.append(seconds)

    async with YoastClient(settings, sleeper=record_delay) as client:
        result = await client.get_json("yoast/v1/get_head", params={"url": "https://law.example/"})

    assert result == {"html": "&lt;title&gt;", "json": {}, "status": 200}
    assert route.call_count == 2
    assert delays == [1.25]


@respx.mock
async def test_client_paginates_and_caps_wordpress_page_size(settings: Settings) -> None:
    route = respx.get("https://law.example/wp-json/wp-abilities/v1/abilities").mock(
        side_effect=[
            httpx.Response(
                200,
                headers={"X-WP-Total": "150", "X-WP-TotalPages": "2"},
                json=[{"name": f"ability-{index}"} for index in range(100)],
            ),
            httpx.Response(
                200,
                headers={"X-WP-Total": "150", "X-WP-TotalPages": "2"},
                json=[{"name": f"ability-{index}"} for index in range(100, 150)],
            ),
        ]
    )

    async with YoastClient(settings) as client:
        result = await client.paginate(
            "wp-abilities/v1/abilities",
            limit=150,
            params={"category": "yoast-seo"},
        )

    assert len(result) == 150
    assert route.call_count == 2
    first_query = route.calls[0].request.url.params
    second_query = route.calls[1].request.url.params
    assert first_query["per_page"] == "100"
    assert first_query["page"] == "1"
    assert second_query["per_page"] == "50"
    assert second_query["page"] == "2"
    assert first_query["category"] == "yoast-seo"


@respx.mock
async def test_get_head_preserves_metadata_body_on_transport_404(settings: Settings) -> None:
    body = {"html": "&lt;meta name=robots content=noindex&gt;", "json": {}, "status": 404}
    respx.get("https://law.example/wp-json/yoast/v1/get_head").mock(
        return_value=httpx.Response(404, json=body)
    )

    async with YoastClient(settings) as client:
        result = await client.get_json(
            "yoast/v1/get_head",
            params={"url": "https://law.example/missing"},
            accept_yoast_metadata_error=True,
        )

    assert result == body
