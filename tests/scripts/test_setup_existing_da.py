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
    tenant_id = "00000000-0000-4000-8000-000000009999"
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
    raw_cache = json.loads(
        (
            tmp_path / ".local" / "setup" / "da-components.json"
        ).read_text(encoding="utf-8")
    )
    assert raw_cache["changeToken"] == "opaque-token"


def test_url_selected_agent_skips_non_authoritative_listing(
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

    assert client.list_calls == 0
    assert result["selectedBy"] == "copilot-studio-url"
    state = json.loads(
        (
            tmp_path / ".local" / "setup" / "da-connection.json"
        ).read_text(encoding="utf-8")
    )
    assert state["selectedBy"] == "copilot-studio-url"


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


def test_power_apps_url_resolves_environment_without_agent() -> None:
    target = setup_existing_da.parse_da_target_url(
        "https://make.powerapps.com/environments/"
        f"{ENVIRONMENT_ID}/bots/{AGENT_ID}"
    )

    assert target == {
        "environmentId": ENVIRONMENT_ID,
        "source": "power-apps-url",
    }


@pytest.mark.parametrize(
    "target_url",
    [
        f"http://copilotstudio.microsoft.com/environments/{ENVIRONMENT_ID}",
        f"https://example.com/environments/{ENVIRONMENT_ID}",
        "https://copilotstudio.microsoft.com/",
    ],
)
def test_da_target_url_rejects_untrusted_or_incomplete_urls(
    target_url: str,
) -> None:
    with pytest.raises(setup_existing_da.ExistingDASetupError):
        setup_existing_da.parse_da_target_url(target_url)


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
    assert target["ring"] == "prod"
    assert args.ring is None


def test_status_parser_does_not_require_connection_arguments() -> None:
    args = setup_existing_da.build_parser().parse_args(["status"])

    assert args.command == "status"


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
