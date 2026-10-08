# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for promoted Workday realm discovery and persisted target state."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


DEV_ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
TEST_ENVIRONMENT_ID = "00000000-0000-4000-8000-000000002222"
DEV_AGENT_ID = "00000000-0000-4000-8000-000000003333"
TEST_AGENT_ID = "00000000-0000-4000-8000-000000004444"
OTHER_AGENT_ID = "00000000-0000-4000-8000-000000005555"
TENANT_ID = "00000000-0000-4000-8000-000000006666"
OTHER_TENANT_ID = "00000000-0000-4000-8000-000000007777"
FAMILY_ID = "00000000-0000-4000-8000-000000008888"
OTHER_FAMILY_ID = "00000000-0000-4000-8000-000000009999"
SCHEMA_NAME = "gptagent_copilotforemployeeselfservicehr"
TEST_URL = "https://contoso-test.crm.dynamics.com"


class FakeClient:
    api_version = "2024-10-01"

    def __init__(
        self,
        *,
        tenant_id: str = TENANT_ID,
        realms: dict[str, Any] | None = None,
        agent: dict[str, Any] | None = None,
        configuration: dict[str, Any] | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self._realms = realms or {
            "routeRealm": 0,
            "siblingRealms": [{"realm": 1, "botId": TEST_AGENT_ID}],
        }
        self._agent = agent or {
            "botId": TEST_AGENT_ID,
            "schemaName": SCHEMA_NAME,
        }
        self._configuration = configuration or {
            "realm": 1,
            "cdsBotId": TEST_AGENT_ID,
            "grsRepositoryId": FAMILY_ID,
            "schemaName": SCHEMA_NAME,
            "commitSha": "abc123",
        }

    def get_realms(self, _agent_id: str) -> dict[str, Any]:
        return self._realms

    def get_agent(self, _agent_id: str) -> dict[str, Any]:
        if _agent_id.casefold() == DEV_AGENT_ID.casefold():
            return {
                "botId": DEV_AGENT_ID,
                "schemaName": SCHEMA_NAME,
            }
        return self._agent

    def get_realm_configuration(
        self,
        _agent_id: str,
        realm: int,
    ) -> dict[str, Any]:
        if realm == 0:
            return {
                "realm": 0,
                "cdsBotId": DEV_AGENT_ID,
                "grsRepositoryId": FAMILY_ID,
            }
        return self._configuration


def _catalog() -> dict[str, Any]:
    return {"supportedAgents": {SCHEMA_NAME: {"slug": "ess-hr"}}}


def _identity(
    *,
    environment_id: str,
    environment_url: str,
    agent_id: str,
    commit_sha: str,
) -> dict[str, str]:
    return {
        "environmentId": environment_id,
        "environmentUrl": environment_url,
        "tenantId": TENANT_ID,
        "agentId": agent_id,
        "agentSchemaName": SCHEMA_NAME,
        "agentSlug": "ess-hr",
        "almFamilyId": FAMILY_ID,
        "commitSha": commit_sha,
        "sourceAgentId": DEV_AGENT_ID,
    }


def _record_dev(store) -> None:
    store.record_target_discovery(
        "dev",
        _identity(
            environment_id=DEV_ENVIRONMENT_ID,
            environment_url="https://contoso-dev.crm.dynamics.com",
            agent_id=DEV_AGENT_ID,
            commit_sha="dev123",
        ),
        ring="test",
    )


def test_discovers_exact_promoted_target() -> None:
    from workday_connect_realms import discover_realm_target

    result = discover_realm_target(
        FakeClient(),
        FakeClient(),
        source_agent_id=DEV_AGENT_ID,
        source_agent_slug="ess-hr",
        realm="test",
        environment_id=TEST_ENVIRONMENT_ID,
        environment_url=TEST_URL,
        catalog=_catalog(),
    )

    assert result == _identity(
        environment_id=TEST_ENVIRONMENT_ID,
        environment_url=TEST_URL,
        agent_id=TEST_AGENT_ID,
        commit_sha="abc123",
    )


def test_rejects_recorded_dev_family_drift() -> None:
    from workday_connect_realms import (
        WorkdayConnectRealmError,
        discover_realm_target,
    )

    with pytest.raises(WorkdayConnectRealmError, match="recorded Dev target"):
        discover_realm_target(
            FakeClient(),
            FakeClient(),
            source_agent_id=DEV_AGENT_ID,
            source_agent_slug="ess-hr",
            realm="test",
            environment_id=TEST_ENVIRONMENT_ID,
            environment_url=TEST_URL,
            expected_source_family_id=OTHER_FAMILY_ID,
            catalog=_catalog(),
        )


@pytest.mark.parametrize(
    ("source", "target", "message"),
    [
        (
            FakeClient(realms={"routeRealm": 0, "siblingRealms": []}),
            FakeClient(),
            "promotion is not visible",
        ),
        (
            FakeClient(
                realms={
                    "routeRealm": 0,
                    "siblingRealms": [
                        {"realm": 1, "botId": TEST_AGENT_ID},
                        {"realm": 1, "botId": TEST_AGENT_ID},
                    ],
                }
            ),
            FakeClient(),
            "multiple Test targets",
        ),
        (
            FakeClient(),
            FakeClient(agent={"botId": OTHER_AGENT_ID}),
            "different agent identity",
        ),
        (
            FakeClient(),
            FakeClient(
                configuration={
                    "realm": 1,
                    "cdsBotId": TEST_AGENT_ID,
                    "grsRepositoryId": OTHER_FAMILY_ID,
                    "schemaName": SCHEMA_NAME,
                    "commitSha": "abc123",
                }
            ),
            "different ALM family",
        ),
        (
            FakeClient(),
            FakeClient(
                configuration={
                    "realm": 1,
                    "cdsBotId": TEST_AGENT_ID,
                    "grsRepositoryId": FAMILY_ID,
                    "schemaName": "other",
                    "commitSha": "abc123",
                }
            ),
            "not the supported ESS HR agent",
        ),
        (
            FakeClient(),
            FakeClient(
                configuration={
                    "realm": 1,
                    "cdsBotId": TEST_AGENT_ID,
                    "grsRepositoryId": FAMILY_ID,
                    "schemaName": SCHEMA_NAME,
                    "commitSha": "",
                }
            ),
            "does not have deployed package evidence",
        ),
        (
            FakeClient(),
            FakeClient(tenant_id=OTHER_TENANT_ID),
            "different Microsoft Entra tenants",
        ),
    ],
)
def test_rejects_unproven_promoted_targets(
    source: FakeClient,
    target: FakeClient,
    message: str,
) -> None:
    from workday_connect_realms import (
        WorkdayConnectRealmError,
        discover_realm_target,
    )

    with pytest.raises(WorkdayConnectRealmError, match=message):
        discover_realm_target(
            source,
            target,
            source_agent_id=DEV_AGENT_ID,
            source_agent_slug="ess-hr",
            realm="test",
            environment_id=TEST_ENVIRONMENT_ID,
            environment_url=TEST_URL,
            catalog=_catalog(),
        )


def test_recording_promoted_target_requires_exact_environment_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workday_connect_realms as realms
    from workday_connect_realms import WorkdayConnectRealmError
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _record_dev(store)
    config = tmp_path / ".local" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "ring": "test",
                "environmentId": DEV_ENVIRONMENT_ID,
                "powerPlatformApiEndpoint": (
                    "https://0000000000004000800000000000111.1."
                    "environment.api.test.powerplatform.com"
                ),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        realms,
        "derive_environment_host",
        lambda *_args: "https://target.environment.api.test.powerplatform.com",
    )

    with pytest.raises(WorkdayConnectRealmError, match="does not match"):
        realms.discover_and_record_realm_target(
            tmp_path,
            store,
            realm="test",
            environment_id=TEST_ENVIRONMENT_ID,
            environment_url="https://wrong.crm.dynamics.com",
            authenticator=lambda *_args, **_kwargs: ("token", TENANT_ID),
            environment_loader=lambda *_args, **_kwargs: [
                {
                    "id": TEST_ENVIRONMENT_ID,
                    "properties": {
                        "linkedEnvironmentMetadata": {
                            "instanceUrl": TEST_URL,
                        }
                    },
                }
            ],
        )


