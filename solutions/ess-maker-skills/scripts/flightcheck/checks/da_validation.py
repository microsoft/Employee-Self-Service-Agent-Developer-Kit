# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Permission-aware DA observations, reusing the existing read clients."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID
from urllib.parse import quote, urlsplit

from auth import query_all

from ..da_execution import DAConfigurationError, manual_result, result_for
from ..pp_admin_client import _policy_applies_to_env
from ._connection_dependencies import _Access, _connector, _mapping
from ._dlp_utils import evaluate_connector_classification, normalize_connector_id
from .licensing import _env_mcs_entitlement_observation, _premium_connectors_in_flow
from .prerequisites import (
    COPILOT_STUDIO_SKUS, M365_COPILOT_SKUS, PREPAID_CAPACITY_SKUS, TEAMS_BEARING_SKUS, _sku_matches,
)


def _cached(runner, key, read):
    cache = runner.da_observations
    if key not in cache:
        try:
            cache[key] = read()
        except Exception as exc:
            cache[key] = exc
    value = cache[key]
    if isinstance(value, Exception):
        raise value
    return value


def _collection(value):
    if isinstance(value, dict) and value.get("_error"):
        status = value.get("_status")
        if status == 403:
            raise PermissionError("The delegated resource read returned HTTP 403.")
        raise RuntimeError(f"Resource read failed: HTTP {status}; {value['_error']}.")
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("The service returned an invalid resource collection.")
    return value


def _graph(runner):
    return runner.da_executor.graph()


def _powerplatform(runner):
    return runner.da_executor.powerplatform()


def _graph_observation(runner, spec):
    graph = _graph(runner)
    key = spec.key
    if key in {"PRE-001", "PRE-002", "PRE-003", "PRE-006"}:
        skus = _cached(runner, "skus", graph.get_subscribed_skus)
        patterns = {
            "PRE-001": M365_COPILOT_SKUS, "PRE-002": COPILOT_STUDIO_SKUS,
            "PRE-003": TEAMS_BEARING_SKUS, "PRE-006": PREPAID_CAPACITY_SKUS,
        }[key]
        if any(not isinstance(sku.get("skuPartNumber"), str) for sku in skus):
            raise ValueError("The tenant SKU inventory omitted a SKU part number.")
        matching = [sku["skuPartNumber"] for sku in skus if _sku_matches(sku, patterns)]
        finding = f"{len(matching)} matching tenant SKU(s): {', '.join(matching) or 'none'}. "
        finding += "This is tenant inventory, not intended-user assignment or effective billing capacity."
        evidence = {"skuPartNumbers": matching, "evidenceBoundary": "tenant_inventory_not_audience_entitlement"}
        if key == "PRE-003":
            return result_for(
                spec, "Passed", finding + " A Teams-bearing SKU is not a universal DA prerequisite; "
                "published DA validation uses Microsoft 365 Copilot Chat, not standalone Teams.",
                evidence=evidence,
            )
        return result_for(spec, "Passed", finding, evidence=evidence) if matching else manual_result(
            runner, spec, finding, evidence=evidence,
        )
    if key in {"PRE-008", "PRE-009"}:
        template = (
            "62e90394-69f5-4237-9190-012177145e10" if key == "PRE-008"
            else "11648597-926c-4cf3-9c36-bcebb0ba8dcc"
        )
        roles = _cached(runner, "directory_roles", graph.get_directory_roles)
        selected = [role for role in roles if str(role.get("roleTemplateId", "")).casefold() == template]
        if any(not isinstance(role.get("roleTemplateId"), str) for role in roles):
            raise ValueError("Directory role inventory omitted a role template ID.")
        members = []
        for role in selected:
            identity = str(UUID(role["id"]))
            members.extend(_cached(runner, ("role_members", identity), lambda: graph.get_role_members(identity)))
        finding = (
            f"{len(selected)} activated role object(s), {len(members)} active member(s) returned. "
            "Eligible/PIM assignments and effective privileges were not evaluated. This role is not required to run maker diagnostics."
        )
        evidence = {"activeMembers": len(members), "activatedRoleObjects": len(selected)}
        return result_for(spec, "Passed", finding, evidence=evidence) if members else manual_result(
            runner, spec, finding, evidence=evidence,
        )
    if key == "AUTH-001":
        orgs = _cached(runner, "organization", lambda: graph.get_all("/organization"))
        if len(orgs) != 1 or str(orgs[0].get("id", "")).casefold() != runner.tenant_id.casefold():
            raise ValueError("Graph organization did not identify the authenticated target tenant.")
        return result_for(spec, "Passed", f"Graph organization matched tenant {runner.tenant_id}.")
    if key == "AUTH-002":
        policies = _cached(runner, "conditional_access", graph.get_conditional_access_policies)
        states = {"enabled": 0, "disabled": 0, "enabledForReportingButNotEnforced": 0}
        for policy in policies:
            if policy.get("state") not in states:
                raise ValueError("A Conditional Access policy omitted its supported enforcement state.")
            states[policy["state"]] += 1
        return result_for(
            spec, "Passed",
            f"Conditional Access inventory: {states['enabled']} enabled, {states['disabled']} disabled, "
            f"{states['enabledForReportingButNotEnforced']} report-only. Effective policy coverage for users was not assessed.",
            evidence={"policyStates": states, "evidenceBoundary": "inventory_not_effective_enforcement"},
        )
    users = _collection(graph.get("/users", params={"$top": "10", "$select": "id"}).get("value"))
    return result_for(
        spec, "Passed", f"{len(users)} user(s) returned by the inventory sample. No synchronization or employee mapping conclusion was made.",
        evidence={"sampleUsers": len(users), "evidenceBoundary": "sample_not_synchronization"},
    )


