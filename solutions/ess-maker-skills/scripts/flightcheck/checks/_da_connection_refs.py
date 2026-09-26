# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Canonical reader for Declarative Agent connection references (minimalBots
components API), shared so the DA connection checks cannot drift apart.

Consumers:
  * ``DV-CONN-001`` (checks/workday_extension.py) -> the single active agent's
    Workday SOAP reference, via ``read_active_agent_connection_references``.
  * ``ENV-004`` (checks/environment.py) -> every configured agent's references,
    environment-wide and de-duped by logical name, via
    ``read_all_agents_connection_references``.
  * The Workday shared-parameter checks (checks/workday.py) -> per-agent Workday
    ``sharedConnectionParameters`` via ``workday_shared_connection_parameters``.

Read shape: ``POST .../components`` -> ``connectionReferenceChanges`` (cassette
``agentbuilder_readiness.yaml``, the same endpoint + shape the shipped native
``DA-CONN-001`` check consumes).

Fail-loudly contract:
  * a missing ``connectionReferenceChanges`` key means genuine absence -> ``[]``;
  * a present-but-malformed shape raises ``ValueError`` so the owning check
    degrades to a WARNING rather than reporting a confident but wrong verdict;
  * a read that cannot be attempted at all (no AgentBuilder client, or no
    configured agent botId) returns ``None`` so the caller SKIPs.
