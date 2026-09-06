"""The request layer - the same two rules as every other DNS Doctor client.

1. **Relay, never compose.** A tool returns the API's JSON untouched; every
   record string an agent sees is the API's bytes.
2. **A transport failure is never a verdict.** 429/402/503/5xx and network
   faults raise ``ApiError(transient=True)`` with a message that says so - a
   chain must never read them as "the domain failed".
"""

from __future__ import annotations

import json
import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx

DEFAULT_API_BASE = "https://dnsdoctor.dev"
TRANSIENT_SUFFIX = "retry; this is not a verdict about the domain"
RATE_LIMITED_MESSAGE = "rate limited - slow down and retry"
PAYMENT_REQUIRED_MESSAGE = (
    "past the free per-caller allowance - the API offered a paid retry over x402 "
    "(USDC on Base); pay with an x402 client, or wait and retry"
)
_TIMEOUT = httpx.Timeout(45.0, connect=10.0)


class ApiError(Exception):
    """A failed call. ``transient`` marks the ones that say nothing about the domain."""

    def __init__(self, message: str, status: int | None, transient: bool) -> None:
        super().__init__(message)
        self.status = status
        self.transient = transient


def api_base() -> str:
    """Base URL for the API; ``DNSDOCTOR_API_BASE`` overrides it for local runs."""
    raw = os.environ.get("DNSDOCTOR_API_BASE", "").strip()
    return (raw or DEFAULT_API_BASE).rstrip("/")


def _package_version() -> str:
    try:
        return version("langchain-dnsdoctor")
    except PackageNotFoundError:
        return "0.0.0"


def user_agent() -> str:
    """The UA every call carries - this package's only attribution on the server."""
    return f"dnsdoctor-langchain/{_package_version()} (+https://dnsdoctor.dev)"


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": user_agent()}
    # A bearer token raises the anonymous budget and unlocks the two monitoring
    # reads. Never prompted for, never required.
    token = os.environ.get("DNSDOCTOR_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _detail(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or body.get("detail") is None:
        return None
    detail = body["detail"]
    return detail if isinstance(detail, str) else json.dumps(detail)


def to_api_error(response: httpx.Response) -> ApiError:
    status = response.status_code
    detail = _detail(response)
    if status == 429:
        message = f"{RATE_LIMITED_MESSAGE} ({detail})" if detail else RATE_LIMITED_MESSAGE
        return ApiError(message, status, True)
    if status == 402:
        return ApiError(PAYMENT_REQUIRED_MESSAGE, status, True)
    if status == 503:
        return ApiError(
            f"DNS Doctor could not complete the lookup (transient) - {TRANSIENT_SUFFIX}",
            status,
            True,
        )
    if status >= 500:
        return ApiError(
            f"DNS Doctor returned a server error (HTTP {status}) - {TRANSIENT_SUFFIX}",
            status,
            True,
        )
    # 4xx: the API's own detail is the answer (422 malformed input, opaque 404). Verbatim.
    return ApiError(detail or f"DNS Doctor request failed (HTTP {status})", status, False)


def request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
) -> Any:
    """One call; the parsed JSON body, untouched."""
    url = f"{api_base()}{path}"
    try:
        response = httpx.request(
            method,
            url,
            headers=_headers(),
            json=json_body,
            params=params,
            files=files,
            timeout=_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise ApiError(
            f"Could not reach the DNS Doctor API ({exc}) - {TRANSIENT_SUFFIX}", None, True
        ) from exc
    if response.is_error:
        raise to_api_error(response)
    try:
        return response.json()
    except ValueError as exc:
        raise ApiError(
            f"DNS Doctor returned an unreadable response (HTTP {response.status_code})"
            f" - {TRANSIENT_SUFFIX}",
            response.status_code,
            True,
        ) from exc