def _environment(runner):
    from ..maker_diagnostics import _check_environment

    runner.da_executor.group("environment", _check_environment)
    snapshot = getattr(runner, "_maker_environment_snapshot", None)
    if snapshot is None:
        raise ValueError("The exact environment snapshot is unavailable.")
    return snapshot["properties"]


def _provisioning(runner, spec):
    properties = _environment(runner)
    link = properties.get("linkedEnvironmentMetadata")
    audit = getattr(runner, "_da_connection_audit", None)
    required = getattr(runner, "maker_workday_extension", False) or bool(audit and any(ref.flow_ids for ref in audit.references))
    if link is None and "linkedEnvironmentMetadata" in properties and not required:
        return result_for(
            spec, "NotConfigured", "No linked Dataverse resource is declared; no selected runtime requirement was established.",
            evidence={"applicability": "not_applicable"},
        )
    if not isinstance(link, dict):
        return manual_result(runner, spec, "The returned environment metadata did not establish Dataverse provisioning.")
    if "resourceProvisioningState" not in link:
        return manual_result(
            runner, spec,
            "The returned linked-resource metadata does not expose a supported provisioning-state observation. Database type presence was not treated as success.",
            evidence={"readLimitation": "unsupported_observation"},
        )
    state = link.get("resourceProvisioningState")
    if not isinstance(state, str) or not state.strip():
        raise ValueError("Linked Dataverse metadata omitted resourceProvisioningState.")
    return result_for(
        spec, "Passed" if state.casefold() == "succeeded" else "Failed",
        f"Dataverse provisioning state: {state}. Database type presence was not used to override this state.",
        evidence={"provisioningState": state},
    )


def _capacity(runner, spec):
    allocated, evidence = _env_mcs_entitlement_observation(_powerplatform(runner), runner.env_id)
    outcome = evidence.get("outcome")
    if allocated is None:
        if evidence.get("serviceStatus") == 403:
            raise PermissionError("The environment entitlement read returned HTTP 403.")
        if outcome in {"service-error", "invalid-response", "ambiguous-entitlement"} or evidence.get("serviceStatus") == 401:
            return result_for(spec, "Error", f"Environment entitlement read was {outcome}.", evidence=evidence)
        return manual_result(runner, spec, f"Environment message capacity could not be established: {outcome}.", evidence=evidence)
    finding = f"{allocated} message credit(s) allocated to this environment. This does not establish audience or usage sufficiency."
    return result_for(spec, "Passed", finding, evidence=evidence) if allocated > 0 else manual_result(
        runner, spec, finding + " The effective prepaid/Pay-as-you-go route still requires comparison.", evidence=evidence,
    )


