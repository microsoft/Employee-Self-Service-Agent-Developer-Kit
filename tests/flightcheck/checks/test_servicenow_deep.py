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

from tests.mocks import pp_admin as pp


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
# SN-CONN-OBJECTS-001 — pre-install ServiceNow + Dataverse connections
# --------------------------------------------------------------------------

def _connection_runner(connections):
    admin = SimpleNamespace(get_connections=lambda env_id: connections)
    return SimpleNamespace(pp_admin=admin, env_id="env-1")


def test_connection_objects_both_connected_passes():
    from flightcheck.checks.servicenow import _check_connection_objects
    connections = [
        pp.connection(api_name="shared_service-now", display_name="ServiceNow"),
        pp.connection(
            api_name="shared_commondataserviceforapps",
            display_name="Microsoft Dataverse",
        ),
    ]
    result = _by_id(
        _check_connection_objects(_connection_runner(connections)),
        "SN-CONN-OBJECTS-001",
    )
    assert result.status == "Passed"


def test_connection_objects_missing_dataverse_not_configured():
    from flightcheck.checks.servicenow import _check_connection_objects
    connections = [
        pp.connection(api_name="shared_service-now", display_name="ServiceNow"),
    ]
    result = _by_id(
        _check_connection_objects(_connection_runner(connections)),
        "SN-CONN-OBJECTS-001",
    )
    assert result.status == "NotConfigured"
    assert "Microsoft Dataverse" in result.result


def test_connection_objects_unhealthy_servicenow_fails():
    from flightcheck.checks.servicenow import _check_connection_objects
    connections = [
        pp.connection(
            api_name="shared_service-now",
            display_name="ServiceNow",
            status="Error",
        ),
        pp.connection(
            api_name="shared_commondataserviceforapps",
            display_name="Microsoft Dataverse",
        ),
    ]
    result = _by_id(
        _check_connection_objects(_connection_runner(connections)),
        "SN-CONN-OBJECTS-001",
    )
    assert result.status == "Failed"
    assert "ServiceNow" in result.result


def test_connection_objects_unreadable_inventory_is_manual():
    from flightcheck.checks.servicenow import _check_connection_objects
    runner = SimpleNamespace(pp_admin=None, env_id="env-1")
    result = _by_id(_check_connection_objects(runner), "SN-CONN-OBJECTS-001")
    assert result.status == "Manual"


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


def test_flow_status_labels_each_row_by_product():
    """Each SN-FLOW row must carry the correct [HRSD]/[ITSM] product label."""
    from flightcheck.checks.servicenow import _check_flow_status
    flows = [
        pp.flow(display_name="ServiceNow HRSD Create Case", state="Started"),
        pp.flow(display_name="ServiceNow ITSM Create Ticket", state="Started"),
    ]
    results = _check_flow_status(SimpleNamespace(), flows)
    assert "[HRSD]" in _by_id(results, "SN-FLOW-001").description
    assert "[ITSM]" in _by_id(results, "SN-FLOW-002").description


def test_flow_status_itsm_not_misclassified_by_host_prefix():
    """An ``ESS HR ServiceNow ITSM ...`` name must classify as ITSM, not HRSD.

    Regression: the old classifier checked the ``HR Service`` substring first,
    so the ``HR ServiceNow`` host-agent prefix pulled real ITSM flows into HRSD.
    """
    from flightcheck.checks.servicenow import _check_flow_status
    flows = [
        pp.flow(display_name="ESS HR ServiceNow ITSM Common Orchestrator",
                state="Started"),
        pp.flow(display_name="ESS HR ServiceNow HRSD Case Orchestrator",
                state="Started"),
    ]
    results = _check_flow_status(SimpleNamespace(), flows)
    assert "[ITSM]" in _by_id(results, "SN-FLOW-001").description
    assert "[HRSD]" in _by_id(results, "SN-FLOW-002").description

    summary = _by_id(results, "SN-FLOW-000")
    assert "1 HRSD" in summary.result
    assert "1 ITSM" in summary.result


