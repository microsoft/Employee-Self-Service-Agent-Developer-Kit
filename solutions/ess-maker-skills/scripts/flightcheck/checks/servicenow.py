# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ServiceNow Deep Validation (SN-CONN-xxx, SN-FLOW-xxx, SN-CFG-xxx, SN-URL-xxx, SN-LOCAL-xxx)

Validates ServiceNow connection references, flow status, template configurations
in Dataverse, portal base URL environment variables, and local agent topic files
for ServiceNow HRSD/ITSM scenarios.
"""

import os
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

    # Skip if no ServiceNow flows detected
    sn_flows = getattr(runner, "_servicenow_flows", [])
    if not sn_flows:
        return results

    print("\n  Running ServiceNow deep validation...")

    # --- Connection References ---
    results.extend(_check_connections(runner))

    # --- Flow Status ---
    results.extend(_check_flow_status(runner, sn_flows))

    # --- Template Configurations (Dataverse) ---
    results.extend(_check_template_configs(runner))

    # --- Portal Base URL environment variables (Dataverse) ---
    results.extend(_check_base_url(runner))

    # --- Local Topic Files ---
    results.extend(_check_local_topics(runner))

    return results


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


# Portal base URL environment variables — one per independently-installable
# extension pack so the value survives managed-solution updates (US 7535608).
# These supersede the template-config base URI, which ships empty and is reset
# on every package update (root cause of ICM 820635151).
PORTAL_BASE_URI_ENV_VARS = {
    "hrsd": {
        "id": "SN-URL-001",
        "schema": "msdyn_ServiceNowHRSDPortalBaseURI",
        "label": "ServiceNow HRSD portal base URL",
    },
    "itsm": {
        "id": "SN-URL-002",
        "schema": "msdyn_ServiceNowITSMPortalBaseURI",
        "label": "ServiceNow ITSM portal base URL",
    },
}

_SET_ENV_VAR_STEPS = (
    "Set this environment variable's current value in the "
    "[Power Platform admin center](https://admin.powerplatform.microsoft.com) "
    "(Environments > Settings > Environment variables) to your ServiceNow portal "
    "URL, e.g. https://<instance>.service-now.com/sp."
)


def _is_well_formed_portal_url(value: str) -> bool:
    """A portal base URL must be an absolute http(s) URL with a host."""
    try:
        parsed = urlparse(value)
    except (ValueError, TypeError):
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _evaluate_base_url(cfg: dict, def_present: bool, value) -> CheckResult:
    """Map the observed env-var state to a CheckResult for one extension pack."""
    roles = [Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value]
    doc = f"{DOC_BASE}/servicenow"

    if value and value.strip():
        trimmed = value.strip()
        if _is_well_formed_portal_url(trimmed):
            return CheckResult(
                roles=roles, checkpoint_id=cfg["id"], category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description=cfg["label"],
                result=f"Set to: {trimmed}",
                doc_link=doc,
            )
        return CheckResult(
            roles=roles, checkpoint_id=cfg["id"], category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=cfg["label"],
            result=f"Set to a value that is not a valid absolute URL: {trimmed}",
            remediation=(
                "ServiceNow record hyperlinks may render incorrectly until this "
                "is a valid absolute URL. " + _SET_ENV_VAR_STEPS
            ),
            doc_link=doc,
        )

    if not def_present:
        return CheckResult(
            roles=roles, checkpoint_id=cfg["id"], category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=cfg["label"],
            result="Portal base URL environment variable not found in Dataverse",
            remediation=(
                "Install the matching ServiceNow extension pack, then set the "
                "portal base URL. " + _SET_ENV_VAR_STEPS
            ),
            doc_link=doc,
        )

    return CheckResult(
        roles=roles, checkpoint_id=cfg["id"], category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.FAILED.value,
        description=cfg["label"],
        result="Environment variable exists but has no value set",
        remediation=(
            "ServiceNow record hyperlinks will not render until this is set. "
            + _SET_ENV_VAR_STEPS
        ),
        doc_link=doc,
    )


def _check_base_url(runner) -> list[CheckResult]:
    """Validate the ServiceNow portal base URL env vars are set and well-formed.

    Each extension pack (HRSD, ITSM) carries its own update-safe Dataverse
    environment variable (msdyn_ServiceNow{HRSD,ITSM}PortalBaseURI) whose value
    the orchestrator stamps onto every case/ticket record so the agent can return
    a clickable portal hyperlink. An empty value is the root cause of
    ICM 820635151 (hyperlinks only returned when explicitly requested).
    """
    results: list[CheckResult] = []
    env_url = runner.env_url
    dv_token = runner.dv_token

    if not env_url or not dv_token:
        for cfg in PORTAL_BASE_URI_ENV_VARS.values():
            results.append(CheckResult(
                roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id=cfg["id"], category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.SKIPPED.value,
                description=cfg["label"],
                result="Dataverse token not available — skipping base URL check",
            ))
        return results

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        defs = query_all(
            env_url, dv_token,
            "environmentvariabledefinitions",
            "displayname,schemaname,environmentvariabledefinitionid",
            filter_expr="contains(schemaname,'PortalBaseURI')",
        )
        vals = query_all(
            env_url, dv_token,
            "environmentvariablevalues",
            "value,schemaname,_environmentvariabledefinitionid_value",
        )

        def_map = {d["environmentvariabledefinitionid"]: d for d in defs}
        val_map = {}
        for v in vals:
            def_id = v.get("_environmentvariabledefinitionid_value")
            if def_id in def_map:
                schema = def_map[def_id].get("schemaname", "")
                val_map[schema] = v.get("value", "")

        def_schemas = [d.get("schemaname", "") for d in defs]

        for cfg in PORTAL_BASE_URI_ENV_VARS.values():
            # Match on the publisher-agnostic core (drop the msdyn_ prefix).
            core = cfg["schema"].split("_", 1)[-1].lower()
            def_present = any(core in s.lower() for s in def_schemas)
            value = None
            for schema, val in val_map.items():
                if core in schema.lower():
                    value = val
                    break
            results.append(_evaluate_base_url(cfg, def_present, value))

    except Exception as e:
        for cfg in PORTAL_BASE_URI_ENV_VARS.values():
            results.append(CheckResult(
                roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id=cfg["id"], category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description=cfg["label"],
                result=f"Unable to check base URL env var: {e}",
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


