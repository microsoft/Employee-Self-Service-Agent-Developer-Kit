# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural guards for the DA-GA foundation setup flow."""

from __future__ import annotations

import re
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_FOUNDATION = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "SKILL.md"
)
_DA_EXISTING_DEV = (
    _SOLUTION
    / "src"
    / "skills"
    / "foundation-setup"
    / "da-existing-dev.md"
)
_WORKDAY = _SOLUTION / "src" / "skills" / "setup" / "SKILL.md"
_CONNECT_STEP1 = _SOLUTION / "src" / "skills" / "connect" / "step1.md"
_INSTRUCTIONS = _SOLUTION / ".github" / "copilot-instructions.md"
_SETUP_PROMPT = _SOLUTION / ".github" / "prompts" / "setup.prompt.md"
_PROMPTS = _SOLUTION / ".github" / "prompts"
_MAKER_PROFILE = (
    _REPO_ROOT / "tools" / "ess-maker-profile" / "extension" / "extension.js"
)
_PATH_RE = re.compile(r"`(src/skills/[^`]+?\.md)`")


def test_public_setup_routes_to_da_foundation_module() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    prompt = _SETUP_PROMPT.read_text(encoding="utf-8")

    assert "src/skills/foundation-setup/SKILL.md" in instructions
    assert "src/skills/foundation-setup/SKILL.md" in prompt
    assert "retired Dataverse foundation or onboarding playbooks" in prompt


def test_global_and_command_gates_require_canonical_da_completion() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")

    assert "`schema_version` equal to `1`" in instructions
    assert "`status` equal to `\"complete\"`" in instructions
    assert "connect_ready" not in instructions

    gated_prompts = [
        path
        for path in _PROMPTS.glob("*.prompt.md")
        if "**Setup-state check.**" in path.read_text(encoding="utf-8")
    ]
    assert gated_prompts
    for path in gated_prompts:
        text = path.read_text(encoding="utf-8")
        assert ".local/setup/config.json" in text, path
        assert "schema_version: 1" in text, path
        assert 'status: "complete"' in text, path
        assert ".local/config.json" in text, path


def test_global_gate_preserves_flightcheck_only_mode() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")
    normalized = " ".join(instructions.split())

    assert "typed `/flightcheck`" in normalized
    assert "`flightCheckOnly: true`" in normalized
    assert "This exception applies only to `/flightcheck`" in normalized


def test_maker_profile_requires_canonical_and_workspace_completion() -> None:
    text = _MAKER_PROFILE.read_text(encoding="utf-8")

    assert "canonicalComplete && workspaceComplete" in text
    assert "json.schema_version === 1" in text
    assert "json.status === 'complete'" in text
    assert "json.setup === 'complete'" in text
    assert "'.local/setup/config.json'" in text


def test_workday_routing_remains_separate() -> None:
    step1 = _CONNECT_STEP1.read_text(encoding="utf-8")

    assert "src/skills/setup/SKILL.md" in step1
    assert "src/skills/foundation-setup/SKILL.md" not in step1
    assert _WORKDAY.is_file()


def test_foundation_routes_only_to_existing_dev_da_setup() -> None:
    text = _FOUNDATION.read_text(encoding="utf-8")

    assert set(_PATH_RE.findall(text)) == {
        "src/skills/foundation-setup/da-existing-dev.md"
    }
    assert "scripts/setup_state.py" not in text
    assert "Dataverse foundation or onboarding playbooks" in text
    assert _DA_EXISTING_DEV.is_file()


def test_existing_da_dev_path_never_routes_through_dataverse() -> None:
    text = _DA_EXISTING_DEV.read_text(encoding="utf-8")

    for command in (
        "setup_existing_da.py status",
        "setup_existing_da.py list-environments",
        "setup_existing_da.py list-organizations",
        "setup_existing_da.py list-agents",
        "setup_existing_da.py attach",
    ):
        assert command in text
    assert "Do not run the Dataverse foundation steps" in text
    assert "scripts/setup_state.py" not in text
    assert "scripts/discover.py" not in text
    assert "setupStatus" in text
    assert "`complete`" in text


def test_foundation_router_paths_resolve() -> None:
    referenced = set(_PATH_RE.findall(_FOUNDATION.read_text(encoding="utf-8")))
    missing = [
        path
        for path in sorted(referenced)
        if not (_SOLUTION / path).is_file()
    ]

    assert not missing


def test_non_da_ga_setup_implementation_is_absent() -> None:
    retired_paths = (
        "scripts/setup_state.py",
        "scripts/install_ess_agent.py",
        "scripts/ess_connection_binding.py",
        "scripts/preferred_solution.py",
        "scripts/backup_template_configs.py",
        "scripts/restore_template_configs.py",
        "src/reference/ess-agent-installation/config.json",
        "src/reference/solution-catalog.md",
        "src/skills/onboarding/SKILL.md",
        "src/skills/foundation-setup/install-starters.md",
        "src/skills/backup-template-configs/SKILL.md",
        "src/skills/restore-template-configs/SKILL.md",
    )

    for path in retired_paths:
        assert not (_SOLUTION / path).exists(), path


def test_da_commands_degrade_by_operation() -> None:
    expected_text = {
        "push.prompt.md": "DA-GA agent is not yet available",
        "delete.prompt.md": "DA-GA agent is not yet available",
        "connect.prompt.md": "requires the corresponding product extension",
        "troubleshoot.prompt.md": (
            "requires the corresponding product extension guidance"
        ),
        "backup-template-configs.prompt.md": (
            "retired Dataverse-based agent model"
        ),
        "restore-template-configs.prompt.md": (
            "retired Dataverse-based agent model"
        ),
    }

    for name, text in expected_text.items():
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        assert text in prompt, name
        if not name.startswith(("backup-", "restore-")):
            assert 'transport: "agentbuilder"' in prompt, name


def test_da_local_capabilities_remain_available() -> None:
    for name in ("create.prompt.md", "update.prompt.md"):
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        normalized = " ".join(prompt.split())
        assert "continue with local authoring" in normalized, name
        assert "skip every instruction to push, publish" in normalized, name

    evaluate = (_PROMPTS / "evaluate.prompt.md").read_text(encoding="utf-8")
    normalized_evaluate = " ".join(evaluate.split())
    assert (
        "continue generating or editing evaluation files locally"
        in normalized_evaluate
    )
    assert "skip every instruction to push them" in normalized_evaluate

    test_prompt = (_PROMPTS / "test.prompt.md").read_text(encoding="utf-8")
    normalized_test = " ".join(test_prompt.split())
    assert "retain browser-based topic driving" in normalized_test
    assert "server-side diagnostics are not yet available" in normalized_test
    assert "DA-GA workflow testing is not yet available" in normalized_test

    for name in ("create.prompt.md", "update.prompt.md"):
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        normalized = " ".join(prompt.split())
        assert "Do not offer `/test`" in normalized, name
        assert "unchanged deployed" in normalized, name


def test_flightcheck_preserves_standalone_and_local_only_modes() -> None:
    prompt = (_PROMPTS / "flightcheck.prompt.md").read_text(encoding="utf-8")
    normalized = " ".join(prompt.split())

    assert "flightCheckOnly: true" in normalized
    assert "proceed without canonical setup state" in normalized
    assert "only the local-files FlightCheck scope" in normalized
    assert "scope fixed to `local`" in normalized
