# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ServiceNow Deep Validation (SN-CONN-xxx, SN-FLOW-xxx, SN-CFG-xxx, SN-LOCAL-xxx)

Validates ServiceNow connection references, flow status, template configurations
in Dataverse, and local agent topic files for ServiceNow HRSD/ITSM scenarios.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

from ..runner import CheckResult, Priority, Role, Status
from .. import live_egress_probe
from .connections import (
    check_connector_connections,
    get_operator_upn,
    select_operator_owned_connection,
)
from .external_systems import _categorize_servicenow_flows
from .infrastructure import (
    _infra_003_directive,
    _infra_003_probe_layer_note,
    _live_probe_context,
)

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"

# Expected ServiceNow template config scenario names (from HRSD + ITSM extension packs)
EXPECTED_TEMPLATE_CONFIGS = {
    "hrsd": [
        "ServiceNowHRSDCreateCase",
        "ServiceNowHRSDGetCaseDetails",
        "ServiceNowHRSDGetCasesList",
    ],
    "itsm": [
        "ServiceNowITSMCreateTicket",
        "ServiceNowITSMGetTicketDetails",
        "ServiceNowITSMGetUserTickets",
        "ServiceNowITSMUpdateTicket",
    ],
}

# Expected local topic patterns (schema name substrings)
EXPECTED_TOPICS = {
    "hrsd": [
        {"pattern": "servicenowhrsdcreatecase", "name": "ServiceNow HRSD Create Case"},
        {"pattern": "servicenowhrsdgetcasedetails", "name": "ServiceNow HRSD Get Case Details"},
        {"pattern": "servicenowhrsdgetusercases", "name": "ServiceNow HRSD Get User Cases"},
    ],
    "itsm": [
        {"pattern": "servicenowitsmcreateticket", "name": "ServiceNow ITSM Create Ticket"},
        {"pattern": "servicenowitsmgetticketdetails", "name": "ServiceNow ITSM Get Ticket Details"},
        {"pattern": "servicenowitsmgetusertickets", "name": "ServiceNow ITSM Get User Tickets"},
        {"pattern": "servicenowitsmupdateticket", "name": "ServiceNow ITSM Update Ticket"},
    ],
}


def run_servicenow_checks(runner) -> list[CheckResult]:
    """Execute ServiceNow-specific deep validation.

    Only runs if ServiceNow flows were detected by external_systems checks.
    """
    results: list[CheckResult] = []

    # Skip if no ServiceNow flows detected. Unlike Workday (which also has a
    # package-flavor signal, so an installed-but-no-flows-deployed tenant still
    # runs its deep checks), ServiceNow's ONLY "is it here?" signal is the flow
    # set itself. So this gate is unconditional, and every downstream ServiceNow
    # check — including SN-RUN-001 — is silent when no flows exist (the
    # not-installed state is already reported by SN-001). If ServiceNow ever
    # gains an installed-but-no-flows detector, mirror Workday's conditional
    # gate here and restore the "no flows discovered" SKIPPED branch in
    # _check_servicenow_run_health (it is intentionally absent today because it
    # was unreachable behind this gate).
    sn_flows = getattr(runner, "_servicenow_flows", [])
    if not sn_flows:
        return results

    print("\n  Running ServiceNow deep validation...")

    # --- Connection References ---
    results.extend(_check_connections(runner))

    # --- Flow Status ---
    results.extend(_check_flow_status(runner, sn_flows))

    # --- Run health (runtime failures connection-status can't see) ---
    # SN-RUN-001 dispatches to the active connector probe when
    # --runtime-reachability is opted in, and falls back to the passive
    # run-history read otherwise (or on declined consent / no connection).
    results.extend(_check_servicenow_active_run_health(runner))

    # --- Template Configurations (Dataverse) ---
    results.extend(_check_template_configs(runner))

    # --- Local Topic Files ---
    results.extend(_check_local_topics(runner))

    return _suppress_manual_conn_sec_when_runs_healthy(results)


def _suppress_manual_conn_sec_when_runs_healthy(
    results: list[CheckResult],
) -> list[CheckResult]:
    """Hide MANUAL ServiceNow connection/security checks when the run-health
    litmus test (SN-RUN-001) proves ServiceNow is actually working.

    Any ``SN-CONN-*`` / ``SN-SEC-*`` row emitted with MANUAL status asks the
    operator to hand-verify config in the ServiceNow/Entra tenant (a surface
    the kit has no admin API for). When SN-RUN-001 PASSES, runtime traffic
    already demonstrates that chain works end to end, so those manual asks are
    redundant noise — drop them.

    They are KEPT whenever SN-RUN-001 does NOT pass — i.e. it FAILED (they help
    diagnose the break), or it could not confirm health (NOT_CONFIGURED = no
    traffic yet, SKIPPED = run history unavailable), where hand-verification is
    still the operator's best signal (e.g. a fresh pre-deployment env).

    (ServiceNow ships no MANUAL conn/sec checks today, so this is a no-op until
    one is added; it mirrors the Workday WD-RUN-001 behaviour 1:1 so a future
    MANUAL SN-CONN/SN-SEC check inherits the suppression automatically.)
    """
    run_health = next(
        (r.status for r in results if r.checkpoint_id == "SN-RUN-001"), None
    )
    if run_health != Status.PASSED.value:
        return results
    return [
        r for r in results
        if not (
            r.status == Status.MANUAL.value
            and (r.checkpoint_id.startswith("SN-CONN") or r.checkpoint_id.startswith("SN-SEC"))
        )
    ]


