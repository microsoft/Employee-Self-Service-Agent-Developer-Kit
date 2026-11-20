# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared, read-only Microsoft 365 registration resolution for configured DA agents."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import requests
from portalocker.exceptions import LockException

from _odata import _validate_title_id
from _tenant_context import configured_da_environment
from base_client import (
    _create_msal_app,
    account_for_identity,
    validate_token_identity,
)

_SOLUTION_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = _SOLUTION_ROOT / ".local" / "config.json"
sys.path.insert(0, str(_SOLUTION_ROOT / "scripts"))

from agentbuilder import (  # noqa: E402
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    agent_inventory_read_scopes,
    environment_id_from_host,
    validate_environment_host,
)


_LOGGER = logging.getLogger("ess-agentconfig.title-resolution")
_INTERACTIVE_SIGN_IN_TIMEOUT_SECONDS = 300


class AgentTitleResolutionError(RuntimeError):
    """A local, content-free diagnostic safe to return through the MCP."""

    def __init__(self, message: str, *, code: str, source: str = "mcp") -> None:
        super().__init__(message)
        self.code = code
        self.source = source


class TitleResolutionCoordinator:
    """Retain one bounded lookup across caller cancellation, without caching results."""

    def __init__(self) -> None:
        self._task: asyncio.Task[dict[str, str | None]] | None = None

    async def run(
        self,
        operation: Callable[[], Coroutine[Any, Any, dict[str, str | None]]],
    ) -> dict[str, str | None]:
        if self._task is not None and not self._task.done():
            raise AgentTitleResolutionError(
                "Agent title resolution is already in progress. Complete the "
                "pending sign-in or wait for the current lookup to finish "
                "before retrying.",
                code="ServiceError",
            )
        task = asyncio.create_task(operation())
        self._task = task
        task.add_done_callback(self._release)
        return await asyncio.shield(task)

    def _release(self, task: asyncio.Task[dict[str, str | None]]) -> None:
        if self._task is task:
            self._task = None
        if not task.cancelled():
            task.exception()


