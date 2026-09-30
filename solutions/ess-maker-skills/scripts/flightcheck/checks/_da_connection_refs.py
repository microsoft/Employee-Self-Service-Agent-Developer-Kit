# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Canonical reader for Declarative Agent connection references.

Intended consumers:
  * ``DV-CONN-001`` (checks/workday_extension.py) -> the single active agent's
    Workday SOAP reference, via ``read_active_agent_connection_references``.
  * ``ENV-004`` (checks/environment.py) -> every configured agent's references,
    environment-wide and de-duped by logical name, via
    ``read_all_agents_connection_references``.

Read shape: ``POST .../components`` -> ``connectionReferenceChanges`` (cassette
``agentbuilder_readiness.yaml``, the same endpoint + shape the shipped native
``DA-CONN-001`` check consumes).

Fail-loudly contract:
  * a missing ``connectionReferenceChanges`` key means genuine absence -> ``[]``;
  * a present-but-malformed shape raises ``ValueError``; how to surface it is
    the consuming check's decision (catch and report a WARNING, or let it
    propagate so the runner records an ERROR) - this reader's only contract is
    "do not swallow it." No consumer imports this reader on this branch yet, so
    the runner's uncaught-raise -> ERROR mapping is documented runner behavior,
    not exercised here;
  * a read that cannot be attempted at all (no AgentBuilder client or no
    configured agent botId) returns ``None`` so the caller SKIPs.
"""

from __future__ import annotations

from typing import Any


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


def _bot_connection_references(client, bot_id: str) -> list[dict[str, Any]]:
    """Fetch + normalize one agent's connection references from the minimalBots
    components API.

    Raises ``ValueError`` for a malformed ``connectionReferenceChanges`` shape
    so the owning check can surface it (as a WARNING, or an uncaught raise the
    runner records as ERROR) instead of overclaiming; that choice belongs to
    the consumer.
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
        # Surface a malformed individual entry instead of silently skipping it
        # (PR #304 review): a non-dict change, or a ``connectionReference`` that
        # is present but not an object, no longer matches the validated
        # contract, so raise and let the owning check decide how to surface it.
        # An absent or null ``connectionReference`` is tolerated (a
        # non-connection change) and skipped - ``.get`` returns ``None`` for
        # both the missing-key and explicit-null cases.
        if not isinstance(change, dict):
            raise ValueError(
                "Component fetch returned a malformed "
                "connectionReferenceChanges entry."
            )
        item = change.get("connectionReference")
        if item is None:
            continue
        if not isinstance(item, dict):
            raise ValueError(
                "Component fetch returned a malformed connectionReference entry."
            )
        # A dict that parses but lacks its identity fields is just as
        # misleading as a non-dict (PR #304 review F-1): a row with a
        # null/blank connectionReferenceLogicalName or connectorId gets
        # silently skipped or misclassified by downstream consumers,
        # recreating the confident "not found" verdict this reader exists to
        # prevent. The validated payload always supplies both as non-empty
        # strings; only connectionId may legitimately be null (an unbound
        # reference), so require the two identity fields and raise on absence.
        logical_name = _require_identity_field(
            item.get("connectionReferenceLogicalName"),
            "connectionReferenceLogicalName",
        )
        connector_id = _require_identity_field(
            item.get("connectorId"), "connectorId"
        )
        refs.append(
            {
                "botid": bot_id,
                "connectionreferencelogicalname": logical_name,
                "connectorid": connector_id,
                "connectionid": item.get("connectionId"),
            }
        )
    return refs


def _require_identity_field(value: Any, field_name: str) -> str:
    """Return ``value`` as a non-empty string, or raise ``ValueError``.

    A connection reference's identity fields (``connectionReferenceLogicalName``,
    ``connectorId``) must be present and non-blank; a null/blank/non-string
    value is a malformed payload, not a legitimate absence.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Component fetch returned a connectionReference with a missing or "
            f"malformed {field_name}."
        )
    return value


def read_active_agent_connection_references(runner) -> list[dict[str, Any]] | None:
    """The single active agent's DA connection references (config
    ``agent.botId``), or ``None`` when the AgentBuilder client or the
    active-agent botId is unavailable.

    Intended for ``DV-CONN-001`` (checks/workday_extension.py), which validates
    the Workday SOAP connection reference on the agent under check. Scoping this
    to the active agent — not every configured agent — keeps the check from
    reporting on a Workday reference that belongs to a different agent.
    Raises ``ValueError`` for malformed components payloads.
    """
    client = getattr(runner, "agentbuilder", None)
    config = getattr(runner, "config", None) or {}
    agent_id = (config.get("agent") or {}).get("botId")
    if client is None or not agent_id:
        return None
    return _bot_connection_references(client, agent_id)


def _all_agents_connection_references(runner) -> list[dict[str, Any]] | None:
    """Every configured agent's DA connection references (multi-agent and
    single-agent config), preserving per-agent rows, or ``None`` when the
    AgentBuilder client is unavailable or no agent botId is configured.

    Used by the environment-wide ``ENV-004`` reader. Raises ``ValueError`` for
    malformed components payloads.
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

    Intended for ``ENV-004`` (checks/environment.py), which is environment-wide
    across every agent under check and reports one row per distinct logical
    name.
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
