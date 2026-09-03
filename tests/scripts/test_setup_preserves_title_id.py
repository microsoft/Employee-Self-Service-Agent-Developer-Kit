# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests that setup preserves a title ID discovered by landing-page tools."""

from __future__ import annotations

import json
from pathlib import Path

import setup


def _agent_info(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "name": "Mock ESS Agent",
        "botId": "bot-1",
        "schema": "msdyn_copilotforemployeeselfservicehr",
        "managed": True,
        "url": "https://example.crm.dynamics.com",
    }
    values.update(overrides)
    return values


def _write_config(
    tmp_path: Path,
    agent_info: dict[str, object],
    slug: str = "mock-ess-agent",
) -> dict:
    setup.write_config(
        agent_info,
        slug,
        f"workspace/agents/{slug}",
        False,
    )
    return json.loads(
        (tmp_path / ".local" / "config.json").read_text(encoding="utf-8")
    )


def _seed_config(
    tmp_path: Path,
    *,
    name: str = "Mock ESS Agent",
    bot_id: str = "bot-1",
    slug: str = "mock-ess-agent",
    title_id: str = "title-1",
) -> None:
    agent = {
        "name": name,
        "botId": bot_id,
        "titleId": title_id,
        "schemaName": "msdyn_copilotforemployeeselfservicehr",
        "isManaged": True,
        "slug": slug,
        "folder": f"workspace/agents/{slug}",
    }
    local = tmp_path / ".local"
    local.mkdir(parents=True, exist_ok=True)
    (local / "config.json").write_text(
        json.dumps(
            {
                "configVersion": 1,
                "setup": "complete",
                "agent": agent,
                "activeAgent": slug,
                "agents": [agent],
                "dataverseEndpoint": "https://example.crm.dynamics.com",
            }
        ),
        encoding="utf-8",
    )


def test_write_config_preserves_discovered_title_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_config(tmp_path)

    config = _write_config(tmp_path, _agent_info(name="Renamed Agent"))

    assert config["agent"]["titleId"] == "title-1"
    assert config["agent"]["name"] == "Renamed Agent"


def test_write_config_replaces_renamed_agent_by_bot_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_config(tmp_path)

    config = _write_config(
        tmp_path,
        _agent_info(name="Renamed Agent"),
        slug="renamed-agent",
    )

    assert len(config["agents"]) == 1
    assert config["agent"]["slug"] == "renamed-agent"
    assert config["agent"]["titleId"] == "title-1"


def test_write_config_does_not_transfer_title_id_to_new_bot_with_same_slug(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _seed_config(tmp_path)

    config = _write_config(tmp_path, _agent_info(botId="bot-2"))

    assert len(config["agents"]) == 1
    assert config["agent"]["botId"] == "bot-2"
    assert "titleId" not in config["agent"]


def test_write_config_omits_unresolved_title_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    config = _write_config(tmp_path, _agent_info())

    assert "titleId" not in config["agent"]
