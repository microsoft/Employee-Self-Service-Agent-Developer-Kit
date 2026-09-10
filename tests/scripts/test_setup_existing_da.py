# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import agentbuilder
import setup_existing_da


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
TENANT_ID = "00000000-0000-4000-8000-000000009999"
HOST = (
    "https://0000000000004000800000000000111."
    "1.environment.api.test.powerplatform.com"
)
SCHEMA = "gptagent_copilotforemployeeselfservicehr"
FAMILY = "00000000-0000-4000-8000-000000003333"


def _dialog() -> dict[str, Any]:
    return {
        "$kind": "AdaptiveDialog",
        "beginDialog": {
            "$kind": "OnRecognizedIntent",
            "id": "main",
            "actions": [
                {
                    "$kind": "SendActivity",
                    "id": "reply",
                    "activity": {
                        "$kind": "Message",
                        "text": [
                            {
                                "$kind": "TemplateLine",
                                "segments": [
                                    {
                                        "$kind": "TextSegment",
                                        "value": "Hello ",
                                    },
                                    {
                                        "$kind": "ExpressionSegment",
                                        "expression": {
                                            "$kind": "ValueExpression",
                                            "variableReference": "System.User.DisplayName",
                                        },
                                    },
                                ],
                            }
                        ],
                    },
                }
            ],
        },
        "inputType": {"$kind": "Record"},
        "outputType": {"$kind": "Record"},
    }


def _changeset() -> dict[str, Any]:
    return {
        "bot": {
            "$kind": "BotEntity",
            "cdsBotId": AGENT_ID,
            "schemaName": SCHEMA,
        },
        "changeToken": "opaque-token",
        "botComponentChanges": [
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "DialogComponent",
                    "version": 3,
                    "displayName": "Greeting",
                    "id": "00000000-0000-4000-8000-000000004444",
                    "parentBotId": AGENT_ID,
                    "schemaName": f"{SCHEMA}.topic.Greeting",
                    "dialog": _dialog(),
                },
            },
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "GlobalVariableComponent",
                    "version": 1,
                    "id": "00000000-0000-4000-8000-000000005555",
                    "parentBotId": AGENT_ID,
                    "schemaName": f"{SCHEMA}.component.Locale",
                    "variable": {"$kind": "GlobalVariable", "name": "Locale"},
                },
            },
        ],
    }


