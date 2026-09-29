# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lifecycle checkpoints for the DA HR ServiceNow HRSD provider."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from connect_servicenow_da import (
    AUTH_MODE,
    CONNECTOR_NAME,
    HR_SCHEMA_NAME,
    PROVIDER_KEY,
    SERVICENOW_CONNECTOR_APP_ID,
    normalize_client_id,
    normalize_instance_name,
    required_servicenow_prerequisites,
    summarize_components,
)

from ..agent_scope import validate_agent_slug
from ..runner import CheckResult, Priority, Role, Status


_CATEGORY = "ServiceNow DA HRSD"
_ROLES = [Role.ESS_MAKER.value, Role.SERVICENOW_ADMIN.value]
_MS_GRAPH_RESOURCE_APP_ID = "00000003-0000-0000-c000-000000000000"
_GRAPH_DELEGATED_SCOPE_IDS = {
    "openid": "37f7f235-527c-4136-accd-4a02d197296e",
    "profile": "14dad69e-099b-42c9-810b-d002981feec1",
    "User.Read": "e1fe6dd8-ba31-4d61-89e7-88639da4683d",
}
def _result(
    checkpoint_id: str,
    status: str,
    description: str,
    result: str,
    remediation: str = "",
) -> CheckResult:
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category=_CATEGORY,
        priority=Priority.HIGH.value,
        status=status,
        description=description,
        result=result,
        remediation=remediation,
        roles=_ROLES,
    )


def _active_agent(runner) -> tuple[str, dict[str, Any]] | None:
    config = getattr(runner, "config", {}) or {}
    if not isinstance(config, dict):
        return None
    slug = (
        getattr(runner, "agent_slug", None)
        or config.get("activeAgent")
        or (config.get("agent") or {}).get("slug")
    )
    try:
        slug = validate_agent_slug(str(slug))
    except ValueError:
        return None
    agents = config.get("agents")
    if isinstance(agents, list):
        for agent in agents:
            if isinstance(agent, dict) and agent.get("slug") == slug:
                return slug, agent
    legacy = config.get("agent")
    if isinstance(legacy, dict) and legacy.get("slug") == slug:
        return slug, legacy
    return None


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _load_state(slug: str) -> dict[str, Any]:
    path = (
        Path(".local/connect")
        / PROVIDER_KEY
        / "agents"
        / slug
        / "lifecycle.json"
    )
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _connection_status(record: dict[str, Any]) -> str:
    statuses = (record.get("properties") or {}).get("statuses")
    if not isinstance(statuses, list):
        return ""
    token = next(
        (
            value
            for value in statuses
            if isinstance(value, dict) and value.get("target") == "token"
        ),
        next((value for value in statuses if isinstance(value, dict)), {}),
    )
    return str(token.get("status") or "")


def _auth_mode(record: dict[str, Any]) -> str:
    parameters = (record.get("properties") or {}).get(
        "connectionParametersSet"
    )
    return str(
        parameters.get("name") if isinstance(parameters, dict) else ""
    )


def _servicenow_connections(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if str((record.get("properties") or {}).get("apiId") or "")
        .rstrip("/")
        .rsplit("/", 1)[-1]
        .casefold()
        == CONNECTOR_NAME.casefold()
    ]


