# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Mock response builders for the Power Platform Admin (BAP + PowerApps) APIs.

# ─────────────────────────────────────────────────────────────────
# MOCK_STATUS = "validated"
#
# Backed by a real captured cassette. Safe to use in FlightCheck
# integration tests under tests/flightcheck/.
#
# Cassette: tests/fixtures/cassettes/flightcheck_pp_admin.yaml
# Endpoints covered: see tests/fixtures/cassettes/INDEX.md
# ─────────────────────────────────────────────────────────────────

Used by FlightCheck integration tests for any check that reads
environments, connections, flows, or DLP policies via
solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py.

References:
- BAP environments: https://learn.microsoft.com/power-platform/admin/list-environments
- PowerApps connections: https://learn.microsoft.com/power-apps/maker/canvas-apps/add-manage-connections
- Production source: solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Validation status — read by tests/conftest.py:require_validated_mock().
MOCK_STATUS = "validated"
MOCK_CASSETTE = "tests/fixtures/cassettes/flightcheck_pp_admin.yaml"

BAP_BASE = "https://api.bap.microsoft.com"
POWERAPPS_BASE = "https://api.powerapps.com"
# Flow listing endpoint lives on a different host with a different audience
# token. See solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py
# `FLOW_BASE` and the `service.flow.microsoft.com//.default` scope.
FLOW_BASE = "https://api.flow.microsoft.com"

MOCK_ENV_ID = "Default-00000000-0000-0000-0000-000000001111"
MOCK_ORG_ID = "00000000-0000-0000-0000-000000005555"


# ────────────────────────────────────────────────────────────────────────
# Payload builders — return single records suitable for assembling into
# a {"value": [...]} response collection.
# ────────────────────────────────────────────────────────────────────────


def environment(
    *,
    env_id: str = MOCK_ENV_ID,
    display_name: str = "Mock Environment",
    organization_id: str = MOCK_ORG_ID,
    instance_url: str = "https://orgmocktenant.crm.dynamics.com/",
) -> dict[str, Any]:
    """Build a single BAP environment record.

    Cited consumers:
      - flightcheck/pp_admin_client.py:148-162 (get_environments / get_environment)
      - flightcheck/pp_admin_client.py:240+ (derive_environment_id)
    """
    return {
        "id": f"/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments/{env_id}",
        "name": env_id,
        "type": "Microsoft.BusinessAppPlatform/scopes/admin/environments",
        "properties": {
            "displayName": display_name,
            "createdTime": "2026-01-01T00:00:00.000Z",
            "linkedEnvironmentMetadata": {
                "instanceUrl": instance_url,
                "instanceState": "Ready",
                "resourceId": organization_id,
                "uniqueName": f"unq{organization_id[:8]}",
            },
            "environmentSku": "Production",
            "states": {
                "management": {"id": "Ready"},
                "runtime": {"id": "Enabled"},
            },
        },
    }


