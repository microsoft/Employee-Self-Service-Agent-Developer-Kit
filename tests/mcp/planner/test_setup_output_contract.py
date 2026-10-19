# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline contract: actual setup writer -> capture -> Planner completion."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from planner.capture import detect_config_artifacts, read_config
from planner.sync import to_remote_output
from setup_state import JsonSetupStateRepository, SetupState, SetupWorkflow

SOLUTION = Path(__file__).resolve().parents[3] / "solutions" / "ess-maker-skills"
sys.path.insert(0, str(SOLUTION / "src" / "mcp" / "agentconfig_core"))
sys.path.insert(0, str(SOLUTION / "src" / "mcp" / "agentconfig_planner"))
from planner_surface import _normalize_completion_outputs  # noqa: E402

_spec = importlib.util.spec_from_file_location("planner_contract_setup", SOLUTION / "scripts" / "setup.py")
setup_writer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(setup_writer)


def _agent(**overrides):
    return {
        "botId": "test-bot", "name": "ESS HR", "schema": "test_ess",
        "managed": True, "url": "https://test.crm.dynamics.com", **overrides,
    }


@pytest.mark.parametrize("source", ["explicit", "foundation", "existing"])
def test_setup_metadata_can_be_consumed_by_real_completion_validator(tmp_path, monkeypatch, source):
    monkeypatch.chdir(tmp_path)
    agent = _agent()
    if source == "explicit":
        agent["environmentId"] = "test-environment"
    elif source == "foundation":
        state = SetupState()
        SetupWorkflow.set_scope(
            state, environment_id="test-environment", environment_name="Test",
            environment_type="Dev", tenant_endpoint=agent["url"],
        )
        JsonSetupStateRepository(tmp_path / ".local" / "setup" / "config.json").save(state)
    else:
        (tmp_path / ".local").mkdir()
        (tmp_path / ".local" / "config.json").write_text(json.dumps({
            "environmentId": "test-environment", "dataverseEndpoint": agent["url"] + "/",
        }), encoding="utf-8")
    setup_writer.write_config(agent, "ess-hr", "workspace\\agents\\ess-hr", False)
    config = read_config(tmp_path / ".local" / "config.json")
    artifacts = detect_config_artifacts({}, config, task_id="setup")
    outputs = _normalize_completion_outputs([to_remote_output(a) for a in artifacts])
    by_key = {output["key"]: output for output in outputs}
    assert {"key": "environmentId", "value": "test-environment"} in by_key["primaryEnvironment"]["attributes"]
    assert {"key": "environmentUrl", "value": agent["url"]} in by_key["primaryEnvironment"]["attributes"]
    assert by_key["essAgent"]["kind"] == "Custom"
    assert {"key": "artifactType", "value": "Agent"} in by_key["essAgent"]["attributes"]
    assert config["agent"]["botId"] == "test-bot"


def test_environment_id_is_not_reused_for_a_different_endpoint(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".local").mkdir()
    path = tmp_path / ".local" / "config.json"
    path.write_text(json.dumps({
        "environmentId": "old-id", "dataverseEndpoint": "https://other.crm.dynamics.com",
    }), encoding="utf-8")
    setup_writer.write_config(_agent(), "ess", "workspace\\agents\\ess", False)
    assert "environmentId" not in read_config(path)
    assert "ID has not been verified" in capsys.readouterr().err


def test_corrupt_existing_config_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".local").mkdir()
    path = tmp_path / ".local" / "config.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError):
        setup_writer.write_config(_agent(), "ess", "workspace\\agents\\ess", False)
    assert path.read_text(encoding="utf-8") == "{broken"
