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

import json
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

def _base_url_cfg(name, url):
    """A root extension-pack config that carries the portal base URL."""
    return dv.template_config(
        name=name, value=json.dumps({"ServiceNowPortalBaseURI": url})
    )


def _scenario_cfg(name):
    """A scenario / field-mapping config — never carries the base URL."""
    return dv.template_config(
        name=name, value=json.dumps({"Scenario": name, "Table": "sn_hr_core_case"})
    )


def _route(*, configs=None, env_defs=None, env_vals=None):
    """Build a query_all stub that routes by Dataverse entity set."""
    configs = configs or []
    env_defs = env_defs or []
    env_vals = env_vals or []

    def _q(*a, **kw):
        entity = a[2] if len(a) > 2 else kw.get("entity_set")
        if entity == "msdyn_employeeselfservicetemplateconfigs":
            return configs
        if entity == "environmentvariabledefinitions":
            return env_defs
        if entity == "environmentvariablevalues":
            return env_vals
        return []

    return _q


_HRSD_CFG = "msdyn_ServiceNowHRSD"
_ITSM_CFG = "msdyn_ServiceNowITSM"
_DEF_HRSD = "00000000-0000-0000-0000-0000000060a1"
_DEF_ITSM = "00000000-0000-0000-0000-0000000060a2"


def _env_present(hrsd_url=None, itsm_url=None):
    """Build (defs, vals) for the ServiceNow*PortalBaseURI env vars."""
    defs, vals = [], []
    if hrsd_url is not None:
        defs.append(dv.env_var_def(
            definition_id=_DEF_HRSD, schema_name="ServiceNowHRSDPortalBaseURI"))
        vals.append(dv.env_var_value(
            definition_id=_DEF_HRSD, schema_name="ServiceNowHRSDPortalBaseURI",
            value=hrsd_url))
    if itsm_url is not None:
        defs.append(dv.env_var_def(
            definition_id=_DEF_ITSM, schema_name="ServiceNowITSMPortalBaseURI"))
        vals.append(dv.env_var_value(
            definition_id=_DEF_ITSM, schema_name="ServiceNowITSMPortalBaseURI",
            value=itsm_url))
    return defs, vals


def _run_base_url(monkeypatch, stub):
    import auth
    monkeypatch.setattr(auth, "query_all", stub)
    from flightcheck.checks.servicenow import _check_template_config_base_urls
    runner = SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")
    return _by_id(_check_template_config_base_urls(runner), "SN-CFG-002")


def test_base_url_all_populated_passes(monkeypatch):
    cfg = _run_base_url(monkeypatch, _route(configs=[
        _base_url_cfg(_HRSD_CFG, "https://contoso.service-now.com/sp"),
        _base_url_cfg(_ITSM_CFG, "https://contoso.service-now.com/esc"),
    ]))
    assert cfg.status == "Passed"
    assert "All 2 ServiceNow base-URL template config(s)" in cfg.result
    assert "well-formed http(s) portal base URL" in cfg.result
    assert cfg.priority == "Medium"


def test_base_url_blank_value_warns(monkeypatch):
    cfg = _run_base_url(monkeypatch, _route(configs=[
        _base_url_cfg(_HRSD_CFG, "https://contoso.service-now.com/sp"),
        _base_url_cfg(_ITSM_CFG, ""),
    ]))
    assert cfg.status == "Warning"
    assert "1 of 2 ServiceNow base-URL config(s)" in cfg.result
    assert _ITSM_CFG in cfg.result
    assert "https://<instance>.service-now.com" in cfg.remediation
    assert "omit" in cfg.remediation and "hyperlinks" in cfg.remediation


def test_base_url_unsubstituted_placeholder_warns(monkeypatch):
    # Scheme-prefixed placeholder: the host is still a template token, so
    # this must NOT pass as a populated base URL.
    cfg = _run_base_url(monkeypatch, _route(configs=[
        _base_url_cfg(_HRSD_CFG, "https://{{ServiceNowBaseUrl}}/sp"),
    ]))
    assert cfg.status == "Warning"
    assert "missing or malformed portal base URL" in cfg.result
    assert _HRSD_CFG in cfg.result
    assert "https://<instance>.service-now.com" in cfg.remediation
    assert "omit" in cfg.remediation and "hyperlinks" in cfg.remediation


def test_base_url_bare_placeholder_token_warns(monkeypatch):
    cfg = _run_base_url(monkeypatch, _route(configs=[
        _base_url_cfg(_HRSD_CFG, "{{ServiceNowBaseUrl}}/sp"),
    ]))
    assert cfg.status == "Warning"
    assert _HRSD_CFG in cfg.result
    assert "https://<instance>.service-now.com" in cfg.remediation
    assert "omit" in cfg.remediation and "hyperlinks" in cfg.remediation


def test_base_url_relative_path_only_warns(monkeypatch):
    cfg = _run_base_url(monkeypatch, _route(configs=[
        _base_url_cfg(_ITSM_CFG, "/api/now/table/incident"),
    ]))
    assert cfg.status == "Warning"
    assert _ITSM_CFG in cfg.result
    assert "https://<instance>.service-now.com" in cfg.remediation
    assert "omit" in cfg.remediation and "hyperlinks" in cfg.remediation


