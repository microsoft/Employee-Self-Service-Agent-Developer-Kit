# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for WD-CONN-013 (Workday connection OBO parameter sharing).

The check verifies that every Workday connection the *agent* uses has
"Allow permission to share parameters" enabled. That setting is persisted on the
agent's own ``connectionreference`` rows (logical name
``{agentSchemaName}.{guid}.{connector}``) in column ``connectionparametersetconfig``
(populated = shared, null = not shared) — confirmed empirically by toggling it
live. Solution-template refs (``new_sharedworkdaysoap_ff0df`` etc.) are bound but
are NOT the agent's connections, so they're excluded by the schema-name prefix.

The Dataverse ``connectionreferences`` query is documented tier — stubbed here
via ``auth.query_all`` (no cassette).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

SCHEMA = "msdyn_copilotforemployeeselfservicehr"
_SHARED_CFG = '{"name":"oauth","values":{}}'

# Real GUID-format middle segments — the agent connection-ref detector requires
# a ``.{guid}.`` segment.
G1 = "9f1b2c3d-4e5f-6789-abcd-1234567890ab"
G2 = "aab52569-483a-f111-8e38-0022480875be"
G3 = "11111111-2222-3333-4444-555555555555"


def _agent_ref(guid: str, *, connector: str = "shared_workdaysoap",
               shared: bool = True, display: str = "ESS HR Workday",
               via_params_config: bool = False):
    setcfg = None if (via_params_config or not shared) else _SHARED_CFG
    paramscfg = _SHARED_CFG if (via_params_config and shared) else None
    return {
        "connectionreferencelogicalname": f"{SCHEMA}.{guid}.{connector}",
        "connectionreferencedisplayname": display,
        "connectorid": f"/providers/Microsoft.PowerApps/apis/{connector}",
        "connectionid": f"conn-{guid}",
        "connectionparametersetconfig": setcfg,
        "connectionparametersconfig": paramscfg,
    }


def _solution_ref(name: str = "new_sharedworkdaysoap_ff0df"):
    # A bound ref that is NOT the agent's (no ``.{guid}.`` segment), unshared.
    return {
        "connectionreferencelogicalname": name,
        "connectionreferencedisplayname": "OAuthUser",
        "connectorid": "/providers/Microsoft.PowerApps/apis/shared_workdaysoap",
        "connectionid": "conn-ff0df",
        "connectionparametersetconfig": None,
        "connectionparametersconfig": None,
    }


def _runner(*, config: Any = None, dv_token: str | None = "t",
            env_url: str | None = "https://org.crm.dynamics.com"):
    return SimpleNamespace(
        env_url=env_url, dv_token=dv_token,
        config=config if config is not None else {"agents": [{"schemaName": SCHEMA}]},
    )


def _stub(monkeypatch, refs):
    import auth
    monkeypatch.setattr(auth, "query_all", lambda *a, **k: list(refs))


def _run(runner) -> Any:
    from flightcheck.checks.workday import _check_workday_connection_obo_sharing

    results = _check_workday_connection_obo_sharing(runner)
    assert len(results) == 1
    assert results[0].checkpoint_id == "WD-CONN-013"
    return results[0]


# ── PASS / FAIL on the agent's connections ─────────────────────────────────

def test_all_agent_connections_shared_passes(monkeypatch):
    _stub(monkeypatch, [
        _agent_ref(G1, shared=True, display="ESS HR Workday"),
        _agent_ref(G2, shared=True, display="ESS HR Workday Get User Context V2"),
        _solution_ref(),  # excluded
    ])
    r = _run(_runner())
    assert r.status == "Passed"
    assert "All 2 connection(s) the agent uses" in r.result


def test_one_unshared_connection_fails(monkeypatch):
    _stub(monkeypatch, [
        _agent_ref(G1, shared=True, display="ESS HR Workday"),
        _agent_ref(G2, shared=False, display="ESS HR Workday Get User Context V2"),
    ])
    r = _run(_runner())
    assert r.status == "Failed"
    assert "1 of 2" in r.result
    assert "ESS HR Workday Get User Context V2" in r.result
    assert "Allow permission to share parameters" in r.remediation


