# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.attestable — the scripts-tree mirror of the closed
attestable-role catalogue and the uploaded-role resolver.

Pure logic, no network. The mirror MUST stay in lockstep with the backend registry
``src/mcp/agentconfig_planner/roles_surface.py``; the lockstep test AST-parses that
source (no import of the MCP package, so no ``_odata`` / network dependency), the
same technique ``test_setup_tasks.py`` uses.
"""

from __future__ import annotations

import ast
from pathlib import Path

from planner import attestable


def _registry_roles() -> dict[str, str]:
    """Compact id -> wire display name from the attestable-role registry.

    AST-parses ``roles_surface.py``'s ``_ROLES_BY_PROVIDER`` literal — the single
    source of truth this module's catalogue must match.
    """
    path = (
        Path(__file__).resolve().parents[2]
        / "solutions" / "ess-maker-skills" / "src" / "mcp"
        / "agentconfig_planner" / "roles_surface.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
        elif isinstance(node, ast.Assign) and node.targets:
            target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and target.id == "_ROLES_BY_PROVIDER"
            and isinstance(node.value, ast.Dict)
        ):
            roles: dict[str, str] = {}
            # Outer keys are PROVIDER_* name constants (not literals); only the
            # inner {compact_id: display} dicts are string literals we can eval.
            for inner in node.value.values:
                roles.update(ast.literal_eval(inner))
            return roles
    raise AssertionError("_ROLES_BY_PROVIDER not found in roles_surface.py")


class TestRegistryLockstep:
    def test_catalogue_matches_registry_exactly(self):
        assert attestable.ATTESTABLE_ROLE_WIRE_NAMES == _registry_roles()

    def test_every_role_id_is_a_real_attestable_role(self):
        registry = _registry_roles()
        for role_id in attestable.ATTESTABLE_ROLES:
            assert role_id in registry


class TestResolve:
    def test_compact_id_resolves_to_itself(self):
        assert attestable.resolve_attestable_role_id("WorkdayAdmin") == "WorkdayAdmin"
        assert attestable.resolve_attestable_role_id("PowerPlatformEnvironmentMaker") == "PowerPlatformEnvironmentMaker"

    def test_wire_display_name_resolves_to_compact_id(self):
        assert attestable.resolve_attestable_role_id("Workday administrator") == "WorkdayAdmin"
        assert attestable.resolve_attestable_role_id("Environment Maker") == "PowerPlatformEnvironmentMaker"

    def test_spacing_and_case_variants_resolve(self):
        # Slug, spaced, and odd-casing variants all fold to the same id.
        assert attestable.resolve_attestable_role_id("workday-administrator") == "WorkdayAdmin"
        assert attestable.resolve_attestable_role_id("  environment maker  ") == "PowerPlatformEnvironmentMaker"
        assert attestable.resolve_attestable_role_id("CLOUD APPLICATION ADMINISTRATOR") == "EntraCloudApplicationAdministrator"

    def test_non_attestable_returns_none(self):
        # The reviewer's example: a plausible-looking label that isn't in the set.
        assert attestable.resolve_attestable_role_id("Power Platform Admin") is None
        assert attestable.resolve_attestable_role_id("Some Future Role") is None
        assert attestable.resolve_attestable_role_id("") is None

    def test_is_attestable_role(self):
        assert attestable.is_attestable_role("ServiceNow Administrator") is True
        assert attestable.is_attestable_role("not a role") is False
