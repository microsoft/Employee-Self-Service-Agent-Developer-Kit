# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the ServiceNow checks that lacked coverage:
``_check_flow_status`` (SN-FLOW-*), ``_check_template_configs``
(SN-CFG-*), and ``_check_local_topics`` (SN-LOCAL-*).

The connection helper (SN-CONN-*) is covered separately in
``test_servicenow_connections.py``. Flow status and local topics are
pure-logic (flow dicts / local files); template configs reads Dataverse
via ``query_all``, which is stubbed here (the Dataverse contract itself
is exercised by the connection/env tests).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.mocks import dataverse as dv
from tests.mocks import pp_admin as pp
from tests.conftest import require_validated_mock

require_validated_mock(dv)


@pytest.fixture(autouse=True)
def _scripts_on_path():
    repo_root = Path(__file__).resolve().parents[3]
    scripts_dir = repo_root / "solutions" / "ess-maker-skills" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


def _by_id(results, cid):
    matches = [r for r in results if r.checkpoint_id == cid]
    assert len(matches) == 1, [r.checkpoint_id for r in results]
    return matches[0]


# --------------------------------------------------------------------------
# _check_flow_status — SN-FLOW-000 summary + SN-FLOW-NNN per flow
# --------------------------------------------------------------------------

def test_flow_status_all_enabled():
    from flightcheck.checks.servicenow import _check_flow_status
    flows = [
        pp.flow(display_name="ServiceNow HRSD Create Case", state="Started"),
        pp.flow(display_name="ServiceNow ITSM Create Ticket", state="Started"),
    ]
    results = _check_flow_status(SimpleNamespace(), flows)

    summary = _by_id(results, "SN-FLOW-000")
    assert summary.status == "Passed"
    assert "2 enabled, 0 disabled" in summary.result

    first = _by_id(results, "SN-FLOW-001")
    assert first.status == "Passed"
    assert "Enabled" in first.result


def test_flow_status_one_disabled_warns_and_fails_row():
    from flightcheck.checks.servicenow import _check_flow_status
    flows = [
        pp.flow(display_name="ServiceNow HRSD Create Case", state="Started"),
        pp.flow(display_name="ServiceNow ITSM Create Ticket", state="Stopped"),
    ]
    results = _check_flow_status(SimpleNamespace(), flows)

    summary = _by_id(results, "SN-FLOW-000")
    assert summary.status == "Warning"
    assert "1 enabled, 1 disabled" in summary.result
    assert "enable them in Power Automate" in summary.remediation

    disabled = _by_id(results, "SN-FLOW-002")
    assert disabled.status == "Failed"
    assert "Enable" in disabled.remediation


# --------------------------------------------------------------------------
# _check_template_configs — SN-CFG-001 + per-pack SN-CFG-010 / SN-CFG-020
# --------------------------------------------------------------------------

_ALL_SCENARIOS = [
    "ServiceNowHRSDCreateCase", "ServiceNowHRSDGetCaseDetails",
    "ServiceNowHRSDGetCasesList",
    "ServiceNowITSMCreateTicket", "ServiceNowITSMGetTicketDetails",
    "ServiceNowITSMGetUserTickets", "ServiceNowITSMUpdateTicket",
]


def test_template_configs_all_present(monkeypatch):
    import auth
    monkeypatch.setattr(
        auth, "query_all",
        lambda *a, **kw: [{"msdyn_name": s} for s in _ALL_SCENARIOS],
    )
    from flightcheck.checks.servicenow import _check_template_configs
    runner = SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")
    results = _check_template_configs(runner)

    cfg = _by_id(results, "SN-CFG-001")
    assert cfg.status == "Passed"
    assert "7 ServiceNow template config(s)" in cfg.result
    # Per-pack completeness rows.
    assert _by_id(results, "SN-CFG-010").status == "Passed"
    assert _by_id(results, "SN-CFG-020").status == "Passed"


def test_template_configs_none_found(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [])
    from flightcheck.checks.servicenow import _check_template_configs
    runner = SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")
    cfg = _by_id(_check_template_configs(runner), "SN-CFG-001")
    assert cfg.status == "NotConfigured"
    assert "No ServiceNow template configs" in cfg.result
    assert "extension pack" in cfg.remediation


def test_template_configs_skipped_without_token():
    from flightcheck.checks.servicenow import _check_template_configs
    runner = SimpleNamespace(env_url="", dv_token="")
    cfg = _by_id(_check_template_configs(runner), "SN-CFG-001")
    assert cfg.status == "Skipped"
    assert "Dataverse token not available" in cfg.result


# --------------------------------------------------------------------------
# _check_template_config_base_urls — SN-CFG-002 (portal base URL populated)
# --------------------------------------------------------------------------

def test_base_url_all_populated_passes(monkeypatch):
    import auth
    monkeypatch.setattr(
        auth, "query_all",
        lambda *a, **kw: [
            dv.template_config(name="ServiceNowHRSDGetCasesList"),
            dv.template_config(
                name="ServiceNowITSMGetUserTickets",
                value="https://contoso.service-now.com/api/now/table/incident",
            ),
        ],
    )
    from flightcheck.checks.servicenow import _check_template_config_base_urls
    runner = SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")
    cfg = _by_id(_check_template_config_base_urls(runner), "SN-CFG-002")

    assert cfg.status == "Passed"
    assert "All 2 ServiceNow template config(s)" in cfg.result
    assert "well-formed http(s) portal base URL" in cfg.result
    assert cfg.priority == "Medium"


