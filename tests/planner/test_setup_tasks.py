# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for planner.setup_tasks — the grounded setup-task decomposer.

Pure logic, no network (see ``tests/AGENTS.md`` — pure-logic helpers are exempt
from the FlightCheck cassette rule). The Workday planning reference
(``src/skills/planner/systems/workday.md``) maps the ``/setup`` foundation and the
six ``/connect-workday`` phases onto role-boundary tasks. These tests pin that
mapping to its sources of truth so it cannot drift silently:

* the phases follow ``PHASE_DEFINITIONS`` (``scripts/workday_connect_model.py``),
  and the produces/consumes ledger honours each phase's prerequisite;
* every reference step lands in exactly one task;
* every role is grounded and mapped to an attestable role in the backend registry
  (``roles_surface.py``) — the Microsoft Entra work maps to Cloud Application
  Administrator, never Global Administrator;
* every emitted ``add-task`` line parses with the real planner CLI parser.
"""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path
from typing import NamedTuple

import pytest

from planner import setup_tasks
from planner.cli import build_parser
from planner.setup_tasks import (
    canonical_role,
    checklist_path,
    decompose,
    ground_role,
    parse_setup_checklist,
    system_setup_tasks,
)
from workday_connect_model import PHASE_DEFINITIONS

_SOLUTION_ROOT = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills"

_EXPECTED_STEPS = [
    "S1.1", "S1.2",
    "S2.1",
    "S3.1",
    "S4.1", "S4.2", "S4.3", "S4.4",
    "S5.1", "S5.2", "S5.3",
    "S6.1", "S6.2", "S6.3",
]


class _Expected(NamedTuple):
    role: str
    steps: list[str]
    phases: list[str]
    produces: list[str]
    consumes: list[str]
    command: str | None


# One task per role boundary, in plan order.
_WORKDAY_TASKS = {
    "workday-pp-environment": _Expected(
        role="EntraPowerPlatformAdministrator",
        steps=["S1.1", "S1.2"],
        phases=[],
        produces=["primaryEnvironment"],
        consumes=[],
        command=None,
    ),
    "workday-ess-hr-agent": _Expected(
        role="PowerPlatformEnvironmentMaker",
        steps=["S2.1"],
        phases=[],
        produces=["essAgent"],
        consumes=["primaryEnvironment"],
        command="/setup",
    ),
    "workday-preflight": _Expected(
        role="PowerPlatformEnvironmentMaker",
        steps=["S3.1"],
        phases=["preflight"],
        produces=["workdayPreflight"],
        consumes=["primaryEnvironment", "essAgent"],
        command="/connect-workday",
    ),
    "workday-entra-app": _Expected(
        role="EntraCloudApplicationAdministrator",
        steps=["S4.1", "S4.2", "S4.3", "S4.4"],
        phases=["entra"],
        produces=["workdayEntraApp"],
        consumes=["workdayPreflight"],
        command=None,
    ),
    "workday-tenant-config": _Expected(
        role="WorkdayAdmin",
        steps=["S5.1", "S5.2", "S5.3"],
        phases=["workday-admin"],
        produces=["workdayTenantConfig"],
        consumes=["workdayEntraApp"],
        command=None,
    ),
    "workday-connect": _Expected(
        role="PowerPlatformEnvironmentMaker",
        steps=["S6.1", "S6.2", "S6.3"],
        phases=["connections", "runtime", "maker-validation"],
        produces=["workdayConnection"],
        consumes=["primaryEnvironment", "essAgent", "workdayEntraApp", "workdayTenantConfig"],
        command="/connect-workday",
    ),
}


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


def _reference_items() -> list[setup_tasks.ChecklistItem]:
    return parse_setup_checklist(checklist_path("workday").read_text(encoding="utf-8"))


def _workday_tasks() -> dict[str, setup_tasks.SetupTask]:
    return {t.task_id: t for t in system_setup_tasks("workday")}


class TestReference:
    def test_parses_every_step_under_its_group(self):
        items = _reference_items()
        assert [it.step_id for it in items] == _EXPECTED_STEPS
        assert all(it.step_id.startswith(f"S{it.group_index}.") for it in items)
        assert all(it.role_label for it in items)
        assert {it.gate for it in items} <= {"prog", "manual", "attest"}

    def test_title_and_summary_come_from_the_bold_lead(self):
        s41 = {it.step_id: it for it in _reference_items()}["S4.1"]
        assert s41.title == "Identify the Workday app and configure SAML"
        assert s41.summary.startswith("Use the existing Workday enterprise application")
        assert s41.group_title == "Microsoft Entra"

    def test_phases_follow_the_connect_workday_lifecycle(self):
        items = _reference_items()
        foundation = [it for it in items if it.group_index in setup_tasks.FOUNDATION_GROUPS]
        assert foundation and not any(it.phase for it in foundation)

        lifecycle = [d.identifier.value for d in PHASE_DEFINITIONS]
        phased = [it.phase for it in items if it not in foundation]
        # Every lifecycle phase appears, each one contiguous and in lifecycle order.
        assert list(dict.fromkeys(phased)) == lifecycle
        assert phased == sorted(phased, key=lifecycle.index)

    def test_relative_links_resolve(self):
        path = checklist_path("workday")
        targets = re.findall(r"\]\(([^)#\s]+)", path.read_text(encoding="utf-8"))
        local = [t for t in targets if not t.startswith(("http://", "https://"))]
        assert local
        for target in local:
            assert (path.parent / target).resolve().is_file(), target


class TestRoleGrounding:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Application Administrator or Cloud Application Administrator", "Entra app administrator"),
            (
                "Application Administrator or Cloud Application Administrator "
                "(a separate consent-capable administrator only if tenant policy blocks consent)",
                "Entra app administrator",
            ),
            ("App/Cloud App Admin", "Entra app administrator"),
            ("Environment Maker (+ package installation access)", "Environment Maker"),
            (
                "Environment Maker (+ Dataverse System Administrator access for runtime authorization)",
                "Environment Maker",
            ),
            ("Power Platform Administrator", "Power Platform Administrator"),
            ("Workday Administrator", "Workday Administrator"),
            ("Records Manager (+ legal)", "Records Manager"),
            ("Records Manager or Auditor", "Records Manager"),
        ],
    )
    def test_canonical_role(self, raw, expected):
        assert canonical_role(raw) == expected

    def test_every_reference_role_maps_to_its_least_privileged_attestable_role(self):
        mapped: dict[str, str] = {}
        for item in _reference_items():
            grounded = ground_role(item.role_label)
            assert grounded.mapped is True, item.role_label
            mapped[grounded.grounded_id] = grounded.attestable_role
        # The Entra work is Cloud Application Administrator, never Global Administrator.
        assert mapped == {
            "power-platform-administrator": "EntraPowerPlatformAdministrator",
            "environment-maker": "PowerPlatformEnvironmentMaker",
            "entra-app-administrator": "EntraCloudApplicationAdministrator",
            "workday-administrator": "WorkdayAdmin",
        }


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
    def test_tasks_split_on_role_boundaries(self):
        tasks = system_setup_tasks("workday")
        actual = {
            t.task_id: _Expected(t.role, t.step_ids, t.phases, t.produces, t.consumes, t.command)
            for t in tasks
        }
        assert list(actual) == list(_WORKDAY_TASKS)
        assert actual == _WORKDAY_TASKS
        for task in tasks:
            assert task.attestable is True
            assert task.stream == "Workday"

    def test_ledger_honours_each_phase_prerequisite(self):
        tasks = system_setup_tasks("workday")
        producer = {key: t.task_id for t in tasks for key in t.produces}
        position = {t.task_id: i for i, t in enumerate(tasks)}
        # Every consumed key comes from an earlier task, so plan order is a valid
        # dependency order.
        for task in tasks:
            for key in task.consumes:
                assert key in producer, (task.task_id, key)
                assert position[producer[key]] < position[task.task_id], (task.task_id, key)

        parents = {t.task_id: {producer[k] for k in t.consumes} for t in tasks}

        def ancestors(task_id: str) -> set[str]:
            found: set[str] = set()
            stack = list(parents[task_id])
            while stack:
                current = stack.pop()
                if current not in found:
                    found.add(current)
                    stack.extend(parents[current])
            return found

        owner = {phase: t.task_id for t in tasks for phase in t.phases}
        for definition in PHASE_DEFINITIONS:
            if definition.prerequisite is None:
                continue
            task_id = owner[definition.identifier.value]
            before = owner[definition.prerequisite.value]
            assert before == task_id or before in ancestors(task_id), definition.identifier.value

    def test_skip_foundation_keeps_the_connect_workday_tasks(self):
        tasks = system_setup_tasks("workday", skip_foundation=True)
        assert [t.task_id for t in tasks] == list(_WORKDAY_TASKS)[2:]

    def test_commands_name_real_kit_prompts(self):
        for task in system_setup_tasks("workday"):
            if task.command is not None:
                name = task.command.lstrip("/")
                assert (_SOLUTION_ROOT / ".github" / "prompts" / f"{name}.prompt.md").is_file()


class TestDescriptions:
    def test_grounding_names_the_steps_and_phases(self):
        by_id = _workday_tasks()
        assert (
            "Grounded in planner/systems/workday.md group 1 (Power Platform environment) "
            "steps S1.1-S1.2. Reference role: Power Platform Administrator;"
        ) in by_id["workday-pp-environment"].description
        assert "steps S3.1; /connect-workday phase: preflight." in by_id["workday-preflight"].description
        assert (
            "steps S6.1-S6.3; /connect-workday phases: connections, runtime, maker-validation."
        ) in by_id["workday-connect"].description

    def test_role_nuance_survives_grounding(self):
        by_id = _workday_tasks()
        assert (
            "Reference role: Entra app administrator (involve a separate consent-capable "
            "administrator only if tenant policy prevents admin consent); "
            "attestable role: Cloud Application Administrator."
        ) in by_id["workday-entra-app"].description
        assert (
            "(with package installation access; with Dataverse System Administrator "
            "access for runtime authorization)"
        ) in by_id["workday-connect"].description
        for task in by_id.values():
            assert "Global Administrator" not in task.description


class TestCommandRendering:
    def test_add_task_lines_parse_with_the_planner_cli(self):
        parser = build_parser()
        for task in system_setup_tasks("workday"):
            # Double-quoted values must stay literal in both bash and PowerShell.
            for value in (task.title, task.description, task.stream):
                assert not set(value) & set('"`$!\\'), task.task_id
            argv = shlex.split(task.add_task_command())
            assert argv[:2] == ["python", "scripts/planner/cli.py"]
            assert (_SOLUTION_ROOT / argv[1]).is_file()
            args = parser.parse_args(argv[2:])
            assert args.command == "add-task"
            assert (args.id, args.title, args.description, args.role, args.stream) == (
                task.task_id, task.title, task.description, task.role, task.stream,
            )
            assert args.produces == (",".join(task.produces) or None)
            assert args.consumes == (",".join(task.consumes) or None)


# A system with no annotation ledger; S1.1 keeps the legacy "- [ ]" checkbox.
_UNANNOTATED = """### 1. Discovery

