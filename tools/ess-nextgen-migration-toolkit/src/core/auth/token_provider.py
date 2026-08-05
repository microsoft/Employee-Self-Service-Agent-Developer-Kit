"""MSAL-backed Dataverse authentication token provider."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias, cast
from urllib.parse import urlparse

if TYPE_CHECKING:
    from core.logging import Logger

TokenResult: TypeAlias = dict[str, object]
Clock: TypeAlias = Callable[[], float]


class AuthenticationException(RuntimeError):
    """Raised when a Dataverse bearer token cannot be acquired safely."""


class TokenProvider(Protocol):
    """Provides currently-valid bearer tokens for Dataverse resources/scopes."""

    def get_token(self, scopes: str | Sequence[str] | None = None) -> str:
        """Return a bearer token that is valid at return time."""


class MsalApplication(Protocol):
    """Subset of MSAL PublicClientApplication used by the provider."""

    def get_accounts(self) -> list[object]:
        """Return accounts known to the in-memory MSAL cache."""

    def acquire_token_silent(
        self,
        scopes: Sequence[str],
        account: object | None,
        **kwargs: object,
    ) -> TokenResult | None:
        """Acquire a token from cache, silently refreshing when MSAL allows."""

    def acquire_token_interactive(self, scopes: Sequence[str]) -> TokenResult:
        """Acquire a token interactively on cold start only."""


@dataclass(frozen=True)
class MsalTokenProviderConfig:
    """Configuration for MSAL-backed token acquisition."""

    client_id: str
    authority: str
    scopes: tuple[str, ...]
    refresh_window_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError("client_id must be provided.")
        _validate_https_url(self.authority, "authority")
        if not self.scopes:
            raise ValueError("at least one default scope must be provided.")
        for scope in self.scopes:
            _validate_https_url(scope, "scope")
        if self.refresh_window_seconds < 0:
            raise ValueError("refresh_window_seconds must not be negative.")


class MsalTokenProvider:
    """Token provider backed by an in-memory MSAL PublicClientApplication."""

    def __init__(
        self,
        config: MsalTokenProviderConfig,
        logger: Logger,
        *,
        app: MsalApplication | None = None,
        now: Clock | None = None,
    ) -> None:
        self._config = config
        self._app = app if app is not None else self._build_public_client_application(config)
        self._now = now if now is not None else _default_now
        self._logger = logger

    def get_token(self, scopes: str | Sequence[str] | None = None) -> str:
        """Return a currently-valid bearer token for the requested HTTPS scopes."""
        normalized_scopes = _normalize_scopes(scopes, self._config.scopes)
        accounts = self._app.get_accounts()
        account = accounts[0] if accounts else None

        result: TokenResult | None = None
        if account is not None:
            self._logger.LogDebug(
                "Attempting silent token acquisition.",
                pipeline_stage="Auth",
                pipeline_step="TokenProvider",
            )
            result = self._app.acquire_token_silent(normalized_scopes, account=account)
            if result is not None and self._token_needs_refresh(result):
                self._logger.LogDebug(
                    "Cached token is near expiry; forcing silent refresh.",
                    pipeline_stage="Auth",
                    pipeline_step="TokenProvider",
                )
                result = self._app.acquire_token_silent(
                    normalized_scopes,
                    account=account,
                    force_refresh=True,
                )

        if result is None:
            if account is not None:
                self._logger.LogWarning(
                    "Silent token acquisition failed.",
                    pipeline_stage="Auth",
                    pipeline_step="TokenProvider",
                )
                raise AuthenticationException("Authentication token acquisition failed.")
            self._logger.LogInfo(
                "Starting interactive token acquisition for cold start.",
                pipeline_stage="Auth",
                pipeline_step="TokenProvider",
            )
            result = self._app.acquire_token_interactive(normalized_scopes)

        if self._token_needs_refresh(result):
            self._logger.LogWarning(
                "Token acquisition returned an expired or near-expiry token.",
                pipeline_stage="Auth",
                pipeline_step="TokenProvider",
            )
            raise AuthenticationException("Authentication token acquisition failed.")

        access_token = result.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            self._logger.LogWarning(
                "Token acquisition response did not include a bearer token.",
                pipeline_stage="Auth",
                pipeline_step="TokenProvider",
            )
            raise AuthenticationException("Authentication token acquisition failed.")

        return access_token

    def _token_needs_refresh(self, result: TokenResult) -> bool:
        now = self._now()
        expires_at = _token_expiry_epoch(result, now)
        if expires_at is None:
            return True
        return expires_at <= now + self._config.refresh_window_seconds

    @staticmethod
    def _build_public_client_application(config: MsalTokenProviderConfig) -> MsalApplication:
        msal_module = import_module("msal")
        public_client_application = cast(Any, msal_module).PublicClientApplication
        # Do not pass a SerializableTokenCache or token_cache path. MSAL's default
        # cache remains process-local and in-memory, preserving DIAG-003.
        return cast(
            MsalApplication,
            public_client_application(config.client_id, authority=config.authority),
        )


def _default_now() -> float:
    from time import time

    return time()


def _normalize_scopes(
    requested_scopes: str | Sequence[str] | None,
    default_scopes: tuple[str, ...],
) -> list[str]:
    scopes = default_scopes if requested_scopes is None else _coerce_scopes(requested_scopes)
    if not scopes:
        raise ValueError("at least one scope must be provided.")
    for scope in scopes:
        _validate_https_url(scope, "scope")
    return list(scopes)


def _coerce_scopes(scopes: str | Sequence[str]) -> list[str]:
    if isinstance(scopes, str):
        return [_resource_to_default_scope(scopes)]
    return [_resource_to_default_scope(scope) for scope in scopes]


def _resource_to_default_scope(scope_or_resource: str) -> str:
    value = scope_or_resource.strip()
    if not value:
        raise ValueError("scope must not be empty.")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        _validate_https_url(value, "scope")
    if parsed.path in ("", "/"):
        return f"{value.rstrip('/')}/.default"
    return value


def _validate_https_url(value: str, label: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be an HTTPS URL.")


def _token_expiry_epoch(result: TokenResult, now: float) -> float | None:
    expires_on = result.get("expires_on")
    if isinstance(expires_on, str):
        try:
            return float(expires_on)
        except ValueError:
            return None
    if isinstance(expires_on, int | float):
        return float(expires_on)

    expires_in = result.get("expires_in")
    if isinstance(expires_in, int | float):
        return now + float(expires_in)
    if isinstance(expires_in, str):
        try:
            return now + float(expires_in)
        except ValueError:
            return None
    return None
