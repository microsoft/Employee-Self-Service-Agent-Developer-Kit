# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Unit tests for ``check_instruction_budget`` — the deterministic probe the
``/harden`` skill relies on to decide whether proposed instructions fit.

Why this is probed rather than reasoned about: hardening only ever *adds*
text, and instructions that exceed the ceiling can be silently truncated,
which can drop the guardrail the pass just added. The skill is told the
probe's verdict outranks its own estimate, so these tests lock down the
contract that makes that safe — a sentinel line is always emitted, and the
error paths report ``unknown`` rather than a falsely clean measurement.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import check_instruction_budget as budget

_SKILL_ROOT = Path(budget.__file__).resolve().parent.parent
_SCRIPT = _SKILL_ROOT / "scripts" / "check_instruction_budget.py"
_AGENTS_DIR = _SKILL_ROOT / "workspace" / "agents"

_SENTINEL = "###INSTRUCTION_BUDGET_JSON###"


def _agent_yaml(instructions: str) -> str:
    body = "\n".join("  " + line for line in instructions.splitlines())
    return f"kind: GptComponentMetadata\ninstructions: |-\n{body}\n"


@pytest.fixture
def temp_agent():
    """A throwaway agent with a working and a baseline copy of its instructions.

    Lives under the gitignored workspace/agents/ tree so it leaves no git
    trace; removed on teardown.
    """
    name = f"_pytest_{uuid.uuid4().hex}"
    agent_dir = _AGENTS_DIR / name
    (agent_dir / ".baseline").mkdir(parents=True)

    (agent_dir / "agent.mcs.yml").write_text(
        _agent_yaml("You are an HR agent.\nAnswer only from your sources."),
        encoding="utf-8",
    )
    (agent_dir / ".baseline" / "agent.mcs.yml").write_text(
        _agent_yaml("You are an HR agent."),
        encoding="utf-8",
    )
    try:
        yield name
    finally:
        shutil.rmtree(agent_dir, ignore_errors=True)


def _run(*args) -> tuple[int, dict, str]:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    combined = proc.stdout + proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(_SENTINEL)]
    # Every path must emit exactly one verdict; the skill parses this line and
    # has no fallback if it is missing or duplicated.
    assert len(lines) == 1, f"expected one sentinel line, got {len(lines)}: {combined}"
    return proc.returncode, json.loads(lines[0][len(_SENTINEL):]), combined


# --------------------------------------------------------------------------- #
# verdict thresholds
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "chars, limit, expected",
    [
        (100, 8000, "ok"),
        (7999, 8000, "tight"),      # under the limit but inside the warning band
        (8000, 8000, "tight"),      # exactly at the limit is not over
        (8001, 8000, "over"),
        (7751, 8000, "tight"),      # 249 left -> still inside the band
        (7750, 8000, "ok"),         # 250 left -> the first value outside it
    ],
)
def test_verdict_thresholds(chars, limit, expected):
    assert budget._verdict(chars, limit) == expected


def test_limit_boundary_is_inclusive():
    """Exactly at the limit is not over — an off-by-one here would send the
    skill hunting for text to remove from instructions that already fit."""
    assert budget._verdict(8000, 8000) != "over"


# --------------------------------------------------------------------------- #
# measuring a real agent
# --------------------------------------------------------------------------- #

def test_measures_working_instructions(temp_agent):
    code, result, combined = _run("--agent", temp_agent)
    assert code == 0, combined
    assert result["verdict"] == "ok"
    assert result["source"] == "working"
    assert result["chars"] == len("You are an HR agent.\nAnswer only from your sources.")
    assert result["headroom"] == result["limit"] - result["chars"]


def test_reports_delta_against_baseline(temp_agent):
    """The maker needs to see what a pass *added*, not just the total."""
    _, result, _ = _run("--agent", temp_agent)
    assert result["baseline_chars"] == len("You are an HR agent.")
    assert result["delta"] == result["chars"] - result["baseline_chars"]


