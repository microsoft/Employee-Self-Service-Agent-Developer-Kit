# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the ENV-004 agent connection-reference scope builder
(``flightcheck.checks._agent_connection_refs.build_agent_ref_scope``).

The builder resolves the connection references an ESS agent actually
uses so ENV-004 can stop judging environment-wide references (which
produced false FAILs on other apps' refs and on the ESS-shipped
placeholder refs that ship unbound-by-design on a Workday simplified
install).

Chain under test: config botId(s) -> Dataverse ``botcomponents``
(enabled topics) ``data`` -> InvokeFlowAction flowIds -> per-flow
``pp.get_flow`` detail -> that detail's ``connectionReferences``.

The Dataverse ``botcomponents`` read is ``documented`` tier (tests stub
``query_all``); the BAP per-flow detail is ``validated`` tier — its
record shape (``properties.connectionReferences.<c>.{connectionReferenceLogicalName,apiDefinition}``)
comes from ``tests/mocks/pp_admin.py`` (``MOCK_STATUS = "validated"``,
cassette ``flightcheck_flow_licensing.yaml``). The listing
(``pp.get_flows``) is deliberately NOT used: it omits
``connectionReferences`` entirely, which would yield an empty scope and
silently turn ENV-004 into a no-op.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)


FLOW_A = "11111111-1111-1111-1111-111111111111"
FLOW_B = "22222222-2222-2222-2222-222222222222"


def _topic(data: str) -> dict[str, Any]:
    """A ``botcomponents`` topic row as ENV-004 scoping reads it."""
    return {"name": "SomeTopic", "schemaname": "cr123_sometopic", "data": data}


def _invoke(flow_id: str) -> str:
    """Topic YAML fragment invoking a cloud flow (Pattern B)."""
    return (
        "kind: AdaptiveDialog\n"
        "actions:\n"
        "  - kind: InvokeFlowAction\n"
        f"    flowId: {flow_id}\n"
    )


def _detail_with_ref(flow_id: str, api_name: str) -> dict[str, Any]:
    """A BAP per-flow DETAIL record binding a flow to one connector's
    ref, built from the validated ``pp_admin`` mock builders. The
    connection references live in the DETAIL response (``get_flow``), not
    the listing."""
    return pp.flow_detail(
        flow_id=flow_id,
        connection_refs={api_name: pp.flow_connector_ref(api_name=api_name)},
    )


class _FakePP:
    """Fake ``pp_admin`` exposing ``get_flow(env_id, flow_id)`` -> detail.

    ``details`` maps a flow_id to its DETAIL dict (or an ``{"_error",
    "_status"}`` payload). A flow_id absent from the map returns ``None``
    — modelling a flow not visible on the admin surface, exactly as
    ``pp_admin.get_flow`` does for a 404.
    """

    def __init__(self, details=None):
        self._details = details or {}
        self.calls: list[tuple[str, str]] = []

    def get_flow(self, env_id, flow_id):
        self.calls.append((env_id, flow_id))
        return self._details.get(flow_id)

    def get_flows(self, _env_id):  # pragma: no cover - guard only
        raise AssertionError(
            "build_agent_ref_scope must read connection references from the "
            "per-flow DETAIL (get_flow), not the listing (get_flows) — the "
            "listing omits connectionReferences (flightcheck_flow_licensing.yaml)."
        )


def _runner(*, config, details=None):
    return SimpleNamespace(
        config=config,
        env_url="https://example.crm.dynamics.com",
        dv_token="dv-token",
        env_id="env-1",
        pp_admin=_FakePP(details or {}),
    )


def test_scope_resolves_logical_names_and_connectors(monkeypatch):
    from flightcheck.checks import _agent_connection_refs as mod

    monkeypatch.setattr(mod, "query_all", lambda *a, **k: [_topic(_invoke(FLOW_A))])
    runner = _runner(
        config={"agents": [{"botId": "bot-1"}]},
        details={FLOW_A: _detail_with_ref(FLOW_A, "shared_commondataserviceforapps")},
    )

    scope = mod.build_agent_ref_scope(runner)

    assert scope is not None
    assert scope.logical_names == frozenset({"ref_shared_commondataserviceforapps"})
    assert scope.connectors == frozenset({"shared_commondataserviceforapps"})


