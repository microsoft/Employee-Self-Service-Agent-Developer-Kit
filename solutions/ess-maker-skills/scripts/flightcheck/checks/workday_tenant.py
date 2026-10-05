# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Workday Tenant Configuration Validation (skill-4).

Programmatic attestation for the ``configure-workday-tenant`` setup skill.
Emits the two setup checkpoints skill-4 owns, each runnable in isolation
via ``--checkpoint``:

  * ``WD-API-CLIENT-001`` — the Workday API client is registered (Client
    Grant Type = SAML ******; functional areas Core Payroll, Organizations
    and Roles, Staffing, Time Off and Leave; Include Workday Owned Scope =
    Yes, required for the REST ``/workers/me`` call). Echoes the captured
    ``oauthClientId`` / ``tokenEndpoint``.
  * ``WD-TENANT-001`` — Tenant Setup - Security is configured (redirect URL
    set; OAuth 2.0 Clients + SAML enabled; SAML Service Provider ID matches
    the exact Workday SAML entity ID) AND an active authentication rule allows
    SAML for
    the intended employee population. Echoes the captured ``restBaseUrl`` /
    ``soapBaseUrl`` / ``tenant`` / ``workdaySamlEntityId``.

Design invariants (per ``scripts/flightcheck/AGENTS.md``):
  * **Always MANUAL.** Workday exposes no queryable admin API the kit can
    reach, and standing up a Workday connection to self-verify would be
    circular (it needs the same Entra-app + tenant config the ESS agent
    itself needs). So both checkpoints emit MANUAL attestations — they echo
    whatever the operator captured into the provider config explicitly merged
    into ``runner.config`` and name the exact Workday admin screen to verify.
    A MANUAL row never fails readiness and never auto-completes an attest row.
  * **Never raise** — the dispatcher wraps every emitter so an unexpected
    failure degrades to a WARNING for that checkpoint instead of aborting
    the whole run.
  * **Pure-logic** — reads ``runner.config`` only; no HTTP, no client. Both
    registry specs declare ``clients=frozenset()`` (mirrors
    ``WD-ENTRA-SIGNOPT-001``), so no cassette/mock tier is required.
  * **One CheckResult per checkpoint** (principle 7).
  * The S4.4 signing-cert thumbprint parity is **not** minted here — it
    reuses ``WD-CONN-102`` from ``checks/workday.py``.
