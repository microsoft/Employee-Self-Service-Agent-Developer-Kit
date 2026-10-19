# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Resolve one configured agent's Microsoft 365 title through AgentBuilder."""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import msal
import requests
from portalocker.exceptions import LockException

from validation import validate_title_id


_SOLUTION_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = _SOLUTION_ROOT / ".local" / "config.json"
sys.path.insert(0, str(_SOLUTION_ROOT / "scripts"))

from agentbuilder import (  # noqa: E402
    CLIENT_ID,
    RING_CONFIG,
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    derive_environment_host,
    environment_id_from_host,
    list_environments,
    minimal_bot_read_scope,
    ring_from_environment_host,
    validate_environment_host,
)
from base_client import (  # noqa: E402
    _TOKEN_CACHE_PATH,
    account_for_identity,
    validate_token_identity,
)
from _odata import _validate_https_base_url  # noqa: E402
from _token_cache import create_token_cache  # noqa: E402


AGENTBUILDER_TOKEN_CACHE_PATH = Path(_TOKEN_CACHE_PATH)
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
    ring: str
    environment_id: str | None
    host: str | None
    dataverse_endpoint: str | None


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


def _environment_id(value: Any) -> str:
    if isinstance(value, str) and value.casefold().startswith("default-"):
        value = value[len("default-"):]
    return _guid(value, "environmentId")


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

    # An agent-specific environment must not inherit another agent's API host.
    has_own_environment = any(
        selected.get(key) is not None
        for key in ("environmentId", "powerPlatformApiEndpoint", "dataverseEndpoint")
    )
    environment = selected if has_own_environment else config
    raw_environment_id = environment.get("environmentId")
    environment_id = (
        _environment_id(raw_environment_id)
        if raw_environment_id is not None
        else None
    )
    host = environment.get("powerPlatformApiEndpoint")
    ring = environment.get("ring")
    endpoint = environment.get("dataverseEndpoint")
    try:
        if host is not None:
            if not isinstance(host, str):
                raise ValueError
            host_ring = ring_from_environment_host(host)
            if ring is not None and ring != host_ring:
                raise ValueError
            ring = host_ring
            host = validate_environment_host(host, ring)
            host_environment_id = _environment_id(environment_id_from_host(host, ring))
            if environment_id is not None and environment_id != host_environment_id:
                raise ValueError
            environment_id = host_environment_id
        ring = ring if ring is not None else config.get("ring", "prod")
        if not isinstance(ring, str) or ring not in RING_CONFIG:
            raise ValueError
        if endpoint is not None:
            endpoint = _validate_https_base_url(endpoint, "dataverseEndpoint")
    except (ValueError, TypeError, AttributeError) as error:
        raise AgentTitleResolutionError(
            "The selected agent's environment, API host, or service ring is invalid "
            "or inconsistent. Confirm its environment in /setup.",
            code="InvalidRequest",
        ) from error
    if environment_id is None and endpoint is None:
        raise AgentTitleResolutionError(
            "The selected agent has no configured environmentId or Dataverse URL. "
            "Complete /setup for that agent.",
            code="InvalidRequest",
        )
    return ConfiguredAgentTarget(bot_id, ring, environment_id, host, endpoint)


def acquire_agentbuilder_token(
    tenant_id: str, object_id: str | None, scopes: list[str]
) -> str:
    """Reuse the shared authoring cache for the same tenant and account."""
    if not object_id:
        raise AgentTitleResolutionError(
            "The authoring account cannot be identified. Sign in with a delegated "
            "AgentConfiguration token containing tid and oid claims.",
            code="AuthenticationRequired",
        )
    try:
        app = msal.PublicClientApplication(
            CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{UUID(tenant_id)}",
            token_cache=create_token_cache(str(AGENTBUILDER_TOKEN_CACHE_PATH)),
        )
        account = account_for_identity(app, tenant_id, object_id)
        result = (
            app.acquire_token_silent(scopes, account=account)
            if account is not None
            else None
        )
        if not isinstance(result, dict) or not result.get("access_token"):
            _LOGGER.info("Opening a browser for Power Platform component discovery.")
            result = app.acquire_token_interactive(scopes, prompt="select_account")
        token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError
        return validate_token_identity(token, tenant_id, object_id)
    except (ValueError, OSError, LockException, requests.RequestException) as error:
        raise AgentTitleResolutionError(
            "Power Platform sign-in failed or selected a different tenant/account. "
            "Sign in with the current announcement authoring account and retry.",
            code="AuthenticationRequired",
        ) from error


def _dataverse_hostname(url: str) -> str:
    hostname = (urlparse(url).hostname or "").casefold()
    # Dataverse web and Web API endpoints identify the same environment.
    return re.sub(r"\.api\.(crm[0-9]*\.dynamics\.com)$", r".\1", hostname)


