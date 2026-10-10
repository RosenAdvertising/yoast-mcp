"""Configuration and startup behavior tests."""

from __future__ import annotations

import pytest

from yoast_mcp.config import ConfigurationError, Settings


def test_missing_credentials_name_every_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "WORDPRESS_SITE_URL",
        "WORDPRESS_USERNAME",
        "WORDPRESS_APPLICATION_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ConfigurationError) as exc_info:
        Settings.from_env()

    message = str(exc_info.value)
    assert "WORDPRESS_SITE_URL" in message
    assert "WORDPRESS_USERNAME" in message
    assert "WORDPRESS_APPLICATION_PASSWORD" in message


def test_startup_without_credentials_runs_stdio(monkeypatch, capsys) -> None:
    from yoast_mcp import server
    from yoast_mcp.runtime import MCPServer

    seen = []
    monkeypatch.setattr(MCPServer, "run", lambda self, **kwargs: seen.append(kwargs))
    server.main()
    assert seen == [{"transport": "stdio"}]
    assert "Traceback" not in capsys.readouterr().err


def test_site_url_requires_https_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORDPRESS_SITE_URL", "http://law.example/wp-json")

    with pytest.raises(ConfigurationError, match="WORDPRESS_SITE_URL"):
        Settings.from_env()
