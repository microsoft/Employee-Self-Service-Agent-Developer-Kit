# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ENV-004 helper — resolve the connection references an ESS agent uses.

ENV-004 (``environment.py:_check_connections_and_refs``) historically
judged **every** ``connectionreference`` row in the environment. That
produced false FAILs on refs an ESS agent never touches — most visibly
the ESS-shipped placeholder refs that ship *unbound by design* on a
Workday **simplified** install (``msdyn_Dataverse`` /
``msdyn_ContentConversion`` with ``connectionid = null``). A customer
running any other Power Platform app in the same environment would also
see that app's refs judged against ESS's expectations.

This module builds the **allow-list of connection references the agent
actually uses** so ENV-004 can scope its verdict to them. The chain:

    config agent botId(s)
      -> Dataverse ``botcomponents`` (enabled topics: componenttype 9,
         statecode 0) ``data`` column (the topic YAML)
      -> extract every ``flowId:`` referenced by an InvokeFlowAction
      -> Power Platform Admin ``pp.get_flow(env_id, flow_id)`` (BAP
         per-flow detail) for each discovered flowId
      -> read ``properties.connectionReferences[*]`` from that detail for
         its ``connectionReferenceLogicalName`` (the allow-list) and its
         connector (for scoping the unbound-connection branch).

Why this join is sound (the flowId↔flow identity linkage):
  A Power Automate cloud flow's identity is a single GUID that is the
  same across surfaces — the topic's ``InvokeFlowAction.flowId``, the
  Dataverse ``workflow.workflowid``, and the BAP flow detail endpoint's
  ``/flows/{id}`` key. ``scripts/fetch_and_setup.py`` and LIC-FLOW-001
  (``licensing.py``) both rely on exactly this equality — LIC-FLOW-001
  passes each topic flowId straight to ``pp.get_flow(env_id, flow_id)``
  — so we do the same.

Why the per-flow detail (not the listing):
  The connection references block lives ONLY in the per-flow DETAIL
  response. The flow LISTING (``pp.get_flows`` -> ``/v2/flows``) omits
  ``properties.connectionReferences`` entirely (verified against the
  cassette). Reading refs off the listing yields an empty allow-list,
  which silently turns ENV-004 into a no-op — the bug this design avoids.

External API contract tiers (per tests/fixtures/cassettes/INDEX.md):
  - Dataverse ``botcomponents`` ``$select=name,schemaname,data`` /
    ``$filter`` — ``documented`` tier (INDEX.md "API tier registry";
    the ``data`` column is the topic YAML per the MS Learn
    ``botcomponent`` reference). ``$filter`` narrowing needs no cassette.
  - Power Platform Admin ``/flows/{id}`` per-flow detail — ``validated``
    tier, cassette
    ``tests/fixtures/cassettes/flightcheck_flow_licensing.yaml``
    (INDEX.md "Confirmed endpoints"); the detail record exposes
    ``properties.connectionReferences.<connector>.{connectionReferenceLogicalName,apiDefinition}``.

Contract of :func:`build_agent_ref_scope`:
  - Returns an :class:`AgentRefScope` when the agent's used refs were
    resolved (possibly empty logical-name set if the matched flows carry
    no connection references).
  - Returns ``None`` when scoping cannot be established at all (no
    configured botId, no Dataverse creds, no BAP client/env, no flowIds
    discovered in the agent's topics, or none of the discovered flowIds
    matched a flow returned by the admin surface). The caller SKIPs
    rather than falling back to an env-wide verdict — a misleading
    env-wide FAIL is worse than an honest SKIP.
  - Raises on genuine API errors (Dataverse query exception, admin
    ``_error`` payload). The caller converts these to a WARNING so the
    failure is surfaced, not silently swallowed (design principle 3).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ._dlp_utils import normalize_connector_id
from auth import query_all  # scripts/auth.py, on path via cli.py


# Matches ``flowId: <guid>`` (optionally quoted) inside an
# InvokeFlowAction block of a topic's YAML. Mirrors
# ``scripts/fetch_and_setup.py:discover_flow_ids_from_components`` so the
# two stay in agreement about what a topic flow reference looks like.
_FLOW_ID_RE = re.compile(
    r'flowId:\s*["\']?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
    r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})',
)


@dataclass(frozen=True)
class AgentRefScope:
    """The connection references (and their connectors) an agent uses.

    ``logical_names`` — lowercased ``connectionReferenceLogicalName``
    values the agent's flows bind to. ENV-004 keeps only Dataverse
    ``connectionreference`` rows whose logical name is in this set.

    ``connectors`` — normalized connector ids (see
    :func:`_dlp_utils.normalize_connector_id`) the agent's flows use.
    ENV-004 scopes its unbound-connection (UC) warning to connections
    whose connector is in this set, so unrelated apps' connections
    don't get flagged.
    """

    logical_names: frozenset[str]
    connectors: frozenset[str]


