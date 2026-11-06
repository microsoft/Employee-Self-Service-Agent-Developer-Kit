"""MSAL-backed Dataverse authentication.

Interactive (device-less) public-client auth against the customer's Dataverse
environment. The MSAL cache is left at its default: process-local and in-memory,
so no token ever touches disk.
"""

from __future__ import annotations

import os
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

# Well-known first-party public client with Dataverse user_impersonation consent.
DEFAULT_CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"
DEFAULT_AUTHORITY = "https://login.microsoftonline.com/organizations"

# Default token audience for the target Declarative Agent import (Power Platform
# API). Draft-design value — override with ESSMIG_TARGET_SCOPE when confirmed.
DEFAULT_TARGET_SCOPE = "https://api.powerplatform.com/.default"

_DEFAULT_TENANT = "organizations"
_SCOPE_SUFFIX = "/user_impersonation"
_TENANT_RE = re.compile(r"login\.microsoftonline\.com/([^/\"'\s]+)")

TokenResult = dict[str, object]


class AuthenticationError(RuntimeError):
    """Raised when a bearer token cannot be acquired safely."""


class TokenProvider(Protocol):
    """Provides currently-valid bearer tokens."""

    def get_token(self, scopes: str | Sequence[str] | None = None) -> str: ...


@dataclass(frozen=True)
class MsalConfig:
    client_id: str = DEFAULT_CLIENT_ID
    authority: str = DEFAULT_AUTHORITY
    scopes: tuple[str, ...] = ()
    refresh_window_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError("client_id must be provided.")
        _require_https(self.authority, "authority")
        for scope in self.scopes:
            _require_https(scope, "scope")
        if self.refresh_window_seconds < 0:
            raise ValueError("refresh_window_seconds must not be negative.")


class MsalTokenProvider:
    """Token provider backed by an in-memory MSAL PublicClientApplication."""

    def __init__(self, config: MsalConfig, *, app: Any | None = None) -> None:
        self._config = config
        self._app = app if app is not None else self._build_app(config)

    def get_token(self, scopes: str | Sequence[str] | None = None) -> str:
        wanted = _normalize_scopes(scopes, self._config.scopes)
        accounts = self._app.get_accounts()
        account = accounts[0] if accounts else None

        result: TokenResult | None = None
        if account is not None:
            result = self._app.acquire_token_silent(wanted, account=account)
            if result is not None and self._needs_refresh(result):
                result = self._app.acquire_token_silent(
                    wanted, account=account, force_refresh=True
                )
        if result is None:
            if account is not None:
                raise AuthenticationError("Silent token acquisition failed.")
            result = self._app.acquire_token_interactive(wanted)

        if self._needs_refresh(result):
            raise AuthenticationError("Token acquisition returned an expired token.")
        token = result.get("access_token")
        if not isinstance(token, str) or not token:
            error = result.get("error_description") or result.get("error") or "unknown error"
            raise AuthenticationError(f"No bearer token in the auth response: {error}")
        return token

    def _needs_refresh(self, result: TokenResult) -> bool:
        now = time.time()
        expires_at = _expiry_epoch(result, now)
        return expires_at is None or expires_at <= now + self._config.refresh_window_seconds

    @staticmethod
    def _build_app(config: MsalConfig) -> Any:
        import msal

        # No SerializableTokenCache / token_cache path: keep the cache in-memory.
        return msal.PublicClientApplication(config.client_id, authority=config.authority)


