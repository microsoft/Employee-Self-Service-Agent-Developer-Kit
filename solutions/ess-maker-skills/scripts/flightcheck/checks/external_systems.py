# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — External Systems Discovery (WD-001, SN-001, SAP-001)

Discovers installed integration solutions by scanning flows for name patterns.
Solution-scoped: uses agent name to filter relevant flows.
"""

from ..runner import CheckResult, Priority, Role, Status

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"

# Flow name patterns per integration
WORKDAY_PATTERNS = ("Workday",)
SERVICENOW_PATTERNS = ("ServiceNow",)
SAP_PATTERNS = ("SAP", "SuccessFactors")


def _match_flows(flows: list, patterns: tuple) -> list:
    """Return flows whose display name contains any of the patterns."""
    matched = []
    for f in flows:
        name = f.get("properties", {}).get("displayName", f.get("displayName", ""))
        if any(p.lower() in name.lower() for p in patterns):
            matched.append(f)
    return matched


def _categorize_servicenow_flows(flows: list) -> tuple[list, list, list]:
    """Split ServiceNow flows into HRSD, ITSM, and Other."""
    hrsd, itsm, other = [], [], []
    for f in flows:
        name = f.get("properties", {}).get("displayName", f.get("displayName", ""))
        if any(k in name for k in ("HRSD", "HR Service")):
            hrsd.append(f)
        elif any(k in name for k in ("ITSM", "Incident", "Ticket")):
            itsm.append(f)
        else:
            other.append(f)
    return hrsd, itsm, other


def run_external_systems_checks(runner) -> list[CheckResult]:
    """Discover external system integrations from flow inventory."""
    pp = runner.pp_admin
    env_id = runner.env_id
    results: list[CheckResult] = []

    if not env_id:
        return results

    # Fetch all flows
    try:
        all_flows = pp.get_flows(env_id)
        if isinstance(all_flows, dict) and "_error" in all_flows:
            results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="EXT-001", category="External Systems",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="Flow inventory",
                result=f"Unable to list flows: {all_flows['_error']}",
                remediation="Requires Power Platform Admin role.",
            ))
            return results
    except Exception as e:
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="EXT-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Flow inventory",
            result=f"Unable to list flows: {e}",
        ))
        return results

    # Store discovered flows on runner for downstream checks
    runner._all_flows = all_flows

    # ---- WD-001: Workday solution ----
    wd_flows = _match_flows(all_flows, WORKDAY_PATTERNS)
    runner._workday_flows = wd_flows
    if wd_flows:
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="WD-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Workday solution installed",
            result=f"Found {len(wd_flows)} Workday flow(s)",
            remediation=f"Validated: {len(wd_flows)} Workday cloud flow(s) are present in the environment, indicating the Workday solution/extension pack is installed.",
            doc_link=f"{DOC_BASE}/workday",
        ))
    else:
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="WD-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="Workday solution installed",
            result="No Workday flows found in environment",
            remediation="Install the Workday extension pack if you plan to integrate.",
            doc_link=f"{DOC_BASE}/workday",
        ))

    # ---- SN-001: ServiceNow solution ----
    sn_flows = _match_flows(all_flows, SERVICENOW_PATTERNS)
    runner._servicenow_flows = sn_flows
    if sn_flows:
        hrsd, itsm, other = _categorize_servicenow_flows(sn_flows)
        detail = f"Found {len(sn_flows)} ServiceNow flow(s)"
        if hrsd:
            detail += f" ({len(hrsd)} HRSD"
        if itsm:
            detail += f", {len(itsm)} ITSM"
        if other:
            detail += f", {len(other)} other"
        if hrsd or itsm or other:
            detail += ")"
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="SN-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="ServiceNow solution installed",
            result=detail,
            remediation="Validated: ServiceNow cloud flow(s) are present in the environment, indicating the ServiceNow (HRSD/ITSM) solution is installed.",
            doc_link=f"{DOC_BASE}/servicenow",
        ))
    else:
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="SN-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="ServiceNow solution installed",
            result="No ServiceNow flows found in environment",
            remediation="Install the ServiceNow extension pack if you plan to integrate.",
            doc_link=f"{DOC_BASE}/servicenow",
        ))

    # ---- SAP-001: SAP SuccessFactors solution ----
    sap_flows = _match_flows(all_flows, SAP_PATTERNS)
    runner._sap_flows = sap_flows
    if sap_flows:
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="SAP-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="SAP SuccessFactors solution installed",
            result=f"Found {len(sap_flows)} SAP flow(s)",
            remediation=f"Validated: {len(sap_flows)} SAP SuccessFactors cloud flow(s) are present in the environment, indicating the SAP SuccessFactors solution is installed.",
            doc_link=f"{DOC_BASE}/sap-successfactors",
        ))
    else:
        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="SAP-001", category="External Systems",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="SAP SuccessFactors solution installed",
            result="No SAP SuccessFactors flows found",
            remediation="Install the SAP extension pack if you plan to integrate.",
            doc_link=f"{DOC_BASE}/sap-successfactors",
        ))

    return results