def test_categorize_servicenow_flows_by_explicit_token():
    """Direct coverage of the shared categorizer: token wins over host prefix."""
    from flightcheck.checks.external_systems import _categorize_servicenow_flows
    flows = [
        pp.flow(display_name="ESS HR ServiceNow ITSM Common Orchestrator"),
        pp.flow(display_name="servicenow hrsd create case"),  # case-insensitive
        pp.flow(display_name="ServiceNow Generic Helper"),     # neither token
    ]
    hrsd, itsm, other = _categorize_servicenow_flows(flows)
    assert [f["properties"]["displayName"] for f in itsm] == [
        "ESS HR ServiceNow ITSM Common Orchestrator"]
    assert [f["properties"]["displayName"] for f in hrsd] == [
        "servicenow hrsd create case"]
    assert [f["properties"]["displayName"] for f in other] == [
        "ServiceNow Generic Helper"]


# --------------------------------------------------------------------------
# _check_pack_install — SN-PKG-001 summary + per-product SN-PKG-010 / SN-PKG-020
# (S6.1). Deterministic install evidence = per-product template-config records.
# --------------------------------------------------------------------------

_HRSD_SCENARIOS = [
    "ServiceNowHRSDCreateCase", "ServiceNowHRSDGetCaseDetails",
    "ServiceNowHRSDGetUserCases",
]
_ITSM_SCENARIOS = [
    "ServiceNowITSMCreateTicket", "ServiceNowITSMGetTicketDetails",
    "ServiceNowITSMGetUserTickets", "ServiceNowITSMUpdateTicket",
]


def _pack_runner():
    return SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")


def _patch_pack_configs(monkeypatch, names):
    import auth
    monkeypatch.setattr(
        auth, "query_all", lambda *a, **kw: [{"msdyn_name": s} for s in names])


def test_pack_install_both_products(monkeypatch):
    _patch_pack_configs(monkeypatch, _HRSD_SCENARIOS + _ITSM_SCENARIOS)
    from flightcheck.checks.servicenow import _check_pack_install
    results = _check_pack_install(_pack_runner())
    summary = _by_id(results, "SN-PKG-001")
    assert summary.status == "Passed"
    assert "HRSD" in summary.result and "ITSM" in summary.result
    assert _by_id(results, "SN-PKG-010").status == "Passed"
    assert _by_id(results, "SN-PKG-020").status == "Passed"


def test_pack_install_hr_only(monkeypatch):
    """HR-only scope passes with ITSM reported as not installed, not a failure."""
    _patch_pack_configs(monkeypatch, _HRSD_SCENARIOS)
    from flightcheck.checks.servicenow import _check_pack_install
    results = _check_pack_install(_pack_runner())
    summary = _by_id(results, "SN-PKG-001")
    assert summary.status == "Passed"
    assert "installed for HRSD" in summary.result
    assert "Not installed: ITSM" in summary.result
    assert _by_id(results, "SN-PKG-010").status == "Passed"
    assert _by_id(results, "SN-PKG-020").status == "NotConfigured"


def test_pack_install_it_only(monkeypatch):
    _patch_pack_configs(monkeypatch, _ITSM_SCENARIOS)
    from flightcheck.checks.servicenow import _check_pack_install
    results = _check_pack_install(_pack_runner())
    summary = _by_id(results, "SN-PKG-001")
    assert summary.status == "Passed"
    assert "installed for ITSM" in summary.result
    assert "Not installed: HRSD" in summary.result
    assert _by_id(results, "SN-PKG-010").status == "NotConfigured"
    assert _by_id(results, "SN-PKG-020").status == "Passed"