def test_candidate_file_is_measured_instead(temp_agent, tmp_path):
    candidate = tmp_path / "candidate.txt"
    candidate.write_text("x" * 12, encoding="utf-8")

    _, result, _ = _run("--agent", temp_agent, "--candidate", str(candidate))
    assert result["source"] == "candidate"
    assert result["chars"] == 12


def test_over_budget_is_reported(temp_agent, tmp_path):
    candidate = tmp_path / "candidate.txt"
    candidate.write_text("x" * 50, encoding="utf-8")

    code, result, combined = _run(
        "--agent", temp_agent, "--candidate", str(candidate), "--limit", "40"
    )
    assert code == 0, combined
    assert result["verdict"] == "over"
    assert result["headroom"] == -10
    assert "OVER BUDGET" in combined


def test_custom_limit_is_honoured(temp_agent):
    """The ceiling is the kit's working assumption, so a maker who knows their
    real one must be able to override it rather than be blocked by ours."""
    _, result, _ = _run("--agent", temp_agent, "--limit", "6000")
    assert result["limit"] == 6000


# --------------------------------------------------------------------------- #
# error paths never produce a falsely clean verdict
# --------------------------------------------------------------------------- #

def test_agent_accepts_slug_or_config_folder_path(temp_agent):
    """`.local/config.json` stores `agent.folder` as `workspace/agents/<slug>`
    and `activeAgent` as a bare slug. Both must resolve, or which one the
    caller reaches for first decides whether the probe works."""
    _, by_slug, _ = _run("--agent", temp_agent)
    _, by_path, _ = _run("--agent", f"workspace/agents/{temp_agent}")

    assert by_slug["chars"] == by_path["chars"]
    assert by_path["verdict"] == "ok"


def test_missing_agent_reports_unknown():
    code, result, _ = _run("--agent", "_pytest_does_not_exist")
    assert code != 0
    assert result["verdict"] == "unknown"
    assert "chars" not in result


def test_missing_instructions_block_reports_unknown(temp_agent):
    (_AGENTS_DIR / temp_agent / "agent.mcs.yml").write_text(
        "kind: GptComponentMetadata\n", encoding="utf-8"
    )
    code, result, _ = _run("--agent", temp_agent)
    assert code != 0
    assert result["verdict"] == "unknown"


def test_empty_instructions_block_reports_unknown(temp_agent):
    """An empty block means the agent was never configured. Reporting it as
    "0 characters, plenty of headroom" would read as a clean pass."""
    (_AGENTS_DIR / temp_agent / "agent.mcs.yml").write_text(
        "kind: GptComponentMetadata\ninstructions:\n", encoding="utf-8"
    )
    code, result, _ = _run("--agent", temp_agent)
    assert code != 0
    assert result["verdict"] == "unknown"


def test_unparseable_yaml_reports_unknown(temp_agent):
    (_AGENTS_DIR / temp_agent / "agent.mcs.yml").write_text(
        "instructions: [unclosed\n", encoding="utf-8"
    )
    code, result, _ = _run("--agent", temp_agent)
    assert code != 0
    assert result["verdict"] == "unknown"


def test_missing_candidate_reports_unknown(temp_agent, tmp_path):
    code, result, _ = _run(
        "--agent", temp_agent, "--candidate", str(tmp_path / "nope.txt")
    )
    assert code != 0
    assert result["verdict"] == "unknown"


def test_missing_baseline_still_measures(temp_agent):
    """A baseline is advisory context. Its absence must not block the measure —
    an agent mid-edit may not have one."""
    (_AGENTS_DIR / temp_agent / ".baseline" / "agent.mcs.yml").unlink()

    code, result, combined = _run("--agent", temp_agent)
    assert code == 0, combined
    assert result["verdict"] == "ok"
    assert result["baseline_chars"] is None
    assert result["delta"] is None


