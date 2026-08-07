# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ServiceNow Entra App Provisioning Validation (setup skills 4/5).

Programmatic, Microsoft-Graph-only verification for the ServiceNow setup
orchestrator's Entra-side steps. Emits three checkpoints, each runnable in
isolation via ``--checkpoint``:

  * ``SN-ENTRA-SCOPE-001`` (S4.1) — the ServiceNow sign-in app (user path)
    exposes the ``user_impersonation`` API scope, pre-authorizes the Power
    Platform **ServiceNow** connector (``c26b24aa``) on that scope, and
    requests the Graph delegated permissions ``openid`` / ``profile`` /
    ``User.Read``.
  * ``SN-ENTRA-CONSENT-001`` (S4.2) — tenant-wide admin consent
    (an ``oauth2PermissionGrant`` with ``consentType == 'AllPrincipals'``)
    covering those three delegated permissions.
  * ``SN-ENTRA-CERT-001`` (S5.1/S5.2) — the ServiceNow service-account app
    (certificate path, "App B") holds a non-expired ``AsymmetricX509Cert``
    key credential, matching the recorded thumbprint when one is captured.

Unlike Workday (whose enterprise app comes from the Entra gallery and is
discovered by ``applicationTemplateId``), the ServiceNow apps are **custom
registrations** created by the setup playbooks. There is no gallery template
to discover them by, so resolution is driven entirely by the identifiers the
playbooks persist to ``.local/connect/servicenow/config.json``
(``entra.*`` for the user path, ``certificate.*`` for the certificate path).
When those hints are absent the checks degrade to SKIPPED — the Entra app has
not been provisioned yet — never a silent pass.

Design invariants (per ``scripts/flightcheck/AGENTS.md``):
  * Never raise — every emitter is wrapped so an unexpected failure becomes a
    WARNING for that checkpoint instead of aborting the rest.
  * One CheckResult per checkpoint (principle 7 — coalesce multi-resource
    findings).
  * All checks are Entra-only (Microsoft Graph); none needs Dataverse or a
    live ServiceNow tenant.
  * These checks NEVER touch ServiceNow-internal OIDC (provider registration,
    system user, claim mapping) — the spec forbids automating those, so they
    remain attestation rows owned by the playbooks (S4.3/S4.4/S5.3).
