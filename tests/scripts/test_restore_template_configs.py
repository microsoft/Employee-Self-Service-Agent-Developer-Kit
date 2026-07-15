# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for solutions/ess-maker-skills/scripts/restore_template_configs.py.

Coverage focus:

* ``load_backup`` schema-version gating (the failure mode that breaks paired
  restore for cross-version backups).
* ``build_unique_name_index`` produces an O(1) lookup table from query_all
  results.
* ``_call_with_refresh`` auto-retries once on ``AuthExpiredError``.
* ``main()`` end-to-end with auth + Dataverse mocked — covers the matched /
  skipped / failed accounting and the corresponding exit codes.
"""

from __future__ import annotations

import json
from unittest.mock import call

import pytest

import restore_template_configs as rt
from auth import AuthExpiredError


# ---------------------------------------------------------------------------
# load_backup - schema gate
# ---------------------------------------------------------------------------


def test_load_backup_returns_dict_on_matching_schema(tmp_path):
    payload = {
        "schemaVersion": "v1",
        "metadata": {"envUrl": "https://orgX.crm10.dynamics.com"},
        "records": [{"uniqueName": "n", "value": "v"}],
    }
    p = tmp_path / "b.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert rt.load_backup(str(p)) == payload


def test_load_backup_exits_on_schema_mismatch(tmp_path):
    payload = {"schemaVersion": "v2", "records": []}
    p = tmp_path / "b.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        rt.load_backup(str(p))
    assert exc_info.value.code == 1


def test_load_backup_exits_on_missing_schema_version(tmp_path):
    # No schemaVersion at all - same failure mode as v2: refuse to proceed.
    p = tmp_path / "b.json"
    p.write_text(json.dumps({"records": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc_info:
        rt.load_backup(str(p))
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# build_unique_name_index
# ---------------------------------------------------------------------------


def test_build_unique_name_index_maps_uniquename_to_record_id(monkeypatch):
    fake_records = [
        {
            "msdyn_employeeselfservicetemplateconfigid": "id-1",
            "msdyn_uniquename": "msdyn_HRWorkdayHCMReferenceData_A",
        },
        {
            "msdyn_employeeselfservicetemplateconfigid": "id-2",
            "msdyn_uniquename": "msdyn_ITWorkdayHCMReferenceData_B",
        },
    ]
    monkeypatch.setattr(
        rt,
        "query_all",
        lambda *args, **kwargs: fake_records,
    )
    index = rt.build_unique_name_index("https://orgX.crm.dynamics.com", "tok")
    assert index == {
        "msdyn_HRWorkdayHCMReferenceData_A": "id-1",
        "msdyn_ITWorkdayHCMReferenceData_B": "id-2",
    }


def test_build_unique_name_index_skips_records_with_no_uniquename(monkeypatch):
    fake_records = [
        {"msdyn_employeeselfservicetemplateconfigid": "id-1",
         "msdyn_uniquename": "msdyn_HRWorkdayHCMReferenceData_A"},
        {"msdyn_employeeselfservicetemplateconfigid": "id-orphan"},
    ]
    monkeypatch.setattr(rt, "query_all", lambda *a, **k: fake_records)
    index = rt.build_unique_name_index("https://orgX.crm.dynamics.com", "tok")
    assert index == {"msdyn_HRWorkdayHCMReferenceData_A": "id-1"}


# ---------------------------------------------------------------------------
# _call_with_refresh - auth holder + 401 auto-retry
# ---------------------------------------------------------------------------


def test_call_with_refresh_succeeds_on_first_try():
    # The happy path: no exception, no re-auth.
    auth = rt._AuthHolder("https://orgX.crm.dynamics.com")
    auth.token = "initial-token"
    called = []

    def fn(env, token, *_args, **_kw):
        called.append(token)
        return "ok"

    assert rt._call_with_refresh(auth, fn, "https://orgX", auth.token) == "ok"
    assert called == ["initial-token"]


def test_call_with_refresh_reauths_and_retries_once_on_401(monkeypatch):
    auth = rt._AuthHolder("https://orgX.crm.dynamics.com")
    auth.token = "initial-token"

    # Force authenticate() (called by auth.refresh()) to return a fresh token.
    monkeypatch.setattr(rt, "authenticate", lambda _u, **_kw: "refreshed-token")

    attempts = []

    def fn(env, token, *_args, **_kw):
        attempts.append(token)
        if len(attempts) == 1:
            raise AuthExpiredError("session expired")
        return "ok-after-refresh"

    result = rt._call_with_refresh(auth, fn, "https://orgX", auth.token)
    assert result == "ok-after-refresh"
    # First with the original token, then again with the refreshed one.
    assert attempts == ["initial-token", "refreshed-token"]


def test_call_with_refresh_does_not_retry_more_than_once(monkeypatch):
    # If the second attempt also 401s, the exception propagates — we never
    # loop forever.
    auth = rt._AuthHolder("https://orgX.crm.dynamics.com")
    auth.token = "initial-token"
    monkeypatch.setattr(rt, "authenticate", lambda _u, **_kw: "refreshed-token")

    def fn(env, token, *_args, **_kw):
        raise AuthExpiredError("still expired")

    with pytest.raises(AuthExpiredError):
        rt._call_with_refresh(auth, fn, "https://orgX", auth.token)


# ---------------------------------------------------------------------------
# main() end-to-end
# ---------------------------------------------------------------------------


def _write_backup(path, records, env_url="https://orgX.crm10.dynamics.com"):
    payload = {
        "schemaVersion": "v1",
        "metadata": {
            "envUrl": env_url,
            "capturedAt": "2026-06-24T15:30:00Z",
            "filterSubstring": "WorkdayHCMReferenceData_",
            "agentsDetected": ["HR"],
            "recordCountsByAgent": {"HR": len(records)},
            "recordCount": len(records),
        },
        "records": records,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_main_restores_all_matched_records(monkeypatch, tmp_path):
    backup_path = tmp_path / "b.json"
    _write_backup(
        backup_path,
        [
            {
                "id": "id-1",
                "uniqueName": "msdyn_HRWorkdayHCMReferenceData_Phone_Device_Type_ID",
                "name": "n1",
                "agent": "HR",
                "value": "<items/>",
            },
            {
                "id": "id-2",
                "uniqueName": "msdyn_HRWorkdayHCMReferenceData_Visa_ID_Type_ID",
                "name": "n2",
                "agent": "HR",
                "value": "<items><i k='X' v='Y'/></items>",
            },
        ],
    )

    monkeypatch.setattr(rt, "authenticate", lambda _u, **_kw: "tok")
    monkeypatch.setattr(
        rt,
        "query_all",
        lambda *a, **k: [
            {
                "msdyn_employeeselfservicetemplateconfigid": "env-id-1",
                "msdyn_uniquename": "msdyn_HRWorkdayHCMReferenceData_Phone_Device_Type_ID",
            },
            {
                "msdyn_employeeselfservicetemplateconfigid": "env-id-2",
                "msdyn_uniquename": "msdyn_HRWorkdayHCMReferenceData_Visa_ID_Type_ID",
            },
        ],
    )
    patches = []
    monkeypatch.setattr(
        rt, "update_record",
        lambda env, tok, entity, rec_id, body: patches.append((rec_id, body)) or True,
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "restore_template_configs.py",
            "--url", "https://orgX.crm10.dynamics.com",
            "--input", str(backup_path),
            "--yes",
            "--force",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        rt.main()
    assert exc_info.value.code == 0
    # Both env-side record IDs were PATCHed with the backup payload.
    assert ("env-id-1", {"msdyn_value": "<items/>"}) in patches
    assert (
        "env-id-2",
        {"msdyn_value": "<items><i k='X' v='Y'/></items>"},
    ) in patches


def test_main_exits_2_when_no_record_matches(monkeypatch, tmp_path):
    backup_path = tmp_path / "b.json"
    _write_backup(
        backup_path,
        [
            {
                "id": "id-1",
                "uniqueName": "msdyn_HRWorkdayHCMReferenceData_Orphan",
                "name": "n",
                "agent": "HR",
                "value": "<x/>",
            },
        ],
    )
    monkeypatch.setattr(rt, "authenticate", lambda _u, **_kw: "tok")
    monkeypatch.setattr(rt, "query_all", lambda *a, **k: [])  # env has nothing

    monkeypatch.setattr(
        "sys.argv",
        [
            "restore_template_configs.py",
            "--url", "https://orgX.crm10.dynamics.com",
            "--input", str(backup_path),
            "--yes",
            "--force",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        rt.main()
    assert exc_info.value.code == 2


def test_main_exits_1_when_input_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        [
            "restore_template_configs.py",
            "--url", "https://orgX.crm10.dynamics.com",
            "--input", str(tmp_path / "does-not-exist.json"),
            "--yes",
            "--force",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        rt.main()
    assert exc_info.value.code == 1
