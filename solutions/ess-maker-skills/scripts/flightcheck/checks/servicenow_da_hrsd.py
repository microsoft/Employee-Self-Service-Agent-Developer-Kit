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
    _connection_binding_hash,
    _draft_semantic_hash,
    normalize_client_id,
    normalize_instance_name,
    portal_configuration_summary,
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
_ENTRA_PREFIX = "SN-DA-HRSD-ENTRA"


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


def _target_matches(target: str | None, checkpoint_id: str) -> bool:
    if target is None:
        return True
    if target in {_ENTRA_PREFIX, f"{_ENTRA_PREFIX}-*"}:
        return checkpoint_id.startswith(f"{_ENTRA_PREFIX}-")
    return checkpoint_id == target


def _target_rows(
    target: str | None,
    results: list[CheckResult],
) -> list[CheckResult]:
    return [
        result
        for result in results
        if _target_matches(target, result.checkpoint_id)
    ]


def run_servicenow_da_hrsd_checks(runner) -> list[CheckResult]:
    target = getattr(runner, "checkpoint_target", None)
    selected = _active_agent(runner)
    if selected is None:
        return _all_unavailable(
            Status.FAILED.value,
            "The selected agent could not be resolved.",
            "Select the exact editable ESS HR agent and rerun the checkpoint.",
            target=target,
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
            target=target,
        )
    agent_id = str(agent.get("botId") or agent.get("id") or "")
    if not agent_id:
        return _all_unavailable(
            Status.FAILED.value,
            "The selected HR agent has no AgentBuilder ID.",
            "Refresh the local setup handoff for this agent.",
            target=target,
        )
    client = getattr(runner, "agentbuilder", None)
    if client is None:
        return _all_unavailable(
            Status.ERROR.value,
            "AgentBuilder authentication is unavailable.",
            "Sign in to the target environment and retry.",
            target=target,
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
                target=target,
            )
        summary = summarize_components(components)
    except Exception as exc:
        return _all_unavailable(
            Status.ERROR.value,
            f"Unable to inspect the HR agent: {type(exc).__name__}: {exc}",
            "Verify AgentBuilder access to the selected environment and retry.",
            target=target,
        )

    state = _load_state(slug)
    evidence = state.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    admin_setup = state.get("adminSetup")
    admin_setup = admin_setup if isinstance(admin_setup, dict) else {}
    if target == "SN-DA-HRSD-PKG-001":
        return [_package_result(slug, summary)]
    if target == "SN-DA-HRSD-ADMIN-PREFLIGHT-001":
        return [_preflight_result(admin_setup)]
    if target == "SN-DA-HRSD-PLUGIN-001":
        return [_plugin_result(admin_setup)]
    if target is not None and target.startswith(f"{_ENTRA_PREFIX}-"):
        return _target_rows(
            target,
            _entra_results(getattr(runner, "graph", None), admin_setup),
        )
    if target in {_ENTRA_PREFIX, f"{_ENTRA_PREFIX}-*"}:
        return _entra_results(getattr(runner, "graph", None), admin_setup)
    if target == "SN-DA-HRSD-OIDC-001":
        return [_oidc_result(admin_setup)]
    if target == "SN-DA-HRSD-PORTAL-001":
        return [_portal_result(components, admin_setup)]

    component_hash = (
        _hash(components)
        if target
        in {
            "SN-DA-HRSD-TOPICS-001",
            "SN-DA-HRSD-TEST-001",
            "SN-DA-HRSD-PUBLISH-001",
            None,
        }
        else ""
    )
    if target == "SN-DA-HRSD-TOPICS-001":
        return [_topics_result(summary, evidence, component_hash)]
    if target == "SN-DA-HRSD-PUBLISH-001":
        try:
            draft_semantic_hash = _draft_semantic_hash(components)
        except Exception as exc:
            return _all_unavailable(
                Status.ERROR.value,
                f"Unable to inspect the HR agent draft identity: "
                f"{type(exc).__name__}: {exc}",
                "Verify the selected HR agent component state and retry.",
                target=target,
            )
        return [
            _publish_result(
                evidence,
                component_hash,
                draft_semantic_hash,
            )
        ]

    needs_inventory = target in {
        "SN-DA-HRSD-CREDENTIAL-001",
        "SN-DA-HRSD-AGENT-CONNECTION-001",
        "SN-DA-HRSD-TEST-001",
        None,
    }
    connections: list[dict[str, Any]] = []
    connectivity_error = ""
    if needs_inventory:
        connectivity = getattr(runner, "connectivity", None)
        environment_id = str(getattr(runner, "env_id", None) or "")
        if connectivity is None:
            connectivity_error = (
                "Connection inventory authentication is unavailable."
            )
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

    credential_result = _credential_result(
        evidence,
        admin_setup,
        connections,
        connectivity_error,
    )
    if target == "SN-DA-HRSD-CREDENTIAL-001":
        return [credential_result]

    needs_draft_identity = target in {
        "SN-DA-HRSD-AGENT-CONNECTION-001",
        "SN-DA-HRSD-TEST-001",
        None,
    }
    draft_semantic_hash = ""
    current_connection_binding_hash = None
    if needs_draft_identity:
        try:
            draft_semantic_hash = _draft_semantic_hash(components)
            if target in {"SN-DA-HRSD-TEST-001", None}:
                current_connection_binding_hash = (
                    _connection_binding_hash(
                        {
                            "agent": {
                                "id": agent.get("botId"),
                                "workspace_slug": slug,
                            },
                            "environment": {
                                "id": str(
                                    getattr(runner, "env_id", None) or ""
                                )
                            },
                        },
                        state,
                        components,
                        require_agent_attestation=False,
                    )
                    if isinstance(evidence.get("credential"), dict)
                    and evidence["credential"].get("connectionId")
                    else None
                )
        except Exception as exc:
            return _all_unavailable(
                Status.ERROR.value,
                f"Unable to inspect the HR agent draft identity: "
                f"{type(exc).__name__}: {exc}",
                "Verify the selected HR agent component state and retry.",
                target=target,
            )

    agent_connection_result = _agent_connection_result(
        evidence,
        credential_result,
        draft_semantic_hash,
    )
    if target == "SN-DA-HRSD-AGENT-CONNECTION-001":
        return [agent_connection_result]

    topics_result = _topics_result(summary, evidence, component_hash)
    portal_result = _portal_result(components, admin_setup)
    if target == "SN-DA-HRSD-TEST-001":
        return [
            _test_result(
                evidence,
                draft_semantic_hash,
                current_connection_binding_hash,
                topics_result,
                portal_result,
                credential_result,
                agent_connection_result,
            )
        ]
    test_result = _test_result(
        evidence,
        draft_semantic_hash,
        current_connection_binding_hash,
        topics_result,
        portal_result,
        credential_result,
        agent_connection_result,
    )
    return [
        _package_result(slug, summary),
        _preflight_result(admin_setup),
        _plugin_result(admin_setup),
        *_entra_results(getattr(runner, "graph", None), admin_setup),
        _oidc_result(admin_setup),
        topics_result,
        portal_result,
        credential_result,
        agent_connection_result,
        test_result,
        _publish_result(
            evidence,
            component_hash,
            draft_semantic_hash,
        ),
    ]


