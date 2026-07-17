# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ENV-004 connection-binding remediations.

The user surfaced that ENV-004 remediations had no actionable link —
operators were told to "fix the broken connection reference" with no
pointer to the actual page in the maker portal. This module pins the
deep links that the remediation strings must now carry, for every
ENV-004 row that asks the operator to take a manual action.

Strategy:
- Drive `_check_connections_and_refs` with a tiny in-memory fake of
  the PPAdminClient + a monkeypatched `auth.query_all`.
- Build the three buggy bindings the check is supposed to surface
  (orphan ref, unbound ref, unbound connection) and assert each
  remediation contains the expected env-scoped maker URL.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Make `flightcheck.*` and `auth` importable from the kit's scripts dir."""
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


def test_maker_connections_url_targets_powerautomate():
    from flightcheck.checks._maker_urls import maker_connections_url

    assert maker_connections_url("env-123") == (
        "https://make.powerautomate.com/environments/env-123/connections"
    )


def test_maker_solutions_url_targets_powerapps():
    """Solutions are only surfaced in the Power Apps maker — the
    Power Automate maker does not expose the Connection References
    pane that ENV-004 asks the operator to open."""
    from flightcheck.checks._maker_urls import maker_solutions_url

    assert maker_solutions_url("env-123") == (
        "https://make.powerapps.com/environments/env-123/solutions"
    )


class _FakePPAdmin:
    """Minimal stand-in for ``PPAdminClient`` covering the methods
    ENV-004 calls. Returns the list passed at construction time."""

    def __init__(self, connections):
        self._connections = connections

    def get_connections(self, _env_id):
        return self._connections


def _make_runner(connections):
    return SimpleNamespace(
        pp_admin=_FakePPAdmin(connections),
        env_id="env-deeplinks",
        env_url="https://example.crm.dynamics.com",
        dv_token="fake-token",
    )


def _conn(name, display_name="Display Name"):
    """Shape we need from PP Admin's get_connections — just `name`
    (the GUID id field) and `properties.displayName`."""
    return {"name": name, "properties": {"displayName": display_name, "apiId": "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"}}


def _ref(conn_id, ref_id=None, display="Reference", solution_id=None):
    """Shape we need from Dataverse connectionreferences query.

    ``solution_id`` does NOT live on the ref itself in the production
    schema — connectionreference has no solution column. We carry it
    on the fake dict purely so the test fixtures (``_patch_query_all``)
    can derive a solutioncomponents response from the same input list,
    keeping each test's setup compact.
    """
    return {
        "connectionreferenceid": ref_id or "ref-id",
        "connectionreferencelogicalname": "logical_name",
        "connectionreferencedisplayname": display,
        "connectorid": "shared_workdaysoap",
        "connectionid": conn_id,
        "statuscode": 1,
        # NOTE: prefixed so the production code path never reads this
        # — it's test-fixture metadata, not a Dataverse column.
        "_test_solution_id": solution_id or "00000000-0000-0000-0000-000000009000",
    }


def _solution(sid, friendly_name, unique_name=None, ismanaged=False):
    """Shape we need from Dataverse `solutions` query for the
    ref → solution lookup. Defaults to ``ismanaged=False`` (unmanaged)
    because that's the layer the maker can actually edit and the one
    production prefers when picking among multiple matches."""
    return {
        "solutionid": sid,
        "uniquename": unique_name or friendly_name.lower().replace(" ", ""),
        "friendlyname": friendly_name,
        "ismanaged": ismanaged,
    }


def _patch_query_all(monkeypatch, env_mod, *, conn_refs, solutions=None):
    """Install a dispatching fake for ``auth.query_all`` covering all
    three queries ENV-004 issues:

      1. ``connectionreferences`` → returns the conn_refs argument
      2. ``solutioncomponents`` → derives a (ref_id → solution_id)
         mapping from each ref's ``_test_solution_id`` fixture field
      3. ``solutions`` → returns the solutions argument

    Tests that don't care about the per-row deep link can omit
    ``solutions`` and the third call returns []; the production code
    falls back to the env-wide solutions URL.
    """
    solutions = solutions or []

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        if entity_set == "connectionreferences":
            # Production code never reads `_test_solution_id` — strip
            # it so the mock can't accidentally make production logic
            # depend on a non-existent Dataverse column.
            return [{k: v for k, v in r.items() if not k.startswith("_test_")}
                    for r in conn_refs]
        if entity_set == "solutioncomponents":
            return [
                {"objectid": r["connectionreferenceid"],
                 "_solutionid_value": r["_test_solution_id"]}
                for r in conn_refs if r.get("_test_solution_id")
            ]
        if entity_set == "solutions":
            return solutions
        return []

    monkeypatch.setattr(env_mod, "query_all", _fake)


