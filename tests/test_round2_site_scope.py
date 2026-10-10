"""Site metadata lookup policy through the real MCP boundary; no external I/O."""

from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from mcp import Client
from test_security_boundaries import BAD_URLS

from yoast_mcp import server

BAD_SITE_URLS = [
    "https://127.0.0.1.sslip.io/page",
    "https://redirect.example/redirect?url=http://169.254.169.254/latest/meta-data/",
    "https://unlisted.example/page",
    "https://sub.law.example/page",
    "https://law.example.attacker.example/page",
    "https://notlaw.example/page",
    "https://127.0.0.1./page",
    "https://127.1./page",
    "https://2130706433./page",
    "HTTPS://LOCALHOST/page",
]


@pytest.mark.parametrize("url", BAD_URLS + BAD_SITE_URLS)
async def test_rejected_page_zero_requests(monkeypatch, url):
    request = AsyncMock()
    monkeypatch.setattr(server, "_get_json", request)
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_url_seo_metadata", {"url": url})
    assert result.is_error
    assert (
        "public HTTPS" in result.content[0].text or "WORDPRESS_SITE_URL" in result.content[0].text
    )
    assert url not in result.content[0].text
    request.assert_not_awaited()


@pytest.mark.parametrize(
    ("site", "url"),
    [
        ("https://law.example", "https://law.example/practice/tax"),
        ("https://LAW.EXAMPLE.", "HTTPS://law.EXAMPLE./practice/tax?one=1"),
        ("https://bücher.example", "https://xn--bcher-kva.example/page"),
        ("https://XN--BCHER-KVA.EXAMPLE.", "https://xn--bcher-kva.example./page"),
    ],
)
@respx.mock
async def test_same_host_uses_configured_api_not_page(monkeypatch, site, url):
    monkeypatch.setenv("WORDPRESS_SITE_URL", site)
    route = respx.get(f"{site}/wp-json/yoast/v1/get_head", params={"url": url}).mock(
        return_value=httpx.Response(
            200, json={"html": "<title>Test</title>", "json": {}, "status": 200}
        )
    )
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_url_seo_metadata", {"url": url})
    assert not result.is_error, result
    assert route.call_count == 1
    assert len(respx.calls) == 1
    assert route.calls[0].request.url.path == "/wp-json/yoast/v1/get_head"
    assert route.calls[0].request.url.params["url"] == url


@pytest.mark.parametrize("site", [None, "", "http://law.example"])
async def test_missing_site_refuses_before_request(monkeypatch, site):
    if site is None:
        monkeypatch.delenv("WORDPRESS_SITE_URL")
    else:
        monkeypatch.setenv("WORDPRESS_SITE_URL", site)
    request = AsyncMock()
    monkeypatch.setattr(server, "_get_json", request)
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_url_seo_metadata", {"url": "https://law.example/page"})
    assert result.is_error
    assert "WORDPRESS_SITE_URL" in result.content[0].text
    request.assert_not_awaited()


async def test_model_cannot_override_site_or_use_allowlist(monkeypatch):
    monkeypatch.setenv("YOAST_ALLOWED_DESTINATION_HOSTS", "unlisted.example")
    request = AsyncMock()
    monkeypatch.setattr(server, "_get_json", request)
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "get_url_seo_metadata",
            {
                "url": "https://unlisted.example/page",
                "WORDPRESS_SITE_URL": "https://unlisted.example",
            },
        )
    assert result.is_error
    request.assert_not_awaited()


@respx.mock
async def test_unlisted_site_produces_no_http_requests():
    async with Client(server.mcp) as client:
        result = await client.call_tool(
            "get_url_seo_metadata", {"url": "https://unlisted.example/page"}
        )
    assert result.is_error
    assert len(respx.calls) == 0