def test_covers_every_connector_the_agent_references(monkeypatch):
    # Not just Workday SOAP — a non-Workday agent connection that is unshared
    # must also fail the check.
    _stub(monkeypatch, [
        _agent_ref(G1, connector="shared_workdaysoap", shared=True),
        _agent_ref(G3, connector="shared_commondataserviceforapps",
                   shared=False, display="Microsoft Dataverse"),
    ])
    r = _run(_runner())
    assert r.status == "Failed"
    assert "1 of 2" in r.result
    assert "Microsoft Dataverse" in r.result


def test_solution_refs_are_excluded(monkeypatch):
    # One agent connection (shared) + unshared solution refs (no .{guid}. segment).
    # The solution refs must NOT drag the verdict to FAIL.
    _stub(monkeypatch, [
        _agent_ref(G1, shared=True),
        _solution_ref(),
        {"connectionreferencelogicalname": "msdyn_sharedcommondataserviceforapps_92b66",
         "connectorid": "/providers/Microsoft.PowerApps/apis/shared_commondataserviceforapps",
         "connectionid": "conn-dv", "connectionparametersetconfig": None,
         "connectionparametersconfig": None},
    ])
    r = _run(_runner())
    assert r.status == "Passed"
    assert "All 1 connection(s) the agent uses" in r.result


def test_sharing_via_parameters_config_column_also_counts(monkeypatch):
    _stub(monkeypatch, [_agent_ref(G1, shared=True, via_params_config=True)])
    r = _run(_runner())
    assert r.status == "Passed"


# ── NOT_CONFIGURED / SKIPPED branches ──────────────────────────────────────

def test_no_agent_refs_is_not_configured(monkeypatch):
    # Only solution refs (no .{guid}. agent-connection segment).
    _stub(monkeypatch, [_solution_ref()])
    r = _run(_runner())
    assert r.status == "NotConfigured"
    assert "No agent connection references found" in r.result


def test_no_dataverse_token_is_skipped():
    from flightcheck.checks.workday import _check_workday_connection_obo_sharing
    r = _check_workday_connection_obo_sharing(_runner(dv_token=None))[0]
    assert r.status == "Skipped"
    assert "Dataverse token not available" in r.result


def test_query_error_is_skipped(monkeypatch):
    import auth

    def _boom(*a, **k):
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(auth, "query_all", _boom)
    r = _run(_runner())
    assert r.status == "Skipped"
    assert "Unable to read Dataverse connection references" in r.result


# ── wiring ─────────────────────────────────────────────────────────────────

class TestWiring:
    @pytest.fixture
    def _auto_stub_other_workday_checks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from flightcheck.checks import workday as wd_mod

        keep = {"_check_workday_connection_obo_sharing"}
        for name in dir(wd_mod):
            if not name.startswith("_check_") or name in keep:
                continue
            if not callable(getattr(wd_mod, name)):
                continue
            monkeypatch.setattr(wd_mod, name, lambda *_a, **_k: [])

    def test_run_workday_checks_invokes_obo_sharing(
        self, monkeypatch: pytest.MonkeyPatch, _auto_stub_other_workday_checks: None,
    ) -> None:
        from flightcheck.checks.workday import run_workday_checks

        # dv_token=None → the check returns SKIPPED without any query.
        runner = SimpleNamespace(
            _workday_flows=[{"id": "fake-flow"}],
            env_url="https://org.crm.dynamics.com", dv_token=None,
            config={"agents": [{"schemaName": SCHEMA}]},
        )
        results = run_workday_checks(runner)
        rows = [r for r in results if r.checkpoint_id == "WD-CONN-013"]
        assert len(rows) == 1, "WD-CONN-013 must be emitted by run_workday_checks"