class FakeClient:
    host = HOST
    ring = "test"
    tenant_id = TENANT_ID
    api_version = "2024-10-01"

    def __init__(
        self,
        *,
        listed: bool = False,
        realm: str = "Dev",
        configured_agent_id: str = AGENT_ID,
        changeset: dict[str, Any] | None = None,
        agent_name: str = "Employee Self-Service HR",
    ) -> None:
        self.listed = listed
        self.list_calls = 0
        self.realm = realm
        self.configured_agent_id = configured_agent_id
        self.changeset = changeset or _changeset()
        self.agent_name = agent_name

    def list_agents(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return [{"botId": AGENT_ID}] if self.listed else []

    def get_agent(self, _agent_id: str) -> dict[str, Any]:
        return {
            "fullBotName": self.agent_name,
            "realm": "dev",
            "schemaName": SCHEMA,
            "managedProperties": {"isManaged": True},
        }

    def get_dev_configuration(self, _agent_id: str) -> dict[str, Any]:
        return {
            "realm": self.realm,
            "cdsBotId": self.configured_agent_id,
            "schemaName": SCHEMA,
            "grsRepositoryId": FAMILY,
            "values": {"mustNotPersist": "sensitive-realm-value"},
        }

    def fetch_components(self, _agent_id: str) -> dict[str, Any]:
        return self.changeset


class FailingFetchClient(FakeClient):
    def fetch_components(self, _agent_id: str) -> dict[str, Any]:
        raise agentbuilder.AgentBuilderError("fetch failed")


class MissingAgentClient(FakeClient):
    def list_agents(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return [
            {
                "botId": "00000000-0000-4000-8000-000000006666",
                "fullBotName": "Another Agent",
            }
        ]

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        if agent_id == "00000000-0000-4000-8000-000000006666":
            return {
                "botId": agent_id,
                "fullBotName": "Another Agent",
                "realm": "dev",
            }
        raise agentbuilder.AgentBuilderHTTPError(
            "Direct agent lookup",
            404,
            error_code="ObjectNotFound",
            request_id="request-1",
        )


class EmptyEnvironmentClient(MissingAgentClient):
    def list_agents(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return []


class ListingOmitsTargetClient(MissingAgentClient):
    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return FakeClient.get_agent(self, agent_id)


class ListingDeniedClient(FakeClient):
    def list_agents(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        raise agentbuilder.AgentBuilderHTTPError(
            "Agent listing",
            403,
            error_code="Forbidden",
        )


def test_connection_iteration_persists_before_acquisition_failure(
    tmp_path: Path,
) -> None:
    with pytest.raises(agentbuilder.AgentBuilderError, match="fetch failed"):
        setup_existing_da.attach_existing_dev(
            FailingFetchClient(),
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            kit_root=tmp_path,
        )

    state = json.loads(
        (
            tmp_path / ".local" / "setup" / "da-connection.json"
        ).read_text(encoding="utf-8")
    )
    assert state["status"] == "connected"
    assert state["environment"] == {
        "id": ENVIRONMENT_ID,
        "tenantId": "00000000-0000-4000-8000-000000009999",
        "powerPlatformApiEndpoint": HOST,
        "ring": "test",
        "apiVersion": "2024-10-01",
    }
    assert state["agent"]["id"] == AGENT_ID
    assert state["agent"]["realm"] == "dev"
    assert state["agent"]["almFamilyId"] == FAMILY
    assert "acquisition" not in state
    assert not (tmp_path / ".local" / "config.json").exists()


def test_status_reports_new_and_validated_resumable_state(
    tmp_path: Path,
) -> None:
    assert setup_existing_da.load_da_connection_state(tmp_path)["status"] == (
        "not-started"
    )
    with pytest.raises(agentbuilder.AgentBuilderError, match="fetch failed"):
        setup_existing_da.attach_existing_dev(
            FailingFetchClient(),
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            kit_root=tmp_path,
        )

    state = setup_existing_da.load_da_connection_state(tmp_path)

    assert state["status"] == "connected"
    assert state["environment"]["id"] == ENVIRONMENT_ID
    assert state["agent"]["id"] == AGENT_ID


def test_status_rejects_corrupt_temporary_state(tmp_path: Path) -> None:
    path = tmp_path / ".local" / "setup" / "da-connection.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "stateKind": "da-existing-dev-connection",
                "status": "workspace-ready",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="missing connection identity",
    ):
        setup_existing_da.load_da_connection_state(tmp_path)


def test_attach_materializes_authorable_topics_and_da_identity(
    tmp_path: Path,
) -> None:
    result = setup_existing_da.attach_existing_dev(
        FakeClient(),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )

    assert result["selectedBy"] == "direct-id-fallback"
    assert result["realm"] == "dev"
    assert result["topicCount"] == 1
    assert result["projectionEngine"] == (
        setup_existing_da.PROJECTION_ENGINE
    )
    assert result["connectionStatus"] == "workspace-ready"
    assert result["workspace"]["status"] == "qualified-complete"
    assert result["workspace"]["unprojectedComponentKinds"] == {
        "GlobalVariableComponent": 1
    }
    workspace = (
        tmp_path
        / "workspace"
        / "agents"
        / "employee-self-service-hr"
    )
    topic = yaml.safe_load(
        (workspace / "topics" / "Greeting.mcs.yml").read_text(
            encoding="utf-8"
        )
    )
    assert topic["kind"] == "AdaptiveDialog"
    assert topic["beginDialog"]["actions"][0]["activity"] == (
        "Hello {System.User.DisplayName}"
    )
    assert (workspace / ".baseline" / "topics" / "Greeting.mcs.yml").is_file()
    raw = json.loads(
        (workspace / ".agentbuilder" / "components.json").read_text(
            encoding="utf-8"
        )
    )
    assert raw["changeToken"] == "opaque-token"

    config = json.loads(
        (tmp_path / ".local" / "config.json").read_text(encoding="utf-8")
    )
    assert "dataverseEndpoint" not in config
    assert config["releaseLine"] == "da"
    assert config["transport"] == "agentbuilder"
    assert config["agent"]["realm"] == "dev"
    assert config["agent"]["almFamilyId"] == FAMILY
    assert config["agent"]["environmentId"] == ENVIRONMENT_ID
    assert config["agent"]["agentBuilderChangeSetPath"].endswith(
        ".agentbuilder/components.json"
    )
    attach_metadata = (
        workspace / ".agentbuilder" / "attach.json"
    ).read_text(encoding="utf-8")
    assert "mustNotPersist" not in attach_metadata
    assert "sensitive-realm-value" not in attach_metadata
    connection = json.loads(
        (
            tmp_path / ".local" / "setup" / "da-connection.json"
        ).read_text(encoding="utf-8")
    )
    assert connection["status"] == "workspace-ready"
    assert connection["acquisition"]["status"] == "acquired"
    assert connection["workspace"]["status"] == "qualified-complete"
    assert connection["workspace"]["projectedComponentKinds"] == [
        "DialogComponent"
    ]
    assert connection["workspace"]["unprojectedComponentKinds"] == {
        "GlobalVariableComponent": 1
    }
    assert connection["workspace"]["unprojectedDialogCount"] == 0
    raw_cache = json.loads(
        (
            tmp_path / ".local" / "setup" / "da-components.json"
        ).read_text(encoding="utf-8")
    )
    assert raw_cache["changeToken"] == "opaque-token"


def test_canonical_converter_materializes_task_dialog_and_skips_failure(
    tmp_path: Path,
) -> None:
    changeset = _changeset()
    changeset["botComponentChanges"].extend(
        [
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "DialogComponent",
                    "version": 1,
                    "displayName": "ESS HR GA Import Aug27",
                    "id": "00000000-0000-4000-8000-000000007777",
                    "parentBotId": AGENT_ID,
                    "schemaName": (
                        "gptagent_copilotforemployeeselfservicecore."
                        "InvokeConnectedAgentTaskAction.ESSHRGAImportAug27"
                    ),
                    "dialog": {
                        "$kind": "TaskDialog",
                        "modelDisplayName": "ESS HR GA Import Aug27",
                        "modelDescription": (
                            "Built using Microsoft Copilot Studio"
                        ),
                        "action": {
                            "$kind": "InvokeConnectedAgentTaskAction",
                            "botSchemaName": (
                                "gptagent_"
                                "copilotforemployeeselfservicehr"
                            ),
                        },
                    },
                },
            },
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "DialogComponent",
                    "version": 1,
                    "displayName": "Internal dialog record",
                    "id": "00000000-0000-4000-8000-000000008888",
                    "parentBotId": AGENT_ID,
                    "schemaName": f"{SCHEMA}.topic.InternalRecord",
                    "dialog": {"$kind": "NonAdaptiveDialog"},
                },
            },
        ]
    )

    result = setup_existing_da.attach_existing_dev(
        FakeClient(changeset=changeset),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )

    assert result["topicCount"] == 2
    assert result["projectionEngine"] == (
        setup_existing_da.PROJECTION_ENGINE
    )
    assert result["workspace"]["unprojectedDialogCount"] == 1
    unavailable = result["unprojectedDialogs"][0]
    assert unavailable["schemaName"] == f"{SCHEMA}.topic.InternalRecord"
    assert unavailable["displayName"] == "Internal dialog record"
    assert unavailable["dialogKind"] == "NonAdaptiveDialog"
    assert unavailable["reason"] == "object-model-conversion-failed"
    assert unavailable["detail"]
    workspace = (
        tmp_path
        / "workspace"
        / "agents"
        / "employee-self-service-hr"
    )
    task_dialog = yaml.safe_load(
        (
            workspace / "topics" / "ESSHRGAImportAug27.mcs.yml"
        ).read_text(encoding="utf-8")
    )
    assert task_dialog == {
        "kind": "TaskDialog",
        "modelDisplayName": "ESS HR GA Import Aug27",
        "modelDescription": "Built using Microsoft Copilot Studio",
        "action": {
            "kind": "InvokeConnectedAgentTaskAction",
            "botSchemaName": (
                "gptagent_copilotforemployeeselfservicehr"
            ),
        },
    }
    raw = json.loads(
        (workspace / setup_existing_da.RAW_CHANGESET).read_text(
            encoding="utf-8"
        )
    )
    assert raw == changeset
    snapshot = (workspace / "snapshot.md").read_text(encoding="utf-8")
    assert "## Unavailable dialog components" in snapshot
    assert "Internal dialog record (`NonAdaptiveDialog`)" in snapshot


