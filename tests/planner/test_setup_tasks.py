# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.setup_tasks — the grounded setup-task decomposer.

Pure logic, no network (see ``tests/AGENTS.md`` — pure-logic helpers are exempt
from the FlightCheck cassette rule). These tests pin the behaviour that fixes
the planner's Workday task list: every checklist step is accounted for, roles are
grounded from the checklist and mapped to the *correct attestable* role (Workday
SSO -> Cloud Application Administrator, NOT Global Administrator), and no role is
invented. The attestable-role mapping is cross-checked against the backend
registry mirror (``roles_surface.py``) so the two never drift.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from planner import setup_tasks
from planner.setup_tasks import (
    canonical_role,
    checklist_path,
    ground_role,
    parse_setup_checklist,
    system_setup_tasks,
)

# The canonical Workday Step IDs (kept in lockstep with
# tests/setup/test_checklist_template.py).
_EXPECTED_STEPS = {
    "S1.1", "S1.2",
    "S2.1",
    "S3.1", "S3.2", "S3.3", "S3.4", "S3.5", "S3.6", "S3.7",
    "S4.1", "S4.2", "S4.3", "S4.4",
    "S5.1", "S5.2", "S5.3", "S5.4", "S5.5", "S5.6", "S5.7", "S5.8",
    "S6.1", "S6.2", "S6.3",
}

_WORKDAY_TASK_ORDER = [
    "workday-pp-environment",
    "workday-ess-base-agent",
    "workday-sso-entra",
    "workday-tenant-config",
    "workday-pack-connect",
    "workday-firewall-allowlist",
    "workday-first-topic",
]