"""

from __future__ import annotations

import json
from typing import Any


WORKDAY_SOAP_CONNECTOR_SUFFIX = "/apis/shared_workdaysoap"


def agent_bot_ids(config: dict[str, Any]) -> list[str]:
    """Return configured bot IDs from multi-agent and single-agent config."""
    bot_ids: list[str] = []
    for agent in config.get("agents", []) or []:
        bid = (agent or {}).get("botId")
        if isinstance(bid, str) and bid.strip():
            bot_ids.append(bid.strip())
    single = (config.get("agent") or {}).get("botId")
    if isinstance(single, str) and single.strip():
        bot_ids.append(single.strip())

    seen: set[str] = set()
    ordered: list[str] = []
    for bot_id in bot_ids:
        folded = bot_id.casefold()
        if folded not in seen:
            seen.add(folded)
            ordered.append(bot_id)
    return ordered


def active_agent_bot_id(config: dict[str, Any]) -> str | None:
    """Return the exact active agent bot ID from supported config shapes."""
    active_slug = config.get("activeAgent")
    if isinstance(active_slug, str) and active_slug.strip():
        for agent in config.get("agents", []) or []:
            if not isinstance(agent, dict) or agent.get("slug") != active_slug:
                continue
            bot_id = agent.get("botId")
            if isinstance(bot_id, str) and bot_id.strip():
                return bot_id.strip()

    single = config.get("agent") or {}
    single_bot_id = single.get("botId") if isinstance(single, dict) else None
    if isinstance(single_bot_id, str) and single_bot_id.strip():
        return single_bot_id.strip()
    return None


def _bot_connection_references(client, bot_id: str) -> list[dict[str, Any]]:
    """Fetch + normalize one agent's connection references from the minimalBots
    components API.

    Raises ``ValueError`` for a malformed ``connectionReferenceChanges`` shape
    so the owning check reports a WARNING instead of overclaiming.
    """
    changeset = client.fetch_components(bot_id) or {}
    changes = changeset.get("connectionReferenceChanges")
    if changes is None:
        return []
    if not isinstance(changes, list):
        raise ValueError(
            "Component fetch returned invalid connectionReferenceChanges."
        )

    refs: list[dict[str, Any]] = []
    for change in changes:
        item = (
            change.get("connectionReference")
            if isinstance(change, dict)
            else None
        )
        if not isinstance(item, dict):
            continue
        refs.append(
            {
                "botid": bot_id,
                "connectionreferencelogicalname": item.get(
                    "connectionReferenceLogicalName"
                ),
                "connectorid": item.get("connectorId"),
                "connectionid": item.get("connectionId"),
                "sharedconnectionparameters": item.get(
                    "sharedConnectionParameters"
                ),
            }
        )
    return refs


def read_active_agent_connection_references(runner) -> list[dict[str, Any]] | None:
    """The active agent's DA connection references.

    Resolves either the single-agent ``agent.botId`` shape or
    ``activeAgent`` against the multi-agent ``agents`` collection. Returns
    ``None`` when the AgentBuilder client or active-agent bot ID is unavailable.

    Used by ``DV-CONN-001`` (checks/workday_extension.py), which validates the
    Workday SOAP connection reference on the agent under check. Scoping this to
    the active agent — not every configured agent — keeps the check from
    reporting on a Workday reference that belongs to a different agent.
    Raises ``ValueError`` for malformed components payloads.
    """
    client = getattr(runner, "agentbuilder", None)
    config = getattr(runner, "config", None) or {}
    agent_id = active_agent_bot_id(config)
    if client is None or not agent_id:
        return None
    return _bot_connection_references(client, agent_id)


def _all_agents_connection_references(runner) -> list[dict[str, Any]] | None:
    """Every configured agent's DA connection references (multi-agent and
    single-agent config), preserving per-agent rows, or ``None`` when the
    AgentBuilder client is unavailable or no agent botId is configured.

    Used by the Workday shared-parameter sweep, which must inspect each
    configured agent's own Workday reference rather than only the active one.
    Raises ``ValueError`` for malformed components payloads.
    """
    client = getattr(runner, "agentbuilder", None)
    config = getattr(runner, "config", None) or {}
    bot_ids = agent_bot_ids(config)
    if client is None or not bot_ids:
        return None

    refs: list[dict[str, Any]] = []
    for bot_id in bot_ids:
        refs.extend(_bot_connection_references(client, bot_id))
    return refs


def read_all_agents_connection_references(
    runner,
) -> list[dict[str, Any]] | None:
    """Every configured agent's references, de-duped by connection-reference
    logical name (first occurrence wins, order preserved), or ``None`` when the
    AgentBuilder client is unavailable or no agent botId is configured.

    Used by ``ENV-004`` (checks/environment.py), which is environment-wide
    across every agent under check and reports one row per distinct logical
    name. The per-agent (non-de-duped) view is ``_all_agents_connection_references``,
    which the Workday shared-parameter sweep uses instead.
    """
    refs = _all_agents_connection_references(runner)
    if refs is None:
        return None
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for ref in refs:
        key = (ref.get("connectionreferencelogicalname") or "").casefold()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(ref)
    return deduped


def _shared_parameter_value(raw_value: Any) -> str:
    if isinstance(raw_value, dict):
        raw_value = raw_value.get("value")
    if raw_value is None:
        return ""
    return str(raw_value).strip()


def shared_connection_parameter_values(ref: dict[str, Any]) -> dict[str, str]:
    """Return ``sharedConnectionParameters.values`` as a string map.

    A present-but-malformed shape raises ``ValueError`` because the components
    payload no longer matches the validated contract.
    """
    params = ref.get("sharedconnectionparameters")
    if params is None:
        return {}
    # Live AgentBuilder returns sharedConnectionParameters as a JSON string,
    # not a nested object (observed on a live connection reference), so parse
    # the string before validating the shape.
    if isinstance(params, str):
        text = params.strip()
        if not text:
            return {}
        try:
            params = json.loads(text)
        except ValueError as exc:
            raise ValueError(
                "Component fetch returned invalid sharedConnectionParameters."
            ) from exc
    if not isinstance(params, dict):
        raise ValueError(
            "Component fetch returned invalid sharedConnectionParameters."
        )
    raw_values = params.get("values")
    if raw_values is None:
        return {}
    if not isinstance(raw_values, dict):
        raise ValueError(
            "Component fetch returned invalid sharedConnectionParameters.values."
        )
    return {
        str(key): value
        for key, raw_value in raw_values.items()
        if isinstance(key, str)
        if (value := _shared_parameter_value(raw_value))
    }


def workday_shared_connection_parameters(
    runner,
) -> tuple[dict[str, str] | None, str]:
    """Return Workday ``sharedConnectionParameters.values`` from components.

    ``values is None`` means the check could not run because AgentBuilder or a
    botId is unavailable. ``values == {}`` means the check ran and observed a
    missing Workday reference or missing shared parameters.
    """
    refs = _all_agents_connection_references(runner)
    if refs is None:
        return None, (
            "AgentBuilder client or a configured agent botId not available"
        )

    found_workday_ref = False
    for ref in refs:
        connector_id = str(ref.get("connectorid") or "").casefold().rstrip("/")
        if connector_id.endswith(WORKDAY_SOAP_CONNECTOR_SUFFIX):
            found_workday_ref = True
            values = shared_connection_parameter_values(ref)
            if values:
                return values, ""

    if found_workday_ref:
        return {}, (
            "Workday connection reference is missing "
            "sharedConnectionParameters.values"
        )

    return {}, "Workday connection reference was not found"
