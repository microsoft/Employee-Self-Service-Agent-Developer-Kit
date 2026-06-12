# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Prerequisites Validation (PRE-xxx)

Checks Microsoft 365 Copilot licenses, Copilot Studio licenses, Teams
licenses, role assignments, and capacity.
"""

from ..runner import CheckResult, Status, Priority

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"


def _sku_matches(sku: dict, patterns: tuple[str, ...]) -> bool:
    """Case-insensitive substring match against `skuPartNumber`.

    Graph returns `skuPartNumber` in mixed case (e.g. ``Microsoft_365_Copilot``)
    for many SKUs, while Microsoft's documented part numbers and most
    operator-facing references use UPPER_SNAKE_CASE (e.g.
    ``MICROSOFT_365_COPILOT``). A naive case-sensitive ``in`` check
    silently misses every license on tenants whose Graph response uses
    mixed case, which was the original behavior of these PRE-xxx
    checks and produced false-negative "No <X> licenses found" results
    even on properly-licensed tenants.
    """
    part = (sku.get("skuPartNumber") or "").upper()
    return any(p.upper() in part for p in patterns)


# Microsoft 365 Copilot SKU part numbers (and historical aliases).
M365_COPILOT_SKUS: tuple[str, ...] = (
    "MICROSOFT_365_COPILOT",
)

# Copilot Studio SKU part numbers. The M365 Copilot bundle also
# includes Copilot Studio message capacity, so it counts as a source
# of Copilot Studio entitlement for prerequisite-check purposes.
COPILOT_STUDIO_SKUS: tuple[str, ...] = (
    "COPILOT_STUDIO",                  # forward-compatible Studio SKUs
    "MICROSOFT_COPILOT_STUDIO",        # alternate naming convention
    "POWER_VIRTUAL_AGENTS",            # legacy PVA SKUs (PVA_VIRAL, etc.)
    "CCIBOTS_PRIVPREV_VIRAL",          # original PVA preview SKU
    "MICROSOFT_365_COPILOT",           # M365 Copilot bundle includes Studio messages
)

# SKUs that carry Microsoft Teams entitlement, including bundles
# whose part numbers do not literally contain "TEAMS".
TEAMS_BEARING_SKUS: tuple[str, ...] = (
    "TEAMS",                           # standalone Teams SKUs (TEAMS_EXPLORATORY, TEAMS_FREE_*, etc.)
    "O365_BUSINESS_PREMIUM",           # M365 Business Standard
    "O365_BUSINESS_ESSENTIALS",        # M365 Business Basic
    "SPB",                             # M365 Business Premium
    "M365_BUSINESS_PREMIUM",
    "ENTERPRISEPACK",                  # Office 365 E3
    "ENTERPRISEPREMIUM",               # Office 365 E5
    "SPE_E3",                          # Microsoft 365 E3
    "SPE_E5",                          # Microsoft 365 E5
    "DEVELOPERPACK_E5",                # M365 E5 Developer
)


def run_prerequisites_checks(runner) -> list[CheckResult]:
    """Execute all prerequisites checks using the Graph client."""
    graph = runner.graph
    results: list[CheckResult] = []

    # ---- PRE-001: Microsoft 365 Copilot licenses ----
    try:
        skus = graph.get_subscribed_skus()
        copilot_skus = [s for s in skus if _sku_matches(s, M365_COPILOT_SKUS)]
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
                remediation="Validated: at least one Microsoft 365 Copilot license seat is consumed in the tenant, read via Microsoft Graph (GET /subscribedSkus, consumedUnits > 0).",
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
        cs_skus = [s for s in skus if _sku_matches(s, COPILOT_STUDIO_SKUS)]
        if cs_skus:
            names = ", ".join(s.get("skuPartNumber", "") for s in cs_skus)
            results.append(CheckResult(
                checkpoint_id="PRE-002", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Copilot Studio licenses",
                result=f"Found: {names}",
                remediation="Validated: at least one Copilot Studio license SKU is present in the tenant, read via Microsoft Graph (GET /subscribedSkus).",
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
        teams_skus = [s for s in skus if _sku_matches(s, TEAMS_BEARING_SKUS)]
        consumed = sum(s.get("consumedUnits", 0) for s in teams_skus)
        if teams_skus and consumed > 0:
            results.append(CheckResult(
                checkpoint_id="PRE-003", category="Prerequisites",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Microsoft Teams licenses",
                result=f"{consumed} users licensed for Teams",
                remediation="Validated: at least one Microsoft Teams license is consumed in the tenant, read via Microsoft Graph (GET /subscribedSkus, consumedUnits > 0).",
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
                remediation="Validated: the Global Administrator directory role has at least one active member, read via Microsoft Graph (GET /directoryRoles + members).",
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
                remediation="Validated: the Power Platform Administrator directory role has at least one active member, read via Microsoft Graph (GET /directoryRoles + members).",
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