def _billing(runner, spec):
    client = _powerplatform(runner)
    policies = _collection(client.list_billing_policies())
    matches = []
    for policy in policies:
        policy_id = policy.get("id")
        if not isinstance(policy_id, str) or not policy_id or policy.get("status") not in {"Enabled", "Disabled"}:
            raise ValueError("Billing policy inventory omitted its identity/status.")
        environments = _collection(client.list_policy_environments(quote(policy_id, safe="")))
        if any(not isinstance(row.get("environmentId"), str) for row in environments):
            raise ValueError("A billing-policy environment link omitted its environment identity.")
        if any(str(row.get("environmentId", "")).casefold() == runner.env_id.casefold() for row in environments):
            matches.append({"id": policy_id, "status": policy.get("status"), "billingInstrument": policy.get("billingInstrument")})
    observations = []
    for policy in matches:
        if policy["status"] != "Enabled":
            continue
        instrument = policy.get("billingInstrument")
        if not isinstance(instrument, dict) or not instrument.get("subscriptionId"):
            raise ValueError("An enabled billing policy omitted its subscription identity.")
        subscription_id = str(UUID(instrument["subscriptionId"]))
        arm = runner.da_executor.azure_arm()
        try:
            subscription = _mapping(arm.get_subscription(subscription_id), "Linked Azure subscription")
            if str(subscription.get("subscriptionId", "")).casefold() != subscription_id.casefold():
                raise ValueError("Azure returned a different subscription identity.")
            state = subscription.get("state")
            if state not in {"Enabled", "Warned", "PastDue", "Disabled", "Deleted"}:
                raise ValueError("Linked Azure subscription omitted its supported health state.")
            observation = {"subscriptionId": subscription_id, "state": state, "costBudgets": None}
            observations.append(observation)
            if state in {"PastDue", "Disabled", "Deleted"}:
                return result_for(
                    spec, "Failed", f"The environment's enabled billing policy references an unhealthy subscription: {observations}.",
                    evidence={"linkedBillingPolicies": matches, "subscriptions": observations},
                )
            budgets = _collection(arm.list_budgets(subscription_id))
            if any(
                not isinstance(item.get("properties"), dict)
                or item["properties"].get("category") not in {"Cost", "Usage"}
                for item in budgets
            ):
                raise ValueError("A returned Azure budget omitted its supported category.")
            observation["costBudgets"] = sum(item["properties"]["category"] == "Cost" for item in budgets)
        except PermissionError as exc:
            return manual_result(
                runner, spec, f"The environment billing links were read; the linked subscription/budget read was denied: {exc}",
                evidence={"linkedBillingPolicies": matches, "subscriptions": observations, "readLimitation": "permission_denied"},
            )
    evidence = {"linkedBillingPolicies": matches, "subscriptions": observations}
    if observations and all(item["state"] == "Enabled" and item["costBudgets"] for item in observations):
        return result_for(
            spec, "Passed", f"{len(observations)} exact environment billing link(s) have Enabled subscriptions and a returned cost-budget record. Budget effectiveness and audience sufficiency were not assessed.",
            evidence=evidence,
        )
    return manual_result(
        runner, spec,
        f"{len(matches)} billing policy link(s) returned for this exact environment. "
        f"Observed subscription health/budget counts: {observations}. Effective spending controls and alternative prepaid coverage require comparison.",
        evidence=evidence,
    )


def _dlp(runner, spec):
    policies = _cached(
        runner, "dlp_policies",
        lambda: _collection(_Access(runner).admin().get_dlp_policies(strict_collection=True)),
    )
    if any(not isinstance(policy.get("properties"), dict) for policy in policies):
        raise ValueError("DLP policy inventory returned malformed policy properties.")
    effective = [policy for policy in policies if _policy_applies_to_env(policy, runner.env_id)]
    if spec.key == "ENV-008":
        return result_for(
            spec, "Passed", f"{len(effective)} effective policy record(s) returned for this environment; connector restrictions are evaluated by INFRA-006.",
            evidence={"effectivePolicies": len(effective)},
        )
    audit = runner._da_connection_audit
    incomplete = bool(audit.warnings or audit.blocked or audit.read_limitations)
    connectors = {normalize_connector_id(ref.connector_id) for ref in audit.references}
    limitations = {
        "dependencyCoverageComplete": not incomplete,
        "verificationLimitations": audit.warnings + ([audit.blocked] if audit.blocked else []),
        "readLimitations": audit.read_limitations,
    }
    discovery_error = any(item["kind"] == "error" for item in audit.read_limitations)
    if incomplete and (not connectors or not effective):
        finding = "Connector discovery is incomplete; no complete DLP assertion was possible."
        return result_for(spec, "Error", finding, evidence=limitations) if discovery_error else manual_result(runner, spec, finding, evidence=limitations)
    if not connectors:
        return result_for(
            spec, "NotConfigured", "No selected active connector dependencies were discovered.",
            evidence={"applicability": "not_applicable"},
        )
    if not effective and not incomplete:
        return result_for(spec, "Passed", "The complete policy inventory contains no policy effective on this environment.")
    evaluation = evaluate_connector_classification(connectors, effective)
    evidence = {**asdict(evaluation), **limitations}
    if incomplete and not evaluation.blocked:
        if discovery_error:
            return result_for(spec, "Error", "Connector discovery encountered a service/response error; DLP coverage is incomplete.", evidence=evidence)
        return manual_result(runner, spec, "Only part of the required connector inventory was inspected; the returned classifications do not establish complete DLP coverage.", evidence=evidence)
    if not evaluation.blocked and (evaluation.indeterminate or evaluation.cross_group):
        return manual_result(runner, spec, "Selected connectors have indeterminate or cross-group classifications; actual action combinations need comparison.", evidence=evidence)
    return result_for(
        spec, "Failed" if evaluation.blocked else "Passed",
        f"Selected connector classification: blocked={evaluation.blocked}; cross-group={evaluation.cross_group}; groups={evaluation.groups_seen}.",
        evidence=evidence,
    )


def _knowledge(runner, spec):
    components = [
        change["component"] for change in runner._da_native_snapshot["changeset"]["botComponentChanges"]
        if change["component"]["$kind"] == "KnowledgeSourceComponent"
    ]
    return manual_result(
        runner, spec,
        f"{len(components)} native knowledge-source component(s) observed for this agent. "
        "This authoring contract does not establish complete external-source mapping, runtime indexing or effective employee access.",
        evidence={"sourceComponents": [
            {"schemaName": component.get("schemaName", ""), "id": component.get("id", "")}
            for component in components
        ], "evidenceBoundary": "native_configuration_not_indexing_or_acl"},
    )


