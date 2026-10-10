"""Shared offline test fixtures."""

from __future__ import annotations

import pytest

from yoast_mcp.config import Settings


@pytest.fixture(autouse=True)
def configured_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give server tools deterministic test-only credentials."""
    monkeypatch.setenv("WORDPRESS_SITE_URL", "https://law.example")
    monkeypatch.setenv("WORDPRESS_USERNAME", "seo_auditor")
    monkeypatch.setenv("WORDPRESS_APPLICATION_PASSWORD", "test application password")
    monkeypatch.delenv("YOAST_HTTP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("YOAST_MAX_RETRIES", raising=False)
    monkeypatch.delenv("YOAST_RETRY_BACKOFF_SECONDS", raising=False)


@pytest.fixture
def settings() -> Settings:
    """Return client settings containing test-only values."""
    return Settings(
        site_url="https://law.example",
        username="seo_auditor",
        application_password="test application password",
        timeout_seconds=5,
        max_retries=2,
        retry_backoff_seconds=0,
    )
