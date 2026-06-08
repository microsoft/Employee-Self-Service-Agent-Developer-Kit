# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for ``_check_agent_identity`` in
``flightcheck.checks.local_files``.

Pins the YAML-aware parsing behavior. The previous implementation used
a regex (``instructions:\\s*[|>]?\\s*\\n…``) which silently missed
YAML's chomping-indicator block scalars (``|-``, ``|+``, ``>-``,
``>+``). Real Copilot Studio agent.mcs.yml files routinely emit
``instructions: |-``, so the check reported "No instructions block
found in agent.mcs.yml" for agents that obviously had instructions.

These tests pin the new behavior and the specific regression.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Make `flightcheck.*` importable from the kit's scripts dir."""
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "solutions" / "ess-maker-skills" / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


# Minimal block-scalar instructions text built to exceed the 50-word
# PASS threshold. Single source of truth so every test uses the same
# wording — only the YAML scalar STYLE varies between tests.
_INSTRUCTION_BODY = (
    "  You are an employee experience agent that helps enterprise employees "
    "with HR questions. Your role is to provide clear, authoritative, "
    "policy-based guidance, clarify next steps, and escalate to HR support "
    "channels when needed. Be empathetic, professional, nonjudgmental, "
    "supportive, and reassuring across every interaction with a worker. "
    "Always cite sources from the employee handbook, prefer concrete "
    "actionable next steps, and gracefully hand off to a human reviewer "
    "whenever the question goes beyond your authority."
)


def _runner():
    return SimpleNamespace(env_id="env-guid", config={})


def _write_agent(tmp_path, body: str) -> Path:
    agent_path = tmp_path / "agentfolder"
    agent_path.mkdir()
    (agent_path / "agent.mcs.yml").write_text(body, encoding="utf-8")
    return agent_path


def _get_check(results, checkpoint_id):
    hits = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert hits, f"no result with checkpoint_id={checkpoint_id!r}"
    assert len(hits) == 1, f"expected exactly one {checkpoint_id} result"
    return hits[0]


# ─────────────────────────────────────────────────────────────────────
# CONFIG-007 — instructions
# ─────────────────────────────────────────────────────────────────────


def test_config_007_passes_when_instructions_use_strip_chomping_block_scalar(tmp_path):
    """Regression: `instructions: |-` (strip-chomping) is what the
    user's real Copilot Studio agent emits. The old regex required
    `[|>]?` then `\\n` immediately, so `|-` failed to match and
    CONFIG-007 wrongly reported "No instructions block found in
    agent.mcs.yml" despite the agent obviously having instructions.
    """
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = (
        "kind: GptComponentMetadata\n"
        "displayName: ESS_HR_WDAY_ONLY_OAUTH\n"
        "instructions: |-\n"
        f"{_INSTRUCTION_BODY}\n"
    )
    agent_path = _write_agent(tmp_path, yaml_text)

    results = _check_agent_identity(agent_path, "ESS Agent", runner=_runner(), agent_name="esshrwdayonlyoauth")
    instructions = _get_check(results, "CONFIG-007")
    assert instructions.status == "Passed", instructions.result
    assert "Instructions present" in instructions.result


def test_config_007_passes_with_plain_block_scalar(tmp_path):
    """Sanity: plain `|` (clip-chomping, the YAML default) still works."""
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = (
        "displayName: Some Agent\n"
        "instructions: |\n"
        f"{_INSTRUCTION_BODY}\n"
    )
    agent_path = _write_agent(tmp_path, yaml_text)

    results = _check_agent_identity(agent_path, "Some Agent", runner=_runner(), agent_name="some-agent")
    assert _get_check(results, "CONFIG-007").status == "Passed"


def test_config_007_passes_with_keep_chomping_block_scalar(tmp_path):
    """Sanity: `|+` (keep-chomping) — same chomping-indicator failure
    mode as `|-`, just keeping trailing newlines instead of stripping."""
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = (
        "displayName: Some Agent\n"
        "instructions: |+\n"
        f"{_INSTRUCTION_BODY}\n"
    )
    agent_path = _write_agent(tmp_path, yaml_text)

    results = _check_agent_identity(agent_path, "Some Agent", runner=_runner(), agent_name="some-agent")
    assert _get_check(results, "CONFIG-007").status == "Passed"


def test_config_007_passes_with_folded_block_scalar(tmp_path):
    """Sanity: `>-` (folded with strip-chomping) — would also miss
    the old regex for the same reason."""
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = (
        "displayName: Some Agent\n"
        "instructions: >-\n"
        f"{_INSTRUCTION_BODY}\n"
    )
    agent_path = _write_agent(tmp_path, yaml_text)

    results = _check_agent_identity(agent_path, "Some Agent", runner=_runner(), agent_name="some-agent")
    assert _get_check(results, "CONFIG-007").status == "Passed"