def test_pack_install_partial_fails(monkeypatch):
    """A pack missing some of its template configs is a partial install."""
    _patch_pack_configs(
        monkeypatch, _HRSD_SCENARIOS[:1] + _ITSM_SCENARIOS)  # HRSD missing 2
    from flightcheck.checks.servicenow import _check_pack_install
    results = _check_pack_install(_pack_runner())
    summary = _by_id(results, "SN-PKG-001")
    assert summary.status == "Warning"
    assert "partially installed for HRSD" in summary.result
    hrsd = _by_id(results, "SN-PKG-010")
    assert hrsd.status == "Failed"
    assert "1/3" in hrsd.result
    assert "Reinstall" in hrsd.remediation
    # ITSM is fully present and must still pass.
    assert _by_id(results, "SN-PKG-020").status == "Passed"


def test_pack_install_none_installed(monkeypatch):
    _patch_pack_configs(monkeypatch, [])
    from flightcheck.checks.servicenow import _check_pack_install
    results = _check_pack_install(_pack_runner())
    summary = _by_id(results, "SN-PKG-001")
    assert summary.status == "NotConfigured"
    assert "no pack is installed" in summary.result.lower()
    assert _by_id(results, "SN-PKG-010").status == "NotConfigured"
    assert _by_id(results, "SN-PKG-020").status == "NotConfigured"


def test_pack_install_reinstall_recovers_partial(monkeypatch):
    """After a reinstall recreates the missing configs, the pack passes again."""
    from flightcheck.checks.servicenow import _check_pack_install
    # Before: HRSD partial.
    _patch_pack_configs(monkeypatch, _HRSD_SCENARIOS[:1])
    before = _by_id(_check_pack_install(_pack_runner()), "SN-PKG-010")
    assert before.status == "Failed"
    # After reinstall: all HRSD configs present.
    _patch_pack_configs(monkeypatch, _HRSD_SCENARIOS)
    after = _by_id(_check_pack_install(_pack_runner()), "SN-PKG-010")
    assert after.status == "Passed"


def test_pack_install_skipped_without_token():
    from flightcheck.checks.servicenow import _check_pack_install
    runner = SimpleNamespace(env_url="", dv_token="")
    summary = _by_id(_check_pack_install(runner), "SN-PKG-001")
    assert summary.status == "Skipped"
    assert "Dataverse token not available" in summary.result


def test_pack_install_query_error_warns(monkeypatch):
    import auth
    def _boom(*a, **kw):
        raise RuntimeError("dv down")
    monkeypatch.setattr(auth, "query_all", _boom)
    from flightcheck.checks.servicenow import _check_pack_install
    summary = _by_id(_check_pack_install(_pack_runner()), "SN-PKG-001")
    assert summary.status == "Warning"
    assert "Unable to read" in summary.result


def test_pack_install_wrapper_registered_and_self_contained(monkeypatch):
    """--checkpoint SN-PKG-001 resolves and the wrapper needs no flow gate."""
    from flightcheck import registry
    assert registry.resolve("SN-PKG-001").key == "SN-PKG-001"
    _patch_pack_configs(monkeypatch, _HRSD_SCENARIOS + _ITSM_SCENARIOS)
    from flightcheck.checks.servicenow import run_servicenow_pack_checks
    summary = _by_id(run_servicenow_pack_checks(_pack_runner()), "SN-PKG-001")
    assert summary.status == "Passed"


# --------------------------------------------------------------------------
# _check_template_configs — SN-CFG-001 + per-pack SN-CFG-010 / SN-CFG-020
# --------------------------------------------------------------------------

