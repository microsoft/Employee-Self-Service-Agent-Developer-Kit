# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the per-check `roles` field (next-step owner).

Pure-logic tests — no network, no cassettes. They pin:
  * The `Role` enum membership.
  * `CheckResult.roles` defaults to an empty list.
  * The HTML report renders a "Role" column (header + cell).
  * `save_results` persists `roles` into results.json.
  * The terminal summary surfaces the role(s) on action/manual rows.
  * A representative production check module (publishing) sets roles on
    every result it emits.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    scripts_dir = (
        Path(__file__).resolve().parents[1]
        / "solutions" / "ess-maker-skills" / "scripts"
    )
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


def _result(checkpoint_id, status, roles, priority="High"):
    from flightcheck.runner import CheckResult
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category="Test",
        priority=priority,
        status=status,
        description=f"desc {checkpoint_id}",
        result=f"result {checkpoint_id}",
        remediation="fix it" if status != "Passed" else "",
        roles=roles,
    )


def test_role_enum_has_expected_members():
    from flightcheck.runner import Role
    assert {r.value for r in Role} == {
        "Entra Admin",
        "Microsoft 365 Admin",
        "Power Platform Admin",
        "Workday Admin",
        "ServiceNow Admin",
        "SAP Admin",
        "ESS Maker / Agent Developer",
    }


def test_checkresult_roles_defaults_to_empty_list():
    from flightcheck.runner import CheckResult
    r = CheckResult(
        checkpoint_id="X-001", category="Test", priority="High",
        status="Passed", description="d", result="r",
    )
    assert r.roles == []


def test_html_rows_render_role_column():
    from flightcheck.runner import Role, _render_rows
    rows = _render_rows([
        _result("X-001", "Failed",
                [Role.ENTRA_ADMIN.value, Role.WORKDAY_ADMIN.value]),
    ])
    assert "Entra Admin, Workday Admin" in rows


def test_html_rows_render_dash_when_no_roles():
    from flightcheck.runner import _render_rows
    rows = _render_rows([_result("X-002", "Passed", [])])
    assert "—" in rows


def test_html_rows_blank_role_for_passed_even_if_populated():
    """Passed/Skipped rows have no next step — Role cell is blank even
    if the constructor populated roles (e.g. a conditional-status check
    that happened to pass)."""
    from flightcheck.runner import Role, _render_rows
    passed = _render_rows([_result("X-005", "Passed", [Role.WORKDAY_ADMIN.value])])
    assert "Workday Admin" not in passed
    skipped = _render_rows([_result("X-006", "Skipped", [Role.WORKDAY_ADMIN.value])])
    assert "Workday Admin" not in skipped


def test_html_rows_show_role_for_actionable_statuses():
    from flightcheck.runner import Role, _render_rows
    for status in ("Failed", "Warning", "Manual", "NotConfigured", "Error"):
        rows = _render_rows([_result("X-007", status, [Role.ENTRA_ADMIN.value])])
        assert "Entra Admin" in rows, f"role missing for {status}"


def test_html_section_header_includes_role_column():
    from flightcheck.runner import _render_section
    section = _render_section(
        section_id="s", title="t", subtitle="sub", empty_text="none",
        rows_html="<tr></tr>", count=1, open_by_default=True,
    )
    assert "<th>Role</th>" in section
    # Role column sits between Status and Result.
    assert section.index("<th>Status</th>") < section.index("<th>Role</th>")
    assert section.index("<th>Role</th>") < section.index("<th>Result</th>")


def test_results_json_persists_roles(tmp_path):
    from flightcheck.runner import RunResult, Role, save_results
    rr = RunResult(scope="full", started="2026-01-01T00-00-00")
    rr.results = [_result("X-003", "Failed", [Role.POWER_PLATFORM_ADMIN.value])]
    rr.total = 1
    rr.failed = 1
    save_results(rr, output_dir=str(tmp_path))
    data = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert data["results"][0]["roles"] == ["Power Platform Admin"]


def test_terminal_summary_shows_roles_on_action_rows(capsys):
    from flightcheck.runner import RunResult, Role
    from flightcheck.cli import _print_prioritized_summary
    rr = RunResult(scope="full", started="2026-01-01T00-00-00", overall="NOT_READY")
    rr.results = [_result("X-004", "Failed", [Role.WORKDAY_ADMIN.value])]
    rr.total = 1
    rr.failed = 1
    _print_prioritized_summary(rr)
    out = capsys.readouterr().out
    assert "Workday Admin" in out
    assert "X-004" in out


def test_publishing_checks_all_carry_roles():
    """Every result from a real check module must declare at least one role."""
    from flightcheck.checks.publishing import run_publishing_checks

    class _Runner:
        env_id = None
        config = {}

    results = run_publishing_checks(_Runner())
    assert results
    for r in results:
        assert r.roles, f"{r.checkpoint_id} has no roles"
