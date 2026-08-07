# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — ServiceNow Deep Validation (SN-CONN-xxx, SN-FLOW-xxx, SN-CFG-xxx, SN-LOCAL-xxx)

Validates ServiceNow connection references, flow status, template configurations
in Dataverse, and local agent topic files for ServiceNow HRSD/ITSM scenarios.
"""

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from ..runner import CheckResult, Priority, Role, Status
from .connections import (
    check_connector_connections,
    filter_connections_by_connector,
    get_connection_status,
)
from .external_systems import _categorize_servicenow_flows

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"

# Expected ServiceNow template config scenario names (from HRSD + ITSM extension packs)
EXPECTED_TEMPLATE_CONFIGS = {
    "hrsd": [
        "ServiceNowHRSDCreateCase",
        "ServiceNowHRSDGetCaseDetails",
        "ServiceNowHRSDGetUserCases",
    ],
    "itsm": [
        "ServiceNowITSMCreateTicket",
        "ServiceNowITSMGetTicketDetails",
        "ServiceNowITSMGetUserTickets",
        "ServiceNowITSMUpdateTicket",
    ],
}

# Expected local topic patterns (schema name substrings)
EXPECTED_TOPICS = {
    "hrsd": [
        {"pattern": "servicenowhrsdcreatecase", "name": "ServiceNow HRSD Create Case"},
        {"pattern": "servicenowhrsdgetcasedetails", "name": "ServiceNow HRSD Get Case Details"},
        {"pattern": "servicenowhrsdgetusercases", "name": "ServiceNow HRSD Get User Cases"},
    ],
    "itsm": [
        {"pattern": "servicenowitsmcreateticket", "name": "ServiceNow ITSM Create Ticket"},
        {"pattern": "servicenowitsmgetticketdetails", "name": "ServiceNow ITSM Get Ticket Details"},
        {"pattern": "servicenowitsmgetusertickets", "name": "ServiceNow ITSM Get User Tickets"},
        {"pattern": "servicenowitsmupdateticket", "name": "ServiceNow ITSM Update Ticket"},
    ],
}


def run_servicenow_checks(runner) -> list[CheckResult]:
    """Execute ServiceNow-specific deep validation.

    Only runs if ServiceNow flows were detected by external_systems checks.
    """
    results: list[CheckResult] = []

    # Skip if no ServiceNow flows detected. Unlike Workday (which also has a
    # package-flavor signal, so an installed-but-no-flows-deployed tenant still
    # runs its deep checks), ServiceNow's ONLY "is it here?" signal is the flow
    # set itself. So this gate is unconditional, and every downstream ServiceNow
    # check — including SN-RUN-001 — is silent when no flows exist (the
    # not-installed state is already reported by SN-001). If ServiceNow ever
    # gains an installed-but-no-flows detector, mirror Workday's conditional
    # gate here and restore the "no flows discovered" SKIPPED branch in
    # _check_servicenow_run_health (it is intentionally absent today because it
    # was unreachable behind this gate).
    sn_flows = getattr(runner, "_servicenow_flows", [])
    if not sn_flows:
        return results

    print("\n  Running ServiceNow deep validation...")

    # --- Pre-install connection objects (SN-CONN-OBJECTS-001, S6.0) ---
    results.extend(_check_connection_objects(runner))

    # --- Connection References ---
    results.extend(_check_connections(runner))

    # --- Dataverse connection reference binding (SN-DV-CONN-001, S6.2) ---
    results.extend(_check_dataverse_connection(runner))

    # --- Flow Status ---
    results.extend(_check_flow_status(runner, sn_flows))

    # --- Run health (runtime failures connection-status can't see) ---
    results.extend(_check_servicenow_run_health(runner))

    # --- Extension pack install verification (SN-PKG-001, S6.1) ---
    results.extend(_check_pack_install(runner))

    # --- Template Configurations (Dataverse) ---
    results.extend(_check_template_configs(runner))

    # --- Portal Base URL (SN-BASEURL-001, S6.6) ---
    results.extend(_check_portal_base_url(runner))

    # --- Local Topic Files ---
    results.extend(_check_local_topics(runner))

    return _suppress_manual_conn_sec_when_runs_healthy(results)


def _suppress_manual_conn_sec_when_runs_healthy(
    results: list[CheckResult],
) -> list[CheckResult]:
    """Hide MANUAL ServiceNow connection/security checks when the run-health
    litmus test (SN-RUN-001) proves ServiceNow is actually working.

    Any ``SN-CONN-*`` / ``SN-SEC-*`` row emitted with MANUAL status asks the
    operator to hand-verify config in the ServiceNow/Entra tenant (a surface
    the kit has no admin API for). When SN-RUN-001 PASSES, runtime traffic
    already demonstrates that chain works end to end, so those manual asks are
    redundant noise — drop them.

    They are KEPT whenever SN-RUN-001 does NOT pass — i.e. it FAILED (they help
    diagnose the break), or it could not confirm health (NOT_CONFIGURED = no
    traffic yet, SKIPPED = run history unavailable), where hand-verification is
    still the operator's best signal (e.g. a fresh pre-deployment env).

    (ServiceNow ships no MANUAL conn/sec checks today, so this is a no-op until
    one is added; it mirrors the Workday WD-RUN-001 behaviour 1:1 so a future
    MANUAL SN-CONN/SN-SEC check inherits the suppression automatically.)
    """
    run_health = next(
        (r.status for r in results if r.checkpoint_id == "SN-RUN-001"), None
    )
    if run_health != Status.PASSED.value:
        return results
    return [
        r for r in results
        if not (
            r.status == Status.MANUAL.value
            and (r.checkpoint_id.startswith("SN-CONN") or r.checkpoint_id.startswith("SN-SEC"))
        )
    ]


def _check_connections(runner) -> list[CheckResult]:
    """Validate ServiceNow connection references in Power Platform."""
    return check_connector_connections(
        runner,
        connector_keyword=["service-now", "servicenow"],
        checkpoint_prefix="SN-CONN",
        category="ServiceNow",
        not_found_remediation="Configure ServiceNow connections in the environment. Run /connect servicenow.",
        doc_link=f"{DOC_BASE}/servicenow",
        connection_pin=getattr(runner, "servicenow_connection_pin", "") or "",
    )


def _check_connection_objects(runner) -> list[CheckResult]:
    """Verify the pre-install ServiceNow and Dataverse connection objects."""
    roles = [Role.POWER_PLATFORM_ADMIN.value]
    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    description = "ServiceNow and Dataverse connection objects are connected"

    if pp is None or not env_id:
        return [CheckResult(
            checkpoint_id="SN-CONN-OBJECTS-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.MANUAL.value,
            description=description,
            result="Power Platform Admin API not available — connection objects could not be verified.",
            roles=roles,
        )]

    try:
        connections = pp.get_connections(env_id)
    except Exception as exc:  # noqa: BLE001 — report an actionable warning
        connections = {"_error": str(exc)}

    if isinstance(connections, dict) and "_error" in connections:
        return [CheckResult(
            checkpoint_id="SN-CONN-OBJECTS-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.MANUAL.value,
            description=description,
            result=f"Unable to list Power Platform connections: {connections['_error']}",
            remediation="Run FlightCheck as a Power Platform Administrator, then retry.",
            roles=roles,
        )]

    required = {
        "ServiceNow": ["shared_service-now", "service-now", "servicenow"],
        "Microsoft Dataverse": ["shared_commondataserviceforapps"],
    }
    states = {}
    for label, keywords in required.items():
        matches = filter_connections_by_connector(connections or [], keywords)
        connected = [conn for conn in matches if get_connection_status(conn) == "Connected"]
        states[label] = (matches, connected)

    missing = [label for label, (matches, _) in states.items() if not matches]
    unhealthy = [
        label for label, (matches, connected) in states.items()
        if matches and not connected
    ]
    if missing:
        return [CheckResult(
            checkpoint_id="SN-CONN-OBJECTS-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=description,
            result=f"Missing required connection object(s): {', '.join(missing)}.",
            remediation="Create the missing connection(s) in Power Apps > Connections, then retry.",
            doc_link=f"{DOC_BASE}/servicenow", roles=roles,
        )]
    if unhealthy:
        return [CheckResult(
            checkpoint_id="SN-CONN-OBJECTS-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=description,
            result=f"No connected connection object found for: {', '.join(unhealthy)}.",
            remediation="Re-authenticate the unhealthy connection(s) in Power Apps > Connections, then retry.",
            doc_link=f"{DOC_BASE}/servicenow", roles=roles,
        )]

    return [CheckResult(
        checkpoint_id="SN-CONN-OBJECTS-001", category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.PASSED.value,
        description=description,
        result="Connected ServiceNow and Microsoft Dataverse connection objects were found in this environment.",
        doc_link=f"{DOC_BASE}/servicenow", roles=roles,
    )]


def run_servicenow_connection_object_checks(runner) -> list[CheckResult]:
    """Self-contained emitter for the pre-install connection-object gate."""
    return _check_connection_objects(runner)


# ─────────────────────────────────────────────────────────────────────
# SN-DV-CONN-001 — Dataverse connection reference binding (S6.2, PASS/FAIL).
#
# The ServiceNow extension pack ships its OWN Microsoft Dataverse connection
# reference (e.g. ``new_sharedcommondataserviceforapps_41c83``) alongside the
# ESS base agent's (``msdyn_Dataverse``). Both carry the
# ``shared_commondataserviceforapps`` connector. This checkpoint validates only
# the SERVICENOW PACK's Dataverse reference — identified by the
# ``sharedcommondataserviceforapps`` marker in its logical name — and verifies
# it is bound to an ACTIVE connection (owner echoed).
#
# It deliberately does NOT verify the base agent's ``msdyn_Dataverse`` reference:
# that reference belongs to the ESS base agent (installed in an earlier step),
# routinely ships unbound in a healthy ServiceNow setup, and is out of scope for
# the ServiceNow S6.2 step. Matching every ``shared_commondataserviceforapps``
# reference by connector alone would false-fail this ServiceNow check whenever an
# unrelated base-agent/system Dataverse reference is unbound.
#
# This is also NOT the Workday-family ``DV-CONN-001``: that check keys on the
# Workday pack's ``…_92b66`` logical-name suffix, so in a ServiceNow-only
# environment it reports NotConfigured (its reference is absent) even though the
# ServiceNow pack's own Dataverse reference is perfectly bound. Matching by the
# connector-generic ``sharedcommondataserviceforapps`` marker (not a hardcoded
# hex suffix) avoids repeating that coupling while still scoping to the pack.
# ─────────────────────────────────────────────────────────────────────

_DV_CONNECTOR_SUFFIX = "/apis/shared_commondataserviceforapps"
# Logical-name marker that scopes the check to the ServiceNow pack's own
# Dataverse reference (``<prefix>_sharedcommondataserviceforapps_<suffix>``),
# excluding the base agent's ``msdyn_Dataverse`` and other system references.
_SN_DV_LOGICALNAME_MARKER = "sharedcommondataserviceforapps"
_SN_DV_DESC = "Dataverse connection reference(s) bound to an active connection you own"

# ServiceNow Portal Base URL (SN-BASEURL-001, S6.6). The extension packs never
# populate it, but the agent needs it to turn case/ticket references into working
# links. It lives in the Dataverse template-config table on each product's parent
# record (msdyn_ServiceNowHRSD / msdyn_ServiceNowITSM) as a JSON blob in
# msdyn_value under this key.
_SN_BASEURL_DESC = "ServiceNow Portal Base URL set so case/ticket links resolve"
_SN_PORTAL_URI_KEY = "ServiceNowPortalBaseURI"
_SN_PORTAL_PARENT_RECORDS = {
    "hrsd": "msdyn_ServiceNowHRSD",
    "itsm": "msdyn_ServiceNowITSM",
}


def _resolve_conn_owner(props: dict) -> str:
    """Best-effort owner identity from a BAP connection's properties."""
    account = props.get("accountName")
    if account:
        return account
    created_by = props.get("createdBy") or {}
    return (
        created_by.get("userPrincipalName")
        or created_by.get("displayName")
        or "(unknown owner)"
    )


