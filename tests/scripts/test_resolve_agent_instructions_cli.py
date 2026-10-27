# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the ``resolve_agent_instructions`` CLI shim's JSON contract.

Runs ``main()`` in-process with the working directory switched to a
``tmp_path`` (so the ``.local/config.json`` relative-path convention is
exercised) and ``discover_tenant``/``PVAClient`` monkeypatched — no network
access.

The Island Gateway fakes expose ``get_bot_components`` directly (the raw
``botComponentChanges`` list). The shim wraps a real ``PVAClient`` in an
adapter that implements ``get_bot_components``; here we substitute a fake PVA
that already exposes that method, and patch the shim's adapter to pass the
PVA through unchanged so the resolver reads our fake changeset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import resolve_agent_instructions

FAKE_BOT_ID = "00000000-0000-0000-0000-000000003333"


class _FakePVA:
    """Duck-typed stand-in for ``PVAClient`` + its adapter.

    Exposes ``get_bot_components`` directly so the shim's adapter (patched to
    an identity wrapper) forwards resolver reads straight here.
    """

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
        self.bot_components: list[dict[str, Any]] = []
        _FakePVA.instances.append(self)

    def authenticate(self) -> None:
        if self.authenticate_error is not None:
            raise self.authenticate_error

    def get_bot_components(self, bot_id: str) -> list[dict[str, Any]]:
        return list(self.bot_components)


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
                {"component": _gc_gpt_component()},
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


def _gc_gpt_component() -> dict[str, Any]:
    """A GptComponent carrying the agent's live instruction segments."""
    return {
        "$kind": "GptComponent",
        "metadata": {
            "$kind": "GptComponentMetadata",
            "instructions": {
                "$kind": "TemplateLine",
                "segments": [
                    {
                        "$kind": "TextSegment",
                        "value": "You are a helpful agent.",
                    }
                ],
            },
        },
    }


@pytest.fixture(autouse=True)
def _reset_fake_instances():
    _FakePVA.instances = []
    _FakeAgentBuilder.instances = []
    yield
    _FakePVA.instances = []
    _FakeAgentBuilder.instances = []


def _patch_pva(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolve_agent_instructions, "PVAClient", _FakePVA)
    monkeypatch.setattr(
        resolve_agent_instructions,
        "discover_tenant",
        lambda env_url: "tenant-123",
    )
    # The adapter would wrap a real PVAClient to add get_bot_components; the
    # fake PVA already exposes it, so patch the adapter to an identity pass-through.
    monkeypatch.setattr(
        resolve_agent_instructions,
        "_PVAComponentClient",
        lambda pva: pva,
    )


def test_missing_config_reports_json_error_and_exits_nonzero(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _patch_pva(monkeypatch)

    exit_code = resolve_agent_instructions.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["instructions"] is None
    assert "/setup" in payload["error"]


def test_gpt_component_present_reports_ok_and_exits_zero(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _patch_pva(monkeypatch)
    real_init = _FakePVA.__init__

    def _init_with_component(self, tenant_id, env_url):
        real_init(self, tenant_id, env_url)
        self.bot_components = [{"component": _gc_gpt_component()}]

    monkeypatch.setattr(_FakePVA, "__init__", _init_with_component)

    exit_code = resolve_agent_instructions.main([])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["instructions"] == "You are a helpful agent."
    assert _FakePVA.instances[0].tenant_id == "tenant-123"
    assert _FakePVA.instances[0].env_url == "https://contoso.crm.dynamics.com"


def test_no_gpt_component_reports_not_found_and_exits_zero(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _patch_pva(monkeypatch)
    real_init = _FakePVA.__init__

    def _init_without_component(self, tenant_id, env_url):
        real_init(self, tenant_id, env_url)
        self.bot_components = [{"component": {"$kind": "DialogComponent"}}]

    monkeypatch.setattr(_FakePVA, "__init__", _init_without_component)

    exit_code = resolve_agent_instructions.main([])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "not_found"
    assert payload["instructions"] is None


def test_authenticate_failure_reports_json_error_and_exits_nonzero(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _patch_pva(monkeypatch)
    real_init = _FakePVA.__init__

    def _init_with_auth_error(self, tenant_id, env_url):
        real_init(self, tenant_id, env_url)
        self.authenticate_error = RuntimeError("network unreachable")

    monkeypatch.setattr(_FakePVA, "__init__", _init_with_auth_error)

    exit_code = resolve_agent_instructions.main([])

    assert exit_code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["instructions"] is None
    assert "network unreachable" in payload["error"]


def _patch_native_success(monkeypatch: pytest.MonkeyPatch, tenant_id: str) -> None:
    """Wire up native-agent auth/client fakes for the happy path."""
    monkeypatch.setattr(
        resolve_agent_instructions,
        "discover_tenant",
        lambda _env_url: pytest.fail(
            "Native agent resolution must not require a Dataverse endpoint"
        ),
    )
    monkeypatch.setattr(
        resolve_agent_instructions,
        "PVAClient",
        lambda *_args, **_kwargs: pytest.fail(
            "Native agent resolution must use AgentBuilder"
        ),
    )
    monkeypatch.setattr(
        resolve_agent_instructions,
        "authenticate_flightcheck",
        lambda ring, include_connectivity: ("native-token", tenant_id),
        raising=False,
    )
    monkeypatch.setattr(
        resolve_agent_instructions,
        "ring_from_environment_host",
        lambda host: "test",
        raising=False,
    )
    monkeypatch.setattr(
        resolve_agent_instructions,
        "validate_environment_host",
        lambda host, ring: host,
        raising=False,
    )
    monkeypatch.setattr(
        resolve_agent_instructions,
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

    exit_code = resolve_agent_instructions.main([])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "ok",
        "instructions": "You are a helpful agent.",
    }
    assert _FakeAgentBuilder.instances[0].tenant_id == tenant_id
    assert _FakeAgentBuilder.instances[0].ring == "test"
    assert _FakeAgentBuilder.instances[0].requested_agent_id == FAKE_BOT_ID
    assert _FakeAgentBuilder.instances[0].host == (
        "https://55a9a6bc97d9efbaae2018541f34eeb."
        "b.environment.api.test.powerplatform.com"
    )
