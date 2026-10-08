# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for live native Workday agent completion evidence."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


def _state():
    from workday_connect_model import default_state

    state = default_state()
    state["scope"].update(
        {
            "environmentId": "environment-id",
            "dataverseUrl": "https://example.crm.dynamics.com",
            "agent": {
                "slug": "ess-hr",
                "botId": "bot-id",
                "schemaName": "contoso",
            },
        }
    )
    state["operators"]["powerPlatformMaker"] = {"username": "maker@example.com"}
    return state


def _complete_preflight(store) -> None:
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified"},
    )
    store.set_phase_status("preflight", "complete")


def _advance_administrator_to_completion(store, phase_id: str) -> None:
    for substage in (
        "administrator-engaged",
        "handoff-presented",
        "awaiting-completion",
        "completion-confirmed",
    ):
        store.record_administrator_progress(phase_id, substage)


def _entra_partial_evidence() -> dict:
    checks = {
        name: {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        }
        for name in (
            "samlMode",
            "signingCertificate",
            "connectorPreauthorized",
            "graphDelegatedPermissions",
            "adminConsent",
            "userAssignment",
        )
    }
    checks.update(
        {
            "nameId": {
                "outcome": "verified",
                "provenance": "microsoft-graph",
                "observedValue": "user.userPrincipalName",
            },
            "samlSigningOption": {
                "outcome": "confirmed",
                "provenance": "administrator-attestation",
                "observedValue": "Sign SAML response and assertion",
            },
            "existingScopesPreserved": {
                "outcome": "verified",
                "provenance": "microsoft-graph",
                "observedValue": "preserved",
            },
            "authorizedClientsPreserved": {
                "outcome": "verified",
                "provenance": "microsoft-graph",
                "observedValue": "preserved",
            },
            "permissionsPreserved": {
                "outcome": "verified",
                "provenance": "microsoft-graph",
                "observedValue": "preserved",
            },
        }
    )
    app_id = "44444444-4444-4444-4444-444444444444"
    return {
        "selectedDirectoryId": (
            "00000000-0000-0000-0000-000000000000"
        ),
        "selectedDirectoryDisplayName": "Contoso",
        "applicationId": app_id,
        "applicationDisplayName": "Workday",
        "applicationObjectId": (
            "55555555-5555-5555-5555-555555555555"
        ),
        "servicePrincipalId": (
            "66666666-6666-6666-6666-666666666666"
        ),
        "applicationIdentifierUris": [
            "http://www.workday.com/contoso_impl",
            f"api://{app_id}",
        ],
        "applicationReplyUrls": [
            "https://www.workday.com/saml/acs",
        ],
        "scopeGuid": "77777777-7777-7777-7777-777777777777",
        "replyUrl": "https://www.workday.com/saml/acs",
        "microsoftEntraIdentifier": (
            "https://sts.windows.net/"
            "00000000-0000-0000-0000-000000000000/"
        ),
        "loginUrl": (
            "https://login.microsoftonline.com/"
            "00000000-0000-0000-0000-000000000000/saml2"
        ),
        "entraChecks": checks,
        "nameIdSource": "user.userPrincipalName",
        "samlSigningOption": "Sign SAML response and assertion",
        "certificateThumbprint": "AA11",
        "certificateValidFrom": "2026-01-01T00:00:00Z",
        "certificateValidTo": "2027-01-01T00:00:00Z",
        "scopePreservationOutcome": "preserved",
        "authorizedClientPreservationOutcome": "preserved",
        "permissionPreservationOutcome": "preserved",
    }


def _workday_partial_evidence() -> dict:
    return {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": (
            "http://www.workday.com/contoso_impl"
        ),
        "certificateSelectionOutcome": (
            "entra-signing-certificate-selected"
        ),
        "certificateValidityOutcome": (
            "matches-verified-entra-certificate"
        ),
        "oauthClientId": "safe-client-id",
        "oauthTokenUrl": (
            "https://example.workday.com/ccx/oauth2/"
            "contoso_impl/token"
        ),
        "restBaseUrl": "https://example.workday.com/ccx/api",
        "soapBaseUrl": "https://example.workday.com/ccx/service",
        "authenticationPolicyOutcome": "existing-active-policy",
        "networkReadinessOutcome": "confirmed-hosts-allowed",
        "apiClientOutcome": "existing-client-verified",
        "clientGrantType": "saml-bearer",
        "includeWorkdayOwnedScope": "yes",
        "identityProviderSsoServiceUrl": (
            "https://login.microsoftonline.com/"
            "00000000-0000-0000-0000-000000000000/saml2"
        ),
        "signOnRedirectUrl": "https://www.workday.com/saml/acs",
        "rolloutType": "limited-or-test",
        "employeeSecurityGroup": "ESS Workday Pilot Employees",
        "publicWorkerReportsOutcome": "get-permission-verified",
        "integrationPermissionsGetOutcome": "get-permission-verified",
        "functionalAreaScopes": [
            "Core Payroll",
            "Organizations and Roles",
            "Staffing",
            "Time Off and Leave",
        ],
        "optionalDomains": [],
    }


