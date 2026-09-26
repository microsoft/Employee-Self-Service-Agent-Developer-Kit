# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contracts for the runnable Workday DA setup orchestration."""

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKDAY_DA = (
    _REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "setup"
    / "workday-da"
)
_CONNECT = _WORKDAY_DA.parents[1] / "connect"


def test_orchestrator_resumes_durable_state_without_restarting_setup() -> None:
    text = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "pick the first whose state is not" in normalized
    assert "must not** batch those writes" in text
    assert 'provider `status` to be `"ready"`' in text
    assert ".local/connect/workday-da/tasks.md" in text
    assert ".local/setup/workday-da/tasks.md" in text
    assert "move that exact file to the canonical path" in normalized
    assert "you do not need to run `/setup` again" in normalized
    assert "customer-status" in text
    assert "Workday connection progress:" in text
    assert "| Preflight | {marker} |" in text
    assert "| Employee validation | {marker} |" in text
    assert "not the 21 internal rows" in normalized
    assert "Do not repeat that sentence" in text
    assert "Your ESS HR agent is connected to Workday" in text
    assert "supports only the Workday connection option named **Microsoft" in text
    assert "direct Workday federation through Okta, Ping" in text
    assert "do not expose Git revisions or local file-system paths" in normalized
    assert "same five-phase lifecycle and the same completion gates" in text
    assert "Environment type never skips, reorders, or relaxes" in normalized


def test_router_keeps_internal_diagnostics_out_of_customer_message() -> None:
    route = (_CONNECT / "step1.md").read_text(encoding="utf-8")

    assert "Workday setup path selected:" in route
    assert "Workspace revision:" not in route
    assert "Setup state:" not in route
    assert "This release does not configure direct Workday federation" not in route