_ALL_SCENARIOS = [
    "ServiceNowHRSDCreateCase", "ServiceNowHRSDGetCaseDetails",
    "ServiceNowHRSDGetUserCases",
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


# --------------------------------------------------------------------------
# _check_dataverse_connection — SN-DV-CONN-001 (scoped to the ServiceNow pack's
# OWN Dataverse reference, matched by the 'sharedcommondataserviceforapps'
# logical-name marker). Deliberately EXCLUDES the base-agent 'msdyn_Dataverse'
# reference and other system Dataverse references, which are out of scope for
# the ServiceNow S6.2 step and routinely ship unbound in a healthy setup.
# --------------------------------------------------------------------------

_DV_CONNECTOR = (
    "/providers/Microsoft.PowerApps/apis/shared_commondataserviceforapps"
)


def _dv_ref(logical, *, connectionid="c1", statuscode=1, connector=_DV_CONNECTOR):
    return {
        "connectionreferencelogicalname": logical,
        "connectionreferencedisplayname": logical,
        "connectorid": connector,
        "connectionid": connectionid,
        "statuscode": statuscode,
    }


def _dv_runner():
    return SimpleNamespace(
        env_url="https://org.crm.dynamics.com", dv_token="t",
        pp_admin=None, env_id="env-1",
    )


def test_dataverse_connection_all_bound_active(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        # Base-agent system reference — UNBOUND, but out of scope for the
        # ServiceNow gate, so it must NOT fail this check.
        _dv_ref("msdyn_Dataverse", connectionid=None),
        _dv_ref("new_sharedcommondataserviceforapps_41c83"),
        # A non-Dataverse ref that must be ignored.
        _dv_ref("msdyn_service_now",
                connector="/providers/x/apis/shared_service-now"),
    ])
    from flightcheck.checks.servicenow import _check_dataverse_connection
    r = _by_id(_check_dataverse_connection(_dv_runner()), "SN-DV-CONN-001")
    assert r.status == "Passed"
    assert "All 1 Dataverse connection reference(s)" in r.result


def test_dataverse_connection_none_found_not_configured(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        # Base-agent Dataverse reference is present but is NOT the pack's own
        # reference — the gate is scoped to the pack reference, so the pack's
        # reference being absent is NotConfigured even though msdyn_Dataverse
        # exists on the same connector.
        _dv_ref("msdyn_Dataverse"),
        _dv_ref("msdyn_service_now",
                connector="/providers/x/apis/shared_service-now"),
    ])
    from flightcheck.checks.servicenow import _check_dataverse_connection
    r = _by_id(_check_dataverse_connection(_dv_runner()), "SN-DV-CONN-001")
    assert r.status == "NotConfigured"
    assert "sharedcommondataserviceforapps" in r.result
    assert "extension pack" in r.remediation


def test_dataverse_connection_unbound_fails(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _dv_ref("msdyn_Dataverse"),
        _dv_ref("new_sharedcommondataserviceforapps_41c83", connectionid=None),
    ])
    from flightcheck.checks.servicenow import _check_dataverse_connection
    r = _by_id(_check_dataverse_connection(_dv_runner()), "SN-DV-CONN-001")
    assert r.status == "Failed"
    assert "unbound" in r.result
    assert "new_sharedcommondataserviceforapps_41c83" in r.result


def test_dataverse_connection_inactive_fails(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _dv_ref("new_sharedcommondataserviceforapps_41c83", statuscode=2),
    ])
    from flightcheck.checks.servicenow import _check_dataverse_connection
    r = _by_id(_check_dataverse_connection(_dv_runner()), "SN-DV-CONN-001")
    assert r.status == "Failed"
    assert "inactive" in r.result


def test_dataverse_connection_skipped_without_token():
    from flightcheck.checks.servicenow import _check_dataverse_connection
    runner = SimpleNamespace(env_url="", dv_token="")
    r = _by_id(_check_dataverse_connection(runner), "SN-DV-CONN-001")
    assert r.status == "Skipped"
    assert "Dataverse token not available" in r.result


def test_dataverse_connection_query_error_warns(monkeypatch):
    import auth

    def _boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(auth, "query_all", _boom)
    from flightcheck.checks.servicenow import _check_dataverse_connection
    r = _by_id(_check_dataverse_connection(_dv_runner()), "SN-DV-CONN-001")
    assert r.status == "Warning"
    assert "boom" in r.result