def test_scope_reads_from_flow_detail_not_listing(monkeypatch):
    """Regression guard: the builder resolves refs via the per-flow
    DETAIL (``get_flow``), never the listing. ``_FakePP.get_flows``
    raises, so any lapse back to the listing fails loudly here."""
    from flightcheck.checks import _agent_connection_refs as mod

    monkeypatch.setattr(mod, "query_all", lambda *a, **k: [_topic(_invoke(FLOW_A))])
    runner = _runner(
        config={"agents": [{"botId": "bot-1"}]},
        details={FLOW_A: _detail_with_ref(FLOW_A, "shared_workdaysoap")},
    )

    scope = mod.build_agent_ref_scope(runner)

    assert scope is not None
    # get_flow was called with the topic-discovered flowId directly.
    assert runner.pp_admin.calls == [("env-1", FLOW_A)]


def test_scope_none_without_botid(monkeypatch):
    """No configured agent botId -> cannot scope -> None (caller SKIPs)."""
    from flightcheck.checks import _agent_connection_refs as mod

    monkeypatch.setattr(mod, "query_all", lambda *a, **k: [_topic(_invoke(FLOW_A))])
    runner = _runner(
        config={}, details={FLOW_A: _detail_with_ref(FLOW_A, "shared_workdaysoap")}
    )

    assert mod.build_agent_ref_scope(runner) is None


def test_scope_supports_single_agent_config(monkeypatch):
    """The legacy single-agent ``config['agent']`` shape is honored."""
    from flightcheck.checks import _agent_connection_refs as mod

    monkeypatch.setattr(mod, "query_all", lambda *a, **k: [_topic(_invoke(FLOW_A))])
    runner = _runner(
        config={"agent": {"botId": "solo"}},
        details={FLOW_A: _detail_with_ref(FLOW_A, "shared_workdaysoap")},
    )

    scope = mod.build_agent_ref_scope(runner)

    assert scope is not None
    assert "ref_shared_workdaysoap" in scope.logical_names


def test_scope_none_when_topics_invoke_no_flows(monkeypatch):
    """Topics with no InvokeFlowAction flowIds -> None (can't scope)."""
    from flightcheck.checks import _agent_connection_refs as mod

    monkeypatch.setattr(
        mod, "query_all", lambda *a, **k: [_topic("kind: SendActivity\n")]
    )
    runner = _runner(
        config={"agents": [{"botId": "bot-1"}]},
        details={FLOW_A: _detail_with_ref(FLOW_A, "shared_workdaysoap")},
    )

    assert mod.build_agent_ref_scope(runner) is None


def test_scope_none_when_flow_detail_not_found(monkeypatch):
    """flowIds discovered but the admin surface returns none of them
    (get_flow -> None) -> scoping unreliable -> None rather than
    under-report."""
    from flightcheck.checks import _agent_connection_refs as mod

    monkeypatch.setattr(mod, "query_all", lambda *a, **k: [_topic(_invoke(FLOW_A))])
    runner = _runner(
        config={"agents": [{"botId": "bot-1"}]},
        details={},  # FLOW_A not present -> get_flow returns None
    )

    assert mod.build_agent_ref_scope(runner) is None


def test_scope_raises_on_flow_detail_auth_error(monkeypatch):
    """A 401/403 ``_error`` payload from a flow detail fetch surfaces
    loudly (caller converts to WARNING) — not a silent SKIP."""
    from flightcheck.checks import _agent_connection_refs as mod

    monkeypatch.setattr(mod, "query_all", lambda *a, **k: [_topic(_invoke(FLOW_A))])
    runner = _runner(
        config={"agents": [{"botId": "bot-1"}]},
        details={FLOW_A: {"_error": "403 Forbidden", "_status": 403}},
    )

    with pytest.raises(RuntimeError, match="unauthorized"):
        mod.build_agent_ref_scope(runner)