def _resolve_environment(
    target: ConfiguredAgentTarget, environments: list[dict[str, Any]], tenant_id: str
) -> str:
    wanted = _dataverse_hostname(target.dataverse_endpoint or "")
    matches: set[str] = set()
    for environment in environments:
        try:
            url = environment.get("url")
            if url is not None and not isinstance(url, str):
                raise ValueError
            if not url:
                domain = environment.get("domainName")
                if domain is not None and not isinstance(domain, str):
                    raise ValueError
                url = f"https://{domain}" if domain else ""
            if not url:
                continue
            url = _validate_https_base_url(url, "Power Platform environment URL")
            if _dataverse_hostname(url) != wanted:
                continue
            if (
                environment.get("tenantId") is not None
                and _guid(environment["tenantId"], "tenantId") != tenant_id
            ):
                raise ValueError
            matches.add(_environment_id(environment.get("id")))
        except (ValueError, AgentTitleResolutionError) as error:
            raise AgentTitleResolutionError(
                "Power Platform returned inconsistent environment metadata. "
                "No titleId was resolved.",
                code="ServiceError",
                source="backend",
            ) from error
    if len(matches) != 1:
        raise AgentTitleResolutionError(
            "The configured Dataverse URL did not identify exactly one Power "
            "Platform environment available to the authoring account. Confirm "
            "the selected environment and access in /setup.",
            code="NotFound",
            source="backend",
        )
    return matches.pop()


def _registered_title(payload: dict[str, Any], bot_id: str) -> str:
    bot = payload.get("bot")
    try:
        if not isinstance(bot, dict) or _guid(bot.get("cdsBotId"), "cdsBotId") != bot_id:
            raise ValueError
    except (ValueError, AgentTitleResolutionError) as error:
        raise AgentTitleResolutionError(
            "The component response did not identify the selected configured bot. "
            "No titleId was accepted.",
            code="ServiceError",
            source="backend",
        ) from error
    metadata = bot
    for field in ("teamsAppInformation", "microsoft365"):
        value = metadata.get(field)
        if value is None:
            raise AgentTitleResolutionError(
                "The selected agent has no Microsoft 365 registration titleId. "
                "Publish/register this agent for Microsoft 365, then retry.",
                code="RegistrationRequired",
                source="backend",
            )
        if not isinstance(value, dict):
            raise AgentTitleResolutionError(
                "The component response contains malformed Microsoft 365 "
                "registration metadata. No titleId was accepted.",
                code="ServiceError",
                source="backend",
            )
        metadata = value
    title_id = metadata.get("titleId")
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
            "The component response contains an invalid Microsoft 365 titleId. "
            "No titleId was accepted.",
            code="ServiceError",
            source="backend",
        ) from error


def resolve_configured_agent_title(
    target: ConfiguredAgentTarget, tenant_id: str, object_id: str | None
) -> dict[str, str]:
    """Read components off the event loop; never write tenant or local state."""
    try:
        with requests.Session() as session:
            environment_id = target.environment_id
            if environment_id is None:
                # The documented environment-list API uses .default, separately
                # from the component-read scope; MSAL cannot mix those requests.
                inventory_token = acquire_agentbuilder_token(
                    tenant_id, object_id,
                    [f"{RING_CONFIG[target.ring]['audience']}/.default"],
                )
                environments = list_environments(
                    inventory_token, target.ring, session=session
                )
                environment_id = _resolve_environment(target, environments, tenant_id)
            host = target.host or derive_environment_host(environment_id, target.ring)
            token = acquire_agentbuilder_token(
                tenant_id, object_id, [minimal_bot_read_scope(target.ring)]
            )
            client = AgentBuilderClient(
                host, token, ring=target.ring, tenant_id=tenant_id, session=session
            )
            payload = client.fetch_components(target.bot_id)
            return {
                "botId": target.bot_id,
                "environmentId": environment_id,
                "titleId": _registered_title(payload, target.bot_id),
            }
    except AgentBuilderHTTPError as error:
        status = error.status_code
        code, message = {
            401: ("AuthenticationRequired", "Power Platform sign-in must be renewed."),
            403: (
                "AuthorizationDenied",
                "The authoring account is not authorized to read the selected "
                "agent's Power Platform metadata.",
            ),
            404: (
                "NotFound",
                "The configured agent or environment was not found in Power Platform.",
            ),
        }.get(
            status,
            ("ServiceError", "Power Platform could not resolve the selected agent."),
        )
        raise AgentTitleResolutionError(
            f"{message} (HTTP {status}). No titleId was resolved.",
            code=code, source="backend",
        ) from error
    except requests.RequestException as error:
        raise AgentTitleResolutionError(
            "Power Platform is temporarily unavailable. No titleId was resolved; "
            "retry when connectivity is restored.",
            code="NetworkError", source="backend",
        ) from error
    except AgentBuilderError as error:
        raise AgentTitleResolutionError(
            "Power Platform returned an invalid discovery response. "
            "No titleId was resolved.",
            code="ServiceError", source="backend",
        ) from error
