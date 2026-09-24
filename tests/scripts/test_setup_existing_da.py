# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

import setup_existing_da


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
OTHER_AGENT_ID = "00000000-0000-4000-8000-000000006666"
TENANT_ID = "00000000-0000-4000-8000-000000009999"
FAMILY_ID = "00000000-0000-4000-8000-000000003333"
SCHEMA_NAME = "gptagent_copilotforemployeeselfservicehr"
HOST = (
    "https://0000000000004000800000000000111."
    "1.environment.api.test.powerplatform.com"
)
AGENT_URL = (
    "https://copilotstudio.test.microsoft.com/environments/"
    f"{ENVIRONMENT_ID}/bots/{AGENT_ID}/overview"
)


def _normalize_object_model_keys(value: Any) -> Any:
    if isinstance(value, dict):
        if value.get("$kind") == "Message":
            return "\n".join(
                "".join(
                    segment.get("value", "")
                    if segment.get("$kind") == "TextSegment"
                    else f"{{{segment.get('expression', {}).get('variableReference', '')}}}"
                    for segment in line.get("segments", [])
                )
                for line in value.get("text", [])
            )
        return {
            key.removeprefix("$"): _normalize_object_model_keys(child)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [_normalize_object_model_keys(child) for child in value]
    return value


def _convert_object_models(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for item in items:
        value = item["objectModel"]
        if value.get("$kind") == "UnsupportedDialog":
            results.append(
                {
                    "key": item["key"],
                    "success": False,
                    "error": {"message": "unsupported dialog kind"},
                }
            )
            continue
        results.append(
            {
                "key": item["key"],
                "success": True,
                "yaml": yaml.safe_dump(
                    _normalize_object_model_keys(value),
                    sort_keys=False,
                ),
            }
        )
    return results


@pytest.fixture(autouse=True)
def _isolate_external_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_auth(*_args: Any, **_kwargs: Any) -> str:
        raise AssertionError("Tests must stub Agent Builder authentication.")

    monkeypatch.setattr(
        setup_existing_da,
        "object_models_to_yaml",
        _convert_object_models,
    )
    monkeypatch.setattr(
        setup_existing_da,
        "validate_object_model_runtime",
        lambda: None,
    )
    monkeypatch.setattr(setup_existing_da, "authenticate", reject_auth)
    monkeypatch.setattr(
        setup_existing_da,
        "authenticate_selected_tenant",
        reject_auth,
    )


def _dialog(*, kind: str = "AdaptiveDialog", message: str = "Hello") -> dict[str, Any]:
    return {
        "$kind": kind,
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
                                        "value": message,
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        },
    }


def _changeset(
    *,
    dialog_kind: str = "AdaptiveDialog",
    message: str = "Hello",
    change_token: str = "opaque-token",
    agent_id: str = AGENT_ID,
    schema_name: str = SCHEMA_NAME,
    display_name: str = "Employee Self-Service HR",
) -> dict[str, Any]:
    return {
        "bot": {
            "$kind": "BotEntity",
            "cdsBotId": agent_id,
            "schemaName": schema_name,
            "displayName": display_name,
        },
        "changeToken": change_token,
        "botComponentChanges": [
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "DialogComponent",
                    "version": 3,
                    "displayName": "Greeting",
                    "id": "00000000-0000-4000-8000-000000004444",
                    "parentBotId": agent_id,
                    "schemaName": f"{schema_name}.topic.Greeting",
                    "dialog": _dialog(kind=dialog_kind, message=message),
                },
            },
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "GlobalVariableComponent",
                    "version": 1,
                    "displayName": "Locale",
                    "id": "00000000-0000-4000-8000-000000005555",
                    "parentBotId": agent_id,
                    "schemaName": f"{schema_name}.component.Locale",
                    "variable": {
                        "$kind": "GlobalVariable",
                        "name": "Locale",
                        "scope": "User",
                    },
                },
            },
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "GptComponent",
                    "version": 1,
                    "displayName": display_name,
                    "id": "00000000-0000-4000-8000-000000007777",
                    "parentBotId": agent_id,
                    "schemaName": f"{schema_name}.gpt.default",
                    "metadata": {
                        "$kind": "GptComponentMetadata",
                        "instructions": "Help employees.",
                    },
                },
            },
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "CloudFlowDefinitionComponent",
                    "id": "00000000-0000-4000-8000-000000008888",
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
        agent_name: str = "Employee Self-Service HR",
        agent_id: str = AGENT_ID,
        schema_name: str = SCHEMA_NAME,
        agent_realm: str = "dev",
        configuration_realm: str = "Dev",
        configured_agent_id: str | None = None,
        route_realm: int | str = 0,
        include_agent_schema: bool = True,
        published_config_available: bool = True,
        changeset: dict[str, Any] | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.agent_id = agent_id
        self.schema_name = schema_name
        self.agent_realm = agent_realm
        self.configuration_realm = configuration_realm
        self.configured_agent_id = configured_agent_id or agent_id
        self.route_realm = route_realm
        self.include_agent_schema = include_agent_schema
        self.published_config_available = published_config_available
        self.changeset = changeset or _changeset(
            agent_id=agent_id,
            schema_name=schema_name,
        )
        self.list_calls = 0
        self.fetch_calls = 0
        self.realm_calls = 0
        self.configuration_calls = 0

    def list_agents(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return [
            {"botId": self.agent_id, "fullBotName": self.agent_name},
            {"botId": OTHER_AGENT_ID, "fullBotName": "Production Agent"},
        ]

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        if agent_id != self.agent_id:
            return {
                "botId": OTHER_AGENT_ID,
                "fullBotName": "Production Agent",
                "realm": "prod",
            }
        agent = {
            "botId": self.agent_id,
            "fullBotName": self.agent_name,
            "realm": self.agent_realm,
            "managedProperties": {"isManaged": True},
        }
        if self.include_agent_schema:
            agent["schemaName"] = self.schema_name
        return agent

    def get_realms(self, _agent_id: str) -> dict[str, Any]:
        self.realm_calls += 1
        return {"routeRealm": self.route_realm}

    def get_dev_configuration(self, _agent_id: str) -> dict[str, Any]:
        self.configuration_calls += 1
        if not self.published_config_available:
            raise setup_existing_da.ExistingDASetupError(
                "The agent has no published Dev config. Publish the agent first."
            )
        return {
            "realm": self.configuration_realm,
            "cdsBotId": self.configured_agent_id,
            "schemaName": self.schema_name,
            "grsRepositoryId": FAMILY_ID,
            "values": {"mustNotPersist": "sensitive-realm-value"},
        }

    def fetch_components(self, _agent_id: str) -> dict[str, Any]:
        self.fetch_calls += 1
        return self.changeset


def _attach(
    client: FakeClient,
    root: Path,
    *,
    refresh: bool = False,
    agent_id: str = AGENT_ID,
) -> dict[str, Any]:
    return setup_existing_da.attach_existing_dev(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=agent_id,
        kit_root=root,
        refresh=refresh,
    )


def _agent_root(root: Path) -> Path:
    return root / "workspace" / "agents" / "employee-self-service-hr"


def _setup_state(root: Path) -> dict[str, Any]:
    return json.loads(
        (root / setup_existing_da.CANONICAL_SETUP_STATE).read_text(
            encoding="utf-8"
        )
    )


def _agent_setup_state(
    root: Path,
    agent_id: str = AGENT_ID,
) -> dict[str, Any]:
    return _setup_state(root)["agents"][agent_id]


def _projection_failure_path(
    root: Path,
    agent_id: str = AGENT_ID,
) -> Path:
    return (
        root
        / ".local"
        / "setup"
        / "agents"
        / agent_id
        / "projection-failure.json"
    )


def _write_flightcheck_results(
    root: Path,
    checkpoint: str,
    *statuses: str,
    agent_id: str = AGENT_ID,
) -> Path:
    path = root / f"{checkpoint.replace('*', 'family')}.json"
    prefix = checkpoint[:-1] if checkpoint.endswith("*") else checkpoint
    rows = [
        {
            "checkpoint_id": (
                f"{prefix}{index:03d}"
                if checkpoint.endswith("*")
                else checkpoint
            ),
            "status": status,
            "result": f"{checkpoint} returned {status}",
        }
        for index, status in enumerate(statuses, start=1)
    ]
    path.write_text(
        json.dumps(
            {
                "scope": f"checkpoint:{checkpoint}",
                "failed": sum(status == "Failed" for status in statuses),
                "errors": sum(status == "Error" for status in statuses),
                "results": rows,
            }
        ),
        encoding="utf-8",
    )
    step_id = setup_existing_da.SETUP_FLIGHTCHECK_STEPS[checkpoint]
    step_updated_at = _setup_state(root)["agents"][agent_id]["steps"][step_id][
        "updated_at"
    ]
    step_started = datetime.fromisoformat(step_updated_at).timestamp()
    # Do not let host filesystem timestamp precision decide fixture freshness.
    fresh_time = max(path.stat().st_mtime, step_started + 1)
    os.utime(path, (fresh_time, fresh_time))
    return path


def _complete_setup_flightchecks(root: Path) -> None:
    for checkpoint, statuses in (
        ("DA-AGENT-001", ("Passed",)),
        ("ENV-CAPACITY-001", ("Passed",)),
        ("DA-CONN-*", ("Passed", "Warning")),
        ("DA-CONTENT-001", ("Passed",)),
    ):
        setup_existing_da.maintain_setup_flightcheck(
            root,
            agent_id=AGENT_ID,
            checkpoint=checkpoint,
            results_path=_write_flightcheck_results(
                root,
                checkpoint,
                *statuses,
            ),
        )


def test_target_url_resolves_ids_and_ring() -> None:
    target = setup_existing_da.resolve_da_target(
        target_url=AGENT_URL,
        environment_id=None,
        agent_id=None,
        ring=None,
        require_agent=True,
    )

    assert target["environmentId"] == ENVIRONMENT_ID
    assert target["agentId"] == AGENT_ID
    assert target["ring"] == "test"
    assert target["agentSelection"] == "copilot-studio-url"


def test_target_rejects_conflicting_ring() -> None:
    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="different service rings",
    ):
        setup_existing_da.resolve_da_target(
            target_url=AGENT_URL,
            environment_id=None,
            agent_id=None,
            ring="prod",
            require_agent=True,
        )


