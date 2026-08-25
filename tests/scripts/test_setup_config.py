# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for scripts/setup.py write_config — stamping the resolved environment
GUID into `.local/config.json`.

`write_config` historically recorded only the org URL (`dataverseEndpoint`).
The locked environment GUID lives in setup state (`.local/setup/config.json`);
these tests verify `write_config` reads it back and stamps `environmentId` +
`environmentName` so downstream consumers (the planner's /setup output capture,
flightcheck) get a stable id, not just a URL.
"""

from __future__ import annotations

import json
import os

import setup

ENDPOINT = "https://org.crm.dynamics.com"
ENV_ID = "d4546776-2ea3-e81d-aecf-04ef89c5bc0b"


def _agent_info(url=ENDPOINT):
    return {
        "name": "ESS",
        "botId": "bot-1",
        "schema": "msdyn_x",
        "managed": True,
        "url": url,
    }


def _write_setup_state(env: dict) -> None:
    os.makedirs(os.path.join(".local", "setup"), exist_ok=True)
    with open(os.path.join(".local", "setup", "config.json"), "w", encoding="utf-8") as fh:
        json.dump({"environment": env}, fh)


def _read_config() -> dict:
    with open(os.path.join(".local", "config.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


def test_write_config_stamps_environment_id_from_setup_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_setup_state(
        {"id": ENV_ID, "name": "ADK_PLANNER", "tenant_endpoint": ENDPOINT}
    )
    setup.write_config(_agent_info(), "ess", "workspace/agents/ess", False)
    cfg = _read_config()
    assert cfg["dataverseEndpoint"] == ENDPOINT
    assert cfg["environmentId"] == ENV_ID
    assert cfg["environmentName"] == "ADK_PLANNER"


def test_write_config_skips_env_id_on_endpoint_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_setup_state(
        {"id": ENV_ID, "name": "OTHER", "tenant_endpoint": "https://other.crm.dynamics.com"}
    )
    setup.write_config(_agent_info(), "ess", "workspace/agents/ess", False)
    cfg = _read_config()
    assert "environmentId" not in cfg
    assert "environmentName" not in cfg


def test_write_config_no_setup_state_still_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    setup.write_config(_agent_info(), "ess", "workspace/agents/ess", False)
    cfg = _read_config()
    assert cfg["setup"] == "complete"
    assert cfg["dataverseEndpoint"] == ENDPOINT
    assert "environmentId" not in cfg


def test_write_config_preserves_existing_env_id_when_no_setup_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs(".local", exist_ok=True)
    with open(os.path.join(".local", "config.json"), "w", encoding="utf-8") as fh:
        json.dump({"environmentId": ENV_ID, "environmentName": "ADK_PLANNER"}, fh)
    setup.write_config(_agent_info(), "ess", "workspace/agents/ess", False)
    cfg = _read_config()
    assert cfg["environmentId"] == ENV_ID
    assert cfg["environmentName"] == "ADK_PLANNER"
