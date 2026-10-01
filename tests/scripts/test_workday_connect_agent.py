# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for live native Workday agent completion evidence."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace


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
            f"      dialog: {runtime_schema}\n"
            "    - kind: SendActivity\n"
            "      activity: Welcome\n"
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
    calls = []

    def checkpoint(_root, _state, checkpoint_id, *, preferred_username):
        calls.append((checkpoint_id, preferred_username))
        return "Passed"

    evidence = verify_agent_binding(
        tmp_path,
        _state(),
        checkpoint_verifier=checkpoint,
        client_factory=lambda _config: client,
    )

    assert calls == [
        ("WD-REST-002", "maker@example.com"),
        ("WD-CONN-013", "maker@example.com"),
    ]
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

    assert evidence["checkpoints"] == {}
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

    assert evidence["verifiedComponents"] == 2
    assert evidence["runtimeTemplate"].endswith(
        "WorkdaySystemSetRuntimeTemplateConfigurations"
    )
    assert {item["componentId"] for item in client.expectations} == {
        "conversation-start",
        "user-context-v2",
    }


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
            checkpoint_verifier=lambda *_args, **_kwargs: "Passed",
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
    for action in ("verify-target", "verify-package"):
        store.complete_action(
            "preflight",
            action,
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
    assert status["blocker"]["operation"] == "set-workday-tenant"


def test_controller_records_invocation_only_at_status_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workday_connect
    from workday_connect_store import WorkdayConnectStore

    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
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

    events = WorkdayConnectStore(tmp_path).load()["lifecycle"]["journal"]
    assert [event["event"] for event in events] == ["invoked"]


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
    assert connections["completedActions"] == ["physical-connections-verified"]
    assert connections["evidence"][0]["connectionIds"] == {
        "workday": "workday-id",
        "dataverse": "dataverse-id",
    }


def test_record_connections_previews_before_target_confirmation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workday_connect
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
    assert store.load()["phases"]["connections"]["status"] == "pending"


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
            "checkpoints": {
                "WD-REST-002": "Passed",
                "WD-CONN-013": "Passed",
            },
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
            "checkpoints": {},
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


def test_record_validation_failure_blocks_employee_phase(
    tmp_path: Path,
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
        "runtime",
    ):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    evidence_file = tmp_path / "employee-failure.json"
    evidence_file.write_text(
        json.dumps(
            {
                "remediationId": "WD-E2E-006",
                "timestamp": "2026-09-25T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    result = workday_connect._record_validation_failure(
        SimpleNamespace(evidence_file=evidence_file),
        store,
    )

    assert result["recorded"] is True
    assert result["remediationId"] == "WD-E2E-006"
    phase = store.load()["phases"]["employee-validation"]
    assert phase["status"] == "blocked"
    assert phase["blocker"]["remediationId"] == "WD-E2E-006"
    assert phase["blocker"]["errorType"] == "workday-access"
    assert phase["blocker"]["failureSurface"] == "workday-response"
    assert phase["blocker"]["capturedAt"] == "2026-09-25T00:00:00Z"


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
        "employee-validation",
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
    blocker = store.load()["phases"]["employee-validation"]["blocker"]
    assert blocker["remediationId"] == "WD-E2E-006"
    assert blocker["failureSurface"] == "workday-response"
    assert blocker["capturedAt"] == "2026-09-25T00:00:00Z"
    assert blocker["operation"] == "record-validation"
