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

    # ---- AUTH-005: Workday Enterprise App user assignment ----
    results.extend(_check_workday_app_user_assignment(graph))

    return results


# Display-name prefix(es) we recognize as the Workday Enterprise App
# in a customer tenant. Most customers leave the SSO gallery name
# ("Workday") in place; some prepend "Workday SSO" / "Workday OAuth".
# Matches via the `startswith(displayName, '...')` Graph filter.
_WORKDAY_SP_PREFIXES = ("Workday",)


def _check_workday_app_user_assignment(graph) -> list[CheckResult]:
    """AUTH-005: Verify the Workday Enterprise App requires user assignment
    AND has at least one user/group assigned.

    Without user assignment + an assigned ESS security group, the OBO/OAuth
    handshake at first agent access fails for end users (Sev 2 outage seen
    in customer ICM analysis). Validation logic per issue
    microsoft/Employee-Self-Service-Agent-Developer-Kit#79:

      1. Locate the Workday Enterprise Application service principal(s)
         via ``GET /servicePrincipals?$filter=startswith(displayName,'Workday')``.
      2. For each, read ``appRoleAssignmentRequired`` (Edm.Boolean).
         - ``False`` → WARNING (deploy-time check cannot guarantee per-user
           access at runtime; recommend setting it to Yes and assigning an
           ESS group).
         - ``True`` → query
           ``GET /servicePrincipals/{id}/appRoleAssignedTo``:
           * No assignments → FAILED (OBO will fail for all users).
           * At least one Group assignment → PASSED.
           * Only User-typed assignments → WARNING (works, but a security
             group is the supportable pattern).

    If no Workday SP is found, return SKIPPED — the customer tenant doesn't
    have the Workday SSO app provisioned yet, so this gate isn't
    applicable until they install it.
    """
    cp_id = "AUTH-005"
    description = "Workday Enterprise App user assignment"
    doc_link = f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso"

    if not graph:
        return [CheckResult(
            checkpoint_id=cp_id, category="Authentication",
            priority=Priority.CRITICAL.value, status=Status.SKIPPED.value,
            description=description,
            result="Microsoft Graph client not available (auth skipped).",
        )]

    try:
        # Single Graph filter that catches the common SSO gallery name and
        # the OAuth-flavored variants tenants sometimes register alongside.
        filter_clause = " or ".join(
            f"startswith(displayName,'{p}')" for p in _WORKDAY_SP_PREFIXES
        )
        sps = graph.get_service_principals(filter_expr=filter_clause)
    except Exception as e:
        return [CheckResult(
            checkpoint_id=cp_id, category="Authentication",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description=description,
            result=f"Unable to query Workday Enterprise App: {e}",
            remediation=(
                "Requires Application.Read.All or Directory.Read.All on the "
                "Graph token. Re-run FlightCheck with an account that holds "
                "those permissions."
            ),
        )]

    if not sps:
        return [CheckResult(
            checkpoint_id=cp_id, category="Authentication",
            priority=Priority.CRITICAL.value, status=Status.SKIPPED.value,
            description=description,
            result=(
                "No Enterprise Application matching displayName starting with "
                f"{', '.join(repr(p) for p in _WORKDAY_SP_PREFIXES)} found in "
                "this tenant. The Workday SSO app must be provisioned before "
                "this check applies."
            ),
            remediation=(
                "Install the Workday Enterprise Application from the Entra "
                "gallery and re-run FlightCheck. See the ESS Workday "
                "prerequisites: " + doc_link
            ),
        )]

    results: list[CheckResult] = []
    for sp in sps:
        sp_id = sp.get("id", "")
        sp_name = sp.get("displayName", "(unnamed)")
        required = sp.get("appRoleAssignmentRequired")

        if not sp_id:
            # Should not happen — Graph always returns id on /servicePrincipals
            # — but guard rather than crash if a future schema change drops it.
            results.append(CheckResult(
                checkpoint_id=cp_id, category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description=description,
                result=f"Workday SP '{sp_name}' returned without an id field.",
                doc_link=doc_link,
            ))
            continue

        if required is False:
            results.append(CheckResult(
                checkpoint_id=cp_id, category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description=description,
                result=(
                    f"Workday SP '{sp_name}': 'User assignment required?' is "
                    "set to No. A deploy-time check cannot guarantee per-user "
                    "access at runtime."
                ),
                remediation=(
                    "In Entra → Enterprise Applications → "
                    f"'{sp_name}' → Properties, set 'Assignment required?' "
                    "to Yes, then assign the ESS user security group under "
                    "Users and groups."
                ),
                doc_link=doc_link,
            ))
            continue

        # appRoleAssignmentRequired is True (or absent — Graph defaults to
        # False, but the schema lets it be omitted; treat None as True only
        # if we got a falsy answer above. Here required is True or None
        # already-implies-True only after the False branch — for missing
        # field we conservatively continue to the assignment check).
        try:
            assignments = graph.get_app_role_assignments(sp_id)
        except Exception as e:
            results.append(CheckResult(
                checkpoint_id=cp_id, category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description=description,
                result=(
                    f"Workday SP '{sp_name}': unable to list assigned "
                    f"users/groups: {e}"
                ),
                remediation=(
                    "Requires Application.Read.All or Directory.Read.All. "
                    "Re-run FlightCheck with sufficient permissions."
                ),
                doc_link=doc_link,
            ))
            continue

        if not assignments:
            results.append(CheckResult(
                checkpoint_id=cp_id, category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description=description,
                result=(
                    f"Workday SP '{sp_name}' requires user assignment but no "
                    "users or groups are assigned. The OBO/OAuth handshake "
                    "on first agent access will fail for ALL end users."
                ),
                remediation=(
                    "In Entra → Enterprise Applications → "
                    f"'{sp_name}' → Users and groups, assign the ESS user "
                    "security group (preferred) or the individual ESS users "
                    "before deploying."
                ),
                doc_link=doc_link,
            ))
            continue

        groups = [a for a in assignments if a.get("principalType") == "Group"]
        users_only = all(a.get("principalType") == "User" for a in assignments)

        if groups:
            group_names = ", ".join(
                a.get("principalDisplayName", "?") for a in groups[:3]
            )
            extra = "" if len(groups) <= 3 else f" (+{len(groups) - 3} more)"
            results.append(CheckResult(
                checkpoint_id=cp_id, category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description=description,
                result=(
                    f"Workday SP '{sp_name}': user assignment required, "
                    f"{len(assignments)} principal(s) assigned including "
                    f"{len(groups)} group(s) — {group_names}{extra}."
                ),
                doc_link=doc_link,
            ))
        elif users_only:
            results.append(CheckResult(
                checkpoint_id=cp_id, category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description=description,
                result=(
                    f"Workday SP '{sp_name}' has {len(assignments)} "
                    "individual user(s) assigned but no security groups. "
                    "Per-user assignment works but doesn't scale; new ESS "
                    "users won't get access automatically."
                ),
                remediation=(
                    "Assign an ESS user security group to the Workday "
                    "Enterprise Application instead of (or in addition to) "
                    "individual users."
                ),
                doc_link=doc_link,
            ))
        else:
            # Mix of types we didn't categorize (e.g. ServicePrincipal-only).
            results.append(CheckResult(
                checkpoint_id=cp_id, category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description=description,
                result=(
                    f"Workday SP '{sp_name}': user assignment required, "
                    f"{len(assignments)} principal(s) assigned."
                ),
                doc_link=doc_link,
            ))

    return results
