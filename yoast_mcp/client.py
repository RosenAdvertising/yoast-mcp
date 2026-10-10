"""Thin asynchronous client for the documented Yoast and WordPress REST surfaces."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from yoast_mcp.config import Settings
from yoast_mcp.urls import validate_url_arguments

JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None
Sleeper = Callable[[float], Awaitable[None]]


class YoastAPIError(RuntimeError):
    """An honest, user-displayable Yoast or WordPress REST API error."""

    def __init__(
        self,
        *,
        status_code: int | None,
        message: str,
        code: str | None = None,
        data: JsonValue = None,
        additional_errors: JsonValue = None,
    ) -> None:
        self.status_code = status_code
        self.message = message
        self.code = code
        self.data = data
        self.additional_errors = additional_errors
        super().__init__(self.__str__())

    def __str__(self) -> str:
        details = []
        if self.status_code is not None:
            details.append(f"HTTP {self.status_code}")
        if self.code:
            details.append(self.code)
        suffix = f" ({', '.join(details)})" if details else ""
        return f"{self.message}{suffix}"

    def as_dict(self) -> dict[str, JsonValue]:
        """Return all vendor error fields as structured JSON."""
        return {
            "status_code": self.status_code,
            "code": self.code,
            "message": self.message,
            "data": self.data,
            "additional_errors": self.additional_errors,
        }


class YoastClient:
    """Authenticated HTTP client with bounded retries and WordPress pagination."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self._sleeper = sleeper
        self._http = httpx.AsyncClient(
            base_url=settings.api_base_url,
            auth=httpx.BasicAuth(settings.username, settings.application_password),
            headers={"Accept": "application/json, application/xml, text/xml;q=0.9"},
            timeout=settings.timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> YoastClient:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        accept_yoast_metadata_error: bool = False,
    ) -> httpx.Response:
        """Send one request, retrying only throttling and temporary server failures."""
        attempts = self.settings.max_retries + 1
        response: httpx.Response | None = None

        validate_url_arguments(params, site_url=self.settings.site_url)
        for attempt in range(attempts):
            try:
                response = await self._http.request(method, path, params=params)
            except httpx.TransportError as exc:
                raise YoastAPIError(
                    status_code=None,
                    message=f"Could not reach the WordPress site: {exc}",
                ) from exc

            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < self.settings.max_retries:
                await self._sleeper(self._retry_delay(response, attempt))
                continue

            if response.is_error:
                if accept_yoast_metadata_error and self._is_yoast_metadata(response):
                    return response
                raise self._error_from_response(response)
            return response

        if response is None:  # pragma: no cover - defensive; the loop always executes.
            raise YoastAPIError(status_code=None, message="The request did not run.")
        raise self._error_from_response(response)  # pragma: no cover

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        accept_yoast_metadata_error: bool = False,
    ) -> JsonValue:
        """Fetch a JSON response and reject undocumented non-JSON bodies."""
        response = await self.request(
            "GET",
            path,
            params=params,
            accept_yoast_metadata_error=accept_yoast_metadata_error,
        )
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise YoastAPIError(
                status_code=response.status_code,
                message="The WordPress site returned a non-JSON response.",
            ) from exc

    async def get_text(
        self, path: str, *, params: Mapping[str, Any] | None = None
    ) -> tuple[str, str]:
        """Fetch text while preserving the vendor's reported content type."""
        response = await self.request("GET", path, params=params)
        return response.text, response.headers.get("content-type", "")

    async def get_schema_page(self, path: str) -> dict[str, JsonValue]:
        """Preserve Schema Aggregator output whether the site emits JSON or raw text."""
        response = await self.request("GET", path)
        content_type = response.headers.get("content-type", "")
        try:
            body: JsonValue = response.json()
            wire_format = "json"
        except json.JSONDecodeError:
            body = response.text
            wire_format = "raw"
        return {
            "content_type": content_type,
            "wire_format": wire_format,
            "body": body,
        }

    async def paginate(
        self,
        path: str,
        *,
        limit: int,
        page: int = 1,
        params: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        """Collect a bounded number of records from a WordPress collection."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if page < 1:
            raise ValueError("page must be at least 1")

        collected: list[Any] = []
        current_page = page
        base_params = dict(params or {})

        while len(collected) < limit:
            per_page = min(100, limit - len(collected))
            request_params = {**base_params, "page": current_page, "per_page": per_page}
            response = await self.request("GET", path, params=request_params)
            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise YoastAPIError(
                    status_code=response.status_code,
                    message="The WordPress collection returned a non-JSON response.",
                ) from exc
            if not isinstance(payload, list):
                raise YoastAPIError(
                    status_code=response.status_code,
                    message="The WordPress collection returned JSON that was not an array.",
                )

            collected.extend(payload[: limit - len(collected)])
            if not payload:
                break

            total_pages = _integer_header(response, "X-WP-TotalPages")
            if total_pages is not None:
                if current_page >= total_pages:
                    break
            elif len(payload) < per_page:
                break
            current_page += 1

        return collected

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
                except (TypeError, ValueError, OverflowError):
                    pass
        return self.settings.retry_backoff_seconds * (2**attempt)

    @staticmethod
    def _is_yoast_metadata(response: httpx.Response) -> bool:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            return False
        return (
            isinstance(payload, dict)
            and "html" in payload
            and "json" in payload
            and isinstance(payload.get("status"), int)
        )

    @staticmethod
    def _error_from_response(response: httpx.Response) -> YoastAPIError:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, dict):
            message = payload.get("message")
            if not isinstance(message, str) or not message:
                message = response.reason_phrase or "The WordPress API rejected the request."
            code = payload.get("code") if isinstance(payload.get("code"), str) else None
            return YoastAPIError(
                status_code=response.status_code,
                message=message,
                code=code,
                data=payload.get("data"),
                additional_errors=payload.get("additional_errors"),
            )

        message = response.text.strip() or response.reason_phrase or "WordPress API error"
        return YoastAPIError(status_code=response.status_code, message=message)


def _integer_header(response: httpx.Response, name: str) -> int | None:
    value = response.headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