@dataclass(frozen=True)
class ConfiguredAgentTarget:
    bot_id: str
    environment_id: str
    host: str
    ring: str
    tenant_id: str


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
    """Bind an exact bot to the canonical DA environment, never a display name."""
    bot_id = _guid(bot_id, "botId")
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AgentTitleResolutionError(
            "The maker configuration could not be read. Complete /setup first.",
            code="InvalidRequest",
        ) from error
    if (
        not isinstance(config, dict)
        or config.get("setup") != "complete"
        or config.get("releaseLine") != "da"
    ):
        raise AgentTitleResolutionError(
            "Complete DA /setup before resolving a configured agent.",
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
    try:
        environment = configured_da_environment(config, config_path=CONFIG_PATH)
        if bot_id not in environment.agent_ids:
            raise ValueError
        if selected.get("releaseLine", "da") != "da":
            raise ValueError
        if (
            "environmentId" in selected
            and _guid(selected["environmentId"], "environmentId")
            != environment.environment_id
        ):
            raise ValueError
        if "ring" in selected and selected["ring"] != environment.ring:
            raise ValueError
        if "powerPlatformApiEndpoint" in selected:
            host = validate_environment_host(
                selected["powerPlatformApiEndpoint"], environment.ring
            )
            if (
                host != environment.host
                or environment_id_from_host(host, environment.ring)
                != environment.environment_id
            ):
                raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise AgentTitleResolutionError(
            "The selected agent conflicts with its canonical DA setup environment. "
            "Complete /setup for that agent; no other environment will be used.",
            code="InvalidRequest",
        ) from error
    return ConfiguredAgentTarget(
        bot_id, environment.environment_id, environment.host,
        environment.ring, environment.tenant_id,
    )


def acquire_power_platform_token(
    ring: str, tenant_id: str, object_id: str | None
) -> str:
    """Reuse the shared authoring cache for the same tenant and account."""
    if not object_id:
        raise AgentTitleResolutionError(
            "The authoring account cannot be identified. Sign in with a delegated "
            "AgentConfiguration token containing tid and oid claims.",
            code="AuthenticationRequired",
        )
    try:
        tenant_id = str(UUID(tenant_id))
        object_id = str(UUID(object_id))
        if not UUID(tenant_id).int or not UUID(object_id).int:
            raise ValueError
        scopes = list(agent_inventory_read_scopes(ring))
        app = _create_msal_app(str(UUID(tenant_id)))
        account = account_for_identity(app, tenant_id, object_id)
        result = (
            app.acquire_token_silent(scopes, account=account)
            if account is not None
            else None
        )
        if not isinstance(result, dict) or not result.get("access_token"):
            _LOGGER.info("Opening a browser for native agent metadata discovery.")
            try:
                result = app.acquire_token_interactive(
                    scopes,
                    prompt="select_account",
                    timeout=_INTERACTIVE_SIGN_IN_TIMEOUT_SECONDS,
                )
            except RuntimeError as error:
                raise AgentTitleResolutionError(
                    "Power Platform browser sign-in did not complete. Retry with "
                    "the current authoring account; the sign-in limit is "
                    f"{_INTERACTIVE_SIGN_IN_TIMEOUT_SECONDS} seconds.",
                    code="AuthenticationRequired",
                ) from error
        token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise ValueError
        return validate_token_identity(token, tenant_id, object_id)
    except AgentTitleResolutionError:
        raise
    except (
        ValueError, OSError, RuntimeError, LockException, requests.RequestException,
    ) as error:
        raise AgentTitleResolutionError(
            "Power Platform sign-in failed or selected a different tenant/account. "
            "Sign in with the current authoring account and retry.",
            code="AuthenticationRequired",
        ) from error


def _response_bot(payload: Any, field: str, bot_id: str) -> None:
    try:
        if not isinstance(payload, dict) or _guid(payload.get(field), field) != bot_id:
            raise ValueError
    except (ValueError, AgentTitleResolutionError) as error:
        raise AgentTitleResolutionError(
            "The Copilot Studio response did not identify the selected configured "
            "bot. No registration title IDs were accepted.",
            code="ServiceError", source="backend",
        ) from error


def _title(value: Any, field: str) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        return _validate_title_id(value)
    except ValueError as error:
        raise AgentTitleResolutionError(
            f"Copilot Studio returned an invalid Microsoft 365 {field}. "
            "No registration title IDs were accepted.",
            code="ServiceError", source="backend",
        ) from error


def _registered_titles(
    components: Any, publish_status: Any, bot_id: str
) -> dict[str, str | None]:
    bot = components.get("bot") if isinstance(components, dict) else None
    _response_bot(bot, "cdsBotId", bot_id)
    try:
        information = bot.get("teamsAppInformation")
        if information is not None and not isinstance(information, dict):
            raise ValueError
        metadata = information.get("microsoft365") if information is not None else None
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError
        if not isinstance(publish_status, dict) or "titleId" not in publish_status:
            raise ValueError
    except ValueError as error:
        raise AgentTitleResolutionError(
            "Copilot Studio returned malformed Microsoft 365 registration metadata. "
            "No registration title IDs were accepted.",
            code="ServiceError", source="backend",
        ) from error
    if "botId" in publish_status:
        _response_bot(publish_status, "botId", bot_id)
    titles = {
        "titleId": _title(metadata.get("titleId") if metadata else None, "titleId"),
        "lobTitleId": _title(publish_status["titleId"], "lobTitleId"),
    }
    if not any(titles.values()):
        raise AgentTitleResolutionError(
            "The selected agent has no Microsoft 365 registration titleId or lobTitleId. "
            "Publish/register this agent for Microsoft 365, then retry.",
            code="RegistrationRequired", source="backend",
        )
    return titles


def resolve_configured_agent_title(
    target: ConfiguredAgentTarget, tenant_id: str, object_id: str | None
) -> dict[str, str | None]:
    """Read native metadata off the event loop; never write tenant or local state."""
    if target.tenant_id != _guid(tenant_id, "tenantId"):
        raise AgentTitleResolutionError(
            "The authoring tenant does not match the configured DA environment. "
            "Sign in with the configured tenant/account and retry.",
            code="AuthenticationRequired",
        )
    try:
        token = acquire_power_platform_token(target.ring, tenant_id, object_id)
        with requests.Session() as session:
            client = AgentBuilderClient(
                target.host, token, ring=target.ring,
                tenant_id=target.tenant_id, session=session,
            )
            _response_bot(client.get_agent(target.bot_id), "botId", target.bot_id)
            components = client.fetch_components(target.bot_id)
            _response_bot(
                components.get("bot") if isinstance(components, dict) else None,
                "cdsBotId", target.bot_id,
            )
            publish_status = client.get_m365_publish_status(target.bot_id)
            return {
                "botId": target.bot_id,
                **_registered_titles(components, publish_status, target.bot_id),
            }
    except AgentBuilderHTTPError as error:
        code, message = {
            401: ("AuthenticationRequired", "Power Platform sign-in must be renewed."),
            403: (
                "AuthorizationDenied",
                "The authoring account is not authorized to read the selected "
                "agent's Copilot Studio metadata.",
            ),
            404: (
                "NotFound",
                "The configured agent or its M365 publish-status route was not found "
                "in the selected DA environment. This does not establish that a "
                "registration is absent; no backend switch was attempted.",
            ),
        }.get(
            error.status_code,
            ("ServiceError", "Copilot Studio could not resolve the selected agent."),
        )
        raise AgentTitleResolutionError(
            f"{message} (HTTP {error.status_code}). No registration title IDs were resolved.",
            code=code, source="backend",
        ) from error
    except (AgentBuilderError, ValueError) as error:
        raise AgentTitleResolutionError(
            "Copilot Studio returned an invalid discovery response. "
            "No registration title IDs were resolved.",
            code="ServiceError", source="backend",
        ) from error
    except requests.RequestException as error:
        raise AgentTitleResolutionError(
            "Copilot Studio is temporarily unavailable. No registration title IDs "
            "were resolved; retry when connectivity is restored.",
            code="NetworkError", source="backend",
        ) from error