def test_validate_agent_is_direct_and_side_effect_free(tmp_path: Path) -> None:
    client = FakeClient()

    connection = setup_existing_da.validate_existing_dev_connection(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
    )

    assert client.list_calls == 0
    assert connection["environment"]["tenantId"] == TENANT_ID
    assert connection["agent"] == {
        "id": AGENT_ID,
        "name": "Employee Self-Service HR",
        "schemaName": SCHEMA_NAME,
        "realm": "dev",
        "almFamilyId": FAMILY_ID,
        "isManaged": True,
        "workspaceSlug": "employee-self-service-hr",
    }
    assert connection["selectedBy"] == "direct-id"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    ("client", "message"),
    [
        (FakeClient(configuration_realm="Prod"), "returned realm"),
        (FakeClient(configured_agent_id=OTHER_AGENT_ID), "different agent"),
        (FakeClient(agent_realm="prod"), "non-Dev realm"),
    ],
)
def test_validate_agent_rejects_wrong_identity_or_realm(
    client: FakeClient,
    message: str,
) -> None:
    with pytest.raises(setup_existing_da.ExistingDASetupError, match=message):
        setup_existing_da.validate_existing_dev_connection(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )


@pytest.mark.parametrize(
    ("route_realm", "expected"),
    [(0, "dev"), (1, "test"), (2, "prod"), ("Prod", "prod")],
)
def test_inspect_agent_route_returns_service_realm(
    route_realm: int | str,
    expected: str,
) -> None:
    result = setup_existing_da.inspect_agent_route(
        FakeClient(route_realm=route_realm),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
    )

    assert result["realm"] == expected
    assert result["agentId"] == AGENT_ID
    assert result["tenantId"] == TENANT_ID


def test_inspect_agent_route_rejects_unknown_realm() -> None:
    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="recognized route realm",
    ):
        setup_existing_da.inspect_agent_route(
            FakeClient(route_realm=9),
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
        )