def test_all_dialog_conversion_failures_remain_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_conversion(
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "key": item["key"],
                "success": False,
                "error": {"message": "unsupported adaptive node"},
            }
            for item in items
        ]

    monkeypatch.setattr(
        setup_existing_da,
        "object_models_to_yaml",
        fail_conversion,
    )

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="could not materialize any authorable dialog",
    ):
        setup_existing_da.attach_existing_dev(
            FakeClient(),
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            kit_root=tmp_path,
        )


def test_url_selected_agent_uses_listing_only_as_diagnostic(
    tmp_path: Path,
) -> None:
    client = FakeClient()

    result = setup_existing_da.attach_existing_dev(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
        selection_source="copilot-studio-url",
    )

    assert client.list_calls == 1
    assert result["selectedBy"] == "copilot-studio-url"
    state = json.loads(
        (
            tmp_path / ".local" / "setup" / "da-connection.json"
        ).read_text(encoding="utf-8")
    )
    assert state["selectedBy"] == "copilot-studio-url"


def test_listing_failure_does_not_block_direct_agent_validation(
    tmp_path: Path,
) -> None:
    client = ListingDeniedClient()

    result = setup_existing_da.attach_existing_dev(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
        selection_source="copilot-studio-url",
    )

    assert client.list_calls == 1
    assert result["selectedBy"] == "copilot-studio-url"


def test_listing_omission_does_not_block_direct_agent_validation(
    tmp_path: Path,
) -> None:
    client = ListingOmitsTargetClient()

    result = setup_existing_da.attach_existing_dev(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
        selection_source="copilot-studio-url",
    )

    assert client.list_calls == 1
    assert result["agentId"] == AGENT_ID
    assert result["selectedBy"] == "copilot-studio-url"


def test_missing_direct_agent_reports_accessible_environment_agents() -> None:
    with pytest.raises(
        setup_existing_da.ExistingDAAgentNotFound,
        match="target environment is accessible",
    ) as error:
        setup_existing_da.validate_existing_dev_connection(
            MissingAgentClient(),
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            selection_source="copilot-studio-url",
        )

    diagnostic = error.value.diagnostic()
    assert diagnostic == {
        "environmentStatus": "accessible",
        "agentStatus": "not-found",
        "tenantId": TENANT_ID,
        "targetListed": False,
        "excludedNonDevCount": 0,
        "unverifiedAgentCount": 0,
        "agents": [
            {
                "id": "00000000-0000-4000-8000-000000006666",
                "name": "Another Agent",
            }
        ],
    }


def test_missing_direct_agent_reports_empty_accessible_environment() -> None:
    with pytest.raises(
        setup_existing_da.ExistingDAAgentNotFound,
    ) as error:
        setup_existing_da.validate_existing_dev_connection(
            EmptyEnvironmentClient(),
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            selection_source="copilot-studio-url",
        )

    assert error.value.diagnostic()["agents"] == []
    assert error.value.diagnostic()["environmentStatus"] == "accessible"
    assert error.value.diagnostic()["excludedNonDevCount"] == 0