def test_servicenow_dataverse_wrapper_self_contained(monkeypatch):
    """The wrapper emits SN-DV-CONN-001 with no _servicenow_flows gate."""
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _dv_ref("new_sharedcommondataserviceforapps_41c83"),
    ])
    from flightcheck.checks.servicenow import run_servicenow_dataverse_checks
    # No _servicenow_flows attribute at all — must still emit.
    r = _by_id(run_servicenow_dataverse_checks(_dv_runner()), "SN-DV-CONN-001")
    assert r.status == "Passed"


# --------------------------------------------------------------------------
# _check_portal_base_url — SN-BASEURL-001 (portal base URL set on the
# per-product parent template-config record; P6.6 / S6.5).
# --------------------------------------------------------------------------
import json as _json


def _portal_row(name, uri=None, *, raw=None):
    """A template-config parent row. ``uri=None`` → key present but empty."""
    if raw is not None:
        value = raw
    else:
        value = _json.dumps({"ServiceNowPortalBaseURI": uri or ""})
    return {"msdyn_name": name, "msdyn_value": value}


def _portal_runner():
    return SimpleNamespace(env_url="https://org.crm.dynamics.com", dv_token="t")


def _patch_confirmed_portal(monkeypatch, confirmed=None):
    """Isolate the confirmed portalBaseUrl the check reads from local config.

    Existing presence/format tests want the presence-only fallback (no confirmed
    value), so default to an empty config; the equality tests pass an explicit
    ``confirmed`` URL. Without this the check would read the real developer
    ``.local`` config from the cwd and couple tests to that value.
    """
    from flightcheck.checks import servicenow
    cfg = {"portalBaseUrl": confirmed} if confirmed else {}
    monkeypatch.setattr(servicenow, "_load_sn_connect_config", lambda: cfg)


def test_portal_base_url_set_passes(monkeypatch):
    import auth
    _patch_confirmed_portal(monkeypatch)
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _portal_row("msdyn_ServiceNowHRSD", "https://dev184242.service-now.com/sp"),
        # Unrelated child record must be ignored.
        _portal_row("msdyn_ServiceNowHRSDGetCaseDetails", ""),
    ])
    from flightcheck.checks.servicenow import _check_portal_base_url
    r = _by_id(_check_portal_base_url(_portal_runner()), "SN-BASEURL-001")
    assert r.status == "Passed"
    assert "HRSD" in r.result
    assert "Note:" not in r.result


def test_portal_base_url_non_portal_path_passes_with_note(monkeypatch):
    import auth
    _patch_confirmed_portal(monkeypatch)
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _portal_row("msdyn_ServiceNowHRSD", "https://dev184242.service-now.com"),
    ])
    from flightcheck.checks.servicenow import _check_portal_base_url
    r = _by_id(_check_portal_base_url(_portal_runner()), "SN-BASEURL-001")
    assert r.status == "Passed"
    assert "Service Portal path" in r.result


def test_portal_base_url_empty_fails(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _portal_row("msdyn_ServiceNowHRSD", ""),
    ])
    from flightcheck.checks.servicenow import _check_portal_base_url
    r = _by_id(_check_portal_base_url(_portal_runner()), "SN-BASEURL-001")
    assert r.status == "Failed"
    assert "empty for HRSD" in r.result


def test_portal_base_url_malformed_fails(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _portal_row("msdyn_ServiceNowITSM", "dev184242.service-now.com/sp"),
    ])
    from flightcheck.checks.servicenow import _check_portal_base_url
    r = _by_id(_check_portal_base_url(_portal_runner()), "SN-BASEURL-001")
    assert r.status == "Failed"
    assert "not a URL for ITSM" in r.result


