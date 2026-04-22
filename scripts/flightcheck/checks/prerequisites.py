"""
ESS FlightCheck — Prerequisites Validation (PRE-xxx)

Checks Microsoft 365 Copilot licenses, Copilot Studio licenses, Teams
licenses, role assignments, and capacity.
"""

from ..runner import CheckResult, Status, Priority

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"


def run_prerequisites_checks(runner) -> list[CheckResult]:
    """Execute all prerequisites checks using the Graph client."""
    graph = runner.graph
    results: list[CheckResult] = []

    # ---- PRE-001: Microsoft 365 Copilot licenses ----
    try:
        skus = graph.get_subscribed_skus()
        copilot_skus = [s for s in skus if "MICROSOFT_365_COPILOT" in s.get("skuPartNumber", "")]
        consumed = sum(s.get("consumedUnits", 0) for s in copilot_skus)
        enabled = sum(
            s.get("prepaidUnits", {}).get("enabled", 0) for s in copilot_skus
        )
        if copilot_skus and consumed > 0:
            results.append(CheckResult(
                checkpoint_id="PRE-001", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Microsoft 365 Copilot licenses",
                result=f"Found {consumed} consumed / {enabled} enabled",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="PRE-001", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Microsoft 365 Copilot licenses",
                result="No M365 Copilot licenses found or none consumed",
                remediation="Purchase and assign M365 Copilot licenses in the [M365 admin center](https://admin.microsoft.com).",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="PRE-001", category="Prerequisites",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Microsoft 365 Copilot licenses",
            result=f"Unable to check: {e}",
            remediation="Ensure permissions to read license info via Graph.",
            doc_link=f"{DOC_BASE}/prerequisites#licensing",
        ))

    # ---- PRE-002: Copilot Studio licenses ----
    try:
        skus = graph.get_subscribed_skus()
        cs_skus = [
            s for s in skus
            if any(k in s.get("skuPartNumber", "")
                   for k in ("COPILOT_STUDIO", "POWER_VIRTUAL_AGENTS"))
        ]
        if cs_skus:
            names = ", ".join(s.get("skuPartNumber", "") for s in cs_skus)
            results.append(CheckResult(
                checkpoint_id="PRE-002", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Copilot Studio licenses",
                result=f"Found: {names}",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="PRE-002", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Copilot Studio licenses",
                result="No Copilot Studio licenses found",
                remediation="Assign Copilot Studio licenses to admins/makers in the [M365 admin center](https://admin.microsoft.com).",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="PRE-002", category="Prerequisites",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Copilot Studio licenses",
            result=f"Unable to check: {e}",
            remediation="Ensure Graph license read permissions.",
        ))

    # ---- PRE-003: Microsoft Teams licenses ----
    try:
        skus = graph.get_subscribed_skus()
        teams_skus = [s for s in skus if "TEAMS" in s.get("skuPartNumber", "")]
        consumed = sum(s.get("consumedUnits", 0) for s in teams_skus)
        if teams_skus and consumed > 0:
            results.append(CheckResult(
                checkpoint_id="PRE-003", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Microsoft Teams licenses",
                result=f"{consumed} users licensed for Teams",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="PRE-003", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description="Microsoft Teams licenses",
                result="No Teams licenses found or none consumed",
                remediation="Assign Teams licenses in the [M365 admin center](https://admin.microsoft.com).",
                doc_link=f"{DOC_BASE}/prerequisites#licensing",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="PRE-003", category="Prerequisites",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Microsoft Teams licenses",
            result=f"Unable to check: {e}",
        ))

    # ---- PRE-008: Global Admin role ----
    try:
        roles = graph.get_directory_roles()
        ga_role = next(
            (r for r in roles if r.get("displayName") == "Global Administrator"),
            None,
        )
        if ga_role:
            members = graph.get_role_members(ga_role["id"])
            results.append(CheckResult(
                checkpoint_id="PRE-008", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Global Admin role assigned",
                result=f"Assigned to {len(members)} user(s)",
                doc_link=f"{DOC_BASE}/prerequisites#required-roles",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="PRE-008", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Global Admin role assigned",
                result="Global Administrator role not found",
                remediation="Assign Global Admin to at least one user.",
                doc_link=f"{DOC_BASE}/prerequisites#required-roles",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="PRE-008", category="Prerequisites",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Global Admin role assigned",
            result=f"Unable to check: {e}",
        ))

    # ---- PRE-009: Power Platform Admin role ----
    try:
        roles = graph.get_directory_roles()
        pp_role = next(
            (r for r in roles if "Power Platform" in r.get("displayName", "")),
            None,
        )
        if pp_role:
            members = graph.get_role_members(pp_role["id"])
            results.append(CheckResult(
                checkpoint_id="PRE-009", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Power Platform Admin role assigned",
                result=f"Assigned to {len(members)} user(s)",
                doc_link=f"{DOC_BASE}/prerequisites#required-roles",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="PRE-009", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description="Power Platform Admin role assigned",
                result="Power Platform Administrator role not activated",
                remediation="Assign Power Platform Admin role in [Entra admin center](https://entra.microsoft.com).",
                doc_link=f"{DOC_BASE}/prerequisites#required-roles",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="PRE-009", category="Prerequisites",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Power Platform Admin role assigned",
            result=f"Unable to check: {e}",
        ))

    return results