def test_base_url_skipped_without_token():
    from flightcheck.checks.servicenow import _check_template_config_base_urls
    runner = SimpleNamespace(env_url="", dv_token="")
    cfg = _by_id(_check_template_config_base_urls(runner), "SN-CFG-002")
    assert cfg.status == "Skipped"
    assert "Dataverse token not available" in cfg.result


def test_base_url_none_found_not_configured(monkeypatch):
    cfg = _run_base_url(monkeypatch, _route(configs=[]))
    assert cfg.status == "NotConfigured"
    assert "No ServiceNow template config carries a portal base URL" in cfg.result


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
    assert "Re-run /flightcheck" in cfg.remediation
    assert "Dataverse is reachable" in cfg.remediation


def test_base_url_scenario_configs_ignored(monkeypatch):
    # Regression for the 19-false-positive bug: scenario / field-mapping
    # configs carry no ServiceNowPortalBaseURI field and must never be flagged.
    cfg = _run_base_url(monkeypatch, _route(configs=[
        _scenario_cfg("msdyn_ServiceNowHRSDCreateCasePayroll"),
        _scenario_cfg("msdyn_ITHelpdeskServiceNowITSMCreateTicket"),
        _scenario_cfg("msdyn_ServiceNowLiveAgent"),
    ]))
    assert cfg.status == "NotConfigured"
    assert "No ServiceNow template config carries a portal base URL" in cfg.result


def test_base_url_only_flags_root_config_amongst_scenarios(monkeypatch):
    # Mirrors the real PROD tenant: many scenario configs plus two root
    # configs, one root empty. Only the empty root is flagged.
    cfg = _run_base_url(monkeypatch, _route(configs=[
        _scenario_cfg("msdyn_ServiceNowHRSDCreateCaseCore"),
        _scenario_cfg("msdyn_ServiceNowHRSDGetUserCases"),
        _scenario_cfg("msdyn_ITHelpdeskServiceNowITSMGetUserTickets"),
        _base_url_cfg(_HRSD_CFG, ""),
        _base_url_cfg(_ITSM_CFG, "https://contoso.service-now.com/esc"),
    ]))
    assert cfg.status == "Warning"
    assert "1 of 2 ServiceNow base-URL config(s)" in cfg.result
    assert _HRSD_CFG in cfg.result
    assert "CreateCaseCore" not in cfg.result
    assert "GetUserCases" not in cfg.result
    assert "https://<instance>.service-now.com" in cfg.remediation
    assert "omit" in cfg.remediation and "hyperlinks" in cfg.remediation


def test_base_url_defers_to_env_var_when_both_migrated(monkeypatch):
    # Both template configs empty, but both env vars hold valid URLs
    # (Option B). SN-CFG-002 defers entirely — no false WARN.
    defs, vals = _env_present(
        hrsd_url="https://contoso.service-now.com/sp",
        itsm_url="https://contoso.service-now.com/esc",
    )
    cfg = _run_base_url(monkeypatch, _route(
        configs=[_base_url_cfg(_HRSD_CFG, ""), _base_url_cfg(_ITSM_CFG, "")],
        env_defs=defs, env_vals=vals,
    ))
    assert cfg.status == "Passed"
    assert "superseded" in cfg.result
    assert "SN-URL-001/002" in cfg.result


def test_base_url_partial_env_deference_warns_on_unmigrated(monkeypatch):
    # HRSD moved to env var (defer); ITSM still an empty template config with
    # no env var -> WARN on ITSM only, noting HRSD superseded.
    defs, vals = _env_present(hrsd_url="https://contoso.service-now.com/sp")
    cfg = _run_base_url(monkeypatch, _route(
        configs=[_base_url_cfg(_HRSD_CFG, ""), _base_url_cfg(_ITSM_CFG, "")],
        env_defs=defs, env_vals=vals,
    ))
    assert cfg.status == "Warning"
    assert "1 of 2 ServiceNow base-URL config(s)" in cfg.result
    assert _ITSM_CFG in cfg.result
    assert "1 superseded" in cfg.result
    assert "https://<instance>.service-now.com" in cfg.remediation
    assert "omit" in cfg.remediation and "hyperlinks" in cfg.remediation


def test_base_url_from_env_var_only_no_template_config(monkeypatch):
    # No template config carries the field, but the env var holds a valid URL.
    defs, vals = _env_present(
        hrsd_url="https://contoso.service-now.com/sp",
        itsm_url="https://contoso.service-now.com/esc",
    )
    cfg = _run_base_url(monkeypatch, _route(
        configs=[_scenario_cfg("msdyn_ServiceNowHRSDCreateCaseCore")],
        env_defs=defs, env_vals=vals,
    ))
    assert cfg.status == "Passed"
    assert "environment variable" in cfg.result
    assert "SN-URL-001/002" in cfg.result


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
