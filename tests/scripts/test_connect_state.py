# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for ``scripts/connect_state.py`` — durable connect-state merges.

All writes are relative to the current directory, so every test chdirs into a
``tmp_path`` sandbox to avoid touching the real repo ``.local``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import connect_state  # noqa: E402


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sn_config():
    return connect_state.config_path("servicenow")


def test_merge_creates_file_and_preserves_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs(os.path.dirname(_sn_config()), exist_ok=True)
    with open(_sn_config(), "w", encoding="utf-8") as f:
        json.dump({"scope": {"hrsd": True}, "packs": {"installMode": "automated"}}, f)

    connect_state.record_packs("servicenow", ["hrsd"], "installed")

    data = _read(_sn_config())
    # New value merged in without dropping installMode or scope.
    assert data["packs"] == {"installMode": "automated", "hrsd": "installed"}
    assert data["scope"] == {"hrsd": True}


def test_merge_creates_missing_dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert not os.path.exists(_sn_config())
    connect_state.record_status("servicenow", "connected")
    assert _read(_sn_config())["status"] == "connected"


def test_record_connections_deep_merges(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connect_state.record_connections("servicenow", {"servicenow": {"state": "bound"}})
    connect_state.record_connections("servicenow", {"dataverse": {"state": "bound"}})
    conns = _read(_sn_config())["connections"]
    assert conns["servicenow"] == {"state": "bound"}
    assert conns["dataverse"] == {"state": "bound"}


def test_record_setup_step_shape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connect_state.record_setup_step("servicenow", "S6.2", "SN-CONN-001, SN-DV-CONN-001")
    step = _read(_sn_config())["setupStatus"]["S6.2"]
    assert step == {
        "state": "done",
        "checkpoint": "SN-CONN-001, SN-DV-CONN-001",
        "gate": "prog",
        "verifiedBy": "programmatic",
    }


def test_record_setup_step_preserves_earlier_steps(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connect_state.record_setup_step("servicenow", "S6.1", "SN-001")
    connect_state.record_setup_step("servicenow", "S6.2", "SN-DV-CONN-001")
    setup = _read(_sn_config())["setupStatus"]
    assert set(setup) == {"S6.1", "S6.2"}


def test_record_setup_step_with_note(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connect_state.record_setup_step(
        "servicenow", "S6.1", "SN-001", note="Install the ServiceNow pack.")
    step = _read(_sn_config())["setupStatus"]["S6.1"]
    assert step["note"] == "Install the ServiceNow pack."


def test_record_setup_step_omits_blank_note(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connect_state.record_setup_step("servicenow", "S6.1", "SN-001")
    assert "note" not in _read(_sn_config())["setupStatus"]["S6.1"]
    connect_state.record_setup_step("servicenow", "S6.2", "SN-001", note="")
    assert "note" not in _read(_sn_config())["setupStatus"]["S6.2"]


def test_record_setup_step_note_merge_preserves_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connect_state.record_setup_step(
        "servicenow", "S6.1", "SN-001", note="Install the ServiceNow pack.")
    connect_state.record_setup_step("servicenow", "S6.1", "SN-001", state="done")
    step = _read(_sn_config())["setupStatus"]["S6.1"]
    assert step["note"] == "Install the ServiceNow pack."


def test_record_packs_empty_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert connect_state.record_packs("servicenow", []) is None
    assert not os.path.exists(_sn_config())


def test_record_product_setup_step_shape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connect_state.record_product_setup_step(
        "servicenow", "hrsd", "S6.1", "SN-001",
        note="Install the ServiceNow HRSD extension pack into the agent.")
    ps = _read(_sn_config())["productStatus"]
    assert ps["hrsd"]["S6.1"] == {
        "state": "done",
        "checkpoint": "SN-001",
        "gate": "prog",
        "verifiedBy": "programmatic",
        "note": "Install the ServiceNow HRSD extension pack into the agent.",
    }


def test_record_product_setup_step_isolates_products(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Two products, each with their own S6.1 — one must never clobber the other.
    connect_state.record_product_setup_step("servicenow", "hrsd", "S6.1", "SN-001")
    connect_state.record_product_setup_step("servicenow", "itsm", "S6.1", "SN-001")
    # A per-product step at a different state for the same Step ID.
    connect_state.record_product_setup_step(
        "servicenow", "itsm", "S6.6", "SN-BASEURL-001",
        state="in-progress", verified_by=None)
    ps = _read(_sn_config())["productStatus"]
    assert set(ps) == {"hrsd", "itsm"}
    assert ps["hrsd"]["S6.1"]["state"] == "done"
    assert ps["itsm"]["S6.1"]["state"] == "done"
    assert ps["itsm"]["S6.6"]["state"] == "in-progress"
    assert ps["itsm"]["S6.6"]["verifiedBy"] is None
    # HRSD block untouched by the ITSM S6.6 write.
    assert "S6.6" not in ps["hrsd"]


def test_record_product_setup_step_coexists_with_shared_setupstatus(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Shared connection steps live in the flat setupStatus block; per-product
    # install/portal steps live in productStatus — both survive a deep merge.
    connect_state.record_setup_step("servicenow", "S6.2", "SN-CONN-001")
    connect_state.record_product_setup_step("servicenow", "hrsd", "S6.1", "SN-001")
    data = _read(_sn_config())
    assert data["setupStatus"]["S6.2"]["state"] == "done"
    assert data["productStatus"]["hrsd"]["S6.1"]["state"] == "done"


def test_record_product_setup_step_omits_blank_note(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connect_state.record_product_setup_step("servicenow", "hrsd", "S6.1", "SN-001")
    assert "note" not in _read(_sn_config())["productStatus"]["hrsd"]["S6.1"]
    connect_state.record_product_setup_step(
        "servicenow", "itsm", "S6.1", "SN-001", note="")
    assert "note" not in _read(_sn_config())["productStatus"]["itsm"]["S6.1"]


def test_record_product_setup_step_note_merge_preserves_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connect_state.record_product_setup_step(
        "servicenow", "hrsd", "S6.1", "SN-001", note="Install the HRSD pack.")
    # A later state-only write must not wipe the earlier note.
    connect_state.record_product_setup_step(
        "servicenow", "hrsd", "S6.1", "SN-001", state="done")
    step = _read(_sn_config())["productStatus"]["hrsd"]["S6.1"]
    assert step["note"] == "Install the HRSD pack."


def test_record_product_setup_step_missing_args_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert connect_state.record_product_setup_step("servicenow", "", "S6.1", "SN-001") is None
    assert connect_state.record_product_setup_step("servicenow", "hrsd", "", "SN-001") is None
    assert not os.path.exists(_sn_config())


def test_legacy_summary_writes_root_and_drops_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs(".local", exist_ok=True)
    with open(os.path.join(".local", "config.json"), "w", encoding="utf-8") as f:
        json.dump({"dataverseEndpoint": "https://x", "connections": {"Other": {}}}, f)

    connect_state.record_legacy_servicenow_summary({
        "instanceName": "dev184242",
        "instanceUrl": "https://dev184242.service-now.com",
        "usage": "hrsd",
        "authType": "entra_user",
        "connectedAt": "2026-07-27",
        "tenantId": None,  # dropped
    })

    root = _read(os.path.join(".local", "config.json"))
    assert root["dataverseEndpoint"] == "https://x"  # preserved
    assert root["connections"]["Other"] == {}  # preserved
    sn = root["connections"]["ServiceNow"]
    assert sn["instanceName"] == "dev184242"
    assert "tenantId" not in sn


def test_load_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert connect_state.load("servicenow") == {}


def test_merge_tolerates_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs(os.path.dirname(_sn_config()), exist_ok=True)
    with open(_sn_config(), "w", encoding="utf-8") as f:
        f.write("{ not valid json")
    # Corrupt file is treated as empty, then overwritten with a valid merge.
    connect_state.record_status("servicenow", "connected")
    assert _read(_sn_config()) == {"status": "connected"}
