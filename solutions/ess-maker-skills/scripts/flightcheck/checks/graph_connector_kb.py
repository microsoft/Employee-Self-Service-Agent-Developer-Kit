# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Graph Connector Knowledge Source readiness (EXT-002)

Conditional check, gated on the ESS agent actually using a Microsoft Graph
Connector as a knowledge source. The OOTB ESS knowledge path is the native
SharePoint/OneDrive integration (``SharePointSearchSource``); Graph
Connectors are an opt-in path documented at:

  solutions/ess-maker-skills/src/reference/ess-docs/operations/known-issues-limitations.md
  solutions/ess-maker-skills/src/reference/ess-docs/deployment/deployment-checklist.md

When a customer DOES choose to attach a Graph Connector knowledge source
(``$kind: GraphConnectorSearchSource``), the silent failure mode is
severe: ``ScdPreprocessingValidatorPlugin`` returns HTTP 400 ``Invalid
Connector provider Request`` and KB-grounded queries produce a generic
"An unexpected error has occurred" with no actionable signal to the user.
This check pre-flights the connector state via the Microsoft Graph
external connectors API so the misconfiguration surfaces before deploy.

Pattern: mirrors WD-CONN-* / SN-001 — only runs when the relevant
solution/source is present, never false-positives the OOTB path.

What is validated (per Graph Connector knowledge source on the agent):

  * The referenced connection exists in the tenant
    (``GET /v1.0/external/connections``) — referenced-but-missing is the
    most common deploy-time failure.
  * ``connection.state == "ready"`` — ``draft`` / ``obsolete`` /
    ``limitExceeded`` mean the connector is not serving search results
    even though the agent references it.
  * Most recent crawl operation (``GET /v1.0/external/connections/{id}
    /operations``) is ``completed`` — ``failed`` is a silent failure;
    ``inprogress`` is surfaced as a warning so the operator waits.

What is NOT automated (surfaced as ``NOT_CONFIGURED`` manual check):

  * Item-level ACL inspection. The Graph external connectors API exposes
    items as PUT-only — there is no ``list items`` operation, so a
    deny-shadowing audit must be performed in the M365 Admin Center or
    via the connector's own admin tooling.
  * Tenant-wide search audience restriction
    (M365 Admin Center → Search & Intelligence → Data Sources). This
    setting is not exposed via Microsoft Graph today.