@pytest.fixture(autouse=True)
def _scope_to_all_present_refs(monkeypatch):
    """Reproduce ENV-004's original whole-environment behavior for the
    remediation-link tests in this module.

    ENV-004 now scopes its verdict to the connection references the agent
    actually uses (``build_agent_ref_scope``). These tests predate that
    scoping and assert on the binding-state / deep-link behavior, so we
    default the scope to "every reference + connector present in the
    test's fixtures", which keeps all of a test's refs in scope exactly
    as the pre-scoping code judged them. Tests exercising the new
    scoping / SKIP / missing-ref paths override ``build_agent_ref_scope``
    themselves (a later ``monkeypatch.setattr`` wins)."""
    from flightcheck.checks import environment as env_mod
    from flightcheck.checks._agent_connection_refs import AgentRefScope
    from flightcheck.checks._dlp_utils import normalize_connector_id

    def _all_present(runner):
        refs = env_mod.query_all(
            runner.env_url, runner.dv_token, "connectionreferences", "sel"
        )
        logicals = {
            (r.get("connectionreferencelogicalname") or "").lower()
            for r in refs or []
            if (r.get("connectionreferencelogicalname") or "")
        }
        connectors = {
            normalize_connector_id(r.get("connectorid"))
            for r in refs or []
            if r.get("connectorid")
        }
        try:
            conns = runner.pp_admin.get_connections(runner.env_id)
        except Exception:
            conns = []
        for c in conns or []:
            cid = normalize_connector_id((c.get("properties", {}) or {}).get("apiId"))
            if cid:
                connectors.add(cid)
        return AgentRefScope(
            logical_names=frozenset(logicals),
            connectors=frozenset(connectors),
        )

    monkeypatch.setattr(env_mod, "build_agent_ref_scope", _all_present)


def _scope(*, logical_names, connectors=("shared_workdaysoap",)):
    """Build a fixed :class:`AgentRefScope` for the agent-scoping tests."""
    from flightcheck.checks._agent_connection_refs import AgentRefScope

    return AgentRefScope(
        logical_names=frozenset(logical_names),
        connectors=frozenset(connectors),
    )


def _ref_named(logical, conn_id, *, ref_id, display="Reference"):
    """A connectionreferences row with an explicit logical name (the
    default ``_ref`` helper hardcodes 'logical_name')."""
    return {
        "connectionreferenceid": ref_id,
        "connectionreferencelogicalname": logical,
        "connectionreferencedisplayname": display,
        "connectorid": "shared_workdaysoap",
        "connectionid": conn_id,
        "statuscode": 1,
    }


def _conn_c(name, connector, display_name="Display Name"):
    """A get_connections record with an explicit connector."""
    return {
        "name": name,
        "properties": {
            "displayName": display_name,
            "apiId": f"/providers/Microsoft.PowerApps/apis/{connector}",
        },
    }


def test_env_004_skips_when_agent_scope_unresolvable(monkeypatch):
    """When the agent's connection-reference set can't be resolved
    (builder returns None), ENV-004 SKIPs rather than judging every
    reference in the environment."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("", display="Placeholder")])
    monkeypatch.setattr(env_mod, "build_agent_ref_scope", lambda runner: None)

    results = env_mod._check_connections_and_refs(runner)

    env004 = [r for r in results if r.checkpoint_id == "ENV-004"]
    assert len(env004) == 1
    assert env004[0].status == "Skipped"
    assert "belong to this agent" in env004[0].result
    # The unbound placeholder ref must NOT surface as a FAILED detail row.
    assert not any(r.checkpoint_id.startswith("ENV-004-UR-") for r in results)


def test_env_004_warns_when_scope_build_raises(monkeypatch):
    """A genuine API error while resolving the agent's flows surfaces as
    a WARNING (principle 3), not a silent SKIP or an env-wide verdict."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("real-conn-id")])

    def _boom(runner):
        raise RuntimeError("flow listing failed: 403")

    monkeypatch.setattr(env_mod, "build_agent_ref_scope", _boom)

    results = env_mod._check_connections_and_refs(runner)

    env004 = [r for r in results if r.checkpoint_id == "ENV-004"]
    assert len(env004) == 1
    assert env004[0].status == "Warning"
    assert "403" in env004[0].result