def _dv_owner_note(runner, connection_id) -> str:
    """Return an owner-confirmation note for ``connection_id`` (best-effort).

    Owner echo only — never the basis for a PASS/FAIL verdict. Degrades to an
    empty string whenever the Power Platform admin client is unavailable.
    """
    pp = getattr(runner, "pp_admin", None)
    env_id = getattr(runner, "env_id", None)
    if pp is None or not env_id or not connection_id:
        return ""
    try:
        conns = pp.get_connections(env_id)
    except Exception:  # noqa: BLE001 — owner echo is best-effort
        return ""
    if isinstance(conns, dict) and "_error" in conns:
        return ""
    for conn in conns or []:
        if conn.get("name") == connection_id:
            owner = _resolve_conn_owner(conn.get("properties", {}) or {})
            return f" Owner: {owner} — confirm this is your own account."
    return ""


def _check_dataverse_connection(runner) -> list[CheckResult]:
    """Verify the ServiceNow pack's Dataverse connection reference(s) are bound.

    Connector-generic sibling of the Workday-family ``DV-CONN-001``: it matches
    the ServiceNow pack's own Dataverse reference by the connector-family marker
    ``sharedcommondataserviceforapps`` in its logical name
    (``new_sharedcommondataserviceforapps_<suffix>``) rather than a hardcoded
    hex suffix. It deliberately EXCLUDES the base agent's ``msdyn_Dataverse``
    reference and other system Dataverse references, which are out of scope for
    the ServiceNow S6.2 step and routinely ship unbound in a healthy setup.

    Documented-tier Dataverse ``connectionreferences`` read (no cassette
    required; tests stub ``query_all``). Never raises a verdict from the owner
    echo — that is a best-effort Power Platform admin read.
    """
    roles = [Role.ESS_MAKER.value]
    env_url = getattr(runner, "env_url", None)
    dv_token = getattr(runner, "dv_token", None)
    if not env_url or not dv_token:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-DV-CONN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=_SN_DV_DESC,
            result="Dataverse token not available — skipping the Dataverse connection-reference check.",
        )]

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        rows = query_all(
            env_url, dv_token, "connectionreferences",
            "connectionreferencelogicalname,connectionreferencedisplayname,"
            "connectorid,connectionid,statuscode",
        )
    except Exception as e:  # noqa: BLE001 — degrade to WARNING, never abort
        return [CheckResult(roles=roles,
            checkpoint_id="SN-DV-CONN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=_SN_DV_DESC,
            result=f"Unable to read Dataverse connection references: {e}.",
            remediation="Confirm the FlightCheck identity has Dataverse read access on connectionreferences.",
        )]

    dv_refs = [
        r for r in (rows or [])
        if str(r.get("connectorid") or "").lower().endswith(_DV_CONNECTOR_SUFFIX)
        and _SN_DV_LOGICALNAME_MARKER
        in str(r.get("connectionreferencelogicalname") or "").lower()
    ]

    def _names(refs):
        return ", ".join(
            str(r.get("connectionreferencelogicalname") or "?") for r in refs
        )

    if not dv_refs:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-DV-CONN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=_SN_DV_DESC,
            result=(
                "No ServiceNow pack Microsoft Dataverse connection reference "
                "(logical name containing 'sharedcommondataserviceforapps') was "
                "found in this environment."
            ),
            remediation=(
                "Install the ServiceNow extension pack so its Dataverse "
                "connection reference is created, then bind it in Copilot Studio "
                "> your agent > Connections."
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    unbound = [r for r in dv_refs if not r.get("connectionid")]
    if unbound:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-DV-CONN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_SN_DV_DESC,
            result=(
                f"{len(unbound)} of {len(dv_refs)} Dataverse connection "
                f"reference(s) are unbound (connectionid=null): {_names(unbound)}."
            ),
            remediation=(
                "Bind the Dataverse reference to an active connection you own in "
                "Copilot Studio > your agent > Connections."
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    inactive = [r for r in dv_refs if r.get("statuscode") != 1]
    if inactive:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-DV-CONN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_SN_DV_DESC,
            result=(
                f"{len(inactive)} of {len(dv_refs)} Dataverse connection "
                f"reference(s) are bound but inactive: {_names(inactive)}."
            ),
            remediation=(
                "Re-authenticate or re-bind the Dataverse connection so its "
                "status is active, using an account you own."
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    owner_note = _dv_owner_note(runner, dv_refs[0].get("connectionid"))
    return [CheckResult(roles=roles,
        checkpoint_id="SN-DV-CONN-001", category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.PASSED.value,
        description=_SN_DV_DESC,
        result=(
            f"All {len(dv_refs)} Dataverse connection reference(s) are bound to "
            f"an active connection ({_names(dv_refs)})." + owner_note
        ),
        doc_link=f"{DOC_BASE}/servicenow",
    )]


def run_servicenow_dataverse_checks(runner) -> list[CheckResult]:
    """Self-contained emitter for ``SN-DV-CONN-001``.

    Unlike :func:`run_servicenow_checks` (which is gated on ServiceNow flow
    discovery), this wrapper has no ``_servicenow_flows`` dependency, so the
    checkpoint is independently runnable via ``--checkpoint SN-DV-CONN-001``
    (mirroring how ``SN-FLOWCONN-001`` is self-contained). The deep
    ``run_servicenow_checks`` path calls :func:`_check_dataverse_connection`
    directly, so scope runs still surface it once (no double emit here).
    """
    return _check_dataverse_connection(runner)


def _portal_uri(value) -> str:
    """Extract the ServiceNow portal base URI from a template-config ``msdyn_value``.

    ``value`` is the JSON string stored on the parent record. Returns the trimmed
    URI or ``""`` when the blob is missing, unparseable, or the key is empty.
    """
    try:
        data = json.loads(value) if isinstance(value, str) else (value or {})
    except (TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get(_SN_PORTAL_URI_KEY) or "").strip()


def _normalize_portal_url(value) -> str:
    """Normalize a portal URL for equality comparison.

    Lower-cases the scheme and host (case-insensitive per RFC 3986), preserves
    the path (ServiceNow portal suffixes like ``/sp`` are case-sensitive), and
    strips surrounding whitespace and any trailing slash. Returns ``""`` for an
    empty/whitespace value so callers can treat "no confirmed value" uniformly.
    """
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        # Not an absolute URL — return the trimmed form so a malformed stored
        # value never accidentally equals a malformed confirmed value.
        return raw.lower()
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path}"


def _check_portal_base_url(runner) -> list[CheckResult]:
    """Verify the ServiceNow Portal Base URL is set for each installed product.

    The extension packs create per-product parent config records
    (``msdyn_ServiceNowHRSD`` / ``msdyn_ServiceNowITSM``) but leave the portal
    base URL empty, so the case/ticket links the agent returns don't resolve
    until a maker sets it. FAILS when a present product's URL is empty, is not an
    ``http(s)`` URL, or — when a confirmed ``portalBaseUrl`` is recorded in the
    local ServiceNow connect config — does not match that confirmed value
    (normalized). NOT_CONFIGURED when no product config record exists (pack not
    installed). Same documented Dataverse read as the template-config check.
    """
    roles = [Role.ESS_MAKER.value]
    env_url = getattr(runner, "env_url", None)
    dv_token = getattr(runner, "dv_token", None)
    if not env_url or not dv_token:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-BASEURL-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=_SN_BASEURL_DESC,
            result="Dataverse token not available — skipping the portal base URL check.",
        )]

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        rows = query_all(
            env_url, dv_token, "msdyn_employeeselfservicetemplateconfigs",
            "msdyn_name,msdyn_value",
            filter_expr=(
                "msdyn_name eq 'msdyn_ServiceNowHRSD' or "
                "msdyn_name eq 'msdyn_ServiceNowITSM'"
            ),
        )
    except Exception as e:  # noqa: BLE001 — degrade to WARNING, never abort
        return [CheckResult(roles=roles,
            checkpoint_id="SN-BASEURL-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=_SN_BASEURL_DESC,
            result=f"Unable to read ServiceNow template configs: {e}.",
            remediation="Confirm the FlightCheck identity has Dataverse read access.",
        )]

    valid_records = set(_SN_PORTAL_PARENT_RECORDS.values())
    parents = {
        r.get("msdyn_name"): r for r in (rows or [])
        if r.get("msdyn_name") in valid_records
    }
    if not parents:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-BASEURL-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=_SN_BASEURL_DESC,
            result=(
                "No ServiceNow product config record (msdyn_ServiceNowHRSD / "
                "msdyn_ServiceNowITSM) was found — the extension pack is not installed."
            ),
            remediation=(
                "Install the ServiceNow extension pack (S6.1), then set the portal "
                "base URL on the product config in Copilot Studio."
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    label_by_record = {v: k.upper() for k, v in _SN_PORTAL_PARENT_RECORDS.items()}

    # The maker confirms one Portal Base URL and applies it to every in-scope
    # pack (P6.6). Compare each product's stored Dataverse value against that
    # confirmed value so a stale/wrong-but-absolute URL can't pass while the run
    # claims the confirmed URL was deployed. When no confirmed value is recorded
    # yet, fall back to presence/format validation only.
    cfg = _load_sn_connect_config() or {}
    confirmed_raw = str(cfg.get("portalBaseUrl") or "").strip()
    confirmed = _normalize_portal_url(confirmed_raw)

    unset: list[str] = []
    malformed: list[str] = []
    mismatched: list[str] = []
    ok: list[str] = []
    for record_name, row in parents.items():
        label = label_by_record.get(record_name, record_name)
        uri = _portal_uri(row.get("msdyn_value"))
        if not uri:
            unset.append(label)
        elif not uri.lower().startswith(("http://", "https://")):
            malformed.append(f"{label} ({uri})")
        elif confirmed and _normalize_portal_url(uri) != confirmed:
            mismatched.append(f"{label}: expected {confirmed_raw}, found {uri}")
        else:
            ok.append(f"{label} ({uri})")

    if unset or malformed or mismatched:
        problems = []
        if unset:
            problems.append(f"empty for {', '.join(unset)}")
        if malformed:
            problems.append(f"not a URL for {', '.join(malformed)}")
        if mismatched:
            problems.append(
                "does not match the confirmed URL for " + "; ".join(mismatched)
            )
        remediation = (
            "In Copilot Studio, open each in-scope ServiceNow product config "
            "and set the Portal Base URL to your Service Portal, e.g. "
            "https://<instance>.service-now.com/sp."
        )
        if mismatched and confirmed_raw:
            remediation = (
                "In Copilot Studio, open each in-scope ServiceNow product config "
                f"and set the Portal Base URL to the confirmed value "
                f"{confirmed_raw} on every in-scope pack."
            )
        return [CheckResult(roles=roles,
            checkpoint_id="SN-BASEURL-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_SN_BASEURL_DESC,
            result=(
                "ServiceNow Portal Base URL is " + "; ".join(problems)
                + ". Case and ticket links will not resolve correctly for employees."
            ),
            remediation=remediation,
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    non_portal = [u for u in ok if "/sp" not in u.lower()]
    note = ""
    if non_portal:
        note = (
            " Note: " + ", ".join(non_portal)
            + " does not point at a Service Portal path (…/sp)."
        )
    match_note = (
        f" Matches the confirmed URL ({confirmed_raw})." if confirmed else ""
    )
    return [CheckResult(roles=roles,
        checkpoint_id="SN-BASEURL-001", category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.PASSED.value,
        description=_SN_BASEURL_DESC,
        result=(
            f"Portal base URL set for {len(ok)} product(s): {', '.join(ok)}."
            + match_note + note
        ),
        doc_link=f"{DOC_BASE}/servicenow",
    )]


def run_servicenow_portal_checks(runner) -> list[CheckResult]:
    """Self-contained emitter for ``SN-BASEURL-001``.

    Like :func:`run_servicenow_dataverse_checks`, this wrapper has no
    ``_servicenow_flows`` gate, so the checkpoint is independently runnable via
    ``--checkpoint SN-BASEURL-001``. The deep ``run_servicenow_checks`` path calls
    :func:`_check_portal_base_url` directly, so scope runs surface it once.
    """
    return _check_portal_base_url(runner)


# ─────────────────────────────────────────────────────────────────────────
# Skill-3 capture gates (S3.1 / S3.2 / S3.3). These run BEFORE any pack is
# installed, so they read only the local ServiceNow connect config
# (.local/connect/servicenow/config.json) — no Dataverse, Graph, or live
# ServiceNow tenant. They were specified by capture-servicenow-config.md and
# tasks.md (checkpoints SN-CONFIG-001 / SN-PERM-001 / SN-USER-001) but never
# implemented, so a faithful resume into skill-3 hit "unknown checkpoint" and
# stalled. Emitted by run_servicenow_capture_checks (self-contained, ungated by
# flow discovery) rather than run_servicenow_checks, which is the post-install,
# flow-gated deep run.
# ─────────────────────────────────────────────────────────────────────────

_SN_CONFIG_DESC = "ServiceNow instance, product scope, connector, and sign-in method captured"
_SN_PERM_DESC = "Maker has the Entra and ServiceNow permissions the rest of setup needs"
_SN_USER_DESC = "Signed-in identity resolves to an active ServiceNow user record"

# authType values the sign-in flow supports (capture-servicenow-config.md P3.3).
_VALID_AUTH_TYPES = {"entra_user", "entra_certificate"}


def _load_sn_connect_config():
    """Read ``.local/connect/servicenow/config.json``.

    Returns ``None`` when the file is absent (skill-3 hasn't started), or the
    parsed dict (``{}`` when empty/corrupt) otherwise.
    """
    path = os.path.join(".local", "connect", "servicenow", "config.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_servicenow_instance(url: str) -> bool:
    """True for an ``https://<instance>.service-now.com`` base URL."""
    u = url.strip().lower()
    return u.startswith("https://") and ".service-now.com" in u


def _check_config_basics(runner) -> list[CheckResult]:
    """SN-CONFIG-001 (S3.1, prog) — validate the captured ServiceNow basics.

    Purely local: confirms the connect config records a valid instance URL, at
    least one in-scope product (HRSD/ITSM), a connector type, and a supported
    sign-in method. These are the inputs every later ServiceNow step depends on.
    """
    roles = [Role.ESS_MAKER.value]
    cfg = _load_sn_connect_config()
    if cfg is None:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-CONFIG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=_SN_CONFIG_DESC,
            result="No ServiceNow connection config has been captured yet.",
            remediation="Run /setup servicenow (skill 3) to capture your instance, product scope, connector, and sign-in method.",
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    missing = []
    instance = str(cfg.get("instanceUrl") or "").strip()
    if not _is_servicenow_instance(instance):
        missing.append("a valid ServiceNow instance URL (https://<instance>.service-now.com)")
    scope = cfg.get("scope") if isinstance(cfg.get("scope"), dict) else {}
    in_scope = [p.upper() for p in ("hrsd", "itsm") if scope.get(p)]
    if not in_scope:
        missing.append("at least one product in scope (HRSD or ITSM)")
    connector = str(cfg.get("connectorType") or "").strip()
    if not connector:
        missing.append("the connector type")
    auth_type = str(cfg.get("authType") or "").strip()
    if auth_type not in _VALID_AUTH_TYPES:
        missing.append("a supported sign-in method (Entra user sign-in or Entra certificate)")

    if missing:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-CONFIG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_SN_CONFIG_DESC,
            result="ServiceNow basics are incomplete: missing " + "; ".join(missing) + ".",
            remediation="Re-run the ServiceNow capture step (skill 3) and provide the missing values.",
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    return [CheckResult(roles=roles,
        checkpoint_id="SN-CONFIG-001", category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.PASSED.value,
        description=_SN_CONFIG_DESC,
        result=(
            f"Captured instance {instance}, scope {'+'.join(in_scope)}, "
            f"connector {connector}, sign-in {auth_type}."
        ),
        doc_link=f"{DOC_BASE}/servicenow",
    )]


def _check_maker_permissions(runner) -> list[CheckResult]:
    """SN-PERM-001 (S3.2, prog/manual) — validate the maker-permission summary.

    Reads the ``makerPermissions`` summary skill-3 persists after its read-only
    Graph role probe and the ServiceNow-admin availability question. A
    ServiceNow admin is mandatory (only they can register the OIDC provider), so
    its absence FAILS. Entra admin confirmed programmatically PASSES; anything
    less (not held / probe unavailable) degrades to MANUAL — the Entra app and
    admin-consent steps may need an escalation, which the operator attests to.
    """
    roles = [Role.ESS_MAKER.value]
    cfg = _load_sn_connect_config()
    perms = (cfg or {}).get("makerPermissions")
    if cfg is None or not isinstance(perms, dict) or not perms:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-PERM-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=_SN_PERM_DESC,
            result="Maker permissions haven't been probed yet.",
            remediation="Run /setup servicenow (skill 3) so it can probe your Entra role and confirm ServiceNow admin availability.",
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    sn_admin = perms.get("serviceNowAdmin")
    entra_admin = perms.get("entraAdmin")
    entra_evidence = str(perms.get("entraAdminEvidence") or "unconfirmed").strip()

    if sn_admin is False:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-PERM-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description=_SN_PERM_DESC,
            result="No ServiceNow administrator is available. Registering the Entra OIDC provider in ServiceNow is a ServiceNow-admin-only action, so setup cannot complete without one.",
            remediation="Arrange access to someone who can administer this ServiceNow instance (register an OIDC provider and elevate to security_admin), then re-run this step.",
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    if sn_admin is not True:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-PERM-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.MANUAL.value,
            description=_SN_PERM_DESC,
            result="ServiceNow admin availability hasn't been confirmed.",
            remediation="Confirm a ServiceNow administrator is available for the OIDC-provider and user-mapping steps, then attest to continue.",
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    if entra_admin is True:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-PERM-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description=_SN_PERM_DESC,
            result="Entra admin capability confirmed programmatically and a ServiceNow admin is available.",
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    return [CheckResult(roles=roles,
        checkpoint_id="SN-PERM-001", category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.MANUAL.value,
        description=_SN_PERM_DESC,
        result=(
            "A ServiceNow admin is available, but Entra admin capability wasn't "
            f"confirmed programmatically ({entra_evidence})."
        ),
        remediation="The Entra app-registration and admin-consent steps may need an account with an app/consent admin role. Confirm you can complete them (or have help), then attest to continue.",
        doc_link=f"{DOC_BASE}/servicenow",
    )]


def _check_user_record(runner) -> list[CheckResult]:
    """SN-USER-001 (S3.3, attest) — the mapped ServiceNow user record.

    The kit holds no ServiceNow-tenant credentials on this path, so it cannot
    programmatically prove the record exists; the row is an attestation. PASSES
    only once the operator has confirmed it (persisted as
    ``userRecord.activeUserConfirmed``); otherwise MANUAL with the check to run.
    """
    roles = [Role.ESS_MAKER.value]
    cfg = _load_sn_connect_config()
    user = (cfg or {}).get("userRecord")
    user = user if isinstance(user, dict) else {}
    if user.get("activeUserConfirmed") is True:
        mapped = str(user.get("mappedField") or "the mapped identity field").strip()
        return [CheckResult(roles=roles,
            checkpoint_id="SN-USER-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description=_SN_USER_DESC,
            result=f"You confirmed the signed-in identity maps to an active ServiceNow user ({mapped}).",
            doc_link=f"{DOC_BASE}/servicenow",
        )]

    return [CheckResult(roles=roles,
        checkpoint_id="SN-USER-001", category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.MANUAL.value,
        description=_SN_USER_DESC,
        result="The signed-in person's ServiceNow user record hasn't been confirmed.",
        remediation="In ServiceNow, confirm the person who signs in exists as an ACTIVE user whose mapped field (e.g. email) matches their Microsoft identity — otherwise requests come back empty — then attest to continue.",
        doc_link=f"{DOC_BASE}/servicenow",
    )]


def run_servicenow_capture_checks(runner) -> list[CheckResult]:
    """Self-contained emitter for the skill-3 capture gates.

    Emits SN-CONFIG-001, SN-PERM-001 and SN-USER-001 from the local ServiceNow
    connect config only (no Dataverse/Graph), so each is independently runnable
    via ``--checkpoint`` before any pack is installed. Deliberately NOT wired
    into :func:`run_servicenow_checks` (the flow-gated post-install deep run),
    which stays unchanged.
    """
    return (
        _check_config_basics(runner)
        + _check_maker_permissions(runner)
        + _check_user_record(runner)
    )


def _check_flow_status(runner, sn_flows: list) -> list[CheckResult]:
    """Check whether ServiceNow flows are enabled, grouped by HRSD/ITSM."""
    results = []

    # Reuse categorization from external_systems.py
    hrsd, itsm, other = _categorize_servicenow_flows(sn_flows)

    enabled = 0
    disabled = 0
    for i, f in enumerate(sn_flows):
        props = f.get("properties", {})
        name = props.get("displayName", f.get("displayName", f"Flow {i + 1}"))
        state = props.get("state", "")
        is_on = state.lower() in ("started", "on", "enabled")
        cid = f"SN-FLOW-{i + 1:03d}"

        if is_on:
            enabled += 1
        else:
            disabled += 1

        # Determine pack label
        pack_label = "Other"
        if f in hrsd:
            pack_label = "HRSD"
        elif f in itsm:
            pack_label = "ITSM"

        results.append(CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id=cid, category="ServiceNow",
            priority=Priority.HIGH.value,
            status=Status.PASSED.value if is_on else Status.FAILED.value,
            description=f"Flow [{pack_label}]: {name}",
            result=f"State: {'Enabled' if is_on else 'Disabled'}",
            remediation=f"Enable '{name}' in Power Automate." if not is_on else "",
            doc_link=f"{DOC_BASE}/servicenow",
        ))

    # Summary
    if sn_flows:
        hrsd_detail = f"{len(hrsd)} HRSD" if hrsd else ""
        itsm_detail = f"{len(itsm)} ITSM" if itsm else ""
        other_detail = f"{len(other)} other" if other else ""
        breakdown = ", ".join(filter(None, [hrsd_detail, itsm_detail, other_detail]))

        results.insert(0, CheckResult(roles=[Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="SN-FLOW-000", category="ServiceNow",
            priority=Priority.HIGH.value,
            status=Status.PASSED.value if disabled == 0 else Status.WARNING.value,
            description="ServiceNow flow status summary",
            result=f"{len(sn_flows)} flows ({breakdown}) — {enabled} enabled, {disabled} disabled",
            remediation=f"{disabled} flow(s) disabled — enable them in Power Automate." if disabled else "",
        ))

    return results


# ─────────────────────────────────────────────────────────────────────────
# SN-RUN-001 — ServiceNow shared-flow run health (run-history analysis)
# ─────────────────────────────────────────────────────────────────────────
#
# Complements the connection-status checks (SN-CONN-001+): those confirm the
# Power Platform connection is *Connected*, but a connection can be Connected
# while ServiceNow calls still FAIL at runtime — e.g. a revoked ServiceNow
# role/ACL for the signed-in user, a broken template config, or a ServiceNow-
# side outage. Connection status cannot see any of that; the only evidence is
# in the shared flow's *run history*.
#
# Detection model — CONFIRMED live 2026-06 against 3 environments with real
# ServiceNow run history (ESS_MODEL_UPGRADE_PREVIEW_FRE_2, test_CA, and
# "SunbreakDev - Release Testing - Workday+Snow"), captured via
# tests/captures/record_flightcheck_servicenow_runs.py. The user-facing
# orchestrator flow responds to Copilot Studio with exactly two actions:
#   * SUCCESS  -> status=Succeeded, response.name="Respond_to_Copilot"
#   * FAILURE  -> status=Failed,    response.name="Respond_to_Copilot_-_Failure"
# (NOTE this differs from Workday: Workday catches faults and reports
# status=Succeeded with a non-success Response branch, whereas ServiceNow's
# orchestrator failure surfaces as status=Failed. We still keep the
# "Succeeded but non-success Copilot response = caught_failure" branch for
# safety, but in practice ServiceNow failures are caught by the status=Failed
# path.)
#
# ServiceNow topology vs. Workday (same capture): unlike Workday's SINGLE
# shared flow, ServiceNow ships a MULTI-FLOW orchestration — per pack an entry
# "Common Orchestrator" plus child/utility flows ("Common Get/Create/Update/List
# Record", "Request Body Generator", "Live Agent Save Summary", ...). Only the
# orchestrator responds to Copilot; the child flows respond to their PARENT with
# NON-Copilot actions observed in the capture
# ("Respond_back_to_Orchestrator_-_Success",
# "Respond_to_Common_Orchestrator_-_Success",
# "Respond_to_a_Power_App_or_flow[_-_Success]"). A single user scenario produces
# several flow runs but only ONE user-facing (Copilot-responding) run. We
# therefore SCORE only runs whose response.name starts with
# ``Respond_to_Copilot``; succeeded child/utility runs are non-scoring
# 'pending'. (For Workday every run is the one shared flow and always carries a
# ``Respond_to_Copilot_*`` response, so the equivalent Workday check needs no
# such scoping — the two checks stay correct on their respective topologies.)
#
# So per-run detection:
#   a run FAILED  if  status in {Failed, TimedOut, ...}
#                 OR (status == "Succeeded" AND it responded to Copilot with an
#                     action != "Respond_to_Copilot")
#
# The check's VERDICT, however, is a litmus test for a *deterministic* break,
# not a per-run pass/fail: it looks only at the most recent window of scored
# runs (``_SN_RECENT_WINDOW``, newest first across all ServiceNow flows) and
# FAILs only when NONE of them succeeded. Scattered failures among recent
# successes (e.g. a user requesting a case their ServiceNow ACL doesn't allow)
# do NOT fail readiness — recent successes prove the integration is wired up. A
# single run that failed (no successes in the window) IS a failure.
#
# Known limitations (documented, not silently swallowed):
#   * A fully-broken/unconfigured connection makes Copilot Studio prompt
#     "connect to continue" and never invokes the flow, so NO run is created.
#     That case is covered by SN-CONN-001+ (connection status), NOT here.
#   * Agent-side timeouts (``flowActionTimedOut``) leave the run "Succeeded"
#     and are not detectable from run history.

# The single success Response action of the ServiceNow orchestrator (CONFIRMED
# live 2026-06). Any OTHER Copilot response action (e.g.
# "Respond_to_Copilot_-_Failure") is a failure branch.
_SN_SUCCESS_RESPONSE_ACTION = "Respond_to_Copilot"

# Prefix identifying a run that responded to Copilot Studio (the user-facing
# orchestrator run). Child/utility flow runs respond to their parent with
# non-Copilot actions (Respond_back_to_Orchestrator_*, Respond_to_a_Power_App_
# or_flow_*) and are non-scoring. CONFIRMED live 2026-06.
_SN_COPILOT_RESPONSE_PREFIX = "Respond_to_Copilot"

# Terminal run statuses that are definite failures of the run itself. A run in
# any of these did not complete successfully, regardless of response branch.
# (Cancelled / Skipped and unknown states are intentionally NOT here — they are
# inconclusive and treated as non-scoring 'pending' in _classify_run.)
_RUN_FAILURE_STATUSES = {"Failed", "TimedOut", "Faulted", "Aborted"}

# SN-RUN-001 evaluates only the most recent N terminal runs (newest first,
# across all ServiceNow flows). The check is a litmus test for a *deterministic*
# break: it FAILs only when NONE of the recent runs succeeded. A couple of
# scattered failures among recent successes is expected (e.g. a user asks for a
# case their ServiceNow ACL doesn't permit) and must NOT fail readiness — the
# presence of recent successes proves the integration is wired up.
_SN_RECENT_WINDOW = 10


def _classify_run(run: dict) -> str:
    """Classify one flow run as 'success', 'caught_failure', 'hard_failure',
    or 'pending' (non-scoring).

    Definite run-level failures (``"Failed"``/``"TimedOut"``/``"Faulted"``/
    ``"Aborted"``) are hard_failure. A ``"Succeeded"`` run is scored ONLY when it
    actually responded to Copilot Studio (``response.name`` starts with
    ``Respond_to_Copilot``) — that is the user-facing orchestrator run whose
    Response-action name distinguishes the success branch from a caught
    ServiceNow fault. ServiceNow's child/utility flow runs respond to their
    parent, not to Copilot, so a succeeded child run is non-scoring 'pending'
    (see the SN-RUN-001 module comment on the multi-flow topology). Everything
    else is 'pending' too: in-flight states (``"Running"``/``"Waiting"``/
    ``"Paused"``/``"Suspended"``) AND inconclusive terminal states that are not
    a ServiceNow-health signal (``"Cancelled"``/``"Skipped"``/unknown).
    Critically, a non-``"Succeeded"`` run is NEVER counted as a success — an
    all-``"Cancelled"`` window must not yield a misleading PASS (which would
    hide the manual conn/sec checks).
    """
    props = run.get("properties", {}) or {}
    status = props.get("status")
    resp_name = ((props.get("response") or {}).get("name")) or ""
    if status in _RUN_FAILURE_STATUSES:
        return "hard_failure"
    if status == "Succeeded":
        # Only orchestrator (Copilot-responding) runs are user-facing and
        # scoreable; child/utility flow runs are non-scoring.
        if not resp_name.startswith(_SN_COPILOT_RESPONSE_PREFIX):
            return "pending"
        if resp_name != _SN_SUCCESS_RESPONSE_ACTION:
            return "caught_failure"
        return "success"
    return "pending"


def _check_servicenow_run_health(runner) -> list[CheckResult]:
    """SN-RUN-001 — litmus test for a *deterministic* ServiceNow runtime break.

    Reads run history for each discovered ServiceNow flow via
    ``runner.pp_admin.get_flow_runs``, looks at the most recent window of runs
    (``_SN_RECENT_WINDOW``, newest first across all flows), and FAILs only when
    NONE of them succeeded. Recent successes prove the integration is wired up,
    so scattered failures alongside them do not fail readiness. Catches runtime
    ServiceNow failures that connection status (SN-CONN-001+) cannot see.
    """
    roles = [Role.SERVICENOW_ADMIN.value, Role.ESS_MAKER.value]
    pp = runner.pp_admin
    env_id = runner.env_id
    sn_flows = getattr(runner, "_servicenow_flows", [])

    if pp is None or not env_id:
        return [CheckResult(
            checkpoint_id="SN-RUN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ServiceNow flow run health",
            result="Power Platform Admin API not available — cannot read flow run history.",
            remediation="Re-run /flightcheck with Power Platform Admin access to evaluate ServiceNow run health.",
            roles=[Role.POWER_PLATFORM_ADMIN.value],
        )]

    # NOTE: no "not sn_flows" SKIPPED branch here on purpose. The only
    # production caller (run_servicenow_checks) returns early when sn_flows is
    # empty, so this function is never reached without flows. See the gate
    # comment in run_servicenow_checks for the ServiceNow-vs-Workday rationale.

    terminal: list[dict] = []
    api_error: str | None = None

    for f in sn_flows:
        flow_id = f.get("name")
        fname = f.get("properties", {}).get("displayName", f.get("displayName", flow_id))
        if not flow_id:
            continue
        runs = pp.get_flow_runs(env_id, flow_id)
        if isinstance(runs, dict) and "_error" in runs:
            api_error = runs["_error"]
            continue
        for run in runs:
            kind = _classify_run(run)
            if kind == "pending":
                continue
            props = run.get("properties", {}) or {}
            terminal.append({
                "start": props.get("startTime") or "",
                "kind": kind,
                "flow": fname,
                "run": run.get("name"),
                "resp": ((props.get("response") or {}).get("name")) or "?",
            })

    if not terminal:
        if api_error:
            return [CheckResult(
                checkpoint_id="SN-RUN-001", category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.SKIPPED.value,
                description="ServiceNow flow run health",
                result=f"Unable to read ServiceNow flow run history: {api_error}.",
                remediation="Run history requires owner/maker access to the ServiceNow flows. "
                            "Re-run as a user who owns the flows, or check it manually in "
                            "Power Automate (make.powerautomate.com).",
                roles=[Role.POWER_PLATFORM_ADMIN.value],
            )]
        return [CheckResult(
            checkpoint_id="SN-RUN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description="ServiceNow flow run health",
            result="No recent ServiceNow flow runs found — no runtime traffic to evaluate.",
            remediation="Exercise a ServiceNow scenario in the agent Test pane, then re-run /flightcheck. "
                        "Note: a fully-broken connection produces NO runs (the flow is never invoked) — "
                        "if ServiceNow isn't responding, check connection status first (SN-CONN-001).",
            doc_link=f"{DOC_BASE}/servicenow",
            roles=roles,
        )]

    # Evaluate only the most recent window (newest first). A deterministic
    # break = NO success among the recent runs. Scattered failures alongside
    # recent successes do NOT fail readiness.
    terminal.sort(key=lambda r: r["start"], reverse=True)
    window = terminal[:_SN_RECENT_WINDOW]
    n = len(window)
    win_fail = [r for r in window if r["kind"] in ("caught_failure", "hard_failure")]
    win_success = n - len(win_fail)

    def _sample_lines(rows: list[dict]) -> str:
        lines = []
        for r in rows[:5]:
            if r["kind"] == "hard_failure":
                lines.append(f"'{r['flow']}' run {r['run']}: flow run Failed")
            else:
                lines.append(f"'{r['flow']}' run {r['run']}: ServiceNow call failed ({r['resp']})")
        return "\n".join(lines)

    if win_success > 0:
        # At least one recent success → the integration is working. Not a
        # readiness blocker even if some recent runs failed.
        if win_fail:
            result = (
                f"{win_success} of the {n} most recent ServiceNow flow run(s) succeeded — the "
                f"integration is working. {len(win_fail)} recent run(s) failed, likely "
                f"scenario- or permission-specific rather than a broken connection."
            )
        else:
            result = f"All {n} most recent ServiceNow flow run(s) succeeded."
        return [CheckResult(
            checkpoint_id="SN-RUN-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="ServiceNow flow run health",
            result=result,
            remediation="",
            doc_link=f"{DOC_BASE}/servicenow",
            roles=roles,
        )]

    # No recent success → deterministically broken.
    return [CheckResult(
        checkpoint_id="SN-RUN-001", category="ServiceNow",
        priority=Priority.HIGH.value, status=Status.FAILED.value,
        description="ServiceNow flow run health",
        result=(
            f"All {n} most recent ServiceNow flow run(s) FAILED — the ServiceNow integration "
            f"appears deterministically broken. Note: run status alone shows 'Succeeded' "
            f"for caught ServiceNow failures, so this is based on the flow's response branch.\n"
            f"{_sample_lines(win_fail)}"
        ),
        remediation=(
            "Every recent ServiceNow call is failing — users cannot use ServiceNow scenarios. "
            "Open the failed run(s) in Power Automate (make.powerautomate.com) to read the "
            "ServiceNow error. Common causes: a revoked ServiceNow role/ACL, a misconfigured "
            "template config, an expired OAuth token, or a ServiceNow-side outage. If the "
            "connection itself shows Error, fix that first (see SN-CONN-001)."
        ),
        doc_link=f"{DOC_BASE}/servicenow",
        roles=roles,
    )]


def _check_template_configs(runner) -> list[CheckResult]:
    """Validate ServiceNow template configurations exist in Dataverse."""
    results = []
    env_url = runner.env_url
    dv_token = runner.dv_token

    if not env_url or not dv_token:
        results.append(CheckResult(roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="SN-CFG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="ServiceNow template configurations",
            result="Dataverse token not available — skipping template config checks",
        ))
        return results

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        # Query template configs filtering for ServiceNow scenarios
        configs = query_all(
            env_url, dv_token,
            "msdyn_employeeselfservicetemplateconfigs",
            "msdyn_name,msdyn_employeeselfservicetemplateconfigid",
            filter_expr="contains(msdyn_name,'ServiceNow')",
        )

        if configs:
            results.append(CheckResult(roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="SN-CFG-001", category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description="ServiceNow template configurations",
                result=f"Found {len(configs)} ServiceNow template config(s) in Dataverse",
                doc_link=f"{DOC_BASE}/servicenow",
            ))

            # Check for expected HRSD configs
            config_names = [c.get("msdyn_name", "").lower() for c in configs]
            _validate_expected_configs(results, config_names, "hrsd", "SN-CFG-01")
            _validate_expected_configs(results, config_names, "itsm", "SN-CFG-02")
        else:
            results.append(CheckResult(roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
                checkpoint_id="SN-CFG-001", category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
                description="ServiceNow template configurations",
                result="No ServiceNow template configs found in Dataverse",
                remediation=(
                    "Install the ServiceNow extension pack (HRSD/ITSM) in Copilot Studio. "
                    "Template configs are created automatically during installation."
                ),
                doc_link=f"{DOC_BASE}/servicenow",
            ))

    except Exception as e:
        results.append(CheckResult(roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
            checkpoint_id="SN-CFG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="ServiceNow template configurations",
            result=f"Unable to query template configs: {e}",
        ))

    return results


def _validate_expected_configs(
    results: list[CheckResult],
    config_names: list[str],
    pack_type: str,
    cid_prefix: str,
) -> None:
    """Check that expected template configs for a given pack type exist."""
    expected = EXPECTED_TEMPLATE_CONFIGS.get(pack_type, [])
    found = []
    missing = []

    for scenario in expected:
        if any(scenario.lower() in name for name in config_names):
            found.append(scenario)
        else:
            missing.append(scenario)

    pack_label = pack_type.upper()
    if not missing:
        results.append(CheckResult(
            checkpoint_id=f"{cid_prefix}0", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.PASSED.value,
            description=f"ServiceNow {pack_label} template configs",
            result=f"All {len(expected)} expected {pack_label} configs present",
            roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
        ))
    elif found:
        results.append(CheckResult(
            checkpoint_id=f"{cid_prefix}0", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.WARNING.value,
            description=f"ServiceNow {pack_label} template configs",
            result=f"{len(found)}/{len(expected)} configs found — missing: {', '.join(missing)}",
            remediation=f"Reinstall the ServiceNow {pack_label} extension pack or create missing configs manually.",
            roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
        ))
    # If none found, the pack likely isn't installed — don't flag as error


# ─────────────────────────────────────────────────────────────────────
# SN-PKG-001 — ServiceNow extension-pack install verification (S6.1).
#
# Installing a ServiceNow extension pack in Copilot Studio creates that product's
# Dataverse template-config scenario records (EXPECTED_TEMPLATE_CONFIGS). Their
# presence is the deterministic, auditable evidence that the pack CONTENT landed
# for a product — the same artifact SN-CFG reads, but surfaced here as a
# first-class per-product INSTALL gate so S6.1 has a real checkpoint instead of
# improvising install evidence from unrelated flow/config rows.
#
# Emits a summary ``SN-PKG-001`` (whose result names each product's state so the
# single-row ``--checkpoint SN-PKG-001`` read carries per-product evidence) plus
# one per-product row (``SN-PKG-010`` HRSD, ``SN-PKG-020`` ITSM). Per product:
#   all expected configs present -> Passed        (installed)
#   some present                 -> Failed        (partial / mid-install or
#                                                  corrupt — reinstall the pack)
#   none present                 -> NotConfigured (pack not installed)
# The summary is PASSED when at least one product is fully installed and none is
# partial (so an HR-only or IT-only scope passes with the other product absent),
# WARNING when any product is partially installed, and NotConfigured when no
# ServiceNow pack content exists at all.
#
# Self-contained (no ServiceNow-flow gate) via run_servicenow_pack_checks so it
# is independently runnable via ``--checkpoint SN-PKG-001`` and reports
# "not installed" BEFORE any flow exists. The deep run_servicenow_checks path
# also calls _check_pack_install directly, so scope runs surface it once.
# ─────────────────────────────────────────────────────────────────────

_SN_PKG_DESC = "ServiceNow extension pack content installed (per-product template configs present)"
_SN_PKG_PRODUCT_CIDS = {"hrsd": "SN-PKG-010", "itsm": "SN-PKG-020"}


def _check_pack_install(runner) -> list[CheckResult]:
    """Verify each ServiceNow extension pack's content landed in Dataverse."""
    roles = [Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value]
    env_url = getattr(runner, "env_url", None)
    dv_token = getattr(runner, "dv_token", None)
    if not env_url or not dv_token:
        return [CheckResult(roles=roles,
            checkpoint_id="SN-PKG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description=_SN_PKG_DESC,
            result="Dataverse token not available — skipping the ServiceNow pack install check.",
        )]

    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from auth import query_all

        configs = query_all(
            env_url, dv_token,
            "msdyn_employeeselfservicetemplateconfigs",
            "msdyn_name",
            filter_expr="contains(msdyn_name,'ServiceNow')",
        )
    except Exception as e:  # noqa: BLE001 — degrade to WARNING, never abort
        return [CheckResult(roles=roles,
            checkpoint_id="SN-PKG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=_SN_PKG_DESC,
            result=f"Unable to read ServiceNow template configs: {e}.",
            remediation="Confirm the FlightCheck identity has Dataverse read access.",
        )]

    config_names = [str(c.get("msdyn_name", "")).lower() for c in (configs or [])]

    per_product: list[CheckResult] = []
    installed: list[str] = []
    partial: list[str] = []
    absent: list[str] = []
    for product in ("hrsd", "itsm"):
        expected = EXPECTED_TEMPLATE_CONFIGS.get(product, [])
        found = [s for s in expected if any(s.lower() in n for n in config_names)]
        missing = [s for s in expected if s not in found]
        label = product.upper()
        cid = _SN_PKG_PRODUCT_CIDS[product]
        if found and not missing:
            installed.append(label)
            per_product.append(CheckResult(roles=roles,
                checkpoint_id=cid, category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description=f"ServiceNow {label} extension pack installed",
                result=f"All {len(expected)} {label} template config(s) present — pack installed.",
                doc_link=f"{DOC_BASE}/servicenow",
            ))
        elif found:
            partial.append(label)
            per_product.append(CheckResult(roles=roles,
                checkpoint_id=cid, category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.FAILED.value,
                description=f"ServiceNow {label} extension pack installed",
                result=(
                    f"{len(found)}/{len(expected)} {label} template config(s) present — "
                    f"partial install; missing: {', '.join(missing)}."
                ),
                remediation=(
                    f"Reinstall the ServiceNow {label} extension pack in Copilot Studio so all "
                    "its template configs are recreated."
                ),
                doc_link=f"{DOC_BASE}/servicenow",
            ))
        else:
            absent.append(label)
            per_product.append(CheckResult(roles=roles,
                checkpoint_id=cid, category="ServiceNow",
                priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
                description=f"ServiceNow {label} extension pack installed",
                result=f"No {label} template configs found — the {label} extension pack is not installed.",
                remediation=(
                    f"If {label} is in scope, install the ServiceNow {label} extension pack in "
                    "Copilot Studio; template configs are created automatically during install."
                ),
                doc_link=f"{DOC_BASE}/servicenow",
            ))

    if partial:
        summary = CheckResult(roles=roles,
            checkpoint_id="SN-PKG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description=_SN_PKG_DESC,
            result=(
                f"ServiceNow pack partially installed for {', '.join(partial)} (missing template "
                "configs)."
                + (f" Installed: {', '.join(installed)}." if installed else "")
                + (f" Not installed: {', '.join(absent)}." if absent else "")
            ),
            remediation="Reinstall the partially-installed ServiceNow pack(s) in Copilot Studio.",
            doc_link=f"{DOC_BASE}/servicenow",
        )
    elif installed:
        summary = CheckResult(roles=roles,
            checkpoint_id="SN-PKG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description=_SN_PKG_DESC,
            result=(
                f"ServiceNow extension pack installed for {', '.join(installed)}."
                + (f" Not installed: {', '.join(absent)}." if absent else "")
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        )
    else:
        summary = CheckResult(roles=roles,
            checkpoint_id="SN-PKG-001", category="ServiceNow",
            priority=Priority.HIGH.value, status=Status.NOT_CONFIGURED.value,
            description=_SN_PKG_DESC,
            result="No ServiceNow extension pack content found in Dataverse — no pack is installed.",
            remediation=(
                "Install the in-scope ServiceNow extension pack(s) (HR and/or IT) in Copilot "
                "Studio; template configs are created automatically during install."
            ),
            doc_link=f"{DOC_BASE}/servicenow",
        )
    return [summary] + per_product


def run_servicenow_pack_checks(runner) -> list[CheckResult]:
    """Self-contained emitter for ``SN-PKG-001`` (+ per-product SN-PKG-010/020).

    Like :func:`run_servicenow_dataverse_checks` / :func:`run_servicenow_portal_checks`,
    this wrapper has no ``_servicenow_flows`` gate, so the checkpoint is
    independently runnable via ``--checkpoint SN-PKG-001`` and can report the
    not-installed state before any flow exists. The deep ``run_servicenow_checks``
    path calls :func:`_check_pack_install` directly, so scope runs surface it once.
    """
    return _check_pack_install(runner)


def _check_local_topics(runner) -> list[CheckResult]:
    """Validate ServiceNow topics are present in local agent files."""
    results = []

    agents_root = Path("workspace/agents")
    if not agents_root.exists():
        return results

    agent_folders = [d for d in agents_root.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if not agent_folders:
        return results

    for agent_path in sorted(agent_folders):
        agent_name = agent_path.name
        label = agent_name.replace("-", " ").title()
        results.extend(_check_agent_sn_topics(agent_path, label))

    return results


def _check_agent_sn_topics(agent_path: Path, label: str) -> list[CheckResult]:
    """Check a single agent for ServiceNow topic files."""
    results = []
    topics_dir = agent_path / "topics"

    if not topics_dir.exists():
        return results

    # Collect all topic file names (lowercased for matching)
    topic_files = []
    for f in topics_dir.rglob("*.mcs.yml"):
        topic_files.append(f.stem.lower().replace(".mcs", ""))

    # Also check file content for ServiceNow references
    sn_topic_count = 0
    for f in topics_dir.rglob("*.mcs.yml"):
        try:
            content = f.read_text(encoding="utf-8").lower()
            if "servicenow" in content:
                sn_topic_count += 1
        except (OSError, UnicodeDecodeError):
            continue

    if sn_topic_count > 0:
        results.append(CheckResult(roles=[Role.ESS_MAKER.value],
            checkpoint_id="SN-LOCAL-001", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.PASSED.value,
            description=f"{label}: ServiceNow topics present",
            result=f"Found {sn_topic_count} topic(s) referencing ServiceNow",
        ))

        # Check for HRSD topics
        hrsd_found = _count_matching_topics(topic_files, "hrsd")
        itsm_found = _count_matching_topics(topic_files, "itsm")

        if hrsd_found:
            results.append(CheckResult(roles=[Role.ESS_MAKER.value],
                checkpoint_id="SN-LOCAL-002", category="ServiceNow",
                priority=Priority.MEDIUM.value, status=Status.PASSED.value,
                description=f"{label}: ServiceNow HRSD topics",
                result=f"Found {hrsd_found} HRSD topic(s)",
            ))

        if itsm_found:
            results.append(CheckResult(roles=[Role.ESS_MAKER.value],
                checkpoint_id="SN-LOCAL-003", category="ServiceNow",
                priority=Priority.MEDIUM.value, status=Status.PASSED.value,
                description=f"{label}: ServiceNow ITSM topics",
                result=f"Found {itsm_found} ITSM topic(s)",
            ))

        if not hrsd_found and not itsm_found:
            results.append(CheckResult(roles=[Role.ESS_MAKER.value],
                checkpoint_id="SN-LOCAL-002", category="ServiceNow",
                priority=Priority.MEDIUM.value, status=Status.WARNING.value,
                description=f"{label}: ServiceNow HRSD/ITSM topics",
                result="ServiceNow topics found but none match expected HRSD or ITSM patterns",
                remediation="Verify the ServiceNow extension pack installed correctly.",
            ))
    else:
        results.append(CheckResult(roles=[Role.ESS_MAKER.value],
            checkpoint_id="SN-LOCAL-001", category="ServiceNow",
            priority=Priority.MEDIUM.value, status=Status.NOT_CONFIGURED.value,
            description=f"{label}: ServiceNow topics",
            result="No ServiceNow topics found in local agent files",
            remediation="Install a ServiceNow extension pack and re-run /setup to extract topics.",
            doc_link=f"{DOC_BASE}/servicenow",
        ))

    return results


def _count_matching_topics(topic_files: list[str], pack_type: str) -> int:
    """Count how many topic files match expected patterns for a pack type."""
    patterns = [t["pattern"] for t in EXPECTED_TOPICS.get(pack_type, [])]
    count = 0
    for f in topic_files:
        # Remove spaces/dashes for fuzzy matching
        normalized = f.replace("-", "").replace("_", "").replace(" ", "")
        if any(p.replace(" ", "") in normalized for p in patterns):
            count += 1
    return count


