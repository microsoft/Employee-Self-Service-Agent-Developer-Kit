# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ENV-004 Workday hybrid connection coverage.

The minimalBots components API never surfaces Workday's SOAP connection
reference: it is flow-scoped (bound on the WorkdayRESTExecution Power Automate
flow inside the Dataverse solution, not on any bot topic). A components-only
read therefore reports a false clean on a Workday install. ENV-004 closes that
gap by also reading the environment's Dataverse ``connectionreference`` table
and unioning in any Workday SOAP reference.

These tests stub the Dataverse read (``environment.query_all``) exactly as
``test_environment_basics._stub_query_all`` does, so they stay offline. The
Dataverse ``connectionreferences`` GET is a ``documented``-tier endpoint
already exercised by WD-PKG-001 (see ``tests/fixtures/cassettes/INDEX.md``).

Per tests/AGENTS.md, every GOOD/BAD/WARNING assertion pins a phrase from both
``result`` and ``remediation``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as ab

require_validated_mock(ab)


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Make ``flightcheck.*`` importable from the kit's scripts dir."""
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "solutions" / "ess-maker-skills" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


class _FakeAgentBuilder:
    def __init__(self, components):
        self._components = components

    def fetch_components(self, _agent_id):
        return self._components

    def get_realm_configuration(self, _agent_id, realm):
        if type(realm) is not int:
            raise ValueError("Realm must be the numeric Dev/Test/Prod value.")
        return None


def _servicenow_only():
    """Components read with a single bound ServiceNow reference.

    Workday is deliberately absent from the components changeset, mirroring the
    live finding that the components API never carries the Workday SOAP ref.
    """
    return ab.components_with_references(
        references=[
            ab.connection_reference_change(
                connector="shared_service-now", connection_id="conn-sn"
            )
        ]
    )


def _runner(*, components, dv_rows_or_error, env_url="https://x.crm.dynamics.com",
            dv_token="t", config_extra=None):
    config = {"agent": {"botId": ab.MOCK_AGENT_ID}}
    if config_extra:
        config.update(config_extra)
    return SimpleNamespace(
        agentbuilder=_FakeAgentBuilder(components),
        config=config,
        env_id="env-wd",
        env_url=env_url,
        dv_token=dv_token,
        _dv=dv_rows_or_error,
    )


def _dv_row(*, logical_name, connectorid, connection_id):
    return {
        "connectionreferenceid": "ref-guid",
        "connectionreferencelogicalname": logical_name,
        "connectionreferencedisplayname": "Workday SOAP",
        "connectorid": connectorid,
        "connectionid": connection_id,
        "statuscode": 1,
    }


_WD_CONNECTOR = "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"


@pytest.fixture
def _patch_query_all(monkeypatch):
    """Route ``environment.query_all`` at runner._dv (rows list or exception)."""
    from flightcheck.checks import environment as env_mod

    def _fake(env_url, token, entity_set, select, *a, **kw):
        # The rows/error are carried on the runner, but query_all takes no
        # runner; stash the active runner's payload via a closure set per test.
        payload = _fake.payload
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(env_mod, "query_all", _fake)
    return _fake


def _check(runner, patch):
    from flightcheck.checks.environment import _check_connections_and_refs

    patch.payload = runner._dv
    return _check_connections_and_refs(runner)


def _by_id(results):
    return {r.checkpoint_id: r for r in results}


def test_workday_ref_bound_via_dataverse_passes(_patch_query_all):
    runner = _runner(
        components=_servicenow_only(),
        dv_rows_or_error=[
            _dv_row(
                logical_name="gptagent_ess.shared_workdaysoap",
                connectorid=_WD_CONNECTOR,
                connection_id="conn-wd",
            )
        ],
    )

    by_id = _by_id(_check(runner, _patch_query_all))
    summary = by_id["ENV-004"]

    assert summary.status == "Passed"
    assert "2 reference(s) declared by the agent(s)" in summary.result
    assert "2 bound" in summary.result
    assert "unbound" not in summary.result
    assert "ENV-004-WD" not in by_id


