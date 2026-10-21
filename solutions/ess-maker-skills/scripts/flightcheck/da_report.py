# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline, presentation-only DA report with shared work and distinct assertions."""

from __future__ import annotations

from collections import Counter
from html import escape
import json
from pathlib import Path
import re
import shlex

from .da_contract import DA_REVIEWABLE_FEATURES
from .da_readiness import DA_EVIDENCE_SCHEMA
from .runner import CheckResult, RunResult, _APP_ICON_DATA_URI, _REPORT_CSS, _mask_sensitive, _slug


_BASE_FIELDS = {"observedAt", "source", "reviewerRole", "configurationRevision"}
_GROUPS = {
    "Confirm which features you use": ("DA-INTEGRATIONS-001",),
    "Licenses for automated tasks": ("LIC-FLOW-001", "LIC-FLOW-002"),
    "Workday connection settings": ("WD-CONN-AUTH-001", "WD-CONN-013", "WD-DA-ATTACH-001"),
    "Ask your Microsoft Entra administrator": (
        "WD-ENTRA-SCOPE-001", "WD-ENTRA-CONSENT-001", "WD-ASSIGN-001",
        "WD-ENTRA-NAMEID-001", "WD-ENTRA-SIGNOPT-001", "WD-CONN-010", "WD-CONN-102",
    ),
    "Ask your Workday administrator": (
        "WD-API-CLIENT-001", "WD-TENANT-001", "WD-NET-001", "WD-SEC-003", "WD-REST-001",
    ),
    "Billing and capacity review": ("PRE-004", "PRE-005", "PRE-006", "ENV-CAPACITY-001"),
    "Check the services your agent uses": ("ENV-004", "DA-CONN-001", "SN-CONN-001"),
    "Testing and approval": ("QA-001", "QA-002", "QA-012", "PUB-003", "PUB-006"),
}
_GROUP_BY_ID = {key: title for title, keys in _GROUPS.items() for key in keys}
_STAGE_ORDER = (
    "Agent setup", "Environment and connections", "Licenses and billing", "Conversations",
    "Knowledge and transfers", "Workday", "Employee testing and release", "Features to confirm", "Other checks",
)
_GROUP_STEPS = {
    "Licenses for automated tasks": "Review task licensing and employee coverage.",
    "Workday connection settings": "Confirm sign-in, available tasks and sharing permissions.",
    "Ask your Microsoft Entra administrator": "Review Workday sign-in and application permissions.",
    "Ask your Workday administrator": "Review the Workday application, security and network settings.",
    "Billing and capacity review": "Confirm billing and capacity for expected employee usage.",
    "Check the services your agent uses": "Review the incomplete connection checks with your administrator.",
    "Testing and approval": "Complete the agreed tests and obtain release approvals.",
    "Confirm which features you use": "Confirm which features you use before completing their checks.",
}
_REVIEW_STEPS = {
    "DA-INTEGRATIONS-001": (
        "Review the services FlightCheck found and confirm which other features this agent uses.",
        "Record Yes or No for each feature you can confirm. Leave anything you do not know unresolved.",
        "Have the agent owner review the completed form and include it with the next full check. "
        "Features marked Yes still need their own checks.",
    ),
    "LIC-FLOW-001": (
        "Ask your licensing owner to list each automated task and the services it uses.",
        "Record the licensing arrangement that applies to each task.",
    ),
    "LIC-FLOW-002": (
        "Confirm which employees will use the automated tasks.",
        "Ask your licensing owner to confirm that the agreed arrangement covers those employees.",
    ),
    "WD-CONN-013": (
        "Open the agent's `Connection Settings` and find both Workday entries.",
        "Confirm `Allow permission to share parameters` for each entry.",
    ),
    "WD-DA-MAKER-001": (
        "Run the supported Workday tasks in the **Copilot Studio** `Test` pane.",
        "Record each task, the date and time, the agent version and the result.",
        "Keep these results separate from employee tests of the published agent.",
    ),
    "DA-RUNTIME-001": (
        "Test the published agent with signed-in employees in the intended channel.",
        "Record a reference and result for each test, including the published version.",
    ),
}
_REASONS = {
    "required_evidence_unverified": "We still need the results of this check or a completed review.",
    "unknown_applicability": "Confirm whether you use this feature. If you do, it needs to be checked.",
    "missing_results": "A required result was not produced.",
    "evidence_revision_mismatch": "The review does not match the agent settings checked in this report.",
    "evidence_expired_or_future": "The review is out of date or its dates are in the future.",
    "no_approved_dispatch": "This check is not yet available in FlightCheck. Ask your support team for guidance.",
    "expected_result_missing": "FlightCheck did not return a result for this required check.",
    "duplicate_status_bucket": "FlightCheck returned conflicting or repeated results. Ask your support team to investigate.",
    "evidence_target_mismatch": "The review is for a different agent or environment.",
    "evidence_review_missing_or_wrong_role": "The appropriate owner still needs to review this information.",
    "evidence_source_missing": "Add a reference to the test results or approval record.",
    "evidence_validity_window_invalid": "Include when the check and review took place and when the review expires.",
    "evidence_outcome_invalid": "Record whether the check passed or found a problem.",
    "evidence_cannot_replace_automated_verification": "A written approval cannot replace this automatic check.",
    "evidence_required_details_missing": "Some required review details are missing.",
    "evidence_kind_mismatch": "Provide the type of test or approval requested for this check.",
    "employee_runtime_correlation_missing": "Include a reference and result for each employee test.",
    "employee_runtime_outcome_conflict": "The overall result does not agree with the individual employee test results.",
    "test_pane_is_not_published_employee_runtime": "Test with a signed-in employee in the published channel, not only in Copilot Studio.",
    "maker_test_evidence_invalid": "Include the Copilot Studio test result and the time it was tested.",
    "evidence_not_applicable_to_observed_requirement": "This review cannot be used for the check recorded in this report.",
    "evidence_features_invalid_or_conflicting": "The feature choices are incomplete, unsupported or conflict with services already found. Review the feature form.",
}
_ISSUES = {
    "verified_configuration_snapshot_unavailable": "We could not confirm the agent settings needed to match reviews to this report.",
    "producer_execution_error": "One or more checks could not finish. Ask your administrator to review the details below.",
    "required_client_unavailable": "FlightCheck could not access a service needed for this review.",
    "unrecognized_evidence_checkpoint": "Some submitted reviews do not match a check in this report.",
}
_STATUS_LABELS = {
    "Failed": "Needs fixing", "Blocked": "Could not check", "Error": "Check could not finish",
    "Warning": "Needs review", "Manual": "Review needed", "Skipped": "Not checked",
    "NotConfigured": "Not set up", "satisfied": "Confirmed", "defect": "Needs fixing",
    "incomplete": "More information needed", "unknown": "Please confirm",
    "excluded": "Outside this review", "not_applicable": "Does not apply", "advisory": "For information",
}
_CHECK_COPY = {
    "PRE-001": ("Employee licenses", "Ask your licensing owner to confirm that the employees who will use this agent have the required licenses."),
    "PRE-002": ("Your permission to build and edit", "Confirm your license allows you to edit this agent and that you have access to its environment."),
    "PRE-003": ("Use in Microsoft Teams", "Confirm whether employees will use the agent in Microsoft Teams."),
    "PRE-004": ("Capacity for your employees", "Review who will use the agent, expected usage and the capacity needed to support them."),
    "PRE-005": ("Billing for this environment", "Ask your billing owner to confirm the billing policy and prepaid or pay-as-you-go coverage for this environment."),
    "PRE-006": ("Purchased capacity", "Confirm that your purchased capacity or alternative billing arrangement covers this environment."),
    "ENV-CAPACITY-001": ("Capacity assigned to this environment", "Ask your administrator to review the capacity assigned here and how it covers the expected employee usage."),
    "ENV-001": ("Access to the agent's environment", "Confirm you can access this agent in the intended environment."),
    "ENV-002": ("Dataverse database setup", "If the services your agent uses require Dataverse, ask your administrator to confirm that the linked database is ready."),
    "ENV-004": ("Connections to your services", "Review the services this agent uses and confirm that the required connections are available. See the shared connection issue above."),
    "ENV-004-COVERAGE": ("Services that still need to be identified", "Review the shared connection issue to confirm which services your agent uses."),
    "ENV-009": ("Custom Dataverse changes", "Confirm whether your agent depends on custom changes to Dataverse."),
    "INFRA-003": ("Access to external services", "If your agent uses external services, ask your administrator to test access from where the agent runs. A test from your computer alone is not enough."),
    "INFRA-006": ("Policies for connected services", "Ask your administrator to confirm that your organization's policies allow the services this agent uses to work together."),
    "CONFIG-013": ("Knowledge sources and employee access", "If your agent uses knowledge sources, confirm that they have finished processing and that intended employees can access the information."),
    "DA-HANDOFF-001": ("Conversation transfers", "Confirm whether conversations are passed to another assistant. If so, check the destination, permissions and employee experience."),
    "DA-RUNTIME-001": ("Employee testing of the published agent", "Test the published agent with signed-in employees in the intended channel. Record each test reference and result; a Copilot Studio test alone is not enough."),
    "DA-SN-RUNTIME-001": ("Employee testing of ServiceNow tasks", "Test the ServiceNow tasks employees will use and record the results for this agent and version."),
    "DA-AGENT-001": ("Access to your agent", "Confirm that the selected agent can be opened in the intended environment."),
    "DA-CONTENT-001": ("Agent content", "Review whether FlightCheck could read the content of this agent."),
    "DA-INTEGRATIONS-001": ("Features included in this review", "Complete the feature review form for this agent. Confirm each choice without changing the services already found."),
    "DA-CUSTOM-TOPICS-001": ("Custom conversations", "Review your custom conversations, when they start, the services they use and representative test results."),
    "DA-CONN-001": ("Agent connections", "Confirm that each service used directly by this agent has the right connection. See the shared connection issue above."),
    "SN-CONN-001": ("ServiceNow connections", "Confirm the ServiceNow connections used by this agent. See the shared connection issue above."),
    "ESS-SOLN-001": ("Employee Self-Service installation", "Ask your administrator to confirm the installation and version details for this agent."),
    "LIC-FLOW-001": ("Licensing for each automated task", "Ask your licensing owner to review each automated task and the services it uses, and record which licensing arrangement applies. Employee coverage is checked separately."),
    "LIC-FLOW-002": ("License coverage for your employees", "Using the agreed licensing arrangement, confirm that it covers the employees who will use these automated tasks. Your own license alone is not enough."),
    "WD-ENTRA-SCOPE-001": ("Application permissions", "Ask your Microsoft Entra administrator to record the permissions approved for the Workday application."),
    "WD-ENTRA-CONSENT-001": ("Administrator approval of permissions", "Ask your Microsoft Entra administrator to confirm that the required Workday application permissions have been approved."),
    "WD-ASSIGN-001": ("Employees allowed to use Workday", "Confirm the employee users and groups assigned to the Workday application."),
    "WD-ENTRA-NAMEID-001": ("Matching employee sign-in identities", "Ask your administrator to confirm that the employee sign-in identifier matches the identity expected by Workday."),
    "WD-ENTRA-SIGNOPT-001": ("Sign-in security settings", "Ask your administrator to confirm the signing settings that protect Workday sign-in."),
    "WD-CONN-010": ("Matching sign-in settings", "Ask your administrators to confirm that Microsoft Entra and Workday have matching sign-in settings."),
    "WD-CONN-102": ("Matching sign-in certificates", "Ask your administrators to confirm that both systems use matching certificates that are still valid."),
    "WD-API-CLIENT-001": ("Workday application registration", "Ask your Workday administrator to confirm the registered application and approved sign-in method."),
    "WD-TENANT-001": ("Workday sign-in policy", "Ask your Workday administrator to confirm the employee sign-in policy for the Workday environment you use."),
    "WD-SEC-003": ("Permission to make Workday changes", "If employees can submit changes to Workday, ask your administrator to approve each supported action. This review does not submit changes."),
    "WD-NET-001": ("Network access allowed by Workday", "Ask your Workday administrator to review the allowed network addresses. This alone does not prove the agent can reach Workday."),
    "WD-REST-001": ("Workday service addresses", "Ask your Workday administrator to confirm that the service addresses point to the correct Workday environment and supported tasks."),
    "WD-CONN-AUTH-001": ("Workday connection sign-in", "Review the connection with its owner and confirm the Workday environment, application and sign-in method. A Connected status alone does not prove an employee test will work."),
    "WD-CONN-013": ("Permission to share connection settings", "In the agent's `Connection Settings`, check both Workday entries and confirm `Allow permission to share parameters` for each."),
    "WD-DA-MAKER-001": ("Test Workday in Copilot Studio", "Run the Workday tasks in **Copilot Studio**'s `Test` pane. Record what you tested, when, the version and the result. Published employee testing is a separate check."),
    "WD-DA-ATTACH-001": ("Workday tasks available to this agent", "In the agent's Workday connection settings, confirm that the reviewed automated tasks are available to this agent. Record their references; sharing permission is checked separately."),
    "WD-DA-PKG-001": ("Workday extension installation", "Confirm that the Workday extension is installed for this Employee Self-Service HR agent."),
    "WD-DA-FLOW-001": ("Workday automated tasks", "Confirm that the required Workday automated tasks are present and turned on."),
    "WD-DA-AUTH-001": ("Permission to run Workday tasks", "Confirm that this agent is authorized to use the required Workday tasks on behalf of signed-in employees."),
    "WD-DA-TOPIC-001": ("Built-in Workday conversations", "Confirm that the supported built-in Workday conversations are present and turned on."),
    "WD-DA-WIRING-001": ("Workday setup when a conversation starts", "Confirm that starting a conversation runs the required Workday setup."),
    "WD-CONN-012": ("Connections required by Workday", "Confirm that each required Workday connection is linked to a working connection."),
    "DV-CONN-001": ("Workday's Dataverse connection", "Confirm that the Dataverse connection required by Workday is active and linked correctly."),
    "WD-REST-002": ("Employee context for Workday", "Confirm that the conversation uses the supported Workday step for identifying the signed-in employee."),
    "WD-REF-001": ("Custom Workday settings", "Confirm whether you have customized Workday settings that need review."),
    "WD-WF-CAT-001": ("Custom Workday tasks", "Confirm whether you have custom Workday tasks that need review."),
    "CONFIG-007": ("Agent instructions", "Review the instructions that guide your agent."),
    "CONFIG-005": ("Suggested questions", "Review the starter questions employees see."),
    "TOPIC-011": ("Available conversations", "Review the conversations included in your agent."),
    "CONFIG-012": ("Employee context", "Review the employee information used by your agent."),
    "CONFIG-014": ("Conversation descriptions", "Review whether conversation descriptions clearly explain what each conversation does."),
    "TOPIC-TRIGGER-NNN": ("Custom conversation starting points", "Confirm whether you have custom conversations and review when they start."),
    "TOPIC-INTEGRATION-NNN": ("Services used by custom conversations", "Confirm whether custom conversations use additional services that need checking."),
    "EXT-002": ("Search across connected content", "Ask your administrator whether your agent uses connected search sources, called Microsoft Graph connectors."),
    "EXT-002-ACL": ("Employee access to connected content", "If connected content is used, confirm that employees can only see information they are allowed to access."),
    "EXT-002-NNN": ("Connected content sources", "Confirm which additional content sources need to be checked."),
    "QA-001": ("Representative test questions", "Agree on a set of test questions that covers the tasks employees need, including common and important cases."),
    "QA-002": ("Run the agreed tests", "Run the agreed test questions against this agent and keep the results."),
    "QA-012": ("Review answer quality", "Review the test results against your agreed accuracy target."),
    "PUB-001": ("Agent export file", "Review whether the agent export file was created successfully and can be opened. This does not verify import or publication."),
    "PUB-002": ("Moving changes between environments", "Confirm whether you need to move this version to another environment, and review that process if you do."),
    "PUB-003": ("Business approval", "Have the business owner review employee testing and record approval for the planned release."),
    "PUB-006": ("Microsoft 365 administrator approval", "Obtain the Microsoft 365 administrator's approval for employees to use this agent."),
    "PUB-011": ("Time for Microsoft 365 Copilot rollout", "Allow up to 48 hours for changes to appear in Microsoft 365 Copilot."),
    "DA-PLAN-COVERAGE": ("Checks included in this report", "Review any required checks that FlightCheck could not complete."),
}
_FIELD_LABELS = {
    "features": "Features used by this agent; confirm Yes or No for each choice",
    "customDataverseComponents": "Custom Dataverse components used by this agent",
    "solutionOwnership": "Solutions that own those custom components",
    "customizationReview": "Review of the custom changes and deployment process",
    "connectedSourceIds": "Connected search sources used by this agent",
    "sourceConfigurationReview": "Review of the connected search setup",
    "crawlAndIndexingResults": "Recent search processing results",
    "itemPermissionReview": "Review of who may access the connected content",
    "allowedAndDeniedAccessTests": "Tests of allowed and denied employee access",
    "customWorkdaySettings": "Custom Workday settings used by this agent",
    "scenarioBindings": "Workday tasks and connections used by those settings",
    "configurationOwnerReview": "Review by the owner of those settings",
    "enabledCustomScenarios": "Custom Workday tasks in use",
    "scenarioCoverage": "Which custom Workday tasks the tests cover",
    "readOnlyTestResults": "Results from the approved read-only tests",
    "enabledCustomConversations": "Custom conversations in use",
    "startingConditionsReview": "Review of when those conversations start",
    "dependencyReview": "Review of the services those conversations use",
    "sourceRealm": "Environment the changes came from",
    "destinationRealm": "Environment the changes were moved to",
    "promotionApproval": "Approval to move those changes",
    "promotionResult": "Recorded result of moving the changes",
    "deploymentAudience": "Employees who will use the agent", "publishedAudience": "Employees who will use the published agent",
    "audienceEntitlements": "Licenses covering those employees", "audienceCoverage": "How those employees are covered",
    "audienceSizing": "Expected number of employees", "makerEntitlement": "Your license to build and edit",
    "effectiveEnvironmentAccess": "Your access to this environment", "expectedUsage": "Expected usage",
    "capacitySizing": "Capacity needed for that usage", "environmentAllocation": "Capacity assigned to this environment",
    "environmentBillingPolicy": "Billing policy for this environment", "billingRoute": "How usage will be paid for",
    "billingCoverage": "Billing coverage for this environment", "purchasedEntitlement": "Purchased capacity or billing arrangement",
    "environmentCoverage": "How the purchase covers this environment", "invokedFlowIds": "References for each automated task",
    "flowClassifications": "Services used by each task and its licensing category", "licensingRoute": "Agreed licensing arrangement",
    "licensingOwnerReview": "Licensing owner's review", "selectedConnectors": "Services this agent connects to",
    "effectivePolicies": "Policies that apply to those services", "connectorCompatibility": "Whether those services are allowed to work together",
    "runtimeDependencies": "Services that require Dataverse", "linkedDataverseEnvironment": "Linked Dataverse environment",
    "provisioningState": "Whether the database is ready", "runtimeEndpoints": "Service addresses the agent must reach",
    "managedRuntimeTestRun": "Access test from where the agent runs", "nativeKnowledgeSources": "Knowledge sources used by the agent",
    "indexingState": "Whether the knowledge sources have finished processing", "intendedUserAccessTests": "Employee access test results",
    "enabledHandoffTargets": "Where conversations can be transferred", "targetPermissions": "Permission to use those destinations",
    "handoffTestRuns": "Conversation transfer test results", "publishedChannel": "Where employees use the published agent",
    "publishedRelease": "Published version tested", "employeeTestRunIds": "References for employee tests",
    "employeeTestRuns": "Employee tests and their references", "outcomes": "Result of each employee test",
    "outcome": "Test result", "entraTenant": "Microsoft Entra organization",
    "applicationIdentity": "Workday application being reviewed", "administratorWorkbook": "Administrator's completed setup workbook",
    "certificateMetadata": "Sign-in certificate details and expiry", "approvedScopes": "Approved application permissions",
    "administratorConsent": "Administrator approval of permissions", "audienceAssignments": "Employees and groups allowed to use the application",
    "nameIdMapping": "How employee sign-in identities match", "signingOptions": "Approved security settings for Workday sign-in",
    "federationConfiguration": "Matching Microsoft Entra and Workday sign-in settings",
    "certificateAgreement": "Confirmation that both systems use matching, valid certificates",
    "workdayTenant": "Workday environment", "validatedEndpoints": "Approved Workday service addresses",
    "scenarioPermissions": "Permissions for the supported employee tasks", "apiClientRegistration": "Registered Workday application and sign-in method",
    "tenantAuthenticationPolicy": "Employee sign-in policy", "writeScenarioPermissions": "Approval for each action that changes Workday data",
    "networkAllowlist": "Network addresses Workday allows", "restEndpointAgreement": "Matching Workday service addresses and environment",
    "workdayConnectionTarget": "Workday environment and application used by the connection", "authenticationMode": "Connection sign-in method",
    "authenticationOwnerReview": "Connection owner's sign-in review", "parameterSharing": "Sharing permission for each Workday connection",
    "agentAttachments": "Tasks made available to this agent", "exposedFlowIds": "References for those tasks",
    "makerTestCategory": "Where the Copilot Studio test was run", "testTimestamp": "Date and time tested",
    "releaseRevision": "Agent version tested", "enabledScenarios": "Employee tasks enabled",
    "serviceNowTarget": "ServiceNow environment tested", "scenario": "Task tested",
    "testOrApprovalRecord": "Test results or approval record",
}