def provider_for(environment_url: str, *, client_id: str | None = None) -> MsalTokenProvider:
    """A token provider scoped to a Dataverse environment, in that environment's tenant.

    The authority is built from the tenant that the environment itself advertises in
    its ``WWW-Authenticate`` challenge, not from the operator's home tenant — an
    engineer signing in to a customer environment is usually a guest, and the
    ``organizations`` authority would authenticate them into the wrong tenant.

    Overridable for unusual setups via ``ESSMIG_MSAL_CLIENT_ID``,
    ``ESSMIG_MSAL_AUTHORITY`` and ``ESSMIG_MSAL_SCOPE``.
    """
    _require_https(environment_url, "environment_url")
    root = environment_url.rstrip("/")
    authority = os.environ.get("ESSMIG_MSAL_AUTHORITY") or (
        f"https://login.microsoftonline.com/{discover_tenant(root)}"
    )
    scope = os.environ.get("ESSMIG_MSAL_SCOPE") or f"{root}{_SCOPE_SUFFIX}"
    return MsalTokenProvider(
        MsalConfig(
            client_id=client_id or os.environ.get("ESSMIG_MSAL_CLIENT_ID") or DEFAULT_CLIENT_ID,
            authority=authority,
            scopes=(scope,),
        )
    )


def provider_for_target(
    tenant_id: str, *, scope: str | None = None, client_id: str | None = None
) -> MsalTokenProvider:
    """A token provider for the target Declarative Agent's import API.

    Authenticates in the given tenant (the same tenant as the source, per the
    migration design) against the Power Platform API audience. The audience, the
    authority and the client id are all overridable — the import contract is a
    draft — via ``ESSMIG_TARGET_SCOPE``, ``ESSMIG_TARGET_AUTHORITY`` and
    ``ESSMIG_MSAL_CLIENT_ID``.
    """
    if not tenant_id.strip():
        raise ValueError("tenant_id must be provided for the target token.")
    authority = os.environ.get("ESSMIG_TARGET_AUTHORITY") or (
        f"https://login.microsoftonline.com/{tenant_id.strip()}"
    )
    resolved_scope = scope or os.environ.get("ESSMIG_TARGET_SCOPE") or DEFAULT_TARGET_SCOPE
    return MsalTokenProvider(
        MsalConfig(
            client_id=client_id or os.environ.get("ESSMIG_MSAL_CLIENT_ID") or DEFAULT_CLIENT_ID,
            authority=authority,
            scopes=(_normalize_scope(resolved_scope),),
        )
    )


def discover_tenant(environment_url: str) -> str:
    """The tenant id the environment authenticates against, from its 401 challenge.

    Falls back to ``organizations`` when the environment cannot be reached or does
    not advertise an authorization URI.
    """
    try:
        response = httpx.get(
            f"{environment_url}/api/data/v9.2/",
            headers={"Accept": "application/json"},
            follow_redirects=False,
            timeout=10.0,
        )
    except httpx.HTTPError:
        return _DEFAULT_TENANT
    match = _TENANT_RE.search(response.headers.get("WWW-Authenticate", ""))
    return match.group(1) if match else _DEFAULT_TENANT


def _normalize_scopes(
    requested: str | Sequence[str] | None, default: tuple[str, ...]
) -> list[str]:
    raw: Sequence[str]
    if requested is None:
        raw = default
    elif isinstance(requested, str):
        raw = [requested]
    else:
        raw = requested
    if not raw:
        raise ValueError("at least one scope must be provided.")
    return [_normalize_scope(scope) for scope in raw]


def _normalize_scope(value: str) -> str:
    """A bare resource URL means `/.default`; anything with a path is already a scope."""
    scope = value.strip()
    _require_https(scope, "scope")
    return f"{scope.rstrip('/')}/.default" if urlparse(scope).path in ("", "/") else scope


def _require_https(value: str, label: str) -> None:
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be an HTTPS URL (got {value!r}).")


def _expiry_epoch(result: TokenResult, now: float) -> float | None:
    for key, base in (("expires_on", 0.0), ("expires_in", now)):
        value = result.get(key)
        if isinstance(value, int | float):
            return base + float(value)
        if isinstance(value, str):
            try:
                return base + float(value)
            except ValueError:
                continue
    return None


__all__ = [
    "AuthenticationError",
    "MsalConfig",
    "MsalTokenProvider",
    "TokenProvider",
    "discover_tenant",
    "provider_for",
    "provider_for_target",
]
