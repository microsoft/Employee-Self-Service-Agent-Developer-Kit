# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.roles — the absent-safe roles-source seam (pure logic)."""

from __future__ import annotations

from planner.roles import (
    DEFAULT_REGISTRY,
    RoleDef,
    RoleDirectory,
    RoleRegistry,
    StaticRoleSource,
    is_well_formed_role_id,
    slugify_role_id,
)

ANN = "00000000-0000-0000-0000-0000000000b2"
PAUL = "00000000-0000-0000-0000-0000000000b1"


def test_well_formed_role_id():
    assert is_well_formed_role_id("power-platform-admin")
    assert is_well_formed_role_id("eval-author")
    assert not is_well_formed_role_id("Power Platform Admin")  # spaces/caps
    assert not is_well_formed_role_id("-leading")
    assert not is_well_formed_role_id("")


def test_slugify_role_id_from_checklist_labels():
    # The verbatim Workday checklist labels slugify to stable, well-formed ids.
    cases = {
        "App/Cloud App Admin": "app-cloud-app-admin",
        "Workday Administrator": "workday-administrator",
        "Environment Maker": "environment-maker",
        "InfoSec/IT": "infosec-it",
        "Power Platform Administrator": "power-platform-administrator",
    }
    for label, expected in cases.items():
        assert slugify_role_id(label) == expected
        assert is_well_formed_role_id(slugify_role_id(label))  # always valid


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


# --- role registry (the WeveNova valid-role catalogue) ----------------------- #

def test_registry_exact_match_is_ordinal_and_case_sensitive():
    r = DEFAULT_REGISTRY
    # Exact wire ids are known; slugs / wrong case / no-space variants are not.
    assert r.is_known_task_role("Power Platform Administrator")
    assert r.is_known_task_role("WorkdayAdmin")
    assert r.is_known_task_role("Environment Maker")
    assert not r.is_known_task_role("power-platform-administrator")   # slug rejected
    assert not r.is_known_task_role("power platform administrator")   # wrong case
    assert not r.is_known_task_role("PowerPlatformAdministrator")     # no spaces
    assert not r.is_known_task_role("Workday Administrator")          # External uses compact id


def test_registry_attestable_and_provider():
    r = DEFAULT_REGISTRY
    assert r.is_attestable("WorkdayAdmin")
    assert r.is_attestable("Environment Maker")
    assert not r.is_attestable("AgentOwner")                 # internal authority role
    assert r.provider_of("WorkdayAdmin") == "External"
    assert r.provider_of("Global Administrator") == "Entra"
    assert r.provider_of("Environment Maker") == "PowerPlatform"
    assert r.provider_of("AgentOwner") == "AgentConfiguration"


def test_registry_find_resolves_free_text_to_canonical_id():
    r = DEFAULT_REGISTRY
    # Exact id round-trips; display name and casing variants resolve to the id.
    assert r.find("WorkdayAdmin").role == "WorkdayAdmin"
    assert r.find("Workday Administrator").role == "WorkdayAdmin"      # display -> compact id
    assert r.find("workday administrator").role == "WorkdayAdmin"      # case-insensitive
    assert r.find("Power Platform Administrator").role == "Power Platform Administrator"
    assert r.find("environment maker").role == "Environment Maker"
    assert r.find("no such role") is None


def test_registry_allowed_names_render_external_with_wire_id():
    names = DEFAULT_REGISTRY.allowed_attestable_names("External")
    # External display != id, so the nudge shows "Display (WireId)".
    assert "Workday Administrator (WorkdayAdmin)" in names
    # Entra id == display, so it renders bare.
    entra = DEFAULT_REGISTRY.allowed_attestable_names("Entra")
    assert "Power Platform Administrator" in entra


def test_registry_from_mcp_uses_live_payload_and_falls_back():
    class Fake:
        def __init__(self, payload):
            self._payload = payload
        def call_tool(self, name, args=None):
            if isinstance(self._payload, Exception):
                raise self._payload
            return self._payload

    payload = {"roles": [
        {"provider": "External", "role": "WorkdayAdmin",
         "displayName": "Workday Administrator", "attestable": True},
        {"provider": "AgentConfiguration", "role": "AgentOwner",
         "displayName": "AgentOwner", "attestable": False},
    ]}
    reg = RoleRegistry.from_mcp(Fake(payload))
    assert reg.is_attestable("WorkdayAdmin")
    assert reg.provider_of("WorkdayAdmin") == "External"
    assert not reg.is_attestable("AgentOwner")

    # On any error the static catalogue is used, so the registry is never empty.
    from planner.mcp_client import McpError
    reg2 = RoleRegistry.from_mcp(Fake(McpError("down")))
    assert reg2.is_known_task_role("Environment Maker")
