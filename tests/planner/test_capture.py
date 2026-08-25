# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.capture — observe-mode detectors (pure logic + local IO)."""

from __future__ import annotations

import json

from planner.capture import (
    ask_artifact,
    config_snapshot,
    detect_agent,
    detect_config_artifacts,
    detect_environment,
    read_config,
    snapshot_config,
)

ENV_ID = "d3f10000-0000-1111-2222-333344445555"
ENDPOINT = "https://org123.crm.dynamics.com"
AGENT = {"botId": "bot-9", "name": "ESS Agent", "schemaName": "ess_agent", "folder": "agents/ess", "slug": "ess"}


def test_read_config_missing_returns_empty(tmp_path):
    assert read_config(tmp_path / "nope.json") == {}


def test_read_config_corrupt_returns_empty(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert read_config(path) == {}


def test_snapshot_config_returns_full_config(tmp_path):
    # The snapshot is the WHOLE file (deep copy) so the generic sweep sees every key.
    cfg = {"setup": "complete", "dataverseEndpoint": ENDPOINT, "environmentId": ENV_ID, "other": 1, "agent": AGENT}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    snap = snapshot_config(path)
    assert snap == cfg
    snap["agent"]["botId"] = "mutated"  # deep copy — mutating the snapshot doesn't leak
    assert config_snapshot(cfg)["agent"]["botId"] == "bot-9"


def test_detect_agent_new_clone():
    before = config_snapshot({"setup": "pending"})
    after = config_snapshot({"setup": "complete", "agent": AGENT})
    art = detect_agent(before, after, task_id="T1")
    assert art is not None
    assert art["kind"] == "Agent"
    assert art["key"] == "essAgent"
    assert art["attributes"]["botId"] == "bot-9"
    assert art["attributes"]["schemaName"] == "ess_agent"
    assert art["attributes"]["slug"] == "ess"
    assert art["inventoryRef"] == "Agent:bot-9"
    assert art["producedByTaskId"] == "T1"


def test_detect_agent_none_when_absent():
    before = config_snapshot({})
    after = config_snapshot({"setup": "complete", "environmentId": ENV_ID})
    assert detect_agent(before, after, task_id="T1") is None


def test_detect_agent_none_when_unchanged():
    snap = config_snapshot({"agent": AGENT})
    assert detect_agent(snap, snap, task_id="T1") is None


# --- generic config-artifact capture -------------------------------------------------

def test_detect_config_artifacts_env_and_agent():
    before = {}
    after = config_snapshot({"setup": "complete", "dataverseEndpoint": ENDPOINT, "environmentId": ENV_ID, "agent": AGENT})
    arts = detect_config_artifacts(before, after, task_id="T1")
    by_key = {a["key"]: a for a in arts}
    assert set(by_key) == {"primaryEnvironment", "essAgent"}
    assert by_key["primaryEnvironment"]["kind"] == "Environment"
    assert by_key["essAgent"]["kind"] == "Agent"


def test_detect_config_artifacts_generic_connection_and_custom():
    # A real before-snapshot is required for the generic sweep; the connection
    # and widget are new since `before`, so they are pinned.
    before = config_snapshot({"setup": "pending"})
    after = config_snapshot({
        "setup": "complete",
        "connection": {"connectionId": "conn-1", "name": "Workday conn"},
        "widget": {"widgetId": "w-7", "displayName": "My widget"},
        "flags": {"enabled": True},          # no id → skipped
        "note": "just a string",             # not an object → skipped
    })
    arts = detect_config_artifacts(before, after, task_id="T2")
    by_key = {a["key"]: a for a in arts}
    assert by_key["connection"]["kind"] == "Connection"
    assert by_key["connection"]["attributes"]["connectionId"] == "conn-1"
    assert by_key["connection"]["inventoryRef"] == "Connection:conn-1"
    assert by_key["widget"]["kind"] == "Custom"          # unknown shape → Custom
    assert by_key["widget"]["attributes"]["displayName"] == "My widget"
    assert "flags" not in by_key and "note" not in by_key


def test_detect_config_artifacts_list_of_objects():
    before = config_snapshot({"setup": "pending"})
    after = config_snapshot({"connections": [
        {"connectionId": "c-1", "name": "One"},
        {"connectionId": "c-2", "name": "Two"},
    ]})
    arts = detect_config_artifacts(before, after, task_id="T3")
    keys = sorted(a["key"] for a in arts)
    assert keys == ["connections.c-1", "connections.c-2"]
    assert all(a["kind"] == "Connection" for a in arts)


def test_detect_config_artifacts_empty_before_skips_generic_sweep():
    # With NO before-snapshot we can't tell new from pre-existing config, so the
    # generic sweep is skipped — only the recognised /setup outputs are pinned.
    after = config_snapshot({
        "setup": "complete",
        "dataverseEndpoint": ENDPOINT,
        "environmentId": ENV_ID,
        "agent": AGENT,
        "connection": {"connectionId": "conn-1", "name": "Workday conn"},
    })
    arts = detect_config_artifacts({}, after, task_id="T1")
    keys = {a["key"] for a in arts}
    assert keys == {"primaryEnvironment", "essAgent"}  # connection NOT swept


def test_detect_config_artifacts_never_sweeps_agents_list():
    # The discovered-agent list mirrors the active agent; it must never be swept.
    before = config_snapshot({"setup": "pending"})
    after = config_snapshot({
        "setup": "complete",
        "agent": AGENT,
        "agents": [AGENT, {"botId": "bot-2", "name": "Other", "schemaName": "other"}],
    })
    arts = detect_config_artifacts(before, after, task_id="T1")
    keys = {a["key"] for a in arts}
    assert keys == {"essAgent"}  # only the active agent, never agents.<id>


def test_detect_config_artifacts_only_changed():
    before = config_snapshot({"connection": {"connectionId": "conn-1", "name": "Workday conn"}})
    after = config_snapshot({"connection": {"connectionId": "conn-1", "name": "Workday conn"}})
    assert detect_config_artifacts(before, after, task_id="T2") == []


def test_detect_config_artifacts_none_when_empty():
    assert detect_config_artifacts({}, config_snapshot({"setup": "pending"}), task_id="T1") == []


def test_detect_environment_new_setup():
    before = {}
    after = config_snapshot({"setup": "complete", "dataverseEndpoint": ENDPOINT, "environmentId": ENV_ID})
    art = detect_environment(before, after, task_id="T1")
    assert art is not None
    assert art["kind"] == "Environment"
    assert art["attributes"]["environmentId"] == ENV_ID
    assert art["attributes"]["environmentUrl"] == ENDPOINT
    assert art["inventoryRef"] == f"Environment:{ENV_ID}"
    assert art["producedByTaskId"] == "T1"
    assert art["provenance"]["source"] == "Agent"
    assert art["state"] == "Active"


def test_detect_environment_no_change_returns_none():
    snap = {"setup": "complete", "dataverseEndpoint": ENDPOINT, "environmentId": ENV_ID}
    # before == after -> nothing new produced
    assert detect_environment(snap, dict(snap), task_id="T1") is None


def test_detect_environment_became_complete_triggers():
    before = {"setup": None, "dataverseEndpoint": ENDPOINT, "environmentId": ENV_ID}
    after = {"setup": "complete", "dataverseEndpoint": ENDPOINT, "environmentId": ENV_ID}
    art = detect_environment(before, after, task_id="T1")
    assert art is not None


def test_detect_environment_endpoint_only(monkeypatch):
    import planner.capture as capture_mod
    # No setup state to backfill from -> endpoint-only artifact, empty ref.
    monkeypatch.setattr(capture_mod, "SETUP_STATE_PATH", "does-not-exist.json")
    before = {}
    after = {"setup": "complete", "dataverseEndpoint": ENDPOINT, "environmentId": None}
    art = detect_environment(before, after, task_id="T1")
    assert art is not None
    assert art["attributes"] == {"environmentUrl": ENDPOINT}
    assert art["inventoryRef"] == ""  # no env id yet


def test_detect_environment_backfills_env_id_from_setup_state(tmp_path, monkeypatch):
    import planner.capture as capture_mod
    state = tmp_path / "setup-config.json"
    state.write_text(json.dumps({
        "environment": {"id": ENV_ID, "name": "ADK_PLANNER", "tenant_endpoint": ENDPOINT}
    }), encoding="utf-8")
    monkeypatch.setattr(capture_mod, "SETUP_STATE_PATH", str(state))
    # config.json (predating the environmentId stamp) has the endpoint only.
    after = {"setup": "complete", "dataverseEndpoint": ENDPOINT}
    art = detect_environment({}, after, task_id="T1")
    assert art is not None
    assert art["attributes"]["environmentId"] == ENV_ID
    assert art["attributes"]["environmentUrl"] == ENDPOINT
    assert art["inventoryRef"] == f"Environment:{ENV_ID}"


def test_detect_environment_backfill_skips_endpoint_mismatch(tmp_path, monkeypatch):
    import planner.capture as capture_mod
    state = tmp_path / "setup-config.json"
    state.write_text(json.dumps({
        "environment": {"id": ENV_ID, "name": "OTHER",
                        "tenant_endpoint": "https://other.crm.dynamics.com"}
    }), encoding="utf-8")
    monkeypatch.setattr(capture_mod, "SETUP_STATE_PATH", str(state))
    after = {"setup": "complete", "dataverseEndpoint": ENDPOINT}
    art = detect_environment({}, after, task_id="T1")
    assert art is not None
    assert art["inventoryRef"] == ""  # never cross-attribute another environment


def test_detect_environment_empty_after_returns_none():
    assert detect_environment({}, {}, task_id="T1") is None


def test_ask_artifact_marks_user_provenance():
    art = ask_artifact("workdayEntraApp", "EntraApp", {"appId": "abc"}, task_id="T2")
    assert art["kind"] == "EntraApp"
    assert art["attributes"] == {"appId": "abc"}
    assert art["producedByTaskId"] == "T2"
    assert art["provenance"]["source"] == "User"  # assignee supplied it
