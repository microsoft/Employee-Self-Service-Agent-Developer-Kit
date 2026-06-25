# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ServiceNow Deep Validation (SN-CONN-xxx, SN-FLOW-xxx, SN-CFG-xxx, SN-LOCAL-xxx)

Validates ServiceNow connection references, flow status, template configurations
in Dataverse, and local agent topic files for ServiceNow HRSD/ITSM scenarios.
"""

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

    # --- Template Config portal base URL value populated (SN-CFG-002) ---
    results.extend(_check_template_config_base_urls(runner))

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


def _check_template_config_base_urls(runner) -> list[CheckResult]:
    """SN-CFG-002 — verify the portal base URL value inside each ServiceNow
    template config is populated and well-formed.

    Extends SN-CFG-001 (which only validates that the expected config
    records exist by scenario name) from *presence* to *value populated*.
    When the base URL value is blank or malformed, "read all tickets" /
    "read all cases" responses silently omit hyperlinks — no runtime
    error is surfaced, so a pre-flight WARN catches it before rollout.

    Reads the Dataverse ``msdyn_value`` column of
    ``msdyn_employeeselfservicetemplateconfigs`` (Dataverse Web API is the
    ``documented`` tier; field names confirmed in the production
    ``backup_template_configs.py`` selector). Gated the same way as the
    rest of the ServiceNow deep validation (``run_servicenow_checks``
    early-returns when no ServiceNow flows are detected).
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

    if not configs:
        # SN-CFG-001 already reports the missing-config (NotConfigured)
        # state; nothing to validate the base URL against here.
        results.append(CheckResult(roles=roles,
            checkpoint_id="SN-CFG-002", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.NOT_CONFIGURED.value,
            description="ServiceNow portal base URL populated",
            result="No ServiceNow template configs found to validate base URL value",
            remediation=(
                "Install the ServiceNow extension pack (HRSD/ITSM) in Copilot "
                "Studio — see SN-CFG-001."
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        ))
        return results

    missing = []
    for c in configs:
        name = c.get("msdyn_name", "(unnamed)")
        if not _value_has_valid_base_url(c.get("msdyn_value")):
            missing.append(name)

    if not missing:
        results.append(CheckResult(roles=roles,
            checkpoint_id="SN-CFG-002", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.PASSED.value,
            description="ServiceNow portal base URL populated",
            result=(
                f"All {len(configs)} ServiceNow template config(s) carry a "
                "populated, well-formed http(s) portal base URL"
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        ))
    else:
        results.append(CheckResult(roles=roles,
            checkpoint_id="SN-CFG-002", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.WARNING.value,
            description="ServiceNow portal base URL populated",
            result=(
                f"{len(missing)} of {len(configs)} ServiceNow template config(s) "
                f"have a missing or malformed portal base URL: {', '.join(sorted(missing))}"
            ),
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