def test_list_agents_returns_only_verified_dev_agents() -> None:
    result = setup_existing_da.inspect_dev_agents(FakeClient())

    assert result["devAgents"] == [
        {
            "botId": AGENT_ID,
            "fullBotName": "Employee Self-Service HR",
            "realm": "dev",
            "schemaName": SCHEMA_NAME,
            "managedProperties": {"isManaged": True},
        }
    ]
    assert result["excludedNonDevCount"] == 1
    assert result["unverifiedAgentCount"] == 0


def test_list_agents_emits_unverified_http_response(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class UnverifiedClient(FakeClient):
        def get_agent(self, agent_id: str) -> dict[str, Any]:
            if agent_id == AGENT_ID:
                response = SimpleNamespace(
                    text='{"error":{"message":"not visible"}}',
                    json=lambda: {"error": {"message": "not visible"}},
                )
                raise setup_existing_da.AgentBuilderHTTPError(
                    "Agent inspection",
                    403,
                    error_code="Forbidden",
                    request_id="request-403",
                    response=response,
                )
            return super().get_agent(agent_id)

    result = setup_existing_da.inspect_dev_agents(UnverifiedClient())
    captured = capsys.readouterr()

    assert result["unverifiedAgentCount"] == 1
    assert "AgentBuilderHTTPError" in captured.err
    response = json.loads(
        captured.out.split(
            "DA_AGENT_LIST_WARNING_RESPONSE_JSON:",
            1,
        )[1]
    )
    assert response == {"error": {"message": "not visible"}}


def test_print_exception_includes_type_and_notes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = setup_existing_da.ExistingDASetupError("primary failure")
    error.add_note("secondary failure")

    setup_existing_da._print_exception(error)

    assert capsys.readouterr().err.splitlines() == [
        "ERROR: ExistingDASetupError: primary failure",
        "NOTE: secondary failure",
    ]


def test_attach_materializes_complete_workspace(tmp_path: Path) -> None:
    result = _attach(FakeClient(), tmp_path)
    agent_root = _agent_root(tmp_path)

    assert result["status"] == "created"
    assert "unprojectedDialogs" not in result
    assert result["connectionStatus"] == "workspace-ready"
    assert result["connectReady"] is False
    assert result["projectionVersion"] == 2
    assert result["topicCount"] == 1
    assert result["variableCount"] == 1
    assert (agent_root / "agent.mcs.yml").is_file()
    assert (agent_root / "topics" / "Greeting.mcs.yml").is_file()
    assert (agent_root / "variables" / "Locale.mcs.yml").is_file()
    assert (agent_root / setup_existing_da.RAW_CHANGESET).is_file()
    assert not (tmp_path / ".local" / "setup" / "da-connection.json").exists()
    assert not (tmp_path / ".local" / "setup" / "da-components.json").exists()
    metadata = json.loads(
        (agent_root / setup_existing_da.ATTACH_METADATA).read_text(
            encoding="utf-8"
        )
    )
    assert "unprojectedDialogs" not in metadata
    assert "Unavailable dialog components" not in (
        agent_root / "snapshot.md"
    ).read_text(encoding="utf-8")

    component_map = json.loads(
        (agent_root / ".component-map.json").read_text(encoding="utf-8")
    )
    assert set(component_map) == {
        "agent.mcs.yml",
        "topics/Greeting.mcs.yml",
        "variables/Locale.mcs.yml",
    }

    config = json.loads(
        (tmp_path / ".local" / "config.json").read_text(encoding="utf-8")
    )
    assert config["setup"] == "complete"
    assert config["agent"]["botId"] == AGENT_ID

    canonical_state = _setup_state(tmp_path)
    setup_state = _agent_setup_state(tmp_path)
    assert canonical_state["schema_version"] == 4
    assert canonical_state["environment"]["id"] == ENVIRONMENT_ID
    assert setup_state["connect_ready"] is False
    assert setup_state["active_step"] == "SETUP-02.1"
    assert set(setup_state["steps"]) == set(
        setup_existing_da.SETUP_STEP_ORDER
    )
    assert setup_state["steps"]["SETUP-01"]["mode"] == "automated"
    assert setup_state["steps"]["SETUP-03"]["mode"] == "automated"
    assert setup_state["steps"]["SETUP-07"]["mode"] == "automated"
    for step_id in ("SETUP-02.1", "SETUP-02.2", "SETUP-05", "SETUP-06"):
        assert setup_state["steps"][step_id]["state"] == "pending"
        assert setup_state["steps"][step_id]["mode"] is None
    assert setup_state["steps"]["SETUP-04"]["mode"] == "skipped"
    assert "does not apply" in setup_state["steps"]["SETUP-04"]["note"]
    assert setup_state["workspace"]["agent_path"] == "agent.mcs.yml"
    assert setup_state["workspace"]["variable_count"] == 1
    assert setup_state["workspace"]["unprojected_component_kinds"] == {
        "CloudFlowDefinitionComponent": 1
    }


def test_same_environment_agents_keep_independent_state_and_folders(
    tmp_path: Path,
) -> None:
    _attach(FakeClient(), tmp_path)
    _complete_setup_flightchecks(tmp_path)
    first_ready = _agent_setup_state(tmp_path)

    _attach(
        FakeClient(
            agent_id=OTHER_AGENT_ID,
            schema_name="gptagent_secondemployeeselfservice",
            agent_name="Employee Self-Service HR",
        ),
        tmp_path,
        agent_id=OTHER_AGENT_ID,
    )

    canonical = _setup_state(tmp_path)
    assert set(canonical["agents"]) == {AGENT_ID, OTHER_AGENT_ID}
    assert canonical["agents"][AGENT_ID] == first_ready
    assert canonical["agents"][AGENT_ID]["connect_ready"] is True
    assert canonical["agents"][OTHER_AGENT_ID]["connect_ready"] is False
    second_slug = canonical["agents"][OTHER_AGENT_ID]["agent"]["workspace_slug"]
    assert second_slug == "employee-self-service-hr-00000000"
    assert (
        tmp_path
        / "workspace"
        / "agents"
        / "employee-self-service-hr-00000000"
        / "agent.mcs.yml"
    ).is_file()

    config = json.loads(
        (tmp_path / ".local" / "config.json").read_text(encoding="utf-8")
    )
    assert len(config["agents"]) == 2
    assert config["activeAgent"] == second_slug
    assert config["agent"]["botId"] == OTHER_AGENT_ID


def test_select_agent_changes_only_operational_active_agent(
    tmp_path: Path,
) -> None:
    _attach(FakeClient(), tmp_path)
    _attach(
        FakeClient(
            agent_id=OTHER_AGENT_ID,
            schema_name="gptagent_secondemployeeselfservice",
            agent_name="Employee Self-Service IT",
        ),
        tmp_path,
        agent_id=OTHER_AGENT_ID,
    )
    canonical_before = _setup_state(tmp_path)

    result = setup_existing_da.select_local_agent(
        tmp_path,
        agent_id=AGENT_ID,
    )

    config = json.loads(
        (tmp_path / ".local" / "config.json").read_text(encoding="utf-8")
    )
    assert result["agentId"] == AGENT_ID
    assert config["activeAgent"] == "employee-self-service-hr"
    assert config["agent"]["botId"] == AGENT_ID
    assert _setup_state(tmp_path) == canonical_before


def test_attach_rejects_workspace_environment_mismatch(
    tmp_path: Path,
) -> None:
    _attach(FakeClient(), tmp_path)
    other_client = FakeClient(
        agent_id=OTHER_AGENT_ID,
        schema_name="gptagent_secondemployeeselfservice",
    )
    other_client.host = (
        "https://00000000000040008000000000008888."
        "1.environment.api.test.powerplatform.com"
    )

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="another Power Platform environment",
    ):
        setup_existing_da.attach_existing_dev(
            other_client,
            environment_id="00000000-0000-4000-8000-000000008888",
            agent_id=OTHER_AGENT_ID,
            kit_root=tmp_path,
        )

    assert set(_setup_state(tmp_path)["agents"]) == {AGENT_ID}