def _agent_bot_ids(config: dict) -> list[str]:
    """Every configured agent botId (multi-agent + single-agent shapes)."""
    bot_ids: list[str] = []
    for agent in config.get("agents", []) or []:
        bid = (agent or {}).get("botId")
        if bid:
            bot_ids.append(bid)
    if not bot_ids:
        single = (config.get("agent") or {}).get("botId")
        if single:
            bot_ids.append(single)
    # De-dupe while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for bid in bot_ids:
        if bid not in seen:
            seen.add(bid)
            ordered.append(bid)
    return ordered


def _extract_flow_ids(topic_data: str) -> set[str]:
    """Lowercased flowIds referenced by InvokeFlowActions in a topic."""
    if not topic_data:
        return set()
    return {m.group(1).lower() for m in _FLOW_ID_RE.finditer(topic_data)}


def build_agent_ref_scope(runner) -> AgentRefScope | None:
    """Resolve the connection references the configured agent(s) use.

    See the module docstring for the full contract. Returns an
    :class:`AgentRefScope`, or ``None`` when scoping can't be
    established. Raises on genuine API errors.
    """
    config = getattr(runner, "config", None) or {}
    bot_ids = _agent_bot_ids(config)
    if not bot_ids:
        return None

    env_url = getattr(runner, "env_url", None)
    dv_token = getattr(runner, "dv_token", None)
    if not env_url or not dv_token:
        return None

    # --- Step 1: enabled topics -> flowIds ---
    # statecode 0 = Active/Enabled (see local_files.py; a disabled topic
    # never runs, so a ref only reachable through a disabled topic is not
    # a live runtime dependency and must not drive a FAIL).
    flow_ids: set[str] = set()
    for bot_id in bot_ids:
        topics = query_all(
            env_url, dv_token,
            "botcomponents",
            "name,schemaname,data",
            filter_expr=(
                f"_parentbotid_value eq '{bot_id}' "
                f"and componenttype eq 9 and statecode eq 0"
            ),
        )
        for topic in topics or []:
            flow_ids |= _extract_flow_ids(topic.get("data") or "")

    if not flow_ids:
        # The agent's enabled topics invoke no cloud flows we can see.
        # We cannot build an allow-list, so we must not judge env-wide
        # refs — signal "unresolvable" and let the caller SKIP.
        return None

    # --- Step 2: read each agent flow's DETAIL for its connection refs ---
    # A flow's connection references (and their connectors) live ONLY in
    # the per-flow DETAIL response (``pp.get_flow`` -> ``/flows/{id}``).
    # The flow LISTING (``pp.get_flows`` -> ``/v2/flows``) omits
    # ``properties.connectionReferences`` entirely — verified against
    # ``tests/fixtures/cassettes/flightcheck_flow_licensing.yaml`` (listing
    # records carry only apiId/state/workflowEntityId/...). This mirrors
    # LIC-FLOW-001 (``licensing.py``), which likewise resolves refs by
    # calling ``get_flow`` per discovered flowId — the topic flowId is the
    # flow's workflow GUID and the detail endpoint is keyed by it.
    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    if not pp or not env_id:
        return None

    logical_names: set[str] = set()
    connectors: set[str] = set()
    readable = 0
    for flow_id in sorted(flow_ids):
        try:
            detail = pp.get_flow(env_id, flow_id)
        except Exception as e:  # surfaced as a WARNING by the caller
            raise RuntimeError(
                f"Power Platform Admin flow detail fetch failed for {flow_id}: {e}"
            )
        # pp_admin maps 401/403 to {"_error","_status"} without raising. An
        # auth/permission failure means scoping is unreliable, so fail
        # loudly (principle 3) — the caller turns this into a WARNING.
        if isinstance(detail, dict) and detail.get("_status") in (401, 403):
            raise RuntimeError(
                f"Power Platform Admin flow detail unauthorized for {flow_id}: "
                f"{detail.get('_error')}"
            )
        # A flow that is missing / not visible (404, None, other _error)
        # just isn't readable; other flows may still resolve, so skip it
        # rather than aborting the whole scope.
        if not detail or (isinstance(detail, dict) and detail.get("_error")):
            continue
        readable += 1
        conn_refs = (detail.get("properties") or {}).get("connectionReferences") or {}
        for _connector_key, meta in conn_refs.items():
            meta = meta or {}
            logical = meta.get("connectionReferenceLogicalName")
            if logical:
                logical_names.add(str(logical).lower())
            api_def = meta.get("apiDefinition") or {}
            connector = normalize_connector_id(
                api_def.get("name")
                or api_def.get("id")
                or meta.get("apiName")
                or meta.get("apiId")
            )
            if connector:
                connectors.add(connector)

    if readable == 0:
        # We found flowIds in the agent's topics but none resolved to a
        # readable flow on the admin surface (not visible to this caller,
        # or genuinely absent). Scoping is unreliable — SKIP rather than
        # under-report (a misleading env-wide verdict is worse).
        return None

    return AgentRefScope(
        logical_names=frozenset(logical_names),
        connectors=frozenset(connectors),
    )