def _write_workspace(root: Path) -> None:
    agent = root / "workspace" / "agents" / "ess-hr"
    topics = agent / "topics"
    topics.mkdir(parents=True)
    component_map = {}
    for index in (1, 2):
        path = f"topics/workday-{index}.mcs.yml"
        topics.joinpath(f"workday-{index}.mcs.yml").write_text(
            "kind: AdaptiveDialog\n",
            encoding="utf-8",
        )
        component_map[path] = {
            "componentKind": "DialogComponent",
            "componentId": f"topic-{index}",
            "schemaName": f"contoso.topic.WorkdayTopic{index}",
            "displayName": f"Workday Topic {index}",
        }
    agent.joinpath(".component-map.json").write_text(
        json.dumps(component_map),
        encoding="utf-8",
    )
    local = root / ".local"
    local.mkdir()
    local.joinpath("config.json").write_text(
        json.dumps(
            {
                "releaseLine": "da",
                "environmentId": "environment-id",
                "activeAgent": "ess-hr",
                "powerPlatformApiEndpoint": ("https://api.test.powerplatform.com"),
                "agent": {
                    "slug": "ess-hr",
                    "botId": "bot-id",
                    "schemaName": "contoso",
                    "folder": str(agent),
                    "releaseLine": "da",
                },
                "agents": [
                    {
                        "slug": "ess-hr",
                        "botId": "bot-id",
                        "schemaName": "contoso",
                        "folder": str(agent),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_runtime_wiring(root: Path, *, nested_call: bool = False) -> None:
    agent = root / "workspace" / "agents" / "ess-hr"
    component_map_path = agent / ".component-map.json"
    component_map = json.loads(
        component_map_path.read_text(encoding="utf-8")
    )
    runtime_schema = (
        "contoso.topic.WorkdaySystemSetRuntimeTemplateConfigurations"
    )
    topics = agent / "topics"
    topics.joinpath("conversation-start.mcs.yml").write_text(
        (
            "kind: AdaptiveDialog\n"
            "beginDialog:\n"
            "  kind: OnConversationStart\n"
            "  actions:\n"
            "    - kind: BeginDialog\n"
            "      dialog: contoso.topic.System-UserContext-Createglobalvariables\n"
            "    - kind: SendActivity\n"
            "      activity: Welcome\n"
            "    - kind: BeginDialog\n"
            f"      dialog: {runtime_schema}\n"
            "    - kind: BeginDialog\n"
            "      dialog: contoso.topic.System-UserContext-Validate\n"
        ),
        encoding="utf-8",
    )
    topics.joinpath("runtime-template.mcs.yml").write_text(
        "kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRedirect\n",
        encoding="utf-8",
    )
    user_context_actions = (
        "  actions:\n"
        "    - kind: BeginDialog\n"
        f"      dialog: {runtime_schema}\n"
        if nested_call
        else "  actions: []\n"
    )
    topics.joinpath("user-context-v2.mcs.yml").write_text(
        "kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRedirect\n"
        + user_context_actions,
        encoding="utf-8",
    )
    component_map.update(
        {
            "topics/conversation-start.mcs.yml": {
                "componentKind": "DialogComponent",
                "componentId": "conversation-start",
                "schemaName": "contoso.topic.ConversationStart",
                "displayName": "Conversation Start",
            },
            "topics/runtime-template.mcs.yml": {
                "componentKind": "DialogComponent",
                "componentId": "runtime-template",
                "schemaName": runtime_schema,
                "displayName": (
                    "Workday [System] - 1: Set Runtime Template "
                    "Configurations"
                ),
            },
            "topics/user-context-v2.mcs.yml": {
                "componentKind": "DialogComponent",
                "componentId": "user-context-v2",
                "schemaName": (
                    "contoso.topic.WorkdaySystemGetUserContextV2"
                ),
                "displayName": (
                    "Workday [System] - 1: Set User Context V2"
                ),
            },
        }
    )
    component_map_path.write_text(
        json.dumps(component_map),
        encoding="utf-8",
    )


class _VerifiedClient:
    def __init__(self):
        self.signed_in_username = ""
        self.expectations = []

    def authenticate(self, preferred_username=None):
        self.signed_in_username = preferred_username

    def verify_dialog_components(self, expectations):
        self.expectations = expectations
        return {
            "verifiedComponents": len(expectations),
            "activeComponents": len(expectations),
            "blockingDiagnostics": [],
        }


def test_agent_binding_is_built_from_live_checks_and_components(
    tmp_path: Path,
) -> None:
    from workday_connect_agent import verify_agent_binding

    _write_workspace(tmp_path)
    client = _VerifiedClient()

    evidence = verify_agent_binding(
        tmp_path,
        _state(),
        client_factory=lambda _config: client,
    )

    assert evidence["workdayTopics"] == {
        "expected": 2,
        "verified": 2,
        "active": 2,
        "blockingDiagnostics": [],
    }
    assert all(
        expectation["requireCleanDiagnostics"] is False
        for expectation in client.expectations
    )


def test_topic_activation_skips_checkpoints_and_allows_diagnostics(
    tmp_path: Path,
) -> None:
    from workday_connect_agent import verify_topic_activation

    _write_workspace(tmp_path)
    client = _VerifiedClient()

    def verify(expectations):
        client.expectations = expectations
        return {
            "verifiedComponents": len(expectations),
            "activeComponents": len(expectations),
            "blockingDiagnostics": [
                {
                    "errorCode": "NotFound",
                    "errorMessage": "CloudFlow not found",
                    "referenceType": "CloudFlow",
                }
            ],
        }

    client.verify_dialog_components = verify

    evidence = verify_topic_activation(
        tmp_path,
        _state(),
        client_factory=lambda _config: client,
    )

    assert evidence["workdayTopics"]["active"] == 2
    assert evidence["workdayTopics"]["blockingDiagnostics"]
    assert all(
        expectation["requireCleanDiagnostics"] is False
        for expectation in client.expectations
    )


def test_runtime_template_wiring_is_verified_against_live_topics(
    tmp_path: Path,
) -> None:
    from workday_connect_agent import verify_runtime_template_wiring

    _write_workspace(tmp_path)
    _write_runtime_wiring(tmp_path)
    client = _VerifiedClient()

    evidence = verify_runtime_template_wiring(
        tmp_path,
        _state(),
        client_factory=lambda _config: client,
        converter=lambda items: [
            {
                "key": item["key"],
                "success": True,
                "objectModel": {"$kind": "AdaptiveDialog", "key": item["key"]},
            }
            for item in items
        ],
    )

    assert evidence["verifiedComponents"] == 3
    assert evidence["runtimeTemplate"].endswith(
        "WorkdaySystemSetRuntimeTemplateConfigurations"
    )
    assert {item["componentId"] for item in client.expectations} == {
        "conversation-start",
        "runtime-template",
        "user-context-v2",
    }
    conversation_expectation = next(
        item
        for item in client.expectations
        if item["componentId"] == "conversation-start"
    )
    assert conversation_expectation["state"] == "Active"
    assert conversation_expectation["status"] == "Active"
    assert conversation_expectation["requireCleanDiagnostics"] is True


def test_runtime_template_wiring_rejects_wrong_conversation_start_position(
    tmp_path: Path,
) -> None:
    import pytest

    from workday_connect_agent import (
        WorkdayConnectAgentError,
        verify_runtime_template_wiring,
    )

    _write_workspace(tmp_path)
    _write_runtime_wiring(tmp_path)
    conversation_start = (
        tmp_path
        / "workspace"
        / "agents"
        / "ess-hr"
        / "topics"
        / "conversation-start.mcs.yml"
    )
    text = conversation_start.read_text(encoding="utf-8")
    text = text.replace(
        (
            "    - kind: SendActivity\n"
            "      activity: Welcome\n"
            "    - kind: BeginDialog\n"
            "      dialog: contoso.topic."
            "WorkdaySystemSetRuntimeTemplateConfigurations\n"
        ),
        (
            "    - kind: BeginDialog\n"
            "      dialog: contoso.topic."
            "WorkdaySystemSetRuntimeTemplateConfigurations\n"
            "    - kind: SendActivity\n"
            "      activity: Welcome\n"
        ),
    )
    conversation_start.write_text(text, encoding="utf-8")

    with pytest.raises(
        WorkdayConnectAgentError,
        match="immediately before User Context Validate",
    ):
        verify_runtime_template_wiring(
            tmp_path,
            _state(),
            client_factory=lambda _config: _VerifiedClient(),
        )


def test_runtime_template_wiring_rejects_obsolete_nested_call(
    tmp_path: Path,
) -> None:
    import pytest

    from workday_connect_agent import (
        WorkdayConnectAgentError,
        verify_runtime_template_wiring,
    )

    _write_workspace(tmp_path)
    _write_runtime_wiring(tmp_path, nested_call=True)

    with pytest.raises(
        WorkdayConnectAgentError,
        match="obsolete nested",
    ):
        verify_runtime_template_wiring(
            tmp_path,
            _state(),
            client_factory=lambda _config: _VerifiedClient(),
        )


def test_runtime_template_wiring_rejects_spoofed_component_schema(
    tmp_path: Path,
) -> None:
    import pytest

    from workday_connect_agent import (
        WorkdayConnectAgentError,
        verify_runtime_template_wiring,
    )

    _write_workspace(tmp_path)
    _write_runtime_wiring(tmp_path)
    component_map_path = (
        tmp_path
        / "workspace"
        / "agents"
        / "ess-hr"
        / ".component-map.json"
    )
    component_map = json.loads(
        component_map_path.read_text(encoding="utf-8")
    )
    component_map["topics/runtime-template.mcs.yml"]["schemaName"] = (
        "contoso.topic.UnrelatedDialog"
    )
    component_map_path.write_text(
        json.dumps(component_map),
        encoding="utf-8",
    )

    with pytest.raises(
        WorkdayConnectAgentError,
        match="does not match the reviewed",
    ):
        verify_runtime_template_wiring(
            tmp_path,
            _state(),
            client_factory=lambda _config: _VerifiedClient(),
        )


def test_runtime_template_wiring_rejects_recursive_yaml_alias(
    tmp_path: Path,
) -> None:
    import pytest

    from workday_connect_agent import (
        WorkdayConnectAgentError,
        verify_runtime_template_wiring,
    )

    _write_workspace(tmp_path)
    _write_runtime_wiring(tmp_path)
    conversation_start = (
        tmp_path
        / "workspace"
        / "agents"
        / "ess-hr"
        / "topics"
        / "conversation-start.mcs.yml"
    )
    conversation_start.write_text(
        (
            "kind: AdaptiveDialog\n"
            "beginDialog: &start\n"
            "  kind: OnConversationStart\n"
            "  actions:\n"
            "    - kind: BeginDialog\n"
            "      dialog: "
            "contoso.topic.WorkdaySystemSetRuntimeTemplateConfigurations\n"
            "  recursive: *start\n"
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        WorkdayConnectAgentError,
        match="recursive YAML alias",
    ):
        verify_runtime_template_wiring(
            tmp_path,
            _state(),
            client_factory=lambda _config: _VerifiedClient(),
        )


def test_runtime_template_wiring_requires_target_in_live_reread(
    tmp_path: Path,
) -> None:
    import pytest

    from minimalbot_evaluation import MinimalBotEvaluationError
    from workday_connect_agent import (
        WorkdayConnectAgentError,
        verify_runtime_template_wiring,
    )

    _write_workspace(tmp_path)
    _write_runtime_wiring(tmp_path)

    class MissingTargetClient(_VerifiedClient):
        def verify_dialog_components(self, expectations):
            assert any(
                item["componentId"] == "runtime-template"
                for item in expectations
            )
            raise MinimalBotEvaluationError(
                "missing component ID: runtime-template"
            )

    with pytest.raises(
        WorkdayConnectAgentError,
        match="did not retain",
    ):
        verify_runtime_template_wiring(
            tmp_path,
            _state(),
            client_factory=lambda _config: MissingTargetClient(),
            converter=lambda items: [
                {
                    "key": item["key"],
                    "success": True,
                    "objectModel": {
                        "$kind": "AdaptiveDialog",
                        "key": item["key"],
                    },
                }
                for item in items
            ],
        )


def test_agent_binding_rejects_environment_drift(tmp_path: Path) -> None:
    import pytest

    from workday_connect_agent import (
        WorkdayConnectAgentError,
        verify_agent_binding,
    )

    _write_workspace(tmp_path)
    state = _state()
    state["scope"]["environmentId"] = "other-environment"

    with pytest.raises(WorkdayConnectAgentError, match="different environments"):
        verify_agent_binding(
            tmp_path,
            state,
            client_factory=lambda _config: _VerifiedClient(),
        )


def test_controller_persists_phase_blocker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import pytest

    import workday_connect
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified"},
    )
    store.set_phase_status("preflight", "complete")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "workday_connect.py",
            "--root",
            str(tmp_path),
            "set-workday-tenant",
            "--tenant",
            "",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        workday_connect.main()

    assert exc.value.code == 1
    status = WorkdayConnectStore(tmp_path).status()
    assert status["nextPhaseId"] == "entra"
    assert "operation" not in status["blocker"]
    assert status["blocker"]["summary"]
    assert status["blocker"]["nextAction"]


def test_controller_records_invocation_only_at_status_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from contextlib import contextmanager

    import workday_connect
    from workday_connect_store import WorkdayConnectStore

    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
    migration_checks = []
    operation_guards = []

    @contextmanager
    def operation_guard(_store):
        operation_guards.append("entered")
        yield

    monkeypatch.setattr(
        WorkdayConnectStore,
        "operation_guard",
        operation_guard,
    )
    monkeypatch.setattr(
        workday_connect,
        "_ensure_migration_baseline",
        lambda _store: migration_checks.append("checked"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "workday_connect.py",
            "--root",
            str(tmp_path),
            "status",
        ],
    )
    workday_connect.main()
    workday_connect.main()
    assert migration_checks == []
    assert operation_guards == []
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "workday_connect.py",
            "--root",
            str(tmp_path),
            "set-workday-tenant",
            "--tenant",
            "contoso_impl",
        ],
    )
    workday_connect.main()
    assert migration_checks == ["checked"]
    assert operation_guards == ["entered"]

    events = WorkdayConnectStore(tmp_path).load()["lifecycle"]["journal"]
    assert [event["event"] for event in events] == ["invoked"]


def test_controller_parser_accepts_labeled_worksheet_files() -> None:
    import workday_connect

    entra = workday_connect.build_parser().parse_args(
        [
            "record-entra",
            "--verification-worksheet-file",
            "entra.txt",
        ]
    )
    workday = workday_connect.build_parser().parse_args(
        [
            "record-workday-admin",
            "--response-worksheet-file",
            "workday.txt",
        ]
    )

    assert entra.verification_worksheet_file == Path("entra.txt")
    assert workday.response_worksheet_file == Path("workday.txt")


def test_controller_parser_accepts_guided_entra_handoff() -> None:
    import workday_connect

    args = workday_connect.build_parser().parse_args(["entra-handoff"])

    assert args.discovery_file is None
    assert args.discovery_json is None


def test_controller_public_command_and_result_contract_is_stable(
    capsys,
) -> None:
    import argparse

    import workday_connect

    parser = workday_connect.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    assert tuple(subparsers.choices) == (
        "status",
        "discover-realm-target",
        "set-workday-tenant",
        "entra-handoff",
        "record-entra",
        "administrator-stage",
        "record-administrator-evidence",
        "workday-admin-packet",
        "record-workday-admin",
        "runtime-plan",
        "runtime-apply",
        "runtime-approve",
        "record-connections",
        "record-topic-activation",
        "record-runtime-template-wiring",
        "record-agent-binding",
        "record-validation",
        "record-validation-failure",
        "preflight",
        "prepare-connections",
        "prepare-connections-approve",
    )

    workday_connect._emit("status", {"status": "in-progress"})
    output = capsys.readouterr().out
    payload = json.loads(
        output.split(workday_connect.RESULT_MARKER, maxsplit=1)[1]
    )

    assert payload == {
        "contractVersion": 4,
        "operation": "status",
        "status": "in-progress",
    }


@pytest.mark.parametrize(
    "command",
    ("begin-employee-test", "abandon-employee-test"),
)
def test_retired_employee_test_commands_are_rejected(command: str) -> None:
    import workday_connect

    with pytest.raises(SystemExit):
        workday_connect.build_parser().parse_args([command])


def test_controller_persists_valid_partial_administrator_fields(
    tmp_path: Path,
) -> None:
    import workday_connect
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "entraTenantId": "tenant-id",
            "workdayTenant": "contoso",
        },
    )
    for action in model.PHASE_REQUIRED_ACTIONS["preflight"]:
        store.complete_action(
            "preflight",
            action,
            evidence={"outcome": "verified"},
        )
    store.set_phase_status("preflight", "complete")
    for substage in (
        "administrator-engaged",
        "handoff-presented",
        "awaiting-completion",
        "completion-confirmed",
    ):
        store.record_administrator_progress("entra", substage)
    evidence_file = tmp_path / "partial.json"
    evidence_file.write_text(
        json.dumps(
            {
                "fields": {
                    "selectedDirectoryId": "tenant-id",
                    "loginUrl": (
                        "https://login.microsoftonline.com/wrong/saml2"
                    ),
                },
                "invalidFields": [],
            }
        ),
        encoding="utf-8",
    )

    result = workday_connect._record_administrator_evidence(
        SimpleNamespace(
            phase="entra",
            evidence_file=evidence_file,
            evidence_json=None,
        ),
        store,
    )

    assert result["acceptedFields"] == ["selectedDirectoryId"]
    assert result["invalidFields"] == ["loginUrl"]
    assert "loginUrl" in result["fieldErrors"]
    administrator = store.load()["phases"]["entra"]["administrator"]
    assert administrator["partialEvidence"] == {
        "selectedDirectoryId": "tenant-id",
    }


def test_entra_handoff_rediscovery_and_replay_return_actionable_packet(
    tmp_path: Path,
) -> None:
    import workday_connect
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "entraTenantId": (
                "00000000-0000-0000-0000-000000000000"
            ),
            "workdayTenant": "contoso_impl",
        },
    )
    _complete_preflight(store)
    store.record_administrator_progress(
        "entra",
        "administrator-engaged",
    )
    guided = workday_connect._entra_handoff(
        SimpleNamespace(
            discovery_file=None,
            discovery_json=None,
        ),
        store,
    )
    assert guided["packet"]["target"]["mode"] == "administrator-selection"
    assert guided["rediscoveryRequired"] is False

    creation = workday_connect._entra_handoff(
        SimpleNamespace(
            discovery_file=None,
            discovery_json=json.dumps(
                {
                    "directoryDisplayName": "Contoso",
                    "applications": [],
                    "allowCreate": True,
                }
            ),
        ),
        store,
    )

    assert creation["packet"]["requiresRediscovery"] is True
    assert creation["packet"] is not None
    assert store.load()["phases"]["entra"]["administrator"]["substage"] == (
        "administrator-engaged"
    )

    discovery = {
        "directoryDisplayName": "Contoso",
        "applications": [
            {
                "displayName": "Workday",
                "appId": "44444444-4444-4444-4444-444444444444",
                "objectId": "55555555-5555-5555-5555-555555555555",
                "servicePrincipalId": (
                    "66666666-6666-6666-6666-666666666666"
                ),
                "identifierUris": [
                    "http://www.workday.com/contoso_impl",
                ],
                "replyUrls": [],
            }
        ]
    }
    actionable = workday_connect._entra_handoff(
        SimpleNamespace(
            discovery_file=None,
            discovery_json=json.dumps(discovery),
        ),
        store,
    )
    assert actionable["alreadyPresented"] is False
    assert store.load()["phases"]["entra"]["administrator"]["substage"] == (
        "administrator-engaged"
    )
    store.record_administrator_progress("entra", "handoff-presented")
    replay = workday_connect._entra_handoff(
        SimpleNamespace(
            discovery_file=None,
            discovery_json=json.dumps(discovery),
        ),
        store,
    )

    assert actionable["packet"]["target"]["mode"] == "reuse"
    assert replay["alreadyPresented"] is True
    assert replay["packet"] == actionable["packet"]