def _variables(runner, spec):
    if runner.scope == "local":
        path = Path("workspace") / "agents" / runner.agent_slug / "variables"
        count = len(list(path.glob("*.mcs.yml"))) if path.is_dir() else 0
        boundary = "local_authored_content"
    else:
        count = sum(
            item["component"]["$kind"] == "GlobalVariableComponent"
            for item in runner._da_native_snapshot["changeset"]["botComponentChanges"]
        )
        boundary = "native_authored_content"
    return result_for(
        spec, "Passed", f"{count} variable definition(s) in the selected authoring scope; no legacy minimum is imposed.",
        evidence={"agentSlug": runner.agent_slug, "evidenceBoundary": boundary, "deploymentFreshnessVerified": False},
    )


def _flow_licensing(runner, spec):
    details = getattr(runner, "_maker_flow_details", {})
    flow_ids = {
        flow for reference in runner._da_connection_audit.references for flow in reference.flow_ids
    }
    premium = {
        flow: _premium_connectors_in_flow(details[flow]) for flow in sorted(flow_ids)
    }
    return manual_result(
        runner, spec,
        f"{len(flow_ids)} exact invoked flow(s) inspected; {sum(bool(value) for value in premium.values())} contain observed premium/custom connector metadata. "
        "Connector metadata is not proof of the flow's licensing route or intended-user entitlement.",
        evidence={"flowConnectors": premium, "evidenceBoundary": "connector_metadata_not_license_compliance"},
    )


def _workday_application(runner):
    config = runner.config
    app_id = config.get("entraAppId")
    object_id = config.get("entraAppObjectId")
    if not app_id and not object_id:
        return None
    graph = _graph(runner)
    if object_id:
        application = graph.get(f"/applications/{UUID(str(object_id))}")
        if not isinstance(application, dict) or str(application.get("id", "")).casefold() != str(object_id).casefold():
            raise ValueError("Graph returned a different application object.")
        actual_app_id = str(UUID(application["appId"]))
        if app_id and actual_app_id.casefold() != str(app_id).casefold():
            raise ValueError("The configured Workday application IDs identify different applications.")
        app_id = actual_app_id
    else:
        app_id = str(UUID(str(app_id)))
        applications = graph.get_all("/applications", params={"$filter": f"appId eq '{app_id}'"})
        if not applications:
            raise DAConfigurationError("The exact configured Workday application is missing from the readable tenant inventory.")
        if len(applications) != 1:
            raise ValueError("The exact configured Workday application did not resolve uniquely.")
        application = applications[0]
        if str(application.get("appId", "")).casefold() != app_id.casefold():
            raise ValueError("Graph returned a different application than the exact configured Workday application.")
    principals = graph.get_service_principals(
        filter_expr=f"appId eq '{app_id}'",
        select="id,appId,displayName,appRoleAssignmentRequired,keyCredentials,preferredTokenSigningKeyThumbprint,preferredSingleSignOnMode,servicePrincipalNames",
    )
    if not principals:
        raise DAConfigurationError("The configured Workday application has no service principal in the readable tenant inventory.")
    if len(principals) != 1 or str(principals[0].get("appId", "")).casefold() != app_id.casefold():
        raise ValueError("The configured Workday service principal did not resolve uniquely to the exact application.")
    return application, principals[0]