- [ ] **Inventory the tenant** — Export the current configuration.
  <!-- id: S1.1 | role: Some Future Role | gate: manual -->
- **Review the export** — Check the export for gaps.
  <!-- id: S1.2 | role: Environment Maker | phase: build | gate: prog -->
"""


class TestUnannotatedSystem:
    def test_partitions_fall_back_to_the_reference_text(self):
        tasks = decompose("acme", parse_setup_checklist(_UNANNOTATED))
        assert [t.task_id for t in tasks] == ["acme-g1-some-future-role", "acme-g1-environment-maker"]
        first, second = tasks

        # The group's first role takes the heading as its title and, with no
        # attestable role, asks for a person instead of claiming one.
        assert (first.title, first.role, first.attestable) == ("Discovery", "some-future-role", False)
        assert first.description == (
            "Export the current configuration. Grounded in planner/systems/acme.md "
            "group 1 (Discovery) steps S1.1. Reference role: Some Future Role; "
            "attestable role: Some Future Role. No attestable role fits — assign a "
            "person directly."
        )
        assert (first.produces, first.consumes, first.command, first.stream) == ([], [], None, "Acme")

        # A second role in the same group takes its own first step's title.
        assert (second.title, second.role, second.attestable) == (
            "Review the export", "PowerPlatformEnvironmentMaker", True,
        )
        assert "steps S1.2; Phase: build." in second.description

    def test_system_without_a_reference_raises(self):
        with pytest.raises(FileNotFoundError, match="no planning reference"):
            system_setup_tasks("servicenow")