def test_extension_install_uses_the_ring_aware_runtime_installer() -> None:
    text = (_WORKDAY_DA / "install-extension.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "install_workday_da_extension.py" in text
    assert '--package-flavor "{PACKAGE_FLAVOR}"' in text
    assert '--ring "{RING}"' in text
    assert "managed-pac.nuget.config" in text
    assert "Do not present .NET and PAC as unexplained product setup steps" in normalized
    assert "do not restart the Workday checklist" in normalized


def test_extension_install_guides_missing_dataverse_provisioning() -> None:
    text = (_WORKDAY_DA / "install-extension.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "doesn't have a Dataverse database yet" in text
    assert "https://admin.powerplatform.microsoft.com/" in text
    assert "**Add Dataverse** or **Add database**" in text
    assert "solution, connection references, and cloud flows" in normalized
    assert "refresh the environment inventory" in normalized
    assert "rather than trusting acknowledgement alone" in normalized
    assert "do not run the package checkpoint or installer" in normalized
    assert "Power Platform administrator" in normalized


def test_entra_checks_reuse_the_verified_admin_account() -> None:
    text = (_WORKDAY_DA / "provision-entra-app.md").read_text(encoding="utf-8")
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")

    assert "az account show --query user.name -o tsv" in text
    assert "ENTRA_ADMIN_ACCOUNT" in text
    assert "entraAdminAccount = ENTRA_ADMIN_ACCOUNT" in text
    assert text.count('--preferred-username "{ENTRA_ADMIN_ACCOUNT}"') == 7
    assert "manual-only FlightCheck checkpoints" in tenant


def test_entra_changes_use_one_scoped_customer_approval() -> None:
    text = (_WORKDAY_DA / "provision-entra-app.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "## DA2.0c — Approve the Microsoft Entra change plan" in text
    assert "one scoped plan covering all remaining Microsoft Entra work" in normalized
    assert "Do not ask for separate approval" in text
    assert "If the resolved tenant or application changes" in normalized


def test_workday_security_changes_are_explicitly_manual_admin_actions() -> None:
    text = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Before I change any Workday security settings" not in text
    assert "The skill will not sign in to Workday" in text
    assert "normal organization-approved Workday account" in normalized
    assert "must never request or collect a Workday administrator's password" in normalized
    assert "do not ask a second question that repeats the classification" in normalized
    assert "Complete this Workday administrator checklist" in text


def test_saml_safety_gate_pauses_replacement_outside_the_standard_flow() -> None:
    text = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "pause the standard setup" in normalized
    assert "will not perform or guide that replacement" in normalized
    assert "normal change process" in normalized
    assert "Stop without presenting the remaining Workday changes" in text
    assert "I approve replacement" not in text


def test_saml_precheck_requests_only_the_minimum_provider_information() -> None:
    text = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")
    precheck = text[
        text.index("## DA3.0b — Protect the active federation"):
        text.index("## DA3.1–DA3.4 — Workday administrator work packet")
    ]

    assert "No Identity Provider is enabled" in precheck
    assert "Provide" in precheck and "**Service Provider ID**" in precheck
    assert "A different provider is enabled, or the administrator is not sure" in precheck
    assert "x509 Certificate" not in precheck
    assert "Valid From" not in precheck
    assert "Valid To" not in precheck
    assert "do not ask a second question" in " ".join(precheck.lower().split())


def test_workday_admin_actions_are_returned_in_one_structured_handoff() -> None:
    text = (_WORKDAY_DA / "configure-tenant.md").read_text(encoding="utf-8")

    assert "Complete this Workday administrator checklist" in text
    assert text.count("Use one structured `vscode_askQuestions` form") == 1
    assert '"header": "Signing certificate"' in text
    assert '"header": "Tenant security"' in text
    assert '"header": "API client ID"' in text
    assert '"header": "Token endpoint"' in text
    assert '"header": "Employee SAML policy"' in text
    assert "Do not run manual-only FlightCheck checkpoints" in text


def test_connections_are_created_before_binding_and_flow_activation() -> None:
    text = (_WORKDAY_DA / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )

    prepare = text.index("## DA4.0 — Prepare the connections page")
    bind = text.index("## DA4.3 — Bind the extension connections")

    assert prepare < bind
    assert "make.preprod.powerautomate.com" in text
    assert "make.powerautomate.com" in text
    assert "Workday and Dataverse connections show **Connected**" in text
    assert "msdyn_sharedworkdaysoap_workdayruntime" in text
    assert "msdyn_sharedcommondataserviceforapps_workdayruntime" in text
    assert "bind_workday_da_connections.py" in text
    assert "WORKDAY_DA_BINDING_PLAN_JSON" in text
    assert "WORKDAY_DA_BINDING_APPLIED_JSON" in text
    assert "activate_workday_da_flows.py" in text
    assert "WORKDAY_DA_FLOW_ACTIVATION_PLAN_JSON" in text
    assert "WORKDAY_DA_FLOWS_ACTIVATED_JSON" in text
    assert '"verified": true' in text
    assert "2. Enter the connection fields in the order shown below." in text
    assert "Workday tenant: `{tenant}`" in text
    assert "| Microsoft Entra resource URL | `http://www.workday.com/{tenant}` |" in text
    assert "Newly installed managed-solution flows" in text
    assert "Do not open the agent's Connection settings yet" in text
    assert "## DA4.2a — Approve the remaining runtime changes" in text
    assert "approves all remaining helper operations" in text
    assert text.count("another approval") + text.count("a second approval") >= 3


def test_network_review_is_conditional_and_non_blocking() -> None:
    text = (_WORKDAY_DA / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )
    definition = (
        _WORKDAY_DA / "workday-da.definition.json"
    ).read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "## DA4.8 — Review network restrictions" in text
    assert "Most environments need no separate action" in text
    assert "This is a non-blocking advisory" in text
    assert "do not block setup solely" in normalized
    assert '"id": "DA4.8"' in definition
    assert '"gate": "advisory"' in definition


def test_topic_and_authorization_guidance_matches_the_supported_runtime() -> None:
    text = (_WORKDAY_DA / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(text.split())

    assert "Enable all Workday topics" in text
    assert "Choose specific Workday topics" in text
    assert "legacy ISU/RaaS" not in text
    assert "Prefer: return=representation" in text
    assert "fails closed on these" in text
    assert "Do not rely on the script's exit code" not in text
    assert "Both invocations below occur after every Workday flow is connected" in normalized
    assert "The two invocations are preview and apply" in normalized
    assert "AppSource installer installs the managed package but does not activate" in normalized
    assert "Never continue to agent Connection settings" in normalized
    assert "Do not edit, rename, delete, or" in text
    assert "other package-managed system topics" in text
    assert "Workday [System] - 1: Set User Context V2" in text
    assert "Workday System Get CommonExecution" in text
    assert "package/version drift" in text
    assert "configure_workday_da_user_context.py" in text
    assert "WORKDAY_DA_USER_CONTEXT_PLAN_JSON" in text
    assert "WORKDAY_DA_USER_CONTEXT_APPLIED_JSON" in text
    assert "[Admin] - User Context - Setup" in text
    assert "select the existing topic reference" in text
    assert "WD-DA-CTX-001" in text
    assert "WD-DA-CONN-001" in text
    assert "who is not the maker" in text
    assert "Do not use a write or approval scenario" in normalized


def test_readiness_requires_a_signed_in_runtime_scenario() -> None:
    text = (_WORKDAY_DA / "verify-connection.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Run one enabled, read-only Workday scenario" in normalized
    assert "returns real Workday data" in normalized
    assert 'status: "ready"' in text
    assert "does not prove the live" in text
    assert "who is not the maker" in text
    assert "agentSharedWithTestUser" in text
    assert '"connectionPromptObserved": false' in text