def _workday_entra(runner, spec):
    if spec.key == "WD-ENTRA-SIGNOPT-001":
        return manual_result(runner, spec, "FlightCheck has no supported read contract for the SAML signing-option selection.")
    resolved = _cached(runner, "workday_application", lambda: _workday_application(runner))
    if resolved is None:
        return manual_result(
            runner, spec, "The exact Workday Entra application was not configured; no tenant-wide candidate was substituted.",
            evidence={"missingConfiguration": ["entraAppId or entraAppObjectId"]},
        )
    application, principal = resolved
    graph = _graph(runner)
    sp_id = str(UUID(principal["id"]))
    if spec.key == "WD-ASSIGN-001":
        required = principal.get("appRoleAssignmentRequired")
        if not isinstance(required, bool):
            raise ValueError("The Workday service principal omitted appRoleAssignmentRequired.")
        assignments = graph.get_app_role_assignments(sp_id)
        return result_for(
            spec, "Failed" if required and not assignments else "Passed",
            f"Exact Workday application: assignment required={required}; {len(assignments)} assigned principal(s). "
            "Intended-user membership and effective sign-in were not assessed.",
            evidence={"appRoleAssignmentRequired": required, "assignedPrincipals": len(assignments)},
        )
    if spec.key == "WD-ENTRA-SCOPE-001":
        from .entra_app import _GRAPH_DELEGATED_SCOPE_IDS, _MS_GRAPH_RESOURCE_APP_ID, _WORKDAY_CONNECTOR_APP_ID

        api = application.get("api")
        access = application.get("requiredResourceAccess")
        if not isinstance(api, dict) or not isinstance(access, list):
            raise ValueError("Workday application omitted its API/requiredResourceAccess configuration.")
        scopes = api.get("oauth2PermissionScopes", [])
        identifiers = {scope["id"] for scope in scopes if scope.get("value") == "user_impersonation" and scope.get("isEnabled") is True}
        authorized = any(
            entry.get("appId", "").casefold() == _WORKDAY_CONNECTOR_APP_ID
            and identifiers.intersection(entry.get("delegatedPermissionIds", []))
            for entry in api.get("preAuthorizedApplications", [])
        )
        requested = {
            permission["id"] for entry in access
            if str(entry.get("resourceAppId", "")).casefold() == _MS_GRAPH_RESOURCE_APP_ID
            for permission in entry.get("resourceAccess", []) if permission.get("type") == "Scope"
        }
        missing = sorted(name for name, identity in _GRAPH_DELEGATED_SCOPE_IDS.items() if identity not in requested)
        return result_for(
            spec, "Passed" if identifiers and authorized and not missing else "Failed",
            f"Enabled user_impersonation scope(s)={len(identifiers)}; connector authorized for that scope={authorized}; missing requested Graph scopes={missing}.",
        )
    if spec.key == "WD-ENTRA-CONSENT-001":
        from .entra_app import _MS_GRAPH_RESOURCE_APP_ID, _REQUIRED_CONSENT_SCOPES

        resources = graph.get_service_principals(filter_expr=f"appId eq '{_MS_GRAPH_RESOURCE_APP_ID}'")
        if len(resources) != 1 or str(resources[0].get("appId", "")).casefold() != _MS_GRAPH_RESOURCE_APP_ID:
            raise ValueError("The Graph resource service principal did not resolve uniquely.")
        resource_id = str(UUID(resources[0]["id"]))
        grants = graph.get_all("/oauth2PermissionGrants", params={
            "$filter": f"clientId eq '{sp_id}' and resourceId eq '{resource_id}'",
        })
        scopes = {
            scope.casefold() for grant in grants
            if grant.get("consentType") == "AllPrincipals"
            and str(grant.get("clientId", "")).casefold() == sp_id.casefold()
            and str(grant.get("resourceId", "")).casefold() == resource_id.casefold()
            for scope in str(grant.get("scope", "")).split()
        }
        missing = sorted(_REQUIRED_CONSENT_SCOPES - scopes)
        return result_for(
            spec, "Failed" if missing else "Passed",
            f"Exact Workday app to Graph tenant-wide consent: missing scopes={missing}. Grants to other resources were not counted.",
        )
    if spec.key == "WD-ENTRA-NAMEID-001":
        from ._saml_utils import summarize_nameid

        policies = graph.get_claims_mapping_policies(sp_id)
        return manual_result(
            runner, spec, f"Exact Workday application NameID observation: {summarize_nameid(policies)}. "
            "Agreement with Workday employee usernames requires cross-system comparison.",
            evidence={"claimsMappingPolicies": len(policies)},
        )
    evidence = {
        "applicationId": application["appId"], "servicePrincipalId": sp_id,
        "singleSignOnMode": principal.get("preferredSingleSignOnMode"),
        "servicePrincipalNames": principal.get("servicePrincipalNames"),
    }
    if spec.key == "WD-CONN-102":
        credentials = principal.get("keyCredentials")
        if not isinstance(credentials, list):
            raise ValueError("The Workday certificate projection omitted keyCredentials.")
        evidence["keyCredentials"] = credentials
        evidence["preferredThumbprint"] = principal.get("preferredTokenSigningKeyThumbprint")
        signing = [item for item in credentials if item.get("usage") == "Sign"]
        now = datetime.now(timezone.utc)
        expirations = [datetime.fromisoformat(item["endDateTime"].replace("Z", "+00:00")) for item in signing]
        if any(value.tzinfo is None for value in expirations):
            raise ValueError("A signing certificate returned a timestamp without a timezone.")
        if expirations and all(value < now for value in expirations):
            return result_for(
                spec, "Failed", "All returned Entra signing certificates are expired.",
                evidence=evidence,
            )
    return manual_result(
        runner, spec, f"Exact Workday Entra observation: {evidence}. "
        "Cross-system federation/certificate agreement was not established.", evidence=evidence,
    )


