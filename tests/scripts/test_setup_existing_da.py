# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
import shutil
import sys
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
) -> dict[str, Any]:
    return {
        "bot": {
            "$kind": "BotEntity",
            "cdsBotId": AGENT_ID,
            "schemaName": SCHEMA_NAME,
            "displayName": "Employee Self-Service HR",
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
                    "parentBotId": AGENT_ID,
                    "schemaName": f"{SCHEMA_NAME}.topic.Greeting",
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
                    "parentBotId": AGENT_ID,
                    "schemaName": f"{SCHEMA_NAME}.component.Locale",
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
                    "displayName": "Employee Self-Service HR",
                    "id": "00000000-0000-4000-8000-000000007777",
                    "parentBotId": AGENT_ID,
                    "schemaName": f"{SCHEMA_NAME}.gpt.default",
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
        agent_realm: str = "dev",
        configuration_realm: str = "Dev",
        configured_agent_id: str = AGENT_ID,
        route_realm: int | str = 0,
        changeset: dict[str, Any] | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.agent_realm = agent_realm
        self.configuration_realm = configuration_realm
        self.configured_agent_id = configured_agent_id
        self.route_realm = route_realm
        self.changeset = changeset or _changeset()
        self.list_calls = 0
        self.fetch_calls = 0

    def list_agents(self) -> list[dict[str, Any]]:
        self.list_calls += 1
        return [
            {"botId": AGENT_ID, "fullBotName": self.agent_name},
            {"botId": OTHER_AGENT_ID, "fullBotName": "Production Agent"},
        ]

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        if agent_id == OTHER_AGENT_ID:
            return {
                "botId": OTHER_AGENT_ID,
                "fullBotName": "Production Agent",
                "realm": "prod",
            }
        return {
            "botId": AGENT_ID,
            "fullBotName": self.agent_name,
            "realm": self.agent_realm,
            "schemaName": SCHEMA_NAME,
            "managedProperties": {"isManaged": True},
        }

    def get_realms(self, _agent_id: str) -> dict[str, Any]:
        return {"routeRealm": self.route_realm}

    def get_dev_configuration(self, _agent_id: str) -> dict[str, Any]:
        return {
            "realm": self.configuration_realm,
            "cdsBotId": self.configured_agent_id,
            "schemaName": SCHEMA_NAME,
            "grsRepositoryId": FAMILY_ID,
            "values": {"mustNotPersist": "sensitive-realm-value"},
        }

    def fetch_components(self, _agent_id: str) -> dict[str, Any]:
        self.fetch_calls += 1
        return self.changeset


def _attach(client: FakeClient, root: Path, *, refresh: bool = False) -> dict[str, Any]:
    return setup_existing_da.attach_existing_dev(
        client,
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=root,
        refresh=refresh,
    )


def _agent_root(root: Path) -> Path:
    return root / "workspace" / "agents" / "employee-self-service-hr"


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


def test_attach_materializes_complete_workspace(tmp_path: Path) -> None:
    result = _attach(FakeClient(), tmp_path)
    agent_root = _agent_root(tmp_path)

    assert result["status"] == "created"
    assert "unprojectedDialogs" not in result
    assert result["connectionStatus"] == "workspace-ready"
    assert result["connectReady"] is True
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

    setup_state = json.loads(
        (tmp_path / setup_existing_da.CANONICAL_SETUP_STATE).read_text(
            encoding="utf-8"
        )
    )
    assert setup_state["schema_version"] == 3
    assert setup_state["connect_ready"] is True
    assert setup_state["active_step"] == "SETUP-07"
    assert set(setup_state["steps"]) == set(
        setup_existing_da.SETUP_STEP_ORDER
    )
    assert all(
        step["state"] == "done"
        for step in setup_state["steps"].values()
    )
    assert setup_state["steps"]["SETUP-01"]["mode"] == "automated"
    assert setup_state["steps"]["SETUP-03"]["mode"] == "automated"
    assert setup_state["steps"]["SETUP-07"]["mode"] == "automated"
    for step_id in ("SETUP-02.1", "SETUP-02.2", "SETUP-05", "SETUP-06"):
        assert setup_state["steps"][step_id]["mode"] == "skipped"
        assert setup_state["steps"][step_id]["note"]
    assert setup_state["steps"]["SETUP-04"]["mode"] == "skipped"
    assert "does not apply" in setup_state["steps"]["SETUP-04"]["note"]
    assert setup_state["workspace"]["agent_path"] == "agent.mcs.yml"
    assert setup_state["workspace"]["variable_count"] == 1
    assert setup_state["workspace"]["unprojected_component_kinds"] == {
        "CloudFlowDefinitionComponent": 1
    }


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
        (
            tmp_path
            / ".local"
            / "setup"
            / "da-projection-failure.json"
        ).read_text(encoding="utf-8")
    )
    assert evidence["agentId"] == AGENT_ID
    assert evidence["changeset"]["bot"]["cdsBotId"] == AGENT_ID
    assert not _agent_root(tmp_path).exists()
    assert not (tmp_path / ".local" / "config.json").exists()
    setup_state = json.loads(
        (tmp_path / setup_existing_da.CANONICAL_SETUP_STATE).read_text(
            encoding="utf-8"
        )
    )
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
    setup_state = json.loads(
        (tmp_path / setup_existing_da.CANONICAL_SETUP_STATE).read_text(
            encoding="utf-8"
        )
    )
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
        if path.name == "da-projection-failure.json":
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
    setup_state = json.loads(
        (tmp_path / setup_existing_da.CANONICAL_SETUP_STATE).read_text(
            encoding="utf-8"
        )
    )
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
    setup_state = json.loads(
        (tmp_path / setup_existing_da.CANONICAL_SETUP_STATE).read_text(
            encoding="utf-8"
        )
    )
    assert setup_state["connect_ready"] is False
    assert setup_state["steps"]["SETUP-07"]["state"] == "blocked"
    assert "config write denied" in (
        setup_state["steps"]["SETUP-07"]["failure_causes"][0]
    )


def test_stale_failure_evidence_cleanup_is_non_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_path = (
        tmp_path / ".local" / "setup" / "da-projection-failure.json"
    )
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

    assert result["connectReady"] is True
    assert result["cleanupWarnings"] == [
        "Projection-failure evidence cleanup failed "
        "(OSError: cleanup denied)"
    ]
    assert evidence_path.is_file()
    setup_state = json.loads(
        (tmp_path / setup_existing_da.CANONICAL_SETUP_STATE).read_text(
            encoding="utf-8"
        )
    )
    assert setup_state["connect_ready"] is True


def test_temporarily_skipped_step_can_be_reopened(
    tmp_path: Path,
) -> None:
    _attach(FakeClient(), tmp_path)
    state_path = tmp_path / setup_existing_da.CANONICAL_SETUP_STATE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["steps"]["SETUP-02.1"] = setup_existing_da._step_record()
    state["active_step"] = "SETUP-02.1"
    state["connect_ready"] = False
    state["completed_at"] = None
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result = _attach(FakeClient(), tmp_path)
    loaded = setup_existing_da._load_canonical_setup_state(tmp_path)

    assert loaded is not None
    assert result["connectReady"] is False
    assert loaded["steps"]["SETUP-02.1"]["state"] == "pending"
    assert loaded["steps"]["SETUP-07"]["state"] == "done"
    assert loaded["active_step"] == "SETUP-02.1"
    assert loaded["connect_ready"] is False
    assert loaded["completed_at"] is None


def test_connect_ready_rejects_incomplete_steps(tmp_path: Path) -> None:
    _attach(FakeClient(), tmp_path)
    state_path = tmp_path / setup_existing_da.CANONICAL_SETUP_STATE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["steps"]["SETUP-02.1"] = setup_existing_da._step_record()
    state["active_step"] = "SETUP-02.1"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(
        setup_existing_da.ExistingDASetupError,
        match="readiness does not match",
    ):
        setup_existing_da._load_canonical_setup_state(tmp_path)


def test_all_done_steps_require_connect_ready(tmp_path: Path) -> None:
    _attach(FakeClient(), tmp_path)
    state_path = tmp_path / setup_existing_da.CANONICAL_SETUP_STATE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["connect_ready"] = False
    state["completed_at"] = None
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

    setup_state = json.loads(
        (tmp_path / setup_existing_da.CANONICAL_SETUP_STATE).read_text(
            encoding="utf-8"
        )
    )
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


def test_identical_rerun_preserves_alm_import_provenance(
    tmp_path: Path,
) -> None:
    setup_existing_da.attach_existing_dev(
        FakeClient(),
        environment_id=ENVIRONMENT_ID,
        agent_id=AGENT_ID,
        kit_root=tmp_path,
        setup_source="alm-import",
    )

    result = _attach(FakeClient(), tmp_path)
    state = json.loads(
        (tmp_path / setup_existing_da.CANONICAL_SETUP_STATE).read_text(
            encoding="utf-8"
        )
    )
    assert result["setupSource"] == "alm-import"
    assert state["setup_source"] == "alm-import"
    assert state["setup_source"] == "alm-import"


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

    assert result["connectReady"] is True
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


def test_parser_exposes_only_composable_setup_operations() -> None:
    parser = setup_existing_da.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, setup_existing_da.argparse._SubParsersAction)
    )

    assert set(subparsers.choices) == {
        "attach",
        "inspect-agent",
        "list-agents",
        "validate-agent",
    }