def test_dev_agent_inspection_filters_other_realms() -> None:
    class MixedRealmClient(FakeClient):
        def list_agents(self) -> list[dict[str, Any]]:
            return [
                {
                    "botId": AGENT_ID,
                    "fullBotName": "Dev agent",
                },
                {
                    "botId": "00000000-0000-4000-8000-000000006666",
                    "fullBotName": "Test agent",
                },
                {
                    "botId": "00000000-0000-4000-8000-000000007777",
                    "fullBotName": "Unspecified agent",
                },
            ]

        def get_agent(self, agent_id: str) -> dict[str, Any]:
            realms = {
                AGENT_ID: "dev",
                "00000000-0000-4000-8000-000000006666": "test",
                "00000000-0000-4000-8000-000000007777": None,
            }
            return {
                "botId": agent_id,
                "fullBotName": f"Resolved {agent_id[-4:]}",
                "realm": realms[agent_id],
            }

    inspection = setup_existing_da.inspect_dev_agents(MixedRealmClient())

    assert setup_existing_da.summarize_agents(
        inspection["devAgents"]
    ) == [{"id": AGENT_ID, "name": "Resolved 2222"}]
    assert inspection["excludedNonDevCount"] == 2
    assert inspection["unverifiedAgentCount"] == 0


def test_list_agents_command_returns_only_verified_dev_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class MixedRealmClient(FakeClient):
        def list_agents(self) -> list[dict[str, Any]]:
            return [
                {"botId": AGENT_ID, "fullBotName": "Editable Dev"},
                {
                    "botId": "00000000-0000-4000-8000-000000006666",
                    "fullBotName": "Published Test",
                },
            ]

        def get_agent(self, agent_id: str) -> dict[str, Any]:
            return {
                "botId": agent_id,
                "fullBotName": (
                    "Editable Dev" if agent_id == AGENT_ID else "Published Test"
                ),
                "realm": "dev" if agent_id == AGENT_ID else "test",
            }

    monkeypatch.setattr(
        setup_existing_da,
        "_client_from_args",
        lambda *_args: MixedRealmClient(),
    )

    result = setup_existing_da.main(
        [
            "list-agents",
            "--target-url",
            "https://copilotstudio.test.microsoft.com/environments/"
            f"{ENVIRONMENT_ID}/home",
            "--kit-root",
            str(tmp_path),
        ]
    )

    payload = json.loads(
        capsys.readouterr().out.split("DA_AGENT_LIST_JSON:", 1)[1]
    )
    assert result == 0
    assert payload["agents"] == [
        {"id": AGENT_ID, "name": "Editable Dev"}
    ]
    assert payload["excludedNonDevCount"] == 1
    assert payload["unverifiedAgentCount"] == 0


