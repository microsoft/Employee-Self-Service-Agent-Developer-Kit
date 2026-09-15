# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AgentBuilder authentication, host resolution, and read operations."""

from __future__ import annotations

import base64
import binascii
import json
import os
import socket
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import msal
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


CLIENT_ID = "417219b4-3a7d-42a2-bdb1-972bd8281a02"
DEFAULT_API_VERSION = "2024-10-01"
DEFAULT_TOKEN_CACHE = Path(".local/.agentbuilder_token_cache.bin")
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


def minimal_bot_scope(ring: str) -> str:
    """Return the delegated AgentBuilder scope for a supported ring."""
    config = RING_CONFIG.get(ring)
    if config is None:
        raise ValueError(f"Unsupported Power Platform ring: {ring!r}")
    return (
        f"{config['audience']}/"
        "CopilotStudio.MinimalBot.ReadWrite"
    )


def _ring_api_host(ring: str) -> str:
    config = RING_CONFIG.get(ring)
    if config is None:
        raise ValueError(f"Unsupported Power Platform ring: {ring!r}")
    return str(config["audience"])


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
        "x-ms-client-name": "EssAdk",
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


def _persist_token_cache(cache: msal.SerializableTokenCache, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f"{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(cache.serialize())
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temporary_path, 0o600)
        except OSError:
            pass
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _load_token_cache(path: Path) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if path.exists():
        try:
            cache.deserialize(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AgentBuilderError(
                f"AgentBuilder token cache is unreadable: {path}"
            ) from exc
    return cache


def tenant_id_from_access_token(token: str) -> str:
    """Return the issuing tenant ID from an AgentBuilder access token."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return str(uuid.UUID(str(claims.get("tid") or "")))
    except (
        IndexError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        binascii.Error,
        json.JSONDecodeError,
    ) as exc:
        raise AgentBuilderError(
            "AgentBuilder authentication returned an unreadable tenant identity."
        ) from exc


def authenticate(
    tenant_id: str,
    ring: str,
    *,
    cache_path: Path = DEFAULT_TOKEN_CACHE,
    force_account_selection: bool = False,
) -> str:
    """Acquire an ESS ADK delegated token without contacting Dataverse."""
    try:
        normalized_tenant = str(uuid.UUID(tenant_id))
    except ValueError as exc:
        raise ValueError("Tenant ID must be a GUID.") from exc

    cache = _load_token_cache(cache_path)

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{normalized_tenant}",
        token_cache=cache,
    )
    scope = minimal_bot_scope(ring)
    accounts = app.get_accounts()
    result = (
        app.acquire_token_silent([scope], account=accounts[0])
        if accounts and not force_account_selection
        else None
    )
    if not result or "access_token" not in result:
        result = app.acquire_token_interactive(
            scopes=[scope],
            prompt="select_account",
        )
    token = result.get("access_token") if result else None
    if not token:
        error = result.get("error", "unknown_error") if result else "unknown_error"
        raise AgentBuilderError(
            f"AgentBuilder authentication failed ({error})."
        )
    if cache.has_state_changed:
        _persist_token_cache(cache, cache_path)
    return token


def authenticate_selected_tenant(
    ring: str,
    *,
    cache_path: Path = DEFAULT_TOKEN_CACHE,
) -> tuple[str, str]:
    """Let the maker select an account and return its token and tenant."""
    cache = _load_token_cache(cache_path)
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority="https://login.microsoftonline.com/organizations",
        token_cache=cache,
    )
    result = app.acquire_token_interactive(
        scopes=[minimal_bot_scope(ring)],
        prompt="select_account",
    )
    token = result.get("access_token") if result else None
    if not token:
        error = result.get("error", "unknown_error") if result else "unknown_error"
        raise AgentBuilderError(
            f"AgentBuilder authentication failed ({error})."
        )
    tenant_id = tenant_id_from_access_token(token)
    if cache.has_state_changed:
        _persist_token_cache(cache, cache_path)
    return token, tenant_id


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
    )


class AgentBuilderClient:
    """Thin client for the live-proven existing-Dev read surface."""

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
            "Content-Type": "application/json",
            "x-ms-client-name": "EssAdk",
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
        response = self.session.request(
            method,
            f"{self.host}{path}",
            params=request_params,
            headers=self.headers,
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

    def list_agents(self) -> list[dict[str, Any]]:
        body = self._json(
            "GET",
            "/copilotstudio/minimalBots/api",
            "Agent listing",
        )
        if isinstance(body, dict):
            body = body.get("value")
        if not isinstance(body, list) or not all(
            isinstance(item, dict) for item in body
        ):
            raise AgentBuilderError("Agent listing returned an invalid shape.")
        return body

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        body = self._json(
            "GET",
            f"/copilotstudio/minimalBots/api/{agent_id}",
            "Direct agent lookup",
        )
        if not isinstance(body, dict):
            raise AgentBuilderError("Direct agent lookup returned an invalid shape.")
        return body

    def get_dev_configuration(self, agent_id: str) -> dict[str, Any]:
        body = self._json(
            "GET",
            f"/copilotstudio/minimalBots/alm/{agent_id}/configure",
            "Dev realm configuration",
            params={"realm": 0},
        )
        if not isinstance(body, dict):
            raise AgentBuilderError(
                "Dev realm configuration returned an invalid shape."
            )
        return body

    def fetch_components(self, agent_id: str) -> dict[str, Any]:
        body = self._json(
            "POST",
            f"/copilotstudio/minimalBots/api/{agent_id}/components",
            "Component fetch",
            body={},
            timeout=180,
        )
        if not isinstance(body, dict):
            raise AgentBuilderError("Component fetch returned an invalid shape.")
        return body


def canonical_json(value: Any) -> str:
    """Serialize API state deterministically for hashes and local evidence."""
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