"""

from ..runner import CheckResult, Priority, Role, Status

_CATEGORY = "Workday Tenant"
_ROLES = [Role.WORKDAY_ADMIN.value]

_API_CLIENT_DESC = (
    "Workday API client registered (SAML ****** grant, required functional "
    "areas, Include Workday Owned Scope = Yes)"
)
_TENANT_DESC = (
    "Workday Tenant Setup - Security + signed-in employee SAML policy verified"
)

# Marker used in the finding when a config field the operator is expected to
# have captured is still empty. Kept as a module constant so tests can assert
# on it without hard-coding the phrase in multiple places.
_NOT_CAPTURED = "\u2014 not captured yet"


def _fmt(config, key: str) -> str:
    """Return the captured config value for ``key`` or a not-captured marker."""
    value = (config or {}).get(key)
    if value in (None, ""):
        return _NOT_CAPTURED
    return str(value)


def run_workday_tenant_checks(runner) -> list[CheckResult]:
    """Emit the two skill-4 Workday-tenant checkpoints.

    Both are MANUAL attestations (no queryable Workday admin API). Each
    emitter is invoked behind a guard so a single failure degrades to a
    WARNING for that checkpoint instead of aborting the remaining checks.
    """
    config = getattr(runner, "config", None) or {}

    emitters = (
        (_check_api_client, "WD-API-CLIENT-001", _API_CLIENT_DESC,
         Priority.CRITICAL.value),
        (_check_tenant_security, "WD-TENANT-001", _TENANT_DESC,
         Priority.HIGH.value),
    )

    results: list[CheckResult] = []
    for fn, cp_id, description, priority in emitters:
        try:
            results.extend(fn(config))
        except Exception as e:  # noqa: BLE001 — one emitter must not abort the rest
            results.append(CheckResult(roles=_ROLES,
                checkpoint_id=cp_id, category=_CATEGORY,
                priority=priority, status=Status.WARNING.value,
                description=description,
                result=(
                    f"Unable to attest {cp_id}: {type(e).__name__}: {e}"
                ),
                remediation=(
                    "This is a manual Workday-admin attestation; the kit only "
                    "echoes captured config. Re-run the setup step to record "
                    "the connection values, then try again."
                ),
            ))
    return results


# ─────────────────────────────────────────────────────────────────────
# WD-API-CLIENT-001 — Workday API client registration (S4.1, always MANUAL).
# ─────────────────────────────────────────────────────────────────────


def _check_api_client(config) -> list[CheckResult]:
    client_id = _fmt(config, "oauthClientId")
    token_endpoint = _fmt(config, "tokenEndpoint")

    if client_id != _NOT_CAPTURED:
        result = (
            "Workday admin task — verify in the Workday tenant, not "
            f"programmatically. Captured API client: Client ID = {client_id}; "
            f"Token Endpoint = {token_endpoint}. Confirm the registered client "
            "uses Client Grant Type = SAML ******, includes the functional "
            "areas Core Payroll, Organizations and Roles, Staffing, and Time "
            "Off and Leave, and has Include Workday Owned Scope = Yes "
            "(required for the REST /workers/me call). This signed-in employee "
            "setup does not use an ISU, RaaS report, or integration-system "
            "security-group domain mapping."
        )
    else:
        result = (
            "Workday admin task — no Workday API client has been captured yet "
            "(oauthClientId is empty in the active Workday connect config). "
            "Register the API client and capture its Client ID and Token "
            "Endpoint from the 'View API Client' screen before this row can "
            "be attested."
        )

    return [CheckResult(roles=_ROLES,
        checkpoint_id="WD-API-CLIENT-001", category=_CATEGORY,
        priority=Priority.CRITICAL.value, status=Status.MANUAL.value,
        description=_API_CLIENT_DESC,
        result=result,
        remediation=(
            "In Workday, run the 'Register API Client' task: set Client Grant "
            "Type = SAML ******, select the functional areas Core Payroll, "
            "Organizations and Roles, Staffing, and Time Off and Leave, and "
            "set Include Workday Owned Scope = Yes. Then open 'View API "
            "Client' and capture the Client ID and Token Endpoint. Do not add "
            "legacy ISU, RaaS, or integration-system security-group steps to "
            "this signed-in employee setup."
        ),
    )]


# ─────────────────────────────────────────────────────────────────────
# WD-TENANT-001 — Tenant Setup - Security + auth policy (S4.2/S4.3, MANUAL).
# ─────────────────────────────────────────────────────────────────────


def _check_tenant_security(config) -> list[CheckResult]:
    tenant = _fmt(config, "tenant")
    rest_base = _fmt(config, "restBaseUrl")
    soap_base = _fmt(config, "soapBaseUrl")
    saml_entity_id = _fmt(config, "workdaySamlEntityId")

    result = (
        "Workday admin task — verify in the Workday tenant, not "
        f"programmatically. Captured connection fields: tenant = {tenant}; "
        f"REST base = {rest_base}; SOAP base = {soap_base}; Workday SAML "
        f"Service Provider ID = {saml_entity_id}. Confirm Tenant Setup - "
        "Security has the "
        "redirection URL set, OAuth 2.0 Clients and SAML enabled, and the "
        "enabled SAML row uses the exact Service Provider ID above — and "
        "that an active authentication rule allows SAML for the intended "
        "employee population. If the existing active policy already provides "
        "that access, no policy change or activation is required."
    )

    return [CheckResult(roles=_ROLES,
        checkpoint_id="WD-TENANT-001", category=_CATEGORY,
        priority=Priority.HIGH.value, status=Status.MANUAL.value,
        description=_TENANT_DESC,
        result=result,
        remediation=(
            "In Workday: (1) edit 'Tenant Setup - Security' — set the "
            "redirection URL, enable OAuth 2.0 Clients and SAML, and verify "
            "the SAML Service Provider ID equals "
            "http://www.workday.com/{tenant}, not the api:// Entra application "
            "ID URI; (2) open 'Manage Authentication Policies' and verify an active "
            "rule allows SAML for the intended employees. Do not invent an "
            "OAuth-client condition when the tenant UI does not expose one, "
            "and do not use an ISU/integration-system security-group rule for "
            "this signed-in employee setup. If a policy change is required, "
            "preserve administrator access and existing network restrictions, "
            "review all pending changes, and only then activate them. The "
            "functional proof comes downstream, when the Copilot Studio "
            "connection authenticates successfully."
        ),
    )]