def _check_connections(runner) -> list[CheckResult]:
    """Validate ServiceNow connection references in Power Platform."""
    return check_connector_connections(
        runner,
        connector_keyword=["service-now", "servicenow"],
        checkpoint_prefix="SN-CONN",
        category="ServiceNow",
        not_found_remediation="Configure ServiceNow connections in the environment. Run /connect servicenow.",
        doc_link=f"{DOC_BASE}/servicenow",
        connection_pin=getattr(runner, "servicenow_connection_pin", "") or "",
    )


def _check_flow_status(runner, sn_flows: list) -> list[CheckResult]:
    """Check whether ServiceNow flows are enabled, grouped by HRSD/ITSM."""
    results = []

    # Reuse categorization from external_systems.py
    hrsd, itsm, other = _categorize_servicenow_flows(sn_flows)

    enabled = 0
    disabled = 0
    for i, f in enumerate(sn_flows):
        props = f.get("properties", {})
        name = props.get("displayName", f.get("displayName", f"Flow {i + 1}"))
        state = props.get("state", "")
        is_on = state.lower() in ("started", "on", "enabled")
        cid = f"SN-FLOW-{i + 1:03d}"

        if is_on:
            enabled += 1
        else:
            disabled += 1

        # Determine pack label
        pack_label = "Other"
        if f in hrsd:
            pack_label = "HRSD"
        elif f in itsm:
            pack_label = "ITSM"

        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id=cid, category="ServiceNow",
            priority=Priority.HIGH.value,
            status=Status.PASSED.value if is_on else Status.FAILED.value,
            description=f"Flow [{pack_label}]: {name}",
            result=f"State: {'Enabled' if is_on else 'Disabled'}",
            remediation=f"Enable '{name}' in Power Automate." if not is_on else "",
            doc_link=f"{DOC_BASE}/servicenow",
        ))

    # Summary
    if sn_flows:
        hrsd_detail = f"{len(hrsd)} HRSD" if hrsd else ""
        itsm_detail = f"{len(itsm)} ITSM" if itsm else ""
        other_detail = f"{len(other)} other" if other else ""
        breakdown = ", ".join(filter(None, [hrsd_detail, itsm_detail, other_detail]))

        results.insert(0, CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="SN-FLOW-000", category="ServiceNow",
            priority=Priority.HIGH.value,
            status=Status.PASSED.value if disabled == 0 else Status.WARNING.value,
            description="ServiceNow flow status summary",
            result=f"{len(sn_flows)} flows ({breakdown}) — {enabled} enabled, {disabled} disabled",
            remediation=f"{disabled} flow(s) disabled — enable them in Power Automate." if disabled else "",
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────
# SN-RUN-001 — ServiceNow shared-flow run health (run-history analysis)
# ─────────────────────────────────────────────────────────────────────────
#
# Complements the connection-status checks (SN-CONN-001+): those confirm the
# Power Platform connection is *Connected*, but a connection can be Connected
# while ServiceNow calls still FAIL at runtime — e.g. a revoked ServiceNow
# role/ACL for the signed-in user, a broken template config, or a ServiceNow-
# side outage. Connection status cannot see any of that; the only evidence is
# in the shared flow's *run history*.
#
# Detection model — CONFIRMED live 2026-06 against 3 environments with real
# ServiceNow run history (ESS_MODEL_UPGRADE_PREVIEW_FRE_2, test_CA, and
# "SunbreakDev - Release Testing - Workday+Snow"), captured via
# tests/captures/record_flightcheck_servicenow_runs.py. The user-facing
# orchestrator flow responds to Copilot Studio with exactly two actions:
#   * SUCCESS  -> status=Succeeded, response.name="Respond_to_Copilot"
#   * FAILURE  -> status=Failed,    response.name="Respond_to_Copilot_-_Failure"
# (NOTE this differs from Workday: Workday catches faults and reports
# status=Succeeded with a non-success Response branch, whereas ServiceNow's
# orchestrator failure surfaces as status=Failed. We still keep the
# "Succeeded but non-success Copilot response = caught_failure" branch for
# safety, but in practice ServiceNow failures are caught by the status=Failed
# path.)
#
# ServiceNow topology vs. Workday (same capture): unlike Workday's SINGLE
# shared flow, ServiceNow ships a MULTI-FLOW orchestration — per pack an entry
# "Common Orchestrator" plus child/utility flows ("Common Get/Create/Update/List
# Record", "Request Body Generator", "Live Agent Save Summary", ...). Only the
# orchestrator responds to Copilot; the child flows respond to their PARENT with
# NON-Copilot actions observed in the capture
# ("Respond_back_to_Orchestrator_-_Success",
# "Respond_to_Common_Orchestrator_-_Success",
# "Respond_to_a_Power_App_or_flow[_-_Success]"). A single user scenario produces
# several flow runs but only ONE user-facing (Copilot-responding) run. We
# therefore SCORE only runs whose response.name starts with
# ``Respond_to_Copilot``; succeeded child/utility runs are non-scoring
# 'pending'. (For Workday every run is the one shared flow and always carries a
# ``Respond_to_Copilot_*`` response, so the equivalent Workday check needs no
# such scoping — the two checks stay correct on their respective topologies.)
#
# So per-run detection:
#   a run FAILED  if  status in {Failed, TimedOut, ...}
#                 OR (status == "Succeeded" AND it responded to Copilot with an
#                     action != "Respond_to_Copilot")
#
# The check's VERDICT, however, is a litmus test for a *deterministic* break,
# not a per-run pass/fail: it looks only at the most recent window of scored
# runs (``_SN_RECENT_WINDOW``, newest first across all ServiceNow flows) and
# FAILs only when NONE of them succeeded. Scattered failures among recent
# successes (e.g. a user requesting a case their ServiceNow ACL doesn't allow)
# do NOT fail readiness — recent successes prove the integration is wired up. A
# single run that failed (no successes in the window) IS a failure.
#
# Known limitations (documented, not silently swallowed):
#   * A fully-broken/unconfigured connection makes Copilot Studio prompt
#     "connect to continue" and never invokes the flow, so NO run is created.
#     That case is covered by SN-CONN-001+ (connection status), NOT here.
#   * Agent-side timeouts (``flowActionTimedOut``) leave the run "Succeeded"
#     and are not detectable from run history.

# The single success Response action of the ServiceNow orchestrator (CONFIRMED
# live 2026-06). Any OTHER Copilot response action (e.g.
# "Respond_to_Copilot_-_Failure") is a failure branch.
_SN_SUCCESS_RESPONSE_ACTION = "Respond_to_Copilot"

# Prefix identifying a run that responded to Copilot Studio (the user-facing
# orchestrator run). Child/utility flow runs respond to their parent with
# non-Copilot actions (Respond_back_to_Orchestrator_*, Respond_to_a_Power_App_
# or_flow_*) and are non-scoring. CONFIRMED live 2026-06.
_SN_COPILOT_RESPONSE_PREFIX = "Respond_to_Copilot"

# Terminal run statuses that are definite failures of the run itself. A run in
# any of these did not complete successfully, regardless of response branch.
# (Cancelled / Skipped and unknown states are intentionally NOT here — they are
# inconclusive and treated as non-scoring 'pending' in _classify_run.)
_RUN_FAILURE_STATUSES = {"Failed", "TimedOut", "Faulted", "Aborted"}

# SN-RUN-001 evaluates only the most recent N terminal runs (newest first,
# across all ServiceNow flows). The check is a litmus test for a *deterministic*
# break: it FAILs only when NONE of the recent runs succeeded. A couple of
# scattered failures among recent successes is expected (e.g. a user asks for a
# case their ServiceNow ACL doesn't permit) and must NOT fail readiness — the
# presence of recent successes proves the integration is wired up.
_SN_RECENT_WINDOW = 10


def _classify_run(run: dict) -> str:
    """Classify one flow run as 'success', 'caught_failure', 'hard_failure',
    or 'pending' (non-scoring).

    Definite run-level failures (``"Failed"``/``"TimedOut"``/``"Faulted"``/
    ``"Aborted"``) are hard_failure. A ``"Succeeded"`` run is scored ONLY when it
    actually responded to Copilot Studio (``response.name`` starts with
    ``Respond_to_Copilot``) — that is the user-facing orchestrator run whose
    Response-action name distinguishes the success branch from a caught
    ServiceNow fault. ServiceNow's child/utility flow runs respond to their
    parent, not to Copilot, so a succeeded child run is non-scoring 'pending'
    (see the SN-RUN-001 module comment on the multi-flow topology). Everything
    else is 'pending' too: in-flight states (``"Running"``/``"Waiting"``/
    ``"Paused"``/``"Suspended"``) AND inconclusive terminal states that are not
    a ServiceNow-health signal (``"Cancelled"``/``"Skipped"``/unknown).
    Critically, a non-``"Succeeded"`` run is NEVER counted as a success — an
    all-``"Cancelled"`` window must not yield a misleading PASS (which would
    hide the manual conn/sec checks).
    """
    props = run.get("properties", {}) or {}
    status = props.get("status")
    resp_name = ((props.get("response") or {}).get("name")) or ""
    if status in _RUN_FAILURE_STATUSES:
        return "hard_failure"
    if status == "Succeeded":
        # Only orchestrator (Copilot-responding) runs are user-facing and
        # scoreable; child/utility flow runs are non-scoring.
        if not resp_name.startswith(_SN_COPILOT_RESPONSE_PREFIX):
            return "pending"
        if resp_name != _SN_SUCCESS_RESPONSE_ACTION:
            return "caught_failure"
        return "success"
    return "pending"


def _check_servicenow_run_health(runner) -> list[CheckResult]:
    """SN-RUN-001 — litmus test for a *deterministic* ServiceNow runtime break.

    Reads run history for each discovered ServiceNow flow via
    ``runner.pp_admin.get_flow_runs``, looks at the most recent window of runs
    (``_SN_RECENT_WINDOW``, newest first across all flows), and FAILs only when
    NONE of them succeeded. Recent successes prove the integration is wired up,
    so scattered failures alongside them do not fail readiness. Catches runtime
    ServiceNow failures that connection status (SN-CONN-001+) cannot see.
    """
    roles = [Role.SERVICENOW_ADMIN.value, Role.ESS_MAKER.value]
    pp = runner.pp_admin
    env_id = runner.env_id
    sn_flows = getattr(runner, "_servicenow_flows", [])

    if pp is None or not env_id:
        return [CheckResult(
            checkpoint_id="SN-RUN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ServiceNow flow run health",
            result="Power Platform Admin API not available — cannot read flow run history.",
            remediation="Re-run /flightcheck with Power Platform Admin access to evaluate ServiceNow run health.",
            roles=[Role.POWER_PLATFORM_ADMIN.value],
        )]

    # NOTE: no "not sn_flows" SKIPPED branch here on purpose. The only
    # production caller (run_servicenow_checks) returns early when sn_flows is
    # empty, so this function is never reached without flows. See the gate
    # comment in run_servicenow_checks for the ServiceNow-vs-Workday rationale.

    terminal: list[dict] = []
    api_error: str | None = None

    for f in sn_flows:
        flow_id = f.get("name")
        fname = f.get("properties", {}).get("displayName", f.get("displayName", flow_id))
        if not flow_id:
            continue
        runs = pp.get_flow_runs(env_id, flow_id)
        if isinstance(runs, dict) and "_error" in runs:
            api_error = runs["_error"]
            continue
        for run in runs:
            kind = _classify_run(run)
            if kind == "pending":
                continue
            props = run.get("properties", {}) or {}
            terminal.append({
                "start": props.get("startTime") or "",
                "kind": kind,
                "flow": fname,
                "run": run.get("name"),
                "resp": ((props.get("response") or {}).get("name")) or "?",
            })

    if not terminal:
        if api_error:
            return [CheckResult(
                checkpoint_id="SN-RUN-001", category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.SKIPPED.value,
                description="ServiceNow flow run health",
                result=f"Unable to read ServiceNow flow run history: {api_error}.",
                remediation="Run history requires owner/maker access to the ServiceNow flows. "
                            "Re-run as a user who owns the flows, or check it manually in "
                            "Power Automate (make.powerautomate.com).",
                roles=[Role.POWER_PLATFORM_ADMIN.value],
            )]
        return [CheckResult(
            checkpoint_id="SN-RUN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="ServiceNow flow run health",
            result="No recent ServiceNow flow runs found — no runtime traffic to evaluate.",
            remediation="Exercise a ServiceNow scenario in the agent Test pane, then re-run /flightcheck. "
                        "Note: a fully-broken connection produces NO runs (the flow is never invoked) — "
                        "if ServiceNow isn't responding, check connection status first (SN-CONN-001).",
            doc_link=f"{DOC_BASE}/servicenow",
            roles=roles,
        )]

    # Evaluate only the most recent window (newest first). A deterministic
    # break = NO success among the recent runs. Scattered failures alongside
    # recent successes do NOT fail readiness.
    terminal.sort(key=lambda r: r["start"], reverse=True)
    window = terminal[:_SN_RECENT_WINDOW]
    n = len(window)
    win_fail = [r for r in window if r["kind"] in ("caught_failure", "hard_failure")]
    win_success = n - len(win_fail)

    def _sample_lines(rows: list[dict]) -> str:
        lines = []
        for r in rows[:5]:
            if r["kind"] == "hard_failure":
                lines.append(f"'{r['flow']}' run {r['run']}: flow run Failed")
            else:
                lines.append(f"'{r['flow']}' run {r['run']}: ServiceNow call failed ({r['resp']})")
        return "\n".join(lines)

    if win_success > 0:
        # At least one recent success → the integration is working. Not a
        # readiness blocker even if some recent runs failed.
        if win_fail:
            result = (
                f"{win_success} of the {n} most recent ServiceNow flow run(s) succeeded — the "
                f"integration is working. {len(win_fail)} recent run(s) failed, likely "
                f"scenario- or permission-specific rather than a broken connection."
            )
        else:
            result = f"All {n} most recent ServiceNow flow run(s) succeeded."
        return [CheckResult(
            checkpoint_id="SN-RUN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="ServiceNow flow run health",
            result=result,
            remediation="",
            doc_link=f"{DOC_BASE}/servicenow",
            roles=roles,
        )]

    # No recent success → deterministically broken.
    return [CheckResult(
        checkpoint_id="SN-RUN-001", category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.FAILED.value,
        description="ServiceNow flow run health",
        result=(
            f"All {n} most recent ServiceNow flow run(s) FAILED — the ServiceNow integration "
            f"appears deterministically broken. Note: run status alone shows 'Succeeded' "
            f"for caught ServiceNow failures, so this is based on the flow's response branch.\n"
            f"{_sample_lines(win_fail)}"
        ),
        remediation=(
            "Every recent ServiceNow call is failing — users cannot use ServiceNow scenarios. "
            "Open the failed run(s) in Power Automate (make.powerautomate.com) to read the "
            "ServiceNow error. Common causes: a revoked ServiceNow role/ACL, a misconfigured "
            "template config, an expired OAuth token, or a ServiceNow-side outage. If the "
            "connection itself shows Error, fix that first (see SN-CONN-001)."
        ),
        doc_link=f"{DOC_BASE}/servicenow",
        roles=roles,
    )]


# ─────────────────────────────────────────────────────────────────────────
# SN-RUN-001 (active) — on-demand ServiceNow managed-connector probe
# ─────────────────────────────────────────────────────────────────────────
#
# The passive run-history read above answers nothing when no ServiceNow run
# happened recently, and even with data it only exposes the flow's run status
# and Response-action name — never the real ServiceNow faultstring (that sits
# behind a SAS-signed outputsLink FlightCheck deliberately never fetches). The
# active probe closes that gap: it stands up one throwaway Power Automate flow
# bound to the maker's own managed ServiceNow connection, runs ONE read-only
# ServiceNow operation through the real managed connector (the AzureConnectors
# egress path the agent actually uses — NOT the native-HTTP / LogicApps path
# the INFRA-003 probe travels), reads the synchronous result, then deletes the
# flow. It reuses the INFRA-003 transient-flow lifecycle (create / activate /
# listCallbackUrl / invoke / delete, consent gating, deterministic naming, and
# orphan sweep) from live_egress_probe. This mirrors the Workday WD-RUN-001
# active probe 1:1; only the ServiceNow connector binding and error map differ.
#
# On declined consent, an infeasible test, or an OAuth-invoker-only install,
# it falls back to the passive run-history read above. A no-connection /
# pre-deployment state is a clean NOT-CONFIGURED, never FAIL.

_SN_CONNECTOR_API_ID = "/providers/Microsoft.PowerApps/apis/shared_service-now"
_SN_CONNECTOR_NAME = "shared_service-now"
_SN_PROBE_FLOW_NAME = "flightcheck-sn-run-001-probe"
_SN_PROBE_ACTION_NAME = "Probe_ServiceNow"

# SN-RUN-001 AC13 (live-verified 2026-08-11, PROD): "GetRecords" (List
# Records) with parameters {tableType: sys_user, sysparm_limit: 1} returned
# HTTP 200 from a real ServiceNow instance through the managed connector. It
# is the confirmed read-only default. The read-only allowlist below is the
# safety gate that keeps an operator override (env / config) from selecting a
# mutating operation. sys_user is a core table present in every ServiceNow
# instance; sysparm_limit=1 keeps the read to a single record, and the record
# body is never surfaced in the probe Response.
_SN_DEFAULT_READ_OPERATION = "GetRecords"
_SN_DEFAULT_READ_PARAMS: dict[str, Any] = {"tableType": "sys_user", "sysparm_limit": "1"}
_SN_READ_OPERATION_PREFIXES = ("get", "list", "read")
_SN_MUTATING_OPERATION_PREFIXES = (
    "add", "create", "delete", "edit", "insert", "modify", "patch",
    "post", "put", "remove", "set", "submit", "update", "write",
)


def _servicenow_runtime_source(conn: dict) -> str:
    props = conn.get("properties", {}) if isinstance(conn, dict) else {}
    candidates = [
        props.get("runtimeSource"),
        props.get("runtime_source"),
        (props.get("connectionRuntime") or {}).get("runtimeSource")
        if isinstance(props.get("connectionRuntime"), dict)
        else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    return ""


def _is_servicenow_connection(conn: dict) -> bool:
    props = conn.get("properties", {}) if isinstance(conn, dict) else {}
    api_id = props.get("apiId") or (props.get("api") or {}).get("name", "")
    text = str(api_id).lower()
    return "service-now" in text or "servicenow" in text


def _select_servicenow_probe_connection(runner) -> tuple[dict | None, str]:
    """Pick the ServiceNow managed connection the active probe binds to.

    Delegates the vendor-agnostic selection (Connected + service-account +
    operator-owned, with a passive-fallback reason otherwise) to the shared
    ``select_operator_owned_connection`` helper, passing only the
    ServiceNow-specific connection filter and runtime-source reader. The
    ownership preference is what lets the transient flow activate; a connection
    owned by another maker returns ConnectionAuthorizationFailed at activate
    (confirmed live, PROD 2026-08-11).
    """
    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    if pp is None or not env_id:
        return None, "missing Power Platform admin client or environment id"
    try:
        conns = pp.get_connections(env_id)
    except Exception as exc:  # noqa: BLE001 - fallback path must not fail the check
        return None, f"could not list Power Platform connections ({type(exc).__name__})"
    if not isinstance(conns, list):
        return None, "Power Platform connection list was unavailable"

    return select_operator_owned_connection(
        connections=conns,
        is_target=_is_servicenow_connection,
        runtime_source=_servicenow_runtime_source,
        operator_upn=get_operator_upn(runner),
        vendor_label="ServiceNow",
        identity_path_label="integration-user / service-account path",
    )


def _servicenow_probe_config(runner) -> tuple[str | None, dict[str, Any], str | None]:
    """Resolve the read-only operation id and parameters for the probe.

    Order of precedence: ESS_SN_PROBE_OPERATION_ID env var, then the
    ``serviceNowConnectorProbe`` config block, then the read-only default.
    Rejects any operation outside the read-only allowlist so an override can
    never trigger a mutating ServiceNow call (AC7).
    """
    config = getattr(runner, "config", {}) or {}
    probe_cfg: dict[str, Any] = {}
    if isinstance(config.get("serviceNowConnectorProbe"), dict):
        probe_cfg = config["serviceNowConnectorProbe"]
    elif isinstance(config.get("flightcheck"), dict) and isinstance(
        config["flightcheck"].get("serviceNowConnectorProbe"), dict
    ):
        probe_cfg = config["flightcheck"]["serviceNowConnectorProbe"]

    operation_id = (
        os.environ.get("ESS_SN_PROBE_OPERATION_ID", "").strip()
        or str(probe_cfg.get("operationId") or _SN_DEFAULT_READ_OPERATION).strip()
    )
    params: dict[str, Any] = {}
    raw_params = os.environ.get("ESS_SN_PROBE_PARAMS_JSON", "").strip()
    if raw_params:
        try:
            parsed = json.loads(raw_params)
        except json.JSONDecodeError:
            return None, {}, "ESS_SN_PROBE_PARAMS_JSON is not valid JSON"
        if not isinstance(parsed, dict):
            return None, {}, "ESS_SN_PROBE_PARAMS_JSON must be a JSON object"
        params = parsed
    elif isinstance(probe_cfg.get("parameters"), dict):
        params = dict(probe_cfg["parameters"])
    elif operation_id == _SN_DEFAULT_READ_OPERATION:
        # No override supplied: use the live-verified default parameters so the
        # default GetRecords call carries the tableType the connector requires.
        # Live-verified (PROD 2026-08-12): GetRecords with empty parameters
        # fails at flow ACTIVATE (the required connector parameter is missing
        # from the flow definition), before any ServiceNow call — so supplying
        # these defaults is what lets the default probe reach the connector.
        params = dict(_SN_DEFAULT_READ_PARAMS)

    op_lower = operation_id.lower()
    if op_lower.startswith(_SN_MUTATING_OPERATION_PREFIXES):
        return None, {}, f"operation '{operation_id}' is not read-only"
    if not op_lower.startswith(_SN_READ_OPERATION_PREFIXES):
        return None, {}, (
            f"operation '{operation_id}' is not in the read-only allowlist"
        )
    return operation_id, params, None


def _with_sn_run_passive_context(
    results: list[CheckResult], *, reason: str
) -> list[CheckResult]:
    suffix = (
        "\n\nThe live ServiceNow connection test was not run "
        f"({reason}). Readiness was instead assessed from recent ServiceNow "
        "connector run history on this environment. No new ServiceNow call was "
        "made."
    )
    for row in results:
        if row.checkpoint_id == "SN-RUN-001" and suffix not in row.result:
            row.result += suffix
    return results


def _servicenow_probe_not_configured(reason: str) -> list[CheckResult]:
    return [CheckResult(
        checkpoint_id="SN-RUN-001", category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
        description="ServiceNow active connector runtime health",
        result=(
            f"The live ServiceNow connection test did not run: {reason}."
        ),
        remediation=(
            "Connect ServiceNow in Power Platform first, then re-run "
            "/flightcheck with --runtime-reachability to test the live "
            "ServiceNow connection. This is a clean pre-deployment state, "
            "not a runtime failure."
        ),
        doc_link=f"{DOC_BASE}/servicenow",
        roles=[Role.SERVICENOW_ADMIN.value, Role.POWER_PLATFORM_ADMIN.value],
    )]


def _servicenow_probe_layer(res: live_egress_probe.ConnectorProbeResult) -> tuple[str, str]:
    # Classification keys off the two signals the connector's synchronous
    # response exposes: HTTP status (@outputs statusCode) and the action code
    # (@actions code). The human-readable error.message is NOT available
    # synchronously (it lives behind the SAS-signed outputsLink FlightCheck
    # never fetches; live capture confirmed connectorErrorMessage=null on a
    # 200, a 400, and a 404), so a wrong endpoint/table/operation and a
    # ServiceNow business/validation fault can BOTH surface as HTTP 400 /
    # BadRequest and cannot be split here — they share one honest
    # "indeterminate" bucket.
    #
    # Live-verified (PROD, deeper fault-capture pass 2026-08-12,
    # tests/fixtures/cassettes/flightcheck_sn_connector_probe_faults.yaml):
    #   * GetRecords on a valid table (sys_user)        -> 200 / OK
    #   * GetRecords on an invalid table                -> 400 / BadRequest
    #   * GetRecords on a restricted table (sys_user_password)
    #                                                   -> 400 / BadRequest
    #     (NOT 403: ServiceNow table/row ACL denial collapses into 400 here,
    #     so the 401/403 branch below is a connector-AUTH assumption, not how
    #     ACL denial actually surfaces)
    #   * GetRecord with a non-existent sys_id          -> 404 / NotFound
    #     (404 IS reachable and distinct — the connector does not collapse
    #     everything into 400)
    #   * GetRecords with empty required params fails at flow ACTIVATE, before
    #     the connector runs (status None, stage=activate), not as a 400.
    # The status-None sub-splits (TLS / DNS / DLP), 401 / 403, 429, and 500
    # branches remain documented assumptions, not yet separately captured
    # (they cannot be induced non-destructively against a healthy tenant).
    code = (res.error_code or "").lower()
    status = res.status_code
    if status is None:
        if "tls" in code or "cert" in code or "ssl" in code:
            return "network layer (TLS certificate)", "the connector got no HTTP response because TLS failed"
        if "dns" in code or "name" in code:
            return "network layer (DNS)", "the connector got no HTTP response because name resolution failed"
        if "dlp" in code or "firewall" in code or "blocked" in code:
            return "network layer (firewall / DLP)", "the connector got no HTTP response because traffic was blocked"
        return "network layer (DNS / TLS / firewall / DLP)", "the connector got no HTTP response"
    if status in (401, 403) or any(t in code for t in ("unauthor", "forbidden")):
        return (
            "authorization layer",
            "ServiceNow or the connector rejected the request; the integration "
            "user's ServiceNow role/ACL likely does not permit this operation",
        )
    if status in (404, 405) or any(t in code for t in ("notfound", "invalidurl", "endpoint")):
        # Live-verified 404 / NotFound (PROD 2026-08-12). HTTP 404 alone cannot
        # distinguish a not-found record from a not-found table, operation, or
        # instance URL, so the cause names all of them honestly.
        return (
            "endpoint configuration layer",
            "a ServiceNow record, table, operation, or the configured instance "
            "URL was not found (HTTP 404)",
        )
    if status == 429 or any(t in code for t in ("toomanyrequests", "ratelimit", "throttl")):
        return "ServiceNow rate-limit layer", "ServiceNow throttled the request (HTTP 429)"
    if status == 400 or "badrequest" in code:
        return (
            "endpoint-configuration or ServiceNow business-rule layer (indeterminate)",
            "ServiceNow rejected the request with HTTP 400; the connector's "
            "synchronous response cannot distinguish a wrong endpoint / table / "
            "operation from a ServiceNow business or validation fault",
        )
    if status in (409, 422):
        return "ServiceNow business-rule layer", "ServiceNow processed the request and rejected its inputs"
    if status == 500 or "internalservererror" in code or "servererror" in code:
        return "connector runtime / ServiceNow backend layer", "the ServiceNow connector or backend returned a server error"
    return "connector runtime layer", "the ServiceNow connector action failed"


def _servicenow_probe_failure_result(
    res: live_egress_probe.ConnectorProbeResult, connection_name: str
) -> list[CheckResult]:
    _layer, cause = _servicenow_probe_layer(res)
    status_text = f"HTTP {res.status_code}" if res.status_code else "no HTTP status"
    code_text = f"; connector code {res.error_code}" if res.error_code else ""
    return [CheckResult(
        checkpoint_id="SN-RUN-001", category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.FAILED.value,
        description="ServiceNow active connector runtime health",
        result=(
            "The live ServiceNow connection test failed. "
            f"{cause[:1].upper() + cause[1:]} ({status_text}{code_text}). "
            "Tested using the ServiceNow service-account connection "
            f"'{connection_name}'. This tested the standard ServiceNow REST "
            "data-retrieval path; it did not test custom scripted REST APIs."
        ),
        remediation=_infra_003_directive(
            cause=cause,
            scope="ServiceNow managed connector / Power Platform environment egress",
            implies=(
                "The agent's ServiceNow REST connector path can fail at "
                "runtime even if connection status is Connected."
            ),
            next_steps=(
                "Open the transient probe or matching ServiceNow connector run "
                "in Power Automate, then fix the cause named above. For "
                "authorization, check the integration user's ServiceNow "
                "roles/ACLs. For endpoint configuration, check the ServiceNow "
                "instance URL and the table/operation. For network blocks, "
                "check DLP, firewall, DNS, and TLS."
            ),
            responsible_role=(
                f"{Role.SERVICENOW_ADMIN.value} / {Role.POWER_PLATFORM_ADMIN.value}"
            ),
            probe_layer_note=_infra_003_probe_layer_note(),
        ),
        doc_link=f"{DOC_BASE}/servicenow",
        roles=[Role.SERVICENOW_ADMIN.value, Role.POWER_PLATFORM_ADMIN.value],
    )]


def _check_servicenow_active_run_health(runner) -> list[CheckResult]:
    """SN-RUN-001 — active ServiceNow connector probe with passive fallback.

    Dispatches to the on-demand managed-connector probe when the operator opts
    into --runtime-reachability and a Connected service-account ServiceNow
    connection exists. On declined consent, missing prerequisites, an
    OAuth-invoker-only install, or a bad operation override, it falls back to
    the passive run-history read (_check_servicenow_run_health). A missing
    ServiceNow connection is reported as a clean NOT_CONFIGURED, never FAIL.
    """
    ctx, live_env = _live_probe_context(runner)
    if not (ctx.live_ran and live_env is not None):
        reason = (
            "operator declined the runtime-reachability probe"
            if ctx.declined_by_user
            else ctx.unavailable_reason or "runtime-reachability was not opted in"
        )
        return _with_sn_run_passive_context(
            _check_servicenow_run_health(runner), reason=reason
        )

    conn, conn_reason = _select_servicenow_probe_connection(runner)
    if conn is None:
        if "no ServiceNow" in conn_reason:
            return _servicenow_probe_not_configured(conn_reason)
        return _with_sn_run_passive_context(
            _check_servicenow_run_health(runner), reason=conn_reason
        )

    operation_id, params, op_error = _servicenow_probe_config(runner)
    if op_error:
        return _with_sn_run_passive_context(
            _check_servicenow_run_health(runner), reason=op_error
        )

    connection_id = conn.get("name") or ""
    action = live_egress_probe.ConnectorProbeAction(
        connector_api_id=_SN_CONNECTOR_API_ID,
        connection_id=connection_id,
        operation_id=operation_id or _SN_DEFAULT_READ_OPERATION,
        parameters=params,
        action_name=_SN_PROBE_ACTION_NAME,
        connection_ref_key=_SN_CONNECTOR_NAME,
    )
    try:
        live_egress_probe.cleanup_orphan_probe_flows(
            live_env["env_url"], live_env["dv_token"], probe_flow_name=_SN_PROBE_FLOW_NAME
        )
        res = live_egress_probe.run_connector_probe(
            **live_env,
            action=action,
            probe_flow_name=_SN_PROBE_FLOW_NAME,
            description="FlightCheck SN-RUN-001 transient ServiceNow connector probe.",
        )
    finally:
        live_egress_probe.cleanup_orphan_probe_flows(
            live_env["env_url"], live_env["dv_token"], probe_flow_name=_SN_PROBE_FLOW_NAME
        )

    if res.succeeded is True:
        return [CheckResult(
            checkpoint_id="SN-RUN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="ServiceNow active connector runtime health",
            result=(
                "The live test successfully retrieved data from ServiceNow "
                "through the agent's ServiceNow connection "
                f"({res.detail}). Tested using the ServiceNow service-account "
                f"connection '{connection_id}'. This tested the standard "
                "ServiceNow REST data-retrieval path; it did not test custom "
                "scripted REST APIs."
            ),
            remediation="",
            doc_link=f"{DOC_BASE}/servicenow",
            roles=[Role.SERVICENOW_ADMIN.value, Role.POWER_PLATFORM_ADMIN.value],
        )]
    if res.succeeded is False:
        return _servicenow_probe_failure_result(res, connection_id)
    return _with_sn_run_passive_context(
        _check_servicenow_run_health(runner),
        reason=f"the live ServiceNow test could not complete (it did not return a clear pass or fail): {res.detail}",
    )


def _check_template_configs(runner) -> list[CheckResult]:
    """Validate ServiceNow template configurations exist in Dataverse."""
    results = []
    env_url = runner.env_url
    dv_token = runner.dv_token

    if not env_url or not dv_token:
        results.append(CheckResult(roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="SN-CFG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ServiceNow template configurations",
            result="Dataverse token not available — skipping template config checks",
        ))
        return results

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        # Query template configs filtering for ServiceNow scenarios
        configs = query_all(
            env_url, dv_token,
            "msdyn_employeeselfservicetemplateconfigs",
            "msdyn_name,msdyn_employeeselfservicetemplateconfigid",
            filter_expr="contains(msdyn_name,'ServiceNow')",
        )

        if configs:
            results.append(CheckResult(roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="SN-CFG-001", category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description="ServiceNow template configurations",
                result=f"Found {len(configs)} ServiceNow template config(s) in Dataverse",
                doc_link=f"{DOC_BASE}/servicenow",
            ))

            # Check for expected HRSD configs
            config_names = [c.get("msdyn_name", "").lower() for c in configs]
            _validate_expected_configs(results, config_names, "hrsd", "SN-CFG-01")
            _validate_expected_configs(results, config_names, "itsm", "SN-CFG-02")
        else:
            results.append(CheckResult(roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="SN-CFG-001", category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
                description="ServiceNow template configurations",
                result="No ServiceNow template configs found in Dataverse",
                remediation=(
                    "Install the ServiceNow extension pack (HRSD/ITSM) in Copilot Studio. "
                    "Template configs are created automatically during installation."
                ),
                doc_link=f"{DOC_BASE}/servicenow",
            ))

    except Exception as e:
        results.append(CheckResult(roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="SN-CFG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ServiceNow template configurations",
            result=f"Unable to query template configs: {e}",
        ))

    return results


def _validate_expected_configs(
    results: list[CheckResult],
    config_names: list[str],
    pack_type: str,
    cid_prefix: str,
) -> None:
    """Check that expected template configs for a given pack type exist."""
    expected = EXPECTED_TEMPLATE_CONFIGS.get(pack_type, [])
    found = []
    missing = []

    for scenario in expected:
        if any(scenario.lower() in name for name in config_names):
            found.append(scenario)
        else:
            missing.append(scenario)

    pack_label = pack_type.upper()
    if not missing:
        results.append(CheckResult(
            checkpoint_id=f"{cid_prefix}0", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.PASSED.value,
            description=f"ServiceNow {pack_label} template configs",
            result=f"All {len(expected)} expected {pack_label} configs present",
            roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
        ))
    elif found:
        results.append(CheckResult(
            checkpoint_id=f"{cid_prefix}0", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.WARNING.value,
            description=f"ServiceNow {pack_label} template configs",
            result=f"{len(found)}/{len(expected)} configs found — missing: {', '.join(missing)}",
            remediation=f"Reinstall the ServiceNow {pack_label} extension pack or create missing configs manually.",
            roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
        ))
    # If none found, the pack likely isn't installed — don't flag as error


def _check_local_topics(runner) -> list[CheckResult]:
    """Validate ServiceNow topics are present in local agent files."""
    results = []

    agents_root = Path("workspace/agents")
    if not agents_root.exists():
        return results

    agent_folders = [d for d in agents_root.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if not agent_folders:
        return results

    for agent_path in sorted(agent_folders):
        agent_name = agent_path.name
        label = agent_name.replace("-", " ").title()
        results.extend(_check_agent_sn_topics(agent_path, label))

    return results


def _check_agent_sn_topics(agent_path: Path, label: str) -> list[CheckResult]:
    """Check a single agent for ServiceNow topic files."""
    results = []
    topics_dir = agent_path / "topics"

    if not topics_dir.exists():
        return results

    # Collect all topic file names (lowercased for matching)
    topic_files = []
    for f in topics_dir.rglob("*.mcs.yml"):
        topic_files.append(f.stem.lower().replace(".mcs", ""))

    # Also check file content for ServiceNow references
    sn_topic_count = 0
    for f in topics_dir.rglob("*.mcs.yml"):
        try:
            content = f.read_text(encoding="utf-8").lower()
            if "servicenow" in content:
                sn_topic_count += 1
        except (OSError, UnicodeDecodeError):
            continue

    if sn_topic_count > 0:
        results.append(CheckResult(roles=[Role.ESS_MAKER.value],
            checkpoint_id="SN-LOCAL-001", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.PASSED.value,
            description=f"{label}: ServiceNow topics present",
            result=f"Found {sn_topic_count} topic(s) referencing ServiceNow",
        ))

        # Check for HRSD topics
        hrsd_found = _count_matching_topics(topic_files, "hrsd")
        itsm_found = _count_matching_topics(topic_files, "itsm")

        if hrsd_found:
            results.append(CheckResult(roles=[Role.ESS_MAKER.value],
                checkpoint_id="SN-LOCAL-002", category="ServiceNow",
                priority=Priority.MEDIUM.value, status=Status.PASSED.value,
                description=f"{label}: ServiceNow HRSD topics",
                result=f"Found {hrsd_found} HRSD topic(s)",
            ))

        if itsm_found:
            results.append(CheckResult(roles=[Role.ESS_MAKER.value],
                checkpoint_id="SN-LOCAL-003", category="ServiceNow",
                priority=Priority.MEDIUM.value, status=Status.PASSED.value,
                description=f"{label}: ServiceNow ITSM topics",
                result=f"Found {itsm_found} ITSM topic(s)",
            ))

        if not hrsd_found and not itsm_found:
            results.append(CheckResult(roles=[Role.ESS_MAKER.value],
                checkpoint_id="SN-LOCAL-002", category="ServiceNow",
                priority=Priority.MEDIUM.value, status=Status.WARNING.value,
                description=f"{label}: ServiceNow HRSD/ITSM topics",
                result="ServiceNow topics found but none match expected HRSD or ITSM patterns",
                remediation="Verify the ServiceNow extension pack installed correctly.",
            ))
    else:
        results.append(CheckResult(roles=[Role.ESS_MAKER.value],
            checkpoint_id="SN-LOCAL-001", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.NOT_CONFIGURED.value,
            description=f"{label}: ServiceNow topics",
            result="No ServiceNow topics found in local agent files",
            remediation="Install a ServiceNow extension pack and re-run /setup to extract topics.",
            doc_link=f"{DOC_BASE}/servicenow",
        ))

    return results


def _count_matching_topics(topic_files: list[str], pack_type: str) -> int:
    """Count how many topic files match expected patterns for a pack type."""
    patterns = [t["pattern"] for t in EXPECTED_TOPICS.get(pack_type, [])]
    count = 0
    for f in topic_files:
        # Remove spaces/dashes for fuzzy matching
        normalized = f.replace("-", "").replace("_", "").replace(" ", "")
        if any(p.replace(" ", "") in normalized for p in patterns):
            count += 1
    return count


