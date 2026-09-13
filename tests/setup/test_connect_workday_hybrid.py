# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLUTION = REPO_ROOT / "solutions" / "ess-maker-skills"
CONNECT_SKILL = SOLUTION / "src" / "skills" / "connect" / "SKILL.md"
CONNECT_STEP1 = SOLUTION / "src" / "skills" / "connect" / "step1.md"
HYBRID_SKILL = (
    SOLUTION / "src" / "skills" / "connect" / "workday-hybrid" / "SKILL.md"
)
HYBRID_SCRIPT = (
    SOLUTION / "scripts" / "enable_workday_hybrid_flow_authorization.py"
)


def test_connect_router_has_isolated_workday_hybrid_route():
    skill = CONNECT_SKILL.read_text(encoding="utf-8")
    step1 = CONNECT_STEP1.read_text(encoding="utf-8")

    assert "workday-hybrid" in skill
    assert "src/skills/connect/workday-hybrid/SKILL.md" in step1
    assert "standard Workday" in step1
    assert "setup orchestrator" in step1
    assert step1.index("exactly \"workday-hybrid\"") < step1.index(
        "exactly \"workday\""
    )


def test_workday_hybrid_route_has_required_files_and_command():
    assert HYBRID_SKILL.is_file()
    assert HYBRID_SCRIPT.is_file()

    skill = HYBRID_SKILL.read_text(encoding="utf-8")
    assert "dataverseEndpoint" in skill
    assert "--bot-id <BOT_ID>" in skill
    assert "--workflow-id <FLOW_ID>" in skill
    assert "--validate-only" in skill
    assert "--yes" in skill
    assert "Never ask the user for an access" in skill
    assert "token" in skill
