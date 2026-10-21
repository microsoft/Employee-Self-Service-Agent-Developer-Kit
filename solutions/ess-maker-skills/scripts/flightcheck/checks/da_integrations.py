# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Selected DA dependencies and read-only adapters for supported Connect checks."""

from __future__ import annotations

from ..agent_scope import active_agent
from ..da_contract import DAFeature, DAFeatureEvidence
from ..runner import BLOCK_REASON_CHECKPOINT_CONTRACT, CheckResult, Priority, Role, Status
from ._connection_dependencies import audit_connections
from .da_baseline import manual_evidence_requirement
from .workday import _check_package_flavor, _check_package_connection_completeness
from .workday_da import run_workday_da_checks
from .workday_extension import _check_dv_connection, _check_user_context_redirect


def workday_target_matches(config: dict) -> bool:
    """A provider file belongs to one exact agent/environment, not its siblings."""
    scope = config.get("_connectConfigScope")
    if not isinstance(scope, dict):
        return False
    selected = active_agent(config)
    provider_agent = scope.get("agent")
    if not isinstance(provider_agent, dict):
        return False
    for actual, expected in (
        (provider_agent.get("botId"), selected.get("botId")),
        (provider_agent.get("slug"), selected.get("slug")),
        (provider_agent.get("schemaName"), selected.get("schemaName")),
        (scope.get("environmentId"), config.get("environmentId")),
    ):
        if not isinstance(actual, str) or not actual.strip() or not isinstance(expected, str):
            return False
        if actual.casefold() != expected.casefold():
            return False
    realm = config.get("_connectConfigRealm")
    tenant = config.get("_connectConfigFoundationTenant")
    return (
        (realm is None or realm == selected.get("realm", config.get("realm")))
        and (not tenant or str(scope.get("entraTenantId", "")).casefold() == str(tenant).casefold())
    )


def configured_da_features(config: dict) -> dict[DAFeature, DAFeatureEvidence]:
    if not workday_target_matches(config):
        return {}
    source = "Exact selected-agent Workday Connect target (intent, not completion proof)."
    return {
        feature: DAFeatureEvidence(True, source)
        for feature in (DAFeature.WORKDAY, DAFeature.DATAVERSE_RUNTIME)
    }


def discover_da_features(runner) -> dict[DAFeature, DAFeatureEvidence]:
    """Known dependencies survive partial reads; partial absence stays unknown."""
    audit = audit_connections(runner)
    runner._da_connection_audit = audit
    complete = not (audit.blocked or audit.warnings or audit.failures)
    connectors = audit.discovered_connectors
    source = "Exact selected-agent active topic/flow dependency audit."
    features = {}
    for feature, present in (
        (DAFeature.WORKDAY, "shared_workdaysoap" in connectors),
        (DAFeature.SERVICENOW, "shared_service-now" in connectors),
        (DAFeature.CONNECTORS, bool(connectors)),
        (DAFeature.NATIVE_CONNECTIONS, audit.has_direct_references),
        (DAFeature.POWER_AUTOMATE, bool(audit.flow_count)),
    ):
        features[feature] = DAFeatureEvidence(True if present else False if complete else None, source)
    if features[DAFeature.WORKDAY].enabled is True or "shared_commondataserviceforapps" in connectors:
        features[DAFeature.DATAVERSE_RUNTIME] = DAFeatureEvidence(True, source)
    else:
        features[DAFeature.DATAVERSE_RUNTIME] = DAFeatureEvidence(False if complete else None, source)
    # An explicit selected Connect target is installation intent even before its
    # topics/flows are active. It is not contradicted by an empty active graph.
    features.update(configured_da_features(runner.config))
    runner._da_feature_evidence = features
    return features