def test_env_004_out_of_scope_unbound_ref_is_not_failed(monkeypatch):
    """The customer-reported bug: an unbound reference the agent does NOT
    use (e.g. the ESS-shipped placeholder on a simplified install) must
    not FAIL ENV-004. Only the agent's own reference is judged."""
    from flightcheck.checks import environment as env_mod

    used = _ref_named("msdyn_used", "conn-1", ref_id="ref-used", display="Used")
    placeholder = _ref_named("msdyn_placeholder", "", ref_id="ref-ph", display="Placeholder")
    runner = _make_runner(connections=[_conn("conn-1")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [used, placeholder])
    monkeypatch.setattr(
        env_mod, "build_agent_ref_scope",
        lambda runner: _scope(logical_names={"msdyn_used"}),
    )

    results = env_mod._check_connections_and_refs(runner)

    summary = next(r for r in results if r.checkpoint_id == "ENV-004")
    assert summary.status == "Passed", summary.__dict__
    # The out-of-scope placeholder must not produce an unbound-ref FAIL.
    assert not any(r.checkpoint_id.startswith("ENV-004-UR-") for r in results)
    assert "1 reference(s) used by this agent" in summary.result


def test_env_004_missing_ref_emits_mr_row(monkeypatch):
    """A logical name the agent's flows reference but that has no row in
    the environment surfaces as an ENV-004-MR-* FAILED detail row."""
    from flightcheck.checks import environment as env_mod

    used = _ref_named("msdyn_used", "conn-1", ref_id="ref-used")
    runner = _make_runner(connections=[_conn("conn-1")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [used])
    monkeypatch.setattr(
        env_mod, "build_agent_ref_scope",
        lambda runner: _scope(logical_names={"msdyn_used", "msdyn_missing"}),
    )

    results = env_mod._check_connections_and_refs(runner)

    summary = next(r for r in results if r.checkpoint_id == "ENV-004")
    assert summary.status == "Failed", summary.__dict__
    mr = [r for r in results if r.checkpoint_id.startswith("ENV-004-MR-")]
    assert len(mr) == 1
    assert mr[0].status == "Failed"
    assert "msdyn_missing" in mr[0].result
    assert "no such reference exists" in mr[0].result
    assert "1 missing ref(s)" in summary.result


def test_env_004_unbound_connection_scoped_to_agent_connectors(monkeypatch):
    """Unbound connections are only flagged when their connector is one
    the agent uses — a stale connection of an unrelated connector in the
    same environment is not reported."""
    from flightcheck.checks import environment as env_mod

    bound = _conn_c("bound-wd", "shared_workdaysoap")
    stale_wd = _conn_c("stale-wd", "shared_workdaysoap", display_name="Stale Workday")
    other = _conn_c("other-app", "shared_office365", display_name="Other App")
    used = _ref_named("msdyn_used", "bound-wd", ref_id="ref-used")

    runner = _make_runner(connections=[bound, stale_wd, other])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [used])
    monkeypatch.setattr(
        env_mod, "build_agent_ref_scope",
        lambda runner: _scope(logical_names={"msdyn_used"}, connectors={"shared_workdaysoap"}),
    )

    results = env_mod._check_connections_and_refs(runner)

    uc_rows = [r for r in results if r.checkpoint_id.startswith("ENV-004-UC-")]
    # Only the same-connector stale Workday connection is flagged.
    assert len(uc_rows) == 1
    assert "Stale Workday" in uc_rows[0].description
    assert not any("Other App" in r.description for r in uc_rows)


def test_env_004_summary_orphan_remediation_links_to_solutions(monkeypatch):
    """The top-level ENV-004 row, when orphan refs are present, must
    point the operator at the Power Apps Solutions page where the
    Connection References pane lives."""
    from flightcheck.checks import environment as env_mod

    # 1 connection that exists, 1 ref pointing at a DIFFERENT (missing) connection.
    runner = _make_runner(connections=[_conn("real-conn-id")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("missing-conn-id", display="Workday")])

    results = env_mod._check_connections_and_refs(runner)

    summary = next(r for r in results if r.checkpoint_id == "ENV-004")
    assert summary.status == "Failed", summary.__dict__
    assert "https://make.powerapps.com/environments/env-deeplinks/solutions" in (summary.remediation or "")


def test_env_004_summary_unbound_conns_links_to_connections_list(monkeypatch):
    """When only unbound (extra) connections exist with no orphan refs,
    the top-level row must link to the env-scoped connections list."""
    from flightcheck.checks import environment as env_mod

    # 2 connections, only the first has a ref bound to it -> second is unbound.
    runner = _make_runner(connections=[_conn("bound-conn"), _conn("unbound-conn")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("bound-conn")])

    results = env_mod._check_connections_and_refs(runner)

    summary = next(r for r in results if r.checkpoint_id == "ENV-004")
    assert summary.status == "Warning", summary.__dict__
    assert "https://make.powerautomate.com/environments/env-deeplinks/connections" in (summary.remediation or "")


def test_env_004_orphan_ref_detail_links_to_solutions(monkeypatch):
    """Each ENV-004-OR-* (orphan ref) detail row must carry the
    solutions deep link so the operator can re-bind the reference."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("missing-conn-id", display="Workday")])

    results = env_mod._check_connections_and_refs(runner)

    orphan = next(r for r in results if r.checkpoint_id.startswith("ENV-004-OR-"))
    assert orphan.status == "Failed"
    assert "https://make.powerapps.com/environments/env-deeplinks/solutions" in (orphan.remediation or "")


def test_env_004_unbound_ref_detail_links_to_solutions(monkeypatch):
    """ENV-004-UR-* (ref with no connectionid set) detail must point
    the operator at Solutions to bind the reference."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[])
    # connectionid="" -> classified as unbound ref
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("", display="UnboundRef")])

    results = env_mod._check_connections_and_refs(runner)

    unbound = next(r for r in results if r.checkpoint_id.startswith("ENV-004-UR-"))
    assert unbound.status == "Failed"
    assert "https://make.powerapps.com/environments/env-deeplinks/solutions" in (unbound.remediation or "")


