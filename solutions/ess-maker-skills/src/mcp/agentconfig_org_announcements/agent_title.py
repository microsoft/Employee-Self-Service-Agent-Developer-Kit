# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Resolve one configured agent's Microsoft 365 title through Dataverse."""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import msal
import requests
from portalocker.exceptions import LockException

from validation import validate_title_id


_SOLUTION_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = _SOLUTION_ROOT / ".local" / "config.json"
sys.path.insert(0, str(_SOLUTION_ROOT / "scripts"))

from auth import dataverse_get  # noqa: E402
from base_client import (  # noqa: E402
    _CLIENT_ID as DATAVERSE_CLIENT_ID,
    _TOKEN_CACHE_PATH,
    account_for_identity,
    validate_token_identity,
)
from _odata import _validate_https_base_url  # noqa: E402
from _token_cache import create_token_cache  # noqa: E402


DATAVERSE_TOKEN_CACHE_PATH = Path(_TOKEN_CACHE_PATH)
_LOGGER = logging.getLogger("ess-org-announcements.agent-title")


class AgentTitleResolutionError(RuntimeError):
    """A local, content-free diagnostic safe to return through the MCP."""

    def __init__(self, message: str, *, code: str, source: str = "mcp") -> None:
        super().__init__(message)
        self.code = code
        self.source = source


@dataclass(frozen=True)
class ConfiguredAgentTarget:
    bot_id: str
    dataverse_endpoint: str


def _guid(value: Any, field: str) -> str:
    try:
        if not isinstance(value, str):
            raise ValueError
        parsed = UUID(value)
        if not parsed.int:
            raise ValueError
        return str(parsed)
    except ValueError as error:
        raise AgentTitleResolutionError(
            f"{field} must be a non-empty GUID. Confirm the selected agent in /setup.",
            code="InvalidRequest",
        ) from error


def _matches_bot(entry: dict[str, Any], bot_id: str) -> bool:
    value = entry.get("botId")
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == bot_id
    except ValueError:
        return False


def load_configured_target(bot_id: str) -> ConfiguredAgentTarget:
    """Bind an exact botId to workspace configuration, never a display name."""
    bot_id = _guid(bot_id, "botId")
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AgentTitleResolutionError(
            "The maker configuration could not be read. Complete /setup first.",
            code="InvalidRequest",
        ) from error
    if not isinstance(config, dict) or config.get("setup") != "complete":
        raise AgentTitleResolutionError(
            "Complete /setup before resolving an announcement agent.",
            code="InvalidRequest",
        )
    agents = config.get("agents", [])
    if not isinstance(agents, list) or not all(
        isinstance(entry, dict) for entry in agents
    ):
        raise AgentTitleResolutionError(
            "The configured agents are invalid. Refresh /setup before continuing.",
            code="InvalidRequest",
        )
    matches = [entry for entry in agents if _matches_bot(entry, bot_id)]
    if not matches:
        active = config.get("agent")
        if isinstance(active, dict) and _matches_bot(active, bot_id):
            matches = [active]
    if len(matches) != 1:
        raise AgentTitleResolutionError(
            "botId must identify exactly one configured agent. Select it in /setup.",
            code="InvalidRequest",
        )
    selected = matches[0]

    # An agent-specific environment must not inherit another agent's endpoint.
    has_own_environment = any(
        selected.get(key) is not None
        for key in ("environmentId", "powerPlatformApiEndpoint", "dataverseEndpoint")
    )
    environment = selected if has_own_environment else config
    endpoint = environment.get("dataverseEndpoint")
    if endpoint is None:
        raise AgentTitleResolutionError(
            "The selected agent has no configured Dataverse endpoint. "
            "Complete /setup for that agent.",
            code="InvalidRequest",
        )
    try:
        if not isinstance(endpoint, str):
            raise ValueError
        endpoint = _validate_https_base_url(endpoint, "dataverseEndpoint")
        if urlsplit(endpoint).path:
            raise ValueError
    except ValueError as error:
        raise AgentTitleResolutionError(
            "The selected agent's dataverseEndpoint must be an HTTPS origin "
            "without credentials, a path, a query, or a fragment. "
            "Confirm its environment in /setup.",
            code="InvalidRequest",
        ) from error
    return ConfiguredAgentTarget(bot_id, endpoint)


