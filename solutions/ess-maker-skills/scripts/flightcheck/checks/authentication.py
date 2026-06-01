# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Authentication & Identity Validation (AUTH-xxx)

Checks Entra ID configuration, SSO, Conditional Access, user sync.
"""

import json

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

    # ---- AUTH-006: SAML NameID alignment with Workday user identifier ----
    #
    # Fixes issue #84. The check reads the Entra-side half of the
    # comparison (the SAML claim mapping for the customer's Workday
    # federated app) via Microsoft Graph, then emits a MANUAL result
    # asking the operator to verify the Workday-side NameID
    # expectation matches. The Workday side has no programmatic admin
    # surface the kit can use today — Workday's Security service
    # operations aren't exposed via WS-Security UsernameToken on a
    # typical tenant (see tests/fixtures/cassettes/INDEX.md "Workday
    # WQL config-validation pattern" for the full discussion), and
    # FlightCheck checks can't prompt for live SAML assertions, so the
    # comparison is delegated to the operator via MANUAL.
    results.extend(_run_saml_nameid_check(runner))

    return results


# ─────────────────────────────────────────────────────────────────────
# AUTH-005 — Workday Enterprise App user assignment.
# ─────────────────────────────────────────────────────────────────────


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

    # Classify each Workday SP into a status bucket. We emit at most
    # one CheckResult per status so the report doesn't get a separate
    # row for every SP — see issue: per-SP rows make the readiness
    # summary unreadable when a tenant has multiple Workday apps
    # (SSO + OAuth + Implementation tenant, etc.).
    #
    # Per-SP tuples are (sp_name, current_state, fix_action). The
    # current_state describes what we observed for THIS SP and goes
    # into the row's result. The fix_action describes how to fix the
    # status and goes into the row's remediation; it must NOT embed
    # the SP name so identical fixes across multiple SPs collapse to
    # a single de-duplicated remediation line.
    failed_items: list[tuple[str, str, str]] = []
    warning_items: list[tuple[str, str, str]] = []
    passed_items: list[tuple[str, str]] = []

    for sp in sps:
        sp_id = sp.get("id", "")
        sp_name = sp.get("displayName", "(unnamed)")
        required = sp.get("appRoleAssignmentRequired")

        if not sp_id:
            # Should not happen — Graph always returns id on /servicePrincipals
            # — but guard rather than crash if a future schema change drops it.
            warning_items.append((
                sp_name,
                "service principal returned without an id field",
                "Re-run FlightCheck; if this persists, file an issue.",
            ))
            continue

        if required is False:
            warning_items.append((
                sp_name,
                "'Assignment required?' is set to No — any licensed user in "
                "the tenant can obtain a Workday SSO token regardless of "
                "group membership; the Users and groups list is "
                "informational only when this is No",
                "Hardening recommendation (not a functional blocker — ESS "
                "works with this set to No). Setting 'Assignment required?' "
                "to Yes restricts Workday token issuance to explicitly "
                "assigned users/groups, shrinks the OBO impersonation "
                "surface, and gives you deploy-time provable group-based "
                "access control. In Entra → Enterprise Applications, open "
                "the app(s) above → Properties → set 'Assignment required?' "
                "to Yes, then under Users and groups assign the ESS user "
                "security group.",
            ))
            continue

        # appRoleAssignmentRequired is True or absent (Graph defaults to
        # False, but the schema lets it be omitted; we conservatively
        # continue to the assignment check when missing).
        try:
            assignments = graph.get_app_role_assignments(sp_id)
        except Exception as e:
            warning_items.append((
                sp_name,
                f"unable to list assigned users/groups ({e})",
                "Re-run FlightCheck with a Graph token that holds "
                "Application.Read.All or Directory.Read.All.",
            ))
            continue

        if not assignments:
            failed_items.append((
                sp_name,
                "user assignment required, 0 users/groups assigned",
                "In Entra → Enterprise Applications, open the app(s) above → "
                "Users and groups → assign the ESS user security group "
                "(preferred over individual users) before deploying. "
                "Without this, the OBO/OAuth handshake on first agent "
                "access fails for ALL end users.",
            ))
            continue

        groups = [a for a in assignments if a.get("principalType") == "Group"]
        users_only = all(a.get("principalType") == "User" for a in assignments)

        if groups:
            group_names = ", ".join(
                a.get("principalDisplayName", "?") for a in groups[:3]
            )
            extra = "" if len(groups) <= 3 else f" (+{len(groups) - 3} more)"
            passed_items.append((
                sp_name,
                f"user assignment required, {len(assignments)} principal(s) "
                f"assigned including {len(groups)} group(s) — "
                f"{group_names}{extra}",
            ))
        elif users_only:
            warning_items.append((
                sp_name,
                f"user assignment required, {len(assignments)} individual "
                "user(s) assigned but no security groups",
                "Assign an ESS user security group to the app(s) above "
                "(in addition to or instead of individual users) so new ESS "
                "users get access automatically.",
            ))
        else:
            # Mix of types we didn't categorize (e.g. ServicePrincipal-only).
            passed_items.append((
                sp_name,
                f"user assignment required, {len(assignments)} principal(s) "
                "assigned",
            ))

    results: list[CheckResult] = []

    # Emit at most one row per status, in priority order so the most
    # urgent finding appears first in the report.
    if failed_items:
        results.append(CheckResult(
            checkpoint_id=cp_id, category="Authentication",
            priority=Priority.CRITICAL.value, status=Status.FAILED.value,
            description=description,
            result=_format_sp_state(failed_items),
            remediation=_format_sp_remediations(failed_items),
            doc_link=doc_link,
        ))

    if warning_items:
        results.append(CheckResult(
            checkpoint_id=cp_id, category="Authentication",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description=description,
            result=_format_sp_state(warning_items),
            remediation=_format_sp_remediations(warning_items),
            doc_link=doc_link,
        ))

    if passed_items:
        results.append(CheckResult(
            checkpoint_id=cp_id, category="Authentication",
            priority=Priority.CRITICAL.value, status=Status.PASSED.value,
            description=description,
            result=_format_sp_state(passed_items),
            doc_link=doc_link,
        ))

    return results


def _format_sp_state(items: list[tuple]) -> str:
    """Render per-SP current-state phrases into one result string.

    Single SP → ``"Workday SP 'X': <state>."`` (preserves the historical
    one-line format the operator is used to).
    Multiple SPs → header + one bullet per SP. The HTML report
    preserves whitespace in result cells (``cell-text`` class added in
    PR #113), so the bullets render on separate lines.

    Tuples may be ``(name, state)`` for the passed bucket or
    ``(name, state, _fix)`` for the failed/warning buckets — only the
    first two elements are read here.
    """
    if len(items) == 1:
        name, state = items[0][0], items[0][1]
        return f"Workday SP '{name}': {state}."
    lines = [f"{len(items)} Workday Enterprise App(s):"]
    for item in items:
        name, state = item[0], item[1]
        lines.append(f"  • '{name}': {state}")
    return "\n".join(lines)


def _format_sp_remediations(items: list[tuple[str, str, str]]) -> str:
    """Render per-SP fix actions into one remediation string.

    Fix actions never embed SP names (the result already lists the
    affected apps), so identical fixes across SPs collapse to one line.
    When SPs in the same status bucket need different fixes (e.g. one
    has Assignment Required=No and another has only individual users),
    we emit each distinct fix on its own bulleted line.
    """
    distinct = list(dict.fromkeys(item[2] for item in items if item[2]))
    if not distinct:
        return ""
    if len(distinct) == 1:
        return distinct[0]
    return "\n".join(f"  • {fix}" for fix in distinct)


# ─────────────────────────────────────────────────────────────────────
# AUTH-006 — SAML NameID alignment (Entra side automated, Workday
# side MANUAL).
# ─────────────────────────────────────────────────────────────────────


# Most production tenants name the federated app starting with "Workday"
# (e.g. "Workday", "Workday Prod", "Workday Implementation"). Match
# server-side via $filter so we don't pull every SP in the tenant.
_WORKDAY_SP_FILTER = (
    "startswith(displayName,'Workday') and preferredSingleSignOnMode eq 'saml'"
)

# Authoritative reference for the Entra→Workday SAML mapping
# behavior. Step 6 + note: "You need to map the Name ID with actual
# User ID in your Workday account". Workday itself matches the
# incoming NameID against the Workday Username — there is NO
# Workday-side configurable "which attribute to match" field; the
# alignment work happens entirely on the Entra side.
_WORKDAY_SSO_TUTORIAL = (
    "https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial"
)


def _run_saml_nameid_check(runner) -> list[CheckResult]:
    """AUTH-006 implementation. Returns one CheckResult per finding."""
    cp_id = "AUTH-006"
    category = "Authentication"
    description = "SAML NameID alignment with Workday user identifier"
    doc_link = _WORKDAY_SSO_TUTORIAL

    graph = getattr(runner, "graph", None)
    if graph is None:
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=description,
            result="Microsoft Graph client unavailable — skipping.",
            remediation=(
                "Re-run FlightCheck after Graph authentication succeeds."
            ),
            doc_link=doc_link,
        )]

    # Probe /servicePrincipals with graph.get() FIRST — get_all() (which
    # get_service_principals wraps) swallows 401/403 into an empty list,
    # so a missing Application.Read.All consent would otherwise
    # masquerade as "no Workday SAML app exists" and falsely PASS the
    # check as NOT_CONFIGURED. graph.get() preserves the _status field
    # so we can distinguish "no apps" from "we can't see apps."
    sp_probe = graph.get("/servicePrincipals", params={"$top": "1"})
    if sp_probe.get("_status") in (401, 403):
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=description,
            result=(
                "Cannot read Entra service principals — Graph returned "
                f"HTTP {sp_probe['_status']} on /servicePrincipals."
            ),
            remediation=(
                "Grant Application.Read.All (or Directory.Read.All) "
                "consent on the Graph app registration the kit uses, "
                "then re-run FlightCheck. Without this consent the "
                "check cannot tell whether a Workday SAML app exists."
            ),
            doc_link=doc_link,
        )]

    try:
        workday_sps = graph.get_service_principals(filter_expr=_WORKDAY_SP_FILTER)
    except Exception as e:
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=description,
            result=f"Unable to query Entra service principals: {e}",
            remediation=(
                "Requires Application.Read.All (or Directory.Read.All) "
                "consented on the Graph app registration."
            ),
            doc_link=doc_link,
        )]

    if not workday_sps:
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=description,
            result=(
                "No federated Workday enterprise app found in Entra "
                "(filter: displayName starts with 'Workday' and SAML SSO). "
                "ESS uses ISU credentials for runtime Workday calls, "
                "so end-user SAML SSO into Workday is optional — but if "
                "your deployment includes user-context Workday flows, "
                "this means SAML SSO isn't configured."
            ),
            remediation=(
                "If you don't use SAML SSO between Entra and Workday, "
                "this check is not applicable. If you do, register the "
                "Workday enterprise app from the Entra gallery and "
                "configure SAML SSO."
            ),
            doc_link=doc_link,
        )]

    # Same trap on the per-app endpoint: get_all() on
    # /servicePrincipals/{id}/claimsMappingPolicies swallows 401/403 into
    # an empty list, which would make every detected app falsely report
    # "default NameID = userPrincipalName" when really we couldn't read
    # any override data. Probe once on the first SP and bail out as
    # WARNING if Policy.Read.All isn't consented — silently reporting
    # the wrong NameID across all N apps is exactly the
    # confidently-wrong result tier-1 of the cardinal rule forbids.
    first_sp_id = workday_sps[0].get("id", "")
    cmp_probe = graph.get(
        f"/servicePrincipals/{first_sp_id}/claimsMappingPolicies"
    )
    if cmp_probe.get("_status") in (401, 403):
        return [CheckResult(
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=description,
            result=(
                f"Found {len(workday_sps)} federated Workday SAML app(s) "
                "in Entra, but cannot read their claimsMappingPolicies — "
                f"Graph returned HTTP {cmp_probe['_status']}. NameID "
                "overrides (if any) are not visible to the kit, so "
                "AUTH-006 can't reliably surface what Entra is sending."
            ),
            remediation=(
                "Grant Policy.Read.All consent on the Graph app "
                "registration the kit uses, then re-run FlightCheck. "
                "Without this consent the check would falsely report "
                "every Workday app as using Entra's default NameID "
                "mapping even when a claimsMappingPolicy overrides it."
            ),
            doc_link=doc_link,
        )]

    # Collect per-app data first; emit ONE coalesced MANUAL result.
    # Customers often have multiple federated Workday apps (Prod,
    # Implementation, Sandbox, Preview, Training) and only one is the
    # active IdP for the Workday tenant ESS uses — the operator picks
    # which one via Workday's own SAML Identity Providers screen
    # (the join key is each app's SAML entity ID, which appears in
    # servicePrincipalNames here and as the "Service Provider ID"
    # field in Workday).
    app_entries: list[str] = []
    read_failures: list[str] = []
    for sp in workday_sps:
        sp_id = sp.get("id", "")
        sp_name = sp.get("displayName", "(unknown)")
        app_id = sp.get("appId", "?")
        entity_ids = _saml_entity_ids(sp.get("servicePrincipalNames") or [])
        entity_ids_str = ", ".join(entity_ids) if entity_ids else "(none surfaced)"

        try:
            policies = graph.get_claims_mapping_policies(sp_id)
        except Exception as e:
            read_failures.append(f"'{sp_name}': {e}")
            app_entries.append(
                f"  - {sp_name} (appId={app_id}) — entity IDs: "
                f"{entity_ids_str} — NameID = (could not read "
                f"claimsMappingPolicy; defaults to user.userPrincipalName)"
            )
            continue

        nameid = _summarize_nameid(policies)
        app_entries.append(
            f"  - {sp_name} (appId={app_id}) — entity IDs: "
            f"{entity_ids_str} — NameID = {nameid}"
        )

    intro_count = (
        "1 federated Workday SAML app"
        if len(workday_sps) == 1
        else f"{len(workday_sps)} federated Workday SAML apps"
    )
    intro_suffix = (
        ""
        if len(workday_sps) == 1
        else (
            " Only one is the active IdP for the Workday tenant "
            "ESS uses — identify it via Workday in step 1 of the "
            "remediation, then verify only that one's NameID mapping."
        )
    )

    result_text = (
        f"Found {intro_count} in Entra.{intro_suffix}\n"
        f"\n"
        f"Detected apps (display name → entity IDs → Entra NameID mapping):\n"
        + "\n".join(app_entries)
    )
    if read_failures:
        result_text += (
            "\n\nNote: claimsMappingPolicy read failed for: "
            + "; ".join(read_failures)
            + " (likely missing Policy.Read.All consent)."
        )

    return [CheckResult(
        checkpoint_id=cp_id, category=category,
        priority=Priority.HIGH.value, status=Status.MANUAL.value,
        description=description,
        result=result_text,
        remediation=(
            "Manual verification required — Workday matches the "
            "incoming SAML NameID against the Workday User Name "
            "field, and there is no Workday-side configurable "
            "mapping. The alignment lives entirely on the Entra "
            "side. ESS uses exactly one of the federated apps "
            "listed above; identify it via Workday, then verify "
            "only that app's NameID mapping.\n"
            "\n"
            "Step 1 — Identify the active Entra app from inside Workday:\n"
            "  a. Sign in to the Workday tenant ESS connects to.\n"
            "  b. In the global search box, type 'Edit Tenant Setup "
            "- Security' and open the task.\n"
            "  c. Scroll to the 'SAML Identity Providers' section. "
            "Find the row that is enabled (the 'Disabled' checkbox is "
            "unchecked) and whose 'Used for Environments' matches the "
            "environment ESS connects to.\n"
            "  d. Note that row's 'Service Provider ID' value (e.g. "
            "http://www.workday.com/contoso_prod).\n"
            "  e. Match that value to one of the 'entity IDs' in the "
            "list above — the matching row is the active Entra app. "
            "Read its NameID mapping from the same row.\n"
            "\n"
            "Step 2 — Verify NameID alignment for that one app:\n"
            "  a. Pick one ESS pilot user.\n"
            "  b. In Entra, look up that user's value for the "
            "attribute identified in step 1e (e.g. userPrincipalName, "
            "mail, employeeId). Copy the value.\n"
            "  c. In Workday, in the global search box, type 'All "
            "Workday Accounts' and open the report.\n"
            "  d. Find the row for the pilot user (use the column "
            "filter on the 'User Name' column).\n"
            "  e. Compare the 'User Name' column value to the value "
            "you copied in step 2b.\n"
            "  f. They MUST be identical (case-sensitive). If they "
            "differ, either change the Entra NameID claim mapping to "
            "send the value that equals the Workday User Name, or "
            "update the Workday User Name to match. The MS Learn "
            "Workday SSO tutorial walks through the Entra-side claim "
            "edit (step 6, 'nameidentifier' attribute mapping).\n"
            "\n"
            "If the mapping is wrong, end-user SAML SSO into Workday "
            "fails silently — ISU-credentialed runtime calls from ESS "
            "still work, so the agent appears healthy while "
            "user-context Workday flows break."
        ),
        doc_link=doc_link,
    )]


def _saml_entity_ids(service_principal_names: list[str]) -> list[str]:
    """Filter ``servicePrincipalNames`` to entries that look like a
    SAML entity ID (URI form), excluding the raw appId GUID.

    Microsoft Graph returns servicePrincipalNames as a mix of the
    application's appId GUID and one or more identifier URIs (the
    SAML entity ID for SAML apps). The Workday "Service Provider ID"
    column always carries the URI form, so the GUIDs are noise here.

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="servicePrincipal" — Property
              servicePrincipalNames (Collection(Edm.String)).
      Docs:   https://learn.microsoft.com/graph/api/resources/serviceprincipal?view=graph-rest-1.0
    """
    out: list[str] = []
    for spn in service_principal_names:
        if not isinstance(spn, str):
            continue
        # A GUID is 32 hex chars + 4 dashes = 36 chars, no scheme.
        if "://" in spn or "/" in spn or ":" in spn:
            out.append(spn)
    return out


def _summarize_nameid(policies: list[dict]) -> str:
    """Reduce a list of claimsMappingPolicies to a one-line description
    of what Entra is sending for the SAML NameID claim.

    Entra's claimsMappingPolicy.definition is a list of JSON-encoded
    strings, each containing a ClaimsMappingPolicy object with a
    ClaimsSchema array. The NameID entry has SamlClaimType
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier".
    Source for the encoding format (verbatim example response):
    https://learn.microsoft.com/graph/api/serviceprincipal-list-claimsmappingpolicies?view=graph-rest-1.0
    """
    if not policies:
        return "default (NameID = user.userPrincipalName — no custom claimsMappingPolicy assigned)"

    nameid_marker = "nameidentifier"
    findings: list[str] = []
    for pol in policies:
        for raw in pol.get("definition", []) or []:
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                continue
            schema = (
                parsed.get("ClaimsMappingPolicy", {}).get("ClaimsSchema") or []
            )
            for claim in schema:
                saml_type = (claim.get("SamlClaimType") or "").lower()
                if nameid_marker in saml_type:
                    source = claim.get("Source", "?")
                    cid = claim.get("ID", "?")
                    findings.append(
                        f"override (policy '{pol.get('displayName', '?')}': "
                        f"NameID = {source}.{cid})"
                    )

    if findings:
        return "; ".join(findings)
    # Policies exist but none override NameID specifically.
    names = ", ".join(p.get("displayName", "(unnamed)") for p in policies)
    return (
        f"default (NameID = user.userPrincipalName — "
        f"{len(policies)} claimsMappingPolicy assigned [{names}] "
        f"but none override the NameID claim)"
    )