@pytest.mark.parametrize(
    ("setup_source", "selection_source"),
    (
        ("existing-dev", "direct-id"),
        ("alm-import", "alm-import-result"),
        ("prod-to-dev", "prod-to-dev-result"),
        ("mos-starter", "mos-starter-result"),
    ),
)
def test_attach_materializes_without_published_config(
    tmp_path: Path,
    setup_source: str,
    selection_source: str,
) -> None:
    client = FakeClient(
        include_agent_schema=False,
        published_config_available=False,
    )

    result = setup_existing_da.attach_existing_dev(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
        setup_source=setup_source,
        selection_source=selection_source,
        expected_schema_name=(
            None if setup_source == "existing-dev" else SCHEMA_NAME
        ),
    )

    assert result["connectionStatus"] == "workspace-ready"
    assert client.realm_calls == 1
    assert client.configuration_calls == 0
    assert client.fetch_calls == 1
    metadata = json.loads(
        (
            _agent_root(tmp_path)
            / setup_existing_da.ATTACH_METADATA
        ).read_text(encoding="utf-8")
    )
    assert metadata["realm"] == "dev"
    assert metadata["almFamilyId"] is None
    assert metadata["setupSource"] == setup_source


def test_existing_dev_attach_derives_schema_from_components(
    tmp_path: Path,
) -> None:
    client = FakeClient(include_agent_schema=False)

    result = setup_existing_da.attach_existing_dev(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
    )

    assert result["connectionStatus"] == "workspace-ready"
    assert result["schemaName"] == SCHEMA_NAME
    assert client.realm_calls == 1
    assert client.configuration_calls == 0
    assert client.fetch_calls == 1


@pytest.mark.parametrize(
    ("setup_source", "selection_source"),
    (
        ("alm-import", "alm-import-result"),
        ("prod-to-dev", "prod-to-dev-result"),
        ("mos-starter", "mos-starter-result"),
    ),
)
def test_receipt_backed_attach_rejects_component_schema_mismatch(
    tmp_path: Path,
    setup_source: str,
    selection_source: str,
) -> None:
    changeset = _changeset()
    changeset["bot"]["schemaName"] = "gptagent_different"
    client = FakeClient(include_agent_schema=False, changeset=changeset)

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="different schema",
    ):
        setup_existing_da.attach_existing_dev(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            kit_root=tmp_path,
            setup_source=setup_source,
            selection_source=selection_source,
            expected_schema_name=SCHEMA_NAME,
        )

    assert client.realm_calls == 1
    assert client.configuration_calls == 0
    assert client.fetch_calls == 1
    assert not (tmp_path / "workspace").exists()


def test_alm_import_attach_rejects_non_dev_route(
    tmp_path: Path,
) -> None:
    client = FakeClient(
        route_realm="Prod",
        include_agent_schema=False,
    )

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="realm discovery returned realm",
    ):
        setup_existing_da.attach_existing_dev(
            client,
            environment_id=ENVIRONMENT_ID,
            agent_id=AGENT_ID,
            kit_root=tmp_path,
            setup_source="alm-import",
            selection_source="alm-import-result",
            expected_schema_name=SCHEMA_NAME,
        )

    assert client.realm_calls == 1
    assert client.configuration_calls == 0
    assert client.fetch_calls == 0
    assert not (tmp_path / "workspace").exists()


def test_publish_independent_attachment_does_not_invent_family_identity(
    tmp_path: Path,
) -> None:
    client = FakeClient(include_agent_schema=False)

    setup_existing_da.attach_existing_dev(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
        setup_source="alm-import",
        expected_schema_name=SCHEMA_NAME,
    )

    state = _agent_setup_state(tmp_path)
    assert state["agent"]["alm_family_id"] is None
    assert client.configuration_calls == 0


def test_dialog_conversion_gap_preserves_evidence_without_ready_state(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="could not materialize all",
    ):
        _attach(
            FakeClient(changeset=_changeset(dialog_kind="UnsupportedDialog")),
            tmp_path,
        )

    evidence = json.loads(
        _projection_failure_path(tmp_path).read_text(encoding="utf-8")
    )
    assert evidence["agentId"] == AGENT_ID
    assert evidence["changeset"]["bot"]["cdsBotId"] == AGENT_ID
    assert not _agent_root(tmp_path).exists()
    assert not (tmp_path / ".local" / "config.json").exists()
    setup_state = _agent_setup_state(tmp_path)
    assert setup_state["connect_ready"] is False
    assert setup_state["active_step"] == "SETUP-07"
    assert setup_state["steps"]["SETUP-07"]["state"] == "blocked"
    assert setup_state["steps"]["SETUP-07"]["failure_causes"]


