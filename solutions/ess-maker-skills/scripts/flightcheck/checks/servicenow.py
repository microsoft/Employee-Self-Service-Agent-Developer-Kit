# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ServiceNow Deep Validation (SN-CONN-xxx, SN-FLOW-xxx, SN-CFG-xxx, SN-LOCAL-xxx)

Validates ServiceNow connection references, flow status, template configurations
in Dataverse, and local agent topic files for ServiceNow HRSD/ITSM scenarios.
"""

import os
import sys
from pathlib import Path

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

    # Skip if no ServiceNow flows detected
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
# Detection model (ported from Workday WD-RUN-001, confirmed live there): the
# ESS shared flow CATCHES external faults and responds gracefully, so a failed
# ServiceNow call can leave the run ``status == "Succeeded"`` — the real signal
# is the flow's Response action name. The flow has exactly ONE success Response
# (``Respond_to_Copilot_with_Success``); every other Response branch is a
# failure. Some failures ALSO surface as ``status == "Failed"`` with a run-level
# error. So per-run detection uses BOTH signals, anchored on the single success
# action so every failure branch is caught:
#
#   a run FAILED  if  status == "Failed"
#                 OR (status == "Succeeded" AND response.name != the success action)
#
# The check's VERDICT, however, is a litmus test for a *deterministic* break,
# not a per-run pass/fail: it looks only at the most recent window of runs
# (``_SN_RECENT_WINDOW``, newest first across all ServiceNow flows) and FAILs
# only when NONE of them succeeded. Scattered failures among recent successes
# (e.g. a user requesting a case their ServiceNow ACL doesn't allow) do NOT fail
# readiness — recent successes prove the integration is wired up. A single run
# that failed (no successes in the window) IS a failure.
#
# Known limitations (documented, not silently swallowed):
#   * A fully-broken/unconfigured connection makes Copilot Studio prompt
#     "connect to continue" and never invokes the flow, so NO run is created.
#     That case is covered by SN-CONN-001+ (connection status), NOT here.
#   * Agent-side timeouts (``flowActionTimedOut``) leave the run "Succeeded"
#     and are not detectable from run history.

# The single success Response action. Anything else is a failure branch.
_SN_SUCCESS_RESPONSE_ACTION = "Respond_to_Copilot_with_Success"

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

    Only a ``"Succeeded"`` run can be a success/caught_failure — that is the
    single status whose Response-action name distinguishes the success branch
    from a caught ServiceNow fault. Definite run-level failures
    (``"Failed"``/``"TimedOut"``/``"Faulted"``/``"Aborted"``) are hard_failure.
    Everything else is 'pending' (non-scoring): in-flight states
    (``"Running"``/``"Waiting"``/``"Paused"``/``"Suspended"``) AND inconclusive
    terminal states that are not a ServiceNow-health signal
    (``"Cancelled"``/``"Skipped"``/unknown). Critically, a non-``"Succeeded"``
    run is NEVER counted as a success — an all-``"Cancelled"`` window must not
    yield a misleading PASS (which would hide the manual conn/sec checks). See
    the SN-RUN-001 module comment.
    """
    props = run.get("properties", {}) or {}
    status = props.get("status")
    resp_name = ((props.get("response") or {}).get("name")) or ""
    if status == "Succeeded":
        if resp_name and resp_name != _SN_SUCCESS_RESPONSE_ACTION:
            return "caught_failure"
        return "success"
    if status in _RUN_FAILURE_STATUSES:
        return "hard_failure"
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

    if not sn_flows:
        return [CheckResult(
            checkpoint_id="SN-RUN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ServiceNow flow run health",
            result="No ServiceNow flows discovered — no run history to evaluate.",
            remediation="",
            roles=roles,
        )]

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