def test_portal_base_url_no_parent_not_configured(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _portal_row("msdyn_ServiceNowHRSDGetCaseDetails", "x"),  # child only
    ])
    from flightcheck.checks.servicenow import _check_portal_base_url
    r = _by_id(_check_portal_base_url(_portal_runner()), "SN-BASEURL-001")
    assert r.status == "NotConfigured"
    assert "not installed" in r.result


def test_portal_base_url_skipped_without_token():
    from flightcheck.checks.servicenow import _check_portal_base_url
    runner = SimpleNamespace(env_url="", dv_token="")
    r = _by_id(_check_portal_base_url(runner), "SN-BASEURL-001")
    assert r.status == "Skipped"


def test_portal_base_url_bad_json_treated_as_unset(monkeypatch):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _portal_row("msdyn_ServiceNowHRSD", raw="not-json"),
    ])
    from flightcheck.checks.servicenow import _check_portal_base_url
    r = _by_id(_check_portal_base_url(_portal_runner()), "SN-BASEURL-001")
    assert r.status == "Failed"
    assert "empty for HRSD" in r.result


def test_servicenow_portal_wrapper_self_contained(monkeypatch):
    """The wrapper emits SN-BASEURL-001 with no _servicenow_flows gate."""
    import auth
    _patch_confirmed_portal(monkeypatch)
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _portal_row("msdyn_ServiceNowHRSD", "https://x.service-now.com/sp"),
    ])
    from flightcheck.checks.servicenow import run_servicenow_portal_checks
    r = _by_id(run_servicenow_portal_checks(_portal_runner()), "SN-BASEURL-001")
    assert r.status == "Passed"


def test_portal_base_url_matches_confirmed_passes(monkeypatch):
    """A stored URL equal to the confirmed value (case-insensitive host) passes."""
    import auth
    _patch_confirmed_portal(monkeypatch, "https://dev184242.service-now.com/sp")
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        # Host case and a trailing slash must not defeat the match.
        _portal_row("msdyn_ServiceNowHRSD", "https://DEV184242.service-now.com/sp/"),
    ])
    from flightcheck.checks.servicenow import _check_portal_base_url
    r = _by_id(_check_portal_base_url(_portal_runner()), "SN-BASEURL-001")
    assert r.status == "Passed"
    assert "Matches the confirmed URL" in r.result


def test_portal_base_url_mismatch_confirmed_fails(monkeypatch):
    """A present, absolute URL that differs from the confirmed value fails."""
    import auth
    _patch_confirmed_portal(monkeypatch, "https://dev184242.service-now.com/sp")
    monkeypatch.setattr(auth, "query_all", lambda *a, **kw: [
        _portal_row("msdyn_ServiceNowHRSD", "https://stale.service-now.com/sp"),
    ])
    from flightcheck.checks.servicenow import _check_portal_base_url
    r = _by_id(_check_portal_base_url(_portal_runner()), "SN-BASEURL-001")
    assert r.status == "Failed"
    assert "does not match the confirmed URL" in r.result
    # Reports expected-vs-actual for the product.
    assert "expected https://dev184242.service-now.com/sp" in r.result
    assert "found https://stale.service-now.com/sp" in r.result


# --------------------------------------------------------------------------
# Skill-3 capture gates — SN-CONFIG-001 / SN-PERM-001 / SN-USER-001.
# Config-only: they read .local/connect/servicenow/config.json relative to cwd.
# --------------------------------------------------------------------------
import json as _json2


def _write_sn_config(tmp_path, cfg):
    cfg_path = tmp_path / ".local" / "connect" / "servicenow" / "config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(_json2.dumps(cfg), encoding="utf-8")


_FULL_BASICS = {
    "instanceUrl": "https://dev184242.service-now.com",
    "connectorType": "powerplatform",
    "scope": {"hrsd": True, "itsm": False},
    "authType": "entra_user",
}


def test_sn_config_basics_complete_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_sn_config(tmp_path, dict(_FULL_BASICS))
    from flightcheck.checks.servicenow import _check_config_basics
    r = _by_id(_check_config_basics(None), "SN-CONFIG-001")
    assert r.status == "Passed"
    assert "dev184242" in r.result and "HRSD" in r.result


