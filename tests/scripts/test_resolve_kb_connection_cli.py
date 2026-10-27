# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the ``resolve_kb_connection`` CLI shim's JSON contract.

Runs ``main()`` in-process with the working directory switched to a
``tmp_path`` (so the ``.local/config.json`` relative-path convention is
exercised) and ``discover_tenant``/``PVAClient`` monkeypatched — no network
access.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import resolve_kb_connection

FAKE_BOT_ID = "00000000-0000-0000-0000-000000003333"


class _FakePVA:
    """Duck-typed stand-in for ``PVAClient``."""

    instances: list["_FakePVA"] = []

    def __init__(
        self,
        tenant_id: str,
        env_url: str,
    ) -> None:
        self.tenant_id = tenant_id
        self.env_url = env_url
        self.is_configured = True
        self.authenticate_error: Exception | None = None
        self.knowledge_sources: list[dict[str, Any]] = []
        _FakePVA.instances.append(self)

    def authenticate(self) -> None:
        if self.authenticate_error is not None:
            raise self.authenticate_error

    def get_knowledge_sources(self, bot_id: str) -> list[dict[str, Any]]:
        return list(self.knowledge_sources)


class _FakeAgentBuilder:
    """Duck-typed stand-in for ``AgentBuilderClient``."""

    instances: list["_FakeAgentBuilder"] = []

    def __init__(
        self,
        host: str,
        token: str,
        *,
        ring: str,
        tenant_id: str,
        api_version: str,
    ) -> None:
        self.host = host
        self.token = token
        self.ring = ring
        self.tenant_id = tenant_id
        self.api_version = api_version
        self.requested_agent_id: str | None = None
        _FakeAgentBuilder.instances.append(self)

    def fetch_components(self, agent_id: str) -> dict[str, Any]:
        self.requested_agent_id = agent_id
        return {
            "botComponentChanges": [
                {"component": _gc_knowledge_source()},
                {"component": {"$kind": "DialogComponent"}},
            ]
        }


