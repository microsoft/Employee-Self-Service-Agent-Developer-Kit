# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DA evidence requirements that inventory and maker-machine probes cannot prove."""

from __future__ import annotations

from ..agent_scope import active_agent, is_declarative_agent
from ..da_contract import DA_CATALOG
from ..runner import (
    BLOCK_REASON_CHECKPOINT_CONTRACT,
    CheckResult,
    Priority,
    Role,
    Status,
)


# These describe evidence to obtain, not claims that the evidence already exists.
DA_MANUAL_REQUIREMENTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "DA-SN-RUNTIME-001": (
        "Manually configured ServiceNow employee validation",
        "Review target-bound tests for the selected ServiceNow scenarios and intended "
        "users. Guided ServiceNow setup is unavailable; do not use legacy flow names "
        "or uncorrelated run history as execution evidence.",
        ("serviceNowTarget", "enabledScenarios", "employeeTestRuns", "outcomes"),
    ),
    "WD-DA-MAKER-001": (
        "Workday maker Test-pane smoke test",
        "Review the recorded maker's successful enabled read-only Workday scenario "
        "in this realm's Copilot Studio Test pane. Obtain missing evidence without "
        "publishing, waiting for flow run-history correlation, or repeating a healthy "
        "administrator handoff. This is not published-employee validation.",
        ("makerTestCategory", "scenario", "testTimestamp", "outcome"),
    ),
    "PRE-001": (
        "Intended employee audience licensing",
        "Confirm the intended published audience and its applicable Microsoft 365 "
        "Copilot entitlements in the Microsoft 365 admin center.",
        ("publishedAudience", "audienceEntitlements"),
    ),
    "PRE-002": (
        "Selected maker authoring entitlement",
        "Verify the actual maker's enabled authoring entitlement and effective "
        "access to this environment, rather than tenant-wide SKU or role counts.",
        ("makerEntitlement", "effectiveEnvironmentAccess"),
    ),
    "PRE-003": (
        "Teams deployment audience entitlement",
        "Verify Teams entitlement for the intended Teams deployment audience.",
        ("teamsAudience", "teamsEntitlements"),
    ),
    "PRE-004": (
        "Deployment audience capacity sizing",
        "Reconcile the published DA audience, expected usage and the environment's "
        "billing route. Do not use Dataverse bot sharing as the native audience.",
        ("publishedAudience", "expectedUsage", "capacitySizing"),
    ),
    "PRE-005": (
        "Environment billing coverage",
        "In Power Platform admin center verify this environment's billing policy "
        "and prepaid or Pay-as-you-go coverage, including applicable subscription health.",
        ("environmentBillingPolicy", "billingRoute", "billingCoverage"),
    ),
    "PRE-006": (
        "Purchased capacity entitlement",
        "Reconcile purchased prepaid capacity or the approved alternative billing "
        "route with this environment. Tenant purchase alone is not an allocation.",
        ("purchasedEntitlement", "environmentCoverage"),
    ),
    "ENV-002": (
        "Required Dataverse runtime provisioning",
        "For the selected runtime dependencies that require Dataverse, verify the "
        "linked environment and successful database provisioning in Power Platform "
        "admin center. A database type does not override a failed provisioning state.",
        ("runtimeDependencies", "linkedDataverseEnvironment", "provisioningState"),
    ),
    "INFRA-003": (
        "Managed-runtime endpoint reachability",
        "Obtain approved evidence from the actual managed runtime and intended "
        "endpoints. Maker-machine reachability is not runtime egress proof; do not "
        "create a probe flow or invoke an employee transaction in this assessment.",
        ("runtimeEndpoints", "managedRuntimeTestRun"),
    ),
    "INFRA-006": (
        "Effective connector policy",
        "Review every effective policy against the selected agent's exact direct "
        "and invoked-flow connectors, including blocked and cross-group combinations.",
        ("selectedConnectors", "effectivePolicies", "connectorCompatibility"),
    ),
    "CONFIG-013": (
        "Native knowledge indexing and access",
        "Inspect the selected DA's native knowledge sources and current indexing "
        "state in Copilot Studio. Verify representative intended-user access; "
        "a missing local knowledge directory is not proof of native absence.",
        ("nativeKnowledgeSources", "indexingState", "intendedUserAccessTests"),
    ),
    "DA-HANDOFF-001": (
        "Selected DA handoff targets and access",
        "Inventory enabled native handoffs for this agent, verify their exact "
        "target identities and permissions, and record representative intended-user "
        "handoff tests. Legacy PVA discovery is not native handoff evidence.",
        ("enabledHandoffTargets", "targetPermissions", "handoffTestRuns"),
    ),
    "DA-RUNTIME-001": (
        "Published signed-in employee execution",
        "Record fresh signed-in employee test runs for the intended published "
        "channel, exact agent and release. Include correlation IDs and outcomes; "
        "do not substitute authored content or Connected bindings.",
        ("publishedChannel", "publishedRelease", "employeeTestRunIds", "outcomes"),
    ),
}