@pytest.mark.parametrize(
    ("inventory", "message"),
    [
        ([], "not visible"),
        (
            [
                {"id": TEST_ENVIRONMENT_ID, "instanceUrl": TEST_URL},
                {"id": TEST_ENVIRONMENT_ID, "instanceUrl": TEST_URL},
            ],
            "duplicate records",
        ),
        ([{"id": TEST_ENVIRONMENT_ID}], "does not contain a Dataverse URL"),
    ],
)
def test_environment_inventory_must_prove_one_exact_url(
    inventory: list[dict[str, Any]],
    message: str,
) -> None:
    from workday_connect_realms import (
        WorkdayConnectRealmError,
        _environment_url_from_inventory,
    )

    with pytest.raises(WorkdayConnectRealmError, match=message):
        _environment_url_from_inventory(inventory, TEST_ENVIRONMENT_ID)


def test_environment_url_rejects_non_root_paths() -> None:
    from workday_connect_realms import (
        WorkdayConnectRealmError,
        _normalize_environment_url,
    )

    with pytest.raises(WorkdayConnectRealmError, match="safe HTTPS URL"):
        _normalize_environment_url(f"{TEST_URL}/api/data")


def test_records_and_activates_promoted_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workday_connect_realms as realms
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _record_dev(store)
    config = tmp_path / ".local" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "ring": "test",
                "environmentId": DEV_ENVIRONMENT_ID,
                "powerPlatformApiEndpoint": (
                    "https://0000000000004000800000000000111.1."
                    "environment.api.test.powerplatform.com"
                ),
            }
        ),
        encoding="utf-8",
    )
    clients = iter((FakeClient(), FakeClient()))
    monkeypatch.setattr(
        realms,
        "derive_environment_host",
        lambda *_args: "https://target.environment.api.test.powerplatform.com",
    )

    result = realms.discover_and_record_realm_target(
        tmp_path,
        store,
        realm="test",
        environment_id=TEST_ENVIRONMENT_ID,
        environment_url=TEST_URL,
        authenticator=lambda *_args, **_kwargs: ("token", TENANT_ID),
        environment_loader=lambda *_args, **_kwargs: [
            {
                "id": TEST_ENVIRONMENT_ID,
                "properties": {
                    "linkedEnvironmentMetadata": {
                        "instanceApiUrl": f"{TEST_URL}/",
                    }
                },
            }
        ],
        client_factory=lambda *_args, **_kwargs: next(clients),
    )

    state = store.load()
    assert result["realm"] == "test"
    assert result["targetStatus"] == "detected"
    assert state["activeTargetRealm"] == "test"
    assert state["scope"]["environmentId"] == TEST_ENVIRONMENT_ID
    assert state["scope"]["agent"]["botId"] == TEST_AGENT_ID
    assert state["targets"]["test"]["provenance"] == (
        "agentbuilder-realm-discovery"
    )
    assert state["targets"]["dev"]["scope"]["environmentId"] == (
        DEV_ENVIRONMENT_ID
    )