def _registry_roles() -> dict[str, str]:
    """Compact id -> wire display name from the attestable-role registry.

    AST-parses ``roles_surface.py``'s ``_ROLES_BY_PROVIDER`` literal (no import of
    the MCP package, so no network / _odata dependency) — the single source of
    truth this module's mapping must stay in lockstep with.
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


class TestParse:
    def test_covers_all_25_steps_and_6_groups(self):
        items = parse_setup_checklist(checklist_path("workday").read_text(encoding="utf-8"))
        assert {it.step_id for it in items} == _EXPECTED_STEPS
        assert {it.group_index for it in items} == {1, 2, 3, 4, 5, 6}
        # Every item is grounded — a role label and a gate to reason about.
        assert all(it.role_label for it in items)
        assert all(it.gate for it in items)

    def test_item_titles_come_from_the_bold_lead(self):
        items = {it.step_id: it for it in parse_setup_checklist(
            checklist_path("workday").read_text(encoding="utf-8"))}
        assert items["S5.8"].title == "Allow Workday through your firewall"
        assert items["S3.1"].group_title == "Workday single sign-on (Entra)"


class TestRoleGrounding:
    def test_canonical_role_collapses_messy_labels(self):
        cases = {
            "App/Cloud App Admin": "App/Cloud App Admin",
            "App/Cloud App Admin or App Owner": "App/Cloud App Admin",
            "Consent-capable role (App/Cloud App Admin, Priv Role Admin, GA)": "App/Cloud App Admin",
            "Environment Maker": "Environment Maker",
            "Environment Maker (+ Workday SME)": "Environment Maker",
            "Power Platform Administrator": "Power Platform Administrator",
            "Workday Administrator": "Workday Administrator",
            "InfoSec/IT": "InfoSec/IT",
        }
        for raw, expected in cases.items():
            assert canonical_role(raw) == expected

    def test_ground_role_maps_each_role_to_its_attestable_id(self):
        expected = {
            "Power Platform Administrator": ("power-platform-administrator", "EntraPowerPlatformAdministrator"),
            "Environment Maker": ("environment-maker", "PowerPlatformEnvironmentMaker"),
            "App/Cloud App Admin": ("app-cloud-app-admin", "EntraCloudApplicationAdministrator"),
            "Workday Administrator": ("workday-administrator", "WorkdayAdmin"),
            "InfoSec/IT": ("infosec-it", "EntraNetworkAdministrator"),
        }
        for raw, (grounded_id, attestable) in expected.items():
            grounded = ground_role(raw)
            assert grounded.grounded_id == grounded_id
            assert grounded.attestable_role == attestable
            assert grounded.mapped is True

    def test_sso_role_is_not_global_administrator(self):
        # The crux of the fix: App/Cloud App Admin must map to the least-
        # privilege Cloud Application Administrator, never Global Administrator.
        assert ground_role("App/Cloud App Admin").attestable_role == "EntraCloudApplicationAdministrator"
        assert setup_tasks._ATTESTABLE_BY_GROUNDED["app-cloud-app-admin"] != "EntraGlobalAdministrator"

    def test_unmapped_role_falls_back_without_claiming_attestable(self):
        grounded = ground_role("Some Future Role")
        assert grounded.mapped is False
        assert grounded.attestable_role == grounded.grounded_id == "some-future-role"


class TestRegistryLockstep:
    def test_mapping_targets_are_real_attestable_roles(self):
        registry = _registry_roles()
        for attestable in setup_tasks._ATTESTABLE_BY_GROUNDED.values():
            assert attestable in registry, f"{attestable} is not an attestable role"

    def test_display_names_match_registry(self):
        registry = _registry_roles()
        for attestable, display in setup_tasks._ATTESTABLE_DISPLAY.items():
            assert registry.get(attestable) == display


class TestWorkdayDecomposition:
    def test_task_order_and_ids(self):
        tasks = system_setup_tasks("workday")
        assert [t.task_id for t in tasks] == _WORKDAY_TASK_ORDER

    def test_every_step_covered_exactly_once(self):
        covered = [s for t in system_setup_tasks("workday") for s in t.step_ids]
        assert len(covered) == 25
        assert len(covered) == len(set(covered))  # no step duplicated
        assert set(covered) == _EXPECTED_STEPS

    def test_roles_are_correct_and_attestable(self):
        registry = _registry_roles()
        by_id = {t.task_id: t for t in system_setup_tasks("workday")}
        assert by_id["workday-pp-environment"].role == "EntraPowerPlatformAdministrator"
        assert by_id["workday-ess-base-agent"].role == "PowerPlatformEnvironmentMaker"
        assert by_id["workday-sso-entra"].role == "EntraCloudApplicationAdministrator"
        assert by_id["workday-tenant-config"].role == "WorkdayAdmin"
        assert by_id["workday-pack-connect"].role == "PowerPlatformEnvironmentMaker"
        assert by_id["workday-firewall-allowlist"].role == "EntraNetworkAdministrator"
        assert by_id["workday-first-topic"].role == "PowerPlatformEnvironmentMaker"
        for task in by_id.values():
            assert task.attestable is True
            assert task.role in registry

    def test_no_invented_or_nonattestable_roles(self):
        tasks = system_setup_tasks("workday")
        roles = {t.role for t in tasks}
        # The over-privileged / non-attestable slugs the old freehand path emitted.
        assert "EntraGlobalAdministrator" not in roles
        forbidden = {
            "global-administrator", "network-administrator",
            "app-cloud-app-admin", "environment-maker",
            "workday-administrator", "infosec-it",
        }
        assert roles.isdisjoint(forbidden)

    def test_produces_consumes_threaded(self):
        by_id = {t.task_id: t for t in system_setup_tasks("workday")}
        assert by_id["workday-pp-environment"].produces == ["primaryEnvironment"]
        assert by_id["workday-sso-entra"].produces == ["workdayEntraApp"]
        assert by_id["workday-pack-connect"].consumes == ["workdayEntraApp", "workdayTenantConfig"]
        assert by_id["workday-firewall-allowlist"].produces == ["workdayNetworkAllowlist"]
        assert by_id["workday-first-topic"].produces == ["topic:workday"]

    def test_grounding_and_nuance_preserved_in_description(self):
        by_id = {t.task_id: t for t in system_setup_tasks("workday")}
        sso = by_id["workday-sso-entra"]
        assert "setup/workday/tasks.md" in sso.description
        assert "S3.1-S3.7" in sso.description
        # Consent escalation nuance survives grounding.
        assert "Global Administrator" in sso.description
        # SME collaborator nuance survives on the topic task.
        assert "Workday SME" in by_id["workday-first-topic"].description

    def test_skip_foundation_drops_groups_1_and_2(self):
        tasks = system_setup_tasks("workday", skip_foundation=True)
        groups = {t.group_index for t in tasks}
        assert 1 not in groups and 2 not in groups
        assert [t.task_id for t in tasks] == _WORKDAY_TASK_ORDER[2:]

    def test_commands_include_workday_step_five_split(self):
        # Group 5 is multi-role: Environment Maker (pack + connect) AND
        # InfoSec/IT (firewall), so it must yield two tasks, not one.
        g5 = [t for t in system_setup_tasks("workday") if t.group_index == 5]
        assert {t.role for t in g5} == {"PowerPlatformEnvironmentMaker", "EntraNetworkAdministrator"}


class TestCommandRendering:
    def test_add_task_command_shape(self):
        sso = {t.task_id: t for t in system_setup_tasks("workday")}["workday-sso-entra"]
        cmd = sso.add_task_command()
        assert cmd.startswith("python scripts/planner/cli.py add-task --id workday-sso-entra")
        assert '--title "Set up Workday single sign-on (Entra)"' in cmd
        assert "--role EntraCloudApplicationAdministrator" in cmd
        assert '--produces "workdayEntraApp"' in cmd
        assert '--consumes "primaryEnvironment"' in cmd
        # Quotes are balanced (no unterminated shell argument).
        assert cmd.count('"') % 2 == 0

    def test_firewall_command_has_no_consumes_flag(self):
        firewall = {t.task_id: t for t in system_setup_tasks("workday")}["workday-firewall-allowlist"]
        cmd = firewall.add_task_command()
        assert "--consumes" not in cmd
        assert '--produces "workdayNetworkAllowlist"' in cmd


class TestUnknownSystem:
    def test_missing_checklist_raises(self):
        with pytest.raises(FileNotFoundError):
            system_setup_tasks("servicenow")