def test_controller_rejects_non_string_invalid_field_names(
    tmp_path: Path,
) -> None:
    import pytest

    import workday_connect
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _complete_preflight(store)
    _advance_administrator_to_completion(store, "entra")

    with pytest.raises(
        WorkdayConnectStoreError,
        match="must contain field names",
    ):
        workday_connect._record_administrator_evidence(
            SimpleNamespace(
                phase="entra",
                evidence_file=None,
                evidence_json=json.dumps(
                    {
                        "fields": {},
                        "invalidFields": [{}],
                    }
                ),
            ),
            store,
        )


def test_entra_finalization_uses_retained_partial_evidence_and_replays(
    tmp_path: Path,
) -> None:
    import workday_connect
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "entraTenantId": (
                "00000000-0000-0000-0000-000000000000"
            ),
            "workdayTenant": "contoso_impl",
        },
    )
    _complete_preflight(store)
    _advance_administrator_to_completion(store, "entra")
    store.record_administrator_progress(
        "entra",
        "collecting-evidence",
        valid_fields=_entra_partial_evidence(),
    )
    args = SimpleNamespace(
        verification_file=None,
        verification_json="{}",
    )

    result = workday_connect._record_entra(args, store)
    replay = workday_connect._record_entra(args, store)
    changed_verification = workday_connect._merge_entra_verification(
        store.load(),
        {},
    )
    changed_verification["application"].update(
        {
            "appId": "88888888-8888-8888-8888-888888888888",
            "objectId": "99999999-9999-9999-9999-999999999999",
            "servicePrincipalId": (
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            ),
            "identifierUris": [
                "http://www.workday.com/contoso_impl",
                "api://88888888-8888-8888-8888-888888888888",
            ],
        }
    )
    drift = workday_connect._record_entra(
        SimpleNamespace(
            verification_file=None,
            verification_json=json.dumps(changed_verification),
        ),
        store,
    )

    assert result["verified"] is True
    assert replay["replayed"] is True
    assert drift["driftDetected"] is True
    state = store.load()
    assert state["phases"]["entra"]["status"] == "pending"
    assert state["identifiers"]["entraAppId"] == (
        "88888888-8888-8888-8888-888888888888"
    )


