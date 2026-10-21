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
        rows.append(CheckResult(
            checkpoint_id=key,
            category="DA Baseline",
            priority=Priority.HIGH.value,
            status=Status.MANUAL.value if declarative else Status.BLOCKED.value,
            description=title,
            result=(
                "This assessment has not accepted target-bound evidence for this requirement."
                if declarative else "The selected target has no explicit DA context."
            ),
            remediation=action,
            evidence=manual_evidence_requirement(runner, fields),
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