def run_servicenow_da_hrsd_checks(runner) -> list[CheckResult]:
    selected = _active_agent(runner)
    if selected is None:
        return _all_unavailable(
            Status.FAILED.value,
            "The selected agent could not be resolved.",
            "Select the exact editable ESS HR agent and rerun the checkpoint.",
        )
    slug, agent = selected
    schema = str(
        agent.get("schemaName") or agent.get("schema_name") or ""
    ).casefold()
    if schema != HR_SCHEMA_NAME.casefold():
        return _all_unavailable(
            Status.NOT_CONFIGURED.value,
            f"The selected agent '{slug}' is not the ESS DA HR agent.",
            "Select the Employee Self-Service HR agent.",
        )
    agent_id = str(agent.get("botId") or agent.get("id") or "")
    if not agent_id:
        return _all_unavailable(
            Status.FAILED.value,
            "The selected HR agent has no AgentBuilder ID.",
            "Refresh the local setup handoff for this agent.",
        )
    client = getattr(runner, "agentbuilder", None)
    if client is None:
        return _all_unavailable(
            Status.ERROR.value,
            "AgentBuilder authentication is unavailable.",
            "Sign in to the target environment and retry.",
        )
    try:
        components = client.fetch_components(agent_id)
        has_hrsd_topics = any(
            isinstance(change, dict)
            and "ServiceNowHRSD"
            in str((change.get("component") or {}).get("schemaName") or "")
            for change in components.get("botComponentChanges") or []
        )
        if not has_hrsd_topics:
            return _all_unavailable(
                Status.NOT_CONFIGURED.value,
                f"The selected HR agent '{slug}' has no ServiceNow HRSD topics.",
                "Install the ServiceNow HRSD extension for this exact HR agent.",
            )
        summary = summarize_components(components)
    except Exception as exc:
        return _all_unavailable(
            Status.ERROR.value,
            f"Unable to inspect the HR agent: {type(exc).__name__}: {exc}",
            "Verify AgentBuilder access to the selected environment and retry.",
        )

    state = _load_state(slug)
    evidence = state.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    admin_setup = state.get("adminSetup")
    admin_setup = admin_setup if isinstance(admin_setup, dict) else {}
    component_hash = _hash(components)
    connections: list[dict[str, Any]] = []
    connectivity_error = ""
    connectivity = getattr(runner, "connectivity", None)
    environment_id = str(getattr(runner, "env_id", None) or "")
    if connectivity is None:
        connectivity_error = "Connection inventory authentication is unavailable."
    else:
        try:
            connections = _servicenow_connections(
                connectivity.list_connector_connections(
                    environment_id,
                    CONNECTOR_NAME,
                )
            )
        except Exception as exc:
            connectivity_error = f"{type(exc).__name__}: {exc}"

    return [
        _package_result(slug, summary),
        _preflight_result(admin_setup),
        _plugin_result(admin_setup),
        *_entra_results(getattr(runner, "graph", None), admin_setup),
        _oidc_result(admin_setup),
        _topics_result(summary, evidence, component_hash),
        _credential_result(
            evidence,
            admin_setup,
            connections,
            connectivity_error,
        ),
        _agent_connection_result(
            evidence,
            admin_setup,
            connections,
            connectivity_error,
            component_hash,
        ),
        _parameter_result(evidence, component_hash),
        _publish_result(evidence, component_hash),
        _test_result(evidence, component_hash),
    ]


def _all_unavailable(
    status: str,
    result: str,
    remediation: str,
) -> list[CheckResult]:
    ids = (
        "PKG",
        "ADMIN-PREFLIGHT",
        "PLUGIN",
        "ENTRA-APP",
        "ENTRA-CLAIMS",
        "ENTRA-SCOPE",
        "ENTRA-PREAUTH",
        "ENTRA-PERMISSIONS",
        "ENTRA-CONSENT",
        "OIDC",
        "TOPICS",
        "CREDENTIAL",
        "AGENT-CONNECTION",
        "PARAMETER-SHARING",
        "PUBLISH",
        "TEST",
    )
    return [
        _result(
            f"SN-DA-HRSD-{suffix}-001",
            status,
            f"ServiceNow HRSD {suffix.lower()} readiness",
            result,
            remediation,
        )
        for suffix in ids
    ]


def _package_result(slug: str, summary: dict[str, Any]) -> CheckResult:
    count = summary["serviceNowTopicCount"]
    return _result(
        "SN-DA-HRSD-PKG-001",
        Status.PASSED.value if count else Status.NOT_CONFIGURED.value,
        "ServiceNow HRSD package installed for the selected DA HR agent",
        (
            f"Selected HR agent '{slug}' contains {count} ServiceNow HRSD "
            "topic(s)."
        ),
        (
            "Install the ServiceNow HRSD extension for this exact HR agent."
            if not count
            else ""
        ),
    )


def _phase_handoffs(admin_setup: dict[str, Any]) -> dict[str, Any]:
    value = admin_setup.get("phaseHandoffs")
    return value if isinstance(value, dict) else {}