def test_attach_command_emits_environment_agent_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_existing_da,
        "_client_from_args",
        lambda *_args: MissingAgentClient(),
    )

    result = setup_existing_da.main(
        [
            "attach",
            "--target-url",
            "https://copilotstudio.test.microsoft.com/environments/"
            f"{ENVIRONMENT_ID}/copilots/{AGENT_ID}/details",
            "--kit-root",
            str(tmp_path),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    diagnostic = json.loads(
        captured.out.split("DA_EXISTING_DEV_DIAGNOSTIC_JSON:", 1)[1]
    )
    assert diagnostic["environmentStatus"] == "accessible"
    assert diagnostic["agentStatus"] == "not-found"
    assert diagnostic["agents"][0]["name"] == "Another Agent"
    assert "target environment is accessible" in captured.err
    assert not (tmp_path / ".local" / "setup").exists()


def test_identical_rerun_resumes_without_overwriting_local_topic(
    tmp_path: Path,
) -> None:
    client = FakeClient(listed=True)
    setup_existing_da.attach_existing_dev(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )
    topic_path = (
        tmp_path
        / "workspace"
        / "agents"
        / "employee-self-service-hr"
        / "topics"
        / "Greeting.mcs.yml"
    )
    topic_path.write_text("local customization\n", encoding="utf-8")

    result = setup_existing_da.attach_existing_dev(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )

    assert result["status"] == "resumed"
    assert result["selectedBy"] == "list"
    assert topic_path.read_text(encoding="utf-8") == "local customization\n"


def test_rerun_ignores_change_token_and_top_level_change_order(
    tmp_path: Path,
) -> None:
    setup_existing_da.attach_existing_dev(
        FakeClient(),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )
    reordered = _changeset()
    reordered["changeToken"] = "different-opaque-token"
    reordered["botComponentChanges"].reverse()

    result = setup_existing_da.attach_existing_dev(
        FakeClient(changeset=reordered),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )

    assert result["status"] == "resumed"
    state = json.loads(
        (
            tmp_path / ".local" / "setup" / "da-connection.json"
        ).read_text(encoding="utf-8")
    )
    assert state["status"] == "workspace-ready"


def test_rerun_ignores_expanded_literal_activity_wire_shape(
    tmp_path: Path,
) -> None:
    shorthand = _changeset()
    shorthand["botComponentChanges"][0]["component"]["dialog"][
        "beginDialog"
    ]["actions"][0]["activity"] = "Hello"
    setup_existing_da.attach_existing_dev(
        FakeClient(changeset=shorthand),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )
    topic_path = (
        tmp_path
        / "workspace"
        / "agents"
        / "employee-self-service-hr"
        / "topics"
        / "Greeting.mcs.yml"
    )
    topic_path.write_text("local customization\n", encoding="utf-8")

    expanded = json.loads(json.dumps(shorthand))
    expanded["botComponentChanges"][0]["component"]["dialog"][
        "beginDialog"
    ]["actions"][0]["activity"] = {
        "$kind": "Message",
        "text": [
            {
                "$kind": "TemplateLine",
                "segments": [
                    {
                        "$kind": "TextSegment",
                        "value": "Hello",
                    }
                ],
            }
        ],
    }
    result = setup_existing_da.attach_existing_dev(
        FakeClient(changeset=expanded),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )

    assert result["status"] == "resumed"
    assert topic_path.read_text(encoding="utf-8") == "local customization\n"


def test_agent_rename_keeps_stable_workspace_identity(
    tmp_path: Path,
) -> None:
    setup_existing_da.attach_existing_dev(
        FakeClient(),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )

    result = setup_existing_da.attach_existing_dev(
        FakeClient(agent_name="Renamed employee agent"),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )

    assert result["status"] == "resumed"
    assert (
        tmp_path
        / "workspace"
        / "agents"
        / "employee-self-service-hr"
    ).is_dir()
    assert not (
        tmp_path / "workspace" / "agents" / "renamed-employee-agent"
    ).exists()
    config = json.loads(
        (tmp_path / ".local" / "config.json").read_text(encoding="utf-8")
    )
    assert config["agent"]["name"] == "Renamed employee agent"
    assert len(config["agents"]) == 1


def test_changed_remote_content_requires_explicit_repair(
    tmp_path: Path,
) -> None:
    setup_existing_da.attach_existing_dev(
        FakeClient(),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )
    state_path = tmp_path / ".local" / "setup" / "da-connection.json"
    raw_path = tmp_path / ".local" / "setup" / "da-components.json"
    previous_state = json.loads(state_path.read_text(encoding="utf-8"))
    previous_raw = raw_path.read_text(encoding="utf-8")
    changed = _changeset()
    changed["changeToken"] = "changed"
    changed_dialog = changed["botComponentChanges"][0]["component"]["dialog"]
    changed_dialog["beginDialog"]["actions"][0]["activity"]["text"][0][
        "segments"
    ][0]["value"] = "Updated "

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="explicit refresh",
    ):
        setup_existing_da.attach_existing_dev(
            FakeClient(changeset=changed),
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            kit_root=tmp_path,
        )

    current_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert current_state["status"] == "workspace-ready"
    assert current_state["acquisition"] == previous_state["acquisition"]
    assert current_state["workspace"] == previous_state["workspace"]
    assert raw_path.read_text(encoding="utf-8") == previous_raw


def test_explicit_refresh_checkpoints_then_replaces_workspace(
    tmp_path: Path,
) -> None:
    setup_existing_da.attach_existing_dev(
        FakeClient(),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )
    workspace = (
        tmp_path
        / "workspace"
        / "agents"
        / "employee-self-service-hr"
    )
    topic_path = workspace / "topics" / "Greeting.mcs.yml"
    topic_path.write_text("local customization\n", encoding="utf-8")
    changed = _changeset()
    changed["changeToken"] = "changed"
    changed_dialog = changed["botComponentChanges"][0]["component"]["dialog"]
    changed_dialog["beginDialog"]["actions"][0]["activity"]["text"][0][
        "segments"
    ][0]["value"] = "Updated "

    result = setup_existing_da.attach_existing_dev(
        FakeClient(changeset=changed),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
        refresh=True,
    )

    assert result["status"] == "refreshed"
    assert result["checkpoint"] == 1
    assert "Updated {System.User.DisplayName}" in topic_path.read_text(
        encoding="utf-8"
    )
    assert (
        workspace
        / ".checkpoints"
        / "1"
        / "topics"
        / "Greeting.mcs.yml"
    ).read_text(encoding="utf-8") == "local customization\n"
    assert (
        workspace
        / ".baseline"
        / "topics"
        / "Greeting.mcs.yml"
    ).read_text(encoding="utf-8") == topic_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("realm", "configured_agent_id", "message"),
    [
        ("Prod", AGENT_ID, "realm"),
        (
            "Dev",
            "00000000-0000-4000-8000-000000009999",
            "different agent identity",
        ),
    ],
)
def test_attach_rejects_non_dev_or_mismatched_identity(
    tmp_path: Path,
    realm: str,
    configured_agent_id: str,
    message: str,
) -> None:
    with pytest.raises(setup_existing_da.ExistingDASetupError, match=message):
        setup_existing_da.attach_existing_dev(
            FakeClient(
                realm=realm,
                configured_agent_id=configured_agent_id,
            ),
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            kit_root=tmp_path,
        )


def test_attach_rejects_changeset_for_another_agent(
    tmp_path: Path,
) -> None:
    changeset = _changeset()
    changeset["bot"]["cdsBotId"] = (
        "00000000-0000-4000-8000-000000009999"
    )

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="different agent",
    ):
        setup_existing_da.attach_existing_dev(
            FakeClient(changeset=changeset),
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            kit_root=tmp_path,
        )


def test_agent_choices_use_display_names_without_product_labels() -> None:
    choices = setup_existing_da.summarize_agents(
        [
            {
                "botId": AGENT_ID,
                "fullBotName": "Customized employee agent",
                "outlineIcon": "large-image",
            },
            {
                "botId": "not-a-guid",
                "fullBotName": "Invalid card",
            },
        ]
    )

    assert choices == [
        {
            "id": AGENT_ID,
            "name": "Customized employee agent",
        }
    ]
    assert all("product" not in choice for choice in choices)


