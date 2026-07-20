# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Authentication & Identity Validation (AUTH-xxx)

Checks Entra ID configuration, SSO, Conditional Access, user sync.
"""

from ..runner import CheckResult, Priority, Role, Status
from ._saml_utils import (
    WORKDAY_SAML_SP_FILTER,
    WORKDAY_SSO_TUTORIAL_DOC,
    saml_entity_ids,
    summarize_nameid,
)
from ._workday_app_assignment import build_assignment_results, _workday_hints

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"


def run_authentication_checks(runner) -> list[CheckResult]:
    """Execute all authentication checks using the Graph client."""
    graph = runner.graph
    results: list[CheckResult] = []

    # ---- AUTH-001: Entra ID configured ----
    try:
        org = graph.get_organization()
        if org and "displayName" in org:
            results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
                checkpoint_id="AUTH-001", category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Microsoft Entra ID configured",
                result=f"Tenant: {org['displayName']} ({org.get('id', 'N/A')})",
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
        else:
            results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
                checkpoint_id="AUTH-001", category="Authentication",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Microsoft Entra ID configured",
                result="Unable to retrieve organization info",
                remediation="Ensure Entra ID is properly configured.",
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
    except Exception as e:
        results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
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
            results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
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
            results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
                checkpoint_id="AUTH-002", category="Authentication",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="Conditional Access policies",
                result="No Conditional Access policies found",
                remediation="Configure SSO and CA policies for enhanced security.",
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
    except Exception as e:
        results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
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
            results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
                checkpoint_id="AUTH-004", category="Authentication",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description="User identity synchronization",
                result=f"Verified: {len(users)} sample users found in Entra ID",
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
        else:
            results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
                checkpoint_id="AUTH-004", category="Authentication",
                priority=Priority.HIGH.value, status=Status.FAILED.value,
                description="User identity synchronization",
                result="No users found in Entra ID",
                remediation="Ensure user sync is configured and working.",
                doc_link=f"{DOC_BASE}/prerequisites#identity-authentication-and-single-sign-on-sso",
            ))
    except Exception as e:
        results.append(CheckResult(roles=[Role.ENTRA_ADMIN.value],
            checkpoint_id="AUTH-004", category="Authentication",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="User identity sync",
            result=f"Unable to check: {e}",
        ))

    # ---- AUTH-005: Workday Enterprise App user assignment ----
    # Scope to the operator's configured Workday app (entraAppId) — like
    # WD-ASSIGN-001, which shares build_assignment_results — so unrelated
    # sibling Workday SSO apps in the tenant don't drive a false FAILED.
    _auth005_app_id_hint, _ = _workday_hints(getattr(runner, "config", None))
    results.extend(
        _check_workday_app_user_assignment(graph, _auth005_app_id_hint)
    )

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


def _check_workday_app_user_assignment(graph, app_id_hint: str = "") -> list[CheckResult]:
    """AUTH-005: Verify the Workday Enterprise App requires user assignment
    AND has at least one user/group assigned.

    Delegates to the shared assessment in
    ``checks/_workday_app_assignment.build_assignment_results`` so this
    runtime-readiness checkpoint and the S3.4 setup checkpoint
    (``WD-ASSIGN-001``) can never drift. See that module for the full
    validation logic (issue #79). ``app_id_hint`` (the configured
    ``entraAppId``) scopes the assessment to the operator's Workday app.
    """
    return build_assignment_results(
        graph,
        cp_id="AUTH-005",
        category="Authentication",
        description="Workday Enterprise App user assignment",
        priority=Priority.CRITICAL.value,
        doc_link=(
            f"{DOC_BASE}/prerequisites"
            "#identity-authentication-and-single-sign-on-sso"
        ),
        roles=[Role.ENTRA_ADMIN.value],
        app_id_hint=app_id_hint,
    )


# ─────────────────────────────────────────────────────────────────────
# AUTH-006 — SAML NameID alignment (Entra side automated, Workday
# side MANUAL).
# ─────────────────────────────────────────────────────────────────────


# Most production tenants name the federated app starting with "Workday"
# (e.g. "Workday", "Workday Prod", "Workday Implementation"). The SAML
# SP filter and the Workday SSO tutorial URL live in
# ``checks/_saml_utils`` so AUTH-006 and WD-CONN-010 stay in sync.


def _run_saml_nameid_check(runner) -> list[CheckResult]:
    """AUTH-006 implementation. Returns one CheckResult per finding."""
    cp_id = "AUTH-006"
    category = "Authentication"
    description = "SAML NameID alignment with Workday user identifier"
    doc_link = WORKDAY_SSO_TUTORIAL_DOC

    graph = getattr(runner, "graph", None)
    if graph is None:
        return [CheckResult(roles=[Role.ENTRA_ADMIN.value],
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=description,
            result="Microsoft Graph client unavailable — skipping.",
            remediation=(
                "Re-run FlightCheck after Graph authentication succeeds."
            ),
            doc_link=doc_link,
        )]

    # Filtered /servicePrincipals call with raise_on_permission_error=True
    # so a missing Application.Read.All consent surfaces as
    # PermissionError → WARNING instead of get_all()'s default
    # silent-empty-list (which would masquerade as "no Workday SAML app
    # exists" and falsely PASS the check as NOT_CONFIGURED). Uses the
    # same plumbing as get_app_role_assignments (AUTH-005) — see
    # graph_client.get_all() raise_on_permission_error kwarg.
    try:
        workday_sps = graph.get_service_principals(
            filter_expr=WORKDAY_SAML_SP_FILTER,
            raise_on_permission_error=True,
        )
    except PermissionError as e:
        return [CheckResult(roles=[Role.ENTRA_ADMIN.value],
            checkpoint_id=cp_id, category=category,
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=description,
            result=(
                f"Cannot read Entra service principals: {e} "
                "(HTTP 403 typically means Application.Read.All "
                "is not consented)."
            ),
            remediation=(
                "Grant Application.Read.All (or Directory.Read.All) "
                "consent on the Graph app registration the kit uses, "
                "then re-run FlightCheck. Without this consent the "
                "check cannot tell whether a Workday SAML app exists."
            ),
            doc_link=doc_link,
        )]
    except Exception as e:
        return [CheckResult(roles=[Role.ENTRA_ADMIN.value],
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
        return [CheckResult(roles=[Role.ENTRA_ADMIN.value],
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
        return [CheckResult(roles=[Role.ENTRA_ADMIN.value],
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
        entity_ids = saml_entity_ids(sp.get("servicePrincipalNames") or [])
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

        nameid = summarize_nameid(policies)
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

    return [CheckResult(roles=[Role.ENTRA_ADMIN.value],
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
