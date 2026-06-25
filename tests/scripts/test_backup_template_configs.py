# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for solutions/ess-maker-skills/scripts/backup_template_configs.py.

The script's pure helpers (``infer_agent``, ``summarise``, ``to_backup_json``,
``default_output_path``) are exercised directly. The ``main()`` flow is not
unit-tested end-to-end here because it shells out to ``authenticate()`` and
``query_all()`` from ``auth.py`` — those are covered by their own tests and
the kit's VCR cassette suite. Coverage on those helpers + the JSON contract
is what matters: a malformed backup file is the failure mode that breaks the
paired restore.
"""

from __future__ import annotations

import json
import os

import pytest

import backup_template_configs as bt


# ---------------------------------------------------------------------------
# infer_agent
# ---------------------------------------------------------------------------
#
# Substring matching is order-sensitive because "_DAHRWorkdayHCMReferenceData_"
# contains "_HRWorkdayHCMReferenceData_". The implementation checks DA flavours
# first; these tests pin that ordering as a contract.


@pytest.mark.parametrize(
    ("unique_name", "expected"),
    [
        ("msdyn_HRWorkdayHCMReferenceData_Phone_Device_Type_ID", "HR"),
        ("msdyn_ITWorkdayHCMReferenceData_Country_Phone_Code_ID", "IT"),
        ("msdyn_DAHRWorkdayHCMReferenceData_Visa_ID_Type_ID", "DAHR"),
        ("msdyn_DAITWorkdayHCMReferenceData_Degree_ID", "DAIT"),
        ("msdyn_SomeUnrelatedConfig", "Unknown"),
        ("", "Unknown"),
    ],
)
def test_infer_agent(unique_name, expected):
    assert bt.infer_agent(unique_name) == expected


# ---------------------------------------------------------------------------
# summarise
# ---------------------------------------------------------------------------


def test_summarise_groups_by_agent_flavour():
    records = [
        {"msdyn_uniquename": "msdyn_HRWorkdayHCMReferenceData_A"},
        {"msdyn_uniquename": "msdyn_HRWorkdayHCMReferenceData_B"},
        {"msdyn_uniquename": "msdyn_ITWorkdayHCMReferenceData_A"},
        {"msdyn_uniquename": "msdyn_DAHRWorkdayHCMReferenceData_X"},
    ]
    assert bt.summarise(records) == {"HR": 2, "IT": 1, "DAHR": 1}


def test_summarise_handles_missing_uniquename_field():
    # Defensive: a malformed record without msdyn_uniquename should land in
    # "Unknown" rather than crash with KeyError.
    records = [{}, {"msdyn_uniquename": ""}]
    assert bt.summarise(records) == {"Unknown": 2}


# ---------------------------------------------------------------------------
# to_backup_json - the contract that restore reads
# ---------------------------------------------------------------------------


def test_to_backup_json_shape_and_record_fields():
    records = [
        {
            "msdyn_employeeselfservicetemplateconfigid": "id-1",
            "msdyn_uniquename": "msdyn_HRWorkdayHCMReferenceData_Phone_Device_Type_ID",
            "msdyn_name": "HRWorkdayHCMReferenceData_Phone_Device_Type_ID",
            "msdyn_value": "<items><i k='USA_1' v='United States'/></items>",
        },
        {
            "msdyn_employeeselfservicetemplateconfigid": "id-2",
            "msdyn_uniquename": "msdyn_ITWorkdayHCMReferenceData_Visa_ID_Type_ID",
            "msdyn_name": "ITWorkdayHCMReferenceData_Visa_ID_Type_ID",
            "msdyn_value": "<items/>",
        },
    ]
    out = bt.to_backup_json(
        "https://orgX.crm10.dynamics.com", records, "2026-06-24T15:30:00Z",
    )

    assert out["schemaVersion"] == "v1"
    assert out["metadata"]["envUrl"] == "https://orgX.crm10.dynamics.com"
    assert out["metadata"]["capturedAt"] == "2026-06-24T15:30:00Z"
    assert out["metadata"]["filterSubstring"] == "WorkdayHCMReferenceData_"
    assert out["metadata"]["agentsDetected"] == ["HR", "IT"]
    assert out["metadata"]["recordCountsByAgent"] == {"HR": 1, "IT": 1}
    assert out["metadata"]["recordCount"] == 2

    # Each record carries the four fields the restore script needs PLUS the
    # derived `agent` for surface UX. id/uniqueName/value are load-bearing
    # for restore; agent is informational.
    assert out["records"][0] == {
        "id": "id-1",
        "uniqueName": "msdyn_HRWorkdayHCMReferenceData_Phone_Device_Type_ID",
        "name": "HRWorkdayHCMReferenceData_Phone_Device_Type_ID",
        "agent": "HR",
        "value": "<items><i k='USA_1' v='United States'/></items>",
    }
    assert out["records"][1]["agent"] == "IT"


def test_to_backup_json_empty_records_is_still_valid_payload():
    out = bt.to_backup_json(
        "https://orgX.crm10.dynamics.com", [], "2026-06-24T15:30:00Z",
    )
    assert out["records"] == []
    assert out["metadata"]["recordCount"] == 0
    assert out["metadata"]["agentsDetected"] == []
    assert out["metadata"]["recordCountsByAgent"] == {}


def test_to_backup_json_round_trips_through_json_module():
    # Backup files are JSON-serialised before reaching restore. If we ever
    # serialise non-JSON-safe types (datetime, set, etc.) this catches it.
    records = [
        {
            "msdyn_employeeselfservicetemplateconfigid": "id-1",
            "msdyn_uniquename": "msdyn_HRWorkdayHCMReferenceData_X",
            "msdyn_name": "n",
            "msdyn_value": "<xml/>",
        },
    ]
    out = bt.to_backup_json("https://orgX.crm.dynamics.com", records, "2026-06-24T00:00:00Z")
    encoded = json.dumps(out)
    decoded = json.loads(encoded)
    assert decoded == out


# ---------------------------------------------------------------------------
# default_output_path
# ---------------------------------------------------------------------------


def test_default_output_path_uses_env_first_label_as_slug():
    path = bt.default_output_path(
        "https://orgXXX.crm10.dynamics.com", "2026-06-24T15:30:00Z",
    )
    expected = os.path.join(
        bt.DEFAULT_OUTPUT_DIR, "orgXXX-20260624T153000Z.json",
    )
    assert path == expected


def test_default_output_path_falls_back_when_env_is_odd():
    # If the URL is malformed (no scheme separator), the slug should fall
    # back to "env" rather than crash.
    path = bt.default_output_path("orgX.crm.dynamics.com", "2026-06-24T00:00:00Z")
    assert path.endswith("env-20260624T000000Z.json")


# ---------------------------------------------------------------------------
# atomic_write_json
# ---------------------------------------------------------------------------


def test_atomic_write_json_creates_parent_dir_and_writes_indented(tmp_path):
    nested = tmp_path / "subdir1" / "subdir2" / "out.json"
    bt.atomic_write_json(str(nested), {"hello": "world", "n": 1})
    assert nested.exists()
    parsed = json.loads(nested.read_text(encoding="utf-8"))
    assert parsed == {"hello": "world", "n": 1}
    # No leftover tmp file.
    assert not (tmp_path / "subdir1" / "subdir2" / "out.json.tmp").exists()


def test_atomic_write_json_overwrites_existing_file(tmp_path):
    target = tmp_path / "out.json"
    target.write_text('{"old": true}', encoding="utf-8")
    bt.atomic_write_json(str(target), {"new": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"new": True}


# ---------------------------------------------------------------------------
# utc_iso_now
# ---------------------------------------------------------------------------


def test_utc_iso_now_is_z_suffixed_seconds_precision():
    stamp = bt.utc_iso_now()
    # Format: YYYY-MM-DDTHH:MM:SSZ — 20 characters total.
    assert len(stamp) == 20
    assert stamp.endswith("Z")
    assert "T" in stamp
    # No microseconds.
    assert "." not in stamp


# ---------------------------------------------------------------------------
# main() smoke test - the integration-y bit
# ---------------------------------------------------------------------------


def test_main_writes_backup_file_with_monkeypatched_dataverse(
    monkeypatch, tmp_path,
):
    """End-to-end main() smoke test with auth and query mocked out."""
    fake_records = [
        {
            "msdyn_employeeselfservicetemplateconfigid": "id-1",
            "msdyn_uniquename": "msdyn_HRWorkdayHCMReferenceData_Phone_Device_Type_ID",
            "msdyn_name": "HRWorkdayHCMReferenceData_Phone_Device_Type_ID",
            "msdyn_value": "<items/>",
        },
    ]
    monkeypatch.setattr(bt, "authenticate", lambda _url: "fake-token")
    monkeypatch.setattr(
        bt,
        "query_all",
        lambda env_url, token, entity_set, select, filter_expr=None: fake_records,
    )

    out_path = tmp_path / "test-backup.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "backup_template_configs.py",
            "--url", "https://orgX.crm10.dynamics.com",
            "--output", str(out_path),
            "--yes",
        ],
    )

    # main() exits via sys.exit(); a clean run is sys.exit() without arg or
    # sys.exit(0). The fake_records path doesn't trigger sys.exit explicitly,
    # so it returns normally.
    bt.main()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schemaVersion"] == "v1"
    assert payload["metadata"]["recordCount"] == 1
    assert payload["records"][0]["uniqueName"].startswith(
        "msdyn_HRWorkdayHCMReferenceData_",
    )


def test_main_exits_2_when_no_records_match(monkeypatch, tmp_path):
    monkeypatch.setattr(bt, "authenticate", lambda _url: "fake-token")
    monkeypatch.setattr(
        bt,
        "query_all",
        lambda env_url, token, entity_set, select, filter_expr=None: [],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "backup_template_configs.py",
            "--url", "https://orgX.crm10.dynamics.com",
            "--yes",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        bt.main()
    assert exc_info.value.code == 2