def test_workday_finalization_uses_retained_partial_evidence_and_replays(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workday_connect
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    monkeypatch.setattr(
        workday_connect,
        "_run_profile_gate",
        lambda *_args, **_kwargs: {"checkpointStatuses": {}},
    )

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "entraTenantId": (
                "00000000-0000-0000-0000-000000000000"
            ),
            "workdayTenant": "contoso_impl",
        },
    )
    _complete_preflight(store)
    store.merge_section(
        "identifiers",
        {
            "entraAppId": "44444444-4444-4444-4444-444444444444",
            "entraAppObjectId": (
                "55555555-5555-5555-5555-555555555555"
            ),
            "entraServicePrincipalId": (
                "66666666-6666-6666-6666-666666666666"
            ),
            "entraAppIdUri": (
                "api://44444444-4444-4444-4444-444444444444"
            ),
            "scopeGuid": "77777777-7777-7777-7777-777777777777",
            "microsoftEntraIdentifier": (
                "https://sts.windows.net/"
                "00000000-0000-0000-0000-000000000000/"
            ),
            "entraLoginUrl": (
                "https://login.microsoftonline.com/"
                "00000000-0000-0000-0000-000000000000/saml2"
            ),
            "replyUrl": "https://www.workday.com/saml/acs",
            "workdaySamlEntityId": (
                "http://www.workday.com/contoso_impl"
            ),
            "signingCertificate": {
                "thumbprint": "AA11",
                "validTo": "2027-01-01T00:00:00Z",
            },
        },
    )
    for action in model.PHASE_REQUIRED_ACTIONS["entra"]:
        store.complete_action(
            "entra",
            action,
            evidence={"outcome": "verified"},
        )
    store.set_phase_status("entra", "complete")
    _advance_administrator_to_completion(store, "workday-admin")
    partial = _workday_partial_evidence()
    partial.pop("networkReadinessOutcome")
    store.record_administrator_progress(
        "workday-admin",
        "collecting-evidence",
        valid_fields=partial,
    )
    args = SimpleNamespace(
        response_file=None,
        response_json=json.dumps(
            {
                "networkReadinessOutcome": (
                    "confirmed-hosts-allowed"
                )
            }
        ),
    )

    result = workday_connect._record_workday_admin(args, store)
    completed = store.load()
    assert completed["tenantFoundation"] is not None
    assert "validFrom" not in completed["tenantFoundation"]["identifiers"][
        "signingCertificate"
    ]
    completed["tenantFoundation"] = None
    store.config_path.write_text(
        json.dumps(completed),
        encoding="utf-8",
    )
    replay = workday_connect._record_workday_admin(
        SimpleNamespace(
            response_file=None,
            response_json="{}",
        ),
        store,
    )
    assert store.load()["tenantFoundation"] is not None
    drift = workday_connect._record_workday_admin(
        SimpleNamespace(
            response_file=None,
            response_json=json.dumps(
                {"oauthClientId": "rotated-client-id"}
            ),
        ),
        store,
    )

    assert result["verified"] is True
    assert replay["replayed"] is True
    assert drift["driftDetected"] is True
    state = store.load()
    assert state["phases"]["workday-admin"]["status"] == "pending"
    assert state["identifiers"]["oauthClientId"] == "rotated-client-id"


