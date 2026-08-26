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


def _user(oid, name, *, upn=None, mail=None, title="Analyst"):
    return {
        "id": oid,
        "displayName": name,
        "userPrincipalName": upn or f"{name.replace(' ', '.').lower()}@contoso.com",
        "mail": mail or upn or f"{name.replace(' ', '.').lower()}@contoso.com",
        "jobTitle": title,
    }


def _fake_graph_client(users=None, *, raise_auth=False):
    """Build a stand-in for ``roles.cli.GraphClient``.

    ``authenticate`` either succeeds or raises (the sign-in-declined path);
    ``search_users`` returns the canned directory hits.
    """

    class _Fake:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

        def authenticate(self):
            if raise_auth:
                raise RuntimeError("interactive sign-in declined")
            return "fake-token"

        def search_users(self, query, *, top=10):
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
    assert set(only) == {"oid", "displayName", "userPrincipalName", "mail", "jobTitle"}


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


def test_resolve_person_blank_name_short_circuits(monkeypatch):
    """A blank query must never hit the directory (no sign-in, no lookup)."""

    def _boom(*_a, **_k):
        raise AssertionError("GraphClient must not be constructed for blank input")

    monkeypatch.setattr(roles_cli, "GraphClient", _boom)
    out = roles_cli.resolve_person("   ", env_url="")
    assert out["status"] == "no_match"
    assert out["count"] == 0


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