def test_projection_failure_preserves_cleanup_failure_as_secondary_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_rmtree = shutil.rmtree

    def fail_temporary_cleanup(path: str | Path, *args: Any, **kwargs: Any) -> None:
        candidate = Path(path)
        if candidate.name.startswith(".employee-self-service-hr."):
            raise OSError("cleanup denied")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(
        setup_existing_da.shutil,
        "rmtree",
        fail_temporary_cleanup,
    )

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="could not materialize all",
    ):
        _attach(
            FakeClient(changeset=_changeset(dialog_kind="UnsupportedDialog")),
            tmp_path,
        )

    error = capsys.readouterr().err
    assert "WARNING: Temporary workspace cleanup failed" in error
    setup_state = _agent_setup_state(tmp_path)
    failure_causes = setup_state["steps"]["SETUP-07"]["failure_causes"]
    assert "could not materialize all" in failure_causes[0]
    assert "Temporary workspace cleanup failed" in failure_causes[1]


def test_projection_evidence_failure_does_not_replace_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original_write_json = setup_existing_da._write_json

    def fail_projection_evidence(path: Path, value: Any) -> None:
        if path.name == "projection-failure.json":
            raise OSError("evidence write denied")
        original_write_json(path, value)

    monkeypatch.setattr(
        setup_existing_da,
        "_write_json",
        fail_projection_evidence,
    )

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="could not materialize all",
    ):
        _attach(
            FakeClient(changeset=_changeset(dialog_kind="UnsupportedDialog")),
            tmp_path,
        )

    error = capsys.readouterr().err
    assert "Projection-failure evidence persistence failed" in error
    setup_state = _agent_setup_state(tmp_path)
    assert "evidence write denied" in (
        setup_state["steps"]["SETUP-07"]["failure_causes"][1]
    )


def test_blocked_state_failure_does_not_replace_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_existing_da,
        "_record_canonical_setup_blocked",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("state write denied")
        ),
    )
    changeset = _changeset()
    changeset["bot"]["cdsBotId"] = OTHER_AGENT_ID

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="different agent",
    ):
        _attach(FakeClient(changeset=changeset), tmp_path)

    assert "Canonical blocked-state persistence failed" in (
        capsys.readouterr().err
    )


def test_config_failure_preserves_workspace_for_same_target_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_config(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("config write denied")

    monkeypatch.setattr(setup_existing_da, "_write_config", fail_config)

    with pytest.raises(OSError, match="config write denied"):
        _attach(FakeClient(), tmp_path)

    assert _agent_root(tmp_path).is_dir()
    setup_state = _agent_setup_state(tmp_path)
    assert setup_state["connect_ready"] is False
    assert setup_state["steps"]["SETUP-07"]["state"] == "blocked"
    assert "config write denied" in (
        setup_state["steps"]["SETUP-07"]["failure_causes"][0]
    )


def test_stale_failure_evidence_cleanup_is_non_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_path = _projection_failure_path(tmp_path)
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text("{}", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_evidence_cleanup(
        path: Path,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if path == evidence_path:
            raise OSError("cleanup denied")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_evidence_cleanup)

    result = _attach(FakeClient(), tmp_path)

    assert result["connectReady"] is False
    assert result["cleanupWarnings"] == [
        "Projection-failure evidence cleanup failed "
        "(OSError: cleanup denied)"
    ]
    assert evidence_path.is_file()
    setup_state = _agent_setup_state(tmp_path)
    assert setup_state["connect_ready"] is False


def test_skipped_flightcheck_steps_reopen_on_attach(
    tmp_path: Path,
) -> None:
    _attach(FakeClient(), tmp_path)
    state_path = tmp_path / setup_existing_da.CANONICAL_SETUP_STATE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    agent_state = state["agents"][AGENT_ID]
    for step_id in setup_existing_da.SETUP_FLIGHTCHECK_STEPS.values():
        agent_state["steps"][step_id] = setup_existing_da._step_record(
            "done",
            mode="skipped",
            note="Checkpoint was skipped",
            recorded_at=agent_state["created_at"],
        )
    agent_state["active_step"] = "SETUP-07"
    agent_state["connect_ready"] = True
    agent_state["completed_at"] = agent_state["created_at"]
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = _attach(FakeClient(), tmp_path)
    loaded = setup_existing_da._load_canonical_setup_state(tmp_path)

    assert loaded is not None
    loaded_agent = loaded["agents"][AGENT_ID]
    assert result["connectReady"] is False
    for step_id in setup_existing_da.SETUP_FLIGHTCHECK_STEPS.values():
        assert loaded_agent["steps"][step_id]["state"] == "pending"
    assert loaded_agent["steps"]["SETUP-07"]["state"] == "done"
    assert loaded_agent["active_step"] == "SETUP-02.1"
    assert loaded_agent["connect_ready"] is False
    assert loaded_agent["completed_at"] is None


def test_flightcheck_maintenance_completes_setup(tmp_path: Path) -> None:
    _attach(FakeClient(), tmp_path)

    _complete_setup_flightchecks(tmp_path)

    loaded = setup_existing_da._load_canonical_setup_state(tmp_path)
    assert loaded is not None
    loaded_agent = loaded["agents"][AGENT_ID]
    assert loaded_agent["connect_ready"] is True
    assert loaded_agent["completed_at"]
    assert loaded_agent["steps"]["SETUP-02.1"]["checkpoint"] == "DA-AGENT-001"
    assert (
        loaded_agent["steps"]["SETUP-02.2"]["checkpoint"]
        == "ENV-CAPACITY-001"
    )
    assert loaded_agent["steps"]["SETUP-05"]["checkpoint"] == "DA-CONN-*"
    assert (
        loaded_agent["steps"]["SETUP-06"]["checkpoint"]
        == "DA-CONTENT-001"
    )


def test_setup_rerun_requires_fresh_flightcheck_evidence(
    tmp_path: Path,
) -> None:
    _attach(FakeClient(), tmp_path)
    _complete_setup_flightchecks(tmp_path)
    stale_results = _write_flightcheck_results(
        tmp_path,
        "DA-AGENT-001",
        "Passed",
    )

    rerun = _attach(FakeClient(), tmp_path)

    assert rerun["connectReady"] is False
    loaded = setup_existing_da._load_canonical_setup_state(tmp_path)
    assert loaded is not None
    loaded_agent = loaded["agents"][AGENT_ID]
    for step_id in setup_existing_da.SETUP_FLIGHTCHECK_STEPS.values():
        assert loaded_agent["steps"][step_id]["state"] == "pending"
    stale_time = (
        datetime.fromisoformat(
            loaded_agent["steps"]["SETUP-02.1"]["updated_at"]
        ).timestamp()
        - 1
    )
    os.utime(stale_results, (stale_time, stale_time))

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="predate the current setup maintenance run",
    ):
        setup_existing_da.maintain_setup_flightcheck(
            tmp_path,
            agent_id=AGENT_ID,
            checkpoint="DA-AGENT-001",
            results_path=stale_results,
        )


def test_not_configured_connection_blocks_setup(tmp_path: Path) -> None:
    _attach(FakeClient(), tmp_path)
    results_path = _write_flightcheck_results(
        tmp_path,
        "DA-CONN-*",
        "NotConfigured",
    )
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    payload["overall"] = "READY"
    results_path.write_text(json.dumps(payload), encoding="utf-8")
    step_started = datetime.fromisoformat(
        _agent_setup_state(tmp_path)["steps"]["SETUP-05"]["updated_at"]
    ).timestamp()
    fresh_time = max(results_path.stat().st_mtime, step_started + 1)
    os.utime(results_path, (fresh_time, fresh_time))

    result = setup_existing_da.maintain_setup_flightcheck(
        tmp_path,
        agent_id=AGENT_ID,
        checkpoint="DA-CONN-*",
        results_path=results_path,
    )

    assert result["state"] == "blocked"
    assert result["evidenceStatuses"] == ["NotConfigured"]
    assert result["failureCauses"] == [
        "DA-CONN-* returned NotConfigured"
    ]
    assert result["connectReady"] is False
    loaded = setup_existing_da._load_canonical_setup_state(tmp_path)
    assert loaded is not None
    assert loaded["agents"][AGENT_ID]["steps"]["SETUP-05"]["failure_causes"]


def test_connect_ready_rejects_incomplete_steps(tmp_path: Path) -> None:
    _attach(FakeClient(), tmp_path)
    _complete_setup_flightchecks(tmp_path)
    state_path = tmp_path / setup_existing_da.CANONICAL_SETUP_STATE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    agent_state = state["agents"][AGENT_ID]
    agent_state["steps"]["SETUP-02.1"] = setup_existing_da._step_record()
    agent_state["active_step"] = "SETUP-02.1"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="readiness does not match",
    ):
        setup_existing_da._load_canonical_setup_state(tmp_path)