def test_scope_skips_unreadable_flow_but_keeps_readable_ones(monkeypatch):
    """A non-auth unreadable flow (404 / other _error) is skipped, while
    a sibling readable flow still contributes its refs."""
    from flightcheck.checks import _agent_connection_refs as mod

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        return [_topic(_invoke(FLOW_A) + _invoke(FLOW_B))]

    monkeypatch.setattr(mod, "query_all", _fake)
    runner = _runner(
        config={"agents": [{"botId": "bot-1"}]},
        details={
            FLOW_A: _detail_with_ref(FLOW_A, "shared_workdaysoap"),
            FLOW_B: {"_error": "not found", "_status": 404},
        },
    )

    scope = mod.build_agent_ref_scope(runner)

    assert scope is not None
    assert scope.logical_names == frozenset({"ref_shared_workdaysoap"})


def test_scope_raises_on_flow_detail_exception(monkeypatch):
    """A raised exception during a flow detail fetch surfaces loudly."""
    from flightcheck.checks import _agent_connection_refs as mod

    class _BoomPP:
        def get_flow(self, env_id, flow_id):
            raise ConnectionError("socket reset")

    monkeypatch.setattr(mod, "query_all", lambda *a, **k: [_topic(_invoke(FLOW_A))])
    runner = SimpleNamespace(
        config={"agents": [{"botId": "bot-1"}]},
        env_url="https://example.crm.dynamics.com",
        dv_token="dv-token",
        env_id="env-1",
        pp_admin=_BoomPP(),
    )

    with pytest.raises(RuntimeError, match="socket reset"):
        mod.build_agent_ref_scope(runner)


def test_scope_queries_enabled_topics_only(monkeypatch):
    """The topic query MUST filter to enabled topics (statecode 0) scoped
    to the configured botId — a ref only reachable through a disabled
    topic is not a live runtime dependency."""
    from flightcheck.checks import _agent_connection_refs as mod

    captured: dict[str, Any] = {}

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        captured["entity_set"] = entity_set
        captured["filter"] = filter_expr
        return [_topic(_invoke(FLOW_A))]

    monkeypatch.setattr(mod, "query_all", _fake)
    runner = _runner(
        config={"agents": [{"botId": "bot-xyz"}]},
        details={FLOW_A: _detail_with_ref(FLOW_A, "shared_workdaysoap")},
    )

    mod.build_agent_ref_scope(runner)

    assert captured["entity_set"] == "botcomponents"
    assert "statecode eq 0" in captured["filter"]
    assert "componenttype eq 9" in captured["filter"]
    assert "bot-xyz" in captured["filter"]


def test_scope_unions_across_multiple_agents(monkeypatch):
    """Refs are unioned across every configured agent botId."""
    from flightcheck.checks import _agent_connection_refs as mod

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        if "bot-1" in (filter_expr or ""):
            return [_topic(_invoke(FLOW_A))]
        if "bot-2" in (filter_expr or ""):
            return [_topic(_invoke(FLOW_B))]
        return []

    monkeypatch.setattr(mod, "query_all", _fake)
    runner = _runner(
        config={"agents": [{"botId": "bot-1"}, {"botId": "bot-2"}]},
        details={
            FLOW_A: _detail_with_ref(FLOW_A, "shared_commondataserviceforapps"),
            FLOW_B: _detail_with_ref(FLOW_B, "shared_workdaysoap"),
        },
    )

    scope = mod.build_agent_ref_scope(runner)

    assert scope is not None
    assert scope.logical_names == frozenset(
        {"ref_shared_commondataserviceforapps", "ref_shared_workdaysoap"}
    )
    assert scope.connectors == frozenset(
        {"shared_commondataserviceforapps", "shared_workdaysoap"}
    )


def test_scope_matched_flow_without_refs_is_empty_not_none(monkeypatch):
    """A readable flow that carries no connection references yields an
    empty (but resolved) scope — distinct from the unresolvable None."""
    from flightcheck.checks import _agent_connection_refs as mod

    monkeypatch.setattr(mod, "query_all", lambda *a, **k: [_topic(_invoke(FLOW_A))])
    runner = _runner(
        config={"agents": [{"botId": "bot-1"}]},
        details={FLOW_A: pp.flow_detail(flow_id=FLOW_A, connection_refs={})},
    )

    scope = mod.build_agent_ref_scope(runner)

    assert scope is not None
    assert scope.logical_names == frozenset()
    assert scope.connectors == frozenset()