def _write_config(tmp_path: Path, *, bot_id: str | None = FAKE_BOT_ID) -> None:
    local_dir = tmp_path / ".local"
    local_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "dataverseEndpoint": "https://contoso.crm.dynamics.com",
        "agent": {"botId": bot_id} if bot_id is not None else {},
    }
    (local_dir / "config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )


def _write_native_config(tmp_path: Path) -> tuple[str, str]:
    environment_id = "55a9a6bc-97d9-efba-ae20-18541f34eebb"
    tenant_id = "935884d7-bdee-469b-a461-fcc530a3ac83"
    local_dir = tmp_path / ".local"
    setup_dir = local_dir / "setup"
    setup_dir.mkdir(parents=True, exist_ok=True)
    (local_dir / "config.json").write_text(
        json.dumps(
            {
                "activeAgent": "employee-self-service",
                "environmentId": environment_id,
                "powerPlatformApiEndpoint": (
                    "https://55a9a6bc97d9efbaae2018541f34eeb."
                    "b.environment.api.test.powerplatform.com"
                ),
                "agent": {
                    "botId": FAKE_BOT_ID,
                    "slug": "employee-self-service",
                    "environmentId": environment_id,
                },
            }
        ),
        encoding="utf-8",
    )
    (setup_dir / "config.json").write_text(
        json.dumps(
            {
                "schema_version": 4,
                "environment": {
                    "id": environment_id,
                    "tenant_id": tenant_id,
                },
                "agents": {
                    FAKE_BOT_ID: {
                        "agent": {
                            "id": FAKE_BOT_ID,
                            "workspace_slug": "employee-self-service",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return environment_id, tenant_id


def _gc_knowledge_source() -> dict[str, Any]:
    """A KnowledgeSourceComponent bound to a Graph Connector source."""
    return {
        "$kind": "KnowledgeSourceComponent",
        "displayName": "Mock GC KB",
        "id": "00000000-0000-0000-0000-000000007777",
        "state": "mc",
        "status": "Active",
        "configuration": {
            "$kind": "KnowledgeSourceConfiguration",
            "source": {
                "$kind": "GraphConnectorSearchSource",
                "connectionId": {
                    "$kind": "EnvironmentVariableReference",
                    "schemaName": "msdyn_x.envVar.gc",
                },
                "connectionName": "ServiceNowKB48",
                "contentSourceDisplayName": "Mock GC KB",
                "publisherName": "Microsoft",
            },
        },
    }


@pytest.fixture(autouse=True)
def _reset_fake_pva_instances():
    _FakePVA.instances = []
    _FakeAgentBuilder.instances = []
    yield
    _FakePVA.instances = []
    _FakeAgentBuilder.instances = []


def _patch_pva(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolve_kb_connection, "PVAClient", _FakePVA)
    monkeypatch.setattr(
        resolve_kb_connection, "discover_tenant", lambda env_url: "tenant-123"
    )


def test_missing_config_reports_json_error_and_exits_nonzero(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _patch_pva(monkeypatch)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "/setup" in payload["error"]


def test_zero_bound_sources_reports_none_bound_and_exits_zero(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _patch_pva(monkeypatch)

    exit_code = resolve_kb_connection.main([])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"status": "none_bound", "connections": []}
    assert _FakePVA.instances[0].tenant_id == "tenant-123"
    assert _FakePVA.instances[0].env_url == "https://contoso.crm.dynamics.com"


def _patch_native_success(monkeypatch: pytest.MonkeyPatch, tenant_id: str) -> None:
    """Wire up native-agent auth/client fakes for the happy path.

    Individual tests override pieces of this to force specific failures.
    """
    monkeypatch.setattr(
        resolve_kb_connection,
        "discover_tenant",
        lambda _env_url: pytest.fail(
            "Native agent resolution must not require a Dataverse endpoint"
        ),
    )
    monkeypatch.setattr(
        resolve_kb_connection,
        "PVAClient",
        lambda *_args, **_kwargs: pytest.fail(
            "Native agent resolution must use AgentBuilder"
        ),
    )
    monkeypatch.setattr(
        resolve_kb_connection,
        "authenticate_flightcheck",
        lambda ring, include_connectivity: ("native-token", tenant_id),
        raising=False,
    )
    monkeypatch.setattr(
        resolve_kb_connection,
        "ring_from_environment_host",
        lambda host: "test",
        raising=False,
    )
    monkeypatch.setattr(
        resolve_kb_connection,
        "validate_environment_host",
        lambda host, ring: host,
        raising=False,
    )
    monkeypatch.setattr(
        resolve_kb_connection,
        "AgentBuilderClient",
        _FakeAgentBuilder,
        raising=False,
    )


def test_native_agent_uses_canonical_environment_and_tenant(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    environment_id, tenant_id = _write_native_config(tmp_path)
    _patch_native_success(monkeypatch, tenant_id)

    exit_code = resolve_kb_connection.main([])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "ok",
        "connections": [
            {
                "connection_name": "ServiceNowKB48",
                "state": "mc",
                "status": "Active",
            }
        ],
    }
    assert _FakeAgentBuilder.instances[0].tenant_id == tenant_id
    assert _FakeAgentBuilder.instances[0].ring == "test"
    assert _FakeAgentBuilder.instances[0].requested_agent_id == FAKE_BOT_ID
    assert _FakeAgentBuilder.instances[0].host == (
        "https://55a9a6bc97d9efbaae2018541f34eeb."
        "b.environment.api.test.powerplatform.com"
    )


def test_one_bound_source_reports_ok_and_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _patch_pva(monkeypatch)
    real_pva_init = _FakePVA.__init__

    def _init_with_source(self, tenant_id, env_url):
        real_pva_init(self, tenant_id, env_url)
        self.knowledge_sources = [_gc_knowledge_source()]

    monkeypatch.setattr(_FakePVA, "__init__", _init_with_source)

    exit_code = resolve_kb_connection.main([])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["connections"] == [
        {
            "connection_name": "ServiceNowKB48",
            "state": "mc",
            "status": "Active",
        }
    ]


def test_authenticate_failure_reports_json_error_and_exits_nonzero(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _patch_pva(monkeypatch)
    real_pva_init = _FakePVA.__init__

    def _init_with_auth_error(self, tenant_id, env_url):
        real_pva_init(self, tenant_id, env_url)
        self.authenticate_error = RuntimeError("network unreachable")

    monkeypatch.setattr(_FakePVA, "__init__", _init_with_auth_error)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "network unreachable" in payload["error"]


def test_native_agent_missing_environment_id_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    environment_id, tenant_id = _write_native_config(tmp_path)
    config_path = tmp_path / ".local" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    del config["environmentId"]
    del config["agent"]["environmentId"]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _patch_native_success(monkeypatch, tenant_id)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "environmentId" in payload["error"]


def test_native_agent_missing_bot_id_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _, tenant_id = _write_native_config(tmp_path)
    config_path = tmp_path / ".local" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    del config["agent"]["botId"]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _patch_native_success(monkeypatch, tenant_id)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "botId" in payload["error"]


def test_native_agent_missing_setup_state_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _, tenant_id = _write_native_config(tmp_path)
    (tmp_path / ".local" / "setup" / "config.json").unlink()
    _patch_native_success(monkeypatch, tenant_id)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "Could not read" in payload["error"]


def test_native_agent_invalid_json_setup_state_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _, tenant_id = _write_native_config(tmp_path)
    (tmp_path / ".local" / "setup" / "config.json").write_text(
        "{not valid json", encoding="utf-8"
    )
    _patch_native_success(monkeypatch, tenant_id)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "Could not read" in payload["error"]


def test_native_agent_wrong_schema_version_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _, tenant_id = _write_native_config(tmp_path)
    setup_path = tmp_path / ".local" / "setup" / "config.json"
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    setup["schema_version"] = 3
    setup_path.write_text(json.dumps(setup), encoding="utf-8")
    _patch_native_success(monkeypatch, tenant_id)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "schema version 4" in payload["error"]


def test_native_agent_environment_mismatch_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _, tenant_id = _write_native_config(tmp_path)
    setup_path = tmp_path / ".local" / "setup" / "config.json"
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    setup["environment"]["id"] = "11111111-1111-1111-1111-111111111111"
    setup_path.write_text(json.dumps(setup), encoding="utf-8")
    _patch_native_success(monkeypatch, tenant_id)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "does not match canonical setup state" in payload["error"]


def test_native_agent_bot_id_absent_from_canonical_agents_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _, tenant_id = _write_native_config(tmp_path)
    setup_path = tmp_path / ".local" / "setup" / "config.json"
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    setup["agents"] = {}
    setup_path.write_text(json.dumps(setup), encoding="utf-8")
    _patch_native_success(monkeypatch, tenant_id)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "not present in canonical setup state" in payload["error"]


def test_native_agent_missing_slug_fails_closed(tmp_path, monkeypatch, capsys):
    """Regression test: an absent activeAgent/agent.slug must not skip the
    slug identity check — it must fail closed instead."""
    monkeypatch.chdir(tmp_path)
    _, tenant_id = _write_native_config(tmp_path)
    config_path = tmp_path / ".local" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    del config["activeAgent"]
    del config["agent"]["slug"]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _patch_native_success(monkeypatch, tenant_id)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "No active agent slug configured" in payload["error"]


def test_native_agent_missing_power_platform_endpoint_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _, tenant_id = _write_native_config(tmp_path)
    config_path = tmp_path / ".local" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    del config["powerPlatformApiEndpoint"]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _patch_native_success(monkeypatch, tenant_id)

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "powerPlatformApiEndpoint" in payload["error"]


def test_native_agent_tenant_mismatch_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    environment_id, tenant_id = _write_native_config(tmp_path)
    _patch_native_success(monkeypatch, tenant_id)
    monkeypatch.setattr(
        resolve_kb_connection,
        "authenticate_flightcheck",
        lambda ring, include_connectivity: (
            "native-token",
            "22222222-2222-2222-2222-222222222222",
        ),
        raising=False,
    )

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "different tenant" in payload["error"]


def test_native_agent_client_construction_failure_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _, tenant_id = _write_native_config(tmp_path)
    _patch_native_success(monkeypatch, tenant_id)

    def _raise_client(*_args, **_kwargs):
        raise RuntimeError("agent builder client boom")

    monkeypatch.setattr(
        resolve_kb_connection, "AgentBuilderClient", _raise_client, raising=False
    )

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["connections"] == []
    assert "agent builder client boom" in payload["error"]


def test_native_agent_fetch_components_failure_reports_json_error(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _, tenant_id = _write_native_config(tmp_path)
    _patch_native_success(monkeypatch, tenant_id)

    class _FailingAgentBuilder(_FakeAgentBuilder):
        def fetch_components(self, agent_id: str) -> dict[str, Any]:
            raise RuntimeError("fetch_components boom")

    monkeypatch.setattr(
        resolve_kb_connection,
        "AgentBuilderClient",
        _FailingAgentBuilder,
        raising=False,
    )

    exit_code = resolve_kb_connection.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert "fetch_components boom" in payload["error"]