def run_da_integration_checks(runner) -> list[CheckResult]:
    features = getattr(runner, "_da_feature_evidence", {})
    rows = []
    if runner.should_execute("DA-INTEGRATIONS-001"):
        incomplete = not features or any(value.enabled is None for value in features.values())
        rows.append(CheckResult(
            "DA-INTEGRATIONS-001", "DA Integrations", Priority.HIGH.value,
            Status.WARNING.value if incomplete else Status.PASSED.value,
            "Selected DA integration applicability",
            "Recorded dependency applicability; unresolved states remain unknown."
            if features else "Selected-agent dependency discovery was unavailable.",
            (
                "Incomplete configuration evidence is not proof of a runtime failure. "
                "Review ENV-004, restore exact dependency read access and rerun."
                if incomplete else ""
            ),
            roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
            evidence={
                "features": {
                    feature.value: {"enabled": value.enabled, "source": value.source}
                    for feature, value in features.items()
                },
                "sap": "excluded_from_DA_scope",
                "evidenceBoundary": "dependency_configuration_not_connect_completion_or_employee_execution",
            },
        ))
    for key, connector in (("DA-CONN-001", None), ("SN-CONN-001", "shared_service-now")):
        if not runner.should_execute(key):
            continue
        audit = getattr(runner, "_da_connection_audit", None)
        refs = [
            ref for ref in audit.references
            if (ref.connector_id.rstrip("/").rsplit("/", 1)[-1].casefold() == connector
                if connector else not ref.flow_ids)
        ] if audit is not None else []
        unbound = [ref for ref in refs if not isinstance(ref.connection_id, str) or not ref.connection_id.strip()]
        complete = audit is not None and not (audit.blocked or audit.warnings or audit.failures)
        status = Status.FAILED.value if unbound else (
            Status.PASSED.value if refs and complete else Status.BLOCKED.value
        )
        rows.append(CheckResult(
            key, "DA Integrations", Priority.HIGH.value, status,
            "Selected ServiceNow dependency bindings" if connector else "Selected DA direct bindings",
            f"Observed {len(refs)} exact required reference(s), {len(unbound)} unbound; "
            f"complete dependency evidence: {complete}.",
            "" if status == Status.PASSED.value else (
                "Review ENV-004 and restore the selected agent's exact dependency/binding evidence. "
                "Connected candidates and unrelated flow runs do not establish the required mapping."
            ),
            roles=[Role.POWER_PLATFORM_ADMIN.value, Role.ESS_MAKER.value],
            block_reason=BLOCK_REASON_CHECKPOINT_CONTRACT if status == Status.BLOCKED.value else "",
            evidence={
                "dependencyCoverageComplete": complete,
                "references": [
                    {"agentId": ref.agent_id, "logicalName": ref.logical_name,
                     "connectorId": ref.connector_id, "connectionId": ref.connection_id,
                     "flowIds": ref.flow_ids}
                    for ref in refs
                ],
                "evidenceBoundary": "exact_bindings_not_employee_execution",
            },
        ))
    return rows


def run_da_workday_binding_checks(runner) -> list[CheckResult]:
    """Reuse the reviewed package binding contract without legacy flow discovery."""
    _check_package_flavor(runner, wd_flows=[])
    return _check_package_connection_completeness(runner)


def run_da_workday_extension_checks(runner) -> list[CheckResult]:
    """Do not run auth-type inventory or the REST-suffix proxy and filter afterward."""
    rows = []
    if runner.should_execute("DV-CONN-001"):
        rows.extend(_check_dv_connection(runner))
    if runner.should_execute("WD-REST-002"):
        rows.extend(_check_user_context_redirect(runner))
    return rows


def run_da_workday_checks(runner) -> list[CheckResult]:
    rows = run_workday_da_checks(runner)
    for row in rows:
        row.evidence["evidenceBoundary"] = "workday_configuration_not_published_employee_execution"
        if row.status == Status.MANUAL.value:
            row.evidence.update(manual_evidence_requirement(
                runner, ("agentAttachments", "parameterSharing"),
            ))
    return rows