"""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone

from ..runner import CheckResult, Priority, Role, Status

_CATEGORY = "ServiceNow Entra App"
_ROLES = [Role.ENTRA_ADMIN.value]
_DOC_LINK = (
    "https://learn.microsoft.com/en-us/copilot/microsoft-365/"
    "employee-self-service"
)

# The Power Platform ServiceNow connector's Entra appId. The ServiceNow sign-in
# app pre-authorizes THIS app on its exposed scope (never the Workday connector
# ``4e4707ca``). Lowercase so appId comparisons are case-insensitive.
_SERVICENOW_CONNECTOR_APP_ID = "c26b24aa-7874-4e06-ad55-7d06b1f79b63"
# Microsoft Graph's well-known first-party resource appId (stable).
_MS_GRAPH_RESOURCE_APP_ID = "00000003-0000-0000-c000-000000000000"

_USER_IMPERSONATION_SCOPE = "user_impersonation"

# Well-known Microsoft Graph delegated permission ids for the three scopes the
# ServiceNow user path grants (same GUIDs the playbook PATCHes — matched by id
# because Graph does not return the friendly name in requiredResourceAccess).
# Docs: https://learn.microsoft.com/graph/permissions-reference
_GRAPH_DELEGATED_SCOPE_IDS = {
    "openid": "37f7f235-527c-4136-accd-4a02d197296e",
    "profile": "14dad69e-099b-42c9-810b-d002981feec1",
    "User.Read": "e1fe6dd8-ba31-4d61-89e7-88639da4683d",
}
# The consented scope names Entra records on the oauth2PermissionGrant
# (lower-cased for a case-insensitive membership test).
_REQUIRED_CONSENT_SCOPES = {"openid", "profile", "user.read"}

_CONNECT_CONFIG_PATH = os.path.join(
    ".local", "connect", "servicenow", "config.json"
)

_SCOPE_DESC = (
    "ServiceNow sign-in app exposes user_impersonation, pre-authorizes the "
    "Power Platform ServiceNow connector, and requests the Graph delegated "
    "permissions"
)
_CONSENT_DESC = (
    "Admin consent granted for the ServiceNow sign-in app's Graph delegated "
    "permissions"
)
_CERT_DESC = (
    "ServiceNow service-account app holds a valid certificate credential"
)


# ─────────────────────────────────────────────────────────────────────
# Public entry point.
# ─────────────────────────────────────────────────────────────────────


def run_servicenow_entra_checks(runner) -> list[CheckResult]:
    """Emit the three ServiceNow Entra-app checkpoints (setup skills 4/5).

    Each emitter is invoked behind a guard so a single failure degrades to a
    WARNING for that checkpoint instead of aborting the remaining checks.
    """
    graph = getattr(runner, "graph", None)
    config = getattr(runner, "config", None) or {}

    emitters = (
        (_check_scope_exposed, "SN-ENTRA-SCOPE-001", _SCOPE_DESC,
         Priority.CRITICAL.value),
        (_check_admin_consent, "SN-ENTRA-CONSENT-001", _CONSENT_DESC,
         Priority.CRITICAL.value),
        (_check_certificate, "SN-ENTRA-CERT-001", _CERT_DESC,
         Priority.CRITICAL.value),
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
# Config-hint reading + app discovery.
# ─────────────────────────────────────────────────────────────────────


def _load_connect_config() -> dict:
    """Read ``.local/connect/servicenow/config.json`` (the durable ServiceNow
    setup config). Any read/parse error yields ``{}`` — emitters never raise."""
    try:
        with open(_CONNECT_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — missing/invalid config → no hints
        return {}


def _merged_section(config, section: str) -> dict:
    """Merge ``config[section]`` (the runner's ``.local/config.json``) over the
    ServiceNow connect config's ``[section]``. The connect config is the real
    source for ServiceNow fields; ``runner.config`` values win when present."""
    connect = _load_connect_config().get(section) or {}
    live = (config or {}).get(section) or {}
    merged = dict(connect) if isinstance(connect, dict) else {}
    if isinstance(live, dict):
        merged.update({k: v for k, v in live.items() if v})
    return merged


def _user_app_hints(config) -> tuple[str, str]:
    """Return ``(appId, objectId)`` for the ServiceNow user-path sign-in app."""
    entra = _merged_section(config, "entra")
    app_id = str(entra.get("appId") or entra.get("appClientId") or "").strip()
    obj_id = str(entra.get("objectId") or entra.get("appObjectId") or "").strip()
    return app_id, obj_id


def _cert_app_hints(config) -> tuple[str, str, str]:
    """Return ``(appBClientId, appBObjectId, certThumbprint)`` for the
    certificate-path service-account app (App B, which holds the cert)."""
    cert = _merged_section(config, "certificate")
    app_id = str(cert.get("appBClientId") or "").strip()
    obj_id = str(cert.get("appBObjectId") or "").strip()
    thumb = str(cert.get("certThumbprint") or "").strip()
    return app_id, obj_id, thumb


def _resolve_application(graph, app_id: str, obj_id: str) -> dict | None:
    """Resolve an ``application`` object from an object-id or appId hint.

    A direct object-id GET raises on HTTP 404 (the app was deleted or the
    recorded id is stale); that is swallowed so resolution falls through to the
    appId ``$filter`` and, failing that, reports app-not-found (SKIPPED) rather
    than erroring."""
    application: dict | None = None
    if obj_id:
        try:
            got = graph.get(f"/applications/{obj_id}")
            if isinstance(got, dict) and not got.get("_error"):
                application = got
        except Exception:  # noqa: BLE001 — 404/stale id → try the appId filter
            application = None
    if application is None and app_id:
        apps = graph.get_all(
            "/applications", params={"$filter": f"appId eq '{app_id}'"}
        )
        application = apps[0] if apps else None
    return application


def _resolve_service_principal(graph, app_id: str) -> dict | None:
    """Resolve the ``servicePrincipal`` for an appId (enterprise-app object)."""
    if not app_id:
        return None
    sps = graph.get_service_principals(filter_expr=f"appId eq '{app_id}'")
    return sps[0] if sps else None


def _skipped(cp_id: str, description: str, priority: str, result: str,
             remediation: str) -> CheckResult:
    return CheckResult(roles=_ROLES,
        checkpoint_id=cp_id, category=_CATEGORY,
        priority=priority, status=Status.SKIPPED.value,
        description=description, result=result, remediation=remediation,
        doc_link=_DOC_LINK,
    )


def _graph_unavailable(cp_id, description, priority) -> CheckResult:
    return _skipped(
        cp_id, description, priority,
        "Microsoft Graph client not available (auth skipped).",
        "Re-run FlightCheck after Graph authentication succeeds.",
    )


def _no_config(cp_id, description, priority, step: str) -> CheckResult:
    return _skipped(
        cp_id, description, priority,
        "No ServiceNow Entra app identifiers found in "
        ".local/connect/servicenow/config.json. The app has not been "
        "provisioned yet, so there is nothing to verify.",
        f"Run the ServiceNow setup step {step} to register the Entra app, "
        "then re-run this check.",
    )


def _app_not_found(cp_id, description, priority, label: str, step: str) -> CheckResult:
    return _skipped(
        cp_id, description, priority,
        f"The configured {label} was not found in this tenant (looked it up "
        "by the identifiers in .local/connect/servicenow/config.json).",
        f"Confirm the app exists (run ServiceNow setup step {step}) or fix the "
        "recorded identifiers, then re-run this check.",
    )


def _app_label(obj: dict) -> str:
    name = obj.get("displayName") or "(unnamed)"
    return f"'{name}' (appId={obj.get('appId', '?')})"


# ─────────────────────────────────────────────────────────────────────
# SN-ENTRA-SCOPE-001 — scope exposed + connector pre-auth + Graph perms.
# ─────────────────────────────────────────────────────────────────────


def _check_scope_exposed(graph, config) -> list[CheckResult]:
    cp_id = "SN-ENTRA-SCOPE-001"
    priority = Priority.CRITICAL.value
    if not graph:
        return [_graph_unavailable(cp_id, _SCOPE_DESC, priority)]

    app_id, obj_id = _user_app_hints(config)
    if not app_id and not obj_id:
        return [_no_config(cp_id, _SCOPE_DESC, priority, "S4.1")]

    application = _resolve_application(graph, app_id, obj_id)
    if application is None:
        return [_app_not_found(
            cp_id, _SCOPE_DESC, priority, "ServiceNow sign-in app", "S4.1")]

    api = application.get("api") or {}
    scopes = api.get("oauth2PermissionScopes") or []
    has_scope = any(
        s.get("value") == _USER_IMPERSONATION_SCOPE and s.get("isEnabled", True)
        for s in scopes
    )

    preauth = api.get("preAuthorizedApplications") or []
    has_preauth = any(
        str(p.get("appId") or "").lower() == _SERVICENOW_CONNECTOR_APP_ID
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
            f"the ServiceNow connector ({_SERVICENOW_CONNECTOR_APP_ID}) is not "
            "pre-authorized (api.preAuthorizedApplications)"
        )
    if missing_perms:
        problems.append(
            "Graph delegated permission(s) not requested: "
            + ", ".join(missing_perms) + " (requiredResourceAccess)"
        )

    app_label = _app_label(application)
    if problems:
        return [CheckResult(roles=_ROLES,
            checkpoint_id=cp_id, category=_CATEGORY,
            priority=priority, status=Status.FAILED.value,
            description=_SCOPE_DESC,
            result=(
                f"ServiceNow sign-in app {app_label} is missing required "
                "connector configuration: " + "; ".join(problems) + "."
            ),
            remediation=(
                "Run the provision-servicenow-entra-user setup step (S4.1), or "
                "in the Entra portal open App registrations → this app → "
                "'Expose an API' (add the user_impersonation scope and "
                "pre-authorize the ServiceNow connector "
                f"{_SERVICENOW_CONNECTOR_APP_ID}) and 'API permissions' (add "
                "the Microsoft Graph delegated permissions openid, profile, "
                "User.Read). Then re-run this check."
            ),
            doc_link=_DOC_LINK,
        )]

    return [CheckResult(roles=_ROLES,
        checkpoint_id=cp_id, category=_CATEGORY,
        priority=priority, status=Status.PASSED.value,
        description=_SCOPE_DESC,
        result=(
            f"ServiceNow sign-in app {app_label} exposes "
            f"'{_USER_IMPERSONATION_SCOPE}', pre-authorizes the ServiceNow "
            f"connector ({_SERVICENOW_CONNECTOR_APP_ID}), and requests the "
            "Graph delegated permissions openid, profile, User.Read."
        ),
        doc_link=_DOC_LINK,
    )]


# ─────────────────────────────────────────────────────────────────────
# SN-ENTRA-CONSENT-001 — admin consent granted for the Graph perms.
# ─────────────────────────────────────────────────────────────────────


def _check_admin_consent(graph, config) -> list[CheckResult]:
    cp_id = "SN-ENTRA-CONSENT-001"
    priority = Priority.CRITICAL.value
    if not graph:
        return [_graph_unavailable(cp_id, _CONSENT_DESC, priority)]

    app_id, _obj_id = _user_app_hints(config)
    if not app_id:
        return [_no_config(cp_id, _CONSENT_DESC, priority, "S4.1")]

    sp = _resolve_service_principal(graph, app_id)
    if sp is None:
        return [_app_not_found(
            cp_id, _CONSENT_DESC, priority,
            "ServiceNow sign-in enterprise application", "S4.1")]

    sp_id = str(sp.get("id", ""))
    grants = graph.get_all(
        "/oauth2PermissionGrants",
        params={"$filter": f"clientId eq '{sp_id}'"},
    )

    # Admin consent for all users is recorded as an oauth2PermissionGrant with
    # consentType == "AllPrincipals". Aggregate scopes across every such grant
    # (Entra may split them). A user-only ("Principal") grant does NOT satisfy
    # admin consent.
    admin_grants = [g for g in grants if g.get("consentType") == "AllPrincipals"]
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
                "No tenant-wide admin consent (oauth2PermissionGrant with "
                f"consentType 'AllPrincipals') found for {app_label}. Without "
                "admin consent the OBO/OAuth handshake fails for end users."
            ),
            remediation=(
                "Grant admin consent for the app's Graph delegated permissions "
                "(openid, profile, User.Read). Run the "
                "provision-servicenow-entra-user setup step (S4.2), or in the "
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
                f"Admin consent exists for {app_label} but does not cover all "
                "required Graph delegated permissions — missing: "
                + ", ".join(missing) + "."
            ),
            remediation=(
                "Re-grant admin consent so the app has openid, profile, and "
                "User.Read. Run the provision-servicenow-entra-user setup step "
                "(S4.2) or use 'Grant admin consent' in the Entra portal."
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
# SN-ENTRA-CERT-001 — certificate credential on the service-account app.
# ─────────────────────────────────────────────────────────────────────


def _key_credential_thumbprint(cred: dict) -> str:
    """Return the uppercase hex SHA-1 thumbprint for a keyCredential, derived
    from its base64 ``customKeyIdentifier``. Empty string if not decodable."""
    cki = cred.get("customKeyIdentifier")
    if not cki:
        return ""
    try:
        return base64.b64decode(cki).hex().upper()
    except Exception:  # noqa: BLE001 — malformed identifier → no thumbprint
        return ""


def _is_expired(cred: dict, now: datetime) -> bool:
    end = cred.get("endDateTime")
    if not end:
        return False
    try:
        parsed = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed < now
    except Exception:  # noqa: BLE001 — unparseable date → treat as not-expired
        return False


def _check_certificate(graph, config) -> list[CheckResult]:
    cp_id = "SN-ENTRA-CERT-001"
    priority = Priority.CRITICAL.value
    if not graph:
        return [_graph_unavailable(cp_id, _CERT_DESC, priority)]

    app_id, obj_id, thumbprint = _cert_app_hints(config)
    if not app_id and not obj_id:
        return [_no_config(cp_id, _CERT_DESC, priority, "S5.1")]

    application = _resolve_application(graph, app_id, obj_id)
    if application is None:
        return [_app_not_found(
            cp_id, _CERT_DESC, priority,
            "ServiceNow service-account app (certificate path)", "S5.1")]

    app_label = _app_label(application)
    all_creds = application.get("keyCredentials") or []
    x509 = [
        c for c in all_creds
        if str(c.get("type") or "") == "AsymmetricX509Cert"
    ]

    if not x509:
        return [CheckResult(roles=_ROLES,
            checkpoint_id=cp_id, category=_CATEGORY,
            priority=priority, status=Status.FAILED.value,
            description=_CERT_DESC,
            result=(
                f"ServiceNow service-account app {app_label} has no "
                "certificate (AsymmetricX509Cert) key credential. The "
                "certificate sign-in path cannot authenticate without it."
            ),
            remediation=(
                "Upload the public signing certificate (.cer) to the app's "
                "keyCredentials. Run the provision-servicenow-certificate "
                "setup step (S5.2), or in the Entra portal open App "
                "registrations → this app → Certificates & secrets → "
                "Certificates → Upload certificate. Then re-run this check."
            ),
            doc_link=_DOC_LINK,
        )]

    now = datetime.now(timezone.utc)
    valid = [c for c in x509 if not _is_expired(c, now)]
    if not valid:
        return [CheckResult(roles=_ROLES,
            checkpoint_id=cp_id, category=_CATEGORY,
            priority=priority, status=Status.FAILED.value,
            description=_CERT_DESC,
            result=(
                f"ServiceNow service-account app {app_label} has "
                f"{len(x509)} certificate credential(s) but all are expired."
            ),
            remediation=(
                "Upload a current signing certificate and remove the expired "
                "one. Run the provision-servicenow-certificate setup step "
                "(S5.2) or use the Entra portal. Then re-run this check."
            ),
            doc_link=_DOC_LINK,
        )]

    # Cross-check the recorded thumbprint (if the playbook captured one) against
    # the uploaded credentials. A mismatch is a WARNING, not a FAILED — a valid
    # cert IS present; it just isn't the one the setup config recorded.
    if thumbprint:
        recorded = thumbprint.replace(":", "").upper()
        found = {_key_credential_thumbprint(c) for c in valid}
        found.discard("")
        if found and recorded not in found:
            return [CheckResult(roles=_ROLES,
                checkpoint_id=cp_id, category=_CATEGORY,
                priority=priority, status=Status.WARNING.value,
                description=_CERT_DESC,
                result=(
                    f"ServiceNow service-account app {app_label} has a valid "
                    "certificate credential, but none matches the thumbprint "
                    f"recorded in config ({recorded}). Uploaded thumbprint(s): "
                    + ", ".join(sorted(found)) + "."
                ),
                remediation=(
                    "Confirm the correct signing certificate is uploaded, or "
                    "update certificate.certThumbprint in "
                    ".local/connect/servicenow/config.json to match the "
                    "uploaded credential. Re-run the provision-servicenow-"
                    "certificate setup step (S5.2) if the wrong cert is in "
                    "place."
                ),
                doc_link=_DOC_LINK,
            )]

    return [CheckResult(roles=_ROLES,
        checkpoint_id=cp_id, category=_CATEGORY,
        priority=priority, status=Status.PASSED.value,
        description=_CERT_DESC,
        result=(
            f"ServiceNow service-account app {app_label} holds a valid "
            f"certificate credential ({len(valid)} non-expired "
            "AsymmetricX509Cert)."
        ),
        doc_link=_DOC_LINK,
    )]
