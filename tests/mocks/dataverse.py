# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Mock response builders for the Dataverse Web API v9.

# ─────────────────────────────────────────────────────────────────
# MOCK_STATUS = "documented"
#
# Backed by Microsoft Learn prose docs (no public schema URL — the
# per-org $metadata at {org}/api/data/v9.2/$metadata requires auth).
# Each builder's response shape comes from the example response in
# the cited MS Learn operation page.
#
# Tier: documented (see tests/fixtures/cassettes/INDEX.md
#       "API tier registry")
# ─────────────────────────────────────────────────────────────────

Used by unit tests for any FlightCheck check that reads Dataverse
(currently the Workday env var checks via auth.query_all).

Each builder returns a (url, json_body, status, headers) tuple suitable
for handing to `responses.add(...)` directly.

References:
- Dataverse Web API: https://learn.microsoft.com/power-apps/developer/data-platform/webapi/perform-operations-web-api
- WhoAmI function: https://learn.microsoft.com/power-apps/developer/data-platform/webapi/use-web-api-functions
- GetPreferredSolution function: https://learn.microsoft.com/power-apps/developer/data-platform/webapi/reference/getpreferredsolution
- publisher: https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/publisher
- environmentvariabledefinition: https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/environmentvariabledefinition
- environmentvariablevalue: https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/environmentvariablevalue
- Production source: solutions/ess-maker-skills/scripts/auth.py
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping
from urllib.parse import quote

# Validation status — read by tests/conftest.py:require_validated_mock().
MOCK_STATUS = "documented"

# Stable mock identity values, importable so test code never has to repeat them.
MOCK_USER_ID = "00000000-0000-0000-0000-000000002222"
MOCK_BUSINESS_UNIT_ID = "00000000-0000-0000-0000-000000004444"
MOCK_ORGANIZATION_ID = "00000000-0000-0000-0000-000000005555"

DATAVERSE_API_VERSION = "v9.2"


# ────────────────────────────────────────────────────────────────────────
# URL helpers
# ────────────────────────────────────────────────────────────────────────

def _api(base_url: str, path: str) -> str:
    """Build a Dataverse Web API URL: base + /api/data/v9.2/ + path."""
    return f"{base_url.rstrip('/')}/api/data/{DATAVERSE_API_VERSION}/{path.lstrip('/')}"


def _query_url(
    base_url: str,
    entity_set: str,
    *,
    select: str | None = None,
    filter_expr: str | None = None,
    top: int | None = None,
) -> str:
    """Build an OData query URL. Mirrors the shape auth.query_all builds."""
    url = _api(base_url, entity_set)
    qs: list[str] = []
    if select:
        qs.append(f"$select={quote(select, safe=',')}")
    if filter_expr:
        qs.append(f"$filter={quote(filter_expr, safe='')}")
    if top is not None:
        qs.append(f"$top={top}")
    if qs:
        url += "?" + "&".join(qs)
    return url


# Public alias — tests that register custom error-case responses (e.g. 500
# on a real query URL) import this instead of touching the underscore name.
build_query_url = _query_url


# ────────────────────────────────────────────────────────────────────────
# Response payload builders (functions that return dicts, not full registrations)
# ────────────────────────────────────────────────────────────────────────

def who_am_i(
    *,
    user_id: str = MOCK_USER_ID,
    business_unit_id: str = MOCK_BUSINESS_UNIT_ID,
    organization_id: str = MOCK_ORGANIZATION_ID,
) -> dict[str, Any]:
    """Build a WhoAmI() response.

    Cited consumers:
      - solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py:240
        (derive_environment_id reads OrganizationId)
      - kit setup flows that use UserId for ownership checks

    Schema reference: https://learn.microsoft.com/dotnet/api/microsoft.crm.sdk.messages.whoamiresponse
    """
    return {
        "@odata.context": "$metadata#Microsoft.Dynamics.CRM.WhoAmIResponse",
        "BusinessUnitId": business_unit_id,
        "UserId": user_id,
        "OrganizationId": organization_id,
    }


def env_var_def(
    *,
    definition_id: str | None = None,
    schema_name: str = "EmployeeContextRequestAccountName",
    display_name: str = "Mock Env Var",
    type_value: int = 100000000,  # String
) -> dict[str, Any]:
    """Build a single environmentvariabledefinitions record.

    Cited consumers:
      - flightcheck/checks/workday.py — reads schemaname, definitionid
        to look up matching environmentvariablevalues
    """
    return {
        "@odata.etag": 'W/"1"',
        "environmentvariabledefinitionid": definition_id
        or "00000000-0000-0000-0000-000000006001",
        "schemaname": schema_name,
        "displayname": display_name,
        "type": type_value,
    }