def _all_unavailable(
    status: str,
    result: str,
    remediation: str,
    *,
    target: str | None = None,
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
        "PORTAL",
        "CREDENTIAL",
        "AGENT-CONNECTION",
        "TEST",
        "PUBLISH",
    )
    return _target_rows(
        target,
        [
        _result(
            f"SN-DA-HRSD-{suffix}-001",
            status,
            f"ServiceNow HRSD {suffix.lower()} readiness",
            result,
            remediation,
        )
        for suffix in ids
        ],
    )


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
    if not _phase_attested(admin_setup, "preflight"):
        status = Status.NOT_CONFIGURED.value
        result = "The bundled preflight discovery handoff is incomplete."
    elif not preflight.get("instanceName"):
        status = Status.NOT_CONFIGURED.value
        result = "The public ServiceNow instance URL is not known."
    elif not discovery.get("observedAt"):
        status = Status.NOT_CONFIGURED.value
        result = "Read-only remote setup discovery has not run."
    elif not isinstance(discovery.get("connectionCandidates"), list):
        status = Status.NOT_CONFIGURED.value
        result = "Read-only physical-connection discovery is incomplete."
    elif not isinstance(discovery.get("requiredPlugins"), list):
        status = Status.NOT_CONFIGURED.value
        result = "Scope-derived prerequisite discovery is incomplete."
    else:
        status = Status.PASSED.value
        result = (
            "Read-only resource discovery completed. Valid existing items are "
            "reused automatically; missing or unhealthy items continue to "
            "their owning setup phase."
        )
    return _result(
        "SN-DA-HRSD-ADMIN-PREFLIGHT-001",
        status,
        "ServiceNow admin setup preflight discovery",
        result,
        (
            "Run the admin preflight and review every discovered remote item. "
            "Each later phase will verify and reuse valid items or configure "
            "only the missing or unhealthy item it owns."
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
            "The ServiceNow admin confirmed HR Service Delivery Core."
            if not missing
            else "Missing admin confirmation for: " + ", ".join(missing) + "."
        ),
        (
            "Ask a ServiceNow admin to confirm HR Service Delivery Core is "
            "installed and Active."
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
        graph_service_principals = graph.get_service_principals(
            filter_expr=f"appId eq '{_MS_GRAPH_RESOURCE_APP_ID}'",
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
    required_scopes = {name.casefold() for name in _GRAPH_DELEGATED_SCOPE_IDS}
    graph_resource_id = (
        str(graph_service_principals[0].get("id") or "").casefold()
        if graph_service_principals
        else ""
    )
    graph_grants = [
        grant
        for grant in grants
        if isinstance(grant, dict)
        and str(grant.get("resourceId") or "").casefold()
        == graph_resource_id
    ]
    granted_scopes: set[str] = set()
    for grant in graph_grants:
        if grant.get("consentType") == "AllPrincipals":
            granted_scopes.update(
                str(grant.get("scope") or "").casefold().split()
            )
    missing_consent = sorted(required_scopes - granted_scopes)
    results.append(
        programmatic(
            rows[5][0],
            rows[5][1],
            bool(service_principals)
            and bool(graph_resource_id)
            and not missing_consent,
            (
                "Tenant-wide admin consent is missing for: "
                + ", ".join(missing_consent)
                + "."
                if service_principals and graph_resource_id
                else (
                    "The Microsoft Graph resource service principal does not "
                    "exist."
                    if service_principals
                    else "The application service principal does not exist."
                )
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
    elif mapping.get("oidcCapabilityConfirmed") is not True:
        status = Status.NOT_CONFIGURED.value
        result = "The ServiceNow OIDC capability confirmation is missing."
    elif mapping.get("runbookCompleted") is not True:
        status = Status.NOT_CONFIGURED.value
        result = "The complete ServiceNow OIDC runbook attestation is missing."
    elif (
        mapping.get("mappingDetailsCollected") is not False
        or "claim" in mapping
        or "userField" in mapping
    ):
        status = Status.NOT_CONFIGURED.value
        result = (
            "The OIDC handoff does not use the bounded privacy-minimized "
            "completion evidence contract."
        )
    else:
        status = Status.MANUAL.value
        result = (
            "The ServiceNow admin confirmed OIDC capability, security_admin "
            "elevation, provider metadata, claim mapping, and a matching "
            "Active user without returning mapping or employee identity data."
        )
    return _result(
        "SN-DA-HRSD-OIDC-001",
        status,
        "ServiceNow OIDC provider and active-user mapping",
        result,
        (
            "Complete or re-verify the full guided ServiceNow OIDC runbook, "
            "then record the bounded completion attestation."
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


def _portal_result(
    components: dict[str, Any],
    admin_setup: dict[str, Any],
) -> CheckResult:
    preflight = admin_setup.get("preflight")
    preflight = preflight if isinstance(preflight, dict) else {}
    expected_instance = preflight.get("instanceName")
    try:
        portal = portal_configuration_summary(
            components,
            expected_instance_name=(
                expected_instance
                if isinstance(expected_instance, str)
                else None
            ),
        )
    except Exception as exc:
        return _result(
            "SN-DA-HRSD-PORTAL-001",
            Status.ERROR.value,
            "ServiceNow HRSD employee portal Base URI",
            f"Unable to inspect the exact portal configuration: "
            f"{type(exc).__name__}: {exc}",
            (
                "Open Copilot Studio Topics -> ServiceNow HRSD Setup "
                "Configurations and review the Set ServiceNow Portal BaseURI "
                "node without overwriting unrelated topic content."
            ),
        )
    if portal["valid"]:
        status = Status.PASSED.value
        result = (
            "The exact Setup Configurations topic has an HTTPS employee portal "
            f"path on the confirmed ServiceNow instance: {portal['path']}."
        )
        remediation = ""
    elif portal["reason"] == "wrong-instance":
        status = Status.FAILED.value
        result = (
            "The configured Portal BaseURI targets a different ServiceNow "
            "instance."
        )
        remediation = (
            "Set the exact administrator-confirmed employee portal URL on the "
            "confirmed ServiceNow instance."
        )
    elif portal["reason"] == "invalid-url":
        status = Status.FAILED.value
        result = "The configured Portal BaseURI is not a safe plain HTTPS URL."
        remediation = (
            "Set a plain HTTPS employee portal URL without credentials, query, "
            "or fragment."
        )
    else:
        status = Status.NOT_CONFIGURED.value
        result = (
            "The exact Setup Configurations topic does not contain an "
            "administrator-confirmed employee portal path."
        )
        remediation = (
            "Provide the full employee portal URL, including its real portal "
            "path; do not infer /sp or /esc from the instance origin."
        )
    return _result(
        "SN-DA-HRSD-PORTAL-001",
        status,
        "ServiceNow HRSD employee portal Base URI",
        result,
        remediation,
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
    draft_semantic_hash: str,
    connection_id: str | None = None,
) -> str:
    binding = record.get("binding")
    if not isinstance(binding, dict):
        return "binding-missing"
    if binding.get("draftSemanticHash") != draft_semantic_hash:
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


def _agent_connection_result(
    evidence: dict[str, Any],
    credential_check: CheckResult,
    draft_semantic_hash: str,
) -> CheckResult:
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
            draft_semantic_hash,
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
                "saved draft."
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


def _publish_result(
    evidence: dict[str, Any],
    component_hash: str,
    draft_semantic_hash: str,
) -> CheckResult:
    record = evidence.get("publish")
    published_hash = (
        record.get("publishedComponentHash") or record.get("componentHash")
        if isinstance(record, dict)
        else None
    )
    semantic_bridge_current = bool(
        isinstance(record, dict)
        and record.get("testedDraftSemanticHash") == draft_semantic_hash
        and record.get("publishedSemanticHash") == draft_semantic_hash
    )
    if not isinstance(record, dict) or published_hash != component_hash:
        status = Status.NOT_CONFIGURED.value
        result = (
            "The current tested draft identity has no matching publish "
            "receipt."
        )
    elif record.get("status") == "needs_remediation":
        status = Status.FAILED.value
        result = "Publish needs remediation; automatic unpublish is unavailable."
    elif not semantic_bridge_current:
        status = Status.NOT_CONFIGURED.value
        result = (
            "The current tested draft identity has no matching publish "
            "receipt."
        )
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
    draft_semantic_hash: str,
    connection_binding_hash: str | None,
    topics_check: CheckResult,
    portal_check: CheckResult,
    credential_check: CheckResult,
    agent_connection_check: CheckResult,
) -> CheckResult:
    prerequisite = _test_prerequisite_gate(
        topics_check,
        portal_check,
        credential_check,
        agent_connection_check,
    )
    if prerequisite is not None:
        return prerequisite
    record = evidence.get("test")
    valid_binding = (
        isinstance(record, dict)
        and isinstance(record.get("binding"), dict)
        and record["binding"].get("draftSemanticHash")
        == draft_semantic_hash
        and connection_binding_hash is not None
        and record["binding"].get("connectionBindingHash")
        == connection_binding_hash
    )
    privacy_safe_shape = bool(
        isinstance(record, dict)
        and record.get("promptCategory") == "list-my-open-hr-cases"
        and "prompt" not in record
        and "details" not in record
        and (
            (
                record.get("result") == "pass"
                and record.get("failureCategory") is None
            )
            or (
                record.get("result") == "fail"
                and record.get("failureCategory")
                in {
                    "authentication",
                    "permission",
                    "empty-result",
                    "connector",
                    "unexpected",
                }
            )
        )
    )
    if not valid_binding:
        status = Status.NOT_CONFIGURED.value
        result = (
            "No current Test pane evidence is bound to this saved draft and "
            "selected connection."
        )
    elif not privacy_safe_shape:
        status = Status.NOT_CONFIGURED.value
        result = (
            "Current Test pane evidence does not use the privacy-safe "
            "bounded evidence contract."
        )
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


def _test_prerequisite_gate(
    topics_check: CheckResult,
    portal_check: CheckResult,
    credential_check: CheckResult,
    agent_connection_check: CheckResult,
) -> CheckResult | None:
    prerequisites = (
        ("credential", credential_check, {Status.PASSED.value}),
        (
            "topics",
            topics_check,
            {Status.PASSED.value, Status.MANUAL.value},
        ),
        ("portal Base URI", portal_check, {Status.PASSED.value}),
        (
            "Agent Connect",
            agent_connection_check,
            {Status.MANUAL.value},
        ),
    )
    passthrough = {
        Status.FAILED.value,
        Status.BLOCKED.value,
        Status.ERROR.value,
        Status.WARNING.value,
    }
    for label, check, accepted in prerequisites:
        if check.status in accepted:
            continue
        status = (
            check.status
            if check.status in passthrough
            else Status.NOT_CONFIGURED.value
        )
        return _result(
            "SN-DA-HRSD-TEST-001",
            status,
            "ServiceNow HRSD Test pane result",
            (
                f"Current {label} prerequisite is {check.status}: "
                f"{check.result}"
            ),
            check.remediation,
        )
    return None
