"""Exact destination fields and opaque text through the real MCP client/server."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from mcp import Client
from test_round2_site_scope import BAD_SITE_URLS
from test_security_boundaries import BAD_URLS

from yoast_mcp import server
from yoast_mcp.runtime import SafeMCPServer

REVIEW_BAD_URLS = [
    "https://169.254.169.254.nip.io/x",
    "https://foo.localtest.me/x",
    "https://redirect.example/redirect?url=http://127.0.0.1/",
    "https://law.example.evil.test/page",
    "https://evil-law.example/page",
    "https://user@law.example/page",
    "https://law.example@evil.test/page",
    "https://law.example:99999/page",
    "https://law.example/page#fragment",
]


@pytest.fixture
def payload_server():
    app = SafeMCPServer("url-field-regression")
    dispatched = []

    @app.tool()
    async def inspect_payload(payload: dict | None = None, payload_json: str = "") -> dict:
        dispatched.append((payload, payload_json))
        return {"accepted": True}

    return app, dispatched


@pytest.mark.parametrize("key", ["furlong", "curl_options", "my_endpoint", "url2"])
@pytest.mark.parametrize("encoded", [False, True])
async def test_unrelated_keys_pass(payload_server, key, encoded):
    app, dispatched = payload_server
    payload = {key: 7}
    arguments = {"payload_json": json.dumps(payload)} if encoded else {"payload": payload}
    async with Client(app) as client:
        result = await client.call_tool("inspect_payload", arguments)
    assert not result.is_error, result
    assert dispatched == ([(None, json.dumps(payload))] if encoded else [(payload, "")])


@pytest.mark.parametrize(
    "text",
    ['{"url":"http://localhost/notes"}', '[{"target_url":"https://unlisted.example/"}]'],
)
@respx.mock
async def test_production_slug_stays_text(text):
    route = respx.get("https://law.example/wp-json/wp/v2/posts").mock(
        return_value=httpx.Response(200, json=[])
    )
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_post_seo_by_slug", {"slug": text})
    assert not result.is_error, result
    assert route.call_count == 1
    assert len(respx.calls) == 1
    assert route.calls[0].request.url.params["slug"] == text


@pytest.mark.parametrize("nullable", [False, True])
async def test_free_text_stays_text(nullable):
    app = SafeMCPServer("text-regression")
    dispatched = []

    async def inspect_text(description):
        dispatched.append(description)
        return {"accepted": True}

    inspect_text.__annotations__ = {"description": str | None if nullable else str}
    app.add_tool(inspect_text)
    text = '{"url":"http://localhost/notes"}'
    async with Client(app) as client:
        result = await client.call_tool("inspect_text", {"description": text})
    assert not result.is_error, result
    assert dispatched == [text]


async def test_nested_ordinary_text_is_opaque(payload_server):
    app, dispatched = payload_server
    payload = {"description": '{"target_url":"http://localhost/notes"}'}
    async with Client(app) as client:
        result = await client.call_tool("inspect_payload", {"payload_json": json.dumps(payload)})
    assert not result.is_error, result
    assert dispatched == [(None, json.dumps(payload))]


@pytest.mark.parametrize("url", BAD_URLS + BAD_SITE_URLS + REVIEW_BAD_URLS)
async def test_earlier_probes_in_declared_json_refused(payload_server, url):
    app, dispatched = payload_server
    async with Client(app) as client:
        result = await client.call_tool(
            "inspect_payload",
            {"payload_json": json.dumps({"nested": [{"target_url": url}]})},
        )
    assert result.is_error
    assert url not in result.content[0].text
    assert dispatched == []


@pytest.mark.parametrize("url", REVIEW_BAD_URLS)
async def test_remaining_rereview_page_probes_refused(monkeypatch, url):
    request = AsyncMock()
    monkeypatch.setattr(server, "_get_json", request)
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_url_seo_metadata", {"url": url})
    assert result.is_error
    request.assert_not_awaited()


@pytest.mark.parametrize(
    "key",
    [
        "url",
        "urls",
        "uri",
        "uris",
        "href",
        "callback",
        "endpoint",
        "callbackUrl",
        "callback_uri",
        "target_url",
        "TARGET-URI",
        "redirectUrl",
        "redirectUrls",
        "urlToFetch",
        "url_list",
        "baseUrl",
        "baseUrlPattern",
        "webhook_url",
        "uploadUrl",
        "downloadUrl",
        "storage_url",
        "destinationUrl",
    ],
)
@pytest.mark.parametrize("encoded", [False, True])
async def test_exact_destination_names_checked(payload_server, key, encoded):
    app, dispatched = payload_server
    payload = {"nested": [{key: "https://unlisted.example/page"}]}
    arguments = {"payload_json": json.dumps(payload)} if encoded else {"payload": payload}
    async with Client(app) as client:
        result = await client.call_tool("inspect_payload", arguments)
    assert result.is_error
    assert "WORDPRESS_SITE_URL" in result.content[0].text
    assert dispatched == []


async def test_declared_json_allows_same_site_destination(payload_server):
    app, dispatched = payload_server
    payload_json = json.dumps({"nested": [{"target_url": "https://law.example/page"}]})
    async with Client(app) as client:
        result = await client.call_tool("inspect_payload", {"payload_json": payload_json})
    assert not result.is_error, result
    assert dispatched == [(None, payload_json)]