API tier: Microsoft Graph v1.0 is the ``validatable`` tier (see
``tests/fixtures/cassettes/INDEX.md`` API tier registry). The
externalConnection / connectionOperation entities + their fields are
verified against the public CSDL at
``https://graph.microsoft.com/v1.0/$metadata`` — see
``tests/mocks/graph.py`` mock builders for the per-property citation.
"""

from __future__ import annotations

from typing import Any

from ..runner import CheckResult, Status, Priority

DOC_BASE = "https://learn.microsoft.com/graph/api"
ESS_KNOWN_ISSUES_DOC = (
    "https://learn.microsoft.com/microsoft-365/copilot/employee-self-service/"
    "known-issues-limitations"
)

# A connection in any of these states is not actively serving search
# results — see externalConnectors.connectionState in the Graph CSDL.
_NON_READY_STATES = {"draft", "obsolete", "limitexceeded"}


def run_graph_connector_kb_checks(runner) -> list[CheckResult]:
    """Validate Graph Connector knowledge sources attached to the ESS agent.

    Conditional: returns ``[]`` (silently skipped) if the agent has no
    Graph Connector knowledge sources, mirroring the WD-CONN-001 gate
    on ``runner._workday_flows``. Only customers who opted into the
    Graph Connector path see EXT-002 results.
    """
    pva = getattr(runner, "pva", None)
    graph = getattr(runner, "graph", None)
    config = getattr(runner, "config", {}) or {}
    bot_id = config.get("agent", {}).get("botId")

    # Gate 1: need PVA (Island Gateway) to enumerate the agent's
    # knowledge sources. Without it, we cannot know whether a Graph
    # Connector is in play, so we cannot meaningfully run EXT-002 — return
    # nothing rather than a noisy SKIPPED on every full run that lacks
    # PVA auth.
    if not pva or not getattr(pva, "is_configured", False) or not bot_id:
        return []

    try:
        knowledge_sources = pva.get_knowledge_sources(bot_id)
    except Exception:
        # Don't double-warn — CONFIG-013 already surfaces PVA errors.
        return []

    gc_sources = _filter_graph_connector_sources(knowledge_sources)

    # Gate 2: agent does NOT use a Graph Connector knowledge source. This
    # is the OOTB path — silently skip so EXT-002 never false-positives
    # native SharePoint deployments.
    if not gc_sources:
        return []

    results: list[CheckResult] = []

    # Gate 3: we have Graph Connector sources to validate but no Graph
    # client. Surface as WARNING (not skipped) — the customer DID opt
    # into the at-risk path, so silence would defeat the point.
    if not graph:
        results.append(CheckResult(
            checkpoint_id="EXT-002",
            category="Graph Connector KB",
            priority=Priority.HIGH.value,
            status=Status.WARNING.value,
            description="Graph Connector knowledge source readiness",
            result=(
                f"{len(gc_sources)} Graph Connector knowledge source(s) attached but "
                "Microsoft Graph authentication is unavailable — cannot validate "
                "connector state."
            ),
            remediation=(
                "Re-run FlightCheck after signing into Microsoft Graph "
                "(ExternalConnection.Read.All) to validate Graph Connector readiness."
            ),
            doc_link=f"{DOC_BASE}/externalconnectors-externalconnection-get",
        ))
        return results

    # Look up tenant connections once.
    try:
        connections = graph.get_external_connections()
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="EXT-002",
            category="Graph Connector KB",
            priority=Priority.HIGH.value,
            status=Status.WARNING.value,
            description="Graph Connector knowledge source readiness",
            result=f"Unable to list external connections: {e}",
            remediation=(
                "Verify the signed-in account has the ExternalConnection.Read.All "
                "Microsoft Graph delegated permission, then re-run FlightCheck."
            ),
            doc_link=f"{DOC_BASE}/externalconnectors-external-list-connections",
        ))
        return results

    # If listing returned the kit's standard 401/403 sentinel, it is a
    # list payload of zero items (see GraphClient.get_all line 154-155
    # which returns partial results on auth errors). Distinguish that
    # from a real "no connectors exist" state by also probing the named
    # connector below — the per-source check will surface the right
    # error (insufficient_permissions vs. not_found).

    by_id = {c.get("id"): c for c in connections if isinstance(c, dict) and c.get("id")}
    by_name = {c.get("name"): c for c in connections if isinstance(c, dict) and c.get("name")}

    # ---- EXT-002 summary ----
    failed: list[str] = []
    warned: list[str] = []
    passed: list[str] = []

    # Per-source detail rows (EXT-002-001, EXT-002-002, ...).
    for i, src in enumerate(gc_sources, start=1):
        cid = f"EXT-002-{i:03d}"
        ref = _connector_reference(src)
        display = (
            src.get("contentSourceDisplayName")
            or src.get("connectionName")
            or ref
            or f"Knowledge source {i}"
        )

        if not ref:
            failed.append(display)
            results.append(CheckResult(
                checkpoint_id=cid,
                category="Graph Connector KB",
                priority=Priority.HIGH.value,
                status=Status.WARNING.value,
                description=f"Graph Connector: {display}",
                result=(
                    "Knowledge source has no connection identifier we can "
                    "match against Microsoft Graph (no connectionName or "
                    "connectionId field)."
                ),
                remediation=(
                    "Open the agent in Copilot Studio → Knowledge → "
                    f"'{display}' and confirm the Graph Connector reference "
                    "is set; otherwise re-attach the knowledge source."
                ),
            ))
            continue

        # Try the most-likely-to-match strategies in order:
        #   1. The reference is the connector id (per externalConnection
        #      schema, id is admin-assigned and unique within tenant).
        #   2. The reference is the connector display name.
        #   3. Targeted GET /external/connections/{id} (covers connectors
        #      not returned by the list-call due to paging).
        connection = by_id.get(ref) or by_name.get(ref)
        if not connection:
            try:
                fetched = graph.get_external_connection(ref)
            except Exception as e:
                failed.append(display)
                results.append(CheckResult(
                    checkpoint_id=cid,
                    category="Graph Connector KB",
                    priority=Priority.HIGH.value,
                    status=Status.WARNING.value,
                    description=f"Graph Connector: {display}",
                    result=f"Unable to fetch connection '{ref}': {e}",
                ))
                continue
            if isinstance(fetched, dict) and fetched.get("_status") == 404:
                failed.append(display)
                results.append(CheckResult(
                    checkpoint_id=cid,
                    category="Graph Connector KB",
                    priority=Priority.HIGH.value,
                    status=Status.FAILED.value,
                    description=f"Graph Connector: {display}",
                    result=(
                        f"Knowledge source references connection '{ref}', "
                        "but no Microsoft Graph external connection with that "
                        "id or name exists in the tenant."
                    ),
                    remediation=(
                        "Either provision the missing Graph Connector in M365 "
                        "Admin Center → Search & Intelligence → Data Sources, "
                        "or update the agent's knowledge source to point at "
                        "an existing connection."
                    ),
                    doc_link=f"{DOC_BASE}/externalconnectors-externalconnection-get",
                ))
                continue
            if isinstance(fetched, dict) and fetched.get("_status") in (401, 403):
                warned.append(display)
                results.append(CheckResult(
                    checkpoint_id=cid,
                    category="Graph Connector KB",
                    priority=Priority.HIGH.value,
                    status=Status.WARNING.value,
                    description=f"Graph Connector: {display}",
                    result=(
                        "Insufficient Microsoft Graph permissions to read "
                        f"external connection '{ref}'."
                    ),
                    remediation=(
                        "Grant the signed-in account the "
                        "ExternalConnection.Read.All delegated permission and "
                        "re-run FlightCheck."
                    ),
                ))
                continue
            connection = fetched

        # We have a connection object — validate its state + last op.
        state = (connection.get("state") or "").strip().lower()
        connection_id = connection.get("id") or ref
        connection_name = connection.get("name") or display

        if state in _NON_READY_STATES:
            failed.append(display)
            results.append(CheckResult(
                checkpoint_id=cid,
                category="Graph Connector KB",
                priority=Priority.HIGH.value,
                status=Status.FAILED.value,
                description=f"Graph Connector: {connection_name}",
                result=(
                    f"Connection '{connection_id}' state is '{state}' — "
                    "ESS KB queries against this connector will fail silently."
                ),
                remediation=_state_remediation(state),
                doc_link=f"{DOC_BASE}/resources/externalconnectors-externalconnection",
            ))
            continue
        if state and state != "ready":
            # Unknown state — WARNING so we learn about new states.
            warned.append(display)
            results.append(CheckResult(
                checkpoint_id=cid,
                category="Graph Connector KB",
                priority=Priority.HIGH.value,
                status=Status.WARNING.value,
                description=f"Graph Connector: {connection_name}",
                result=f"Connection '{connection_id}' has unrecognized state '{state}'.",
                remediation=(
                    "Verify the connector in M365 Admin Center → Search & "
                    "Intelligence → Data Sources. File an issue against "
                    "FlightCheck so this state can be added to the readiness "
                    "allowlist."
                ),
            ))
            continue

        # state == "ready" (or omitted on a custom connector). Check the
        # most recent crawl operation.
        op_status = _latest_operation_status(graph, connection_id)
        if op_status == "completed":
            passed.append(display)
            results.append(CheckResult(
                checkpoint_id=cid,
                category="Graph Connector KB",
                priority=Priority.HIGH.value,
                status=Status.PASSED.value,
                description=f"Graph Connector: {connection_name}",
                result=(
                    f"Connection '{connection_id}' is ready and the most recent "
                    "crawl operation completed successfully."
                ),
            ))
        elif op_status == "failed":
            failed.append(display)
            results.append(CheckResult(
                checkpoint_id=cid,
                category="Graph Connector KB",
                priority=Priority.HIGH.value,
                status=Status.FAILED.value,
                description=f"Graph Connector: {connection_name}",
                result=(
                    f"Connection '{connection_id}' is ready, but the most "
                    "recent crawl operation FAILED. KB queries may return "
                    "stale or incomplete results."
                ),
                remediation=(
                    "Inspect the connector's crawl errors in M365 Admin "
                    "Center → Search & Intelligence → Data Sources, fix the "
                    "underlying issue (auth, ACL, source connectivity), and "
                    "trigger a re-crawl before deploying the agent."
                ),
                doc_link=(
                    f"{DOC_BASE}/externalconnectors-externalconnection-list-operations"
                ),
            ))
        elif op_status == "inprogress":
            warned.append(display)
            results.append(CheckResult(
                checkpoint_id=cid,
                category="Graph Connector KB",
                priority=Priority.HIGH.value,
                status=Status.WARNING.value,
                description=f"Graph Connector: {connection_name}",
                result=(
                    f"Connection '{connection_id}' is ready, but a crawl "
                    "operation is currently in progress — items may not yet "
                    "be searchable."
                ),
                remediation=(
                    "Wait for the in-progress crawl to complete before "
                    "deploying. Initial crawls of large content sources can "
                    "take hours."
                ),
            ))
        else:
            # No operations recorded, or status is unspecified/unknown.
            warned.append(display)
            results.append(CheckResult(
                checkpoint_id=cid,
                category="Graph Connector KB",
                priority=Priority.HIGH.value,
                status=Status.WARNING.value,
                description=f"Graph Connector: {connection_name}",
                result=(
                    f"Connection '{connection_id}' is ready, but no completed "
                    "crawl operation could be confirmed (status="
                    f"{op_status or 'none'})."
                ),
                remediation=(
                    "Trigger an initial crawl of the connector in M365 Admin "
                    "Center → Search & Intelligence → Data Sources, and "
                    "verify it completes before deploying."
                ),
            ))

    # ---- EXT-002 (top-level summary) ----
    total = len(gc_sources)
    if failed:
        summary_status = Status.FAILED.value
        result_text = (
            f"{total} Graph Connector knowledge source(s) — "
            f"{len(passed)} ready, {len(warned)} warning, {len(failed)} failed"
        )
        summary_remediation = (
            "Resolve the failed Graph Connector(s) above before deploying. "
            "ESS KB queries against an unhealthy Graph Connector return a "
            "generic 'An unexpected error has occurred' to the user."
        )
    elif warned:
        summary_status = Status.WARNING.value
        result_text = (
            f"{total} Graph Connector knowledge source(s) — "
            f"{len(passed)} ready, {len(warned)} warning"
        )
        summary_remediation = "Review the warnings above before deploying."
    else:
        summary_status = Status.PASSED.value
        result_text = f"{total} Graph Connector knowledge source(s) ready"
        summary_remediation = ""

    results.insert(0, CheckResult(
        checkpoint_id="EXT-002",
        category="Graph Connector KB",
        priority=Priority.HIGH.value,
        status=summary_status,
        description="Graph Connector knowledge source readiness",
        result=result_text,
        remediation=summary_remediation,
        doc_link=ESS_KNOWN_ISSUES_DOC,
    ))

    # ---- Manual-only audience checks ----
    # ACL inspection and tenant-wide audience restriction are not
    # automatable via the public Microsoft Graph today. Surface as
    # NOT_CONFIGURED with concrete pointers so the operator knows what
    # to verify in the portal — silence here would let the most cited
    # silent-failure mode for Graph Connector KBs ship unchecked.
    results.append(CheckResult(
        checkpoint_id="EXT-002-ACL",
        category="Graph Connector KB",
        priority=Priority.HIGH.value,
        status=Status.NOT_CONFIGURED.value,
        description="Graph Connector item ACL audience (manual)",
        result=(
            "Microsoft Graph external connectors expose items as PUT-only — "
            "item ACLs cannot be enumerated programmatically."
        ),
        remediation=(
            "Manually verify in the connector's source system that items have "
            "at least one grant ACL targeting the ESS user audience (group or "
            "everyone), and no deny ACL that would shadow it. Also verify in "
            "M365 Admin Center → Search & Intelligence → Data Sources that "
            "the connector audience is not restricted to a group ESS users "
            "are not in."
        ),
    ))

    return results


# ────────────────────────────────────────────────────────────────────────
# Internals
# ────────────────────────────────────────────────────────────────────────


def _filter_graph_connector_sources(knowledge_sources: list) -> list[dict]:
    """Return KnowledgeSourceComponent entries whose source is a Graph Connector."""
    out: list[dict] = []
    for src in knowledge_sources or []:
        config = src.get("configuration", {}) if isinstance(src, dict) else {}
        source = config.get("source", {}) if isinstance(config, dict) else {}
        if source.get("$kind") == "GraphConnectorSearchSource":
            out.append(src)
    return out


def _connector_reference(knowledge_source: dict) -> str:
    """Pull the connector reference from a KnowledgeSourceComponent.

    The Island Gateway returns ``configuration.source`` for a Graph
    Connector knowledge source as e.g.::

        {
          "$kind": "GraphConnectorSearchSource",
          "connectionId": {"$kind": "EnvironmentVariableReference", ...},
          "connectionName": "ServiceNowKB48",
          ...
        }

    ``connectionId`` is an environment-variable reference whose value is
    only resolvable by a Dataverse round-trip; ``connectionName`` is the
    customer-facing identifier customers typed when they attached the
    connector. We prefer ``connectionName`` because it matches one of
    the two ``externalConnection`` identity fields (``id`` or ``name``)
    we look up via Microsoft Graph. If neither is present, return "".
    """
    config = knowledge_source.get("configuration", {})
    source = config.get("source", {})
    name = source.get("connectionName")
    if isinstance(name, str) and name.strip():
        return name.strip()
    # Fall back to the env-var reference's own schemaName so the operator
    # at least sees which env var to inspect.
    cid = source.get("connectionId")
    if isinstance(cid, dict):
        schema = cid.get("schemaName")
        if isinstance(schema, str) and schema.strip():
            return schema.strip()
    if isinstance(cid, str) and cid.strip():
        return cid.strip()
    return ""


def _latest_operation_status(graph, connection_id: str) -> str:
    """Return the status of the most recently created crawl operation.

    Returns one of ``"completed"``, ``"failed"``, ``"inprogress"``,
    ``"unspecified"``, ``""`` (no ops). Operations are sorted by id;
    Microsoft Graph mints monotonic operation ids (per the public
    ``connectionOperation`` schema), so the lexicographically last id
    is the most recent. If sorting yields no winner, fall back to the
    last entry returned.
    """
    try:
        ops = graph.get_connection_operations(connection_id)
    except Exception:
        return ""
    if not ops:
        return ""
    try:
        latest = sorted(ops, key=lambda op: op.get("id") or "")[-1]
    except Exception:
        latest = ops[-1]
    return (latest.get("status") or "").strip().lower()


def _state_remediation(state: str) -> str:
    """Per-state operator guidance for non-ready connectors."""
    if state == "draft":
        return (
            "Connector is in 'draft' state — finish provisioning it in M365 "
            "Admin Center → Search & Intelligence → Data Sources (publish "
            "schema, configure connection, run initial crawl) before deploying."
        )
    if state == "obsolete":
        return (
            "Connector is in 'obsolete' state — recreate it (the connector "
            "schema or owning app changed in a way that retired the "
            "connection) and re-attach the knowledge source."
        )
    if state == "limitexceeded":
        return (
            "Connector hit its tenant-level item or storage limit — request a "
            "limit increase from Microsoft or remove items, then trigger a "
            "re-crawl."
        )
    return (
        f"Connector is not in 'ready' state ({state}); investigate in M365 "
        "Admin Center → Search & Intelligence → Data Sources."
    )
