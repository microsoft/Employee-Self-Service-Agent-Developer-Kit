# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Exercise initial extraction and repeated refresh through the real setup CLI."""

import json
import sys

import pytest
import setup


def _run_setup(tmp_path, monkeypatch, *, refresh=False):
    components = tmp_path / "components.json"
    components.write_text(json.dumps([{
        "botcomponentid": "selected-component",
        "name": "Greeting",
        "schemaname": "selected.topic.Greeting",
        "componenttype": 9,
        "data": "kind: AdaptiveDialog\n",
    }]), encoding="utf-8")
    arguments = [
        "setup.py", "--url", "https://selected.crm.dynamics.com",
        "--bot-id", "selected-bot", "--name", "Selected Agent",
        "--schema", "selected", "--components", str(components),
    ]
    if refresh:
        arguments.append("--refresh")
    monkeypatch.setattr(sys, "argv", arguments)
    setup.main()


@pytest.mark.parametrize("saved_folder", ["", "workspace/agents/other-agent"])
def test_refresh_checkpoints_selected_folder_and_replaces_baseline(
    tmp_path, monkeypatch, saved_folder,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
    _run_setup(tmp_path, monkeypatch)
    agent = tmp_path / "workspace" / "agents" / "selected-agent"
    topic = next((agent / "topics").rglob("*.mcs.yml"))
    topic.write_text("local edit\n", encoding="utf-8")
    config_path = tmp_path / ".local" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["agent"]["folder"] = saved_folder
    config["ring"] = "prod"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    _run_setup(tmp_path, monkeypatch, refresh=True)

    assert topic.read_text(encoding="utf-8") == "kind: AdaptiveDialog\n"
    copies = list((agent / ".checkpoints").rglob(topic.name))
    assert len(copies) == 1
    assert copies[0].read_text(encoding="utf-8") == "local edit\n"
    assert (agent / ".baseline" / topic.relative_to(agent)).read_text(
        encoding="utf-8",
    ) == "kind: AdaptiveDialog\n"
    assert not (agent / ".baseline" / ".checkpoints").exists()
    refreshed = json.loads(config_path.read_text(encoding="utf-8"))
    assert refreshed["ring"] == "prod"
    assert refreshed["agent"]["botId"] == "selected-bot"


def test_refresh_stops_before_overwrite_when_checkpoint_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
    _run_setup(tmp_path, monkeypatch)
    agent = tmp_path / "workspace" / "agents" / "selected-agent"
    topic = next((agent / "topics").rglob("*.mcs.yml"))
    topic.write_text("local edit\n", encoding="utf-8")
    config_path = tmp_path / ".local" / "config.json"
    original_config = config_path.read_bytes()

    def fail_checkpoint(*args):
        raise OSError("checkpoint storage unavailable")

    monkeypatch.setattr(setup, "create_checkpoint", fail_checkpoint)

    with pytest.raises(OSError, match="checkpoint storage unavailable"):
        _run_setup(tmp_path, monkeypatch, refresh=True)

    assert topic.read_text(encoding="utf-8") == "local edit\n"
    assert config_path.read_bytes() == original_config