def test_sn_config_basics_absent_not_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from flightcheck.checks.servicenow import _check_config_basics
    r = _by_id(_check_config_basics(None), "SN-CONFIG-001")
    assert r.status == "NotConfigured"


def test_sn_config_basics_missing_fields_fail(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_sn_config(tmp_path, {
        "instanceUrl": "https://example.com",   # not a service-now host
        "scope": {"hrsd": False, "itsm": False},  # nothing in scope
        "authType": "password",                  # unsupported
    })
    from flightcheck.checks.servicenow import _check_config_basics
    r = _by_id(_check_config_basics(None), "SN-CONFIG-001")
    assert r.status == "Failed"
    assert "instance URL" in r.result
    assert "HRSD or ITSM" in r.result
    assert "sign-in method" in r.result
    assert "connector" in r.result


def test_sn_perm_entra_and_snadmin_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_sn_config(tmp_path, {"makerPermissions": {
        "entraAdmin": True, "serviceNowAdmin": True,
    }})
    from flightcheck.checks.servicenow import _check_maker_permissions
    r = _by_id(_check_maker_permissions(None), "SN-PERM-001")
    assert r.status == "Passed"


def test_sn_perm_no_snadmin_fails(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_sn_config(tmp_path, {"makerPermissions": {
        "entraAdmin": True, "serviceNowAdmin": False,
    }})
    from flightcheck.checks.servicenow import _check_maker_permissions
    r = _by_id(_check_maker_permissions(None), "SN-PERM-001")
    assert r.status == "Failed"
    assert "ServiceNow administrator" in r.result


def test_sn_perm_entra_unconfirmed_manual(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_sn_config(tmp_path, {"makerPermissions": {
        "entraAdmin": False, "serviceNowAdmin": True,
        "entraAdminEvidence": "probe unavailable",
    }})
    from flightcheck.checks.servicenow import _check_maker_permissions
    r = _by_id(_check_maker_permissions(None), "SN-PERM-001")
    assert r.status == "Manual"
    assert "probe unavailable" in r.result


def test_sn_perm_snadmin_unknown_manual(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_sn_config(tmp_path, {"makerPermissions": {
        "entraAdmin": None, "serviceNowAdmin": None,
    }})
    from flightcheck.checks.servicenow import _check_maker_permissions
    r = _by_id(_check_maker_permissions(None), "SN-PERM-001")
    assert r.status == "Manual"


def test_sn_perm_not_probed_not_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_sn_config(tmp_path, dict(_FULL_BASICS))  # no makerPermissions
    from flightcheck.checks.servicenow import _check_maker_permissions
    r = _by_id(_check_maker_permissions(None), "SN-PERM-001")
    assert r.status == "NotConfigured"


def test_sn_user_confirmed_passes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_sn_config(tmp_path, {"userRecord": {
        "activeUserConfirmed": True, "mappedField": "email",
    }})
    from flightcheck.checks.servicenow import _check_user_record
    r = _by_id(_check_user_record(None), "SN-USER-001")
    assert r.status == "Passed"
    assert "email" in r.result


def test_sn_user_unconfirmed_manual(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_sn_config(tmp_path, dict(_FULL_BASICS))  # no userRecord
    from flightcheck.checks.servicenow import _check_user_record
    r = _by_id(_check_user_record(None), "SN-USER-001")
    assert r.status == "Manual"


def test_capture_wrapper_emits_all_three(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_sn_config(tmp_path, dict(_FULL_BASICS))
    from flightcheck.checks.servicenow import run_servicenow_capture_checks
    ids = {r.checkpoint_id for r in run_servicenow_capture_checks(None)}
    assert ids == {"SN-CONFIG-001", "SN-PERM-001", "SN-USER-001"}