def _phase_handoff(
    admin_setup: dict[str, Any],
    phase: str,
) -> dict[str, Any]:
    value = _phase_handoffs(admin_setup).get(phase)
    return value if isinstance(value, dict) else {}


def _phase_attested(
    admin_setup: dict[str, Any],
    phase: str,
) -> bool:
    return _phase_handoff(admin_setup, phase).get("status") in {
        "completed",
        "reused",
    }


def _preflight_result(admin_setup: dict[str, Any]) -> CheckResult:
    preflight = admin_setup.get("preflight")
    preflight = preflight if isinstance(preflight, dict) else {}
    discovery = preflight.get("discovery")
    discovery = discovery if isinstance(discovery, dict) else {}
    decision = preflight.get("reuseDecision")
    decision = decision if isinstance(decision, dict) else {}
    if not _phase_attested(admin_setup, "preflight"):
        status = Status.NOT_CONFIGURED.value
        result = "The bundled preflight/reuse handoff is incomplete."
    elif not preflight.get("scenario"):
        status = Status.NOT_CONFIGURED.value
        result = "The Maker has not described which remote setup already exists."
    elif not discovery.get("observedAt"):
        status = Status.NOT_CONFIGURED.value
        result = "Read-only remote setup discovery has not run."
    elif not decision.get("decision"):
        status = Status.NOT_CONFIGURED.value
        result = "The Maker has not approved reuse or configuration of the gaps."
    elif decision.get("discoveryHash") != _hash(discovery):
        status = Status.NOT_CONFIGURED.value
        result = "Remote discovery changed after the Maker's reuse decision."
    else:
        status = Status.PASSED.value
        result = (
            "Read-only discovery completed and the Maker explicitly approved "
            f"'{decision['decision']}'."
        )
    return _result(
        "SN-DA-HRSD-ADMIN-PREFLIGHT-001",
        status,
        "ServiceNow admin setup preflight and reuse decision",
        result,
        (
            "Run the admin preflight, review every discovered remote item, "
            "then explicitly choose reuse or configure the missing items."
            if status != Status.PASSED.value
            else ""
        ),
    )


def _plugin_result(admin_setup: dict[str, Any]) -> CheckResult:
    requirements = required_servicenow_prerequisites(
        str(admin_setup.get("scope") or "hrsd"),
        str(admin_setup.get("authMode") or AUTH_MODE),
    )
    missing = [] if _phase_attested(
        admin_setup,
        "plugin-prerequisites",
    ) else [requirement["id"] for requirement in requirements]
    status = (
        Status.MANUAL.value if not missing else Status.NOT_CONFIGURED.value
    )
    return _result(
        "SN-DA-HRSD-PLUGIN-001",
        status,
        "Scope-derived ServiceNow plugin prerequisites",
        (
            "The ServiceNow admin confirmed HR Core and OIDC capability."
            if not missing
            else "Missing admin confirmation for: " + ", ".join(missing) + "."
        ),
        (
            "Ask a ServiceNow admin to confirm every scope-derived plugin or "
            "capability is installed and Active."
            if missing
            else ""
        ),
    )


def _entra_client_id(admin_setup: dict[str, Any]) -> str:
    evidence = _phase_handoff(
        admin_setup,
        "entra-registration",
    ).get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    value = evidence.get("clientId")
    return str(value or "")


def _entra_manual_or_missing(
    admin_setup: dict[str, Any],
    checkpoint_id: str,
    description: str,
    reason: str,
) -> CheckResult:
    attested = _phase_attested(admin_setup, "entra-registration")
    return _result(
        checkpoint_id,
        Status.MANUAL.value if attested else Status.NOT_CONFIGURED.value,
        description,
        (
            f"{reason} Structured admin evidence is present."
            if attested
            else f"{reason} Structured admin evidence is also missing."
        ),
        (
            "Have the Entra admin complete or confirm the full registration, "
            "then rerun with Microsoft Graph read access when available."
        ),
    )


