# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural guards for the hybrid Workday setup boundary."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_BOUNDARY = _SOLUTION / "src" / "skills" / "setup" / "SKILL.md"
_CONNECT_STEP1 = _SOLUTION / "src" / "skills" / "connect" / "step1.md"
_CONNECT_SKILL = _SOLUTION / "src" / "skills" / "connect" / "SKILL.md"
_OLD_PROMPT = _SOLUTION / ".github" / "prompts" / "setup-workday.prompt.md"
_MONOLITH_DIR = _SOLUTION / "src" / "skills" / "connect" / "workday"
_WORKDAY_PLAYBOOKS = (
    "provision-power-platform-environment.md",
    "install-ess.md",
    "provision-workday-entra-app.md",
    "configure-workday-tenant.md",
    "install-workday-extension-pack.md",
    "install-workday-ootb-topics.md",
    "create-new-topic.md",
)


def test_connect_workday_routes_to_hybrid_boundary() -> None:
    step1 = _CONNECT_STEP1.read_text(encoding="utf-8")
    connect = _CONNECT_SKILL.read_text(encoding="utf-8")
    normalized_step1 = " ".join(step1.split())

    assert "src/skills/setup/SKILL.md" in step1
    assert "hybrid-extension availability boundary" in normalized_step1
    assert "connect/workday/step" not in step1
    assert "connect/workday/step" not in connect
    assert "src/skills/connect/servicenow/" in connect


def test_hybrid_boundary_is_non_mutating() -> None:
    text = _BOUNDARY.read_text(encoding="utf-8")

    assert "Hybrid Workday extension setup is not available" in text
    assert "Do not run the retained Workday setup playbooks" in text
    assert "no Dataverse environment, solution, connection" in text
    for playbook in _WORKDAY_PLAYBOOKS:
        assert playbook not in text


def test_retained_workday_playbooks_are_not_publicly_routed() -> None:
    playbook_dir = _SOLUTION / "src" / "skills" / "setup" / "workday"
    boundary = _BOUNDARY.read_text(encoding="utf-8")
    connect = _CONNECT_SKILL.read_text(encoding="utf-8")
    step1 = _CONNECT_STEP1.read_text(encoding="utf-8")

    for playbook in _WORKDAY_PLAYBOOKS:
        assert (playbook_dir / playbook).is_file(), playbook
        assert playbook not in boundary
        assert playbook not in connect
        assert playbook not in step1


def test_retired_workday_entry_points_remain_absent() -> None:
    assert not _OLD_PROMPT.exists()
    assert not _MONOLITH_DIR.exists()