def _workday_references(runner, spec):
    from .workday import WORKDAY_RUNTIME_REF_LOGICAL_NAME
    from ..maker_diagnostics import _check_connections

    runner.da_executor.group("connections", _check_connections)
    audit = runner._da_connection_audit
    env_url, token = _Access(runner).dataverse()
    names = {
        ref.logical_name for ref in runner._da_connection_audit.references
        if _connector(ref.connector_id) == "shared_workdaysoap"
    } | {WORKDAY_RUNTIME_REF_LOGICAL_NAME}
    query = " or ".join(
        "connectionreferencelogicalname eq '" + name.replace("'", "''") + "'" for name in sorted(names)
    )
    rows = query_all(
        env_url, token, "connectionreferences",
        "connectionreferencelogicalname,connectorid,connectionid,statuscode", query,
        strict_collection=True,
    )
    rows = _collection(rows)
    index = {}
    for row in rows:
        key = str(row["connectionreferencelogicalname"]).casefold()
        if key in index or key not in {name.casefold() for name in names}:
            raise ValueError("Package reference lookup returned a duplicate or unrelated logical identity.")
        index[key] = row
    missing = sorted(name for name in names if name.casefold() not in index)
    unbound = sorted(name for name in names if name.casefold() in index and not index[name.casefold()].get("connectionid"))
    mismatched = [name for name, row in index.items() if _connector(row["connectorid"]) != "shared_workdaysoap"]
    incomplete = bool(audit.blocked or audit.warnings or audit.read_limitations)
    status = (
        "Failed" if missing or unbound or mismatched else
        "Error" if any(item["kind"] == "error" for item in audit.read_limitations) else
        "Manual" if incomplete else "Passed"
    )
    return result_for(
        spec, status,
        f"Required runtime-package and selected Workday reference bindings: missing={missing}; unbound={unbound}; wrong connector={mismatched}. "
        "Unused environment-wide ISU or sibling-agent references were not treated as this DA's requirements."
        + (" Dependency discovery was incomplete; the inspected subset does not prove complete bindings." if incomplete else ""),
        evidence={
            "requiredLogicalNames": sorted(names), "missing": missing, "unbound": unbound,
            "dependencyCoverageComplete": not incomplete,
            "readLimitations": audit.read_limitations,
            "verificationLimitations": [*audit.warnings, *([audit.blocked] if audit.blocked else [])],
        },
    )


def _litmus_manual(runner, spec, evidence, *, running):
    snapshot = getattr(runner, "_da_native_snapshot", None) or {}
    bot = snapshot.get("changeset", {}).get("bot", {})
    environment = getattr(runner, "_maker_environment_snapshot", None) or {}
    agent_name = bot.get("displayName") or runner.agent_slug
    environment_name = environment.get("properties", {}).get("displayName") or runner.env_id
    rerun_step = "Once the agent finishes answering, rerun the Workday Litmus Test."
    if running:
        finding = "A recent Workday flow is still running. Wait for it to finish, then rerun this check; do not submit another prompt."
        steps = [
            f'Wait for the current answer in "{agent_name}" in environment "{environment_name}" to finish. Do not create duplicate test conversations.',
            "If it does not finish, ask the exact flow owner to inspect the in-progress run in Power Automate.",
            rerun_step,
        ]
    else:
        finding = "No recent completed Workday response could be scored from the returned history (last 60 minutes). FlightCheck does not run the test for you. Complete the steps below, then rerun this check."
        steps = [
            f'Sign in to [Copilot Studio](https://copilotstudio.microsoft.com/) with the Microsoft work account shown in this report. If already signed in, confirm you are using that account. Select environment "{environment_name}", then open agent "{agent_name}".',
            "Click Test in the top-right corner to open the agent's Test pane. Start a new conversation.",
            'In that Test pane, send this exact question: "What is my employee ID". Send it to the agent, not to VS Code Copilot Chat.',
            "If the agent asks you to sign in to Workday or connect, use your own Workday employee account. This is separate from signing in to Copilot Studio. Wait for the agent to finish answering and check the answer against your own Workday information. Keep the employee ID private; do not paste it into FlightCheck.",
            rerun_step,
        ]
    evidence = {
        **evidence, "manualVerificationSteps": steps,
        "ifMissingOrIncorrect": (
            "If sign-in or the question fails, stop and resolve that error before rerunning. "
            "If Employee ID is intentionally disabled, do not enable it for this check: ask the agent owner for an enabled, approved read-only Workday question that invokes the inspected flow. Do not submit employee changes. "
            "If the answer succeeds but this check still reports no recent response, ask the flow owner to inspect the exact flow's history in the same environment. Do not keep sending test questions to fix missing history access."
        ),
    }
    row = manual_result(runner, spec, finding, evidence=evidence)
    row.roles = ["ESS Maker / Agent Developer"]
    return row