for _keys, _title, _action, _fields in (
    (
        ("LIC-FLOW-001",),
        "Licensing route for the exact invoked flows",
        "Have the licensing owner classify each exact invoked flow and its connectors "
        "and confirm the applicable licensing route. Record the flow-by-flow rationale; "
        "connector tier alone does not establish how a flow is billed. "
        "Audience entitlement coverage is reviewed separately under LIC-FLOW-002.",
        ("invokedFlowIds", "flowClassifications", "licensingRoute", "licensingOwnerReview"),
    ),
    (
        ("LIC-FLOW-002",),
        "Audience coverage for the approved flow licensing route",
        "Have the licensing owner reconcile the intended employee audience with the "
        "route established under LIC-FLOW-001. Record entitlement or applicable "
        "coverage evidence for that audience, not the maker's license or unrelated "
        "Dataverse bot-sharing inventory. Do not authenticate the maker to Graph.",
        ("deploymentAudience", "licensingRoute", "audienceCoverage", "licensingOwnerReview"),
    ),
    (
        ("WD-ENTRA-SCOPE-001", "WD-ENTRA-CONSENT-001", "WD-ASSIGN-001",
         "WD-ENTRA-NAMEID-001", "WD-ENTRA-SIGNOPT-001", "WD-CONN-010", "WD-CONN-102"),
        "Workday Entra administrator evidence",
        "Review the validated Workday Connect Entra administrator workbook for "
        "the exact tenant/application and certificate. Keep portal attestations manual; "
        "do not authenticate the maker to Graph or repeat healthy configuration.",
        ("entraTenant", "applicationIdentity", "administratorWorkbook", "certificateMetadata"),
    ),
    (
        ("WD-API-CLIENT-001", "WD-TENANT-001", "WD-SEC-003", "WD-NET-001", "WD-REST-001"),
        "Workday administrator configuration evidence",
        "Review the Workday administrator workbook and validated endpoints for the "
        "same tenant/application/certificate. Verify scenario permissions with the "
        "Workday administrator; do not request ISU credentials or execute SOAP probes.",
        ("workdayTenant", "administratorWorkbook", "validatedEndpoints", "scenarioPermissions"),
    ),
    (
        ("WD-CONN-AUTH-001",),
        "Workday connection authentication configuration",
        "Review the exact Workday connection target and configured authentication "
        "mode with its owner. Record the tenant/application match and authentication "
        "configuration review. Connected status is not signed-in employee execution; "
        "this check does not repeat attachment or parameter-sharing verification.",
        ("workdayConnectionTarget", "authenticationMode", "authenticationOwnerReview"),
    ),
    (
        ("WD-CONN-013",),
        "Workday connection parameter-sharing consent",
        "In the selected agent's Connection Settings, review both Workday connection "
        "entries and confirm 'Allow permission to share parameters' for each. Record "
        "each exact connection target and its setting. Flow exposure is reviewed "
        "separately under WD-DA-ATTACH-001.",
        ("workdayConnectionTarget", "parameterSharing"),
    ),
):
    for _key in _keys:
        DA_MANUAL_REQUIREMENTS[_key] = (_title, _action, _fields)

for _key, _title, _criterion, _field in (
    ("WD-ENTRA-SCOPE-001", "Entra application scopes",
     "Record the approved scopes for this exact application.", "approvedScopes"),
    ("WD-ENTRA-CONSENT-001", "Entra administrator consent",
     "Record consent granted for the application's required permissions.", "administratorConsent"),
    ("WD-ASSIGN-001", "Workday enterprise application assignments",
     "Record the intended employee users/groups assigned to this application.", "audienceAssignments"),
    ("WD-ENTRA-NAMEID-001", "Workday federation NameID mapping",
     "Record the approved NameID claim and matching Workday identity mapping.", "nameIdMapping"),
    ("WD-ENTRA-SIGNOPT-001", "Federation signing options",
     "Record the signing options approved for this Workday federation.", "signingOptions"),
    ("WD-CONN-010", "Cross-system federation configuration",
     "Record the matching Entra and Workday federation settings.", "federationConfiguration"),
    ("WD-CONN-102", "Cross-system certificate agreement",
     "Record the matching certificate metadata and validity in both systems.", "certificateAgreement"),
    ("WD-API-CLIENT-001", "Workday API client registration",
     "Record the exact registered client and approved grant configuration.", "apiClientRegistration"),
    ("WD-TENANT-001", "Workday tenant authentication policy",
     "Record the employee authentication policy for the selected tenant.", "tenantAuthenticationPolicy"),
    ("WD-SEC-003", "Workday write-scenario permissions",
     "Record permission approval for each enabled write scenario without executing writes.", "writeScenarioPermissions"),
    ("WD-NET-001", "Workday network allowlist",
     "Record the approved network allowlist; this is not managed-runtime reachability proof.", "networkAllowlist"),
    ("WD-REST-001", "Workday REST endpoint and tenant agreement",
     "Record the approved REST host, tenant and enabled scenario endpoint mapping.", "restEndpointAgreement"),
):
    _, _action, _fields = DA_MANUAL_REQUIREMENTS[_key]
    DA_MANUAL_REQUIREMENTS[_key] = (_title, f"{_action} {_criterion}", (*_fields, _field))