def test_invalid_limit_is_rejected(temp_agent):
    code, result, _ = _run("--agent", temp_agent, "--limit", "0")
    assert code != 0
    assert result["verdict"] == "unknown"


# --------------------------------------------------------------------------- #
# wiring
# --------------------------------------------------------------------------- #

def test_harden_prompt_and_skill_are_present():
    """The prompt delegates to the skill by path; a rename that breaks the
    link is silent at runtime — the maker just gets an unguided response."""
    prompt = _SKILL_ROOT / ".github" / "prompts" / "harden.prompt.md"
    skill = _SKILL_ROOT / "src" / "skills" / "instructions" / "harden" / "SKILL.md"
    rules = (_SKILL_ROOT / "src" / "reference" / "ess-docs" / "hardening"
             / "instruction-rules.md")

    assert prompt.is_file()
    assert skill.is_file()
    assert rules.is_file()

    prompt_text = prompt.read_text(encoding="utf-8")
    assert "src/skills/instructions/harden/SKILL.md" in prompt_text

    skill_text = skill.read_text(encoding="utf-8")
    assert "src/reference/ess-docs/hardening/instruction-rules.md" in skill_text
    assert "scripts/check_instruction_budget.py" in skill_text
    assert "scripts/list_agent_capabilities.py" in skill_text
    assert "emit_capability.py harden" in skill_text
    # The checkpoint rule is safety-critical and previously pointed at the
    # wrong step; a stale cross-reference here is a real defect.
    assert re.search(r"checkpoint\*{0,2} \(Step 9\)", skill_text), \
        "the checkpoint rule must cross-reference the step that actually runs it"


def test_skill_always_routes_to_validation():
    """A real run ended on the diff and never mentioned validation. Reading
    instructions cannot show that the agent's answers improved, so every
    path has to hand off."""
    skill = _SKILL_ROOT / "src" / "skills" / "instructions" / "harden" / "SKILL.md"
    skill_text = skill.read_text(encoding="utf-8")

    assert "Never end the run without Step 10." in skill_text
    assert "`/evaluate`" in skill_text
    assert "`/test`" in skill_text
    # Step 8 previously told the model to "stop" on the no-proposal paths,
    # which is what skipped the handoff.
    step_8 = skill_text.split("## Step 8:")[1].split("## Step 9:")[0]
    assert "go to Step 10" in step_8
    assert "and stop" not in step_8


def test_skill_rechecks_contradictions_in_the_proposal():
    """Step 4 reads the maker's text. Hardening then adds prohibitions to a
    document that already has rules, so the candidate has to be checked too —
    otherwise the skill introduces the defect it exists to find."""
    skill = _SKILL_ROOT / "src" / "skills" / "instructions" / "harden" / "SKILL.md"
    step_6 = (skill.read_text(encoding="utf-8")
              .split("## Step 6:")[1].split("## Step 7:")[0])

    assert "run the Step 4 contradiction pass again" in step_6
    assert "candidate as a whole" in step_6
    # The fix for a collision is to amend the surviving rule, not to layer a
    # stricter one on top and hope it wins.
    assert "amend or remove that rule" in step_6.lower()