def test_parser_defaults_to_prod_ring_for_external_setup() -> None:
    args = setup_existing_da.build_parser().parse_args(
        [
            "list-agents",
            "--environment-id",
            ENVIRONMENT_ID,
            "--tenant-id",
            "00000000-0000-4000-8000-000000009999",
        ]
    )

    target = setup_existing_da.resolve_da_target(
        target_url=args.target_url,
        environment_id=args.environment_id,
        ring=args.ring,
    )

    assert args.ring is None
    assert target["ring"] == "prod"
    assert args.api_version == "2024-10-01"


@pytest.mark.parametrize("resource_name", ["bots", "copilots"])
def test_copilot_studio_url_resolves_environment_and_agent(
    resource_name: str,
) -> None:
    target = setup_existing_da.parse_da_target_url(
        "https://copilotstudio.microsoft.com/environments/"
        f"Default-{ENVIRONMENT_ID}/{resource_name}/{AGENT_ID}/overview"
    )

    assert target == {
        "environmentId": ENVIRONMENT_ID,
        "agentId": AGENT_ID,
        "source": "copilot-studio-url",
        "ring": "prod",
    }


def test_test_copilot_studio_url_selects_test_ring() -> None:
    target = setup_existing_da.resolve_da_target(
        target_url=(
            "https://copilotstudio.test.microsoft.com/environments/"
            f"{ENVIRONMENT_ID}/copilots/{AGENT_ID}/details"
        ),
        environment_id=None,
        require_agent=True,
    )

    assert target["environmentId"] == ENVIRONMENT_ID
    assert target["agentId"] == AGENT_ID
    assert target["ring"] == "test"
    assert target["agentSelection"] == "copilot-studio-url"


def test_target_rejects_ring_conflicting_with_url() -> None:
    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="different service rings",
    ):
        setup_existing_da.resolve_da_target(
            target_url=(
                "https://copilotstudio.test.microsoft.com/environments/"
                f"{ENVIRONMENT_ID}/copilots/{AGENT_ID}/details"
            ),
            environment_id=None,
            ring="prod",
        )


def test_power_apps_url_resolves_resource_tokens() -> None:
    target = setup_existing_da.parse_da_target_url(
        "https://make.powerapps.com/environments/"
        f"{ENVIRONMENT_ID}/bots/{AGENT_ID}"
    )

    assert target == {
        "environmentId": ENVIRONMENT_ID,
        "agentId": AGENT_ID,
        "source": "power-apps-url",
    }


def test_target_extraction_does_not_require_a_url_contract() -> None:
    target = setup_existing_da.parse_da_target_url(
        "Copied from HTTP://user:password@"
        "COPILOTSTUDIO.TEST.MICROSOFT.COM:123/"
        f"environments/Default-{ENVIRONMENT_ID}/"
        f"copilots/{AGENT_ID}/details?source=chat#selection"
    )

    assert target == {
        "environmentId": ENVIRONMENT_ID,
        "agentId": AGENT_ID,
        "source": "copilot-studio-url",
        "ring": "test",
    }


def test_target_extraction_accepts_unknown_surrounding_location() -> None:
    target = setup_existing_da.parse_da_target_url(
        "https://example.com/context/environments/"
        f"{ENVIRONMENT_ID}/bots/{AGENT_ID}/overview"
    )

    assert target == {
        "environmentId": ENVIRONMENT_ID,
        "agentId": AGENT_ID,
        "source": "provided-target",
    }


def test_target_requires_an_extractable_environment() -> None:
    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="does not identify an environment",
    ):
        setup_existing_da.resolve_da_target(
            target_url=(
                "copilotstudio.microsoft.com without a resource identifier"
            ),
            environment_id=None,
        )


def test_unknown_target_location_defaults_to_prod() -> None:
    target = setup_existing_da.resolve_da_target(
        target_url=(
            "copied environments/"
            f"{ENVIRONMENT_ID}/copilots/{AGENT_ID}"
        ),
        environment_id=None,
        require_agent=True,
    )

    assert target["ring"] == "prod"
    assert target["agentSelection"] == "provided-target"


def test_target_location_is_not_used_as_api_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, str] = {}
    expected_host = HOST.replace(
        ".environment.api.test.powerplatform.com",
        ".environment.api.powerplatform.com",
    )

    def fake_derive(environment_id: str, ring: str) -> str:
        observed.update(environment_id=environment_id, ring=ring)
        return expected_host

    monkeypatch.setattr(
        setup_existing_da,
        "derive_environment_host",
        fake_derive,
    )
    monkeypatch.setattr(
        setup_existing_da,
        "authenticate",
        lambda *_args, **_kwargs: "selected-token",
    )
    args = setup_existing_da.build_parser().parse_args(
        [
            "attach",
            "--target-url",
            "https://unrelated.example/environments/"
            f"{ENVIRONMENT_ID}/copilots/{AGENT_ID}",
            "--kit-root",
            str(tmp_path),
        ]
    )
    target = setup_existing_da.resolve_da_target(
        target_url=args.target_url,
        environment_id=args.environment_id,
        agent_id=args.agent_id,
        ring=args.ring,
        require_agent=True,
    )

    client = setup_existing_da._client_from_args(
        args,
        target["environmentId"],
        target["ring"],
    )

    assert client.host == expected_host
    assert observed == {
        "environment_id": ENVIRONMENT_ID,
        "ring": "prod",
    }


def test_explicit_identifiers_repair_missing_target_tokens() -> None:
    target = setup_existing_da.resolve_da_target(
        target_url=(
            "copilotstudio.test.microsoft.com/environments/not-a-guid"
        ),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
    )

    assert target["environmentId"] == ENVIRONMENT_ID
    assert target["agentId"] == AGENT_ID
    assert target["ring"] == "test"
    assert target["agentSelection"] == "direct-id-fallback"


