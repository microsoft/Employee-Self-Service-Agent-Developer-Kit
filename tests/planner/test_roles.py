# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.roles — the absent-safe roles-source seam (pure logic)."""

from __future__ import annotations

from planner.roles import (
    RoleDirectory,
    StaticRoleSource,
    is_well_formed_role_id,
)

ANN = "00000000-0000-0000-0000-0000000000b2"
PAUL = "00000000-0000-0000-0000-0000000000b1"


def test_well_formed_role_id():
    assert is_well_formed_role_id("power-platform-admin")
    assert is_well_formed_role_id("eval-author")
    assert not is_well_formed_role_id("Power Platform Admin")  # spaces/caps
    assert not is_well_formed_role_id("-leading")
    assert not is_well_formed_role_id("")


def test_directory_absent_safe_defaults():
    d = RoleDirectory()  # no source wired
    assert d.available is False
    # is_valid_role degrades to a well-formed check
    assert d.is_valid_role("integration-owner") is True
    assert d.is_valid_role("Not Valid") is False
    # holds is "unknown"; enumerations are empty (skill falls back)
    assert d.holds(PAUL, "integration-owner") is None
    assert d.list_holders("integration-owner") == []
    assert d.roles_of(PAUL) == []


def test_directory_with_static_source():
    source = StaticRoleSource(
        {
            "integration-owner": [{"oid": PAUL, "displayName": "Paul"}],
            "eval-author": [
                {"oid": ANN, "displayName": "Ann"},
                {"oid": PAUL, "displayName": "Paul"},
            ],
        }
    )
    d = RoleDirectory(source)
    assert d.available is True
    # Flow 1: list holders of a role
    holders = d.list_holders("eval-author")
    assert {h["oid"] for h in holders} == {ANN, PAUL}
    # Flow 2: which roles a person holds (multi-role)
    roles = {r["roleId"] for r in d.roles_of(PAUL)}
    assert roles == {"integration-owner", "eval-author"}
    # holds is now answerable
    assert d.holds(ANN, "eval-author") is True
    assert d.holds(ANN, "integration-owner") is False


def test_static_source_is_valid_role_accepts_wellformed_unknown():
    source = StaticRoleSource({"known-role": []})
    d = RoleDirectory(source)
    assert d.is_valid_role("known-role") is True
    # unknown but well-formed still validates (roster may be incomplete)
    assert d.is_valid_role("another-role") is True
