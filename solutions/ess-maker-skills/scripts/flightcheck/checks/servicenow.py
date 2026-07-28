# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ServiceNow Deep Validation (SN-CONN-xxx, SN-FLOW-xxx, SN-CFG-xxx, SN-LOCAL-xxx)

Validates ServiceNow connection references, flow status, template configurations
in Dataverse, and local agent topic files for ServiceNow HRSD/ITSM scenarios.
"""

import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from ..runner import CheckResult, Priority, Role, Status
from .connections import check_connector_connections
from .external_systems import _categorize_servicenow_flows

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
    results.extend(_check_servicenow_run_health(runner))

    # --- Template Configurations (Dataverse) ---
    results.extend(_check_template_configs(runner))

    # --- Template Config portal base URL value populated (SN-CFG-002) ---
    results.extend(_check_template_config_base_urls(runner))

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


# Characters that must never appear in a real URL host — their presence
# means an unsubstituted placeholder token (e.g. ``{{ServiceNowBaseUrl}}``)
# leaked into the host of an otherwise absolute-looking URL.
_PLACEHOLDER_HOST_CHARS = set("{}<>%$ ")

# Absolute http(s) URL. The host may temporarily include placeholder
# braces here; ``_is_absolute_http_url`` rejects those after parsing so a
# scheme-prefixed placeholder (``https://{{baseUrl}}``) does NOT count as
# a populated base URL.
_ABSOLUTE_URL_RE = re.compile(r"https?://[^\s\"'<>)\\]+", re.IGNORECASE)


def _is_absolute_http_url(candidate: str) -> bool:
    """Return True if ``candidate`` is a non-empty absolute http(s) URL
    with a real host.

    A URL whose host still carries an unsubstituted placeholder token
    (e.g. ``https://{{ServiceNowBaseUrl}}/api/...``) is rejected — its
    netloc is non-empty but is not a real ServiceNow instance host, so it
    must not be treated as a populated base URL.
    """
    try:
        parsed = urlparse(candidate.strip())
    except (ValueError, AttributeError):
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    host = parsed.hostname or parsed.netloc
    if any(ch in _PLACEHOLDER_HOST_CHARS for ch in parsed.netloc):
        return False
    # Reject hosts that are empty or carry no domain/label at all.
    return bool(host) and host not in (".", "")


def _value_has_valid_base_url(value: str | None) -> bool:
    """Decide whether a ServiceNow template config value carries a
    populated, well-formed portal base URL.

    The ServiceNow HRSD/ITSM extension-pack template configs embed the
    ServiceNow instance/portal base URL inside their value (it is the
    host the request templates point at, and the host used to render
    ticket/case hyperlinks). A config is considered good when its value
    contains at least one absolute http(s) URL.

    Returns False when the value is blank, when it still carries an
    unsubstituted base-URL placeholder token (e.g. ``{{baseUrl}}`` /
    ``<ServiceNow Base URL>``) and no real URL alongside it, or when it
    contains no absolute http(s) URL at all.
    """
    if not value or not value.strip():
        return False

    candidates = _ABSOLUTE_URL_RE.findall(value)
    has_real_url = any(_is_absolute_http_url(c) for c in candidates)
    if has_real_url:
        return True

    # No real absolute URL. If an unsubstituted placeholder is present,
    # the base URL was never filled in; otherwise the value simply lacks
    # an absolute URL. Either way it's not a valid populated base URL.
    return False


# The portal base URL lives only in the two extension-pack "root" configs
# (msdyn_ServiceNowHRSD / msdyn_ServiceNowITSM) as a JSON object carrying a
# "ServiceNowPortalBaseURI" field. Every other ServiceNow-named template
# config (scenario request templates, field mappings, live-agent settings)
# never carries the portal URL, so SN-CFG-002 must evaluate only the configs
# that actually hold this field — otherwise it false-WARNs on the majority.
_BASE_URI_KEY = "servicenowportalbaseuri"


def _portal_base_uri_field(value: str | None) -> tuple[bool, str]:
    """Return ``(has_field, field_value)`` for a template config value.

    ``has_field`` is True only when the value carries a
    ``ServiceNowPortalBaseURI`` field — the marker of a base-URL-bearing
    config. ``field_value`` is that field's string ('' when present but
    empty). Non-base-URL configs (the majority of ServiceNow-named configs)
    return ``(False, '')`` and are skipped by SN-CFG-002.
    """
    if not value or not value.strip():
        return (False, "")
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        # Non-JSON value — fall back to substring detection so a
        # differently-serialised config still counts as base-URL-bearing.
        if _BASE_URI_KEY in value.lower():
            return (True, value)
        return (False, "")
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(key, str) and key.lower() == _BASE_URI_KEY:
                return (True, val if isinstance(val, str) else "")
    return (False, "")


def _pack_for_config_name(name: str | None) -> str | None:
    """Map a ServiceNow config/env-var name to its extension pack token."""
    lowered = (name or "").lower()
    if "hrsd" in lowered:
        return "hrsd"
    if "itsm" in lowered:
        return "itsm"
    return None


def _env_var_valid_base_urls(env_url: str, dv_token: str) -> dict[str, str]:
    """Return ``{pack_token: url}`` for ServiceNow ``*PortalBaseURI`` env
    vars that are set to a valid absolute URL.

    SN-CFG-002 validates the legacy template-config base URL. Once a tenant
    moves to the update-safe env-var mechanism (US 7535608, checked by
    SN-URL-001/002), the template config is intentionally left empty, so
    SN-CFG-002 must defer to the env var to avoid a false WARN on migrated
    tenants. Returns ``{}`` on any error — deference simply does not apply.
    """
    try:
        from auth import query_all

        defs = query_all(
            env_url, dv_token,
            "environmentvariabledefinitions",
            "schemaname,environmentvariabledefinitionid",
            filter_expr="contains(schemaname,'PortalBaseURI')",
        )
        if not defs:
            return {}
        vals = query_all(
            env_url, dv_token,
            "environmentvariablevalues",
            "value,_environmentvariabledefinitionid_value",
        )
    except Exception:
        return {}

    schema_by_def_id = {
        d.get("environmentvariabledefinitionid"): d.get("schemaname", "")
        for d in defs
    }
    valid: dict[str, str] = {}
    for v in vals:
        schema = schema_by_def_id.get(v.get("_environmentvariabledefinitionid_value"))
        if not schema:
            continue
        if not _value_has_valid_base_url(v.get("value", "")):
            continue
        pack = _pack_for_config_name(schema)
        if pack:
            valid[pack] = v.get("value", "")
    return valid


def _check_template_config_base_urls(runner) -> list[CheckResult]:
    """SN-CFG-002 — verify the portal base URL is populated in the ServiceNow
    extension-pack template config(s) that carry it.

    Only the HRSD/ITSM root configs embed the base URL (as a
    ``ServiceNowPortalBaseURI`` JSON field); scenario/field-mapping configs
    never do and are ignored. When a tenant has moved the base URL to the
    update-safe environment variable (US 7535608 / SN-URL-001/002), this
    check defers to that env var instead of flagging the now-empty template
    config.

    When the base URL value is blank or malformed, "read all tickets" /
    "read all cases" responses silently omit hyperlinks — no runtime error
    is surfaced, so a pre-flight WARN catches it before rollout.
    """
    results: list[CheckResult] = []
    env_url = runner.env_url
    dv_token = runner.dv_token

    roles = [Role.ESS_MAKER.value, Role.SERVICENOW_ADMIN.value, Role.POWER_PLATFORM_ADMIN.value]

    if not env_url or not dv_token:
        results.append(CheckResult(roles=roles,
            checkpoint_id="SN-CFG-002", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.SKIPPED.value,
            description="ServiceNow portal base URL populated",
            result="Dataverse token not available — skipping base URL value check",
        ))
        return results

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        configs = query_all(
            env_url, dv_token,
            "msdyn_employeeselfservicetemplateconfigs",
            "msdyn_name,msdyn_value",
            filter_expr="contains(msdyn_name,'ServiceNow')",
        )
    except Exception as e:
        results.append(CheckResult(roles=roles,
            checkpoint_id="SN-CFG-002", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.WARNING.value,
            description="ServiceNow portal base URL populated",
            result=f"Unable to query template config values: {e}",
            remediation=(
                "Re-run /flightcheck once Dataverse is reachable to verify the "
                "ServiceNow portal base URL is populated in the HRSD/ITSM "
                "extension-pack template config."
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        ))
        return results

    # Scope to only the config(s) that actually carry the portal base URL
    # field. The majority of ServiceNow-named configs are scenario/field-
    # mapping records that never hold a URL and must not be flagged.
    base_url_configs = []
    for c in configs:
        has_field, field_value = _portal_base_uri_field(c.get("msdyn_value"))
        if has_field:
            base_url_configs.append((c.get("msdyn_name", "(unnamed)"), field_value))

    env_valid = _env_var_valid_base_urls(env_url, dv_token)

    if not base_url_configs:
        # No template config carries the base URL field. Either the pack
        # isn't installed, or the tenant stores the URL only in the env var.
        if env_valid:
            results.append(CheckResult(roles=roles,
                checkpoint_id="SN-CFG-002", category="ServiceNow",
                priority=Priority.MEDIUM.value, status=Status.PASSED.value,
                description="ServiceNow portal base URL populated",
                result=(
                    "Portal base URL is provided via the update-safe environment "
                    "variable (validated by SN-URL-001/002); no template-config "
                    "base URL to validate."
                ),
                doc_link=f"{DOC_BASE}/servicenow",
            ))
            return results
        results.append(CheckResult(roles=roles,
            checkpoint_id="SN-CFG-002", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.NOT_CONFIGURED.value,
            description="ServiceNow portal base URL populated",
            result="No ServiceNow template config carries a portal base URL to validate",
            remediation=(
                "Install the ServiceNow extension pack (HRSD/ITSM) in Copilot "
                "Studio — see SN-CFG-001."
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        ))
        return results

    # Evaluate each base-URL config, deferring per-pack to the update-safe
    # env var when it already holds a valid URL (migrated tenant).
    missing = []
    deferred = []
    validated = 0
    for name, field_value in base_url_configs:
        pack = _pack_for_config_name(name)
        if pack and pack in env_valid:
            deferred.append(name)
            continue
        if _value_has_valid_base_url(field_value):
            validated += 1
        else:
            missing.append(name)

    if missing:
        result = (
            f"{len(missing)} of {len(base_url_configs)} ServiceNow base-URL "
            f"config(s) have a missing or malformed portal base URL: "
            f"{', '.join(sorted(missing))}"
        )
        if deferred:
            result += (
                f" ({len(deferred)} superseded by the env var and validated by "
                "SN-URL-001/002)"
            )
        results.append(CheckResult(roles=roles,
            checkpoint_id="SN-CFG-002", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.WARNING.value,
            description="ServiceNow portal base URL populated",
            result=result,
            remediation=(
                "Set the ServiceNow portal base URL to your instance URL "
                "(e.g. https://<instance>.service-now.com) in the HRSD/ITSM "
                "extension-pack template config. When the base URL is blank, "
                "'read all tickets' / 'read all cases' responses omit "
                "hyperlinks without surfacing any error."
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        ))
        return results

    if deferred and validated == 0:
        result = (
            f"All {len(deferred)} ServiceNow base-URL config(s) are superseded "
            "by the update-safe env var (validated by SN-URL-001/002)."
        )
    elif deferred:
        result = (
            f"{validated} ServiceNow base-URL template config(s) carry a "
            "populated, well-formed http(s) portal base URL; "
            f"{len(deferred)} superseded by the env var (validated by "
            "SN-URL-001/002)."
        )
    else:
        result = (
            f"All {len(base_url_configs)} ServiceNow base-URL template config(s) "
            "carry a populated, well-formed http(s) portal base URL"
        )
    results.append(CheckResult(roles=roles,
        checkpoint_id="SN-CFG-002", category="ServiceNow",
        priority=Priority.MEDIUM.value, status=Status.PASSED.value,
        description="ServiceNow portal base URL populated",
        result=result,
        doc_link=f"{DOC_BASE}/servicenow",
    ))
    return results


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