def test_target_rejects_conflicting_explicit_identity() -> None:
    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="different environments",
    ):
        setup_existing_da.resolve_da_target(
            target_url=(
                "https://copilotstudio.microsoft.com/environments/"
                f"{ENVIRONMENT_ID}/bots/{AGENT_ID}/overview"
            ),
            environment_id="00000000-0000-4000-8000-000000009999",
        )


def test_target_rejects_conflicting_explicit_agent() -> None:
    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="different agents",
    ):
        setup_existing_da.resolve_da_target(
            target_url=(
                "copilotstudio.microsoft.com/environments/"
                f"{ENVIRONMENT_ID}/bots/{AGENT_ID}"
            ),
            environment_id=None,
            agent_id="00000000-0000-4000-8000-000000009999",
        )


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("Environment ID", {"environment_id": "not-a-guid"}),
        (
            "Agent ID",
            {
                "environment_id": ENVIRONMENT_ID,
                "agent_id": "not-a-guid",
            },
        ),
    ],
)
def test_explicit_target_identifiers_still_require_guids(
    field: str,
    kwargs: dict[str, str],
) -> None:
    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match=rf"{field} must be a GUID",
    ):
        setup_existing_da.resolve_da_target(
            target_url=None,
            **kwargs,
        )


def test_attach_parser_accepts_url_without_tenant_or_explicit_ids() -> None:
    args = setup_existing_da.build_parser().parse_args(
        [
            "attach",
            "--target-url",
            "https://copilotstudio.microsoft.com/environments/"
            f"{ENVIRONMENT_ID}/bots/{AGENT_ID}/overview",
        ]
    )

    target = setup_existing_da.resolve_da_target(
        target_url=args.target_url,
        environment_id=args.environment_id,
        agent_id=args.agent_id,
        ring=args.ring,
        require_agent=True,
    )

    assert target["environmentId"] == ENVIRONMENT_ID
    assert target["agentId"] == AGENT_ID
    assert target["agentSelection"] == "copilot-studio-url"
    assert args.tenant_id is None
    assert args.select_account is False
    assert target["ring"] == "prod"
    assert args.ring is None


def test_attach_parser_accepts_forced_account_selection() -> None:
    args = setup_existing_da.build_parser().parse_args(
        [
            "attach",
            "--target-url",
            "https://copilotstudio.microsoft.com/environments/"
            f"{ENVIRONMENT_ID}/bots/{AGENT_ID}/overview",
            "--tenant-id",
            "00000000-0000-4000-8000-000000009999",
            "--select-account",
        ]
    )

    assert args.select_account is True


def test_targeted_client_forces_account_selection_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_authenticate(
        tenant_id,
        ring,
        *,
        cache_path,
        force_account_selection,
    ):
        observed.update(
            tenant_id=tenant_id,
            ring=ring,
            cache_path=cache_path,
            force_account_selection=force_account_selection,
        )
        return "selected-token"

    monkeypatch.setattr(
        setup_existing_da,
        "authenticate",
        fake_authenticate,
    )
    monkeypatch.setattr(
        setup_existing_da,
        "derive_environment_host",
        lambda _environment_id, _ring: HOST,
    )
    args = setup_existing_da.build_parser().parse_args(
        [
            "attach",
            "--environment-id",
            ENVIRONMENT_ID,
            "--agent-id",
            AGENT_ID,
            "--ring",
            "test",
            "--tenant-id",
            "00000000-0000-4000-8000-000000009999",
            "--select-account",
            "--kit-root",
            str(tmp_path),
        ]
    )

    client = setup_existing_da._client_from_args(
        args,
        ENVIRONMENT_ID,
        "test",
    )

    assert client.tenant_id == "00000000-0000-4000-8000-000000009999"
    assert observed == {
        "tenant_id": "00000000-0000-4000-8000-000000009999",
        "ring": "test",
        "cache_path": (
            tmp_path.resolve()
            / ".local"
            / ".agentbuilder_token_cache.bin"
        ),
        "force_account_selection": True,
    }


def test_organization_summary_uses_friendly_names_and_domains() -> None:
    organizations = setup_existing_da.summarize_organizations(
        [
            {
                "tenantId": "00000000-0000-4000-8000-000000002222",
                "displayName": "Fabrikam",
                "defaultDomain": "fabrikam.onmicrosoft.com",
            },
            {
                "tenantId": "00000000-0000-4000-8000-000000001111",
                "displayName": "Contoso",
                "defaultDomain": "contoso.onmicrosoft.com",
            },
        ]
    )

    assert organizations == [
        {
            "id": "00000000-0000-4000-8000-000000001111",
            "name": "Contoso",
            "domain": "contoso.onmicrosoft.com",
        },
        {
            "id": "00000000-0000-4000-8000-000000002222",
            "name": "Fabrikam",
            "domain": "fabrikam.onmicrosoft.com",
        },
    ]


def test_organization_summary_rejects_invalid_picker_records() -> None:
    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="Tenant ID must be a GUID",
    ):
        setup_existing_da.summarize_organizations(
            [
                {
                    "tenantId": "not-a-guid",
                    "displayName": "Invalid",
                }
            ]
        )