def _entra_error_results(message: str) -> list[CheckResult]:
    rows = (
        ("APP", "Entra application registration exists"),
        ("CLAIMS", "Entra access-token optional claims"),
        ("SCOPE", "Entra identifier URI and user_impersonation scope"),
        ("PREAUTH", "ServiceNow connector pre-authorization"),
        ("PERMISSIONS", "Microsoft Graph delegated permissions"),
        ("CONSENT", "Tenant-wide admin consent"),
    )
    return [
        _result(
            f"SN-DA-HRSD-ENTRA-{suffix}-001",
            Status.ERROR.value,
            description,
            message,
            "Restore read-only Microsoft Graph access and retry.",
        )
        for suffix, description in rows
    ]


def _entra_results(
    graph,
    admin_setup: dict[str, Any],
) -> list[CheckResult]:
    client_id = _entra_client_id(admin_setup)
    rows = (
        (
            "SN-DA-HRSD-ENTRA-APP-001",
            "Entra application registration exists",
        ),
        (
            "SN-DA-HRSD-ENTRA-CLAIMS-001",
            "Entra access-token optional claims",
        ),
        (
            "SN-DA-HRSD-ENTRA-SCOPE-001",
            "Entra identifier URI and user_impersonation scope",
        ),
        (
            "SN-DA-HRSD-ENTRA-PREAUTH-001",
            "ServiceNow connector pre-authorization",
        ),
        (
            "SN-DA-HRSD-ENTRA-PERMISSIONS-001",
            "Microsoft Graph delegated permissions",
        ),
        (
            "SN-DA-HRSD-ENTRA-CONSENT-001",
            "Tenant-wide admin consent",
        ),
    )
    if not client_id:
        return [
            _result(
                checkpoint_id,
                Status.NOT_CONFIGURED.value,
                description,
                "No Application client ID has been recorded.",
                "Record only the non-secret Application client ID.",
            )
            for checkpoint_id, description in rows
        ]
    try:
        normalized_client_id = normalize_client_id(client_id)
    except Exception as exc:
        return _entra_error_results(str(exc))
    if graph is None:
        return [
            _entra_manual_or_missing(
                admin_setup,
                checkpoint_id,
                description,
                "Microsoft Graph verification is unavailable.",
            )
            for checkpoint_id, description in rows
        ]

    try:
        applications = graph.get_all(
            "/applications",
            params={
                "$filter": f"appId eq '{normalized_client_id}'",
                "$select": (
                    "id,appId,displayName,signInAudience,identifierUris,"
                    "optionalClaims,api,requiredResourceAccess"
                ),
            },
            raise_on_permission_error=True,
        )
    except PermissionError:
        return [
            _entra_manual_or_missing(
                admin_setup,
                checkpoint_id,
                description,
                "Microsoft Graph denied read-only application access.",
            )
            for checkpoint_id, description in rows
        ]
    except Exception as exc:
        return _entra_error_results(
            f"Unable to query Microsoft Graph: {type(exc).__name__}: {exc}"
        )

    if not applications:
        return [
            _result(
                checkpoint_id,
                Status.FAILED.value,
                description,
                (
                    "Microsoft Graph confirms that no application with the "
                    f"recorded client ID {normalized_client_id} exists."
                ),
                "Correct the client ID or have the Entra admin create the app.",
            )
            for checkpoint_id, description in rows
        ]
    application = applications[0]
    api = application.get("api")
    api = api if isinstance(api, dict) else {}
    scopes = api.get("oauth2PermissionScopes")
    scopes = scopes if isinstance(scopes, list) else []
    scope = next(
        (
            value
            for value in scopes
            if isinstance(value, dict)
            and value.get("value") == "user_impersonation"
            and value.get("isEnabled", True)
        ),
        None,
    )
    scope_id = str((scope or {}).get("id") or "")
    optional_claims = application.get("optionalClaims")
    optional_claims = (
        optional_claims if isinstance(optional_claims, dict) else {}
    )
    access_token_claims = optional_claims.get("accessToken")
    access_token_claims = (
        access_token_claims if isinstance(access_token_claims, list) else []
    )
    claim_names = {
        str(value.get("name") or "").casefold()
        for value in access_token_claims
        if isinstance(value, dict)
    }
    missing_claims = sorted({"email", "upn"} - claim_names)
    identifiers = {
        str(value).casefold()
        for value in application.get("identifierUris") or []
    }
    scope_ok = (
        f"api://{normalized_client_id}".casefold() in identifiers
        and bool(scope_id)
    )
    preauthorized = any(
        isinstance(value, dict)
        and str(value.get("appId") or "").casefold()
        == SERVICENOW_CONNECTOR_APP_ID.casefold()
        and scope_id
        in {
            str(permission_id)
            for permission_id in value.get("delegatedPermissionIds") or []
        }
        for value in api.get("preAuthorizedApplications") or []
    )
    graph_access_ids: set[str] = set()
    for resource in application.get("requiredResourceAccess") or []:
        if (
            isinstance(resource, dict)
            and str(resource.get("resourceAppId") or "").casefold()
            == _MS_GRAPH_RESOURCE_APP_ID.casefold()
        ):
            graph_access_ids.update(
                str(value.get("id") or "").casefold()
                for value in resource.get("resourceAccess") or []
                if isinstance(value, dict) and value.get("type") == "Scope"
            )
    missing_permissions = sorted(
        name
        for name, permission_id in _GRAPH_DELEGATED_SCOPE_IDS.items()
        if permission_id.casefold() not in graph_access_ids
    )

    def programmatic(
        checkpoint_id: str,
        description: str,
        passed: bool,
        failure: str,
    ) -> CheckResult:
        if not passed:
            return _result(
                checkpoint_id,
                Status.FAILED.value,
                description,
                failure,
                "Have the Entra admin correct this exact application setting.",
            )
        if not _phase_attested(admin_setup, "entra-registration"):
            return _result(
                checkpoint_id,
                Status.NOT_CONFIGURED.value,
                description,
                "Microsoft Graph verifies the setting, but explicit Maker reuse approval is not recorded.",
                "Confirm this exact existing setting with the admin and record it as reused.",
            )
        return _result(
            checkpoint_id,
            Status.PASSED.value,
            description,
            "Microsoft Graph read-only verification passed.",
        )

    results = [
        programmatic(
            rows[0][0],
            rows[0][1],
            (
                str(application.get("appId") or "").casefold()
                == normalized_client_id.casefold()
                and application.get("signInAudience") == "AzureADMyOrg"
            ),
            "The application is missing or is not single-tenant.",
        ),
        programmatic(
            rows[1][0],
            rows[1][1],
            not missing_claims,
            "Missing access-token optional claim(s): "
            + ", ".join(missing_claims)
            + ".",
        ),
        programmatic(
            rows[2][0],
            rows[2][1],
            scope_ok,
            (
                "The application must expose api://<client-id> and an enabled "
                "user_impersonation scope."
            ),
        ),
        programmatic(
            rows[3][0],
            rows[3][1],
            preauthorized,
            (
                "The ServiceNow connector application is not pre-authorized "
                "for the user_impersonation scope."
            ),
        ),
        programmatic(
            rows[4][0],
            rows[4][1],
            not missing_permissions,
            "Missing Graph delegated permission(s): "
            + ", ".join(missing_permissions)
            + ".",
        ),
    ]

    try:
        service_principals = graph.get_service_principals(
            filter_expr=f"appId eq '{normalized_client_id}'",
            select="id,appId",
            raise_on_permission_error=True,
        )
        grants = (
            graph.get_all(
                "/oauth2PermissionGrants",
                params={
                    "$filter": (
                        f"clientId eq '{service_principals[0]['id']}'"
                    )
                },
                raise_on_permission_error=True,
            )
            if service_principals
            else []
        )
    except PermissionError:
        results.append(
            _entra_manual_or_missing(
                admin_setup,
                rows[5][0],
                rows[5][1],
                "Microsoft Graph denied read-only consent access.",
            )
        )
        return results
    except Exception as exc:
        results.append(
            _result(
                rows[5][0],
                Status.ERROR.value,
                rows[5][1],
                f"Unable to verify admin consent: {type(exc).__name__}: {exc}",
                "Restore read-only Microsoft Graph access and retry.",
            )
        )
        return results
    granted_scopes: set[str] = set()
    for grant in grants:
        if (
            isinstance(grant, dict)
            and grant.get("consentType") == "AllPrincipals"
        ):
            granted_scopes.update(
                str(grant.get("scope") or "").casefold().split()
            )
    required_scopes = {name.casefold() for name in _GRAPH_DELEGATED_SCOPE_IDS}
    missing_consent = sorted(required_scopes - granted_scopes)
    results.append(
        programmatic(
            rows[5][0],
            rows[5][1],
            bool(service_principals) and not missing_consent,
            (
                "Tenant-wide admin consent is missing for: "
                + ", ".join(missing_consent)
                + "."
                if service_principals
                else "The application service principal does not exist."
            ),
        )
    )
    return results