def test_all_done_steps_require_connect_ready(tmp_path: Path) -> None:
    _attach(FakeClient(), tmp_path)
    _complete_setup_flightchecks(tmp_path)
    state_path = tmp_path / setup_existing_da.CANONICAL_SETUP_STATE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["agents"][AGENT_ID]["connect_ready"] = False
    state["agents"][AGENT_ID]["completed_at"] = None
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="readiness does not match",
    ):
        setup_existing_da._load_canonical_setup_state(tmp_path)


def test_attach_rejects_changeset_for_another_agent(tmp_path: Path) -> None:
    changeset = _changeset()
    changeset["bot"]["cdsBotId"] = OTHER_AGENT_ID

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="different agent",
    ):
        _attach(FakeClient(changeset=changeset), tmp_path)

    setup_state = _agent_setup_state(tmp_path)
    assert setup_state["connect_ready"] is False
    assert setup_state["steps"]["SETUP-07"]["state"] == "blocked"
    assert "different agent" in (
        setup_state["steps"]["SETUP-07"]["failure_causes"][0]
    )


def test_identical_rerun_preserves_local_edits(tmp_path: Path) -> None:
    _attach(FakeClient(), tmp_path)
    topic = _agent_root(tmp_path) / "topics" / "Greeting.mcs.yml"
    topic.write_text("kind: AdaptiveDialog\nlocal: true\n", encoding="utf-8")

    result = _attach(FakeClient(agent_name="Renamed Agent"), tmp_path)

    assert result["status"] == "resumed"
    assert topic.read_text(encoding="utf-8") == (
        "kind: AdaptiveDialog\nlocal: true\n"
    )
    assert result["workspace"]["folder"].endswith(
        "employee-self-service-hr"
    )


def test_identical_rerun_removes_dead_projection_metadata(
    tmp_path: Path,
) -> None:
    _attach(FakeClient(), tmp_path)
    metadata_path = _agent_root(tmp_path) / setup_existing_da.ATTACH_METADATA
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["unprojectedDialogs"] = []
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    result = _attach(FakeClient(), tmp_path)

    assert "unprojectedDialogs" not in result
    persisted = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "unprojectedDialogs" not in persisted


@pytest.mark.parametrize(
    "setup_source",
    ("alm-import", "prod-to-dev", "mos-starter"),
)
def test_identical_rerun_preserves_strongest_provenance(
    tmp_path: Path,
    setup_source: str,
) -> None:
    setup_existing_da.attach_existing_dev(
        FakeClient(),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
        setup_source=setup_source,
    )

    result = _attach(FakeClient(), tmp_path)
    state = _agent_setup_state(tmp_path)

    assert result["setupSource"] == setup_source
    assert state["setup_source"] == setup_source


def test_changed_remote_content_requires_explicit_refresh(tmp_path: Path) -> None:
    _attach(FakeClient(), tmp_path)

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="explicit refresh",
    ):
        _attach(
            FakeClient(changeset=_changeset(message="Remote change")),
            tmp_path,
        )


def test_change_token_does_not_force_refresh(tmp_path: Path) -> None:
    _attach(FakeClient(), tmp_path)

    result = _attach(
        FakeClient(changeset=_changeset(change_token="new-token")),
        tmp_path,
    )

    assert result["status"] == "resumed"