def test_config_007_passes_with_quoted_inline_string(tmp_path):
    """Sanity: a single-line quoted string instead of a block scalar
    must also be honored."""
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = (
        "displayName: Some Agent\n"
        f'instructions: "{_INSTRUCTION_BODY.strip()}"\n'
    )
    agent_path = _write_agent(tmp_path, yaml_text)

    results = _check_agent_identity(agent_path, "Some Agent", runner=_runner(), agent_name="some-agent")
    assert _get_check(results, "CONFIG-007").status == "Passed"


def test_config_007_warns_when_instructions_are_short(tmp_path):
    """Below 50 words is a WARNING, not a FAIL."""
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = (
        "displayName: Some Agent\n"
        "instructions: |-\n"
        "  Short instructions for tests.\n"
    )
    agent_path = _write_agent(tmp_path, yaml_text)

    instructions = _get_check(
        _check_agent_identity(agent_path, "Some Agent", runner=_runner(), agent_name="some-agent"),
        "CONFIG-007",
    )
    assert instructions.status == "Warning"
    assert "short" in instructions.result.lower()


def test_config_007_fails_when_instructions_key_missing(tmp_path):
    """The key truly is absent."""
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = "displayName: Some Agent\n"
    agent_path = _write_agent(tmp_path, yaml_text)

    instructions = _get_check(
        _check_agent_identity(agent_path, "Some Agent", runner=_runner(), agent_name="some-agent"),
        "CONFIG-007",
    )
    assert instructions.status == "Failed"
    assert "No instructions" in instructions.result


def test_config_007_fails_when_yaml_is_unparseable(tmp_path):
    """Surface a clear error rather than silently treating it as
    'no instructions' (which would confuse the user)."""
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = "displayName: [unterminated\n"
    agent_path = _write_agent(tmp_path, yaml_text)

    instructions = _get_check(
        _check_agent_identity(agent_path, "Some Agent", runner=_runner(), agent_name="some-agent"),
        "CONFIG-007",
    )
    assert instructions.status == "Failed"
    assert "could not be parsed" in instructions.result.lower()


# ─────────────────────────────────────────────────────────────────────
# CONFIG-005 — starter prompts (parsed from the same YAML)
# ─────────────────────────────────────────────────────────────────────


def test_config_005_passes_when_six_starter_prompts_present(tmp_path):
    """The user's real file: 6 prompts, each with title+text. The old
    regex counted `-\\s+text:` occurrences and could over- or
    under-count depending on indentation; YAML parsing is deterministic."""
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = (
        "displayName: Some Agent\n"
        "instructions: |-\n"
        f"{_INSTRUCTION_BODY}\n"
        "conversationStarters:\n"
        "  - title: Navigate benefits\n"
        "    text: Help me learn more about benefits and resources\n"
        "  - title: Check policies\n"
        "    text: What are my options for taking time off work?\n"
        "  - title: Discover resources\n"
        "    text: Tell me more about hybrid and remote work policies\n"
        "  - title: Grow skills\n"
        "    text: Where can I find training and learning opportunities?\n"
        "  - title: Find balance\n"
        "    text: How do I learn more about physical and mental wellbeing?\n"
        "  - title: Ask questions\n"
        "    text: Where is my most recent paystub?\n"
    )
    agent_path = _write_agent(tmp_path, yaml_text)

    starters = _get_check(
        _check_agent_identity(agent_path, "Some Agent", runner=_runner(), agent_name="some-agent"),
        "CONFIG-005",
    )
    assert starters.status == "Passed"
    assert "6 starter prompt" in starters.result


def test_config_005_warns_when_only_one_starter_prompt(tmp_path):
    """1 < 3 is a WARNING (not FAIL): some prompts but recommend more."""
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = (
        "displayName: Some Agent\n"
        "instructions: |-\n"
        f"{_INSTRUCTION_BODY}\n"
        "conversationStarters:\n"
        "  - title: Ask questions\n"
        "    text: Where is my most recent paystub?\n"
    )
    agent_path = _write_agent(tmp_path, yaml_text)

    starters = _get_check(
        _check_agent_identity(agent_path, "Some Agent", runner=_runner(), agent_name="some-agent"),
        "CONFIG-005",
    )
    assert starters.status == "Warning"
    assert "Only 1" in starters.result


def test_config_005_warns_when_no_starter_prompts(tmp_path):
    from flightcheck.checks.local_files import _check_agent_identity

    yaml_text = (
        "displayName: Some Agent\n"
        "instructions: |-\n"
        f"{_INSTRUCTION_BODY}\n"
    )
    agent_path = _write_agent(tmp_path, yaml_text)

    starters = _get_check(
        _check_agent_identity(agent_path, "Some Agent", runner=_runner(), agent_name="some-agent"),
        "CONFIG-005",
    )
    assert starters.status == "Warning"
    assert "No starter prompts" in starters.result
