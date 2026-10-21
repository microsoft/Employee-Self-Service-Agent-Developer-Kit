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

from .da_readiness import DA_EVIDENCE_SCHEMA
from .runner import RunResult, _mask_sensitive, _slug


_BASE_FIELDS = {"observedAt", "source", "reviewerRole", "configurationRevision"}
_GROUPS = {
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
    "DA-INTEGRATIONS-001": ("Services used by your agent", "Confirm which connected services this agent uses."),
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
    details = {field: "" for field in sorted(fields)}
    for field in {"employeeTestRunIds", "employeeTestRuns"} & fields:
        details[field] = []
    if "outcomes" in fields:
        details["outcomes"] = {}
    kind = (
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


def _requirement(assessment: dict, entry: dict, rows: list, *, single: bool = False) -> str:
    key = entry["checkpointId"]
    title, next_step = _check_copy(key)
    kind = _kind(entry, rows)
    observed = " ".join(_badge(status) for status in dict.fromkeys(row.status for row in rows))
    reason = " ".join(
        _REASONS.get(code, "This check needs review. See the support details below.") for code in entry["reasonCodes"]
    )
    criteria = list(dict.fromkeys(
        row.evidence.get("acceptanceCriteria") or row.remediation
        for row in rows if row.evidence.get("acceptanceCriteria") or row.remediation
    ))
    if not rows:
        criteria = [entry["applicabilityReason"]]
    content = (
        f'<details class="requirement" id="chk-{_slug(key)}" data-kind="{kind}">'
        f'<summary><span><strong>{_e("What needs to be checked" if single else title)}</strong></span>'
        f'{_badge("unknown") if entry["coverageState"] == "unknown" else observed or _badge(entry["evidenceState"])}</summary>'
        '<div class="requirement-body">'
        f'<p class="muted">{_e(reason)}</p>'
        f'<p><b>Who can help:</b> {_e(", ".join(_role_name(role) for role in entry["roles"]))}</p>'
        f'<p>{_prose(next_step)}</p>'
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
        + "".join(f"<p>{_prose(action)}</p>" for action in criteria)
        + "".join(f"<p>{_prose(row.result)}</p>" for row in rows
                  if key not in {"ENV-004", "DA-CONN-001", "SN-CONN-001"})
    )
    if key in {"ENV-004", "DA-CONN-001", "SN-CONN-001"}:
        content += '<p>See <a href="#dependency-detail">the shared connection issue</a> and the check results below.</p>'
    if fields:
        content += (
            '<p>Required field names: ' + ", ".join(f"<code>{_e(field)}</code>" for field in fields) + "</p>"
            '<details class="template"><summary>Review form for your administrator (JSON)</summary>'
            '<p>This form has not been reviewed. Complete it with the appropriate owner before submitting it. '
            'Copying it does not confirm that the check passed.</p>'
            f'<textarea readonly aria-label="Review form for {_e(title)}" spellcheck="false">'
            f'{_e(_template(assessment, entry))}</textarea>'
            '<button type="button" class="copy-template">Copy review form</button>'
            '<span class="copy-status" role="status"></span></details>'
        )
    return content + "</details></div></details>"


def _work_queue(r: RunResult) -> tuple[str, int]:
    assessment = r.da_assessment
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
    cards = []
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
        cards.append(
            f'<article class="work-card" data-kinds="{_e(" ".join(kinds))}">'
            f'<div class="card-heading"><h3>{_e(label)}</h3>{_badge("defect" if defect else "Needs attention")}</div>'
            f'<p class="muted">{len(entries)} {"check" if len(entries) == 1 else "checks"} · {_e(", ".join(owners))}</p>'
            + ("<p>Work with the owners on this group. Each check still needs its own result.</p>" if len(entries) > 1 else "")
            + (f'<details class="bundle"><summary>View {len(entries)} checks</summary>' if len(entries) > 3 else "")
            + "".join(_requirement(assessment, entry, rows, single=len(entries) == 1) for entry, rows in entries)
            + ("</details>" if len(entries) > 3 else "")
            + "</article>"
        )
    return "".join(cards), len(groups)


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
            f'<tr data-required="{str(entry["deploymentRequired"]).lower()}"><th scope="row"><code>{_e(entry["checkpointId"])}</code></th>'
            f'<td>{_e(applicability)}</td><td>{"Required" if entry["deploymentRequired"] else "Not required for readiness"}</td>'
            f'<td>{_e(observed)}</td><td>{_badge(entry["evidenceState"])}</td>'
            f'<td>{_e(reason or entry["applicabilityReason"])}</td></tr>'
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
        '<div class="table-scroll"><table><thead><tr><th>Check reference</th><th>Does it apply?</th><th>Required?</th>'
        '<th>Results</th><th>Review status</th><th>Explanation</th></tr></thead><tbody>'
        + "".join(rows) + "</tbody></table></div></details></section>"
    )


def _diagnostics(r: RunResult) -> str:
    coverage = {entry["checkpointId"]: entry for entry in r.da_assessment["coverage"]}
    counts = Counter(row.status for row in r.results)
    rows = []
    for row in r.results:
        advisory = row.checkpoint_id in coverage and not coverage[row.checkpoint_id]["deploymentRequired"]
        rows.append(
            f"<tr><th scope=\"row\">{_e(_check_copy(row.checkpoint_id)[0])}<br><code>{_e(row.checkpoint_id)}</code>"
            + ("<span class=\"advisory\">For information</span>" if advisory else "")
            + f"</th><td>{_badge(row.status)}</td><td><details><summary>View technical findings and guidance</summary>"
            + f"<p>{_e(row.description)}</p>"
            + ('<p><a href="#dependency-detail">Shared connection issue</a></p>' if row.checkpoint_id in {"ENV-004", "ENV-004-COVERAGE"}
               else f"<p>{_prose(row.result)}</p>")
            + (f"<p>{_prose(row.remediation)}</p>" if row.remediation else "")
            + (f'<p>{_prose(f"[Documentation]({row.doc_link})")}</p>' if row.doc_link else "")
            + f"</details></td><td>{_e(', '.join(_role_name(role) for role in row.roles))}</td></tr>"
        )
    stats = " ".join(
        f'<span class="stat">{counts[status]} {_e(_STATUS_LABELS.get(status, status))}</span>'
        for status in ("Passed", "Failed", "Blocked", "Error", "Warning", "Manual", "Skipped", "NotConfigured")
    )
    return (
        '<section id="diagnostics" class="panel"><h2>Check results</h2>'
        '<p>These results show what FlightCheck could verify. Readiness also depends on the reviews listed above.</p>'
        f'<div class="status-counts">{stats}</div>'
        '<p>Not checked does not mean Passed. Could not check means the check was unable to finish, '
        'not that it found a problem. Information-only notes do not require a review.</p>'
        f'<details class="support-details"><summary>View all {len(r.results)} check results and support details</summary>'
        '<div class="table-scroll">'
        '<table><thead><tr><th>Check</th><th>Status</th><th>Findings and next steps</th><th>Who can help</th></tr></thead>'
        "<tbody>" + "".join(rows) + "</tbody></table></div></details></section>"
    )


def render_da_report(r: RunResult) -> str:
    assessment = r.da_assessment
    counts, target = assessment["counts"], assessment["target"]
    work, work_count = _work_queue(r)
    state = assessment["deploymentReadiness"]
    state_class = {"READY": "success", "NOT_READY": "danger"}.get(state, "attention")
    decision, explanation = {
        "READY": ("Ready for this environment", "The required checks and reviews for this agent and environment are complete."),
        "NOT_READY": ("Issues need fixing", "The checks found problems that need fixing before this agent is ready."),
        "INCOMPLETE": ("More checks needed", "We still need test results, reviews or information before we can confirm this agent is ready."),
    }[state]
    metrics = "".join(
        f'<div class="metric"><strong>{counts[key]}</strong><span>{label}</span></div>'
        for key, label in (
            ("requiredDefinitions", "Required checks and reviews"), ("satisfied", "Confirmed"),
            ("defects", "Required checks needing fixes"), ("incomplete", "Still to confirm"),
        )
    )
    dependency = next((row for row in r.results if row.checkpoint_id == "ENV-004-COVERAGE"), None)
    root_cause = (
        '<details class="root-cause" id="dependency-detail"><summary>Some connections could not be fully checked</summary>'
        '<p>FlightCheck could not confirm which services are used by every conversation. '
        'Ask your agent owner to review which conversations are turned on and which services they use. '
        'Until then, some connection checks cannot finish.</p>'
        '<p>SAP is not part of this review. However, a conversation name alone does not tell us whether '
        'it is turned off or uses other services.</p>'
        f'<details class="support-details"><summary>Connection details for your administrator</summary>'
        f'<p>{_prose(dependency.result)}</p></details></details>'
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
        '<a class="skip-link" href="#overview">Skip to summary</a><div class="app">'
        '<aside class="sidebar"><div class="brand"><span class="brand-icon" aria-hidden="true">✓</span>'
        '<div>Employee Self-Service<br><strong>FlightCheck</strong></div></div>'
        '<nav aria-label="Report sections"><a href="#overview">Summary</a><a href="#work">What to do next</a>'
        '<a href="#evidence">Record and submit reviews</a><a href="#diagnostics">Check results</a>'
        '<a href="#coverage">Full check list</a></nav>'
        '<p class="sidebar-note">This check does not change settings, publish your agent or submit employee requests.</p></aside>'
        '<main><header id="overview" class="panel overview"><div><p class="eyebrow">Readiness for employee use</p>'
        f'<h1>{_e(target["agentSlug"].replace("-", " ").replace("_", " ").title() or "Your agent")}</h1>'
        f'<span class="decision {state_class}">{_e(decision)}</span><p>{_e(explanation)}</p></div>'
        '<dl class="target"><dt>Environment type</dt>'
        f'<dd>{_e({"dev": "Development", "test": "Test", "prod": "Production"}.get(target["realm"], target["realm"]))}</dd>'
        f'<dt>Checked on</dt><dd>{_e(r.started)}</dd><dt>Time taken</dt><dd>{r.duration_secs} seconds</dd></dl>'
        f'<div class="metrics">{metrics}</div>'
        '<p class="overview-note">This result applies only to the agent, environment and version checked. '
        'Missing information does not mean something is broken. Administrator checks and required reviews '
        'must still be completed before readiness can be confirmed.</p>'
        + (f'<div class="context-gaps"><h3>What we could not confirm</h3><ul>{issues}</ul></div>' if issues else "")
        + '</header>'
        '<section id="work"><div class="section-heading"><div><h2>What to do next</h2>'
        f'<p>{work_count} groups of next steps. {counts["incomplete"]} checks and reviews still need to be confirmed. '
        f'For {counts["unknownApplicability"]} checks, first confirm whether you use the feature. '
        'Related checks are grouped so you can work with the right owner.</p></div></div>'
        '<div class="toolbar" hidden><label>Show<select id="work-filter"><option value="all">All next steps</option>'
        '<option value="evidence">Reviews and test results</option><option value="administrator">Help from an administrator</option>'
        '<option value="verification">Checks needing investigation</option><option value="applicability">Features to confirm</option>'
        '</select></label><label class="search-label">Search<input id="work-search" type="search" placeholder="Check, feature or owner"></label>'
        '<span id="visible-work" role="status"></span></div>'
        + root_cause
        + (f'<div class="work-grid">{work}</div>' if work else '<div class="panel">There are no required checks left to confirm.</div>')
        + '<p id="no-work-match" hidden>No next steps match this filter.</p></section>'
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


_CSS = """
:root{font-family:'Segoe UI Variable','Segoe UI',system-ui,sans-serif;color-scheme:light dark;
 --bg:#f5f5f5;--surface:#fff;--ink:#242424;--muted:#616161;--line:#e0e0e0;--accent:#0f6cbd;
 --success:#0e6b0e;--success-bg:#dff6dd;--danger:#a4262c;--danger-bg:#fde7e9;
 --attention:#835b00;--attention-bg:#fff4ce;--neutral-bg:#f0f0f0;--radius:8px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-size:14px;line-height:1.55}
a{color:var(--accent);text-underline-offset:3px}button,input,select,textarea{font:inherit}
button,select,input[type=search]{border:1px solid var(--line);border-radius:4px;padding:8px 10px;background:var(--surface);color:var(--ink)}
button{cursor:pointer;color:var(--accent);font-weight:600}button:hover{background:var(--neutral-bg)}
:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
[hidden]{display:none!important}.app{display:grid;grid-template-columns:232px minmax(0,1fr);max-width:1920px;margin:auto}
.sidebar{position:sticky;top:0;height:100vh;padding:28px 18px;border-right:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:12px;font-size:13px;margin:0 8px 28px}
.brand strong{font-size:20px}.brand-icon{display:grid;place-items:center;width:38px;height:38px;border-radius:8px;background:var(--accent);color:white;font-size:23px}
nav{display:grid;gap:5px}nav a{padding:10px 14px;color:var(--ink);text-decoration:none;border-radius:4px}
nav a:hover{background:var(--surface);color:var(--accent)}.sidebar-note{margin:32px 12px;font-size:12px;color:var(--muted)}
main{padding:28px 36px;min-width:0}section,header{scroll-margin-top:20px;margin-bottom:28px}
.panel,.work-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 2px 4px #00000005}
.panel{padding:24px}.overview{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:20px 32px;border-top:3px solid var(--accent)}
.eyebrow{font-weight:600;color:var(--muted);margin:0 0 8px}h1{font-size:28px;line-height:1.25;overflow-wrap:anywhere;margin:0 0 16px;font-weight:600}
h2{font-size:21px;line-height:1.35;margin:0 0 8px;font-weight:600}h3{font-size:16px;margin:0 0 8px;font-weight:600}h4{font-size:14px;margin:18px 0 6px}
p{margin:8px 0 12px}.muted,.section-heading p{color:var(--muted);font-size:13px}.overview p{max-width:760px}
.decision{display:inline-flex;border-radius:4px;padding:5px 14px;font-size:17px;font-weight:600}
.success{color:var(--success);background:var(--success-bg)}.danger{color:var(--danger);background:var(--danger-bg)}
.attention{color:var(--attention);background:var(--attention-bg)}.neutral{color:var(--muted);background:var(--neutral-bg)}
.target{display:grid;grid-template-columns:auto auto;gap:6px 18px;align-content:start;font-size:13px}
dt{color:var(--muted)}dd{margin:0;font-weight:600}.metrics{grid-column:1/-1;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.metric{padding:16px;border:1px solid var(--line);border-radius:6px}.metric strong{display:block;font-size:30px;line-height:1.3;font-weight:600}
.metric span{color:var(--muted);font-size:13px}.overview-note{grid-column:1/-1;color:var(--muted);font-size:13px;margin:0}
.context-gaps{grid-column:1/-1;background:var(--attention-bg);padding:16px;border-radius:4px}
.toolbar{display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin:18px 0}.toolbar label{display:grid;gap:4px;font-size:12px;color:var(--muted)}
.search-label{flex:1;min-width:180px}.toolbar input{width:100%}#visible-work{color:var(--muted);font-size:12px;padding-bottom:8px}
.work-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;align-items:start}
.work-card{padding:20px;min-width:0}.card-heading{display:flex;align-items:start;justify-content:space-between;gap:12px}
.badge{display:inline-block;white-space:nowrap;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600}
summary{cursor:pointer;font-weight:600;padding:10px 0;overflow-wrap:anywhere}details[open]>summary{margin-bottom:4px}
.requirement{border-top:1px solid var(--line);margin-top:12px}.requirement summary{display:flex;align-items:start;justify-content:space-between;gap:12px}
.requirement summary>span:first-child{min-width:0}.requirement summary strong{font-size:13px;font-weight:600}
.requirement summary code{display:block;color:var(--muted);font-size:11px;font-weight:400;margin-top:3px}
.requirement summary::before{content:'+';color:var(--accent);font-size:17px;line-height:1.2}
.requirement[open]>summary::before{content:'−'}.requirement summary>span:first-of-type{flex:1}
.requirement-body{font-size:13px;padding:0 0 8px 20px}.field-list{padding-left:18px}.field-list code{font-size:11px;color:var(--muted)}
.root-cause{background:var(--attention-bg);border:1px solid var(--line);border-left:3px solid var(--attention);padding:8px 18px;border-radius:6px;margin:16px 0}
.root-cause p{font-size:13px;overflow-wrap:anywhere}.evidence-grid{display:grid;grid-template-columns:1fr 1fr;gap:32px}
pre,textarea{font-family:Consolas,ui-monospace,monospace;font-size:12px;line-height:1.6}
pre{padding:16px;background:var(--neutral-bg);border-radius:4px;white-space:pre-wrap;overflow-wrap:anywhere}
code{font-family:Consolas,ui-monospace,monospace;font-size:.9em;overflow-wrap:anywhere}
textarea{display:block;width:100%;min-height:240px;resize:vertical;background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:4px;padding:12px;margin:10px 0}
.copy-status{font-size:12px;margin-left:10px}.table-scroll{overflow:auto;max-width:100%}table{width:100%;border-collapse:collapse;font-size:12px;text-align:left}
th,td{padding:12px;vertical-align:top;border-bottom:1px solid var(--line);overflow-wrap:anywhere}
thead{background:var(--neutral-bg)}tbody th{font-weight:600;min-width:180px}td details{min-width:180px;max-width:680px}
.status-counts{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}.stat{padding:5px 10px;background:var(--neutral-bg);border-radius:4px;font-size:12px}
.advisory{display:block;font-size:11px;color:var(--muted);font-weight:400}.coverage-toggle{display:block;margin:12px 0}
footer{display:flex;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:12px;padding-bottom:16px}
.skip-link{position:absolute;left:12px;top:-100px;padding:10px;background:var(--surface);z-index:10}.skip-link:focus{top:12px}
@media(min-width:1700px){.work-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media(max-width:1100px){.app{grid-template-columns:190px minmax(0,1fr)}main{padding:24px}.work-grid{grid-template-columns:1fr}}
@media(max-width:760px){.app{display:block}.sidebar{position:static;height:auto;border-right:0;border-bottom:1px solid var(--line);padding:16px}
 .brand{margin:0 0 12px}nav{display:flex;flex-wrap:wrap;gap:0}nav a{padding:6px 10px;font-size:12px}.sidebar-note{display:none}
 main{padding:16px}.panel,.work-card{padding:18px}.overview{grid-template-columns:1fr}.target{justify-content:start}
 .metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.evidence-grid{grid-template-columns:1fr}.metric strong{font-size:26px}
 .card-heading{flex-wrap:wrap}.requirement summary{flex-wrap:wrap}.requirement summary>.badge{margin-left:28px}h1{font-size:24px}}
@media(prefers-color-scheme:dark){:root{--bg:#141414;--surface:#1f1f1f;--ink:#f5f5f5;--muted:#c2c2c2;--line:#424242;--accent:#75b6e7;
 --success:#9fd89f;--success-bg:#052505;--danger:#f1bbbc;--danger-bg:#442726;--attention:#fce100;--attention-bg:#443b18;--neutral-bg:#292929}}
@media print{.app{display:block}.sidebar,.toolbar,.copy-template{display:none}main{padding:0}.work-grid{display:block}.work-card{break-inside:avoid;margin-bottom:12px}}
"""


_SCRIPT = """
document.querySelector('.toolbar').hidden = false;
const cards = Array.from(document.querySelectorAll('.work-card'));
function filterWork() {
  const kind = document.getElementById('work-filter').value;
  const search = document.getElementById('work-search').value.trim().toLowerCase();
  let shown = 0;
  cards.forEach(card => {
    card.hidden = !((kind === 'all' || card.dataset.kinds.split(' ').includes(kind)) &&
      card.textContent.toLowerCase().includes(search));
    if (!card.hidden) shown++;
  });
  document.getElementById('visible-work').textContent = shown + ' of ' + cards.length + ' work items';
  document.getElementById('no-work-match').hidden = shown !== 0;
}
document.getElementById('work-filter').addEventListener('change', filterWork);
document.getElementById('work-search').addEventListener('input', filterWork);
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
  if (card && card.hidden) {
    document.getElementById('work-filter').value = 'all';
    document.getElementById('work-search').value = '';
    filterWork();
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