def env_var_value(
    *,
    value_id: str | None = None,
    definition_id: str = "00000000-0000-0000-0000-000000006001",
    schema_name: str = "EmployeeContextRequestAccountName",
    value: str = "ISU_MOCK",
) -> dict[str, Any]:
    """Build a single environmentvariablevalues record."""
    return {
        "@odata.etag": 'W/"1"',
        "environmentvariablevalueid": value_id
        or "00000000-0000-0000-0000-000000007001",
        "_environmentvariabledefinitionid_value": definition_id,
        "schemaname": schema_name,
        "value": value,
    }


WORKDAY_SOAP_CONNECTOR_ID = "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"


def connection_ref(
    *,
    ref_id: str | None = None,
    logical_name: str,
    display_name: str,
    connector_id: str,
    connection_id: str | None = None,
    statuscode: int = 1,
) -> dict[str, Any]:
    """Build a single connectionreferences record matching the shape
    captured in tests/fixtures/cassettes/dataverse_workday_connection_refs_*.yaml.

    Cited consumers:
      - flightcheck/checks/workday.py — `_check_package_flavor` (WD-PKG-001)
        reads `connectorid` + `connectionreferencelogicalname` to fingerprint
        the Workday install flavor (simplified vs full / legacy SOAP+custom).
      - flightcheck/checks/workday.py — `_check_package_connection_completeness`
        (WD-CONN-012) reads `connectionid` + `statuscode` to verify each
        expected Workday ref is bound to an active connection.
      - flightcheck/checks/environment.py:222 — `ENV-004` (general
        connection-reference binding-state check).

    Schema reference:
      https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/connectionreference
    """
    return {
        "@odata.etag": 'W/"1"',
        "connectionreferenceid": ref_id or "00000000-0000-0000-0000-000000008001",
        "connectionreferencelogicalname": logical_name,
        "connectionreferencedisplayname": display_name,
        "connectorid": connector_id,
        "connectionid": connection_id,
        "statuscode": statuscode,
    }


def workday_connection_ref(
    *,
    suffix: str,
    display_name: str,
    publisher_prefix: str = "new",
    connection_id: str | None = "shared-workdaysoap-00000000-0000-0000-0000-000000001111",
    statuscode: int = 1,
    ref_id: str | None = None,
) -> dict[str, Any]:
    """Build a Workday connectionreferences record.

    The `suffix` (e.g. "ff0df", "0786a", "d6081") is the deterministic
    fingerprint shipped by Microsoft inside the install solution at
    build time. `publisher_prefix` defaults to `new_` (Default
    Publisher) but is configurable so tests can verify the WD-PKG-001
    matcher is publisher-prefix-agnostic.
    """
    return connection_ref(
        ref_id=ref_id,
        logical_name=f"{publisher_prefix}_sharedworkdaysoap_{suffix}",
        display_name=display_name,
        connector_id=WORKDAY_SOAP_CONNECTOR_ID,
        connection_id=connection_id,
        statuscode=statuscode,
    )


# Canonical fixture-rows mirroring the captured cassettes. Keep these
# in sync with:
#   tests/fixtures/cassettes/dataverse_workday_connection_refs_simplified.yaml
#   tests/fixtures/cassettes/dataverse_workday_connection_refs_full.yaml
def workday_connection_refs_simplified() -> list[dict[str, Any]]:
    """Workday connection refs as they appear in a simplified-install tenant
    (1 ref: OAuthUser / OBO)."""
    return [
        workday_connection_ref(suffix="ff0df", display_name="OAuthUser"),
    ]


def workday_connection_refs_full() -> list[dict[str, Any]]:
    """Workday connection refs as they appear in a full / legacy SOAP+custom
    install tenant (3 refs: OAuthUser + 2 ISU roles)."""
    return [
        workday_connection_ref(suffix="ff0df", display_name="OAuthUser"),
        workday_connection_ref(suffix="0786a", display_name="Generic User"),
        workday_connection_ref(suffix="d6081", display_name="Context Generic User"),
    ]


