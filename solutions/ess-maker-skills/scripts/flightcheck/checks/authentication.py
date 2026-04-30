# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Authentication & Identity Validation (AUTH-xxx)

Checks Entra ID configuration, SSO, Conditional Access, user sync.
"""

from ..runner import CheckResult, Status, Priority

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"


def run_authentication_checks(runner) -> list[CheckResult]:
    """Execute all authentication checks using the Graph client."""
    graph = runner.graph
    results: list[CheckResult] = []

    # ---- AUTH-001: Entra ID configured ----
    try:
        org = graph.get_organization()
        if org and "displayName" in org:
            results.append(CheckResult(
                checkpoint_id="AUTH-001", category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Microsoft Entra ID configured",
                result=f"Tenant: {org['displayName']} ({org.get('id', 'N/A')})",
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="AUTH-001", category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Microsoft Entra ID configured",
                result="Unable to retrieve organization info",
                remediation="Ensure Entra ID is properly configured.",
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="AUTH-001", category="Authentication",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Microsoft Entra ID",
            result=f"Unable to check: {e}",
        ))

    # ---- AUTH-002: Conditional Access policies ----
    try:
        policies = graph.get_conditional_access_policies()
        if policies:
            enabled = [p for p in policies if p.get("state") == "enabled"]
            report_only = [
                p for p in policies
                if p.get("state") == "enabledForReportingButNotEnforced"
            ]
            results.append(CheckResult(
                checkpoint_id="AUTH-002", category="Authentication",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description="Conditional Access policies",
                result=(
                    f"{len(policies)} total — "
                    f"{len(enabled)} enabled, "
                    f"{len(report_only)} report-only"
                ),
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="AUTH-002", category="Authentication",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="Conditional Access policies",
                result="No Conditional Access policies found",
                remediation="Configure SSO and CA policies for enhanced security.",
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="AUTH-002", category="Authentication",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="Conditional Access policies",
            result=f"Unable to check: {e}",
            remediation="Requires Policy.Read.All permission.",
        ))

    # ---- AUTH-004: User identity sync ----
    try:
        users = graph.get_users_sample(top=10)
        if users:
            results.append(CheckResult(
                checkpoint_id="AUTH-004", category="Authentication",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description="User identity synchronization",
                result=f"Verified: {len(users)} sample users found in Entra ID",
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="AUTH-004", category="Authentication",
                priority=Priority.HIGH.value, status=Status.FAILED.value,
                description="User identity synchronization",
                result="No users found in Entra ID",
                remediation="Ensure user sync is configured and working.",
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="AUTH-004", category="Authentication",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="User identity sync",
            result=f"Unable to check: {e}",
        ))

    return results