def test_env_004_unbound_conn_detail_links_to_connections_list(monkeypatch):
    """ENV-004-UC-* (connection no ref points at) detail must link to
    the connections list so the operator can remove the stale entry."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("orphan-conn", display_name="Stale Connection")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])

    results = env_mod._check_connections_and_refs(runner)

    uc = next(r for r in results if r.checkpoint_id.startswith("ENV-004-UC-"))
    assert uc.status == "Warning"
    assert "https://make.powerautomate.com/environments/env-deeplinks/connections" in (uc.remediation or "")


# ---------------------------------------------------------------------------
# ENV-004-UC-* honesty: the check ONLY knows the connection isn't
# referenced by the agent's own solution. It can't see flows, canvas
# apps, or other solutions in the env. The original prose ("If unused,
# remove '<conn>' ... to reduce clutter") under-warned operators about
# the silent-breakage risk of deleting a connection used elsewhere AND
# gave no way to verify true disuse. The new prose must:
#   1) reframe the finding as scoped to THIS agent's solution
#   2) explicitly warn that deletion can silently break dependents
#   3) walk through concrete verification steps (Power Apps connection
#      detail, Power Automate flows, other solutions' connection refs)
#   4) gate the "delete" action on the operator's verification
# ---------------------------------------------------------------------------


def test_env_004_unbound_conn_result_scopes_finding_to_this_solution(monkeypatch):
    """Old result said 'No reference uses this connection' — which over-
    claims, because the check only inspects the agent's own solution.
    The new wording must scope to this agent's solution so the operator
    doesn't read it as 'nothing in the env uses this'."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("orphan-conn", display_name="Stale Connection")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])

    uc = next(
        r for r in env_mod._check_connections_and_refs(runner)
        if r.checkpoint_id.startswith("ENV-004-UC-")
    )
    assert "agent's solution" in uc.result.lower(), uc.result
    # The original over-claim string must not regress.
    assert "no reference uses this connection" not in uc.result.lower(), uc.result


def test_env_004_unbound_conn_remediation_warns_about_silent_breakage(monkeypatch):
    """Deleting a connection that's used by another resource fails
    silently from the operator's perspective (the dependent breaks on
    next run, not at delete time). The remediation must call this out
    so the operator doesn't treat 'delete to reduce clutter' as safe."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("orphan-conn", display_name="Stale Connection")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])

    uc = next(
        r for r in env_mod._check_connections_and_refs(runner)
        if r.checkpoint_id.startswith("ENV-004-UC-")
    )
    rem = (uc.remediation or "").lower()
    # Must explicitly say verification is required before deletion.
    assert "verify" in rem, rem
    # Must explicitly warn about silent breakage.
    assert ("silently" in rem) or ("does not warn" in rem), rem
    # The old phrasing was actively misleading and must not regress.
    assert "to reduce clutter" not in rem, rem


def test_env_004_unbound_conn_remediation_lists_three_verification_paths(monkeypatch):
    """Verification requires checking three places the check itself
    didn't look. All three must be named — naming only one would imply
    the others aren't relevant, and the operator would skip them."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("orphan-conn", display_name="Workday")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])

    uc = next(
        r for r in env_mod._check_connections_and_refs(runner)
        if r.checkpoint_id.startswith("ENV-004-UC-")
    )
    rem = uc.remediation or ""
    # 1. Power Automate Connections detail page (shows app dependencies).
    assert "Connections" in rem and "make.powerautomate.com/environments/env-deeplinks/connections" in rem, rem
    # 2. Power Automate flows (the only place flow dependencies show up).
    assert "Power Automate" in rem, rem
    assert "make.powerautomate.com/environments/env-deeplinks/flows" in rem, rem
    # 3. Other solutions' connection references (the connection could be
    #    bound by a connection reference in a different solution).
    assert "Connection references" in rem, rem
    assert "make.powerapps.com/environments/env-deeplinks/solutions" in rem, rem


def test_env_004_unbound_conn_remediation_names_connector_and_connection(monkeypatch):
    """The verification steps reference both the connection's display
    name (so operators can spot it in the connections list) AND the
    connector API id (so the Power Automate verification step is
    actionable — flows are filtered by connector). Dropping either
    forces the operator to cross-reference the original result text."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("orphan-conn", display_name="My Workday Conn")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [])

    uc = next(
        r for r in env_mod._check_connections_and_refs(runner)
        if r.checkpoint_id.startswith("ENV-004-UC-")
    )
    rem = uc.remediation or ""
    assert "My Workday Conn" in rem, rem
    # The connector label comes from the apiId in the _conn fixture.
    assert "shared_workdaysoap" in rem, rem


# ---------------------------------------------------------------------------
# Walkthrough prose + doc_link pins
#
# The Solutions deep link by itself is not enough — Connection References
# are only visible *inside* a solution, under Objects → Connection
# references. The remediations must spell that out, and the doc_link
# must point to Microsoft's canonical walkthrough for binding a
# connection reference, so an operator unfamiliar with the maker portal
# has a complete reference next to the abbreviated steps.
# ---------------------------------------------------------------------------

_CONN_REF_DOC = (
    "https://learn.microsoft.com/en-us/power-apps/maker/"
    "data-platform/create-connection-reference"
)


def test_env_004_orphan_detail_prose_calls_out_objects_pane(monkeypatch):
    """Operators reported they couldn't find Connection References from
    the Solutions list. The remediation must explicitly walk them
    through `Objects → Connection references` inside the solution."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("missing-conn-id", display="Workday")])

    results = env_mod._check_connections_and_refs(runner)

    orphan = next(r for r in results if r.checkpoint_id.startswith("ENV-004-OR-"))
    rem = orphan.remediation or ""
    assert "Objects" in rem and "Connection references" in rem, rem


