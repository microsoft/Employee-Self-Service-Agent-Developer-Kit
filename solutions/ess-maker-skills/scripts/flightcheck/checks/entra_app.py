# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Workday Entra App Provisioning Validation (skill-3).

Programmatic verification for the ``provision-workday-entra-app`` setup
skill. Emits the five setup checkpoints skill-3 owns, each runnable in
isolation via ``--checkpoint``:

  * ``WD-ENTRA-SCOPE-001``  — the Workday integration app exposes the
    ``user_impersonation`` API scope, pre-authorizes the Workday connector
    (``4e4707ca``), and requests the Graph delegated permissions
    ``openid`` / ``profile`` / ``User.Read``.
  * ``WD-ENTRA-CONSENT-001`` — admin consent has been granted for those
    Graph delegated permissions (an ``oauth2PermissionGrant`` exists).
  * ``WD-ASSIGN-001`` — the Workday Enterprise App requires user assignment
    and has at least one user/group assigned (or assignment is explicitly
    not required). Scoped to the operator's configured ``entraAppId`` so
    unrelated sibling Workday SSO apps in the tenant don't cause a false
    FAILED. Shares its logic with AUTH-005 via
    ``checks/_workday_app_assignment.build_assignment_results`` so the two
    checkpoints can never drift.
  * ``WD-ENTRA-NAMEID-001`` — a ``claimsMappingPolicy`` overriding the SAML
    NameID claim is assigned to the Workday service principal (degrades to
    MANUAL when the policy route is unreadable).
  * ``WD-ENTRA-SIGNOPT-001`` — the "Sign SAML response and assertion"
    signing option. Portal-only (no documented Graph property), so this
    always emits a MANUAL attestation.

Design invariants (per ``scripts/flightcheck/AGENTS.md``):
  * Never raise — every emitter is wrapped so an unexpected failure becomes
    a WARNING instead of aborting the whole run.
  * One CheckResult per checkpoint (principle 7 — coalesce multi-resource
    findings), except WD-ASSIGN-001 which delegates to the shared helper
    and may emit one row per status bucket (matching AUTH-005).
  * All checks are Entra-only (Microsoft Graph); none needs Dataverse.
