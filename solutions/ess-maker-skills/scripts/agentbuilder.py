# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AgentBuilder authentication, host resolution, and API operations."""

from __future__ import annotations

import base64
import binascii
import json
import os
import socket
import sys
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
NATIVE_ALM_API_VERSION = "2022-03-01-preview"
COPILOT_STUDIO_CLIENT_NAME = "CopilotStudio"
DEFAULT_TOKEN_CACHE = Path(".local/.agentbuilder_token_cache.bin")
DEV_REALM = 0
TEST_REALM = 1
PROD_REALM = 2
REALM_NAMES = {
    DEV_REALM: "Dev",
    TEST_REALM: "Test",
    PROD_REALM: "Prod",
}
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


def minimal_bot_read_scope(ring: str) -> str:
    """Return the read-only delegated AgentBuilder scope for a supported ring."""
    config = RING_CONFIG.get(ring)
    if config is None:
        raise ValueError(f"Unsupported Power Platform ring: {ring!r}")
    return f"{config['audience']}/CopilotStudio.MinimalBot.Read"


def connectivity_read_scopes(ring: str) -> tuple[str]:
    """Return the delegated scope for read-only connection inventory."""
    config = RING_CONFIG.get(ring)
    if config is None:
        raise ValueError(f"Unsupported Power Platform ring: {ring!r}")
    audience = config["audience"]
    return (f"{audience}/Connectivity.Connections.Read",)


def flightcheck_read_scopes(ring: str) -> tuple[str, ...]:
    """Return the read-only scopes used by native-agent FlightCheck."""
    return (minimal_bot_read_scope(ring), *connectivity_read_scopes(ring))


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


def _account_identifiers(account: Any) -> list[str]:
    if not isinstance(account, dict):
        return []
    return [
        str(account[key]).strip()
        for key in ("username", "local_account_id", "home_account_id")
        if account.get(key) and str(account[key]).strip()
    ]


def _select_cached_account(
    accounts: list[dict[str, Any]],
    account_hint: str | None,
) -> dict[str, Any] | None:
    """Select an exact hinted account, or one unambiguous cached account."""
    if account_hint:
        wanted = account_hint.strip().casefold()
        matches = [
            account
            for account in accounts
            if any(
                identifier.casefold() == wanted
                for identifier in _account_identifiers(account)
            )
        ]
        if len(matches) > 1:
            return None
        return matches[0] if matches else None
    return accounts[0] if len(accounts) == 1 else None


def cached_account_names(
    cache_path: Path = DEFAULT_TOKEN_CACHE,
) -> list[str]:
    """Return distinct cached sign-in names without acquiring a token."""
    cache = _load_token_cache(cache_path)
    names: dict[str, str] = {}
    for account in cache.find(msal.TokenCache.CredentialType.ACCOUNT):
        username = str(account.get("username") or "").strip()
        if username:
            names.setdefault(username.casefold(), username)
    return sorted(names.values(), key=str.casefold)


def _interactive_token(
    app: msal.PublicClientApplication,
    scopes: list[str],
    account_hint: str | None,
    force_account_selection: bool,
) -> dict[str, Any] | None:
    arguments: dict[str, Any] = {"scopes": scopes}
    if account_hint and not force_account_selection:
        arguments["login_hint"] = account_hint
    else:
        arguments["prompt"] = "select_account"
    return app.acquire_token_interactive(**arguments)


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