def acquire_dataverse_token(
    endpoint: str, tenant_id: str, object_id: str | None
) -> str:
    """Reuse the shared authoring cache for the same tenant and account."""
    if not object_id:
        raise AgentTitleResolutionError(
            "The authoring account cannot be identified. Sign in with a delegated "
            "AgentConfiguration token containing tid and oid claims.",
            code="AuthenticationRequired",
        )
    try:
        scopes = [f"{endpoint}/user_impersonation"]
        app = msal.PublicClientApplication(
            DATAVERSE_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{UUID(tenant_id)}",
            token_cache=create_token_cache(str(DATAVERSE_TOKEN_CACHE_PATH)),
        )
        account = account_for_identity(app, tenant_id, object_id)
        result = (
            app.acquire_token_silent(scopes, account=account)
            if account is not None
            else None
        )
        if not isinstance(result, dict) or not result.get("access_token"):
            _LOGGER.info("Opening a browser for Dataverse agent metadata discovery.")
            result = app.acquire_token_interactive(scopes, prompt="select_account")
        token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError
        return validate_token_identity(token, tenant_id, object_id)
    except (ValueError, OSError, LockException, requests.RequestException) as error:
        raise AgentTitleResolutionError(
            "Dataverse sign-in failed or selected a different tenant/account. "
            "Sign in with the current announcement authoring account and retry.",
            code="AuthenticationRequired",
        ) from error


def _registered_title(payload: Any, bot_id: str) -> str:
    try:
        if (
            not isinstance(payload, dict)
            or _guid(payload.get("botid"), "botid") != bot_id
        ):
            raise ValueError
    except (ValueError, AgentTitleResolutionError) as error:
        raise AgentTitleResolutionError(
            "The Dataverse response did not identify the selected configured bot. "
            "No titleId was accepted.",
            code="ServiceError",
            source="backend",
        ) from error
    raw_manifest = payload.get("applicationmanifestinformation")
    if raw_manifest is None or (
        isinstance(raw_manifest, str) and not raw_manifest.strip()
    ):
        raise AgentTitleResolutionError(
            "The selected agent has no Microsoft 365 registration titleId. "
            "Publish/register this agent for Microsoft 365, then retry.",
            code="RegistrationRequired",
            source="backend",
        )
    try:
        if not isinstance(raw_manifest, str):
            raise ValueError
        manifest = json.loads(raw_manifest)
        if not isinstance(manifest, dict):
            raise ValueError
        metadata = manifest.get("microsoft365")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError
    except ValueError as error:
        raise AgentTitleResolutionError(
            "Dataverse returned malformed application manifest information. "
            "No titleId was accepted.",
            code="ServiceError",
            source="backend",
        ) from error
    title_id = metadata.get("titleId") if metadata is not None else None
    if title_id is None or (isinstance(title_id, str) and not title_id.strip()):
        raise AgentTitleResolutionError(
            "The selected agent has no Microsoft 365 registration titleId. "
            "Publish/register this agent for Microsoft 365, then retry.",
            code="RegistrationRequired",
            source="backend",
        )
    try:
        return validate_title_id(title_id)
    except ValueError as error:
        raise AgentTitleResolutionError(
            "Dataverse returned an invalid Microsoft 365 titleId. "
            "No titleId was accepted.",
            code="ServiceError",
            source="backend",
        ) from error


def resolve_configured_agent_title(
    target: ConfiguredAgentTarget, tenant_id: str, object_id: str | None
) -> dict[str, str]:
    """Read bot metadata off the event loop; never write tenant or local state."""
    try:
        token = acquire_dataverse_token(target.dataverse_endpoint, tenant_id, object_id)
        payload = dataverse_get(
            target.dataverse_endpoint,
            token,
            f"bots({target.bot_id})",
            params={"$select": "botid,applicationmanifestinformation"},
        )
        return {
            "botId": target.bot_id,
            "titleId": _registered_title(payload, target.bot_id),
        }
    except requests.HTTPError as error:
        status = (
            error.response.status_code if error.response is not None
            else getattr(error, "status_code", None)
        )
        code, message = {
            401: ("AuthenticationRequired", "Dataverse sign-in must be renewed."),
            403: (
                "AuthorizationDenied",
                "The authoring account is not authorized to read the selected "
                "agent's Dataverse metadata.",
            ),
            404: (
                "NotFound",
                "The configured agent was not found in the selected "
                "Dataverse environment.",
            ),
        }.get(
            status,
            ("ServiceError", "Dataverse could not resolve the selected agent."),
        )
        status_detail = f" (HTTP {status})" if status is not None else ""
        raise AgentTitleResolutionError(
            f"{message}{status_detail}. No titleId was resolved.",
            code=code, source="backend",
        ) from error
    except ValueError as error:
        raise AgentTitleResolutionError(
            "Dataverse returned an invalid discovery response. "
            "No titleId was resolved.",
            code="ServiceError", source="backend",
        ) from error
    except requests.RequestException as error:
        raise AgentTitleResolutionError(
            "Dataverse is temporarily unavailable. No titleId was resolved; "
            "retry when connectivity is restored.",
            code="NetworkError", source="backend",
        ) from error
