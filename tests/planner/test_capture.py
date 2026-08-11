# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.capture — observe-mode detectors (pure logic + local IO)."""

from __future__ import annotations

import json

from planner.capture import (
    ask_artifact,
    config_snapshot,
    detect_agent,
    detect_environment,
    read_config,
    snapshot_config,
)

ENV_ID = "d3f10000-0000-1111-2222-333344445555"
ENDPOINT = "https://org123.crm.dynamics.com"
EMPTY_AGENT = {"botId": None, "name": None, "schemaName": None, "folder": None, "slug": None}
AGENT = {"botId": "bot-9", "name": "ESS Agent", "schemaName": "ess_agent", "folder": "agents/ess", "slug": "ess"}


def test_read_config_missing_returns_empty(tmp_path):
    assert read_config(tmp_path / "nope.json") == {}


def test_read_config_corrupt_returns_empty(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert read_config(path) == {}


def test_snapshot_config_reads_relevant_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"setup": "complete", "dataverseEndpoint": ENDPOINT, "environmentId": ENV_ID, "other": 1}), encoding="utf-8")
    snap = snapshot_config(path)
    assert snap == {"setup": "complete", "dataverseEndpoint": ENDPOINT, "environmentId": ENV_ID, "agent": EMPTY_AGENT}


def test_snapshot_config_includes_agent(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"setup": "complete", "agent": {**AGENT, "extra": "ignored"}}), encoding="utf-8")
    snap = snapshot_config(path)
    assert snap["agent"] == AGENT


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


def test_detect_environment_endpoint_only():
    before = {}
    after = {"setup": "complete", "dataverseEndpoint": ENDPOINT, "environmentId": None}
    art = detect_environment(before, after, task_id="T1")
    assert art is not None
    assert art["attributes"] == {"environmentUrl": ENDPOINT}
    assert art["inventoryRef"] == ""  # no env id yet


def test_detect_environment_empty_after_returns_none():
    assert detect_environment({}, {}, task_id="T1") is None


def test_ask_artifact_marks_user_provenance():
    art = ask_artifact("workdayEntraApp", "EntraApp", {"appId": "abc"}, task_id="T2")
    assert art["kind"] == "EntraApp"
    assert art["attributes"] == {"appId": "abc"}
    assert art["producedByTaskId"] == "T2"
    assert art["provenance"]["source"] == "User"  # assignee supplied it