def test_explicit_refresh_checkpoints_then_replaces_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _attach(FakeClient(), tmp_path)
    topic = _agent_root(tmp_path) / "topics" / "Greeting.mcs.yml"
    topic.write_text("kind: AdaptiveDialog\nlocal: true\n", encoding="utf-8")
    checkpointed: list[str] = []

    def create_checkpoint(path: str, message: str) -> int:
        checkpointed.extend([path, message])
        return 7

    def restore_from(destination: str, source: str) -> None:
        shutil.rmtree(destination)
        shutil.copytree(source, destination)

    monkeypatch.setitem(
        sys.modules,
        "checkpoint",
        SimpleNamespace(
            create_checkpoint=create_checkpoint,
            restore_from=restore_from,
        ),
    )

    result = _attach(
        FakeClient(changeset=_changeset(message="Remote change")),
        tmp_path,
        refresh=True,
    )

    assert result["status"] == "refreshed"
    assert result["checkpoint"] == 7
    assert "Remote change" in topic.read_text(encoding="utf-8")
    assert checkpointed[1] == "before DA setup refresh"


def test_older_projection_requires_explicit_refresh(tmp_path: Path) -> None:
    _attach(FakeClient(), tmp_path)
    metadata_path = _agent_root(tmp_path) / setup_existing_da.ATTACH_METADATA
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["projectionVersion"] = 1
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="older projection",
    ):
        _attach(FakeClient(), tmp_path)


def test_attach_does_not_treat_operational_config_as_setup_completion(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / ".local" / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "setup": "complete",
                "transport": "agentbuilder",
                "dataverseEndpoint": "https://old",
                "agents": [
                    {
                        "name": "Old Agent",
                        "botId": OTHER_AGENT_ID,
                        "slug": "old-agent",
                        "transport": "agentbuilder",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _attach(FakeClient(), tmp_path)

    assert result["connectReady"] is False
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert "transport" not in config
    assert all("transport" not in agent for agent in config["agents"])


def test_main_validate_agent_writes_no_setup_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_existing_da,
        "_client_from_args",
        lambda *_args, **_kwargs: FakeClient(),
    )

    result = setup_existing_da.main(
        [
            "validate-agent",
            "--target-url",
            AGENT_URL,
            "--kit-root",
            str(tmp_path),
        ]
    )

    assert result == 0
    payload = json.loads(
        capsys.readouterr().out.removeprefix("DA_AGENT_VALIDATION_JSON:")
    )
    assert payload["agentId"] == AGENT_ID
    assert list(tmp_path.iterdir()) == []


def test_main_attach_preflights_serializer_before_authentication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_preflight() -> None:
        raise setup_existing_da.ObjectModelConverterError(
            "serializer unavailable"
        )

    monkeypatch.setattr(
        setup_existing_da,
        "validate_object_model_runtime",
        fail_preflight,
    )
    monkeypatch.setattr(
        setup_existing_da,
        "_client_from_args",
        lambda *_args, **_kwargs: pytest.fail("authentication should not run"),
    )

    result = setup_existing_da.main(
        [
            "attach",
            "--target-url",
            AGENT_URL,
            "--kit-root",
            str(tmp_path),
        ]
    )

    assert result == 1
    error = capsys.readouterr().err
    assert "before authentication or remote agent validation" in error
    assert "serializer unavailable" in error


@pytest.mark.parametrize(
    ("setup_source", "selection_source"),
    (
        ("alm-import", "alm-import-result"),
        ("prod-to-dev", "prod-to-dev-result"),
        ("mos-starter", "mos-starter-result"),
    ),
)
def test_main_attach_forwards_setup_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    setup_source: str,
    selection_source: str,
) -> None:
    observed: dict[str, Any] = {}
    monkeypatch.setattr(
        setup_existing_da,
        "_require_object_model_dependencies",
        lambda: None,
    )
    monkeypatch.setattr(
        setup_existing_da,
        "_client_from_args",
        lambda *_args, **_kwargs: FakeClient(),
    )

    def attach(_client: FakeClient, **kwargs: Any) -> dict[str, Any]:
        observed.update(kwargs)
        return {"status": "created"}

    monkeypatch.setattr(setup_existing_da, "attach_existing_dev", attach)

    result = setup_existing_da.main(
        [
            "attach",
            "--target-url",
            AGENT_URL,
            "--kit-root",
            str(tmp_path),
            "--setup-source",
            setup_source,
        ]
        + (
            ["--expected-schema-name", SCHEMA_NAME]
            if setup_source in {"alm-import", "prod-to-dev", "mos-starter"}
            else []
        )
    )

    assert result == 0
    assert observed["selection_source"] == selection_source
    assert observed["setup_source"] == setup_source
    assert observed["expected_schema_name"] == (
        SCHEMA_NAME
        if setup_source in {"alm-import", "prod-to-dev", "mos-starter"}
        else None
    )


def test_parser_exposes_only_composable_setup_operations() -> None:
    parser = setup_existing_da.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, setup_existing_da.argparse._SubParsersAction)
    )

    assert set(subparsers.choices) == {
        "attach",
        "cached-accounts",
        "inspect-agent",
        "list-environments",
        "list-agents",
        "maintain-flightcheck",
        "select-agent",
        "validate-agent",
    }

    parsed = parser.parse_args(
        [
            "inspect-agent",
            "--target-url",
            "https://copilotstudio.microsoft.com/environments/"
            f"{ENVIRONMENT_ID}/agents/{AGENT_ID}",
            "--account",
            "test.user@example.test",
        ]
    )
    assert parsed.account == "test.user@example.test"
    with pytest.raises(SystemExit):
        parser.parse_args(["list-environments"])


