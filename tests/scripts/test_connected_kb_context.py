# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for shared connected knowledge-base agent context loading."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

import connected_kb_context

BOT_ID = "00000000-0000-0000-0000-000000003333"
ENVIRONMENT_ID = "55a9a6bc-97d9-efba-ae20-18541f34eebb"
TENANT_ID = "935884d7-bdee-469b-a461-fcc530a3ac83"
NATIVE_HOST = (
    "https://55a9a6bc97d9efbaae2018541f34eeb."
    "b.environment.api.test.powerplatform.com"
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_native_state(tmp_path: Path) -> None:
    _write_json(
        tmp_path / ".local" / "config.json",
        {
            "activeAgent": "employee-self-service",
            "environmentId": ENVIRONMENT_ID,
            "powerPlatformApiEndpoint": NATIVE_HOST,
            "agentBuilderApiVersion": "2025-01-01",
            "agent": {
                "botId": BOT_ID,
                "slug": "employee-self-service",
                "environmentId": ENVIRONMENT_ID,
            },
        },
    )
    _write_json(
        tmp_path / ".local" / "setup" / "config.json",
        {
            "schema_version": 4,
            "environment": {"id": ENVIRONMENT_ID, "tenant_id": TENANT_ID},
            "agents": {
                BOT_ID: {
                    "agent": {
                        "id": BOT_ID,
                        "workspace_slug": "employee-self-service",
                    }
                }
            },
        },
    )


def test_loads_dataverse_context_with_discovered_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_json(
        tmp_path / ".local" / "config.json",
        {
            "dataverseEndpoint": " https://contoso.crm.dynamics.com ",
            "agent": {"botId": BOT_ID},
        },
    )
    discovered: list[str] = []
    monkeypatch.setattr(
        connected_kb_context,
        "discover_tenant",
        lambda endpoint: discovered.append(endpoint) or TENANT_ID,
    )

    context = connected_kb_context.load_connected_kb_context()

    assert discovered == ["https://contoso.crm.dynamics.com"]
    assert context.bot_id == BOT_ID
    assert context.tenant_id == TENANT_ID
    assert context.dataverse_endpoint == "https://contoso.crm.dynamics.com"
    assert context.environment_id == ""
    assert context.power_platform_api_endpoint == ""
    with pytest.raises(FrozenInstanceError):
        context.tenant_id = "different"  # type: ignore[misc]


def test_loads_native_context_from_schema_v4_canonical_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_native_state(tmp_path)
    monkeypatch.setattr(
        connected_kb_context,
        "discover_tenant",
        lambda _endpoint: pytest.fail("native context must not discover tenant"),
    )

    context = connected_kb_context.load_connected_kb_context()

    assert context.bot_id == BOT_ID
    assert context.tenant_id == TENANT_ID
    assert context.dataverse_endpoint == ""
    assert context.environment_id == ENVIRONMENT_ID
    assert context.power_platform_api_endpoint == NATIVE_HOST
    assert context.agent_builder_api_version == "2025-01-01"


def test_native_context_fails_closed_when_active_slug_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_native_state(tmp_path)
    config_path = tmp_path / ".local" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    del config["activeAgent"]
    del config["agent"]["slug"]
    _write_json(config_path, config)

    with pytest.raises(ValueError, match="No active agent slug configured"):
        connected_kb_context.load_connected_kb_context()


def test_native_context_rejects_environment_identity_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_native_state(tmp_path)
    setup_path = tmp_path / ".local" / "setup" / "config.json"
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    setup["environment"]["id"] = "11111111-1111-1111-1111-111111111111"
    _write_json(setup_path, setup)

    with pytest.raises(ValueError, match="does not match canonical setup state"):
        connected_kb_context.load_connected_kb_context()


def test_native_context_rejects_noncanonical_setup_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_native_state(tmp_path)
    setup_path = tmp_path / ".local" / "setup" / "config.json"
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    setup["schema_version"] = 3
    _write_json(setup_path, setup)

    with pytest.raises(ValueError, match="schema version 4"):
        connected_kb_context.load_connected_kb_context()