def _check_copy(key: str) -> tuple[str, str]:
    return _CHECK_COPY.get(key, (
        "Additional check", "Ask the owner to review the findings in the support details below.",
    ))


def _role_name(role: str) -> str:
    return {
        "ESS Maker": "Agent owner", "ESS Maker / Agent Developer": "Agent owner",
        "Microsoft 365 Admin": "Microsoft 365 administrator",
        "Power Platform Admin": "Power Platform administrator", "Entra Admin": "Microsoft Entra administrator",
        "Workday Admin": "Workday administrator", "ServiceNow Admin": "ServiceNow administrator",
    }.get(role, role)


def _e(value) -> str:
    return escape(str(value), quote=True)


def _prose(value: str) -> str:
    tokens = re.split(r"(\[[^\]]+\]\(https?://[^\s)]+\)|\*\*[^*]+\*\*|`[^`]+`)", _mask_sensitive(value))
    parts = []
    for token in tokens:
        link = re.fullmatch(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", token)
        if link:
            parts.append(f'<a href="{_e(link[2])}" target="_blank" rel="noopener noreferrer">{_e(link[1])}</a>')
        elif token.startswith("**") and token.endswith("**"):
            parts.append(f"<strong>{_e(token[2:-2])}</strong>")
        elif token.startswith("`") and token.endswith("`"):
            parts.append(f"<code>{_e(token[1:-1])}</code>")
        else:
            parts.append(_e(token).replace("\n", "<br>"))
    return "".join(parts)


def _field_name(value: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", value).replace("_", " ").capitalize()


def _badge(status: str) -> str:
    color = {
        "Passed": "success", "satisfied": "success", "Failed": "danger", "defect": "danger",
        "Error": "danger", "Blocked": "attention", "Warning": "attention",
    }.get(status, "neutral")
    return f'<span class="badge {color}">{_e(_STATUS_LABELS.get(status, status))}</span>'


def _kind(entry: dict, rows: list) -> str:
    if entry["coverageState"] == "unknown":
        return "applicability"
    if any(row.evidence.get("administratorCheckDeferred") is True for row in rows):
        return "administrator"
    if entry["requiredEvidenceFields"]:
        return "evidence"
    return "verification"


def _template(assessment: dict, entry: dict) -> str:
    key = entry["checkpointId"]
    fields = set(entry["requiredEvidenceFields"]) - _BASE_FIELDS
    details: dict[str, object] = {field: "" for field in sorted(fields)}
    if key == "DA-INTEGRATIONS-001":
        states = {
            item["feature"]: item["applicability"] for item in assessment["coverage"]
            if item.get("feature")
        }
        details["features"] = {
            feature.value: (
                True if states.get(feature.value) == "applicable" else
                False if states.get(feature.value) == "not_applicable" else None
            )
            for feature in sorted(DA_REVIEWABLE_FEATURES, key=lambda feature: feature.value)
        }
    for field in {"employeeTestRunIds", "employeeTestRuns"} & fields:
        details[field] = []
    if "outcomes" in fields:
        details["outcomes"] = {}
    kind = (
        "feature_applicability" if key == "DA-INTEGRATIONS-001" else
        "published_employee_runtime" if key in {"DA-RUNTIME-001", "DA-SN-RUNTIME-001"}
        else "maker_test_pane" if key == "WD-DA-MAKER-001" else "manual_attestation"
    )
    return json.dumps({
        "schemaVersion": DA_EVIDENCE_SCHEMA,
        "records": [{
            "checkpointId": key, "target": assessment["target"],
            "configurationRevision": assessment["configurationRevision"],
            "reviewed": False, "reviewerRole": "", "source": "",
            "observedAt": "", "reviewedAt": "", "validUntil": "", "outcome": "",
            "evidenceKind": kind, "details": details,
        }],
    }, indent=2)


def _connection_warning(r: RunResult) -> CheckResult | None:
    return next((row for row in r.results
                 if row.checkpoint_id == "ENV-004-COVERAGE" and row.status != "Passed"), None)


def _stage(entry: dict) -> str:
    if entry["coverageState"] == "unknown":
        return "Features to confirm"
    group = _GROUP_BY_ID.get(entry["checkpointId"])
    area = entry["area"]
    if group == "Check the services your agent uses":
        return "Environment and connections"
    if area.startswith("Workday"):
        return "Workday"
    if area in {"Prerequisites", "Capacity", "Flow licensing"}:
        return "Licenses and billing"
    if area in {"Native agent", "ESS package"}:
        return "Agent setup"
    if area in {"Local files", "Custom topics"}:
        return "Conversations"
    if area in {"Knowledge", "Graph connector knowledge", "Handoff"}:
        return "Knowledge and transfers"
    if area in {"Publishing", "ALM promotion", "Employee runtime", "ServiceNow runtime"}:
        return "Employee testing and release"
    if area in {"Environment", "Connections", "Native connections", "Integration applicability",
                "Dataverse customization", "DLP", "Network", "ServiceNow"}:
        return "Environment and connections"
    return "Other checks"


def _stages(assessment: dict) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for entry in assessment["coverage"]:
        if entry["deploymentRequired"] or (entry["observed"] and entry["evidenceState"] == "advisory"):
            groups.setdefault(_stage(entry), []).append(entry)
    return {name: groups[name] for name in _STAGE_ORDER if name in groups}


def _stage_summary(entries: list[dict]) -> tuple[str, str]:
    required = [entry for entry in entries if entry["deploymentRequired"]]
    if any(entry["evidenceState"] == "defect" for entry in required):
        return "red", "Needs fixing"
    if any(entry["evidenceState"] != "satisfied" for entry in required):
        return "amber", "More checks needed"
    advisory_statuses = {
        row["status"] for entry in entries if not entry["deploymentRequired"] for row in entry["observed"]
    }
    if advisory_statuses & {"Failed", "Error", "Warning"}:
        return "amber", "Notes to review"
    if advisory_statuses & {"Skipped", "Blocked", "NotConfigured"}:
        return "gray", "Not fully checked"
    if required:
        return "green", "Required checks complete"
    if advisory_statuses == {"Passed"}:
        return "green", "Checks passed"
    return "gray", "Information only"


def _status_totals(r: RunResult) -> str:
    counts = Counter(row.status for row in r.results)
    return "".join(
        f'<span class="stat {style}" aria-label="{counts[status]} {_e(_STATUS_LABELS.get(status, status))}">'
        f'<i class="dot {dot}" aria-hidden="true"></i><b>{counts[status]}</b> '
        f'{_e(_STATUS_LABELS.get(status, status))}</span>'
        for status, style, dot in (
            ("Passed", "pass", "green"), ("Failed", "fail", "red"), ("Blocked", "manual", "gray"),
            ("Error", "fail", "red"), ("Warning", "warn", "amber"), ("Manual", "manual", "gray"),
            ("Skipped", "na", "gray"), ("NotConfigured", "na", "gray"),
        )
    )


def _synopsis(r: RunResult) -> str:
    tiles = []
    for index, (name, entries) in enumerate(_stages(r.da_assessment).items(), start=1):
        color, label = _stage_summary(entries)
        owners = sorted({
            _role_name(role) for entry in entries
            if entry["deploymentRequired"] and entry["evidenceState"] != "satisfied" for role in entry["roles"]
        })
        role = " + ".join(owners) if len(owners) <= 2 else "Several owners; see details"
        tiles.append(
            f'<a class="syn-tile {color}" href="#cat-{_slug(name)}">'
            f'<div class="syn-no">Stage {index}</div><div class="syn-name">{_e(name)}</div>'
            f'<div class="syn-role">{_e(label)}</div>'
            + (f'<div class="syn-role act">{_e(role)}</div>' if role else "")
            + '</a>'
        )
    return (
        '<section id="readiness" class="panel synopsis" aria-label="Readiness at a glance">'
        '<div class="syn-head"><h2>Readiness at a glance</h2>'
        '<span class="hint">Select a category to open its checks and next steps.</span></div>'
        f'<div class="syn-stats" aria-label="Recorded check totals">{_status_totals(r)}</div>'
        '<div class="syn-grid">' + "".join(tiles) + '</div>'
        '<p class="muted">Totals count recorded results. Category colors also include required reviews '
        'and checks that could not run. Not checked does not mean Passed.</p></section>'
    )


def _requirement(
    assessment: dict, entry: dict, rows: list, *, single: bool = False, connection_warning: bool = False,
) -> str:
    key = entry["checkpointId"]
    title, next_step = _check_copy(key)
    kind = _kind(entry, rows)
    shared_connection = (
        connection_warning and key in {"ENV-004", "DA-CONN-001", "SN-CONN-001"}
        and not any(row.status in {"Failed", "Error"} for row in rows)
    )
    observed = " ".join(_badge(status) for status in dict.fromkeys(row.status for row in rows))
    reason = " ".join(
        _REASONS.get(code, "This check needs review. See the support details below.") for code in entry["reasonCodes"]
    )
    if entry["reasonCodes"] == ["required_evidence_unverified"]:
        if shared_connection:
            reason = "Some required connections could not be confirmed. Review the shared connection issue."
        elif kind == "administrator":
            reason = "This was not checked automatically. Your administrator's review is still needed."
        elif any(row.status in {"Blocked", "Error"} for row in rows):
            reason = "FlightCheck could not finish this check. Ask the owner to investigate before running it again."
    criteria = list(dict.fromkeys(
        row.evidence.get("acceptanceCriteria") or row.remediation
        for row in rows if row.evidence.get("acceptanceCriteria") or row.remediation
    ))
    if not rows:
        criteria = [entry["applicabilityReason"]]
    content = (
        f'<details class="requirement" id="chk-{_slug(key)}" data-kind="{kind}"{" open" if single else ""}>'
        f'<summary><span><strong>{_e("What needs to be checked" if single else title)}</strong></span>'
        f'{_badge("unknown") if entry["coverageState"] == "unknown" else observed or _badge(entry["evidenceState"])}</summary>'
        '<div class="requirement-body">'
        f'<h4>What we found</h4><p>{_e(reason or ("A required check found a problem." if entry["evidenceState"] == "defect" else "This check still needs review."))}</p>'
        f'<p><b>Who can help:</b> {_e(", ".join(_role_name(role) for role in entry["roles"]))}</p>'
        '<h4>What to do</h4><ol class="steps-list">'
        + "".join(f"<li>{_prose(step)}</li>" for step in _REVIEW_STEPS.get(key, (next_step,)))
        + "</ol>"
    )
    fields = entry["requiredEvidenceFields"]
    if fields:
        domain_fields = [field for field in fields if field not in _BASE_FIELDS]
        content += (
            "<h4>What to record</h4><ul class=\"field-list\">"
            + "".join(f"<li>{_e(_FIELD_LABELS.get(field, _field_name(field)))}</li>" for field in domain_fields)
            + "</ul><p class=\"muted\">Include who reviewed it, a link or reference to the results, "
            "when it was checked and when the review expires. The review must match this agent, environment and version.</p>"
        )
    content += (
        '<details class="support-details"><summary>Technical details for your administrator</summary>'
        f'<p>Check reference: <code>{_e(key)}</code></p>'
        + "".join(f"<p>{_prose(action)}</p>" for action in criteria if not shared_connection)
        + "".join(f"<p>{_prose(row.result)}</p>" for row in rows if not shared_connection)
    )
    if shared_connection:
        content += '<p>See <a href="#dependency-detail">the shared connection issue</a> and the check results below.</p>'
    if fields:
        content += (
            '<p>Required field names: ' + ", ".join(f"<code>{_e(field)}</code>" for field in fields) + "</p>"
            '<details class="template"><summary>Review form for your administrator (JSON)</summary>'
            '<p>This form has not been reviewed. Complete it with the appropriate owner before submitting it. '
            'Copying it does not confirm that the check passed.</p>'
            + (
                '<p>For each feature, use <code>true</code> if used or <code>false</code> if not used. '
                'Leave <code>null</code> for an unknown choice; its checks will remain outstanding.</p>'
                if key == "DA-INTEGRATIONS-001" else ""
            )
            + f'<textarea readonly aria-label="Review form for {_e(title)}" spellcheck="false">'
            f'{_e(_template(assessment, entry))}</textarea>'
            '<button type="button" class="copy-template">Copy review form</button>'
            '<span class="copy-status" role="status"></span></details>'
        )
    return content + "</details></div></details>"


def _work_queue(r: RunResult) -> tuple[str, str, int]:
    assessment = r.da_assessment
    shared_warning = _connection_warning(r) is not None
    groups: dict[str, list] = {}
    rows_by_id: dict[str, list] = {}
    for row in r.results:
        rows_by_id.setdefault(row.checkpoint_id, []).append(row)
    for entry in assessment["coverage"]:
        if not entry["deploymentRequired"] or entry["evidenceState"] == "satisfied":
            continue
        rows = [row for observed in entry["observed"] for row in rows_by_id.get(observed["checkpointId"], [])
                if row.status == observed["status"]]
        # A checkpoint can emit several status buckets; retain each actual row once.
        rows = list({id(row): row for row in rows}.values())
        title = (
            "Confirm which features you use" if entry["coverageState"] == "unknown" else
            _GROUP_BY_ID.get(entry["checkpointId"], entry["checkpointId"])
        )
        groups.setdefault(title, []).append((entry, rows))
    cards: dict[str, list[str]] = {}
    summary_rows = []
    def urgency(item):
        entries = item[1]
        if any(entry["evidenceState"] == "defect" for entry, _ in entries):
            return 0
        ranks = {"verification": 1, "applicability": 2, "administrator": 3, "evidence": 4}
        return min(ranks[_kind(entry, rows)] for entry, rows in entries)

    for title, entries in sorted(groups.items(), key=urgency):
        kinds = sorted({_kind(entry, rows) for entry, rows in entries})
        owners = sorted({_role_name(role) for entry, _ in entries for role in entry["roles"]})
        defect = any(entry["evidenceState"] == "defect" for entry, _ in entries)
        label = title if title in _GROUPS or title == "Confirm which features you use" else _check_copy(title)[0]
        group_id = "group-" + _slug(title)
        action = _GROUP_STEPS[title] if title in _GROUP_STEPS else _check_copy(title)[1]
        owner_summary = ", ".join(owners) if len(owners) <= 2 else "Several owners; see the individual checks"
        summary_rows.append(
            f'<tr class="summary-row" data-group="{group_id}">'
            f'<th scope="row" data-label="Area"><a href="#{group_id}">{_e(label)}</a>'
            f'<span class="advisory">{len(entries)} {"check" if len(entries) == 1 else "checks"} to review</span></th>'
            f'<td data-label="Next step">{_prose(action)}</td>'
            f'<td data-label="Who can help">{_e(owner_summary)}</td></tr>'
        )
        cards.setdefault(_stage(entries[0][0]), []).append(
            f'<details class="work-card sec" id="{group_id}" data-kinds="{_e(" ".join(kinds))}">'
            f'<summary><span class="group-title">{_e(label)}</span>'
            f'<span class="group-count">{len(entries)} {"check" if len(entries) == 1 else "checks"}</span>'
            f'{_badge("defect" if defect else "Needs attention")}</summary><div class="sec-body">'
            + "".join(_requirement(assessment, entry, rows, single=len(entries) == 1,
                                  connection_warning=shared_warning) for entry, rows in entries)
            + "</div></details>"
        )
    table = (
        '<div class="table-scroll"><table class="action-table"><caption>Next steps by area</caption>'
        '<colgroup><col class="area-column"><col class="step-column"><col class="owner-column"></colgroup>'
        '<thead><tr><th scope="col">Area</th><th scope="col">Next step</th><th scope="col">Who can help</th></tr></thead>'
        "<tbody>" + "".join(summary_rows) + "</tbody></table></div>"
    ) if summary_rows else ""
    sections = []
    for name, entries in _stages(assessment).items():
        color, label = _stage_summary(entries)
        complete = "".join(
            f'<li><span>{_e(_check_copy(entry["checkpointId"])[0])}</span>'
            f'{_badge(entry["evidenceState"])}</li>'
            for entry in entries if not entry["deploymentRequired"] or entry["evidenceState"] == "satisfied"
        )
        sections.append(
            f'<details class="category-section sec" id="cat-{_slug(name)}">'
            f'<summary><span class="category-title">{_e(name)}</span>'
            f'<span class="category-state {color}">{_e(label)}</span></summary><div class="sec-body">'
            + "".join(cards.get(name, []))
            + (f'<ul class="completed-checks">{complete}</ul>' if complete else "")
            + '</div></details>'
        )
    return "".join(sections), table, len(groups)


def _rerun(assessment: dict) -> str:
    rerun = assessment.get("rerun")
    if not rerun:
        return (
            "<p>The command used for this report was not saved. Ask the person who ran it to repeat the full "
            "readiness check for the same agent and environment. The in-editor check only reviews local files.</p>"
        )
    args = ["python", str(Path("scripts") / "flightcheck" / "cli.py"), *rerun["arguments"]]
    if rerun["shell"] == "powershell":
        command = " ".join("'" + arg.replace("'", "''") + "'" if index else arg
                           for index, arg in enumerate(args))
    else:
        command = shlex.join(args)
    root = r"solutions\ess-maker-skills" if rerun["shell"] == "powershell" else "solutions/ess-maker-skills"
    return (
        f'<p>Run from <code>{_e(root)}</code> '
        f'using {_e(rerun["shell"])} and the same approved account. '
        'The command keeps the agent and environment used for this report.</p>'
        f'<pre class="command">{_e(command)}</pre>'
        "<p>To include completed reviews, add <code>--da-evidence</code> with the review file "
        "(or replace its existing value). Use this full check, not the in-editor check of local files.</p>"
    )


def _coverage(assessment: dict) -> str:
    rows = []
    for entry in assessment["coverage"]:
        observed = ", ".join(f"{row['checkpointId']}: {_STATUS_LABELS.get(row['status'], row['status'])}"
                             for row in entry["observed"]) or "No result recorded"
        reason = " ".join(_REASONS.get(code, "See the check details for more information.") for code in entry["reasonCodes"])
        applicability = {
            "applicable": "Applies", "unknown": "Please confirm", "excluded": "Outside this review",
            "not_applicable": "Does not apply",
        }.get(entry["applicability"], entry["applicability"])
        rows.append(
            f'<tr data-required="{str(entry["deploymentRequired"]).lower()}">'
            f'<th scope="row" data-label="Check reference"><code>{_e(entry["checkpointId"])}</code></th>'
            f'<td data-label="Recorded results">{_e(observed)}</td>'
            f'<td data-label="Review status">{_badge(entry["evidenceState"])}'
            f'<span class="advisory">{_e(applicability)} · '
            f'{"Required" if entry["deploymentRequired"] else "Not required for readiness"}</span>'
            f'<details><summary>Explanation</summary><p>{_e(reason or entry["applicabilityReason"])}</p></details></td></tr>'
        )
    counts = assessment["counts"]
    return (
        '<section id="coverage" class="panel"><h2>Full check list</h2>'
        '<p>The full list includes checks that may not apply to you, older checks and checks that cannot run automatically. '
        'Several checks can share one review, and a check can return more than one result.</p>'
        '<details class="support-details"><summary>View the full list and check references</summary>'
        f'<p>{counts["catalogDefinitions"]} entries in the full list; '
        f'{counts["scheduledSelectors"]} checks or check groups selected for this run; '
        f'{counts["observedRows"]} results recorded. These are not counts of passed checks.</p>'
        '<label class="coverage-toggle"><input id="required-only" type="checkbox"> Show required checks only</label>'
        '<div class="table-scroll"><table><caption>All checks and their review status</caption><thead><tr>'
        '<th scope="col">Check reference</th><th scope="col">Recorded results</th>'
        '<th scope="col">Review status</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table></div></details></section>"
    )


def _diagnostics(r: RunResult) -> str:
    coverage = {entry["checkpointId"]: entry for entry in r.da_assessment["coverage"]}
    shared_warning = _connection_warning(r) is not None
    rows = []
    for row in r.results:
        advisory = row.checkpoint_id in coverage and not coverage[row.checkpoint_id]["deploymentRequired"]
        shared_connection = (
            shared_warning and row.status not in {"Failed", "Error", "Passed"}
            and row.checkpoint_id in {"ENV-004", "ENV-004-COVERAGE", "DA-CONN-001", "SN-CONN-001"}
        )
        rows.append(
            f'<tr><th scope="row" data-label="Check">{_e(_check_copy(row.checkpoint_id)[0])}<br>'
            f'{_badge(row.status)}<span class="advisory"><code>{_e(row.checkpoint_id)}</code></span>'
            + ("<span class=\"advisory\">For information</span>" if advisory else "")
            + '</th><td data-label="Findings"><details><summary>View findings and guidance</summary>'
            + ('<p>See the <a href="#dependency-detail">shared connection issue</a>. '
               'The original findings are in the <a href="results.json">downloadable report data</a>.</p>' if shared_connection
               else f"<p>{_prose(row.result)}</p>")
            + (f"<p>{_prose(row.remediation)}</p>" if row.remediation and not shared_connection else "")
            + (f'<p>{_prose(f"[Documentation]({row.doc_link})")}</p>' if row.doc_link else "")
            + f'</details></td><td data-label="Who can help">{_e(", ".join(_role_name(role) for role in row.roles))}</td></tr>'
        )
    return (
        '<section id="diagnostics" class="panel"><h2>Check results</h2>'
        '<p>These results show what FlightCheck could verify. Readiness also depends on the reviews listed above.</p>'
        f'<div class="status-counts syn-stats">{_status_totals(r)}</div>'
        '<p>Not checked does not mean Passed. Could not check means the check was unable to finish, '
        'not that it found a problem. Information-only notes do not require a review.</p>'
        f'<details class="support-details"><summary>View all {len(r.results)} check results and support details</summary>'
        '<div class="table-scroll">'
        '<table><caption>Results recorded during this check</caption><thead><tr><th scope="col">Check</th>'
        '<th scope="col">Findings</th><th scope="col">Who can help</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table></div></details></section>"
    )


def render_da_report(r: RunResult) -> str:
    assessment = r.da_assessment
    counts, target = assessment["counts"], assessment["target"]
    work, work_table, work_count = _work_queue(r)
    state = assessment["deploymentReadiness"]
    state_class = {"READY": "success", "NOT_READY": "danger"}.get(state, "attention")
    decision, explanation = {
        "READY": ("Ready for this environment", "The required checks and reviews for this agent and environment are complete."),
        "NOT_READY": ("Issues need fixing", "The checks found problems that need fixing before this agent is ready."),
        "INCOMPLETE": ("More checks needed", "We still need test results, reviews or information before we can confirm this agent is ready."),
    }[state]
    dependency = _connection_warning(r)
    root_cause = (
        '<aside class="root-cause" id="dependency-detail" aria-labelledby="connection-issue-title">'
        '<h3 id="connection-issue-title">Some connection checks are incomplete</h3>'
        '<p>FlightCheck could not confirm every service this agent uses. Ask your agent owner and administrator '
        'to review the affected conversations and connections.</p>'
        '<a href="results.json">Download details for support</a></aside>'
    ) if dependency else ""
    reviews = "".join(
        f'<li>{_e(_check_copy(review["checkpointId"])[0])}: '
        + ("review accepted" if review["accepted"] else
           "review not accepted — " + _e("; ".join(_REASONS.get(code, "See the support details for this check.")
                                                  for code in review["reasonCodes"])))
        + (f'; source: {_e(_mask_sensitive(review["source"]))}; valid until {_e(review["validUntil"])}'
           if review["accepted"] else "")
        + "</li>" for review in assessment["evidenceReviews"]
    )
    issues = "".join(f"<li>{_e(_ISSUES.get(issue, 'Some information needed for this report could not be confirmed.'))}</li>"
                     for issue in assessment["issues"])
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="light dark"><title>Employee Self-Service readiness report</title>'
        f"<style>{_CSS}</style></head><body>"
        '<a class="skip-link" href="#overview">Skip to summary</a><div class="app wrap"><main>'
        '<header id="overview" class="panel report"><div class="brand">'
        f'<img class="app-icon" src="{_APP_ICON_DATA_URI}" alt="Employee Self-Service icon">'
        '<div class="brand-title">Employee Self-Service FlightCheck</div></div>'
        '<p class="eyebrow">Readiness for employee use</p>'
        '<h1>Full readiness report</h1>'
        '<dl class="target"><dt>Agent</dt>'
        f'<dd>{_e(target["agentSlug"].replace("-", " ").replace("_", " ").title() or "Your agent")}</dd>'
        '<dt>Environment type</dt>'
        f'<dd>{_e({"dev": "Development", "test": "Test", "prod": "Production"}.get(target["realm"], target["realm"]))}</dd>'
        f'<dt>Checked on</dt><dd>{_e(r.started)}</dd><dt>Time taken</dt><dd>{r.duration_secs} seconds</dd></dl>'
        f'<div class="verdict"><span class="decision {state_class}">{_e(decision)}</span><p>{_e(explanation)}</p></div>'
        f'<p class="readiness-counts">{counts["requiredDefinitions"]} required checks and reviews · '
        f'{counts["satisfied"]} confirmed · {counts["defects"]} needing fixes · '
        f'{counts["incomplete"]} still to confirm</p>'
        '<p class="overview-note">This result applies only to the agent, environment and version checked. '
        'Missing information does not mean something is broken.</p>'
        + (f'<div class="context-gaps"><h3>What we could not confirm</h3><ul>{issues}</ul></div>' if issues else "")
        + '</header>'
        '<details class="panel howto"><summary>How to read this report</summary><div class="howto-body">'
        '<p>Review any items marked Needs fixing first. Could not check and Not checked do not mean Passed. '
        'Administrator checks and required reviews must still be completed before readiness can be confirmed.</p>'
        '<p>Use the next-steps table to find the right owner, then open the related checks for instructions. '
        'Opening this report or copying a review form does not complete a check.</p>'
        '<p>This check does not change settings, publish your agent or submit employee requests.</p>'
        '<nav class="report-nav" aria-label="Report sections"><a href="#overview">Summary</a><a href="#work">Next steps</a>'
        '<a href="#readiness">Category tiles</a><a href="#check-details">Check details</a>'
        '<a href="#evidence">Submit reviews</a><a href="#diagnostics">All results</a>'
        '<a href="#coverage">Full check list</a></nav></div></details>'
        '<section id="work" class="panel actions-panel"><div class="section-heading"><h2>What to do next</h2>'
        f'<p>{work_count} groups of next steps. {counts["incomplete"]} checks and reviews still need to be confirmed. '
        f'For {counts["unknownApplicability"]} checks, first confirm whether you use the feature. '
        'Select an area to open its instructions.</p></div>'
        + root_cause
        + (work_table if work_table else '<p>There are no required checks left to confirm.</p>')
        + '<button type="button" class="ap-more" id="more-actions" aria-expanded="false" hidden></button>'
        + '<p id="no-work-match" hidden>No next steps match this filter.</p></section>'
        + _synopsis(r)
        +
        '<section id="check-details" class="panel checks-card"><div class="section-heading">'
        '<h2>Check details</h2><p>Open an area for findings and numbered next steps.</p></div>'
        '<div class="toolbar" hidden><div id="work-filter" class="filters" role="group" aria-label="Filter next steps">'
        '<button type="button" data-filter="all" aria-pressed="true">All</button>'
        '<button type="button" data-filter="verification" aria-pressed="false">Investigation</button>'
        '<button type="button" data-filter="evidence" aria-pressed="false">Reviews</button>'
        '<button type="button" data-filter="administrator" aria-pressed="false">Administrator help</button>'
        '<button type="button" data-filter="applicability" aria-pressed="false">Features to confirm</button>'
        '<span class="fl-spacer"></span><button type="button" class="fold" id="expand-work">Expand all</button>'
        '<button type="button" class="fold" id="collapse-work">Collapse all</button>'
        '</div><label class="search-label">Search<input id="work-search" type="search" placeholder="Check, feature or owner"></label>'
        '<span id="visible-work" role="status"></span></div>'
        f'<div class="work-grid">{work}</div></section>'
        '<section id="evidence" class="panel"><h2>Record and submit reviews</h2><div class="evidence-grid"><div>'
        '<h3>How to complete a review</h3><ol><li>Collect the information listed under each check.</li>'
        '<li>Ask the appropriate owner to review it and record the result, supporting reference, '
        'review date and expiry date for this agent and version.</li>'
        '<li>Ask the person running FlightCheck to include the completed reviews in the next full check.</li></ol>'
        '<p>Opening this report or copying a review form does not complete a check. '
        'FlightCheck relies on the submitted administrator reviews and employee test results; '
        'it does not independently verify who performed them.</p>'
        + (f"<h3>Submitted reviews</h3><ul>{reviews}</ul>" if reviews else "<p>No completed reviews were submitted with this report.</p>")
        + '<details class="support-details"><summary>Agent and version details for support</summary>'
        f'<pre>{_e(json.dumps(target, indent=2))}</pre>'
        f'<p>Readiness code: <code>{_e(state)}</code></p>'
        f'<p>Configuration revision: <code>{_e(assessment["configurationRevision"] or "Unavailable: agent settings could not be verified")}</code></p>'
        + (f'<p>Unrecognized check references: {_e(", ".join(assessment["unrecognizedEvidenceCheckpoints"]))}</p>'
           if assessment["unrecognizedEvidenceCheckpoints"] else "") + '</details>'
        + '</div><div><h3>Run the full check again</h3>'
        '<p>After completing the reviews or fixing issues, run FlightCheck again for the same agent and environment.</p>'
        '<details class="support-details"><summary>Command and review file instructions for your administrator</summary>'
        '<p>Combine the completed forms into one JSON file, with one record per check. Keep earlier reviews '
        'that are still valid when adding new ones. Each form starts unreviewed and needs the appropriate owner.</p>'
        + _rerun(assessment) + '</details>'
        + '</div></div></section>'
        + _diagnostics(r) + _coverage(assessment)
        + '<footer>This report works offline and does not track your activity. · '
        '<a href="results.json">Download report data for support</a></footer></main></div>'
        f"<script>{_SCRIPT}</script></body></html>"
    )


_CSS = _REPORT_CSS + """
:root{font-family:'Segoe UI Variable','Segoe UI',system-ui,sans-serif;color-scheme:light dark;
 --bg:#f5f5f5;--surface:#fff;--ink:#242424;--muted:#616161;--line:#e0e0e0;--accent:#0f6cbd;
 --success:#0e6b0e;--success-bg:#dff6dd;--danger:#a4262c;--danger-bg:#fde7e9;
 --attention:#835b00;--attention-bg:#fff4ce;--neutral-bg:#f0f0f0;--radius:4px;
 --shadow:0 2px 4px #00000024,0 0 2px #0000001f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-size:15px;line-height:1.5}
a{color:var(--accent);text-underline-offset:3px}button,input,select,textarea{font:inherit}
button,select,input[type=search]{border:1px solid var(--line);border-radius:4px;padding:8px 10px;background:var(--surface);color:var(--ink)}
button{cursor:pointer;color:var(--accent);font-weight:600}button:hover{background:var(--neutral-bg)}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
[hidden]{display:none!important}.app{max-width:1080px;margin:auto;padding:24px 20px 64px}
.brand{display:flex;flex-direction:column;align-items:flex-start;gap:12px;margin-bottom:16px}
.app-icon{display:block;width:56px;height:56px;filter:drop-shadow(0 2px 5px #0000002e)}
.brand-title{font-size:24px;line-height:32px;font-weight:600}
.report-nav{display:flex;flex-wrap:wrap;gap:4px;margin:0 0 16px}
.report-nav a{padding:6px 12px;color:var(--ink);text-decoration:none;border-radius:4px;font-size:13px}
.report-nav a:hover{background:var(--surface);color:var(--accent)}
main{min-width:0}section,header{scroll-margin-top:20px;margin-bottom:18px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px}
.report{border-top:6px solid var(--accent)}
.eyebrow{font-weight:600;color:var(--muted);margin:0 0 8px}h1{font-size:32px;line-height:40px;overflow-wrap:anywhere;margin:8px 0 12px;font-weight:600}
h2{font-size:24px;line-height:32px;margin:0 0 8px;font-weight:600}h3{font-size:16px;margin:0 0 8px;font-weight:600}h4{font-size:14px;margin:18px 0 6px}
p{margin:8px 0 12px}.muted,.section-heading p{color:var(--muted);font-size:13px}.overview p{max-width:760px}
.verdict{display:block;border-top:1px solid var(--line);margin-top:16px;padding-top:16px}
.decision{display:inline-flex;font-size:24px;line-height:32px;font-weight:600}
.decision.success,.decision.danger,.decision.attention{background:transparent}
.verdict p{margin:8px 0 12px;font-size:14px;font-weight:400;line-height:20px;color:var(--ink)}
.success{color:var(--success);background:var(--success-bg)}.danger{color:var(--danger);background:var(--danger-bg)}
.attention{color:var(--attention);background:var(--attention-bg)}.neutral{color:var(--muted);background:var(--neutral-bg)}
.target{display:grid;grid-template-columns:auto 1fr;gap:3px 12px;font-size:14px}
dt{color:var(--muted)}dd{margin:0;font-weight:600}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:16px}
.metric{padding:16px;border:1px solid var(--line);border-radius:4px}.metric strong{display:block;font-size:28px;line-height:1.3;font-weight:600}
.metric span{color:var(--muted);font-size:13px}.overview-note{color:var(--muted);font-size:13px;margin:0}
.readiness-counts{font-size:13px;color:var(--muted)}
.category-title{flex:1}.category-state{font-size:12px;font-weight:600;border-radius:999px;padding:3px 10px}
.category-state.green{color:var(--accent-ink);background:var(--tile-pass)}.category-state.red{color:var(--accent-ink);background:var(--tile-fail)}
.category-state.amber{color:#242424;background:var(--pill-warn)}.category-state.gray{color:var(--ink);background:var(--neutral-bg)}
.category-section>.sec-body{padding:0 0 8px 16px}.category-section .group-title{font-size:14px}
.completed-checks{list-style:none;padding:0;margin:0}
.completed-checks li{display:flex;align-items:start;justify-content:space-between;gap:12px;padding:12px 0;border-bottom:1px solid var(--line);font-size:14px}
.completed-checks li:last-child{border-bottom:0}.syn-role{overflow-wrap:anywhere}
.ap-more{background:var(--surface);color:var(--ink);border-color:var(--line)}
.ap-more:hover{background:var(--neutral-bg)}
.context-gaps{background:var(--attention-bg);padding:16px;border-radius:4px;margin-top:16px}
.howto{padding:0;margin-bottom:18px}.howto>summary{padding:12px 18px;font-size:14px}
.howto-body{padding:6px 18px 14px;border-top:1px solid var(--line);font-size:13px}
.toolbar{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:18px 0}.toolbar label{display:grid;gap:4px;font-size:12px;color:var(--muted)}
.filters{display:flex;flex:1 1 100%;flex-wrap:wrap;border-bottom:1px solid var(--line);gap:2px}
.filters button{background:none;border:0;border-bottom:2px solid transparent;border-radius:0;padding:10px 12px;color:var(--muted)}
.filters button[aria-pressed=true]{border-bottom-color:var(--accent);color:var(--accent);font-weight:600}
.search-label{flex:1;min-width:180px;max-width:420px}.toolbar input{width:100%}#visible-work{color:var(--muted);font-size:12px;padding-bottom:8px}
.work-grid{display:block}.work-card{border-bottom:1px solid var(--line);min-width:0}
.work-card:last-child{border-bottom:0}.work-card>summary{display:flex;align-items:center;gap:12px;padding:16px 0}
.group-title{flex:1;font-size:16px}.group-count{color:var(--muted);font-size:12px;white-space:nowrap;font-weight:400}
.sec-body{padding:0 0 12px 18px}.fold-controls{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}
.badge{display:inline-block;white-space:nowrap;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600}
.badge.success{background:#107c10;color:#fff}.badge.danger{background:#c50f1f;color:#fff}
.badge.attention{background:#f7630c;color:#242424}
summary{cursor:pointer;font-weight:600;padding:10px 0;overflow-wrap:anywhere}details[open]>summary{margin-bottom:4px}
.requirement{border-top:1px solid var(--line);margin-top:4px}.requirement>summary{display:flex;align-items:start;justify-content:space-between;gap:12px}
.requirement>summary>span:first-child{min-width:0}.requirement>summary strong{font-size:14px;font-weight:600}
.requirement>summary::before{content:'+';color:var(--accent);font-size:17px;line-height:1.2}
.requirement[open]>summary::before{content:'−'}.requirement>summary>span:first-of-type{flex:1}
.requirement-body{font-size:13px;padding:0 0 8px 20px}.field-list{padding-left:18px}.field-list code{font-size:11px;color:var(--muted)}
.steps-list{list-style:none;counter-reset:step;padding:0;margin:10px 0}
.steps-list li{counter-increment:step;position:relative;padding:8px 0 8px 36px}
.steps-list li::before{content:counter(step);position:absolute;left:0;top:7px;width:24px;height:24px;border-radius:50%;
 display:grid;place-items:center;background:var(--neutral-bg);color:var(--muted);font-size:12px;font-weight:600}
.root-cause{background:var(--attention-bg);border:1px solid var(--line);border-left:3px solid var(--attention);padding:8px 18px;border-radius:6px;margin:16px 0}
.root-cause p{font-size:13px;overflow-wrap:anywhere}.evidence-grid{display:grid;grid-template-columns:1fr 1fr;gap:32px}
pre,textarea{font-family:Consolas,ui-monospace,monospace;font-size:12px;line-height:1.6}
pre{padding:16px;background:var(--neutral-bg);border-radius:4px;white-space:pre-wrap;overflow-wrap:anywhere}
code{font-family:Consolas,ui-monospace,monospace;font-size:.9em;overflow-wrap:anywhere}
textarea{display:block;width:100%;min-height:240px;resize:vertical;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:4px;padding:12px;margin:10px 0}
.copy-status{font-size:12px;margin-left:10px}.table-scroll{overflow:auto;max-width:100%}table{width:100%;border-collapse:collapse;font-size:13px;text-align:left}
caption{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip-path:inset(50%)}
th,td{padding:14px 12px;vertical-align:top;border-bottom:1px solid var(--line);overflow-wrap:anywhere;line-height:1.55}
thead{background:var(--neutral-bg)}thead th{font-weight:600}tbody th{font-weight:600}td details{max-width:680px}
.action-table{table-layout:fixed}.area-column{width:34%}.step-column{width:43%}.owner-column{width:23%}
.action-table tbody th a{font-size:14px;font-weight:600;text-decoration:none}
.action-table tbody th a:hover{text-decoration:underline}.action-table tbody tr:hover{background:var(--bg)}
.status-counts{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.stat{padding:5px 10px;background:var(--neutral-bg);border-radius:4px;font-size:12px}
.advisory{display:block;font-size:11px;color:var(--muted);font-weight:400}.coverage-toggle{display:block;margin:12px 0}
footer{display:flex;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:12px;padding-bottom:16px}
.skip-link{position:absolute;left:12px;top:-100px;padding:10px;background:var(--surface);z-index:10}.skip-link:focus{top:12px}
@media(max-width:760px){.app{padding:16px 12px 40px}.panel{padding:16px}.howto{padding:0}
 .brand-title{font-size:21px}.report-nav a{padding:6px 8px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}
 .evidence-grid{grid-template-columns:1fr}.metric strong{font-size:26px}.sec-body{padding-left:0}
 .work-card>summary,.requirement>summary{flex-wrap:wrap}.group-title{flex-basis:100%}.group-count{flex:1}
 .category-section>summary{flex-wrap:wrap}.category-title{flex-basis:100%}.category-section>.sec-body{padding-left:0}
 .requirement>summary>.badge{margin-left:28px}h1{font-size:24px}.requirement-body{padding-left:10px}
 table,tbody,tr,th,td{display:block;width:100%}thead,colgroup{display:none}tbody tr{padding:12px 0;border-bottom:1px solid var(--line)}
 tbody th,tbody td{border:0;padding:5px 0}td[data-label]::before{content:attr(data-label);display:block;font-size:12px;font-weight:600;color:var(--muted);margin-bottom:3px}}
@media(prefers-color-scheme:dark){:root{--bg:#141414;--surface:#292929;--ink:#fff;--muted:#adadad;--line:#525252;--accent:#479ef5;
 --success:#9fd89f;--success-bg:#052505;--danger:#f1bbbc;--danger-bg:#442726;--attention:#fce100;--attention-bg:#443b18;--neutral-bg:#292929}}
@media print{.app{max-width:none;padding:0}.report-nav,.toolbar,.fold-controls,.copy-template{display:none}
 .panel{box-shadow:none}.work-card{break-inside:avoid;margin-bottom:12px}}
"""


_SCRIPT = """
document.querySelector('.toolbar').hidden = false;
const cards = Array.from(document.querySelectorAll('.work-card'));
const categories = Array.from(document.querySelectorAll('.category-section'));
const filterButtons = Array.from(document.querySelectorAll('[data-filter]'));
let selectedKind = 'all';
let showAllActions = false;
function filterWork() {
  const search = document.getElementById('work-search').value.trim().toLowerCase();
  let shown = 0;
  cards.forEach(card => {
    card.hidden = !((selectedKind === 'all' || card.dataset.kinds.split(' ').includes(selectedKind)) &&
      card.textContent.toLowerCase().includes(search));
    document.querySelector('[data-group="' + card.id + '"]').hidden = card.hidden;
    if (!card.hidden) shown++;
  });
  let actionRows = 0;
  document.querySelectorAll('.summary-row').forEach(row => {
    if (!row.hidden) row.hidden = !showAllActions && actionRows++ >= 3;
  });
  categories.forEach(category => {
    const completed = category.querySelector('.completed-checks');
    if (completed) completed.hidden = selectedKind !== 'all' ||
      !completed.textContent.toLowerCase().includes(search);
    category.hidden = !Array.from(category.querySelectorAll('.work-card')).some(card => !card.hidden) &&
      !(completed && !completed.hidden);
    if (!category.hidden && (selectedKind !== 'all' || search)) category.open = true;
  });
  const more = document.getElementById('more-actions');
  more.hidden = shown <= 3;
  more.textContent = showAllActions ? 'Show fewer areas' : 'Show ' + (shown - 3) + ' more areas';
  more.setAttribute('aria-expanded', String(showAllActions));
  filterButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.filter === selectedKind)));
  const table = document.querySelector('.action-table');
  if (table) table.hidden = shown === 0;
  document.getElementById('visible-work').textContent = shown + ' of ' + cards.length + ' groups';
  document.getElementById('no-work-match').hidden = shown !== 0 || cards.length === 0;
}
filterButtons.forEach(button => button.addEventListener('click', () => {
  selectedKind = button.dataset.filter;
  filterWork();
}));
document.getElementById('work-search').addEventListener('input', filterWork);
document.getElementById('more-actions').addEventListener('click', () => {
  showAllActions = !showAllActions;
  filterWork();
});
document.getElementById('expand-work').addEventListener('click', () => {
  categories.filter(category => !category.hidden).forEach(category => category.open = true);
  cards.filter(card => !card.hidden).forEach(card => card.open = true);
});
document.getElementById('collapse-work').addEventListener('click', () => {
  cards.forEach(card => card.open = false);
  categories.forEach(category => category.open = false);
});
document.getElementById('required-only').addEventListener('change', event => {
  document.querySelectorAll('#coverage tr[data-required]').forEach(row => {
    row.hidden = event.target.checked && row.dataset.required !== 'true';
  });
});
document.addEventListener('click', async event => {
  const button = event.target.closest('.copy-template');
  if (!button) return;
  const template = button.closest('.template');
  const text = template.querySelector('textarea');
  const status = template.querySelector('.copy-status');
  try {
    await navigator.clipboard.writeText(text.value);
    status.textContent = 'Review form copied. It still needs to be completed and reviewed.';
  } catch (error) {
    text.focus(); text.select();
    status.textContent = 'Could not copy automatically. Copy the selected review form yourself.';
  }
});
function openTarget(hash) {
  const target = hash && document.getElementById(hash.slice(1));
  if (!target) return;
  let element = target;
  while (element) {
    if (element.tagName === 'DETAILS') element.open = true;
    element = element.parentElement;
  }
  const card = target.closest('.work-card');
  if ((card && card.hidden) || (target.matches('.category-section') && target.hidden)) {
    selectedKind = 'all';
    document.getElementById('work-search').value = '';
    filterWork();
  }
  if (target.matches('.category-section')) {
    target.querySelectorAll('.work-card:not([hidden])').forEach(group => group.open = true);
  }
  target.scrollIntoView({block: 'start'});
}
document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="#"]');
  if (link) openTarget(link.getAttribute('href'));
});
openTarget(location.hash);
window.addEventListener('hashchange', () => openTarget(location.hash));
filterWork();
"""
