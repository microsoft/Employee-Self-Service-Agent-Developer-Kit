# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only subset of the shared AgentBuilder client backported from main.

The host helpers, environment listing, and component request retain the client
contract at 2bf96b4c4fc522a7d40a6d53de305c01d3e76672. Unused native-agent
setup, ALM, and mutation operations are deliberately not backported.
"""

from __future__ import annotations

import socket
import uuid
from typing import Any, Callable
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


CLIENT_ID = "417219b4-3a7d-42a2-bdb1-972bd8281a02"
DEFAULT_API_VERSION = "2024-10-01"
NATIVE_ALM_API_VERSION = "2022-03-01-preview"
COPILOT_STUDIO_CLIENT_NAME = "CopilotStudio"
RING_CONFIG = {
    "prod": {
        "audience": "https://api.powerplatform.com",
        "host_suffix": "environment.api.powerplatform.com",
        "primary_split": 30,
    },
    "preprod": {
        "audience": "https://api.preprod.powerplatform.com",
        "host_suffix": "environment.api.preprod.powerplatform.com",
        "primary_split": 31,
    },
    "test": {
        "audience": "https://api.test.powerplatform.com",
        "host_suffix": "environment.api.test.powerplatform.com",
        "primary_split": 31,
    },
}


class AgentBuilderError(RuntimeError):
    """Raised when an AgentBuilder operation cannot complete safely."""


class AgentBuilderHTTPError(AgentBuilderError):
    """Raised for an unsuccessful AgentBuilder HTTP response."""

    def __init__(
        self,
        operation: str,
        status_code: int,
        *,
        error_code: str | None = None,
        request_id: str | None = None,
        response: requests.Response | None = None,
    ) -> None:
        detail = f"{operation} failed with HTTP {status_code}"
        if error_code:
            detail += f" ({error_code})"
        if status_code == 403:
            detail += "; the signed-in account is not authorized"
        if request_id:
            detail += f" [request {request_id}]"
        super().__init__(detail)
        self.status_code = status_code
        self.error_code = error_code
        self.request_id = request_id
        self.response = response


def normalize_environment_id(environment_id: str) -> str:
    """Return a compact lowercase GUID suitable for a PPAPI hostname."""
    try:
        return uuid.UUID(environment_id).hex
    except ValueError as exc:
        raise ValueError("Environment ID must be a GUID.") from exc


def validate_environment_host(host: str, ring: str) -> str:
    """Validate an explicit PPAPI host before a delegated token is sent."""
    config = RING_CONFIG.get(ring)
    if config is None:
        raise ValueError(f"Unsupported Power Platform ring: {ring!r}")
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").casefold()
    suffix = str(config["host_suffix"]).casefold()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
        or not hostname.endswith(f".{suffix}")
    ):
        raise ValueError(
            f"AgentBuilder host must be an HTTPS environment host for {ring}."
        )
    return f"https://{hostname}"


def environment_id_from_host(host: str, ring: str) -> str:
    """Return the canonical environment GUID encoded in a PPAPI host."""
    validated = validate_environment_host(host, ring)
    hostname = urlparse(validated).hostname or ""
    suffix = str(RING_CONFIG[ring]["host_suffix"]).casefold()
    prefix = hostname[: -(len(suffix) + 1)]
    labels = prefix.split(".")
    compact = "".join(labels)
    if (
        len(labels) != 2
        or len(compact) != 32
        or any(char not in "0123456789abcdef" for char in compact)
    ):
        raise ValueError(
            "AgentBuilder host does not encode a valid environment ID."
        )
    return str(uuid.UUID(hex=compact))


def derive_environment_host(
    environment_id: str,
    ring: str,
    *,
    resolver: Callable[..., Any] = socket.getaddrinfo,
) -> str:
    """Derive the environment-specific PPAPI host for a supported ring."""
    config = RING_CONFIG.get(ring)
    if config is None:
        raise ValueError(f"Unsupported Power Platform ring: {ring!r}")
    compact = normalize_environment_id(environment_id)
    primary = int(config["primary_split"])
    splits = (primary, 31 if primary == 30 else 30)
    suffix = str(config["host_suffix"])
    for split in splits:
        hostname = f"{compact[:split]}.{compact[split:]}.{suffix}"
        try:
            resolver(hostname, 443)
            return f"https://{hostname}"
        except socket.gaierror:
            continue
    hostname = f"{compact[:primary]}.{compact[primary:]}.{suffix}"
    return f"https://{hostname}"


def minimal_bot_read_scope(ring: str) -> str:
    """Return the read-only delegated AgentBuilder scope for a supported ring."""
    config = RING_CONFIG.get(ring)
    if config is None:
        raise ValueError(f"Unsupported Power Platform ring: {ring!r}")
    return f"{config['audience']}/CopilotStudio.MinimalBot.Read"


def _ring_api_host(ring: str) -> str:
    config = RING_CONFIG.get(ring)
    if config is None:
        raise ValueError(f"Unsupported Power Platform ring: {ring!r}")
    return str(config["audience"])


def ring_from_environment_host(host: str) -> str:
    """Return the supported ring identified by an environment API host."""
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").casefold()
    matches = [
        ring
        for ring, config in RING_CONFIG.items()
        if hostname.endswith(f".{str(config['host_suffix']).casefold()}")
    ]
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.params
        or parsed.query
        or parsed.fragment
        or len(matches) != 1
    ):
        raise ValueError(
            "Power Platform API endpoint must be a supported HTTPS "
            "environment host."
        )
    return matches[0]


def _validate_environment_continuation(url: str, ring: str) -> str:
    expected = urlparse(_ring_api_host(ring))
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.hostname != expected.hostname
        or parsed.path != "/environmentmanagement/environments"
        or parsed.fragment
    ):
        raise AgentBuilderError(
            "Environment listing returned an unsafe continuation URL."
        )
    return url


def list_environments(
    token: str,
    ring: str,
    *,
    api_version: str = DEFAULT_API_VERSION,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """List environments visible to an AgentBuilder identity in one ring."""
    host = _ring_api_host(ring)
    client = session or requests.Session()
    if session is None:
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            respect_retry_after_header=True,
        )
        client.mount("https://", HTTPAdapter(max_retries=retry))
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "x-ms-client-name": COPILOT_STUDIO_CLIENT_NAME,
    }
    url = f"{host}/environmentmanagement/environments"
    params: dict[str, str] | None = {"api-version": api_version}
    environments: list[dict[str, Any]] = []
    for _page in range(20):
        response = client.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=120,
        )
        if not response.ok:
            _response_error(response, "Environment listing")
        try:
            body = response.json()
        except ValueError as exc:
            raise AgentBuilderError(
                "Environment listing returned a non-JSON response."
            ) from exc
        values = body.get("value") if isinstance(body, dict) else None
        if not isinstance(values, list) or not all(
            isinstance(value, dict) for value in values
        ):
            raise AgentBuilderError(
                "Environment listing returned an invalid shape."
            )
        environments.extend(values)
        next_url = (
            body.get("@odata.nextLink")
            or body.get("@odata.nextlink")
            or body.get("nextLink")
        )
        if not next_url:
            return environments
        if not isinstance(next_url, str):
            raise AgentBuilderError(
                "Environment listing returned an invalid continuation URL."
            )
        url = _validate_environment_continuation(next_url, ring)
        params = None
    raise AgentBuilderError("Environment listing exceeded 20 pages.")


def _response_error(response: requests.Response, operation: str) -> None:
    error_code = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error") or body.get("Error") or body
        if isinstance(error, dict):
            candidate = error.get("code") or error.get("Code")
            if isinstance(candidate, str):
                error_code = candidate
        elif isinstance(error, str):
            error_code = error
    request_id = next(
        (
            response.headers.get(name)
            for name in (
                "x-ms-service-request-id",
                "x-ms-request-id",
                "request-id",
            )
            if response.headers.get(name)
        ),
        None,
    )
    raise AgentBuilderHTTPError(
        operation,
        response.status_code,
        error_code=error_code,
        request_id=request_id,
        response=response,
    )


class AgentBuilderClient:
    """Thin client for the live-proven AgentBuilder API surface."""

    def __init__(
        self,
        host: str,
        token: str,
        *,
        ring: str,
        tenant_id: str,
        api_version: str = DEFAULT_API_VERSION,
        session: requests.Session | None = None,
    ) -> None:
        self.host = validate_environment_host(host, ring)
        self.ring = ring
        try:
            self.tenant_id = str(uuid.UUID(tenant_id))
        except ValueError as exc:
            raise ValueError("Tenant ID must be a GUID.") from exc
        self.api_version = api_version
        self.session = session or requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "x-ms-client-name": COPILOT_STUDIO_CLIENT_NAME,
        }

    def _json(
        self,
        method: str,
        path: str,
        operation: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        timeout: int = 120,
    ) -> Any:
        request_params = {"api-version": self.api_version}
        if params:
            request_params.update(params)
        request_headers = dict(self.headers)
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        response = self.session.request(
            method,
            f"{self.host}{path}",
            params=request_params,
            headers=request_headers,
            json=body,
            timeout=timeout,
        )
        if not response.ok:
            _response_error(response, operation)
        try:
            return response.json()
        except ValueError as exc:
            raise AgentBuilderError(
                f"{operation} returned a non-JSON response."
            ) from exc

    def fetch_components(self, agent_id: str) -> dict[str, Any]:
        body = self._json(
            "POST",
            f"/copilotstudio/minimalBots/api/{agent_id}/components",
            "Component fetch",
            params={"api-version": NATIVE_ALM_API_VERSION},
            body={},
            timeout=180,
        )
        if not isinstance(body, dict):
            raise AgentBuilderError("Component fetch returned an invalid shape.")
        return body