def test_workday_administrator_commands_require_completed_entra(
    tmp_path: Path,
) -> None:
    import pytest
    import workday_connect
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _complete_preflight(store)

    with pytest.raises(
        WorkdayConnectStoreError,
        match="Complete the Microsoft Entra administrator sign-off",
    ):
        workday_connect._workday_admin_packet(
            SimpleNamespace(),
            store,
        )

    with pytest.raises(
        WorkdayConnectStoreError,
        match="Complete the Microsoft Entra administrator sign-off",
    ):
        workday_connect._record_workday_admin(
            SimpleNamespace(response_file=None, response_json="{}"),
            store,
        )


def test_controller_surfaces_blocker_persistence_failure(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    import pytest

    import workday_connect
    from workday_connect_store import WorkdayConnectStore

    def fail_persistence(*_args, **_kwargs):
        raise OSError("state is read-only")

    monkeypatch.setattr(
        WorkdayConnectStore,
        "set_phase_status",
        fail_persistence,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "workday_connect.py",
            "--root",
            str(tmp_path),
            "set-workday-tenant",
            "--tenant",
            "",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        workday_connect.main()

    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert '"blockerPersistenceError": "state is read-only"' in error


def test_controller_emits_structured_runtime_error_details(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    import pytest

    import workday_connect
    from workday_connect_runtime import WorkdayConnectRuntimeError

    details = {
        "connector": "shared_workdaysoap",
        "candidateConnections": [
            {
                "connectionId": "connection-id",
                "displayName": "Workday",
            }
        ],
    }

    def raise_ambiguity(_args, _store):
        raise WorkdayConnectRuntimeError(
            "Select one connected Workday connection.",
            details=details,
        )

    monkeypatch.setitem(
        workday_connect._COMMAND_HANDLERS,
        "status",
        raise_ambiguity,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "workday_connect.py",
            "--root",
            str(tmp_path),
            "status",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        workday_connect.main()

    assert exc.value.code == 1
    error = capsys.readouterr().err
    payload = json.loads(
        error.split(workday_connect.ERROR_MARKER, maxsplit=1)[1]
    )
    assert payload["details"] == details


def test_record_connections_uses_live_verification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workday_connect
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in ("preflight", "entra", "workday-admin"):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    store.complete_action(
        "connections",
        "verify-package",
        evidence={"outcome": "verified"},
    )
    monkeypatch.setattr(
        workday_connect,
        "verify_physical_connections",
        lambda *_args, **_kwargs: {
            "makerUsername": "maker@example.com",
            "connectionIds": {
                "workday": "workday-id",
                "dataverse": "dataverse-id",
            },
            "connections": [
                {
                    "connector": "shared_workdaysoap",
                    "displayName": "Workday",
                },
                {
                    "connector": "shared_commondataserviceforapps",
                    "displayName": "Dataverse",
                },
            ],
        },
    )

    result = workday_connect._record_connections(
        SimpleNamespace(
            evidence_json=None,
            workday_connection_id=None,
            dataverse_connection_id=None,
            confirm_workday_target=True,
        ),
        store,
    )

    connections = store.load()["phases"]["connections"]
    assert result["verified"] is True
    assert connections["status"] == "complete"
    assert connections["completedActions"] == [
        "verify-package",
        "physical-connections-verified",
    ]
    assert connections["evidence"][1]["connectionIds"] == {
        "workday": "workday-id",
        "dataverse": "dataverse-id",
    }


def test_record_connections_previews_before_target_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workday_connect
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {"workdayTenant": "contoso"},
    )
    store.merge_section(
        "identifiers",
        {
            "workdaySamlEntityId": "http://www.workday.com/contoso",
            "oauthClientId": "client-id",
        },
    )
    store.merge_section(
        "endpoints",
        {
            "oauthTokenUrl": "https://example.workday.com/oauth/token",
            "soapBaseUrl": "https://example.workday.com/ccx/service",
            "restBaseUrl": "https://example.workday.com/ccx/api",
        },
    )
    for phase_id in ("preflight", "entra", "workday-admin"):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    store.complete_action(
        "connections",
        "verify-package",
        evidence={"outcome": "verified"},
    )
    monkeypatch.setattr(
        workday_connect,
        "verify_physical_connections",
        lambda *_args, **_kwargs: {
            "makerUsername": "maker@example.com",
            "connectionIds": {
                "workday": "workday-id",
                "dataverse": "dataverse-id",
            },
            "connections": [
                {
                    "connector": "shared_workdaysoap",
                    "displayName": "Workday",
                },
                {
                    "connector": "shared_commondataserviceforapps",
                    "displayName": "Dataverse",
                },
            ],
        },
    )

    result = workday_connect._record_connections(
        SimpleNamespace(
            evidence_json=None,
            workday_connection_id=None,
            dataverse_connection_id=None,
            confirm_workday_target=False,
        ),
        store,
    )

    assert result["requiresConfirmation"] is True
    assert result["workdayTarget"] == {
        "displayName": "",
        "authenticationType": "Microsoft Entra ID Integrated",
        "resourceUrl": "http://www.workday.com/contoso",
        "oauthTokenUrl": "https://example.workday.com/oauth/token",
        "oauthClientId": "client-id",
        "soapBaseUrl": "https://example.workday.com/ccx/service",
        "restBaseUrl": "https://example.workday.com/ccx/api",
        "tenantName": "contoso",
    }
    assert store.load()["phases"]["connections"]["status"] == "active"


def test_record_agent_binding_completes_only_from_verifier_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workday_connect
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "environmentId": "environment-id",
            "packageFlavor": "runtime",
            "agent": {
                "slug": "ess-hr",
                "botId": "bot-id",
                "schemaName": "contoso",
            },
        },
    )
    store.merge_section(
        "operators",
        {"powerPlatformMaker": {"username": "maker@example.com"}},
    )
    for phase_id in ("preflight", "entra", "workday-admin", "connections"):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    for action in (
        "connection-references-bound",
        "runtime-flows-active",
        "delegated-authorization-configured",
        "runtime-template-configured",
    ):
        store.complete_action(
            "runtime",
            action,
            evidence={"outcome": "verified"},
        )
    monkeypatch.setattr(
        workday_connect,
        "verify_agent_binding",
        lambda *_args, **_kwargs: {
            "environmentId": "environment-id",
            "botId": "bot-id",
            "makerUsername": "maker@example.com",
            "workdayTopics": {
                "expected": 23,
                "verified": 23,
                "active": 23,
                "blockingDiagnostics": [
                    {
                        "errorCode": "NotFound",
                        "errorMessage": "CloudFlow not found",
                        "referenceType": "CloudFlow",
                    }
                ],
            },
        },
    )
    observed_profiles = []

    def run_profile_gate(_store, profile_name):
        observed_profiles.append(profile_name)
        return {
            "checkpointStatuses": (
                {"WD-CONN-013": "Passed"}
                if profile_name == "workday-da:post-connection"
                else {"WD-REST-002": "Passed"}
            )
        }

    monkeypatch.setattr(
        workday_connect,
        "_run_profile_gate",
        run_profile_gate,
    )
    attachment_file = tmp_path / "attachment.json"
    attachment_file.write_text(
        json.dumps(
            {
                "outcome": "maker-confirmed",
                "botId": "bot-id",
                "flowNames": [
                    "ESS Workday Runtime",
                    "ESS Workday Runtime REST Execution",
                ],
                "parameterSharingOutcome": (
                    "enabled-for-exposed-connections"
                ),
            }
        ),
        encoding="utf-8",
    )

    result = workday_connect._record_agent_binding(
        SimpleNamespace(attachment_file=attachment_file),
        store,
    )

    runtime = store.load()["phases"]["runtime"]
    assert result["verified"] is True
    assert observed_profiles == [
        "workday-da:dataverse-ready",
        "workday-da:post-connection",
        "workday-da:post-agent-wiring",
    ]
    assert runtime["status"] == "complete"
    assert "workday-topics-activated" in runtime["completedActions"]
    topic_evidence = next(
        item
        for item in runtime["evidence"]
        if item["action"] == "workday-topics-activated"
    )
    assert topic_evidence["blockingDiagnostics"] == [
        {
            "errorCode": "NotFound",
            "errorMessage": "CloudFlow not found",
            "referenceType": "CloudFlow",
        }
    ]


def test_record_topic_activation_does_not_infer_runtime_failure_from_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workday_connect
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
    ):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    monkeypatch.setattr(
        workday_connect,
        "verify_topic_activation",
        lambda *_args, **_kwargs: {
            "environmentId": "environment-id",
            "botId": "bot-id",
            "makerUsername": "maker@example.com",
            "workdayTopics": {
                "expected": 23,
                "verified": 23,
                "active": 23,
                "blockingDiagnostics": [
                    {
                        "errorCode": "NotFound",
                        "errorMessage": "CloudFlow not found",
                        "referenceType": "CloudFlow",
                    }
                ],
            },
        },
    )

    result = workday_connect._record_topic_activation(
        SimpleNamespace(),
        store,
    )

    runtime = store.load()["phases"]["runtime"]
    assert result["verified"] is True
    assert result["diagnosticsObserved"] == 1
    assert "workday-topics-activated" in runtime["completedActions"]
    assert runtime["status"] == "active"
    assert runtime["blocker"] is None