def _oidc_result(admin_setup: dict[str, Any]) -> CheckResult:
    handoff = _phase_handoff(admin_setup, "servicenow-oidc")
    missing = not _phase_attested(admin_setup, "servicenow-oidc")
    mapping = handoff.get("evidence")
    mapping = mapping if isinstance(mapping, dict) else {}
    if missing:
        status = Status.NOT_CONFIGURED.value
        result = "The complete ServiceNow OIDC admin handoff is missing."
    elif not mapping.get("claim") or not mapping.get("userField"):
        status = Status.NOT_CONFIGURED.value
        result = "The OIDC claim-to-user-field mapping is incomplete."
    else:
        status = Status.MANUAL.value
        result = (
            "The ServiceNow admin confirmed security_admin elevation, OIDC "
            f"provider metadata, {mapping['claim']} -> "
            f"{mapping['userField']} mapping, and a matching Active user."
        )
    return _result(
        "SN-DA-HRSD-OIDC-001",
        status,
        "ServiceNow OIDC provider and active-user mapping",
        result,
        (
            "Complete the full guided ServiceNow OIDC step, then record only "
            "the non-secret claim and user-field identifiers."
            if status != Status.MANUAL.value
            else ""
        ),
    )


def _topics_result(
    summary: dict[str, Any],
    evidence: dict[str, Any],
    component_hash: str,
) -> CheckResult:
    total = summary["serviceNowTopicCount"]
    active = summary["activeServiceNowTopicCount"]
    topic_evidence = evidence.get("topics")
    keep_current = (
        isinstance(topic_evidence, dict)
        and topic_evidence.get("customerChoice") == "keep-current"
        and topic_evidence.get("boundComponentHash") == component_hash
    )
    if total and active == total:
        status = Status.PASSED.value
    elif total and keep_current:
        status = Status.MANUAL.value
    else:
        status = Status.NOT_CONFIGURED.value
    return _result(
        "SN-DA-HRSD-TOPICS-001",
        status,
        "ServiceNow HRSD topic readiness",
        f"{active}/{total} ServiceNow HRSD topics are Active.",
        (
            "Enable the inactive HRSD topics or explicitly attest that their "
            "current states should be retained."
            if status != Status.PASSED.value
            else ""
        ),
    )