def test_workday_ref_unbound_via_dataverse_fails(_patch_query_all):
    runner = _runner(
        components=_servicenow_only(),
        dv_rows_or_error=[
            _dv_row(
                logical_name="gptagent_ess.shared_workdaysoap",
                connectorid=_WD_CONNECTOR,
                connection_id=None,
            )
        ],
    )

    by_id = _by_id(_check(runner, _patch_query_all))
    summary = by_id["ENV-004"]

    assert summary.status == "Failed"
    assert "1 unbound" in summary.result
    detail = by_id["ENV-004-UR-001"]
    assert detail.status == "Failed"
    assert "shared_workdaysoap" in detail.description
    assert "No connection bound to this reference" in detail.result
    assert "Connection references" in detail.remediation


def test_non_workday_dataverse_rows_are_not_unioned(_patch_query_all):
    """Only the flow-scoped Workday SOAP ref is unioned from Dataverse.

    Arbitrary environment-wide references (e.g. a SharePoint connection) are
    NOT pulled in, so ENV-004 does not reintroduce env-wide noise or re-report
    references the components API already owns.
    """
    runner = _runner(
        components=_servicenow_only(),
        dv_rows_or_error=[
            _dv_row(
                logical_name="gptagent_ess.shared_sharepointonline",
                connectorid=(
                    "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"
                ),
                connection_id=None,
            )
        ],
    )

    summary = _by_id(_check(runner, _patch_query_all))["ENV-004"]

    assert summary.status == "Passed"
    assert "1 reference(s) declared by the agent(s)" in summary.result
    assert "1 bound" in summary.result


def test_dataverse_unavailable_warns_without_false_clean(_patch_query_all):
    """A Dataverse read failure degrades to WARNING, never a silent PASS.

    ServiceNow (component-sourced) is still classified, so the failure to reach
    Dataverse does not collapse the whole check.
    """
    runner = _runner(
        components=_servicenow_only(),
        dv_rows_or_error=RuntimeError("boom"),
    )

    by_id = _by_id(_check(runner, _patch_query_all))
    summary = by_id["ENV-004"]

    assert summary.status == "Warning"
    # ServiceNow still judged.
    assert "1 bound" in summary.result
    assert "Workday connection coverage unverified" in summary.result
    # Dedicated detail row names the impact and the fix.
    wd = by_id["ENV-004-WD"]
    assert wd.status == "Warning"
    assert "Workday connection health was not judged" in wd.result
    assert "RuntimeError: boom" in wd.result
    assert "Dataverse read access" in wd.remediation


def test_no_dataverse_creds_on_workday_install_warns_not_false_clean(
    _patch_query_all,
):
    """Creds-absent on a Workday install degrades to WARNING, never PASS.

    Native Declarative Agent runs authenticate no Dataverse token, so the
    flow-scoped Workday SOAP reference cannot be read and the components API
    cannot see it. A components-only PASS would be a false clean on a Workday
    install. The local config's Workday REST base URL marks the install as
    Workday, so ENV-004 must WARN rather than silently PASS.
    """
    runner = _runner(
        components=_servicenow_only(),
        dv_rows_or_error=[],
        env_url=None,
        dv_token=None,
        config_extra={"restBaseUrl": "https://wd.example.com/ccx/api"},
    )

    by_id = _by_id(_check(runner, _patch_query_all))
    summary = by_id["ENV-004"]

    assert summary.status == "Warning"
    # ServiceNow (component-sourced) is still judged.
    assert "1 bound" in summary.result
    assert "Workday connection coverage unverified" in summary.result
    assert "Dataverse read access" in summary.remediation
    # Dedicated detail row names the impact and the fix.
    wd = by_id["ENV-004-WD"]
    assert wd.status == "Warning"
    assert "Workday connection health was not judged" in wd.result
    assert "Dataverse was not available" in wd.result
    assert "Dataverse read access" in wd.remediation


def test_no_dataverse_creds_on_non_workday_install_passes_quietly(
    _patch_query_all,
):
    """Creds-absent on a non-Workday install stays PASS with no Workday noise.

    A ServiceNow-only install has no Workday REST/SOAP base URL configured, so
    there is no Workday coverage to warn about and ENV-004 must not emit a
    false WARNING.
    """
    runner = _runner(
        components=_servicenow_only(),
        dv_rows_or_error=[],
        env_url=None,
        dv_token=None,
    )

    by_id = _by_id(_check(runner, _patch_query_all))
    summary = by_id["ENV-004"]

    assert summary.status == "Passed"
    assert "1 reference(s) declared by the agent(s)" in summary.result
    assert "1 bound" in summary.result
    assert "ENV-004-WD" not in by_id
