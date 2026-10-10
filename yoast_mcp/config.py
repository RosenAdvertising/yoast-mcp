"""Environment-only configuration for the Yoast SEO MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Raised when required server configuration is absent or invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated connection settings loaded exclusively from environment variables."""

    site_url: str
    username: str
    application_password: str
    timeout_seconds: float = 20.0
    max_retries: int = 3
    retry_backoff_seconds: float = 0.5

    @property
    def api_base_url(self) -> str:
        """Return the site's WordPress REST API root."""
        return f"{self.site_url.rstrip('/')}/wp-json/"

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from environment variables or raise an actionable error."""
        required = {
            "WORDPRESS_SITE_URL": os.getenv("WORDPRESS_SITE_URL", "").strip(),
            "WORDPRESS_USERNAME": os.getenv("WORDPRESS_USERNAME", "").strip(),
            "WORDPRESS_APPLICATION_PASSWORD": os.getenv(
                "WORDPRESS_APPLICATION_PASSWORD", ""
            ).strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            joined = ", ".join(missing)
            raise ConfigurationError(
                f"Missing required environment variable(s): {joined}. "
                "Set them before starting yoast-mcp."
            )

        site_url = required["WORDPRESS_SITE_URL"].rstrip("/")
        try:
            parsed = urlsplit(site_url)
            _ = parsed.port  # Accessing port also validates its syntax and range.
        except ValueError:
            raise ConfigurationError("WORDPRESS_SITE_URL must be a complete HTTP(S) URL.") from None
        if parsed.scheme != "https" or not parsed.netloc:
            raise ConfigurationError(
                "WORDPRESS_SITE_URL must be an HTTPS site origin, for example "
                "https://www.example.com."
            )
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ConfigurationError(
                "WORDPRESS_SITE_URL must contain only the site origin, without /wp-json, "
                "a path, query string, or fragment."
            )

        timeout_seconds = _positive_float("YOAST_HTTP_TIMEOUT_SECONDS", 20.0)
        max_retries = _nonnegative_int("YOAST_MAX_RETRIES", 3)
        retry_backoff_seconds = _nonnegative_float("YOAST_RETRY_BACKOFF_SECONDS", 0.5)

        return cls(
            site_url=site_url,
            username=required["WORDPRESS_USERNAME"],
            application_password=required["WORDPRESS_APPLICATION_PASSWORD"],
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number greater than zero.") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} must be a number greater than zero.")
    return value


def _nonnegative_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be zero or a positive number.") from exc
    if value < 0:
        raise ConfigurationError(f"{name} must be zero or a positive number.")
    return value


def _nonnegative_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be zero or a positive integer.") from exc
    if value < 0:
        raise ConfigurationError(f"{name} must be zero or a positive integer.")
    return value