def connection(
    *,
    name: str = "shared-workdaysoap-mock-001",
    display_name: str = "Mock Workday SOAP",
    api_name: str = "shared_workdaysoap",
    env_id: str = MOCK_ENV_ID,
    status: str = "Connected",
    error_target: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    extra_properties: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single PowerApps connection record.

    `status` accepts any of "Connected", "Error", "PendingConfirmation",
    "Unknown". For Error statuses, real responses include a nested
    `target` + `error.{code, message}` block — pass error_target,
    error_code, error_message to populate them. Defaults to the
    "Unauthorized" / "AADSTS50173: grant expired" shape captured from
    the user's real tenant in
    tests/fixtures/cassettes/flightcheck_pp_admin.yaml.

    The check in flightcheck/checks/workday.py:_get_conn_status only
    reads statuses[0].status — the target/error block is included for
    fidelity to real API responses, not because the kit consumes it.

    Cited consumers:
      - flightcheck/pp_admin_client.py:184-190 (get_connections)
      - flightcheck/checks/workday.py:262-342 (_check_connections)

    Reference: tests/fixtures/cassettes/flightcheck_pp_admin.yaml
    """
    api_id = (
        f"/providers/Microsoft.PowerApps/scopes/admin/environments/"
        f"{env_id}/apis/{api_name}"
    )
    status_entry: dict[str, Any] = {"status": status}
    if status == "Error":
        status_entry["target"] = error_target or "token"
        status_entry["error"] = {
            "code": error_code or "Unauthorized",
            "message": error_message or (
                "Failed to refresh access token. AADSTS50173: The provided "
                "grant has expired due to it being revoked, a fresh auth "
                "token is needed."
            ),
        }

    properties: dict[str, Any] = {
        "displayName": display_name,
        "apiId": api_id,
        "iconUri": (
            f"https://static.powerapps.com/resource/ppcr/releases/v1.0.0/"
            f"{api_name.replace('shared_', '')}/icon.png"
        ),
        "statuses": [status_entry],
        "connectionParameters": {"sku": "Enterprise"},
        "keywordsRemaining": 78,
        "isSsoConnection": False,
        "createdBy": {
            "id": "00000000-0000-0000-0000-000000002222",
            "displayName": "Mock User",
            "email": "mock.user@contoso.com",
            "type": "User",
            "tenantId": "00000000-0000-0000-0000-000000001111",
            "userPrincipalName": "mock.user@contoso.com",
        },
        "createdTime": "2026-01-01T00:00:00.0000000Z",
        "lastModifiedTime": "2026-01-15T00:00:00.0000000Z",
        "environment": {
            "id": f"/providers/Microsoft.PowerApps/environments/{env_id}",
            "name": env_id,
        },
        "accountName": "mock.user@contoso.com",
        "allowSharing": False,
    }
    if extra_properties:
        properties.update(extra_properties)

    return {
        "name": name,
        "id": (
            f"/providers/Microsoft.PowerApps/scopes/admin/environments/"
            f"{env_id}/apis/{api_name}/connections/{name}"
        ),
        "type": "Microsoft.PowerApps/scopes/apis/connections",
        "properties": properties,
    }


def dlp_policy(
    *,
    display_name: str = "Mock DLP Policy",
    policy_id: str = "00000000-0000-0000-0000-0000000d1p01",
    business: Iterable[str] = (),
    non_business: Iterable[str] = (),
    blocked: Iterable[str] = (),
    environments: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build a DLP (data) policy record in the apiPolicies 2021-04-01 shape.

    ``business`` / ``non_business`` / ``blocked`` accept connector
    api-names (e.g. ``"shared_workdaysoap"``) or full connector ids; they
    are emitted under ``properties.connectorGroups`` with the wire
    classification tokens ``Confidential`` / ``General`` / ``Blocked``
    respectively (the PowerShell/REST vocabulary; the admin-center UI
    labels these Business / Non-Business / Blocked).

    ``environments`` — BAP env ids the policy is scoped to. Omit (``None``)
    for a tenant-wide (all-environments) policy with no environment filter.

    API tier: the BAP apiPolicies surface is **documented** tier (see
    tests/fixtures/cassettes/INDEX.md → API tier registry; the captured
    ``flightcheck_pp_admin.yaml`` apiPolicies response is an empty
    ``{"value": []}`` and does not exercise connector groups). The
    connector-group shape below is therefore verified against MS Learn,
    not a cassette. A populated apiPolicies capture would upgrade this to
    validated — see INDEX.md follow-up note.

    Documented shape (MS Learn) — one policy's connector groups::

        "properties": {
            "displayName": "Block non-business",
            "connectorGroups": [
                {"classification": "Confidential",   # = Business
                 "connectors": [
                     {"id": "/providers/Microsoft.PowerApps/apis/shared_commondataserviceforapps",
                      "name": "shared_commondataserviceforapps",
                      "type": "Microsoft.PowerApps/apis"}]},
                {"classification": "General",        # = Non-Business
                 "connectors": [...]},
                {"classification": "Blocked",
                 "connectors": [...]}
            ]
        }

    The classification token vocabulary (``Confidential`` / ``General`` /
    ``Blocked``) is documented at:
      - https://learn.microsoft.com/power-platform/admin/dlp-connector-classification
        (Business / Non-Business / Blocked data groups — conceptual)
      - https://learn.microsoft.com/power-platform/admin/dlp-custom-connector-parity#powershell-support-for-custom-connector-url-patterns
        (``customConnectorRuleClassification`` supported values:
        ``General | Confidential | Blocked | Ignore``)

    Consumer:
      flightcheck/checks/_dlp_utils.policy_connector_groups
    """

    def _conns(names: Iterable[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for n in names:
            cid = (
                str(n)
                if str(n).startswith("/providers/")
                else f"/providers/Microsoft.PowerApps/apis/{n}"
            )
            out.append({
                "id": cid,
                "name": str(n).rsplit("/", 1)[-1],
                "type": "Microsoft.PowerApps/apis",
            })
        return out

    groups: list[dict[str, Any]] = []
    if business:
        groups.append({"classification": "Confidential", "connectors": _conns(business)})
    if non_business:
        groups.append({"classification": "General", "connectors": _conns(non_business)})
    if blocked:
        groups.append({"classification": "Blocked", "connectors": _conns(blocked)})

    properties: dict[str, Any] = {
        "displayName": display_name,
        "connectorGroups": groups,
    }
    if environments is not None:
        env_entries = [{"name": e} for e in environments]
        # Newer payloads expose `environments`; the kit's env filter also
        # reads the legacy `environmentFilter.environments` shape — emit
        # both for fidelity.
        properties["environments"] = env_entries
        properties["environmentFilter"] = {"environments": env_entries}

    return {
        "id": (
            "/providers/Microsoft.BusinessAppPlatform/scopes/admin/"
            f"apiPolicies/{policy_id}"
        ),
        "name": policy_id,
        "type": "Microsoft.BusinessAppPlatform/scopes/admin/apiPolicies",
        "properties": properties,
    }


def workday_connection(
    *,
    status: str = "Connected",
    display_name: str = "Workday SOAP — ISU",
    error_target: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    account_name: str | None = None,
    connection_name: str | None = None,
    created_by_upn: str | None = None,
    created_by_display_name: str | None = None,
    created_time: str | None = None,
) -> dict[str, Any]:
    """Convenience: a Workday SOAP connection. The check filters by
    'workday' substring in apiId+displayName, so both the api_id and
    the display_name reference Workday.

    `error_target` / `error_code` / `error_message` are forwarded to the
    underlying ``connection()`` builder when ``status == "Error"`` so
    callers can simulate the AADSTS50173 / AADSTS70008 / AADSTS50058
    grant-expiry shapes that WD-CONN-101 inspects. When omitted, the
    underlying builder falls back to its default AADSTS50173 example.

    `account_name` overrides the connection's ``properties.accountName``
    field — used by WD-CONN-101's remediation message to tell the
    operator exactly which user's grant needs refreshing. Pass an
    empty string ``""`` to simulate the admin-scope shape where
    ``accountName`` is null/empty (forces the check's owner-fallback
    chain through ``createdBy.userPrincipalName`` /
    ``createdBy.displayName``).

    `connection_name` overrides the connection record's ``name`` field
    (the GUID-suffixed identifier like
    ``shared-workdaysoap-ac42a2e7-...``) so tests can pin a specific
    name that matches a flow's ``connectionReferences.{ref}.connectionName``
    for in-use cross-referencing.

    `created_by_upn` / `created_by_display_name` override the
    ``properties.createdBy.userPrincipalName`` /
    ``properties.createdBy.displayName`` fields used by WD-CONN-101's
    owner-fallback chain when ``accountName`` is null.

    `created_time` overrides the ``properties.createdTime`` field used
    by WD-CONN-101 to surface a creation date in the operator's view.
    """
    extra: dict[str, Any] = {}
    if account_name is not None:
        extra["accountName"] = account_name
    if created_time is not None:
        extra["createdTime"] = created_time
    if created_by_upn is not None or created_by_display_name is not None:
        created_by: dict[str, Any] = {
            "id": "00000000-0000-0000-0000-000000002222",
            "type": "User",
            "tenantId": "00000000-0000-0000-0000-000000001111",
        }
        if created_by_upn is not None:
            created_by["userPrincipalName"] = created_by_upn
            created_by["email"] = created_by_upn
        if created_by_display_name is not None:
            created_by["displayName"] = created_by_display_name
        extra["createdBy"] = created_by
    return connection(
        name=connection_name or f"workday-{status.lower()}-{display_name[:8].lower().replace(' ', '-')}",
        display_name=display_name,
        api_name="shared_workdaysoap",
        status=status,
        error_target=error_target,
        error_code=error_code,
        error_message=error_message,
        extra_properties=extra or None,
    )


def non_workday_connection(
    *, display_name: str = "Office 365", status: str = "Connected"
) -> dict[str, Any]:
    """Convenience: a non-Workday connection (Office 365, Dataverse,
    SharePoint, etc.) used to verify the Workday filter excludes them."""
    return connection(
        name="office365-mock-001",
        display_name=display_name,
        api_name="shared_office365",
        status=status,
    )


def servicenow_connection(
    *,
    status: str = "Connected",
    display_name: str = "ServiceNow HRSD",
    api_name: str = "shared_service-now",
    connection_name: str | None = None,
) -> dict[str, Any]:
    """Convenience: a ServiceNow connection.

    Mirrors ``workday_connection`` for the SN-CONN-* checks in
    flightcheck/checks/servicenow.py. The check filters connections by
    matching either ``service-now`` or ``servicenow`` (case-insensitive)
    in the apiId+displayName concatenation, so any combination of
    those substrings is honored.

    ``api_name`` defaults to ``shared_service-now`` — the canonical
    Power Platform connector ID for the ServiceNow connector. The
    hyphenated and unhyphenated aliases both exist in practice
    (older docs and the connector ID itself use the hyphen; some
    UI surfaces strip it) which is why
    ``servicenow._check_connections`` matches both.

    ``connection_name`` overrides the record's ``name`` field
    (defaults to ``servicenow-{status}-{display_name slug}``) so
    tests that need a specific id can pin it.

    Cited consumers:
      - flightcheck/checks/servicenow.py:81-90 (_check_connections)
      - flightcheck/checks/connections.py:67-176 (check_connector_connections)

    Reference: same response shape as workday_connection; backed by
    tests/fixtures/cassettes/flightcheck_pp_admin.yaml.
    """
    return connection(
        name=connection_name or (
            f"servicenow-{status.lower()}-"
            f"{display_name[:8].lower().replace(' ', '-')}"
        ),
        display_name=display_name,
        api_name=api_name,
        status=status,
    )


def flow(
    *,
    flow_id: str | None = None,
    env_id: str = MOCK_ENV_ID,
    display_name: str = "Workday Get Worker",
    state: str = "Started",
    connection_references: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a single PowerApps flow record.

    `state` accepts "Started", "Stopped", "Suspended". The check in
    flightcheck/checks/workday.py:_check_flow_status treats
    {"started", "on", "enabled"} (case-insensitive) as enabled.

    `env_id` defaults to MOCK_ENV_ID so the record's `id` field is
    self-consistent with what `list_flows()` (which uses the same
    default) would serve under. Callers building a flow against a
    specific environment should pass the same env_id they pass to
    `list_flows()`.

    `connection_references` populates ``properties.connectionReferences``,
    a dict keyed by ref-name → ``{"apiId": ..., "connectionName": ...}``.
    Used by WD-CONN-101 to cross-reference unhealthy Workday
    connections against flows that depend on them (in-use ⇒ FAILED,
    orphan ⇒ WARNING). Pass an empty dict / None to model a flow with
    no connection references (i.e. doesn't claim any of the test's
    Workday connections).
    """
    effective_id = flow_id or "00000000-0000-0000-0000-000000007101"
    props: dict[str, Any] = {
        "displayName": display_name,
        "state": state,
        "createdTime": "2026-01-01T00:00:00.000Z",
    }
    if connection_references is not None:
        props["connectionReferences"] = dict(connection_references)
    return {
        "name": effective_id,
        "id": (
            f"/providers/Microsoft.ProcessSimple/environments/{env_id}"
            f"/flows/{effective_id}"
        ),
        "type": "Microsoft.ProcessSimple/environments/flows",
        "properties": props,
    }


def flow_run(
    *,
    run_id: str = "08580000000000000000000000000001CU01",
    env_id: str = MOCK_ENV_ID,
    flow_id: str = "00000000-0000-0000-0000-000000007101",
    status: str = "Succeeded",
    response_name: str = "Respond_to_Copilot_with_Success",
    response_code: str = "OK",
    error: Mapping[str, Any] | None = None,
    bot_schema: str = "msdyn_copilotforemployeeselfservicehr",
) -> dict[str, Any]:
    """Build a single Power Automate flow-run record (run history).

    Models the runtime runs endpoint response consumed by WD-RUN-001 via
    ``pp_admin_client.get_flow_runs``. The two fields the check reads are
    ``properties.status`` and ``properties.response.name``; ``correlation.
    clientKeywords`` (BotSchemaName / CdsBotId) is included for fidelity.

    Cited consumers:
      - solutions/ess-maker-skills/scripts/flightcheck/checks/workday.py
        (_classify_run / _check_workday_run_health)

    Source (validated):
      Captured live (2026-06) from a real ESS Workday tenant via the runtime
      runs endpoint
      ``GET https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple/
      environments/{env}/flows/{flow}/runs?api-version=2016-11-01``.
      Recorder: tests/captures/record_flightcheck_workday_runs.py
      Cassette: tests/fixtures/cassettes/flightcheck_workday_runs.yaml
      Observed shapes:
        - success: status=Succeeded, response.name=Respond_to_Copilot_with_Success
        - caught Workday fault: status=Succeeded,
          response.name=Respond_to_Copilot_with_failure_errorMessage
        - template error: status=Failed,
          response.name=Respond_to_Copilot_with_XmlTemplate_To_Json_Failed,
          error={code:ActionFailed,message:"An action failed..."}
    """
    props: dict[str, Any] = {
        "startTime": "2026-06-01T00:00:00.0000000Z",
        "endTime": "2026-06-01T00:00:03.0000000Z",
        "status": status,
        "correlation": {
            "clientKeywords": [f"BotSchemaName:{bot_schema},ChannelId:pva-studio"],
        },
        "trigger": {"name": "manual", "status": "Succeeded"},
        "response": {"name": response_name, "code": response_code, "status": status},
        "isAborted": False,
    }
    if error is not None:
        props["error"] = dict(error)
    return {
        "name": run_id,
        "id": (
            f"/providers/Microsoft.ProcessSimple/environments/{env_id}"
            f"/flows/{flow_id}/runs/{run_id}"
        ),
        "type": "Microsoft.ProcessSimple/environments/flows/runs",
        "properties": props,
    }


def workday_connection_reference(
    *,
    connection_name: str,
    api_name: str = "shared_workdaysoap",
) -> dict[str, Any]:
    """Build a single ``connectionReferences`` entry binding a flow to
    a specific Workday connection record.

    Returned shape matches the production response: a dict with at
    least ``apiId`` (connector path) and ``connectionName`` (the
    connection record's GUID-suffixed name). Wrap one or more of these
    in a dict keyed by ref-name and pass to ``flow(connection_references=...)``.
    """
    return {
        "apiId": (
            f"/providers/Microsoft.PowerApps/scopes/admin/environments/"
            f"{MOCK_ENV_ID}/apis/{api_name}"
        ),
        "connectionName": connection_name,
        "id": (
            f"/providers/Microsoft.PowerApps/scopes/admin/environments/"
            f"{MOCK_ENV_ID}/apis/{api_name}/connections/{connection_name}"
        ),
        "source": "Embedded",
        "tier": "NotSpecified",
    }


def flow_connector_ref(
    *,
    api_name: str = "shared_workdaysoap",
    tier: str = "Premium",
    is_custom_api: bool = False,
    display_name: str | None = None,
) -> dict[str, Any]:
    """Build a single ``connectionReferences`` entry as it appears in the
    flow DETAIL response (``get_flow``), carrying the connector-tier signal
    LIC-FLOW-001 reads.

    Shape pinned by tests/fixtures/cassettes/flightcheck_flow_licensing.yaml:
    each connection reference nests the connector definition under
    ``apiDefinition.properties`` with ``tier`` ("Premium" / "Standard") and
    ``isCustomApi``. Real connectors observed: shared_workdaysoap=Premium,
    shared_commondataserviceforapps=Premium, shared_conversionservice=Standard.
    """
    disp = display_name or api_name
    return {
        "apiName": api_name,
        "connectionName": f"conn-{api_name}",
        "connectionReferenceLogicalName": f"ref_{api_name}",
        "tier": tier,
        "apiDefinition": {
            "name": api_name,
            "id": f"/providers/Microsoft.PowerApps/apis/{api_name}",
            "type": "/providers/Microsoft.PowerApps/apis",
            "properties": {
                "displayName": disp,
                "tier": tier,
                "isCustomApi": is_custom_api,
                "capabilities": ["actions"],
            },
        },
    }


def flow_detail(
    *,
    flow_id: str | None = None,
    env_id: str = MOCK_ENV_ID,
    display_name: str = "ESS HR Workday",
    trigger_kind: str | None = "Skills",
    connection_refs: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a flow DETAIL record (``GET .../flows/{id}``) for LIC-FLOW-001.

    ``connection_refs`` maps a ref key → a :func:`flow_connector_ref` dict.
    ``trigger_kind`` populates ``definitionSummary.triggers[0].kind``
    ("Skills" / "VirtualAgent" for agent-invoked; pass None for a
    non-agent trigger). Shape pinned by flightcheck_flow_licensing.yaml.
    """
    effective_id = flow_id or "00000000-0000-0000-0000-000000007201"
    triggers = [{
        "type": "Request" if trigger_kind else "Recurrence",
        "kind": trigger_kind,
    }]
    props: dict[str, Any] = {
        "displayName": display_name,
        "state": "Started",
        "userType": "Owner",
        "definitionSummary": {"triggers": triggers, "actions": [], "description": ""},
        "connectionReferences": dict(connection_refs or {}),
    }
    return {
        "name": effective_id,
        "id": (
            f"/providers/Microsoft.ProcessSimple/environments/{env_id}"
            f"/flows/{effective_id}"
        ),
        "type": "Microsoft.ProcessSimple/environments/flows",
        "properties": props,
    }


# ────────────────────────────────────────────────────────────────────────
# Collection wrappers
# ────────────────────────────────────────────────────────────────────────

def collection(
    records: Iterable[Mapping[str, Any]],
    *,
    next_link: str | None = None,
) -> dict[str, Any]:
    """Wrap a list of records in the BAP/PowerApps {"value": [...]} envelope."""
    payload: dict[str, Any] = {"value": list(records)}
    if next_link:
        payload["nextLink"] = next_link
    return payload


# ────────────────────────────────────────────────────────────────────────
# `responses` registration helpers
# ────────────────────────────────────────────────────────────────────────


def list_connections(
    *,
    env_id: str = MOCK_ENV_ID,
    connections: Iterable[Mapping[str, Any]] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock GET /providers/Microsoft.PowerApps/scopes/admin/environments/{env}/connections."""
    return {
        "method": "GET",
        "url": (
            f"{POWERAPPS_BASE}/providers/Microsoft.PowerApps/scopes/admin/environments/"
            f"{env_id}/connections"
        ),
        "json": collection(connections or []),
        "status": status,
    }


def list_environments(
    *,
    environments: Iterable[Mapping[str, Any]] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock GET /providers/Microsoft.BusinessAppPlatform/scopes/admin/environments."""
    return {
        "method": "GET",
        "url": (
            f"{BAP_BASE}/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments"
        ),
        "json": collection(environments or []),
        "status": status,
    }


def list_flows(
    *,
    env_id: str = MOCK_ENV_ID,
    flows: Iterable[Mapping[str, Any]] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock GET /providers/Microsoft.ProcessSimple/scopes/admin/environments/{env}/v2/flows.

    Hosted on `api.flow.microsoft.com` (NOT `api.powerapps.com`) and
    requires a `service.flow.microsoft.com//.default` audience token
    rather than the PowerApps audience.
    """
    return {
        "method": "GET",
        "url": (
            f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/scopes/admin/environments/"
            f"{env_id}/v2/flows"
        ),
        "json": collection(flows or []),
        "status": status,
    }


def list_flow_runs(
    *,
    env_id: str = MOCK_ENV_ID,
    flow_id: str = "00000000-0000-0000-0000-000000007101",
    runs: Iterable[Mapping[str, Any]] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock GET /providers/Microsoft.ProcessSimple/environments/{env}/flows/{flow}/runs.

    The *runtime* runs endpoint (maker/owner scope, NOT ``/scopes/admin``) on
    ``api.flow.microsoft.com`` (``service.flow.microsoft.com//.default`` token).
    Backs WD-RUN-001 via ``pp_admin_client.get_flow_runs``.
    """
    return {
        "method": "GET",
        "url": (
            f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/environments/"
            f"{env_id}/flows/{flow_id}/runs"
        ),
        "json": collection(runs or []),
        "status": status,
    }


def insufficient_permissions(
    *,
    env_id: str = MOCK_ENV_ID,
    endpoint: str = "connections",
    flow_id: str = "00000000-0000-0000-0000-000000007101",
) -> dict[str, Any]:
    """Mock a 403 from BAP/PowerApps — the production code maps
    401/403 to {"_error": "insufficient_permissions"} dict.

    See flightcheck/pp_admin_client.py:126-127.
    """
    if endpoint == "connections":
        url = (
            f"{POWERAPPS_BASE}/providers/Microsoft.PowerApps/scopes/admin/environments/"
            f"{env_id}/connections"
        )
    elif endpoint == "flows":
        url = (
            f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/scopes/admin/environments/"
            f"{env_id}/v2/flows"
        )
    elif endpoint == "flow_runs":
        url = (
            f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/environments/"
            f"{env_id}/flows/{flow_id}/runs"
        )
    elif endpoint == "environments":
        url = (
            f"{BAP_BASE}/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments"
        )
    else:
        raise ValueError(f"unknown endpoint {endpoint!r}")

    return {
        "method": "GET",
        "url": url,
        "json": {
            "error": {
                "code": "Forbidden",
                "message": "User does not have Power Platform Admin role.",
            }
        },
        "status": 403,
    }