def test_automatically_discovers_promoted_target_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workday_connect_realms as realms
    from agentbuilder import AgentBuilderHTTPError
    from workday_connect_store import WorkdayConnectStore

    wrong_environment_id = "00000000-0000-4000-8000-00000000aaaa"
    wrong_url = "https://contoso-other.crm.dynamics.com"

    class MissingAgentClient(FakeClient):
        def get_agent(self, _agent_id: str) -> dict[str, Any]:
            raise AgentBuilderHTTPError("Direct agent lookup", 404)

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _record_dev(store)
    config = tmp_path / ".local" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        json.dumps(
            {
                "ring": "test",
                "environmentId": DEV_ENVIRONMENT_ID,
                "powerPlatformApiEndpoint": (
                    "https://0000000000004000800000000000111.1."
                    "environment.api.test.powerplatform.com"
                ),
            }
        ),
        encoding="utf-8",
    )
    clients = iter((FakeClient(), MissingAgentClient(), FakeClient()))
    monkeypatch.setattr(
        realms,
        "derive_environment_host",
        lambda *_args: "https://target.environment.api.test.powerplatform.com",
    )

    result = realms.discover_and_record_realm_target(
        tmp_path,
        store,
        realm="test",
        authenticator=lambda *_args, **_kwargs: ("token", TENANT_ID),
        environment_loader=lambda *_args, **_kwargs: [
            {
                "id": wrong_environment_id,
                "displayName": "Other environment",
                "instanceUrl": wrong_url,
            },
            {
                "id": TEST_ENVIRONMENT_ID,
                "displayName": "ESS Test",
                "instanceUrl": TEST_URL,
            },
        ],
        client_factory=lambda *_args, **_kwargs: next(clients),
    )

    assert result["realm"] == "test"
    assert result["foundationReused"] is False
    assert store.load()["scope"]["environmentId"] == TEST_ENVIRONMENT_ID