DA_DEFERRED_ADMIN_CHECKS = frozenset({
    "WD-ENTRA-SCOPE-001", "WD-ENTRA-CONSENT-001", "WD-ASSIGN-001",
    "WD-ENTRA-NAMEID-001", "WD-ENTRA-SIGNOPT-001", "WD-CONN-010", "WD-CONN-102",
    "WD-API-CLIENT-001", "WD-TENANT-001", "WD-SEC-003", "WD-NET-001",
})


def manual_evidence_requirement(runner, fields: tuple[str, ...]) -> dict:
    """Describe target-bound evidence without accepting a saved setup override."""
    config = getattr(runner, "config", None) or {}
    selected = active_agent(config, getattr(runner, "agent_slug", None))
    return {
        "evidenceType": "manual_requirement",
        "accepted": False,
        "target": {
            "environmentId": getattr(runner, "env_id", None) or config.get("environmentId", ""),
            "agentId": selected.get("botId", ""),
            "agentSchemaName": selected.get("schemaName", ""),
            "agentSlug": selected.get("slug", ""),
            "realm": (getattr(runner, "validation_context", None) or {}).get(
                "realm", config.get("realm", "")
            ),
        },
        "requiredFields": ["observedAt", "source", "reviewerRole", "configurationRevision", *fields],
    }


def run_da_baseline_checks(runner) -> list[CheckResult]:
    """Keep unsupported assertions explicit; never reinterpret attestations as passes."""
    specs = {spec.key: spec for spec in DA_CATALOG}
    rows: list[CheckResult] = []
    requested = getattr(runner, "should_execute", lambda _key: True)
    declarative = is_declarative_agent(runner)
    for key, (title, action, fields) in DA_MANUAL_REQUIREMENTS.items():
        if not requested(key):
            continue
        deferred = declarative and key in DA_DEFERRED_ADMIN_CHECKS
        evidence = manual_evidence_requirement(runner, fields)
        evidence["acceptanceCriteria"] = action
        if deferred:
            evidence.update({
                "administratorCheckDeferred": True,
                "reason": "Maker administrator permissions are not assumed.",
                "evidenceBoundary": "skipped_not_verified_administrator_prerequisite",
            })
        rows.append(CheckResult(
            checkpoint_id=key,
            category="DA Baseline",
            priority=Priority.HIGH.value,
            status=(Status.SKIPPED.value if deferred else
                    Status.MANUAL.value if declarative else Status.BLOCKED.value),
            description=title,
            result=(
                "Administrator-only verification skipped; maker administrator permissions "
                "are not assumed. This prerequisite has not been verified."
                if deferred else
                "This assessment has not accepted target-bound evidence for this requirement."
                if declarative else "The selected target has no explicit DA context."
            ),
            remediation=(
                "Keep the administrator workbook as supporting evidence. Role-aware "
                "verification is deferred; do not grant administrator permissions just "
                "to run FlightCheck."
                if deferred else action
            ),
            evidence=evidence,
            roles=list(specs[key].owners),
            block_reason="" if declarative else BLOCK_REASON_CHECKPOINT_CONTRACT,
        ))
    if requested("ENV-001"):
        native = next((
            row for row in getattr(runner, "results", [])
            if row.checkpoint_id == "DA-AGENT-001"
        ), None)
        verified = declarative and native is not None and native.status == Status.PASSED.value
        rows.append(CheckResult(
            checkpoint_id="ENV-001",
            category="DA Baseline",
            priority=Priority.HIGH.value,
            status=Status.PASSED.value if verified else Status.BLOCKED.value,
            description="Selected native environment access",
            result=(
                "Exact-agent native access was verified within the selected environment."
                if verified else "Exact-agent native access within the selected environment was not verified."
            ),
            remediation="" if verified else "Restore exact native target access and rerun this assessment.",
            evidence={
                "sourceCheckpoint": "DA-AGENT-001",
                "environmentId": getattr(runner, "env_id", ""),
                "evidenceBoundary": "native_agent_access_not_billing_or_database_provisioning",
            },
            roles=[Role.POWER_PLATFORM_ADMIN.value],
            block_reason="" if verified else BLOCK_REASON_CHECKPOINT_CONTRACT,
        ))
    return rows
