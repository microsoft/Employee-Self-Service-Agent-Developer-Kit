# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Environment Configuration Validation (ENV-xxx)

Checks Power Platform environment, Dataverse, DLP policies, and related config.
"""

from ..runner import CheckResult, Status, Priority

DOC_BASE = "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"


def run_environment_checks(runner) -> list[CheckResult]:
    """Execute all environment checks using the PP Admin client."""
    pp = runner.pp_admin
    env_id = runner.env_id
    results: list[CheckResult] = []

    if not env_id:
        results.append(CheckResult(
            checkpoint_id="ENV-001", category="Environment",
            priority=Priority.CRITICAL.value, status=Status.FAILED.value,
            description="Power Platform environment exists",
            result="Could not derive environment ID from Dataverse URL",
            remediation="Verify the environment URL in my/config.json.",
        ))
        return results

    # ---- ENV-001: Environment exists ----
    try:
        env = pp.get_environment(env_id)
        if "_error" in env:
            results.append(CheckResult(
                checkpoint_id="ENV-001", category="Environment",
                priority=Priority.CRITICAL.value, status=Status.WARNING.value,
                description="Power Platform environment exists",
                result=f"Unable to query environment: {env['_error']}",
                remediation="Requires Power Platform Administrator role.",
                doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
            ))
            return results

        props = env.get("properties", {})
        display_name = props.get("displayName", env_id)
        results.append(CheckResult(
            checkpoint_id="ENV-001", category="Environment",
            priority=Priority.CRITICAL.value, status=Status.PASSED.value,
            description="Power Platform environment exists",
            result=f"Environment: {display_name}",
            doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
        ))

        # ---- ENV-002: Dataverse provisioned ----
        db_state = (
            props.get("linkedEnvironmentMetadata", {})
            .get("resourceProvisioningState", "")
        )
        # Also check databaseType
        db_type = props.get("databaseType", "")
        if db_state.lower() == "succeeded" or db_type:
            results.append(CheckResult(
                checkpoint_id="ENV-002", category="Environment",
                priority=Priority.CRITICAL.value, status=Status.PASSED.value,
                description="Dataverse database provisioned",
                result=f"State: {db_state or 'Available'}, Type: {db_type or 'N/A'}",
                doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="ENV-002", category="Environment",
                priority=Priority.CRITICAL.value, status=Status.FAILED.value,
                description="Dataverse database provisioned",
                result=f"Provisioning state: {db_state or 'Unknown'}",
                remediation="Enable Dataverse database for this environment.",
                doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
            ))

        # ---- ENV-003: Environment type ----
        env_type = props.get("environmentSku", "")
        results.append(CheckResult(
            checkpoint_id="ENV-003", category="Environment",
            priority=Priority.HIGH.value, status=Status.PASSED.value,
            description="Environment type",
            result=f"Type: {env_type}",
            doc_link=f"{DOC_BASE}/prepare#set-up-your-power-platform-environment",
        ))

    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="ENV-001", category="Environment",
            priority=Priority.CRITICAL.value, status=Status.WARNING.value,
            description="Power Platform environment",
            result=f"Unable to check: {e}",
            remediation="Ensure Power Platform Admin permissions.",
        ))

    # ---- ENV-008: DLP policies ----
    try:
        policies = pp.get_dlp_policies_for_env(env_id)
        if policies:
            results.append(CheckResult(
                checkpoint_id="ENV-008", category="Environment",
                priority=Priority.HIGH.value, status=Status.PASSED.value,
                description="DLP policies configured",
                result=f"{len(policies)} policy/policies apply to this environment",
                doc_link=f"{DOC_BASE}/prepare#allow-the-external-systems-connector",
            ))
        else:
            results.append(CheckResult(
                checkpoint_id="ENV-008", category="Environment",
                priority=Priority.HIGH.value, status=Status.WARNING.value,
                description="DLP policies configured",
                result="No DLP policies found for this environment",
                remediation="Review DLP policies in [PP admin center](https://admin.powerplatform.microsoft.com) to ensure connectors are allowlisted.",
                doc_link=f"{DOC_BASE}/prepare#allow-the-external-systems-connector",
            ))
    except Exception as e:
        results.append(CheckResult(
            checkpoint_id="ENV-008", category="Environment",
            priority=Priority.HIGH.value, status=Status.WARNING.value,
            description="DLP policies",
            result=f"Unable to check: {e}",
            remediation="Requires Power Platform Admin role.",
        ))

    return results