def test_env_004_unbound_ref_detail_prose_calls_out_objects_pane(monkeypatch):
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("", display="UnboundRef")])

    results = env_mod._check_connections_and_refs(runner)

    unbound = next(r for r in results if r.checkpoint_id.startswith("ENV-004-UR-"))
    rem = unbound.remediation or ""
    assert "Objects" in rem and "Connection references" in rem, rem


def test_env_004_summary_prose_calls_out_objects_pane_when_failed(monkeypatch):
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("missing-conn-id", display="Workday")])

    results = env_mod._check_connections_and_refs(runner)

    summary = next(r for r in results if r.checkpoint_id == "ENV-004")
    rem = summary.remediation or ""
    assert "Objects" in rem and "Connection references" in rem, rem


def test_env_004_failed_summary_doc_link_points_to_connection_reference_doc(monkeypatch):
    """When the summary is FAILED (ref problems), surface Microsoft's
    canonical connection-reference walkthrough — the generic
    ess-prepare doc doesn't help an operator fix a binding."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("missing-conn-id", display="Workday")])

    results = env_mod._check_connections_and_refs(runner)

    summary = next(r for r in results if r.checkpoint_id == "ENV-004")
    assert summary.status == "Failed"
    assert summary.doc_link == _CONN_REF_DOC


def test_env_004_warning_only_summary_keeps_generic_doc_link(monkeypatch):
    """A WARNING-only summary (unbound connections, no orphan refs) is
    not really about connection references, so keep the generic
    ess-prepare doc as the summary's doc_link."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("bound-conn"), _conn("unbound-conn")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("bound-conn")])

    results = env_mod._check_connections_and_refs(runner)

    summary = next(r for r in results if r.checkpoint_id == "ENV-004")
    assert summary.status == "Warning"
    assert summary.doc_link != _CONN_REF_DOC
    assert "prepare" in (summary.doc_link or "")


def test_env_004_orphan_detail_doc_link_points_to_connection_reference_doc(monkeypatch):
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("missing-conn-id", display="Workday")])

    results = env_mod._check_connections_and_refs(runner)

    orphan = next(r for r in results if r.checkpoint_id.startswith("ENV-004-OR-"))
    assert orphan.doc_link == _CONN_REF_DOC


def test_env_004_unbound_ref_detail_doc_link_points_to_connection_reference_doc(monkeypatch):
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[])
    monkeypatch.setattr(env_mod, "query_all", lambda *a, **kw: [_ref("", display="UnboundRef")])

    results = env_mod._check_connections_and_refs(runner)

    unbound = next(r for r in results if r.checkpoint_id.startswith("ENV-004-UR-"))
    assert unbound.doc_link == _CONN_REF_DOC


# ---------------------------------------------------------------------------
# Per-row specific-solution deep links
#
# The env-wide solutions list is unhelpful — it dumps every first-party
# and ISV solution on the operator and leaves them guessing which one
# holds the broken ref. ENV-004 now resolves each ref's `_solutionid_value`
# to a friendly solution name + GUID and emits a deep link straight to
# that solution's detail page, where the Objects → Connection references
# pane lives.
# ---------------------------------------------------------------------------

_SOL_ID = "11111111-2222-3333-4444-555555555555"
_SOL_URL_FRAGMENT = f"/solutions/{_SOL_ID}"