def test_runtime_template_wiring_requires_topic_activation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import pytest

    import workday_connect
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    verifier_called = False

    def verify(*_args, **_kwargs):
        nonlocal verifier_called
        verifier_called = True
        return {}

    monkeypatch.setattr(
        workday_connect,
        "verify_runtime_template_wiring",
        verify,
    )

    with pytest.raises(
        WorkdayConnectStoreError,
        match="Enable and verify all Workday topics",
    ):
        workday_connect._record_runtime_template_wiring(
            SimpleNamespace(),
            store,
        )

    assert verifier_called is False


def test_record_agent_binding_rejects_manual_boolean_evidence(
    tmp_path: Path,
) -> None:
    import pytest

    import workday_connect
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

    with pytest.raises(
        WorkdayConnectStoreError,
        match="requires a JSON input file",
    ):
        workday_connect._record_agent_binding(
            SimpleNamespace(attachment_file=None),
            WorkdayConnectStore(tmp_path),
        )


def test_record_validation_failure_tracks_maker_authorization_remediation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    import pytest

    import workday_connect
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
    ):
        if phase_id == "runtime":
            store.approve_plan(
                "runtime",
                {
                    "phase": "runtime",
                    "scope": {"environmentId": "environment-id"},
                    "actions": ["Configure runtime"],
                    "flows": [
                        {"name": "REST", "workflowId": "flow-id"}
                    ],
                },
            )
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            evidence = {"outcome": "verified"}
            if (
                phase_id == "runtime"
                and action == "flow-attachment-confirmed"
            ):
                evidence["flowNames"] = ["REST"]
            store.complete_action(
                phase_id,
                action,
                evidence=evidence,
            )
        store.set_phase_status(phase_id, "complete")
    evidence_file = tmp_path / "employee-failure.json"
    evidence_file.write_text(
        json.dumps(
            {
                "remediationId": "WD-E2E-006",
                "scenarioName": "Check vacation balance",
                "affectedDomain": "Worker Data: Public Worker Reports",
                "timestamp": "2026-10-06T01:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    result = workday_connect._record_validation_failure(
        SimpleNamespace(evidence_file=evidence_file),
        store,
    )

    phase = store.load()["phases"]["maker-validation"]
    assert result["recorded"] is True
    assert phase["status"] == "blocked"
    assert phase["blocker"]["scenarioName"] == "Check vacation balance"
    assert phase["blocker"]["affectedDomain"] == (
        "Worker Data: Public Worker Reports"
    )

    success_file = tmp_path / "maker-validation.json"
    success_file.write_text(
        json.dumps(
            {
                "testUserCategory": "maker",
                "scenarioName": "Check worker profile",
                "timestamp": "2026-10-06T01:10:00Z",
                "outcome": "passed",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "workday_connect.py",
            "--root",
            str(tmp_path),
            "record-validation",
            "--evidence-file",
            str(success_file),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        workday_connect.main()
    assert exc.value.code == 1
    capsys.readouterr()
    preserved_blocker = store.load()["phases"]["maker-validation"][
        "blocker"
    ]
    assert preserved_blocker["scenarioName"] == "Check vacation balance"
    assert preserved_blocker["affectedDomain"] == (
        "Worker Data: Public Worker Reports"
    )

    success_file.write_text(
        json.dumps(
            {
                "testUserCategory": "maker",
                "scenarioName": "Check vacation balance",
                "timestamp": "2026-10-06T01:10:00Z",
                "outcome": "passed",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(workday_connect, "_run_final_readiness", lambda _store: None)
    result = workday_connect._record_validation(
        SimpleNamespace(evidence_file=success_file),
        store,
    )

    assert result["lifecycleComplete"] is True
    maker_evidence = store.load()["phases"]["maker-validation"]["evidence"][0]
    assert maker_evidence["scenarioName"] == "Check vacation balance"
    assert maker_evidence["authorizationRemediationDomain"] == (
        "Worker Data: Public Worker Reports"
    )
    assert maker_evidence["authorizationRetestOutcome"] == (
        "verified-after-remediation"
    )


@pytest.mark.parametrize("transport_failure", [False, True])
def test_runtime_apply_revalidation_failure_does_not_persist_blocker(
    tmp_path: Path,
    monkeypatch,
    capsys,
    transport_failure: bool,
) -> None:
    import pytest

    import workday_connect
    import workday_connect_realms as realms
    from workday_connect_store import WorkdayConnectStore

    dev_identity = {
        "environmentId": "dev-environment-id",
        "environmentUrl": "https://contoso-dev.crm.dynamics.com",
        "tenantId": "tenant-id",
        "agentId": "dev-agent-id",
        "agentSchemaName": "gptagent_copilotforemployeeselfservicehr",
        "agentSlug": "ess-hr",
        "almFamilyId": "family-id",
        "commitSha": "dev123",
        "sourceAgentId": "dev-agent-id",
    }
    test_identity = {
        **dev_identity,
        "environmentId": "test-environment-id",
        "environmentUrl": "https://contoso-test.crm.dynamics.com",
        "agentId": "test-agent-id",
        "commitSha": "test123",
    }
    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.record_target_discovery("dev", dev_identity, ring="test")
    store.record_target_discovery("test", test_identity, ring="test")
    store.activate_target("test")
    approved_state = store.load()
    def rediscover(*_args, **_kwargs):
        if transport_failure:
            raise OSError("network unavailable")
        return {**test_identity, "commitSha": "drifted"}, "test"

    monkeypatch.setattr(
        realms,
        "_discover_promoted_realm_identity",
        rediscover,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "workday_connect.py",
            "--root",
            str(tmp_path),
            "runtime-apply",
            "--plan-hash",
            "unused-after-revalidation-failure",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        workday_connect.main()

    assert exc.value.code == 1
    error = capsys.readouterr().err
    expected = (
        "discovery failed before mutation"
        if transport_failure
        else "changed after approval: commitSha"
    )
    assert expected in error
    assert store.load() == approved_state


def test_invalid_validation_retry_preserves_stable_failure_evidence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import pytest

    import workday_connect
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
    ):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    store.set_phase_status(
        "maker-validation",
        "blocked",
        blocker={
            "operation": "record-validation-failure",
            "remediationId": "WD-E2E-006",
            "errorType": "workday-access",
            "failureSurface": "workday-response",
            "message": "Canonical guidance",
            "capturedAt": "2026-09-25T00:00:00Z",
        },
    )
    evidence_file = tmp_path / "invalid-validation.json"
    evidence_file.write_text(
        json.dumps(
            {
                "scenarioName": "Worker profile",
                "testUserCategory": "non-maker employee",
                "outcome": "verified",
                "timestamp": "not-a-timestamp",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "workday_connect.py",
            "--root",
            str(tmp_path),
            "record-validation",
            "--evidence-file",
            str(evidence_file),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        workday_connect.main()

    assert exc.value.code == 1
    blocker = store.load()["phases"]["maker-validation"]["blocker"]
    assert blocker["remediationId"] == "WD-E2E-006"
    assert blocker["failureSurface"] == "workday-response"
    assert blocker["capturedAt"] == "2026-09-25T00:00:00Z"
    assert blocker["operation"] == "record-validation"


def test_non_maker_validation_is_explicitly_post_skill(
    tmp_path: Path,
) -> None:
    import pytest

    import workday_connect
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
    ):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    runtime_plan = {
        "phase": "runtime",
        "scope": {"environmentId": "environment-id"},
        "actions": ["Configure runtime"],
        "flows": [{"name": "REST", "workflowId": "flow-id"}],
    }
    store.approve_plan("runtime", runtime_plan)
    for action in model.PHASE_REQUIRED_ACTIONS["runtime"]:
        evidence = {"outcome": "verified"}
        if action == "flow-attachment-confirmed":
            evidence["flowNames"] = ["REST"]
        store.complete_action(
            "runtime",
            action,
            evidence=evidence,
        )
    store.set_phase_status("runtime", "complete")
    evidence_file = tmp_path / "employee.json"
    evidence_file.write_text(
        json.dumps(
            {
                "testUserCategory": "non-maker employee",
                "timestamp": "2026-10-05T18:00:00-07:00",
                "outcome": "passed",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        workday_connect.WorkdayConnectContractError,
        match="post-skill activity",
    ):
        workday_connect._record_validation(
            SimpleNamespace(evidence_file=evidence_file),
            store,
        )

    state = store.load()
    assert state["status"] == "in-progress"
    assert state["phases"]["maker-validation"]["evidence"] == []
    assert "employeeTestAttempt" not in state["phases"]["maker-validation"]


def test_maker_success_completes_without_run_history_correlation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workday_connect
    import workday_connect_model as model
    from workday_connect_flightcheck import (
        effective_validation_state,
        validation_input_fingerprint,
    )
    from workday_connect_readiness_policy import PROFILE_POLICIES
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
    ):
        if phase_id == "runtime":
            store.approve_plan(
                "runtime",
                {
                    "phase": "runtime",
                    "scope": {"environmentId": "environment-id"},
                    "actions": ["Configure runtime"],
                    "flows": [{"name": "REST", "workflowId": "flow-id"}],
                },
            )
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            evidence = {"outcome": "verified"}
            if action == "flow-attachment-confirmed":
                evidence["flowNames"] = ["REST"]
            store.complete_action(
                phase_id,
                action,
                evidence=evidence,
            )
        store.set_phase_status(phase_id, "complete")
    evidence_file = tmp_path / "maker-validation.json"
    evidence_file.write_text(
        json.dumps(
            {
                "testUserCategory": "maker",
                "timestamp": "2026-10-05T18:00:00-07:00",
                "outcome": "passed",
            }
        ),
        encoding="utf-8",
    )

    def profile_runner(root, state, profile_name, **_kwargs):
        effective_state = effective_validation_state(root, state)
        return {
            "profile": profile_name,
            "sourceProfile": profile_name,
            "schemaVersion": "flightcheck.result.v2",
            "overall": "READY",
            "target": {
                "realm": "dev",
                "environmentId": "environment-id",
                "environmentUrl": "https://example.crm.dynamics.com",
                "tenantId": "tenant-id",
                "agentSlug": "ess-hr",
                "agentSchemaName": "contoso_agent",
                "agentId": "bot-id",
            },
            "inputFingerprint": validation_input_fingerprint(
                effective_state,
                profile_name,
            ),
            "checkpointStatuses": {
                checkpoint_id: "Passed"
                for checkpoint_id in PROFILE_POLICIES[
                    profile_name
                ].checkpoints
            },
            "acceptedSuppressions": [],
            "remediationIds": [],
            "accepted": True,
            "migrationBaseline": False,
        }

    monkeypatch.setattr(
        workday_connect,
        "run_profile",
        profile_runner,
    )

    result = workday_connect._record_validation(
        SimpleNamespace(evidence_file=evidence_file),
        store,
    )

    state = store.load()
    assert result["verified"] is True
    assert result["lifecycleComplete"] is True
    assert result["activeTargetRealm"] == "dev"
    assert result["postSkillNextSteps"] == [
        "Promote the agent from Development to Test when ready.",
        (
            "Return to Connect Workday and say that the agent was promoted "
            "to Test."
        ),
    ]
    assert "non-maker employee" not in " ".join(
        result["postSkillNextSteps"]
    )
    assert state["status"] == "ready"
    assert "employeeTestAttempt" not in state["phases"]["maker-validation"]
    assert set(
        state["phases"]["maker-validation"]["validationProfiles"]
    ) == {
        "workday-da:post-runtime",
        "workday-da:final",
    }
    maker_status = next(
        phase
        for phase in result["status"]["phases"]
        if phase["id"] == "maker-validation"
    )
    assert maker_status["readiness"]["accepted"] is True
    assert maker_status["readiness"]["summary"] == (
        "Maker validation readiness checks passed."
    )
    assert maker_status["readiness"]["validatedAt"]
    evidence = state["phases"]["maker-validation"]["evidence"][0]
    assert evidence["action"] == "maker-smoke-test"
    assert evidence["testUserCategory"] == "maker"
    assert evidence["timestamp"] == "2026-10-06T01:00:00Z"


def test_post_skill_next_steps_are_realm_specific() -> None:
    import workday_connect

    dev_steps = workday_connect._post_skill_next_steps("dev")
    test_steps = workday_connect._post_skill_next_steps("test")
    prod_steps = workday_connect._post_skill_next_steps("prod")

    assert "promoted to Test" in " ".join(dev_steps)
    assert "promoted to Production" in " ".join(test_steps)
    assert "non-maker employee" not in " ".join(dev_steps)
    assert "non-maker employee" not in " ".join(test_steps)
    assert prod_steps == [
        "Publish and deploy the Production agent when ready.",
        (
            "Have each non-maker employee establish their own Workday "
            "connections in Microsoft 365 Chat."
        ),
        (
            "Validate an enabled Workday scenario with the published "
            "Production agent."
        ),
    ]
