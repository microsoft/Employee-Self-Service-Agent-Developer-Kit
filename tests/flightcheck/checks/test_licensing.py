# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for LIC-FLOW-001 (agent flow licensing — connector-tier check).

LIC-FLOW-001 warns when a flow the agent invokes (topic InvokeFlowAction)
binds a premium or custom connector, because every end user who triggers
such a flow needs a Power Automate Premium / Power Apps Premium license
(seeded M365 entitlement is insufficient).

Strategy:
- Build a temp ``workspace/agents/<slug>/topics/*.mcs.yml`` carrying a
  ``flowId:`` reference and chdir into it.
- Drive ``run_licensing_checks`` with a SimpleNamespace runner whose
  ``pp_admin.get_flow`` returns flow-detail mocks built from the validated
  ``flightcheck_flow_licensing.yaml`` shape (tests/mocks/pp_admin.py).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "solutions" / "ess-maker-skills" / "scripts"


@pytest.fixture(autouse=True)
def _scripts_on_path():
    sys.path.insert(0, str(SCRIPTS_DIR))
    sys.path.insert(0, str(REPO_ROOT))
    try:
        yield
    finally:
        for p in (str(SCRIPTS_DIR), str(REPO_ROOT)):
            try:
                sys.path.remove(p)
            except ValueError:
                pass


def _require_validated_pp_mock():
    from tests.conftest import require_validated_mock
    from tests.mocks import pp_admin
    require_validated_mock(pp_admin)
    return pp_admin


FLOW_A = "11111111-1111-1111-1111-111111111111"
FLOW_B = "22222222-2222-2222-2222-222222222222"


def _make_agent_with_flows(tmp_path: Path, flow_ids: list[str], slug: str = "esshr") -> None:
    """Create workspace/agents/<slug>/topics/topic.mcs.yml referencing flow_ids."""
    topics = tmp_path / "workspace" / "agents" / slug / "topics"
    topics.mkdir(parents=True, exist_ok=True)
    body_lines = ["kind: AdaptiveDialog", "beginDialog:", "  kind: OnRecognizedIntent", "  actions:"]
    for fid in flow_ids:
        body_lines += [
            "    - kind: InvokeFlowAction",
            "      id: invokeFlowAction_x",
            f"      flowId: {fid}",
        ]
    (topics / "topic.mcs.yml").write_text("\n".join(body_lines) + "\n", encoding="utf-8")


def _runner(get_flow):
    return SimpleNamespace(env_id="env-1", pp_admin=SimpleNamespace(get_flow=get_flow), config={})


def _run(runner):
    from flightcheck.checks.licensing import run_licensing_checks
    return run_licensing_checks(runner)


def _by_id(results, cid):
    return next(r for r in results if r.checkpoint_id == cid)


# --------------------------------------------------------------- shape


def test_mock_is_validated():
    _require_validated_pp_mock()


# --------------------------------------------------------------- good state


def test_passed_when_no_flow_references(tmp_path, monkeypatch):
    """No InvokeFlowAction => nothing to license => PASSED."""
    (tmp_path / "workspace" / "agents" / "esshr" / "topics").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    runner = _runner(lambda e, f: {})
    r = _by_id(_run(runner), "LIC-FLOW-001")
    from flightcheck.runner import Status
    assert r.status == Status.PASSED.value
    assert runner._lic_flow_premium_present is False


def test_passed_when_only_standard_connectors(tmp_path, monkeypatch):
    pp = _require_validated_pp_mock()
    _make_agent_with_flows(tmp_path, [FLOW_A])
    monkeypatch.chdir(tmp_path)

    def get_flow(env_id, flow_id):
        return pp.flow_detail(
            flow_id=flow_id, display_name="Standard Flow",
            connection_refs={"r": pp.flow_connector_ref(
                api_name="shared_office365", tier="Standard")},
        )

    runner = _runner(get_flow)
    r = _by_id(_run(runner), "LIC-FLOW-001")
    from flightcheck.runner import Status
    assert r.status == Status.PASSED.value
    assert runner._lic_flow_premium_present is False
    assert r.remediation.startswith("Validated:")
    assert "standard-tier" in r.remediation


# --------------------------------------------------------------- bad state


def test_warns_on_premium_connector(tmp_path, monkeypatch):
    pp = _require_validated_pp_mock()
    _make_agent_with_flows(tmp_path, [FLOW_A])
    monkeypatch.chdir(tmp_path)

    def get_flow(env_id, flow_id):
        return pp.flow_detail(
            flow_id=flow_id, display_name="ESS HR Workday",
            connection_refs={"r": pp.flow_connector_ref(
                api_name="shared_workdaysoap", tier="Premium",
                display_name="Workday")},
        )

    runner = _runner(get_flow)
    r = _by_id(_run(runner), "LIC-FLOW-001")
    from flightcheck.runner import Status, Priority
    assert r.status == Status.WARNING.value
    assert r.priority == Priority.HIGH.value
    assert runner._lic_flow_premium_present is True
    # Names the flow + the premium connector in the result.
    assert "ESS HR Workday" in r.result
    assert "Workday" in r.result and "Premium" in r.result
    # Remediation carries the licensing implication + Copilot Credits caveat + links.
    assert "Power Automate Premium" in r.remediation
    assert "seeded" in r.remediation.lower()
    assert "credits" in r.remediation.lower() or "Copilot Studio capacity" in r.remediation
    assert "admin.microsoft.com" in r.remediation


def test_warns_on_custom_connector(tmp_path, monkeypatch):
    pp = _require_validated_pp_mock()
    _make_agent_with_flows(tmp_path, [FLOW_A])
    monkeypatch.chdir(tmp_path)

    def get_flow(env_id, flow_id):
        return pp.flow_detail(
            flow_id=flow_id, display_name="Custom Conn Flow",
            connection_refs={"r": pp.flow_connector_ref(
                api_name="shared_customconnector", tier="Standard",
                is_custom_api=True, display_name="My Custom Connector")},
        )

    runner = _runner(get_flow)
    r = _by_id(_run(runner), "LIC-FLOW-001")
    from flightcheck.runner import Status
    assert r.status == Status.WARNING.value
    assert "Custom" in r.result
    assert runner._lic_flow_premium_present is True


# --------------------------------------------------------------- edge cases


def test_skipped_without_pp_admin(tmp_path, monkeypatch):
    """Flows referenced but no Power Platform admin => SKIPPED, not a false pass."""
    _make_agent_with_flows(tmp_path, [FLOW_A])
    monkeypatch.chdir(tmp_path)
    runner = SimpleNamespace(env_id=None, pp_admin=None, config={})
    r = _by_id(_run(runner), "LIC-FLOW-001")
    from flightcheck.runner import Status
    assert r.status == Status.SKIPPED.value
    assert runner._lic_flow_premium_present is False


def test_unresolved_flow_noted_but_not_fatal(tmp_path, monkeypatch):
    """A referenced flow that 404s in the env is noted, not crashed on."""
    pp = _require_validated_pp_mock()
    _make_agent_with_flows(tmp_path, [FLOW_A, FLOW_B])
    monkeypatch.chdir(tmp_path)

    def get_flow(env_id, flow_id):
        if flow_id == FLOW_A:
            return pp.flow_detail(
                flow_id=flow_id,
                connection_refs={"r": pp.flow_connector_ref(tier="Premium")},
            )
        return {"_error": "not_found", "_status": 404}

    runner = _runner(get_flow)
    r = _by_id(_run(runner), "LIC-FLOW-001")
    from flightcheck.runner import Status
    assert r.status == Status.WARNING.value
    assert "not found in the environment" in r.result


def test_get_flow_exception_is_swallowed(tmp_path, monkeypatch):
    _require_validated_pp_mock()
    _make_agent_with_flows(tmp_path, [FLOW_A])
    monkeypatch.chdir(tmp_path)

    def get_flow(env_id, flow_id):
        raise RuntimeError("transient")

    runner = _runner(get_flow)
    # Must not raise; not-found => no premium flow, no auth gap => PASSED with note.
    r = _by_id(_run(runner), "LIC-FLOW-001")
    from flightcheck.runner import Status
    assert r.status == Status.PASSED.value
    assert "not found in the environment" in r.result


def test_lic001_all_auth_blocked_is_skipped(tmp_path, monkeypatch):
    """All flows unreadable due to 401/403 => SKIPPED, never a false PASS."""
    _require_validated_pp_mock()
    _make_agent_with_flows(tmp_path, [FLOW_A, FLOW_B])
    monkeypatch.chdir(tmp_path)

    def get_flow(env_id, flow_id):
        return {"_error": "insufficient_permissions", "_status": 403}

    runner = _runner(get_flow)
    r = _by_id(_run(runner), "LIC-FLOW-001")
    from flightcheck.runner import Status
    assert r.status == Status.SKIPPED.value
    assert runner._lic_flow_premium_present is False
    assert "could not be read" in r.result


def test_lic001_partial_auth_blocked_is_warning(tmp_path, monkeypatch):
    """Some flows readable (standard) but others 401/403 => WARNING, not PASS,
    because a premium flow may be hidden among the unreadable ones."""
    pp = _require_validated_pp_mock()
    _make_agent_with_flows(tmp_path, [FLOW_A, FLOW_B])
    monkeypatch.chdir(tmp_path)

    def get_flow(env_id, flow_id):
        if flow_id == FLOW_A:
            return pp.flow_detail(
                flow_id=flow_id,
                connection_refs={"r": pp.flow_connector_ref(
                    api_name="shared_office365", tier="Standard")},
            )
        return {"_error": "token_expired", "_status": 401}

    runner = _runner(get_flow)
    r = _by_id(_run(runner), "LIC-FLOW-001")
    from flightcheck.runner import Status
    assert r.status == Status.WARNING.value
    assert "could not be read" in r.result
    assert runner._lic_flow_premium_present is False


# ===========================================================================
# LIC-FLOW-002 — shared-user license verification
# ===========================================================================


def _require_validated_graph_mock():
    from tests.conftest import require_validated_mock
    from tests.mocks import graph
    require_validated_mock(graph)
    return graph


def _principal(ptype: str, pid: str) -> dict:
    return {
        "AccessMask": "ReadAccess",
        "Principal": {"@odata.type": f"#Microsoft.Dynamics.CRM.{ptype}", "ownerid": pid},
    }


class _FakeGraph:
    def __init__(self, licenses=None, groups=None, raise_for=()):
        self.licenses = licenses or {}     # entra_id -> [licenseDetail, ...]
        self.groups = groups or {}         # aad_group_id -> [member, ...]
        self.raise_for = set(raise_for)

    def get_user_license_details(self, uid):
        if uid in self.raise_for:
            raise RuntimeError("403")
        return self.licenses.get(uid, [])

    def get_group_transitive_members(self, gid):
        return self.groups.get(gid, [])


def _install_dataverse(monkeypatch, *, shares, systemusers=None, teams=None, teammemberships=None):
    from flightcheck.checks import licensing as lic
    systemusers = systemusers or {}
    teams = teams or {}
    teammemberships = teammemberships or {}

    def fake_retrieve(env_url, token, bot_id):
        val = shares.get(bot_id)
        if isinstance(val, Exception):
            raise val
        return {"PrincipalAccesses": val or []}

    def fake_query_all(env_url, token, entity_set, select, filter_expr=None):
        rid = filter_expr.split("eq", 1)[1].strip() if filter_expr else None
        if entity_set == "systemusers":
            row = systemusers.get(rid)
            return [row] if row else []
        if entity_set == "teams":
            row = teams.get(rid)
            return [row] if row else []
        if entity_set == "teammemberships":
            return teammemberships.get(rid, [])
        return []

    monkeypatch.setattr(lic, "retrieve_shared_principals_and_access", fake_retrieve)
    monkeypatch.setattr(lic, "query_all", fake_query_all)


def _sysuser(uid, aad, upn, *, disabled=False, app=None):
    return {
        "systemuserid": uid, "azureactivedirectoryobjectid": aad,
        "domainname": upn, "isdisabled": disabled, "applicationid": app,
    }


def _runner002(graph, *, premium=True, bot_id="bot-1"):
    return SimpleNamespace(
        env_url="https://org.crm.dynamics.com", dv_token="t", graph=graph,
        config={"agents": [{"botId": bot_id}]},
        _lic_flow_premium_present=premium,
    )


def _lic002(runner):
    from flightcheck.checks.licensing import _check_shared_user_licensing
    return _check_shared_user_licensing(runner)


def _premium_license():
    g = _require_validated_graph_mock()
    return g.license_detail(sku_part_number="FLOW_PER_USER")


def test_lic002_no_row_when_no_premium_flow():
    """Gating: no premium-connector flow ⇒ LIC-FLOW-002 emits nothing."""
    runner = _runner002(_FakeGraph(), premium=False)
    assert _lic002(runner) == []


def test_lic002_skipped_without_graph(monkeypatch):
    _install_dataverse(monkeypatch, shares={"bot-1": [_principal("systemuser", "u1")]})
    runner = _runner002(None, premium=True)
    r = _lic002(runner)[0]
    from flightcheck.runner import Status
    assert r.checkpoint_id == "LIC-FLOW-002"
    assert r.status == Status.SKIPPED.value


def test_lic002_passed_all_licensed(monkeypatch):
    graph = _FakeGraph(licenses={"aad-1": [_premium_license()]})
    _install_dataverse(
        monkeypatch,
        shares={"bot-1": [_principal("systemuser", "u1")]},
        systemusers={"u1": _sysuser("u1", "aad-1", "alice@contoso.com")},
    )
    r = _lic002(_runner002(graph))[0]
    from flightcheck.runner import Status
    assert r.status == Status.PASSED.value
    assert r.remediation.startswith("Validated:")
    assert "qualifying" in r.remediation


def test_lic002_fail_when_some_missing(monkeypatch):
    graph = _FakeGraph(licenses={"aad-1": [_premium_license()]})  # u2 has none
    _install_dataverse(
        monkeypatch,
        shares={"bot-1": [_principal("systemuser", "u1"), _principal("systemuser", "u2")]},
        systemusers={
            "u1": _sysuser("u1", "aad-1", "alice@contoso.com"),
            "u2": _sysuser("u2", "aad-2", "bob@contoso.com"),
        },
    )
    r = _lic002(_runner002(graph))[0]
    from flightcheck.runner import Status
    assert r.status == Status.FAILED.value
    assert "bob@contoso.com" in r.result
    assert "alice@contoso.com" not in r.result.split("Missing:")[-1]
    assert "Publish-with-caveat" in r.remediation


def test_lic002_all_unlicensed_is_warning_not_fail(monkeypatch):
    """Everyone unlicensed ⇒ likely a permission gap ⇒ WARNING, never a mass FAIL."""
    graph = _FakeGraph(licenses={})
    _install_dataverse(
        monkeypatch,
        shares={"bot-1": [_principal("systemuser", "u1")]},
        systemusers={"u1": _sysuser("u1", "aad-1", "alice@contoso.com")},
    )
    r = _lic002(_runner002(graph))[0]
    from flightcheck.runner import Status
    assert r.status == Status.WARNING.value
    assert "User.Read.All" in r.remediation or "Directory.Read.All" in r.remediation


def test_lic002_app_and_disabled_users_skipped(monkeypatch):
    graph = _FakeGraph(licenses={"aad-1": [_premium_license()]})
    _install_dataverse(
        monkeypatch,
        shares={"bot-1": [
            _principal("systemuser", "u1"),
            _principal("systemuser", "app"),   # application user => skipped
            _principal("systemuser", "dis"),   # disabled => skipped
        ]},
        systemusers={
            "u1": _sysuser("u1", "aad-1", "alice@contoso.com"),
            "app": _sysuser("app", "aad-app", "svc@contoso.com", app="appid-123"),
            "dis": _sysuser("dis", "aad-dis", "old@contoso.com", disabled=True),
        },
    )
    r = _lic002(_runner002(graph))[0]
    from flightcheck.runner import Status
    assert r.status == Status.PASSED.value
    assert "1 shared-with user(s)" in r.result  # only alice counts


def test_lic002_entra_group_team_expanded_via_graph(monkeypatch):
    members = [
        {"id": "aad-1", "userPrincipalName": "alice@contoso.com"},
        {"id": "aad-2", "userPrincipalName": "bob@contoso.com"},
        {"id": "grp-nested", "displayName": "Nested Group"},  # no UPN => ignored
    ]
    graph = _FakeGraph(licenses={"aad-1": [_premium_license()]}, groups={"grp-aad": members})
    _install_dataverse(
        monkeypatch,
        shares={"bot-1": [_principal("team", "team-1")]},
        teams={"team-1": {"teamid": "team-1", "name": "HR Group",
                          "azureactivedirectoryobjectid": "grp-aad"}},
    )
    r = _lic002(_runner002(graph))[0]
    from flightcheck.runner import Status
    assert r.status == Status.FAILED.value      # alice licensed, bob missing
    assert "bob@contoso.com" in r.result


def test_lic002_owner_team_expanded_via_membership(monkeypatch):
    graph = _FakeGraph(licenses={"aad-1": [_premium_license()], "aad-2": [_premium_license()]})
    _install_dataverse(
        monkeypatch,
        shares={"bot-1": [_principal("team", "team-own")]},
        teams={"team-own": {"teamid": "team-own", "name": "Owner Team",
                            "azureactivedirectoryobjectid": None}},
        teammemberships={"team-own": [{"systemuserid": "u1"}, {"systemuserid": "u2"}]},
        systemusers={
            "u1": _sysuser("u1", "aad-1", "alice@contoso.com"),
            "u2": _sysuser("u2", "aad-2", "bob@contoso.com"),
        },
    )
    r = _lic002(_runner002(graph))[0]
    from flightcheck.runner import Status
    assert r.status == Status.PASSED.value
    assert "2 shared-with user(s)" in r.result


def test_lic002_group_over_cap_noted(monkeypatch):
    from flightcheck.checks.licensing import MAX_MEMBERS_PER_GROUP
    big = [{"id": f"aad-{i}", "userPrincipalName": f"u{i}@contoso.com"}
           for i in range(MAX_MEMBERS_PER_GROUP + 5)]
    graph = _FakeGraph(licenses={}, groups={"grp-big": big})
    _install_dataverse(
        monkeypatch,
        shares={"bot-1": [_principal("team", "team-big")]},
        teams={"team-big": {"teamid": "team-big", "name": "Everyone",
                            "azureactivedirectoryobjectid": "grp-big"}},
    )
    r = _lic002(_runner002(graph))[0]
    assert f">= {MAX_MEMBERS_PER_GROUP}" in r.result
    assert f"{MAX_MEMBERS_PER_GROUP} shared-with user(s)" in r.result  # capped


def test_lic002_not_shared_is_passed(monkeypatch):
    _install_dataverse(monkeypatch, shares={"bot-1": []})
    r = _lic002(_runner002(_FakeGraph()))[0]
    from flightcheck.runner import Status
    assert r.status == Status.PASSED.value
    assert "not yet shared" in r.result


def test_lic002_enumerate_failure_is_warning(monkeypatch):
    _install_dataverse(monkeypatch, shares={"bot-1": RuntimeError("boom")})
    r = _lic002(_runner002(_FakeGraph()))[0]
    from flightcheck.runner import Status
    assert r.status == Status.WARNING.value


def test_lic002_undetermined_license_read(monkeypatch):
    # alice licensed (proves perms work), carol's licenseDetails read raises.
    graph = _FakeGraph(licenses={"aad-1": [_premium_license()]}, raise_for={"aad-3"})
    _install_dataverse(
        monkeypatch,
        shares={"bot-1": [_principal("systemuser", "u1"), _principal("systemuser", "u3")]},
        systemusers={
            "u1": _sysuser("u1", "aad-1", "alice@contoso.com"),
            "u3": _sysuser("u3", "aad-3", "carol@contoso.com"),
        },
    )
    r = _lic002(_runner002(graph))[0]
    from flightcheck.runner import Status
    assert r.status == Status.WARNING.value
    assert "carol@contoso.com" in r.result


def test_lic002_group_only_all_licensed_passes_with_group_note(monkeypatch):
    """AC7: shared only with a Premium-licensed security group => PASS, with an
    informational note acknowledging licensing was verified via the group."""
    members = [
        {"id": "aad-1", "userPrincipalName": "alice@contoso.com", "accountEnabled": True},
        {"id": "aad-2", "userPrincipalName": "bob@contoso.com", "accountEnabled": True},
    ]
    graph = _FakeGraph(
        licenses={"aad-1": [_premium_license()], "aad-2": [_premium_license()]},
        groups={"grp-aad": members},
    )
    _install_dataverse(
        monkeypatch,
        shares={"bot-1": [_principal("team", "team-1")]},
        teams={"team-1": {"teamid": "team-1", "name": "ESS Users",
                          "azureactivedirectoryobjectid": "grp-aad"}},
    )
    r = _lic002(_runner002(graph))[0]
    from flightcheck.runner import Status
    assert r.status == Status.PASSED.value
    assert "2 shared-with user(s)" in r.result
    # The note names the group so the maker sees licensing was verified via it.
    assert "ESS Users" in r.result
    assert "via shared group" in r.result


def test_lic002_auth_expired_propagates(monkeypatch):
    """An expired Dataverse token must propagate (=> runner ERROR row),
    not be swallowed into a benign WARNING."""
    from auth import AuthExpiredError
    _install_dataverse(monkeypatch, shares={"bot-1": AuthExpiredError("401")})
    with pytest.raises(AuthExpiredError):
        _lic002(_runner002(_FakeGraph()))


def test_lic002_disabled_group_member_skipped(monkeypatch):
    """A disabled Entra group member is excluded (can't trigger the flow), so
    they don't count toward 'missing' / push the check to FAIL."""
    members = [
        {"id": "aad-1", "userPrincipalName": "alice@contoso.com", "accountEnabled": True},
        {"id": "aad-2", "userPrincipalName": "bob@contoso.com", "accountEnabled": False},
    ]
    # alice licensed; bob is disabled+unlicensed but must be ignored.
    graph = _FakeGraph(licenses={"aad-1": [_premium_license()]}, groups={"grp-aad": members})
    _install_dataverse(
        monkeypatch,
        shares={"bot-1": [_principal("team", "team-1")]},
        teams={"team-1": {"teamid": "team-1", "name": "HR Group",
                          "azureactivedirectoryobjectid": "grp-aad"}},
    )
    r = _lic002(_runner002(graph))[0]
    from flightcheck.runner import Status
    assert r.status == Status.PASSED.value
    assert "1 shared-with user(s)" in r.result  # only alice
    assert "bob@contoso.com" not in r.result