def test_target_switching_preserves_realm_specific_progress(
    tmp_path: Path,
) -> None:
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _record_dev(store)
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified", "realm": "dev"},
    )
    store.set_phase_status("preflight", "complete")
    store.record_target_discovery(
        "test",
        _identity(
            environment_id=TEST_ENVIRONMENT_ID,
            environment_url=TEST_URL,
            agent_id=TEST_AGENT_ID,
            commit_sha="abc123",
        ),
        ring="test",
    )
    store.activate_target("test")
    assert store.load()["phases"]["preflight"]["status"] == "pending"
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified", "realm": "test"},
    )
    store.set_phase_status("preflight", "complete")

    store.activate_target("dev")
    dev_state = store.load()
    assert dev_state["phases"]["preflight"]["evidence"][0]["realm"] == "dev"
    assert dev_state["targets"]["test"]["phases"]["preflight"]["evidence"][
        0
    ]["realm"] == "test"
    assert dev_state["scope"]["environmentId"] == DEV_ENVIRONMENT_ID
    assert store.status()["targets"] == [
        {"realm": "dev", "status": "partially-configured", "active": True},
        {
            "realm": "test",
            "status": "partially-configured",
            "active": False,
        },
        {"realm": "prod", "status": "not-deployed", "active": False},
    ]


def test_maker_validation_completion_is_scoped_to_active_realm(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _record_dev(store)
    store.record_target_discovery(
        "test",
        _identity(
            environment_id=TEST_ENVIRONMENT_ID,
            environment_url=TEST_URL,
            agent_id=TEST_AGENT_ID,
            commit_sha="abc123",
        ),
        ring="test",
    )
    store.activate_target("test")
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
        "maker-validation",
    ):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")

    test_state = store.load()
    assert test_state["status"] == "ready"
    assert test_state["targets"]["test"]["deploymentStatus"] == "ready"

    store.activate_target("dev")
    dev_state = store.load()
    assert dev_state["status"] == "in-progress"
    assert dev_state["phases"]["maker-validation"]["status"] == "pending"
    assert dev_state["targets"]["test"]["phases"]["maker-validation"][
        "status"
    ] == "complete"


def test_replayed_discovery_preserves_target_progress(
    tmp_path: Path,
) -> None:
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _record_dev(store)
    identity = _identity(
        environment_id=TEST_ENVIRONMENT_ID,
        environment_url=TEST_URL,
        agent_id=TEST_AGENT_ID,
        commit_sha="abc123",
    )
    store.record_target_discovery("test", identity, ring="test")
    store.activate_target("test")
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified"},
    )
    store.set_phase_status("preflight", "complete")

    replayed = store.record_target_discovery(
        "test",
        identity,
        ring="test",
    )

    assert replayed["phases"]["preflight"]["status"] == "complete"
    assert replayed["targets"]["test"]["deploymentStatus"] == (
        "partially-configured"
    )


def test_changed_deployment_commit_resets_only_that_target(
    tmp_path: Path,
) -> None:
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _record_dev(store)
    store.record_target_discovery(
        "test",
        _identity(
            environment_id=TEST_ENVIRONMENT_ID,
            environment_url=TEST_URL,
            agent_id=TEST_AGENT_ID,
            commit_sha="abc123",
        ),
        ring="test",
    )
    store.activate_target("test")
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified"},
    )
    store.set_phase_status("preflight", "complete")
    store.activate_target("dev")

    store.record_target_discovery(
        "test",
        _identity(
            environment_id=TEST_ENVIRONMENT_ID,
            environment_url=TEST_URL,
            agent_id=TEST_AGENT_ID,
            commit_sha="def456",
        ),
        ring="test",
    )

    state = store.load()
    assert state["activeTargetRealm"] == "dev"
    assert state["targets"]["test"]["phases"]["preflight"]["status"] == (
        "pending"
    )
    assert state["targets"]["test"]["identity"]["commitSha"] == "def456"
    assert state["targets"]["dev"]["identity"]["commitSha"] == "dev123"


def test_revalidating_dev_target_does_not_call_promoted_discovery(
    tmp_path: Path,
) -> None:
    from workday_connect_realms import revalidate_active_realm_target
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _record_dev(store)

    assert revalidate_active_realm_target(tmp_path, store) == {
        "realm": "dev",
        "revalidated": False,
    }


@pytest.mark.parametrize(
    "changed_field",
    [
        "environmentId",
        "environmentUrl",
        "tenantId",
        "agentId",
        "agentSchemaName",
        "agentSlug",
        "almFamilyId",
        "commitSha",
        "sourceAgentId",
    ],
)
def test_revalidating_promoted_target_rejects_identity_drift_without_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str,
) -> None:
    import workday_connect_realms as realms
    from workday_connect_realms import WorkdayConnectRealmError
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _record_dev(store)
    identity = _identity(
        environment_id=TEST_ENVIRONMENT_ID,
        environment_url=TEST_URL,
        agent_id=TEST_AGENT_ID,
        commit_sha="abc123",
    )
    store.record_target_discovery("test", identity, ring="test")
    store.activate_target("test")
    approved_state = store.load()

    monkeypatch.setattr(
        realms,
        "_discover_promoted_realm_identity",
        lambda *_args, **_kwargs: (
            {**identity, changed_field: "drifted-value"},
            "test",
        ),
    )

    with pytest.raises(
        WorkdayConnectRealmError,
        match=f"changed after approval: {changed_field}",
    ):
        realms.revalidate_active_realm_target(tmp_path, store)

    assert store.load() == approved_state