"""

from ..runner import CheckResult, Priority, Role, Status
from ._saml_utils import WORKDAY_SSO_TUTORIAL_DOC, summarize_nameid
from ._workday_app_assignment import (
    build_assignment_results,
    resolve_workday_template_ids,
    _select_workday_sp,
    _workday_hints,
)

_CATEGORY = "Entra App"
_ROLES = [Role.ENTRA_ADMIN.value]
_DOC_LINK = WORKDAY_SSO_TUTORIAL_DOC

# The Workday connector's Entra appId. Skill-3 pre-authorizes THIS app on
# the Workday integration app's exposed scope (never the generic ServiceNow
# connector ``c26b24aa``). Kept lowercase so appId comparisons are
# case-insensitive against whatever Graph returns.
_WORKDAY_CONNECTOR_APP_ID = "4e4707ca-5f53-46a6-a819-f7765446e6ff"
# Microsoft Graph's well-known resource appId (stable, first-party).
_MS_GRAPH_RESOURCE_APP_ID = "00000003-0000-0000-c000-000000000000"

# The exposed delegated scope the connector calls on the integration app.
_USER_IMPERSONATION_SCOPE = "user_impersonation"

# Well-known Microsoft Graph delegated permission ids for the three scopes
# skill-3 grants. These GUIDs are stable, first-party, and documented — the
# resourceAccess entries in the app's requiredResourceAccess reference them
# by id, so we match by id rather than by name (Graph does not return the
# friendly name in requiredResourceAccess).
# Docs: https://learn.microsoft.com/graph/permissions-reference
_GRAPH_DELEGATED_SCOPE_IDS = {
    "openid": "37f7f235-527c-4136-accd-4a02d197296e",
    "profile": "14dad69e-099b-42c9-810b-d002981feec1",
    "User.Read": "e1fe6dd8-ba31-4d61-89e7-88639da4683d",
}
# The consented scope names Entra records on the oauth2PermissionGrant
# (lower-cased for a case-insensitive membership test).
_REQUIRED_CONSENT_SCOPES = {"openid", "profile", "user.read"}

_SCOPE_DESC = (
    "Workday integration app exposes user_impersonation, pre-authorizes "
    "the Workday connector, and requests the Graph delegated permissions"
)
_CONSENT_DESC = (
    "Admin consent granted for the Workday integration app's Graph "
    "delegated permissions"
)
_ASSIGN_DESC = "Workday Enterprise App user assignment"
_NAMEID_DESC = "SAML NameID claim mapping configured on the Workday app"
_SIGNOPT_DESC = (
    "Workday SAML 'Sign response and assertion' signing option (portal-only)"
)


def run_entra_app_checks(runner) -> list[CheckResult]:
    """Emit the five skill-3 Entra-app checkpoints.

    Each emitter is invoked behind a guard so a single failure degrades to
    a WARNING for that checkpoint instead of aborting the remaining checks.
    """
    graph = getattr(runner, "graph", None)
    config = getattr(runner, "config", None) or {}

    emitters = (
        (_check_scope_exposed, "WD-ENTRA-SCOPE-001", _SCOPE_DESC,
         Priority.CRITICAL.value),
        (_check_admin_consent, "WD-ENTRA-CONSENT-001", _CONSENT_DESC,
         Priority.CRITICAL.value),
        (_check_app_assignment, "WD-ASSIGN-001", _ASSIGN_DESC,
         Priority.CRITICAL.value),
        (_check_nameid_mapping, "WD-ENTRA-NAMEID-001", _NAMEID_DESC,
         Priority.HIGH.value),
        (_check_signing_option, "WD-ENTRA-SIGNOPT-001", _SIGNOPT_DESC,
         Priority.HIGH.value),
    )

    results: list[CheckResult] = []
    for fn, cp_id, description, priority in emitters:
        try:
            results.extend(fn(graph, config))
        except Exception as e:  # noqa: BLE001 — one emitter must not abort the rest
            status_code = getattr(
                getattr(e, "response", None), "status_code", None
            )
            status_hint = f" [HTTP {status_code}]" if status_code is not None else ""
            results.append(CheckResult(roles=_ROLES,
                checkpoint_id=cp_id, category=_CATEGORY,
                priority=priority, status=Status.WARNING.value,
                description=description,
                result=(
                    f"Unable to verify {cp_id}: "
                    f"{type(e).__name__}{status_hint}: {e}"
                ),
                remediation=(
                    "Inspect the error above and re-run FlightCheck. Common "
                    "causes are insufficient Graph permissions (HTTP 403) or "
                    "a transient Graph error (HTTP 5xx)."
                ),
                doc_link=_DOC_LINK,
            ))
    return results


# ─────────────────────────────────────────────────────────────────────
# Shared discovery — locate the Workday integration app + service principal.
# ─────────────────────────────────────────────────────────────────────


def _resolve_workday_app(graph, config) -> tuple[dict | None, dict | None]:
    """Return ``(application, service_principal)`` for the Workday app.

    Discovery is rename-proof: the Workday enterprise-app service principal
    is located by its gallery ``applicationTemplateId`` (the same approach
    AUTH-005 / WD-ASSIGN-001 use), then the backing ``application`` object is
    resolved by ``appId``. Config hints (``entraAppObjectId`` /
    ``entraAppId`` written by the skill-3 playbook) are honored when present
    but never required — ``entraAppId`` also disambiguates which service
    principal to validate when several share the Workday SSO template (see
    ``_select_workday_sp``). Hints come from ``runner.config`` and, as a
    fallback, the Workday connect config (see ``_workday_hints``). Returns
    ``(None, None)`` for whichever object cannot be found.
    """
    app_id_hint, obj_id_hint = _workday_hints(config)

    sp: dict | None = None
    template_ids = resolve_workday_template_ids(graph)
    if template_ids:
        clause = " or ".join(
            f"applicationTemplateId eq '{tid}'" for tid in template_ids
        )
        sps = graph.get_service_principals(filter_expr=f"({clause})")
        sp = _select_workday_sp(sps, app_id_hint)

    app_id = app_id_hint or (str(sp.get("appId", "")) if sp else "")

    application: dict | None = None
    if obj_id_hint:
        got = graph.get(f"/applications/{obj_id_hint}")
        if isinstance(got, dict) and not got.get("_error"):
            application = got
    if application is None and app_id:
        apps = graph.get_all(
            "/applications", params={"$filter": f"appId eq '{app_id}'"}
        )
        application = apps[0] if apps else None

    return application, sp


def _skipped(cp_id: str, description: str, priority: str) -> CheckResult:
    """Standard 'Graph client unavailable' SKIPPED result."""
    return CheckResult(roles=_ROLES,
        checkpoint_id=cp_id, category=_CATEGORY,
        priority=priority, status=Status.SKIPPED.value,
        description=description,
        result="Microsoft Graph client not available (auth skipped).",
        remediation="Re-run FlightCheck after Graph authentication succeeds.",
        doc_link=_DOC_LINK,
    )


def _app_not_found(cp_id: str, description: str, priority: str) -> CheckResult:
    """Standard 'Workday integration app not found' SKIPPED result."""
    return CheckResult(roles=_ROLES,
        checkpoint_id=cp_id, category=_CATEGORY,
        priority=priority, status=Status.SKIPPED.value,
        description=description,
        result=(
            "No Workday integration app registration found in this tenant "
            "(discovered via the Workday SSO gallery applicationTemplateId). "
            "The Entra app must be provisioned before this check applies."
        ),
        remediation=(
            "Run the provision-workday-entra-app setup step (or install the "
            "Workday Enterprise Application from the Entra gallery), then "
            "re-run FlightCheck. See " + _DOC_LINK
        ),
        doc_link=_DOC_LINK,
    )


# ─────────────────────────────────────────────────────────────────────
# WD-ENTRA-SCOPE-001 — scope exposed + connector pre-authorized + Graph perms.
# ─────────────────────────────────────────────────────────────────────


def _check_scope_exposed(graph, config) -> list[CheckResult]:
    cp_id = "WD-ENTRA-SCOPE-001"
    priority = Priority.CRITICAL.value
    if not graph:
        return [_skipped(cp_id, _SCOPE_DESC, priority)]

    application, _sp = _resolve_workday_app(graph, config)
    if application is None:
        return [_app_not_found(cp_id, _SCOPE_DESC, priority)]

    api = application.get("api") or {}
    scopes = api.get("oauth2PermissionScopes") or []
    has_scope = any(
        s.get("value") == _USER_IMPERSONATION_SCOPE
        and s.get("isEnabled", True)
        for s in scopes
    )

    preauth = api.get("preAuthorizedApplications") or []
    has_preauth = any(
        str(p.get("appId") or "").lower() == _WORKDAY_CONNECTOR_APP_ID
        for p in preauth
    )

    graph_access_ids: set[str] = set()
    for entry in application.get("requiredResourceAccess") or []:
        if str(entry.get("resourceAppId") or "").lower() == _MS_GRAPH_RESOURCE_APP_ID:
            for ra in entry.get("resourceAccess") or []:
                rid = ra.get("id")
                if rid:
                    graph_access_ids.add(str(rid).lower())
    missing_perms = [
        name for name, sid in _GRAPH_DELEGATED_SCOPE_IDS.items()
        if sid.lower() not in graph_access_ids
    ]

    problems: list[str] = []
    if not has_scope:
        problems.append(
            f"the '{_USER_IMPERSONATION_SCOPE}' API scope is not exposed "
            "(api.oauth2PermissionScopes)"
        )
    if not has_preauth:
        problems.append(
            f"the Workday connector ({_WORKDAY_CONNECTOR_APP_ID}) is not "
            "pre-authorized (api.preAuthorizedApplications)"
        )
    if missing_perms:
        problems.append(
            "Graph delegated permission(s) not requested: "
            + ", ".join(missing_perms)
            + " (requiredResourceAccess)"
        )

    app_label = _app_label(application)
    if problems:
        return [CheckResult(roles=_ROLES,
            checkpoint_id=cp_id, category=_CATEGORY,
            priority=priority, status=Status.FAILED.value,
            description=_SCOPE_DESC,
            result=(
                f"Workday integration app {app_label} is missing required "
                "connector configuration: " + "; ".join(problems) + "."
            ),
            remediation=(
                "Run the provision-workday-entra-app setup step (P3.1), or in "
                "the Entra portal open App registrations → this app → "
                "'Expose an API' (add the user_impersonation scope and "
                "pre-authorize the Workday connector "
                f"{_WORKDAY_CONNECTOR_APP_ID}) and 'API permissions' (add the "
                "Microsoft Graph delegated permissions openid, profile, "
                "User.Read). Then re-run this check."
            ),
            doc_link=_DOC_LINK,
        )]

    return [CheckResult(roles=_ROLES,
        checkpoint_id=cp_id, category=_CATEGORY,
        priority=priority, status=Status.PASSED.value,
        description=_SCOPE_DESC,
        result=(
            f"Workday integration app {app_label} exposes "
            f"'{_USER_IMPERSONATION_SCOPE}', pre-authorizes the Workday "
            f"connector ({_WORKDAY_CONNECTOR_APP_ID}), and requests the "
            "Graph delegated permissions openid, profile, User.Read."
        ),
        doc_link=_DOC_LINK,
    )]


# ─────────────────────────────────────────────────────────────────────
# WD-ENTRA-CONSENT-001 — admin consent granted for the Graph perms.
# ─────────────────────────────────────────────────────────────────────


def _check_admin_consent(graph, config) -> list[CheckResult]:
    cp_id = "WD-ENTRA-CONSENT-001"
    priority = Priority.CRITICAL.value
    if not graph:
        return [_skipped(cp_id, _CONSENT_DESC, priority)]

    _application, sp = _resolve_workday_app(graph, config)
    if sp is None:
        return [_app_not_found(cp_id, _CONSENT_DESC, priority)]

    sp_id = str(sp.get("id", ""))
    grants = graph.get_all(
        "/oauth2PermissionGrants",
        params={"$filter": f"clientId eq '{sp_id}'"},
    )

    # Admin consent for all users is recorded as an oauth2PermissionGrant
    # with consentType == "AllPrincipals". Aggregate the scopes across every
    # such grant (Entra may split them) and confirm the three we grant are
    # present. A user-only ("Principal") grant does NOT satisfy admin consent.
    admin_grants = [
        g for g in grants if g.get("consentType") == "AllPrincipals"
    ]
    granted_scopes: set[str] = set()
    for g in admin_grants:
        for scope in str(g.get("scope") or "").split():
            granted_scopes.add(scope.lower())
    missing = sorted(_REQUIRED_CONSENT_SCOPES - granted_scopes)

    app_label = _app_label(sp)
    if not admin_grants:
        return [CheckResult(roles=_ROLES,
            checkpoint_id=cp_id, category=_CATEGORY,
            priority=priority, status=Status.FAILED.value,
            description=_CONSENT_DESC,
            result=(
                f"No tenant-wide admin consent (oauth2PermissionGrant with "
                f"consentType 'AllPrincipals') found for {app_label}. Without "
                "admin consent the OBO/OAuth handshake fails for end users."
            ),
            remediation=(
                "Grant admin consent for the app's Graph delegated "
                "permissions (openid, profile, User.Read). Run the "
                "provision-workday-entra-app setup step (P3.2), or in the "
                "Entra portal open Enterprise applications → this app → "
                "Permissions → 'Grant admin consent for <tenant>'. This "
                "requires a consent-capable role (Application Administrator, "
                "Cloud Application Administrator, Privileged Role "
                "Administrator, or Global Administrator)."
            ),
            doc_link=_DOC_LINK,
        )]

    if missing:
        return [CheckResult(roles=_ROLES,
            checkpoint_id=cp_id, category=_CATEGORY,
            priority=priority, status=Status.FAILED.value,
            description=_CONSENT_DESC,
            result=(
                f"Admin consent exists for {app_label} but does not cover "
                "all required Graph delegated permissions — missing: "
                + ", ".join(missing) + "."
            ),
            remediation=(
                "Re-grant admin consent so the app has openid, profile, and "
                "User.Read. Run the provision-workday-entra-app setup step "
                "(P3.2) or use 'Grant admin consent' in the Entra portal."
            ),
            doc_link=_DOC_LINK,
        )]

    return [CheckResult(roles=_ROLES,
        checkpoint_id=cp_id, category=_CATEGORY,
        priority=priority, status=Status.PASSED.value,
        description=_CONSENT_DESC,
        result=(
            f"Tenant-wide admin consent granted for {app_label} covering the "
            "Graph delegated permissions openid, profile, User.Read."
        ),
        doc_link=_DOC_LINK,
    )]


# ─────────────────────────────────────────────────────────────────────
# WD-ASSIGN-001 — enterprise-app user assignment (shared with AUTH-005).
# ─────────────────────────────────────────────────────────────────────


def _check_app_assignment(graph, config) -> list[CheckResult]:
    # Delegates to the shared assessment so WD-ASSIGN-001 (S3.4 setup
    # framing) and AUTH-005 (runtime-readiness framing) never drift. See
    # checks/_workday_app_assignment.build_assignment_results. Scope to the
    # operator's configured Workday app (entraAppId) so unrelated sibling
    # Workday SSO apps in the tenant don't drive a false FAILED.
    app_id_hint, _obj_id_hint = _workday_hints(config)
    return build_assignment_results(
        graph,
        cp_id="WD-ASSIGN-001",
        category=_CATEGORY,
        description=_ASSIGN_DESC,
        priority=Priority.CRITICAL.value,
        doc_link=_DOC_LINK,
        roles=_ROLES,
        app_id_hint=app_id_hint,
    )


# ─────────────────────────────────────────────────────────────────────
# WD-ENTRA-NAMEID-001 — SAML NameID claim mapping (claimsMappingPolicy).
# ─────────────────────────────────────────────────────────────────────


def _check_nameid_mapping(graph, config) -> list[CheckResult]:
    cp_id = "WD-ENTRA-NAMEID-001"
    priority = Priority.HIGH.value
    if not graph:
        return [_skipped(cp_id, _NAMEID_DESC, priority)]

    _application, sp = _resolve_workday_app(graph, config)
    if sp is None:
        return [_app_not_found(cp_id, _NAMEID_DESC, priority)]

    sp_id = str(sp.get("id", ""))
    app_label = _app_label(sp)

    # Probe readability first. get_claims_mapping_policies() (get_all) would
    # silently swallow a 401/403 into an empty list, which would masquerade
    # as "no policy assigned → default UPN" and produce a confidently-wrong
    # FAILED. Degrade to MANUAL instead when we cannot read the policy route.
    probe = graph.get(f"/servicePrincipals/{sp_id}/claimsMappingPolicies")
    if isinstance(probe, dict) and probe.get("_status") in (401, 403):
        return [CheckResult(roles=_ROLES,
            checkpoint_id=cp_id, category=_CATEGORY,
            priority=priority, status=Status.MANUAL.value,
            description=_NAMEID_DESC,
            result=(
                f"Cannot read claimsMappingPolicies for {app_label} — Graph "
                f"returned HTTP {probe['_status']}. The NameID mapping cannot "
                "be verified programmatically, so it must be confirmed "
                "manually in the Entra portal."
            ),
            remediation=(
                "Either grant Policy.Read.All consent on the Graph app "
                "registration the kit uses and re-run this check, or verify "
                "manually: Entra portal → Enterprise applications → this app "
                "→ Single sign-on → Attributes & Claims → confirm the Unique "
                "User Identifier (Name ID) claim maps to the attribute that "
                "equals the Workday User Name."
            ),
            doc_link=_DOC_LINK,
        )]

    policies = graph.get_claims_mapping_policies(sp_id)
    nameid = summarize_nameid(policies)
    has_override = bool(policies) and "override" in nameid.lower()

    if has_override:
        return [CheckResult(roles=_ROLES,
            checkpoint_id=cp_id, category=_CATEGORY,
            priority=priority, status=Status.PASSED.value,
            description=_NAMEID_DESC,
            result=(
                f"A claimsMappingPolicy overriding the SAML NameID claim is "
                f"assigned to {app_label}: {nameid}."
            ),
            doc_link=_DOC_LINK,
        )]

    return [CheckResult(roles=_ROLES,
        checkpoint_id=cp_id, category=_CATEGORY,
        priority=priority, status=Status.FAILED.value,
        description=_NAMEID_DESC,
        result=(
            f"No claimsMappingPolicy overriding the SAML NameID claim is "
            f"assigned to {app_label} — Entra sends {nameid}. Skill-3 "
            "provisions an explicit NameID mapping so the value Workday "
            "receives matches the Workday User Name."
        ),
        remediation=(
            "Run the provision-workday-entra-app setup step (P3.5) to create "
            "and assign a claimsMappingPolicy mapping the Name ID to the "
            "attribute that equals the Workday User Name (typically "
            "user.mail or user.userPrincipalName). If your tenant "
            "deliberately relies on the default userPrincipalName NameID and "
            "it already equals the Workday User Name, this can be attested "
            "manually instead."
        ),
        doc_link=_DOC_LINK,
    )]


# ─────────────────────────────────────────────────────────────────────
# WD-ENTRA-SIGNOPT-001 — SAML signing option (portal-only, always MANUAL).
# ─────────────────────────────────────────────────────────────────────


def _entra_idp_endpoints(config) -> dict:
    """Derive the customer's Entra SAML IdP identifiers from captured config.

    In this federation Entra is the SAML IdP and Workday is the SP, so the
    values Workday's SP configuration must trust are deterministic from the
    Entra tenant id (issuer / login) and the app id (audience / federation
    metadata) — no Graph call needed. Any field the config hasn't captured
    yet is omitted so callers can degrade to generic guidance.
    Docs: https://learn.microsoft.com/entra/identity-platform/single-sign-on-saml-protocol
    """
    cfg = config or {}
    tenant_id = cfg.get("tenantId")
    entra_app_id = cfg.get("entraAppId")
    out: dict = {}
    if cfg.get("tenant"):
        out["workday_tenant"] = cfg["tenant"]
    if tenant_id:
        out["issuer"] = f"https://sts.windows.net/{tenant_id}/"
        out["login_url"] = (
            f"https://login.microsoftonline.com/{tenant_id}/saml2"
        )
        if entra_app_id:
            out["metadata_url"] = (
                f"https://login.microsoftonline.com/{tenant_id}"
                "/federationmetadata/2007-06/federationmetadata.xml"
                f"?appid={entra_app_id}"
            )
    if entra_app_id:
        out["audience"] = f"api://{entra_app_id}"
    return out


def _check_signing_option(graph, config) -> list[CheckResult]:
    # Portal-only: there is no documented Graph property for the "Sign SAML
    # response and assertion" signing option (the beta samlSingleSignOnSettings
    # resource exposes only relayState), so this always emits a MANUAL
    # attestation. clients=frozenset() in the registry — needs no auth.
    #
    # The signing-option VALUE stays a fixed target, but we personalize the
    # remediation with the customer's own IdP identifiers (derived from
    # config, no Graph call) so the attestation names the concrete values
    # Workday must trust instead of generic guidance.
    idp = _entra_idp_endpoints(config)
    remediation = (
        "Verify in the Entra portal: Enterprise applications → the "
        "Workday app → Single sign-on → SAML Signing Certificate → Edit "
        "→ set 'Signing Option' to 'Sign SAML response and assertion'. "
        "Confirm it matches what the Workday tenant's SAML IdP "
        "configuration expects, then re-run the setup step to record the "
        "attestation."
    )
    facts = []
    if idp.get("issuer"):
        facts.append(f"IdP Issuer/Entity ID {idp['issuer']}")
    if idp.get("login_url"):
        facts.append(f"SSO/Login URL {idp['login_url']}")
    if idp.get("audience"):
        facts.append(f"SP audience (Identifier) {idp['audience']}")
    if idp.get("metadata_url"):
        facts.append(f"federation metadata {idp['metadata_url']}")
    if facts:
        lead = (
            f"For your Workday tenant '{idp['workday_tenant']}', the "
            if idp.get("workday_tenant")
            else "The "
        )
        remediation += (
            " " + lead + "Entra SAML IdP values Workday must trust are: "
            + "; ".join(facts) + "."
        )

    return [CheckResult(roles=_ROLES,
        checkpoint_id="WD-ENTRA-SIGNOPT-001", category=_CATEGORY,
        priority=Priority.HIGH.value, status=Status.MANUAL.value,
        description=_SIGNOPT_DESC,
        result=(
            "The Workday SAML 'Sign SAML response and assertion' signing "
            "option is portal-only — Microsoft Graph exposes no property for "
            "it, so the kit cannot verify it programmatically. A Workday "
            "service provider that validates signatures rejects the "
            "assertion if this is set wrong, so it must not be skipped."
        ),
        remediation=remediation,
        doc_link=_DOC_LINK,
    )]


def _app_label(obj: dict) -> str:
    """Render a short ``'DisplayName' (appId=…)`` label for result text."""
    name = obj.get("displayName") or "(unnamed)"
    app_id = obj.get("appId")
    return f"'{name}' (appId={app_id})" if app_id else f"'{name}'"