def test_list_environments_emits_visible_non_dataverse_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_existing_da,
        "_authentication_from_args",
        lambda _args, _ring: ("token", TENANT_ID),
    )
    monkeypatch.setattr(
        setup_existing_da,
        "list_environments",
        lambda token, ring, *, api_version: [
            {
                "id": ENVIRONMENT_ID,
                "displayName": "No Database Environment",
                "type": "Sandbox",
                "state": "Ready",
                "geo": "unitedstates",
                "url": "",
                "futureServiceField": {"preserved": True},
            }
        ],
    )

    assert setup_existing_da.main(
        [
            "list-environments",
            "--ring",
            "test",
            "--account",
            "test.user@example.test",
            "--kit-root",
            str(tmp_path),
        ]
    ) == 0

    result = json.loads(
        capsys.readouterr().out.removeprefix(
            "DA_ENVIRONMENT_LIST_JSON:"
        )
    )
    evidence_path = (
        tmp_path / ".local" / "setup" / "environment-list-test.json"
    )
    assert result == {
        "tenantId": TENANT_ID,
        "ring": "test",
        "evidencePath": str(evidence_path.resolve()),
        "environments": [
            {
                "id": ENVIRONMENT_ID,
                "name": "No Database Environment",
                "type": "Sandbox",
                "state": "Ready",
                "region": "unitedstates",
            }
        ],
    }
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == {
        "tenantId": TENANT_ID,
        "ring": "test",
        "environments": [
            {
                "id": ENVIRONMENT_ID,
                "displayName": "No Database Environment",
                "type": "Sandbox",
                "state": "Ready",
                "geo": "unitedstates",
                "url": "",
                "futureServiceField": {"preserved": True},
            }
        ],
    }


def test_list_environments_preserves_empty_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_existing_da,
        "_authentication_from_args",
        lambda _args, _ring: ("token", TENANT_ID),
    )
    monkeypatch.setattr(
        setup_existing_da,
        "list_environments",
        lambda token, ring, *, api_version: [],
    )

    assert setup_existing_da.main(
        [
            "list-environments",
            "--ring",
            "prod",
            "--kit-root",
            str(tmp_path),
        ]
    ) == 0
    result = json.loads(
        capsys.readouterr().out.removeprefix(
            "DA_ENVIRONMENT_LIST_JSON:"
        )
    )
    assert result["environments"] == []
    assert result["ring"] == "prod"


@pytest.mark.parametrize("status_code", [401, 403])
def test_list_environments_preserves_authorization_failure(
    status_code: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_existing_da,
        "_authentication_from_args",
        lambda _args, _ring: ("token", TENANT_ID),
    )
    response = SimpleNamespace(
        json=lambda: {"error": {"code": "AuthorizationFailed"}},
        text="forbidden",
    )

    def deny_listing(
        _token: str,
        _ring: str,
        *,
        api_version: str,
    ) -> list[dict[str, Any]]:
        raise setup_existing_da.AgentBuilderHTTPError(
            "Environment listing",
            status_code,
            error_code="AuthorizationFailed",
            request_id="request-123",
            response=response,
        )

    monkeypatch.setattr(
        setup_existing_da,
        "list_environments",
        deny_listing,
    )

    assert setup_existing_da.main(
        [
            "list-environments",
            "--ring",
            "prod",
            "--kit-root",
            str(tmp_path),
        ]
    ) == 1
    captured = capsys.readouterr()
    error_result = json.loads(
        next(
            line.removeprefix("DA_ENVIRONMENT_LIST_ERROR_JSON:")
            for line in captured.out.splitlines()
            if line.startswith("DA_ENVIRONMENT_LIST_ERROR_JSON:")
        )
    )
    assert error_result == {
        "statusCode": status_code,
        "errorCode": "AuthorizationFailed",
        "requestId": "request-123",
        "authorizationFailure": True,
    }
    assert "DA_ENVIRONMENT_LIST_ERROR_RESPONSE_JSON:" in captured.out
    assert "DA_ENVIRONMENT_LIST_JSON:" not in captured.out
    assert f"HTTP {status_code}" in captured.err


def test_maintain_flightcheck_command_updates_local_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _attach(FakeClient(), tmp_path)
    results_path = _write_flightcheck_results(
        tmp_path,
        "DA-AGENT-001",
        "Passed",
    )

    exit_code = setup_existing_da.main(
        [
            "maintain-flightcheck",
            "--checkpoint",
            "DA-AGENT-001",
            "--agent-id",
            AGENT_ID,
            "--results",
            str(results_path),
            "--kit-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "DA_SETUP_FLIGHTCHECK_JSON:" in output
    assert '"state": "done"' in output


def test_authentication_uses_workspace_cache_and_account_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def authenticate_selected(
        ring: str,
        *,
        cache_path: Path,
        force_account_selection: bool,
        account_hint: str,
    ) -> tuple[str, str]:
        observed.update(
            {
                "ring": ring,
                "cache_path": cache_path,
                "force_account_selection": force_account_selection,
                "account_hint": account_hint,
            }
        )
        return "token", TENANT_ID

    monkeypatch.setattr(
        setup_existing_da,
        "authenticate_selected_tenant",
        authenticate_selected,
    )
    args = SimpleNamespace(
        tenant_id=None,
        select_account=False,
        account="test.user@example.test",
        kit_root=tmp_path,
    )

    assert setup_existing_da._authentication_from_args(args, "test") == (
        "token",
        TENANT_ID,
    )
    assert observed == {
        "ring": "test",
        "cache_path": tmp_path / ".local" / ".agentbuilder_token_cache.bin",
        "force_account_selection": False,
        "account_hint": "test.user@example.test",
    }


def test_cached_accounts_command_reads_workspace_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, Path] = {}

    def account_names(cache_path: Path) -> list[str]:
        observed["cache_path"] = cache_path
        return ["test.user@example.test"]

    monkeypatch.setattr(setup_existing_da, "cached_account_names", account_names)

    assert setup_existing_da.main(
        ["cached-accounts", "--kit-root", str(tmp_path)]
    ) == 0
    output = capsys.readouterr().out

    assert observed["cache_path"] == (
        tmp_path / ".local" / ".agentbuilder_token_cache.bin"
    )
    assert json.loads(
        output.removeprefix("DA_AGENTBUILDER_ACCOUNTS_JSON:")
    ) == {"accounts": ["test.user@example.test"]}


def test_unknown_setup_state_uses_format_language(tmp_path: Path) -> None:
    state_path = tmp_path / setup_existing_da.CANONICAL_SETUP_STATE
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps({"schema_version": 99}),
        encoding="utf-8",
    )

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="incompatible format",
    ):
        setup_existing_da._load_canonical_setup_state(tmp_path)