def test_base_url_blank_value_warns(monkeypatch):
    import auth
    monkeypatch.setattr(
        auth, "query_all",
        lambda *a, **kw: [
            dv.template_config(name="ServiceNowHRSDGetCasesList"),
            dv.template_config(name="ServiceNowITSMGetUserTickets", value=""),
        ],
    )
    from flightcheck.checks.servicenow import _check_template_config_base_urls
    runner = SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")
    cfg = _by_id(_check_template_config_base_urls(runner), "SN-CFG-002")

    assert cfg.status == "Warning"
    assert "1 of 2 ServiceNow template config(s)" in cfg.result
    assert "ServiceNowITSMGetUserTickets" in cfg.result
    assert "https://<instance>.service-now.com" in cfg.remediation
    assert "omit" in cfg.remediation and "hyperlinks" in cfg.remediation


def test_base_url_unsubstituted_placeholder_warns(monkeypatch):
    import auth
    monkeypatch.setattr(
        auth, "query_all",
        lambda *a, **kw: [
            dv.template_config(
                name="ServiceNowHRSDGetCasesList",
                value="{{ServiceNowBaseUrl}}/api/now/table/sn_hr_core_case",
            ),
        ],
    )
    from flightcheck.checks.servicenow import _check_template_config_base_urls
    runner = SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")
    cfg = _by_id(_check_template_config_base_urls(runner), "SN-CFG-002")

    assert cfg.status == "Warning"
    assert "missing or malformed portal base URL" in cfg.result
    assert "ServiceNowHRSDGetCasesList" in cfg.result


def test_base_url_relative_path_only_warns(monkeypatch):
    import auth
    monkeypatch.setattr(
        auth, "query_all",
        lambda *a, **kw: [
            dv.template_config(
                name="ServiceNowITSMGetUserTickets",
                value="/api/now/table/incident",
            ),
        ],
    )
    from flightcheck.checks.servicenow import _check_template_config_base_urls
    runner = SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")
    cfg = _by_id(_check_template_config_base_urls(runner), "SN-CFG-002")

    assert cfg.status == "Warning"
    assert "ServiceNowITSMGetUserTickets" in cfg.result


def test_base_url_skipped_without_token():
    from flightcheck.checks.servicenow import _check_template_config_base_urls
    runner = SimpleNamespace(env_url="", dv_token="")
    cfg = _by_id(_check_template_config_base_urls(runner), "SN-CFG-002")
    assert cfg.status == "Skipped"
    assert "Dataverse token not available" in cfg.result


def test_base_url_none_found_not_configured(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [])
    from flightcheck.checks.servicenow import _check_template_config_base_urls
    runner = SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")
    cfg = _by_id(_check_template_config_base_urls(runner), "SN-CFG-002")
    assert cfg.status == "NotConfigured"
    assert "No ServiceNow template configs found" in cfg.result


def test_base_url_query_error_warns(monkeypatch):
    import auth

    def _boom(*a, **kw):
        raise RuntimeError("dataverse unreachable")

    monkeypatch.setattr(auth, "query_all", _boom)
    from flightcheck.checks.servicenow import _check_template_config_base_urls
    runner = SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")
    cfg = _by_id(_check_template_config_base_urls(runner), "SN-CFG-002")
    assert cfg.status == "Warning"
    assert "Unable to query template config values" in cfg.result


# --------------------------------------------------------------------------
# _check_local_topics — SN-LOCAL-001/002/003
# --------------------------------------------------------------------------

def _make_agent(tmp_path, files: dict[str, str]):
    agent = tmp_path / "workspace" / "agents" / "ess-hr"
    topics = agent / "topics"
    topics.mkdir(parents=True)
    for name, content in files.items():
        (topics / name).write_text(content, encoding="utf-8")


def test_local_topics_hrsd_and_itsm_present(tmp_path, monkeypatch):
    _make_agent(tmp_path, {
        "servicenowhrsdcreatecase.mcs.yml": "kind: x\nServiceNow case",
        "servicenowitsmcreateticket.mcs.yml": "kind: x\nServiceNow ticket",
    })
    monkeypatch.chdir(tmp_path)
    from flightcheck.checks.servicenow import _check_local_topics
    results = _check_local_topics(SimpleNamespace())

    assert _by_id(results, "SN-LOCAL-001").status == "Passed"
    assert _by_id(results, "SN-LOCAL-002").status == "Passed"   # HRSD
    assert _by_id(results, "SN-LOCAL-003").status == "Passed"   # ITSM


def test_local_topics_none_found_not_configured(tmp_path, monkeypatch):
    _make_agent(tmp_path, {"weather.mcs.yml": "kind: x\nno integration here"})
    monkeypatch.chdir(tmp_path)
    from flightcheck.checks.servicenow import _check_local_topics
    r = _by_id(_check_local_topics(SimpleNamespace()), "SN-LOCAL-001")
    assert r.status == "NotConfigured"
    assert "No ServiceNow topics found" in r.result
