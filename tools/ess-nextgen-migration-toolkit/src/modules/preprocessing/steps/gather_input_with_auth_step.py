"""Prompt for environment input, authenticate, and seed context identity."""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from constants import DATAVERSE_CLIENT_ID, SUPPORTED_MODES
from core.auth import AuthenticationException, MsalTokenProvider, MsalTokenProviderConfig
from core.logging import Logger
from core.outbound import DataverseClient
from modules.migration.migration_step import MigrationPipelineStep
from modules.migration.models import MigrationContext

_DEFAULT_TENANT = "organizations"
_DEFAULT_SCOPE_SUFFIX = "/user_impersonation"
_TENANT_PATTERN = re.compile(r"login\.microsoftonline\.com/([^/]+)")


class GatherInputWithAuthStep(MigrationPipelineStep):
    """Prompt for the Dataverse URL, authenticate, and initialize context access."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            description=(
                "Gather the target Dataverse environment and authenticate the current user."
            ),
            supported_modes=SUPPORTED_MODES,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        environment_url = _prompt_for_environment_url()
        context.environment_url = environment_url

        self._logger.LogInfo(
            f"Using Dataverse environment {environment_url}.",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )
        self._logger.LogInfo(
            f"Discovering tenant and authenticating with MSAL for {environment_url}.",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )

        token_provider = MsalTokenProvider(_build_provider_config(environment_url))
        token = token_provider.get_token()
        claims = _decode_claims(token)

        context.tenant_id = _as_string(claims.get("tid"))
        context.user_id = _as_string(claims.get("oid"))
        context.user_email = _as_string(claims.get("upn")) or _as_string(
            claims.get("preferred_username"),
        )
        context.dataverse_client = DataverseClient(environment_url, token_provider)

        self._logger.LogInfo(
            "Authentication completed.",
            pipeline_stage="Input",
            pipeline_step=self.name(),
        )
        return context


def _prompt_for_environment_url() -> str:
    # Future enhancement: accept an Environment ID and resolve the instance URL
    # via the Power Platform BAP discovery API before Dataverse auth.
    return _normalize_environment_url(
        input(
            "Dataverse environment URL (full URL, for example https://org.crm.dynamics.com): ",
        ),
    )


def _normalize_environment_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("Environment URL must not be empty.")

    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Environment URL must be an HTTPS URL.")

    return normalized


def _build_provider_config(environment_url: str) -> MsalTokenProviderConfig:
    authority = os.environ.get("MTK_MSAL_AUTHORITY", _build_authority(environment_url))
    scope = os.environ.get("MTK_MSAL_DEFAULT_SCOPE", f"{environment_url}{_DEFAULT_SCOPE_SUFFIX}")
    return MsalTokenProviderConfig(
        client_id=os.environ.get("MTK_MSAL_CLIENT_ID", DATAVERSE_CLIENT_ID),
        authority=authority,
        scopes=(scope,),
    )


def _build_authority(environment_url: str) -> str:
    tenant_id = _discover_tenant(environment_url)
    return f"https://login.microsoftonline.com/{tenant_id}"


def _discover_tenant(environment_url: str) -> str:
    response = httpx.get(
        f"{environment_url}/api/data/v9.2/",
        headers={"Accept": "application/json"},
        follow_redirects=False,
        timeout=10.0,
    )
    auth_header = response.headers.get("WWW-Authenticate", "")
    match = _TENANT_PATTERN.search(auth_header)
    if match:
        return match.group(1)
    return _DEFAULT_TENANT


def _decode_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthenticationException("Authentication token acquisition failed.")

    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}")
        claims = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuthenticationException("Authentication token acquisition failed.") from exc

    if not isinstance(claims, dict):
        raise AuthenticationException("Authentication token acquisition failed.")
    return claims


def _as_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
