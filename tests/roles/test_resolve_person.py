# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the roles resolver CLI (``scripts/roles/cli.py``).

The resolver turns a person's name into the directory object id that the
planner's ``attest_plan_role`` tool takes as ``subjectId``. These tests pin the
branching contract the ``/roles`` skill relies on — ``ok`` / ``no_match`` /
``auth_required`` — by faking the kit's Graph client, so nothing here touches the
network. (The live Graph ``$search`` call itself is exercised against the
schema-backed mock in ``tests/flightcheck/test_graph_client_search_users.py``.)
"""

from __future__ import annotations

import json

from roles import cli as roles_cli


def _user(oid, name, *, upn=None, mail=None):
    return {
        "id": oid,
        "displayName": name,
        "userPrincipalName": upn or f"{name.replace(' ', '.').lower()}@contoso.com",
        "mail": mail or upn or f"{name.replace(' ', '.').lower()}@contoso.com",
    }


def _fake_graph_client(users=None, *, raise_auth=False, raise_permission=False):
    """Build a stand-in for ``roles.cli.GraphClient``.

    ``authenticate`` either succeeds or raises (the sign-in-declined path);
    ``search_users`` returns the canned directory hits, or raises
    ``PermissionError`` (sign-in worked but Graph refused the directory read —
    the tenant-blocks-user-consent path).
    """

    class _Fake:
        def __init__(self, tenant_id, scopes=None):
            self.tenant_id = tenant_id
            self.scopes = scopes

        def authenticate(self):
            if raise_auth:
                raise RuntimeError("interactive sign-in declined")
            return "fake-token"

        def search_users(self, query, *, top=10):
            if raise_permission:
                raise PermissionError("Graph returned HTTP 403 resolving users.")
            return list(users or [])

    return _Fake


def test_resolve_person_single_candidate(monkeypatch):
    monkeypatch.setattr(
        roles_cli, "GraphClient", _fake_graph_client([_user("oid-1", "Priya Sharma")])
    )
    out = roles_cli.resolve_person("Priya Sharma", env_url="")
    assert out["status"] == "ok"
    assert out["count"] == 1
    only = out["candidates"][0]
    assert only["oid"] == "oid-1"
    assert only["displayName"] == "Priya Sharma"
    # Every field the skill disambiguates on is projected.
    assert set(only) == {"oid", "displayName", "userPrincipalName", "mail"}


def test_resolve_person_multiple_candidates_all_returned(monkeypatch):
    monkeypatch.setattr(
        roles_cli,
        "GraphClient",
        _fake_graph_client(
            [_user("oid-1", "Priya Sharma"), _user("oid-2", "Priya Kapoor")]
        ),
    )
    out = roles_cli.resolve_person("Priya", env_url="")
    assert out["status"] == "ok"
    assert out["count"] == 2
    # The skill needs every namesake to disambiguate — none are dropped.
    assert {c["oid"] for c in out["candidates"]} == {"oid-1", "oid-2"}


def test_resolve_person_no_match(monkeypatch):
    monkeypatch.setattr(roles_cli, "GraphClient", _fake_graph_client([]))
    out = roles_cli.resolve_person("Nobody Here", env_url="")
    assert out["status"] == "no_match"
    assert out["count"] == 0
    assert out["candidates"] == []


def test_resolve_person_auth_required(monkeypatch):
    monkeypatch.setattr(
        roles_cli, "GraphClient", _fake_graph_client(raise_auth=True)
    )
    out = roles_cli.resolve_person("Priya", env_url="")
    assert out["status"] == "auth_required"
    assert out["count"] == 0
    assert out["candidates"] == []


def test_resolve_person_permission_denied_maps_to_auth_required(monkeypatch):
    """Sign-in succeeds but Graph refuses the directory read (401/403) — the
    Microsoft-corp path. It must surface as ``auth_required``, not ``no_match``,
    so the /roles skill falls back to the WorkIQ MCP instead of telling the maker
    the person doesn't exist."""
    monkeypatch.setattr(
        roles_cli, "GraphClient", _fake_graph_client(raise_permission=True)
    )
    out = roles_cli.resolve_person("Priya", env_url="")
    assert out["status"] == "auth_required"
    assert out["count"] == 0
    assert out["candidates"] == []


def test_resolve_person_blank_name_short_circuits(monkeypatch):
    """A blank query must never hit the directory (no sign-in, no lookup)."""

    def _boom(*_a, **_k):
        raise AssertionError("GraphClient must not be constructed for blank input")

    monkeypatch.setattr(roles_cli, "GraphClient", _boom)
    out = roles_cli.resolve_person("   ", env_url="")
    assert out["status"] == "no_match"
    assert out["count"] == 0


def test_resolve_person_requests_least_privilege_scope(monkeypatch):
    """Resolution must ask for the narrow, user-consentable scope — never
    FlightCheck's admin-gated set — so a maker isn't pushed into an admin
    consent prompt just to look a name up in their own directory."""
    captured = {}

    class _Capture:
        def __init__(self, tenant_id, scopes=None):
            captured["scopes"] = scopes

        def authenticate(self):
            return "fake-token"

        def search_users(self, query, *, top=10):
            return []

    monkeypatch.setattr(roles_cli, "GraphClient", _Capture)
    roles_cli.resolve_person("Priya", env_url="")
    assert captured["scopes"] == roles_cli.PERSON_RESOLUTION_SCOPES
    # Pin the actual permission: least-privilege User.ReadBasic.All, which is
    # user-consentable, not the admin-gated User.Read.All.
    assert captured["scopes"] == ["https://graph.microsoft.com/User.ReadBasic.All"]


def test_cmd_exit_zero_and_prints_json_on_match(monkeypatch, capsys):
    monkeypatch.setattr(
        roles_cli, "GraphClient", _fake_graph_client([_user("oid-1", "Priya Sharma")])
    )
    rc = roles_cli.main(["resolve-person", "--name", "Priya", "--env-url", ""])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["candidates"][0]["oid"] == "oid-1"


def test_cmd_exit_one_only_when_auth_required(monkeypatch, capsys):
    """``no_match`` is a successful lookup (exit 0); only ``auth_required``
    exits non-zero so a caller can branch on 'needs sign-in'."""
    monkeypatch.setattr(roles_cli, "GraphClient", _fake_graph_client([]))
    assert roles_cli.main(["resolve-person", "--name", "Ghost", "--env-url", ""]) == 0
    capsys.readouterr()

    monkeypatch.setattr(
        roles_cli, "GraphClient", _fake_graph_client(raise_auth=True)
    )
    rc = roles_cli.main(["resolve-person", "--name", "Priya", "--env-url", ""])
    assert rc == 1
    assert json.loads(capsys.readouterr().out)["status"] == "auth_required"