def test_revalidating_promoted_target_accepts_complete_identity_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workday_connect_realms as realms
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _record_dev(store)
    identity = _identity(
        environment_id=TEST_ENVIRONMENT_ID,
        environment_url=TEST_URL,
        agent_id=TEST_AGENT_ID,
        commit_sha="abc123",
    )
    store.record_target_discovery("test", identity, ring="test")
    store.activate_target("test")
    approved_state = store.load()
    monkeypatch.setattr(
        realms,
        "_discover_promoted_realm_identity",
        lambda *_args, **_kwargs: (dict(identity), "test"),
    )

    assert realms.revalidate_active_realm_target(tmp_path, store) == {
        "realm": "test",
        "revalidated": True,
    }
    assert store.load() == approved_state


def test_v10_state_migrates_to_realm_registry(tmp_path: Path) -> None:
    from workday_connect_model import PHASE_REQUIRED_ACTIONS, default_state
    from workday_connect_store import WorkdayConnectStore

    state = default_state()
    state["schemaVersion"] = 10
    state.pop("activeTargetRealm")
    state.pop("targets")
    for phase_id in ("preflight", "entra"):
        phase = state["phases"][phase_id]
        phase["status"] = "complete"
        phase["completedActions"] = list(
            PHASE_REQUIRED_ACTIONS[phase_id]
        )
        phase["evidence"] = [
            {"action": action, "outcome": "verified"}
            for action in PHASE_REQUIRED_ACTIONS[phase_id]
        ]
    workday_phase = state["phases"]["workday-admin"]
    workday_phase["status"] = "active"
    workday_phase["administrator"]["partialEvidence"].update(
        {
            "authorizationOutcome": "task-not-authorized-remediated",
            "authorizationRemediationDomain": (
                "Worker Data: Public Worker Reports"
            ),
            "authorizationRemediationScenario": "Check vacation balance",
            "authorizationRetestOutcome": "verified-after-remediation",
        }
    )
    workday_phase["administrator"]["invalidFields"] = [
        "authorizationRetestOutcome"
    ]
    workday_phase["evidence"].append(
        {
            "action": "administrator-response-validated",
            "authorizationOutcome": "verified",
        }
    )
    path = (
        tmp_path
        / ".local"
        / "connect"
        / "workday-da"
        / "config.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state), encoding="utf-8")

    migrated = WorkdayConnectStore(tmp_path).initialize()

    assert migrated["schemaVersion"] == 12
    assert migrated["activeTargetRealm"] == "dev"
    assert migrated["targets"]["dev"]["phases"] == migrated["phases"]
    assert migrated["targets"]["test"] is None
    migrated_workday = migrated["phases"]["workday-admin"]
    assert migrated_workday["administrator"]["partialEvidence"] == {}
    assert migrated_workday["administrator"]["invalidFields"] == []
    assert "authorizationOutcome" not in migrated_workday["evidence"][0]
    assert path.with_name("config.pre-v12.json").exists()


def test_controller_handler_returns_realm_discovery_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workday_connect
    from workday_connect_store import WorkdayConnectStore

    expected = {
        "realm": "test",
        "targetStatus": "detected",
    }
    monkeypatch.setattr(
        workday_connect,
        "discover_and_record_realm_target",
        lambda *_args, **_kwargs: expected,
    )

    result = workday_connect._discover_realm_target(
        SimpleNamespace(
            root=tmp_path,
            realm="test",
            environment_id=TEST_ENVIRONMENT_ID,
            dataverse_url=TEST_URL,
            maker_username="maker@example.com",
        ),
        WorkdayConnectStore(tmp_path),
    )

    assert result == expected


def test_controller_allows_automatic_or_friendly_environment_discovery() -> None:
    import workday_connect

    automatic = workday_connect.build_parser().parse_args(
        ["discover-realm-target", "--realm", "test"]
    )
    selected = workday_connect.build_parser().parse_args(
        [
            "discover-realm-target",
            "--realm",
            "prod",
            "--environment",
            "ESS Production",
        ]
    )

    assert automatic.environment is None
    assert automatic.environment_id is None
    assert automatic.dataverse_url is None
    assert selected.environment == "ESS Production"