def test_env_004_orphan_detail_deep_links_to_specific_solution(monkeypatch):
    """When we can resolve the ref's containing solution, the orphan
    detail row must deep-link to that specific solution (not the
    env-wide solutions list)."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    _patch_query_all(
        monkeypatch, env_mod,
        conn_refs=[_ref("missing-conn-id", display="Workday", solution_id=_SOL_ID)],
        solutions=[_solution(_SOL_ID, "Workday Agent Solution")],
    )

    results = env_mod._check_connections_and_refs(runner)

    orphan = next(r for r in results if r.checkpoint_id.startswith("ENV-004-OR-"))
    rem = orphan.remediation or ""
    assert _SOL_URL_FRAGMENT in rem, rem
    # The link text should surface the friendly solution name so the
    # operator can confirm they're opening the right one.
    assert "Workday Agent Solution" in rem, rem


def test_env_004_unbound_ref_detail_deep_links_to_specific_solution(monkeypatch):
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[])
    _patch_query_all(
        monkeypatch, env_mod,
        conn_refs=[_ref("", display="UnboundRef", solution_id=_SOL_ID)],
        solutions=[_solution(_SOL_ID, "Workday Agent Solution")],
    )

    results = env_mod._check_connections_and_refs(runner)

    unbound = next(r for r in results if r.checkpoint_id.startswith("ENV-004-UR-"))
    rem = unbound.remediation or ""
    assert _SOL_URL_FRAGMENT in rem, rem
    assert "Workday Agent Solution" in rem, rem


def test_env_004_detail_falls_back_to_env_solutions_when_lookup_fails(monkeypatch):
    """If the solutions lookup returns nothing (Dataverse error, missing
    permission, the ref isn't in any solutioncomponent row), the
    remediation must fall back to the env-wide solutions URL — never
    produce a 404 or a half-formed markdown link."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    # Conn-ref query succeeds, but solutioncomponents returns nothing
    # for this ref — simulates a permission/visibility gap mid-check.
    _patch_query_all(
        monkeypatch, env_mod,
        conn_refs=[_ref("missing-conn-id", display="Workday", solution_id=_SOL_ID)],
        solutions=[],  # also empty for good measure
    )
    # Override the solutioncomponents leg to return nothing.
    real_fake = env_mod.query_all

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        if entity_set == "solutioncomponents":
            return []
        return real_fake(env_url, token, entity_set, select, filter_expr=filter_expr)

    monkeypatch.setattr(env_mod, "query_all", _fake)

    results = env_mod._check_connections_and_refs(runner)

    orphan = next(r for r in results if r.checkpoint_id.startswith("ENV-004-OR-"))
    rem = orphan.remediation or ""
    assert "https://make.powerapps.com/environments/env-deeplinks/solutions" in rem
    assert _SOL_URL_FRAGMENT not in rem  # specific solution should NOT appear
    # The fallback link text reverts to the generic label.
    assert "Power Apps \u2192 Solutions" in rem


def test_env_004_detail_falls_back_when_dataverse_solutions_query_raises(monkeypatch):
    """A Dataverse exception during the lookup must not abort ENV-004 —
    it should silently fall back to the env-wide URL so the operator
    still gets actionable remediation. Covers both the
    solutioncomponents and solutions queries failing."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        if entity_set == "connectionreferences":
            return [{
                "connectionreferenceid": "broken-ref-id",
                "connectionreferencelogicalname": "logical_name",
                "connectionreferencedisplayname": "Workday",
                "connectorid": "shared_workdaysoap",
                "connectionid": "missing-conn-id",
                "statuscode": 1,
            }]
        if entity_set == "solutioncomponents":
            raise RuntimeError("403 Forbidden")
        return []

    monkeypatch.setattr(env_mod, "query_all", _fake)

    results = env_mod._check_connections_and_refs(runner)

    orphan = next(r for r in results if r.checkpoint_id.startswith("ENV-004-OR-"))
    rem = orphan.remediation or ""
    assert "https://make.powerapps.com/environments/env-deeplinks/solutions" in rem
    assert _SOL_URL_FRAGMENT not in rem


def test_env_004_solution_lookup_uses_distinct_solution_ids(monkeypatch):
    """When multiple refs live in the same solution, the lookup must
    de-dupe so we don't build an enormous OData filter and don't issue
    multiple round-trips."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    sol_filters: list[str] = []

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        if entity_set == "connectionreferences":
            return [
                {"connectionreferenceid": "r1", "connectionreferencelogicalname": "n",
                 "connectionreferencedisplayname": "Ref1", "connectorid": "x",
                 "connectionid": "missing-1", "statuscode": 1},
                {"connectionreferenceid": "r2", "connectionreferencelogicalname": "n",
                 "connectionreferencedisplayname": "Ref2", "connectorid": "x",
                 "connectionid": "missing-2", "statuscode": 1},
                {"connectionreferenceid": "r3", "connectionreferencelogicalname": "n",
                 "connectionreferencedisplayname": "Ref3", "connectorid": "x",
                 "connectionid": "missing-3", "statuscode": 1},
            ]
        if entity_set == "solutioncomponents":
            # All 3 refs live in the same solution.
            return [
                {"objectid": rid, "_solutionid_value": _SOL_ID}
                for rid in ("r1", "r2", "r3")
            ]
        if entity_set == "solutions":
            sol_filters.append(filter_expr or "")
            return [_solution(_SOL_ID, "Single Solution")]
        return []

    monkeypatch.setattr(env_mod, "query_all", _fake)

    env_mod._check_connections_and_refs(runner)

    # Exactly one solutions query, with exactly one solutionid filter.
    assert len(sol_filters) == 1, sol_filters
    assert sol_filters[0].count("solutionid eq") == 1, sol_filters[0]


def test_env_004_resolves_multiple_distinct_solutions(monkeypatch):
    """When two broken refs live in two different solutions, each
    detail row must deep-link to its own solution."""
    from flightcheck.checks import environment as env_mod

    sol_a = "aaaaaaaa-0000-0000-0000-000000000001"
    sol_b = "bbbbbbbb-0000-0000-0000-000000000002"

    runner = _make_runner(connections=[_conn("real-conn-id")])
    _patch_query_all(
        monkeypatch, env_mod,
        conn_refs=[
            _ref("missing-1", ref_id="r-a", display="RefA", solution_id=sol_a),
            _ref("missing-2", ref_id="r-b", display="RefB", solution_id=sol_b),
        ],
        solutions=[
            _solution(sol_a, "Solution A"),
            _solution(sol_b, "Solution B"),
        ],
    )

    results = env_mod._check_connections_and_refs(runner)

    orphan_rows = [r for r in results if r.checkpoint_id.startswith("ENV-004-OR-")]
    assert len(orphan_rows) == 2

    by_ref = {r.description: r.remediation or "" for r in orphan_rows}
    assert f"/solutions/{sol_a}" in by_ref["Orphan reference: RefA"]
    assert "Solution A" in by_ref["Orphan reference: RefA"]
    assert f"/solutions/{sol_b}" in by_ref["Orphan reference: RefB"]
    assert "Solution B" in by_ref["Orphan reference: RefB"]


def test_resolve_ref_solutions_no_refs_skips_dataverse_call(monkeypatch):
    """If there are no problematic refs, we must not issue an empty
    OData filter (`objectid eq` with nothing) — skip both round-trips."""
    from flightcheck.checks import environment as env_mod

    called = []

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        called.append(entity_set)
        return []

    monkeypatch.setattr(env_mod, "query_all", _fake)

    out = env_mod._resolve_ref_solutions(
        env_url="https://x.api.crm.dynamics.com",
        dv_token="tok",
        env_id="env-1",
        refs=[],
    )
    assert out == {}
    assert "solutioncomponents" not in called
    assert "solutions" not in called


# ---------------------------------------------------------------------------
# Summary remediation when broken refs resolve to specific solutions
#
# Pin the smarter summary text:
#   - All broken refs in ONE solution → summary deep-links to that solution
#   - Broken refs SPREAD across solutions → summary names them and points
#     at the env-wide list
#   - Lookup failed → summary keeps the generic prose (don't pretend to
#     know something we don't)
# ---------------------------------------------------------------------------

def test_env_004_summary_deep_links_when_all_refs_in_one_solution(monkeypatch):
    """When every broken ref lives in the same solution, the summary
    must deep-link to that specific solution — not the env-wide list."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    _patch_query_all(
        monkeypatch, env_mod,
        conn_refs=[
            _ref("missing-1", ref_id="r1", display="RefA", solution_id=_SOL_ID),
            _ref("missing-2", ref_id="r2", display="RefB", solution_id=_SOL_ID),
        ],
        solutions=[_solution(_SOL_ID, "Workday Agent Solution")],
    )

    results = env_mod._check_connections_and_refs(runner)

    summary = next(r for r in results if r.checkpoint_id == "ENV-004")
    rem = summary.remediation or ""
    assert _SOL_URL_FRAGMENT in rem, rem
    assert "Workday Agent Solution" in rem, rem
    # The "click the solution that contains your agent" hedge wording
    # should be gone now that we know the exact solution.
    assert "click the solution that contains your agent" not in rem


def test_env_004_summary_lists_solutions_when_refs_spread(monkeypatch):
    """When broken refs span multiple solutions, the summary must name
    every affected solution so the operator knows where to look."""
    from flightcheck.checks import environment as env_mod

    sol_a = "aaaaaaaa-0000-0000-0000-000000000001"
    sol_b = "bbbbbbbb-0000-0000-0000-000000000002"

    runner = _make_runner(connections=[_conn("real-conn-id")])
    _patch_query_all(
        monkeypatch, env_mod,
        conn_refs=[
            _ref("missing-1", ref_id="r-a", display="RefA", solution_id=sol_a),
            _ref("missing-2", ref_id="r-b", display="RefB", solution_id=sol_b),
        ],
        solutions=[
            _solution(sol_a, "Workday Agent Solution"),
            _solution(sol_b, "Custom Tweaks Solution"),
        ],
    )

    results = env_mod._check_connections_and_refs(runner)

    summary = next(r for r in results if r.checkpoint_id == "ENV-004")
    rem = summary.remediation or ""
    # Both affected solution names must be surfaced.
    assert "Workday Agent Solution" in rem, rem
    assert "Custom Tweaks Solution" in rem, rem
    # The env-wide solutions URL is the only viable link target when
    # multiple solutions are involved.
    assert "https://make.powerapps.com/environments/env-deeplinks/solutions" in rem
    # And it must NOT deep-link to either specific solution (would be
    # misleading — there are TWO to visit).
    assert f"/solutions/{sol_a}" not in rem
    assert f"/solutions/{sol_b}" not in rem


def test_env_004_summary_keeps_generic_prose_when_lookup_unresolved(monkeypatch):
    """If the solutioncomponents lookup returns nothing for any ref,
    the summary must fall back to the generic prose — don't claim to
    know solutions we couldn't resolve."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        if entity_set == "connectionreferences":
            return [{
                "connectionreferenceid": "broken-ref",
                "connectionreferencelogicalname": "n",
                "connectionreferencedisplayname": "Workday",
                "connectorid": "x",
                "connectionid": "missing-conn",
                "statuscode": 1,
            }]
        if entity_set == "solutioncomponents":
            return []  # ref not found in any solution component
        return []

    monkeypatch.setattr(env_mod, "query_all", _fake)

    results = env_mod._check_connections_and_refs(runner)

    summary = next(r for r in results if r.checkpoint_id == "ENV-004")
    rem = summary.remediation or ""
    # Generic prose hallmark — the hedge wording.
    assert "click the solution that contains your agent" in rem
    assert "https://make.powerapps.com/environments/env-deeplinks/solutions" in rem

# ---------------------------------------------------------------------------
# Managed-solution fallback to Default Solution.
#
# Power Apps blocks direct edits inside managed solutions with
# "You cannot directly edit the objects within a managed solution.",
# so a remediation link that lands on one is a dead end for the maker.
# The check redirects the link to Default Solution (always unmanaged,
# always present) so the maker has somewhere to actually re-bind.
# ---------------------------------------------------------------------------


_DEFAULT_SOL_ID = "00000000-0000-0000-0000-00000000DEFA"
_DEFAULT_SOL_URL_FRAGMENT = f"/solutions/{_DEFAULT_SOL_ID}"


def test_env_004_managed_only_ref_links_to_default_solution(monkeypatch):
    """When a broken ref only lives in a *managed* solution, the link
    must redirect to the Default Solution (the unmanaged customization
    layer) — never to a managed solution where edits are blocked."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    managed_sid = "00000000-0000-0000-0000-0000MANAGED1"

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        if entity_set == "connectionreferences":
            return [_ref("missing-conn-id", display="Workday")]
        if entity_set == "solutioncomponents":
            return [{"objectid": "ref-id", "_solutionid_value": managed_sid}]
        if entity_set == "solutions":
            return [
                _solution(managed_sid, "Workday Managed", ismanaged=True),
                _solution(_DEFAULT_SOL_ID, "Default Solution",
                          unique_name="Default", ismanaged=False),
            ]
        return []

    monkeypatch.setattr(env_mod, "query_all", _fake)

    results = env_mod._check_connections_and_refs(runner)
    orphan = next(r for r in results if r.checkpoint_id.startswith("ENV-004-OR-"))
    rem = orphan.remediation or ""
    # Link goes to Default, NOT to the managed solution.
    assert _DEFAULT_SOL_URL_FRAGMENT in rem, rem
    assert f"/solutions/{managed_sid}" not in rem, rem
    # Label should reflect the actual destination so the maker isn't
    # surprised by what they see when they click.
    assert "Default Solution" in rem, rem


def test_env_004_prefers_named_unmanaged_over_default_solution(monkeypatch):
    """If a ref lives in BOTH a named unmanaged solution and Default,
    prefer the named one — it's the maker's focused workspace, while
    Default is the catch-all that includes every component in the org."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    named_sid = "00000000-0000-0000-0000-0000NAMED0001"

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        if entity_set == "connectionreferences":
            return [_ref("missing-conn-id", display="Workday")]
        if entity_set == "solutioncomponents":
            # Same ref appears in two solutions.
            return [
                {"objectid": "ref-id", "_solutionid_value": named_sid},
                {"objectid": "ref-id", "_solutionid_value": _DEFAULT_SOL_ID},
            ]
        if entity_set == "solutions":
            return [
                _solution(named_sid, "Workday Customizations",
                          unique_name="WorkdayCustom", ismanaged=False),
                _solution(_DEFAULT_SOL_ID, "Default Solution",
                          unique_name="Default", ismanaged=False),
            ]
        return []

    monkeypatch.setattr(env_mod, "query_all", _fake)

    results = env_mod._check_connections_and_refs(runner)
    orphan = next(r for r in results if r.checkpoint_id.startswith("ENV-004-OR-"))
    rem = orphan.remediation or ""
    assert f"/solutions/{named_sid}" in rem, rem
    assert _DEFAULT_SOL_URL_FRAGMENT not in rem, rem
    assert "Workday Customizations" in rem, rem


def test_env_004_managed_only_with_no_default_falls_back_to_env_wide(monkeypatch):
    """Edge case: ref only lives in a managed solution AND Dataverse
    didn't return Default (shouldn't happen in practice — Default is
    always present — but be defensive). Must not link to the managed
    solution; fall back to the env-wide URL instead."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    managed_sid = "00000000-0000-0000-0000-0000MANAGED2"

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        if entity_set == "connectionreferences":
            return [_ref("missing-conn-id", display="Workday")]
        if entity_set == "solutioncomponents":
            return [{"objectid": "ref-id", "_solutionid_value": managed_sid}]
        if entity_set == "solutions":
            # No Default returned — only the managed solution.
            return [_solution(managed_sid, "Managed Only", ismanaged=True)]
        return []

    monkeypatch.setattr(env_mod, "query_all", _fake)

    results = env_mod._check_connections_and_refs(runner)
    orphan = next(r for r in results if r.checkpoint_id.startswith("ENV-004-OR-"))
    rem = orphan.remediation or ""
    # Never link to the managed solution.
    assert f"/solutions/{managed_sid}" not in rem, rem
    # Fall back to the env-wide solutions URL.
    assert "https://make.powerapps.com/environments/env-deeplinks/solutions" in rem
    # And no other specific /solutions/<guid>/ fragment leaked through.
    assert "/solutions/00000000" not in rem, rem


def test_env_004_solutions_filter_always_includes_default_uniquename(monkeypatch):
    """The solutions OData filter must always include
    `uniquename eq 'Default'` so the Default Solution row comes back
    even when the ref's containing solutions don't intersect it. Without
    this, the managed-only fallback has nowhere to redirect."""
    from flightcheck.checks import environment as env_mod

    runner = _make_runner(connections=[_conn("real-conn-id")])
    sol_filters: list[str] = []

    def _fake(env_url, token, entity_set, select, filter_expr=None):
        if entity_set == "connectionreferences":
            return [_ref("missing-conn-id", display="Workday")]
        if entity_set == "solutioncomponents":
            return [{"objectid": "ref-id", "_solutionid_value": _SOL_ID}]
        if entity_set == "solutions":
            sol_filters.append(filter_expr or "")
            return [_solution(_SOL_ID, "Some Solution")]
        return []

    monkeypatch.setattr(env_mod, "query_all", _fake)

    env_mod._check_connections_and_refs(runner)

    assert len(sol_filters) == 1, sol_filters
    assert "uniquename eq 'Default'" in sol_filters[0], sol_filters[0]