def _selected_connection(
    evidence: dict[str, Any],
    connections: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    credential = evidence.get("credential")
    credential = credential if isinstance(credential, dict) else {}
    selected_id = str(credential.get("connectionId") or "").casefold()
    match = next(
        (
            record
            for record in connections
            if str(record.get("name") or "").casefold() == selected_id
        ),
        None,
    )
    return match, credential


def _credential_result(
    evidence: dict[str, Any],
    admin_setup: dict[str, Any],
    connections: list[dict[str, Any]],
    error: str,
) -> CheckResult:
    match, credential = _selected_connection(evidence, connections)
    if error:
        status = Status.ERROR.value
        result = error
    elif not _phase_attested(admin_setup, "credential"):
        status = Status.NOT_CONFIGURED.value
        result = "The bundled physical-connection handoff is incomplete."
    elif not credential.get("connectionId"):
        status = Status.NOT_CONFIGURED.value
        result = "No ServiceNow credential has been selected."
    elif match is None:
        status = Status.FAILED.value
        result = "The selected ServiceNow credential is not visible."
    elif (
        _connection_status(match) != "Connected"
        or _auth_mode(match) != AUTH_MODE
    ):
        status = Status.FAILED.value
        result = (
            "The selected ServiceNow credential is not a Connected Microsoft "
            "Entra ID User Login connection."
        )
    else:
        properties = match.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        parameter_set = properties.get("connectionParametersSet")
        parameter_set = (
            parameter_set if isinstance(parameter_set, dict) else {}
        )
        values = parameter_set.get("values")
        values = values if isinstance(values, dict) else {}

        def parameter(name: str) -> Any:
            value = values.get(name)
            return value.get("value") if isinstance(value, dict) else None

        expected_instance = (
            (admin_setup.get("preflight") or {}).get("instanceName")
            if isinstance(admin_setup.get("preflight"), dict)
            else None
        )
        expected_client_id = _entra_client_id(admin_setup)
        actual_instance = parameter("token:InstanceName") or parameter(
            "instance"
        )
        actual_resource = parameter("token:ResourceUri")
        if not expected_instance or not expected_client_id:
            status = Status.NOT_CONFIGURED.value
            result = (
                "The lifecycle does not have a confirmed Instance Name and "
                "Application client ID for exact connection verification."
            )
        elif not actual_instance or not actual_resource:
            status = Status.FAILED.value
            result = (
                "Direct connector inventory did not expose the connection's "
                "Instance Name and Resource URI."
            )
        else:
            try:
                values_match = (
                    normalize_instance_name(str(actual_instance))
                    == expected_instance
                    and normalize_client_id(str(actual_resource))
                    == expected_client_id
                )
            except Exception:
                values_match = False
            if not values_match:
                status = Status.FAILED.value
                result = (
                    "The Connected credential targets a different Instance "
                    "Name or Resource URI. Resource URI must be the exact "
                    "Application client ID, not an api:// URI or object ID."
                )
            else:
                status = Status.PASSED.value
                result = (
                    "Direct connector inventory verifies Connected "
                    "entraIDUserLogin with the exact Instance Name and "
                    "Application client ID."
                )
    return _result(
        "SN-DA-HRSD-CREDENTIAL-001",
        status,
        "ServiceNow HRSD credential health",
        result,
        (
            "Create or select a Connected Microsoft Entra ID User Login "
            "ServiceNow credential."
            if status != Status.PASSED.value
            else ""
        ),
    )


def _binding_evaluation(
    record: dict[str, Any],
    component_hash: str,
    connection_id: str | None = None,
) -> str:
    binding = record.get("binding")
    if not isinstance(binding, dict):
        return "binding-missing"
    if binding.get("componentHash") != component_hash:
        return "revision-stale"

    nested_connection_id = str(binding.get("connectionId") or "")
    legacy_connection_id = str(record.get("connectionId") or "")
    if (
        nested_connection_id
        and legacy_connection_id
        and nested_connection_id.casefold() != legacy_connection_id.casefold()
    ):
        return "connection-conflict"

    recorded_connection_id = nested_connection_id or legacy_connection_id
    if connection_id is not None:
        if not recorded_connection_id:
            return "connection-missing"
        if recorded_connection_id.casefold() != connection_id.casefold():
            return "connection-mismatch"
    return "valid"


def _binding_current(
    record: dict[str, Any],
    component_hash: str,
    connection_id: str | None = None,
) -> bool:
    return (
        _binding_evaluation(record, component_hash, connection_id)
        == "valid"
    )


def _agent_connection_result(
    evidence: dict[str, Any],
    admin_setup: dict[str, Any],
    connections: list[dict[str, Any]],
    error: str,
    component_hash: str,
) -> CheckResult:
    credential_check = _credential_result(
        evidence,
        admin_setup,
        connections,
        error,
    )
    record = evidence.get("agentConnection")
    if credential_check.status not in {
        Status.PASSED.value,
    }:
        status = credential_check.status
        result = credential_check.result
    elif not isinstance(record, dict) or not record.get("makerAttested"):
        status = Status.NOT_CONFIGURED.value
        result = "Current maker evidence for the agent's ServiceNow row is absent."
    else:
        binding_evaluation = _binding_evaluation(
            record,
            component_hash,
            str((evidence.get("credential") or {}).get("connectionId") or ""),
        )
    if (
        credential_check.status == Status.PASSED.value
        and isinstance(record, dict)
        and record.get("makerAttested")
        and binding_evaluation != "valid"
    ):
        status = Status.NOT_CONFIGURED.value
        if binding_evaluation == "revision-stale":
            result = (
                "The prior Agent Connect attestation is stale for this "
                "component revision."
            )
        elif binding_evaluation == "connection-conflict":
            result = (
                "The Agent Connect evidence contains conflicting connection "
                "identities."
            )
        elif binding_evaluation == "connection-mismatch":
            result = (
                "The Agent Connect evidence belongs to a different selected "
                "credential."
            )
        else:
            result = (
                "The Agent Connect evidence does not identify the selected "
                "credential."
            )
    elif credential_check.status == Status.PASSED.value and isinstance(
        record, dict
    ) and record.get("makerAttested"):
        status = Status.MANUAL.value
        result = "Maker attested that the ServiceNow row currently shows Connected."
    return _result(
        "SN-DA-HRSD-AGENT-CONNECTION-001",
        status,
        "ServiceNow credential connected to the selected agent",
        result,
        "Confirm the ServiceNow row in Copilot Studio Connection settings.",
    )


def _parameter_result(
    evidence: dict[str, Any],
    component_hash: str,
) -> CheckResult:
    record = evidence.get("parameterSharing")
    connection_id = str(
        (evidence.get("credential") or {}).get("connectionId") or ""
    )
    valid = (
        isinstance(record, dict)
        and record.get("status") in {"enabled", "not-exposed"}
        and record.get("makerAttested") is True
        and _binding_current(record, component_hash, connection_id)
    )
    return _result(
        "SN-DA-HRSD-PARAMETER-SHARING-001",
        Status.MANUAL.value if valid else Status.NOT_CONFIGURED.value,
        "ServiceNow parameter-sharing behavior",
        (
            f"Maker observed parameter sharing as {record.get('status')}."
            if valid
            else "Current parameter-sharing evidence is absent or stale."
        ),
        "Open Connection parameters and confirm the current control state.",
    )


def _publish_result(
    evidence: dict[str, Any],
    component_hash: str,
) -> CheckResult:
    record = evidence.get("publish")
    if not isinstance(record, dict) or record.get("componentHash") != component_hash:
        status = Status.NOT_CONFIGURED.value
        result = "The current component revision has no publish receipt."
    elif record.get("status") == "completed":
        status = Status.PASSED.value
        result = "The current component revision has a definitive publish receipt."
    elif record.get("status") == "confirmation-required":
        status = Status.MANUAL.value
        result = "Publish was accepted but requires current maker confirmation."
    else:
        status = Status.FAILED.value
        result = "Publish needs remediation; automatic unpublish is unavailable."
    return _result(
        "SN-DA-HRSD-PUBLISH-001",
        status,
        "ServiceNow HRSD agent publish status",
        result,
        "Review Copilot Studio publish details and republish only after explicit confirmation.",
    )


def _test_result(
    evidence: dict[str, Any],
    component_hash: str,
) -> CheckResult:
    record = evidence.get("test")
    publish = evidence.get("publish")
    valid_binding = (
        isinstance(record, dict)
        and isinstance(record.get("binding"), dict)
        and isinstance(publish, dict)
        and record["binding"].get("publishedComponentHash") == component_hash
        and publish.get("componentHash") == component_hash
    )
    if not valid_binding:
        status = Status.NOT_CONFIGURED.value
        result = "No current Test pane evidence is bound to this publish."
    elif record.get("result") == "pass":
        status = Status.MANUAL.value
        result = "Maker recorded a passing HRSD Test pane result."
    else:
        status = Status.FAILED.value
        result = "Maker recorded a failing HRSD Test pane result."
    return _result(
        "SN-DA-HRSD-TEST-001",
        status,
        "ServiceNow HRSD Test pane result",
        result,
        "Run a low-side-effect HRSD prompt in the Test pane and record the current result.",
    )