def test_environment_summary_uses_safe_picker_fields() -> None:
    environments = setup_existing_da.summarize_environments(
        [
            {
                "id": "00000000-0000-4000-8000-000000006666",
                "displayName": "Zeta",
                "url": "https://internal.example",
            },
            {
                "id": ENVIRONMENT_ID,
                "displayName": "Alpha",
            },
        ]
    )

    assert environments == [
        {"id": ENVIRONMENT_ID, "name": "Alpha"},
        {
            "id": "00000000-0000-4000-8000-000000006666",
            "name": "Zeta",
        },
    ]


def test_list_environments_uses_url_ring_and_agentbuilder_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, Any] = {}

    def fake_authenticate(
        tenant_id: str,
        ring: str,
        *,
        cache_path: Path,
        force_account_selection: bool,
    ) -> str:
        observed.update(
            {
                "tenant_id": tenant_id,
                "ring": ring,
                "cache_path": cache_path,
                "force_account_selection": force_account_selection,
            }
        )
        return "agentbuilder-token"

    def fake_list_environments(
        token: str,
        ring: str,
        *,
        api_version: str,
    ) -> list[dict[str, str]]:
        observed.update(
            {
                "token": token,
                "inventory_ring": ring,
                "api_version": api_version,
            }
        )
        return [
            {
                "id": "00000000-0000-4000-8000-000000006666",
                "displayName": "Another Environment",
            }
        ]

    monkeypatch.setattr(setup_existing_da, "authenticate", fake_authenticate)
    monkeypatch.setattr(
        setup_existing_da,
        "list_agentbuilder_environments",
        fake_list_environments,
    )

    result = setup_existing_da.main(
        [
            "list-environments",
            "--target-url",
            "https://copilotstudio.test.microsoft.com/environments/"
            f"{ENVIRONMENT_ID}/home",
            "--tenant-id",
            TENANT_ID,
            "--kit-root",
            str(tmp_path),
        ]
    )

    payload = json.loads(
        capsys.readouterr().out.split("DA_ENVIRONMENT_LIST_JSON:", 1)[1]
    )
    assert result == 0
    assert payload == {
        "tenantId": TENANT_ID,
        "ring": "test",
        "currentEnvironmentId": ENVIRONMENT_ID,
        "environments": [
            {
                "id": "00000000-0000-4000-8000-000000006666",
                "name": "Another Environment",
            }
        ],
    }
    assert observed == {
        "tenant_id": TENANT_ID,
        "ring": "test",
        "cache_path": (
            tmp_path.resolve()
            / ".local"
            / ".agentbuilder_token_cache.bin"
        ),
        "force_account_selection": False,
        "token": "agentbuilder-token",
        "inventory_ring": "test",
        "api_version": "2024-10-01",
    }


def test_list_organizations_command_returns_picker_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, Any] = {}

    class FakeAzureArmClient:
        def __init__(self, tenant_id, *, cache_path) -> None:
            observed["tenant_id"] = tenant_id
            observed["cache_path"] = cache_path

        def authenticate(self, *, force_account_selection: bool) -> str:
            observed["force_account_selection"] = force_account_selection
            return "arm-token"

        def list_tenants(self) -> list[dict[str, str]]:
            return [
                {
                    "tenantId": "00000000-0000-4000-8000-000000001111",
                    "displayName": "Contoso",
                    "defaultDomain": "contoso.onmicrosoft.com",
                }
            ]

    monkeypatch.setattr(
        setup_existing_da,
        "AzureArmClient",
        FakeAzureArmClient,
    )

    assert setup_existing_da.main(
        [
            "list-organizations",
            "--kit-root",
            str(tmp_path),
        ]
    ) == 0

    output = capsys.readouterr().out
    payload = json.loads(output.split("DA_ORGANIZATION_LIST_JSON:", 1)[1])
    assert payload["organizations"] == [
        {
            "id": "00000000-0000-4000-8000-000000001111",
            "name": "Contoso",
            "domain": "contoso.onmicrosoft.com",
        }
    ]
    assert observed == {
        "tenant_id": "organizations",
        "cache_path": (
            tmp_path.resolve()
            / ".local"
            / ".organization_token_cache.bin"
        ),
        "force_account_selection": True,
    }


def test_status_parser_does_not_require_connection_arguments() -> None:
    args = setup_existing_da.build_parser().parse_args(["status"])

    assert args.command == "status"


def test_list_organizations_parser_does_not_require_target_arguments() -> None:
    args = setup_existing_da.build_parser().parse_args(
        ["list-organizations"]
    )

    assert args.command == "list-organizations"


def test_list_environments_parser_accepts_ring_source_url() -> None:
    args = setup_existing_da.build_parser().parse_args(
        [
            "list-environments",
            "--target-url",
            "https://copilotstudio.test.microsoft.com/environments/"
            f"{ENVIRONMENT_ID}/home",
        ]
    )

    assert args.command == "list-environments"
    assert args.target_url.endswith(f"/environments/{ENVIRONMENT_ID}/home")


@pytest.mark.parametrize(
    ("state_path", "payload"),
    [
        (
            ".local/setup/config.json",
            {"schema_version": 2},
        ),
        (
            ".local/config.json",
            {"configVersion": 1, "dataverseEndpoint": "https://example"},
        ),
    ],
)
def test_da_connection_rejects_another_platform_workspace(
    tmp_path: Path,
    state_path: str,
    payload: dict[str, Any],
) -> None:
    path = tmp_path / state_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="another platform|non-DA",
    ):
        setup_existing_da.attach_existing_dev(
            FakeClient(),
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            kit_root=tmp_path,
        )