def _run_history(runner, spec):
    from .servicenow import _classify_run as classify_servicenow
    from .workday import _classify_run as classify_workday
    from ..maker_diagnostics import _check_connections

    runner.da_executor.group("connections", _check_connections)
    audit = runner._da_connection_audit
    if getattr(audit, "warnings", []) or getattr(audit, "blocked", "") or getattr(audit, "read_limitations", []):
        evidence = {
            "verificationLimitations": audit.warnings,
            "readLimitations": getattr(audit, "read_limitations", []),
            "dependencyCoverageComplete": False,
        }
        finding = "The exact invoked-flow inventory could not be completely inspected. A new test prompt cannot resolve missing discovery access."
        if any(item["kind"] == "error" for item in evidence["readLimitations"]):
            return result_for(spec, "Error", finding, evidence=evidence)
        evidence["manualVerificationSteps"] = [
            "Ask the selected agent's flow/connection owner to inspect the discovery or permission limitation in the technical details.",
            "Verify access to the exact selected environment and invoked flows, then rerun this checkpoint. Do not repeatedly submit test prompts to fix read access.",
        ]
        return manual_result(runner, spec, finding, evidence=evidence)
    connector = "shared_service-now" if spec.key.startswith("SN-") else "shared_workdaysoap"
    ids = {
        flow for ref in runner._da_connection_audit.references
        if _connector(ref.connector_id) == connector for flow in ref.flow_ids
    }
    if not ids:
        return result_for(
            spec, "NotConfigured", "No active invoked flows for this provider; native direct actions do not require legacy flows.",
            evidence={"applicability": "not_applicable"},
        )
    observations = []
    now = datetime.now(timezone.utc)
    pp = _Access(runner).admin(flow=True)
    for flow_id in sorted(ids):
        try:
            runs = _collection(pp.get_flow_runs(runner.env_id, flow_id, strict_collection=True))
        except PermissionError as exc:
            if connector != "shared_workdaysoap":
                raise
            return manual_result(
                runner, spec,
                f"The exact Workday flow's run history was denied: {exc}. A new test prompt cannot repair history access.",
                evidence={
                    "flowId": flow_id, "recentRuns": observations,
                    "readLimitation": "permission_denied", "httpStatus": 403,
                    "manualVerificationSteps": [
                        "Ask the exact invoked-flow owner to verify read access to the reported flow in the selected environment in Power Automate.",
                        "After access is restored, rerun only WD-RUN-001. Do not submit additional test prompts to fix denied run-history access.",
                    ],
                },
            )
        for run in runs:
            properties = run.get("properties")
            if not isinstance(properties, dict) or not isinstance(properties.get("startTime"), str):
                raise ValueError("An exact invoked-flow run omitted its start timestamp.")
            started = datetime.fromisoformat(properties["startTime"].replace("Z", "+00:00"))
            if started.tzinfo is None or started > now + timedelta(minutes=5):
                raise ValueError("An exact invoked-flow run has an unverifiable timestamp.")
            if started < now - timedelta(minutes=60):
                continue
            classification = classify_servicenow(run) if connector == "shared_service-now" else classify_workday(run)
            # Workday's legacy scorer accepts unnamed Succeeded child responses;
            # that is not evidence of an agent-facing successful response.
            if connector == "shared_workdaysoap" and (
                properties.get("status") == "Succeeded"
                and not (properties.get("response") or {}).get("name")
            ):
                classification = "pending"
            observations.append({
                "flowId": flow_id, "runId": run.get("name"),
                "classification": classification, "status": properties.get("status"),
                "responseBranch": (properties.get("response") or {}).get("name"),
                "startTime": properties["startTime"],
            })
    scored = [item for item in observations if item["classification"] != "pending"]
    evidence = {"recentRuns": observations, "windowMinutes": 60, "evidenceBoundary": "returned_exact_flow_history_not_current_employee_execution"}
    if not scored:
        if connector == "shared_workdaysoap":
            return _litmus_manual(
                runner, spec, evidence,
                running=any(item["status"] in {"Running", "Waiting", "Paused", "Suspended"} for item in observations),
            )
        return manual_result(runner, spec, "No scoreable agent-facing runs in the returned pages within the last 60 minutes.", evidence=evidence)
    success = any(item["classification"] == "success" for item in scored)
    row = result_for(
        spec, "Passed" if success else "Failed",
        f"{len(scored)} scoreable recent exact-flow run(s); successful agent-facing response observed={success}. "
        f"{sum(item['classification'] != 'success' for item in scored)} scored failure(s) were also observed. "
        "At least one success is sufficient for this passive litmus; it does not mean every flow or scenario is healthy. "
        "This sample is not a current intended-employee smoke test.", evidence=evidence,
    )
    if connector == "shared_workdaysoap" and not success:
        row.remediation = (
            "Ask the exact flow/connection owner to investigate the failed response branch and binding in the technical details. "
            'After correcting the confirmed issue, open the selected agent in Copilot Studio Test and ask "What is my employee ID" '
            "if enabled, or another approved read-only Workday question. Wait for completion, then rerun only WD-RUN-001. "
            "A top-level Succeeded flow can still contain a caught Workday failure."
        )
    return row