def collection(
    records: Iterable[Mapping[str, Any]],
    *,
    next_link: str | None = None,
) -> dict[str, Any]:
    """Wrap a list of records in the OData v4 collection envelope.

    Pass next_link to test pagination — auth.query_all follows
    @odata.nextLink until it stops being present.
    """
    payload: dict[str, Any] = {
        "@odata.context": "$metadata#collection",
        "value": list(records),
    }
    if next_link:
        payload["@odata.nextLink"] = next_link
    return payload


# ────────────────────────────────────────────────────────────────────────
# `responses` registration helpers
#
# Each returns a kwargs dict ready for `responses.add(**foo(...))`. Tests
# that need fine-grained control can build payloads via the functions
# above and call `responses.add(...)` directly.
# ────────────────────────────────────────────────────────────────────────

def query(
    *,
    base_url: str,
    entity_set: str,
    records: Iterable[Mapping[str, Any]] | None = None,
    select: str | None = None,
    filter_expr: str | None = None,
    next_link: str | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock a paginated table query (auth.query_all).

    The returned URL includes the OData query string so `responses`
    matches strictly. Tests that need looser matching (e.g. the actual
    URL the production code builds may have an extra `&pagesize=...`)
    can build the kwargs by hand using `_query_url` + `collection`.
    """
    return {
        "method": "GET",
        "url": _query_url(base_url, entity_set, select=select, filter_expr=filter_expr),
        "json": collection(records or [], next_link=next_link),
        "status": status,
    }


def whoami(*, base_url: str, **kwargs: Any) -> dict[str, Any]:
    """Mock the WhoAmI() function call."""
    return {
        "method": "GET",
        "url": _api(base_url, "WhoAmI()"),
        "json": who_am_i(**kwargs),
        "status": 200,
    }


def get_preferred_solution(
    *,
    base_url: str,
    solution_id: str | None = None,
    uniquename: str | None = None,
    friendlyname: str | None = None,
) -> dict[str, Any]:
    """Mock ``GET /GetPreferredSolution()``.

    Web API reference:
      https://learn.microsoft.com/power-apps/developer/data-platform/webapi/reference/getpreferredsolution

    UNCERTAINTY: the MS Learn reference page documents the return type
    as ``crmbaseentity`` but does NOT include an example response body.
    The shape used here is derived by composing three MS-documented
    sources:

      1. The .NET SDK ``GetPreferredSolutionResponse.PreferredSolution``
         property is typed as ``Microsoft.Xrm.Sdk.Entity`` representing
         a ``solution`` row:
         https://learn.microsoft.com/dotnet/api/microsoft.crm.sdk.messages.getpreferredsolutionresponse.preferredsolution
      2. The ``solution`` entity reference documents the field names
         (``solutionid``, ``uniquename``, ``friendlyname``):
         https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/solution
      3. The Web API serialisation conventions for a single-entity
         response use the ``$metadata#<entityset>/$entity``
         ``@odata.context`` form:
         https://learn.microsoft.com/power-apps/developer/data-platform/webapi/retrieve-entity-using-web-api#basic-retrieve-operations

    When ``solution_id`` is None, ``solutionid`` is omitted from the
    body — the production check treats a missing ``solutionid`` as
    "no preferred solution selected" rather than asserting on any
    specific empty-response shape.
    """
    body: dict[str, Any] = {
        "@odata.context": _api(base_url, "$metadata#solutions/$entity"),
    }
    if solution_id is not None:
        body["solutionid"] = solution_id
        body["uniquename"] = uniquename or "ESSCustomization"
        body["friendlyname"] = friendlyname or "ESS Customization"
    return {
        "method": "GET",
        "url": _api(base_url, "GetPreferredSolution()"),
        "json": body,
        "status": 200,
    }


def publisher(
    *,
    base_url: str,
    publisher_id: str,
    uniquename: str = "ContosoPublisher",
    customizationprefix: str = "contoso",
    friendlyname: str | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock ``GET /publishers({publisherid})?$select=...``.

    Web API reference:
      https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/publisher

    The MS Learn publisher entity reference documents the columns used
    here (``publisherid``, ``uniquename``, ``customizationprefix``,
    ``friendlyname``). The ENV-009 check fetches this record after the
    preferred-solution match to detect when the solution is bound to
    the env's auto-provisioned Default Publisher (``uniquename``
    starting with ``DefaultPublisher``) instead of a customer-created
    publisher.

    Defaults model a customer-created publisher with the ``contoso``
    prefix. To simulate the Default Publisher, callers should pass
    ``uniquename="DefaultPublisherorg<suffix>"`` and
    ``customizationprefix="cr<NNN>"`` - one such Default Publisher value
    (``DefaultPublisherorgeeac24d0``) is observable in
    ``tests/fixtures/cassettes/island_gateway_botcomponents.yaml``.

    The production call site uses the same ``$select`` field list every
    time; this builder hard-codes that querystring so ``responses``
    matches strictly. A non-200 ``status`` causes the body to be
    returned with the supplied status code so callers can drive the
    "publisher fetch failed" code path.
    """
    body: dict[str, Any] = {
        "@odata.context": _api(
            base_url,
            "$metadata#publishers(uniquename,customizationprefix,friendlyname)/$entity",
        ),
        "publisherid": publisher_id,
        "uniquename": uniquename,
        "customizationprefix": customizationprefix,
        "friendlyname": friendlyname or uniquename,
    }
    url = (
        _api(base_url, f"publishers({publisher_id})")
        + f"?$select={quote('uniquename,customizationprefix,friendlyname', safe=',')}"
    )
    return {
        "method": "GET",
        "url": url,
        "json": body,
        "status": status,
    }


def discover_tenant_challenge(
    *,
    base_url: str,
    tenant_id: str = "00000000-0000-0000-0000-000000001111",
    quoted: bool = False,
    include_resource_id: bool = False,
) -> dict[str, Any]:
    """Mock the auth.discover_tenant() probe.

    auth.discover_tenant sends an unauthenticated GET to /api/data/v9.2/
    and parses the WWW-Authenticate header in the 401 response to extract
    the tenant ID. The mock has to return the right header shape or
    discover_tenant falls back to the literal string "organizations".

    Three header shapes are observed:

      1. Bearer authorization_uri=https://login.microsoftonline.com/<tenant>
         (unquoted, alone) — what Microsoft actually sends for Dataverse;
         the kit's discover_tenant parses this correctly.

      2. Bearer authorization_uri=https://login.microsoftonline.com/<tenant>,
         resource_id=https://<host>
         (unquoted, with resource_id) — also a valid Microsoft format;
         kit handles it correctly because the comma stops the regex.

      3. Bearer authorization_uri="https://login.microsoftonline.com/<tenant>"
         (quoted form, RFC 7235 style) — the kit's regex
         `login\\.microsoftonline\\.com/([^/]+)` over-captures the closing
         quote and returns '<tenant>"' as the tenant id. See the
         regression test in tests/test_mocks_dataverse.py and the TODO
         in solutions/ess-maker-skills/scripts/auth.py:110.

    Defaults to shape 1 (unquoted, alone) since that's what Dataverse sends
    in practice. Pass `quoted=True` to exercise the regex bug; pass
    `include_resource_id=True` to add a `, resource_id=...` suffix.

    See solutions/ess-maker-skills/scripts/auth.py:99-113.
    """
    q = '"' if quoted else ""
    parts = [f"authorization_uri={q}https://login.microsoftonline.com/{tenant_id}{q}"]
    if include_resource_id:
        parts.append(f"resource_id={q}{base_url}{q}")
    header = "Bearer " + ", ".join(parts)

    return {
        "method": "GET",
        "url": _api(base_url, ""),  # trailing slash matters
        "status": 401,
        "headers": {
            "WWW-Authenticate": header,
        },
    }


def auth_expired(
    *, base_url: str, entity_set: str = "environmentvariabledefinitions"
) -> dict[str, Any]:
    """Mock a 401 on a Dataverse query — used to test AuthExpiredError raising."""
    return {
        "method": "GET",
        "url": _api(base_url, entity_set),
        "json": {
            "error": {
                "code": "0x80048306",
                "message": "Authentication failed.",
            }
        },
        "status": 401,
    }


def create_record_response(
    *,
    base_url: str,
    entity_set: str,
    record_id: str,
    id_key: str | None = None,
    return_representation: bool = True,
    include_entity_id_header: bool = True,
    status: int = 201,
) -> dict[str, Any]:
    """Mock a POST create against ``{base}/api/data/v9.2/{entity_set}``.

    Models the two ways Dataverse communicates the new record's key back to
    the client on create, so tests can pin that ``auth.create_record`` reads
    the id for ANY entity set (not just ``botcomponents``):

      1. The ``OData-EntityId`` response header — returned on every create,
         shaped ``{base}/api/data/v9.2/{entity_set}({record_id})``. This is
         the entity-agnostic source and is present even on a ``204`` create
         with no ``Prefer: return=representation``.
      2. The representation body (only when the client sends
         ``Prefer: return=representation``, which ``create_record`` does),
         whose primary-key column is entity-specific:
         ``workflows`` → ``workflowid``, ``botcomponents`` → ``botcomponentid``,
         ``connectionreferences`` → ``connectionreferenceid``.

    ``id_key`` overrides the derived body primary-key column; when omitted it
    is derived by singularising ``entity_set`` (strip a trailing ``s``) and
    appending ``id`` — the Dataverse convention for these entities. Pass
    ``return_representation=False`` (typically with ``status=204``) to model a
    header-only create, and ``include_entity_id_header=False`` to force the
    body-only fallback path.

    Web API create reference:
      https://learn.microsoft.com/power-apps/developer/data-platform/webapi/create-entity-web-api
    """
    kwargs: dict[str, Any] = {
        "method": "POST",
        "url": _api(base_url, entity_set),
        "status": status,
    }
    if include_entity_id_header:
        kwargs["headers"] = {
            "OData-EntityId": _api(base_url, f"{entity_set}({record_id})"),
        }
    if return_representation:
        key = id_key or (
            entity_set[:-1] + "id" if entity_set.endswith("s") else entity_set + "id"
        )
        kwargs["json"] = {
            "@odata.context": _api(base_url, f"$metadata#{entity_set}/$entity"),
            key: record_id,
        }
    return kwargs


def associate_ref_response(
    *,
    base_url: str,
    entity_set: str,
    record_id: str,
    nav_property: str,
    status: int = 204,
) -> dict[str, Any]:
    """Mock an N:N associate via ``POST {entity_set}({id})/{nav}/$ref``.

    Dataverse creates a many-to-many link by POSTing an ``@odata.id`` pointer
    to the collection-valued navigation property's ``/$ref`` endpoint and
    returns ``204 No Content`` on success. Used to test the
    ``botcomponent_workflow`` link that wires a system-topic botcomponent to
    the workflow it invokes.

    Web API associate reference:
      https://learn.microsoft.com/power-apps/developer/data-platform/webapi/associate-disassociate-entities-using-web-api
    """
    return {
        "method": "POST",
        "url": _api(base_url, f"{entity_set}({record_id})/{nav_property}/$ref"),
        "status": status,
    }


def pva_publish_response(
    *,
    base_url: str,
    bot_id: str,
    status: int = 200,
) -> dict[str, Any]:
    """Mock the ``PvaPublish`` bound action (publish a Copilot Studio bot).

    ``PvaPublish`` is bound to the ``bot`` entity, so the bot is addressed via
    the URL binding — ``POST {base}/api/data/v9.2/bots({bot_id})/
    Microsoft.Dynamics.CRM.PvaPublish`` — not an unbound action with a
    ``botid`` body. Publishing makes pushed botcomponent changes go live.
    """
    return {
        "method": "POST",
        "url": _api(base_url, f"bots({bot_id})/Microsoft.Dynamics.CRM.PvaPublish"),
        "status": status,
        "json": {},
    }


def record_get(
    *,
    base_url: str,
    entity_set: str,
    record_id: str,
    id_key: str,
    exists: bool = True,
) -> dict[str, Any]:
    """Mock ``GET {entity_set}({record_id})?$select={id_key}``.

    Used to test existence checks. Dataverse returns a clean ``404`` with the
    ``0x80040217`` "Entity … Does Not Exist" error when the record is gone —
    unlike a PATCH against a missing record, which returns an ambiguous
    ``400``. ``exists=False`` models that 404.
    """
    url = _api(base_url, f"{entity_set}({record_id})") + f"?$select={id_key}"
    if exists:
        return {
            "method": "GET",
            "url": url,
            "status": 200,
            "json": {
                "@odata.context": _api(base_url, f"$metadata#{entity_set}/$entity"),
                id_key: record_id,
            },
        }
    return {
        "method": "GET",
        "url": url,
        "status": 404,
        "json": {
            "error": {
                "code": "0x80040217",
                "message": (
                    f"Entity '{entity_set[:-1]}' With Id = {record_id} "
                    f"Does Not Exist"
                ),
            }
        },
    }