def _acquire_token(
    *,
    authority: str,
    ring: str,
    cache_path: Path,
    force_account_selection: bool,
    account_hint: str | None,
    scopes: tuple[str, ...] | None = None,
) -> str:
    cache = _load_token_cache(cache_path)
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=authority,
        token_cache=cache,
    )
    requested_scopes = list(scopes or (minimal_bot_scope(ring),))
    selected_account = (
        None
        if force_account_selection
        else _select_cached_account(app.get_accounts(), account_hint)
    )
    result = (
        app.acquire_token_silent(requested_scopes, account=selected_account)
        if selected_account is not None
        else None
    )
    selected_identifiers = _account_identifiers(selected_account)
    if selected_identifiers:
        print(
            "Using cached AgentBuilder account: "
            f"{selected_identifiers[0]}",
            file=sys.stderr,
        )
    if not result or "access_token" not in result:
        result = _interactive_token(
            app,
            requested_scopes,
            account_hint,
            force_account_selection,
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


def authenticate(
    tenant_id: str,
    ring: str,
    *,
    cache_path: Path = DEFAULT_TOKEN_CACHE,
    force_account_selection: bool = False,
    account_hint: str | None = None,
) -> str:
    """Acquire an ESS ADK delegated token without contacting Dataverse."""
    try:
        normalized_tenant = str(uuid.UUID(tenant_id))
    except ValueError as exc:
        raise ValueError("Tenant ID must be a GUID.") from exc

    return _acquire_token(
        authority=f"https://login.microsoftonline.com/{normalized_tenant}",
        ring=ring,
        cache_path=cache_path,
        force_account_selection=force_account_selection,
        account_hint=account_hint,
    )


def authenticate_selected_tenant(
    ring: str,
    *,
    cache_path: Path = DEFAULT_TOKEN_CACHE,
    force_account_selection: bool = False,
    account_hint: str | None = None,
) -> tuple[str, str]:
    """Reuse or select an account and return its token and tenant."""
    token = _acquire_token(
        authority="https://login.microsoftonline.com/organizations",
        ring=ring,
        cache_path=cache_path,
        force_account_selection=force_account_selection,
        account_hint=account_hint,
    )
    return token, tenant_id_from_access_token(token)


def authenticate_flightcheck(
    ring: str,
    *,
    cache_path: Path = DEFAULT_TOKEN_CACHE,
    force_account_selection: bool = False,
    account_hint: str | None = None,
    include_connectivity: bool = True,
) -> tuple[str, str]:
    """Acquire one read-only token for native AgentBuilder FlightCheck reads."""
    scopes = (
        flightcheck_read_scopes(ring)
        if include_connectivity
        else (minimal_bot_read_scope(ring),)
    )
    token = _acquire_token(
        authority="https://login.microsoftonline.com/organizations",
        ring=ring,
        cache_path=cache_path,
        force_account_selection=force_account_selection,
        account_hint=account_hint,
        scopes=scopes,
    )
    return token, tenant_id_from_access_token(token)


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


class ConnectivityClient:
    """Thin client for ring-native Power Platform connection inventory."""

    def __init__(
        self,
        token: str,
        *,
        ring: str,
        api_version: str = DEFAULT_API_VERSION,
        session: requests.Session | None = None,
    ) -> None:
        self.host = _ring_api_host(ring)
        self.ring = ring
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

    def list_connections(self, environment_id: str) -> list[dict[str, Any]]:
        """List physical connections visible to the signed-in maker."""
        normalized_environment_id = str(uuid.UUID(environment_id))
        response = self.session.request(
            "GET",
            (
                f"{self.host}/connectivity/environments/"
                f"{normalized_environment_id}/connections"
            ),
            params={"api-version": self.api_version},
            headers=self.headers,
            timeout=120,
        )
        if not response.ok:
            _response_error(response, "Connection listing")
        try:
            body = response.json()
        except ValueError as exc:
            raise AgentBuilderError(
                "Connection listing returned a non-JSON response."
            ) from exc
        values = body.get("value") if isinstance(body, dict) else None
        if not isinstance(values, list) or not all(
            isinstance(value, dict) for value in values
        ):
            raise AgentBuilderError(
                "Connection listing returned an invalid shape."
            )
        return values


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

    def list_starter_packages(
        self,
        *,
        page_size: int = 200,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """List AgentBuilder starter packages entitled to this identity.

        Read-only and safe to call before any maker confirmation; it never
        mutates the target environment. Live-proven GET route. Uses the
        client's normal idempotent-GET retry policy; this method adds only
        bounded pagination and strict response-shape validation on top of
        it.
        """
        if page_size <= 0:
            raise ValueError("Page size must be a positive integer.")
        if max_pages <= 0:
            raise ValueError("Max pages must be a positive integer.")
        packages: list[dict[str, Any]] = []
        continuation: str | None = None
        for _page in range(max_pages):
            params: dict[str, Any] = {"pageSize": page_size}
            if continuation:
                params["continuationToken"] = continuation
            body = self._json(
                "GET",
                "/copilotstudio/minimalBots/agentStarterPackages",
                "Starter package listing",
                params=params,
            )
            if not isinstance(body, dict):
                raise AgentBuilderError(
                    "Starter package listing returned an invalid shape."
                )
            page_packages = body.get("packages")
            if not isinstance(page_packages, list) or not all(
                isinstance(item, dict) for item in page_packages
            ):
                raise AgentBuilderError(
                    "Starter package listing returned an invalid shape."
                )
            packages.extend(page_packages)
            continuation = body.get("continuationToken")
            if not continuation:
                return packages
            if not isinstance(continuation, str):
                raise AgentBuilderError(
                    "Starter package listing returned an invalid "
                    "continuation token."
                )
        raise AgentBuilderError(
            f"Starter package listing exceeded {max_pages} pages."
        )

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        body = self._json(
            "GET",
            f"/copilotstudio/minimalBots/api/{agent_id}",
            "Direct agent lookup",
        )
        if not isinstance(body, dict):
            raise AgentBuilderError("Direct agent lookup returned an invalid shape.")
        return body

    def publish_agent(
        self,
        agent_id: str,
        *,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Publish one native agent through the MinimalBot API."""
        response = self.session.request(
            "POST",
            f"{self.host}/copilotstudio/minimalBots/api/{agent_id}/publish",
            params={"api-version": NATIVE_ALM_API_VERSION},
            headers={**self.headers, "Content-Type": "application/json"},
            json={},
            timeout=timeout,
            allow_redirects=False,
        )
        if not response.ok:
            _response_error(response, "Native agent publish")
        try:
            body = response.json()
        except ValueError:
            if response.content:
                raise AgentBuilderError(
                    "Native agent publish returned a non-JSON response."
                )
            return {}
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise AgentBuilderError(
                "Native agent publish returned an invalid shape."
            )
        return body

    def get_realms(self, agent_id: str) -> dict[str, Any]:
        body = self._json(
            "GET",
            f"/copilotstudio/minimalBots/alm/{agent_id}/realms",
            "Agent realm family",
        )
        if not isinstance(body, dict):
            raise AgentBuilderError(
                "Agent realm family returned an invalid shape."
            )
        return body

    def get_realm_configuration(
        self,
        agent_id: str,
        realm: int,
    ) -> dict[str, Any]:
        if type(realm) is not int or realm not in REALM_NAMES:
            raise ValueError("Realm must be the numeric Dev, Test, or Prod value.")
        operation = f"{REALM_NAMES[realm]} realm configuration"
        body = self._json(
            "GET",
            f"/copilotstudio/minimalBots/alm/{agent_id}/configure",
            operation,
            params={"realm": realm},
        )
        if not isinstance(body, dict):
            raise AgentBuilderError(f"{operation} returned an invalid shape.")
        return body

    def get_dev_configuration(self, agent_id: str) -> dict[str, Any]:
        return self.get_realm_configuration(agent_id, DEV_REALM)

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

    def update_bot_entity(
        self,
        agent_id: str,
        bot: dict[str, Any],
        *,
        timeout: int = 300,
    ) -> requests.Response:
        """Replace one fetched BotEntity without changing bot components."""
        if not isinstance(bot, dict):
            raise ValueError("BotEntity must be an object.")
        return self.session.request(
            "PUT",
            f"{self.host}/copilotstudio/minimalBots/api/{agent_id}/components",
            params={"api-version": NATIVE_ALM_API_VERSION},
            headers={**self.headers, "Content-Type": "application/json"},
            json={"bot": bot, "botComponentChanges": []},
            timeout=timeout,
            allow_redirects=False,
        )

    def import_package(
        self,
        package_path: Path,
        *,
        replacement_schema_name: str | None = None,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Import one package without replaying or exposing its response body."""
        request_headers = {
            "Authorization": self.headers["Authorization"],
            "x-ms-client-name": COPILOT_STUDIO_CLIENT_NAME,
        }
        form = (
            {"schemaName": replacement_schema_name}
            if replacement_schema_name
            else {}
        )
        with package_path.open("rb") as package:
            response = self.session.request(
                "POST",
                f"{self.host}/copilotstudio/minimalBots/alm/import",
                params={"api-version": NATIVE_ALM_API_VERSION},
                headers=request_headers,
                files={
                    "package": (
                        "package.zip",
                        package,
                        "application/zip",
                    )
                },
                data=form,
                timeout=timeout,
                allow_redirects=False,
            )
        if not 200 <= response.status_code < 300:
            _response_error(response, "Native ALM import")
        try:
            body = response.json()
        except ValueError:
            return {
                "responseStatus": "invalid",
                "reason": "non-json-response",
            }
        if not isinstance(body, dict):
            return {
                "responseStatus": "invalid",
                "reason": "invalid-agent-identity",
            }
        try:
            agent_id = str(uuid.UUID(str(body.get("cdsBotId") or "")))
        except ValueError:
            return {
                "responseStatus": "invalid",
                "reason": "invalid-agent-identity",
            }
        schema_name = body.get("schemaName")
        if not isinstance(schema_name, str) or not schema_name.strip():
            return {
                "responseStatus": "invalid",
                "reason": "invalid-agent-identity",
            }
        return {
            "responseStatus": "valid",
            "result": {
                "cdsBotId": agent_id,
                "schemaName": schema_name.strip(),
            },
        }

    def export_package(
        self,
        agent_id: str,
        destination: Path,
        *,
        timeout: int = 300,
    ) -> None:
        """Export one native package to a caller-owned path."""
        request_headers = {
            "Authorization": self.headers["Authorization"],
            "x-ms-client-name": COPILOT_STUDIO_CLIENT_NAME,
        }
        response = self.session.request(
            "POST",
            f"{self.host}/copilotstudio/minimalBots/alm/{agent_id}/export",
            params={"api-version": NATIVE_ALM_API_VERSION},
            headers=request_headers,
            timeout=timeout,
            allow_redirects=False,
            stream=True,
        )
        operation_error: BaseException | None = None
        try:
            if not 200 <= response.status_code < 300:
                _response_error(response, "Native ALM export")
            with destination.open("wb") as package:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        package.write(chunk)
        except BaseException as exc:
            operation_error = exc
            raise
        finally:
            try:
                response.close()
            except Exception as close_error:
                if operation_error is None:
                    raise
                operation_error.add_note(
                    "Native ALM export response cleanup also failed: "
                    f"{type(close_error).__name__}: {close_error}"
                )

    def create_agent_from_starter_package(
        self,
        package_id: str,
        *,
        timeout: int = 300,
    ) -> requests.Response:
        """Dispatch one create-only MOS starter package request.

        The live-proven request is
        ``POST /minimalBots/createFromStarterPackage`` with the exact package
        ID in ``{"packageId": ...}``. The service returns HTTP 201 with the
        new ``botId`` and ``sourcePackage`` identity.

        Create-only: the caller supplies the exact maker-confirmed package
        ID and this method never supplies a replacement schema or targets
        an existing agent. Redirects are disabled and this POST is
        intentionally excluded from the session's retry policy (mounted for
        GET/HEAD/OPTIONS only), so a mutation is never replayed
        automatically by the transport.

        Returns the raw response instead of raising on a non-2xx status or
        parsing its body: the caller owns near-verbatim, redacted evidence
        rendering and the attempt-fuse disposition, and must not lose
        response detail to a discarded exception.
        """
        if not isinstance(package_id, str) or not package_id.strip():
            raise ValueError("Starter package ID must be a non-empty string.")
        return self.session.request(
            "POST",
            f"{self.host}/copilotstudio/minimalBots/createFromStarterPackage",
            params={"api-version": self.api_version},
            headers={**self.headers, "Content-Type": "application/json"},
            json={"packageId": package_id},
            timeout=timeout,
            allow_redirects=False,
        )


def canonical_json(value: Any) -> str:
    """Serialize API state deterministically for hashes and local evidence."""
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