def run_registered_da_check(runner):
    from .. import maker_diagnostics as maker
    from .workday_da import _check_reviewed_workday_topics, _check_runtime_template_wiring

    spec = runner.da_current_spec
    strategy = spec.da.strategy
    component_checks = {
        "workday_topics": _check_reviewed_workday_topics,
        "workday_wiring": _check_runtime_template_wiring,
        "workday_redirect": maker._check_workday_redirect,
    }
    if strategy in component_checks:
        return component_checks[strategy](runner)
    grouped = {
        "native": lambda current: maker._check_native(current, current.da_executor.args),
        "environment": maker._check_environment, "connections": maker._check_connections,
        "agent_configuration": maker._check_agent_configuration,
        "integrations": maker._check_integrations, "workday": maker._check_workday,
        "local": maker._check_local, "attachment": maker._check_manual_verification,
    }
    if strategy in grouped:
        rows = runner.da_executor.group(strategy, grouped[strategy])
        if strategy == "integrations":
            matching = next((row for row in rows if row.checkpoint_id == spec.key), None)
            audit = runner._da_connection_audit
            service_flows = {
                flow for reference in audit.references
                if _connector(reference.connector_id) == "shared_service-now"
                for flow in reference.flow_ids
            }
            if matching is None and spec.key == "SN-FLOW-001" and not service_flows and not audit.warnings and not audit.blocked:
                return [result_for(
                    spec, "NotConfigured", "No selected active ServiceNow flow dependencies were discovered; direct actions do not require legacy flows.",
                    evidence={"applicability": "not_applicable"},
                )]
            if matching is None:
                state = runner.maker_integrations.get("ServiceNow" if spec.key.startswith("SN-") else "Workday", {})
                if state.get("applicability") in {"not_configured", "disabled", "configured"}:
                    return [result_for(
                        spec, "NotConfigured", f"The selected integration is {state['applicability']}.",
                        evidence={"applicability": "not_applicable"},
                    )]
                if state.get("applicability") == "unknown":
                    limitations = [*audit.read_limitations, *state.get("inventoryReadLimitations", [])]
                    if any(item["kind"] == "error" for item in limitations):
                        return [result_for(
                            spec, "Error", "The selected integration discovery encountered a service/response error.",
                            evidence={"readLimitations": limitations},
                        )]
                    return [manual_result(runner, spec, "The selected integration's applicability was not established by the returned inventory.")]
            if matching is not None and matching.status == "Blocked":
                limitations = [*audit.read_limitations, *matching.evidence.get("inventoryReadLimitations", [])]
                if limitations:
                    status = "Error" if any(item["kind"] == "error" for item in limitations) else "Manual"
                    return [replace(matching, status=status, evidence={**matching.evidence, "readLimitations": limitations})]
        if strategy == "environment":
            rows = [
                replace(row, checkpoint_id="DA-ENV-LINK-001" if row.checkpoint_id == "ENV-002" else row.checkpoint_id)
                for row in rows
            ]
        if strategy == "local" and not any(row.checkpoint_id == spec.key for row in rows):
            identity = next((row for row in rows if row.checkpoint_id == "CONFIG-007"), None)
            status = "Blocked" if identity is not None and identity.status != "Passed" else "NotConfigured"
            return [result_for(
                spec, status, "The selected local extraction does not contain this optional authoring surface.",
                evidence={"evidenceBoundary": "local_authored_content", "applicability": "not_applicable"} if status == "NotConfigured" else {},
            )]
        return rows
    functions = {
        "graph": _graph_observation, "provisioning": _provisioning,
        "capacity": _capacity, "billing": _billing, "dlp": _dlp,
        "knowledge": _knowledge, "variables": _variables,
        "flow_licensing": _flow_licensing, "workday_entra": _workday_entra,
        "workday_federation": _workday_entra, "workday_references": _workday_references,
        "run_history": _run_history,
    }
    if strategy in functions:
        return [functions[strategy](runner, spec)]
    if strategy == "rest_endpoint":
        rest = runner.config.get("restBaseUrl")
        if rest is None or rest == "":
            return [manual_result(
                runner, spec, "No Workday REST base URL is saved; deployed connection settings were not read.",
                evidence={"missingConfiguration": ["restBaseUrl"]},
            )]
        if not isinstance(rest, str):
            raise ValueError("Saved Workday REST base URL must be a string.")
        try:
            parsed = urlsplit(rest)
            valid = (
                not any(character.isspace() for character in rest) and "\\" not in rest
                and parsed.scheme == "https" and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and parsed.port != 0
                and parsed.path in {"/ccx/api", "/ccx/api/"}
                and not parsed.query and not parsed.fragment
            )
        except ValueError:
            valid = False
        if not valid:
            return [result_for(
                spec, "Failed",
                "The saved Workday REST base URL is not an HTTPS base ending at /ccx/api "
                "without credentials, query, fragment or extra path segments. Deployed settings were not read.",
                evidence={"evidenceBoundary": "saved_configuration_not_deployed_endpoint"},
            )]
        return [manual_result(
            runner, spec,
            f"The saved REST base URL has the documented HTTPS /ccx/api structure: {rest}. "
            "This does not establish deployed endpoint or Workday tenant agreement.",
            evidence={"configuredRestBaseUrl": rest, "evidenceBoundary": "saved_configuration_not_deployed_endpoint"},
        )]
    if strategy == "optional_manual":
        return [manual_result(
            runner, spec,
            "The supported selected-agent snapshot does not establish whether this optional configuration is used. "
            "First inspect applicability; no setup is required if it is not used.",
            evidence={"applicability": "unknown"},
        )]
    if strategy == "manual":
        return [manual_result(
            runner, spec,
            "This scoped verification has no complete supported automatic assertion. "
            "No employee transaction, publishing action or evidence submission was performed.",
        )]
    raise ValueError(f"No DA producer is registered for strategy {strategy!r} ({spec.key}).")