def test_skill_states_changes_are_local_until_push():
    """A maker told 'I updated agent.mcs.yml' reasonably concludes the change
    is live, stops watching for the behaviour, and never pushes."""
    skill = _SKILL_ROOT / "src" / "skills" / "instructions" / "harden" / "SKILL.md"
    skill_text = skill.read_text(encoding="utf-8")
    step_9 = skill_text.split("## Step 9:")[1].split("## Step 10:")[0]

    assert "still running the previous" in step_9
    # Step 9 states location only; Step 10 owns the instruction to push, so
    # the maker is not told the same thing twice in adjacent paragraphs.
    assert "Step 10 gives the instruction to push" in step_9

    # /push writes agent.mcs.yml to Copilot Studio without publishing, so the
    # change reaches the draft the test pane answers from. /test drives that
    # pane and captures the reply, which is how an instruction change is
    # checked. Neither reads the local agent.mcs.yml, so the push comes first.
    step_10 = skill_text.split("## Step 10:")[1].split("## References")[0]
    # Markdown wraps at 110 columns, so a phrase can span a newline.
    flat_10 = " ".join(step_10.split())
    assert "does not publish" in flat_10
    assert "drives that test pane" in flat_10
    # A pushed change can be served from a cached definition for minutes; a
    # maker who is not told that reads stale behaviour as a failed fix.
    assert "cached definition" in flat_10
    # It does not write CSVs to workspace/tests/, a path that exists nowhere
    # else in the repo.
    assert "workspace/tests" not in flat_10
    # That explanation is routing logic for the model. A real run leaked it to
    # the maker, who was told what /test is not for instead of a next step.
    assert "Internal — do not say any of this to the maker." in flat_10
    applied = step_10.split("**If changes were applied:**")[1].split("**If the maker declined")[0]
    maker_facing = "\n".join(
        ln for ln in applied.splitlines() if ln.lstrip().startswith(">")
    )
    # /test is what actually exercises the new instructions, so the applied
    # path has to name it rather than leaving the maker without a way to look.
    assert "/test" in maker_facing
    # /push is the only command that makes the change real, and a run dropped
    # it once the routing rule was read as "name one command".
    assert "must** name `/push`" in applied
    assert "`/push`" in maker_facing


def test_skill_reports_the_contradiction_check_result():
    """A silent pass is indistinguishable from a skipped check, so the result
    is stated next to the length rather than left implied."""
    skill = _SKILL_ROOT / "src" / "skills" / "instructions" / "harden" / "SKILL.md"
    step_8 = (skill.read_text(encoding="utf-8")
              .split("## Step 8:")[1].split("## Step 9:")[0])

    assert "state the result of the Step 6 re-check explicitly" in step_8
    assert 'Say this even when the answer is "none"' in step_8


def test_skill_requires_live_progress_tracking():
    """The list was created and then never updated, so the maker could not
    tell whether the run was working or waiting on them."""
    skill = _SKILL_ROOT / "src" / "skills" / "instructions" / "harden" / "SKILL.md"
    skill_text = skill.read_text(encoding="utf-8")

    assert "mark each in-progress as you start it" in skill_text
    assert "Update it as you go rather than at the end" in skill_text


def test_skill_forbids_option_menus_at_intake():
    """A maker offered a menu picks a category, and a category cannot be
    anchored to a change — the run then produces generic hardening."""
    skill = _SKILL_ROOT / "src" / "skills" / "instructions" / "harden" / "SKILL.md"
    step_2 = (skill.read_text(encoding="utf-8")
              .split("## Step 2:")[1].split("## Step 3:")[0])
    flat_2 = " ".join(step_2.split())

    assert "Do not offer numbered options" in flat_2
    # One prose follow-up turns a label into something scopeable often enough
    # to be worth asking for.
    assert "follow up once" in flat_2


def test_skill_does_not_gate_intake_on_concrete_examples():
    """A run asked repeatedly for a verbatim question/answer pair before it
    would look at anything, which reads as a gate on the capability. Step 6
    has branches for a theme and for no reported problem, so the run has
    somewhere to go without an example."""
    skill = _SKILL_ROOT / "src" / "skills" / "instructions" / "harden" / "SKILL.md"
    step_2 = (skill.read_text(encoding="utf-8")
              .split("## Step 2:")[1].split("## Step 3:")[0])
    flat_2 = " ".join(step_2.split())

    assert "Examples are never required" in flat_2
    # The earlier wording stalled the run on a label instead of routing it.
    assert "Do not proceed to Step 3" not in flat_2
    assert "you do not have an answer yet" not in flat_2
