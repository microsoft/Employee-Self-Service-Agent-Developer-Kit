# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import json
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_ROOT = _ROOT / "solutions" / "ess-maker-skills" / "src" / "skills"
_PROMPTS_ROOT = _ROOT / "solutions" / "ess-maker-skills" / ".github" / "prompts"
_MANIFEST = Path(__file__).with_name("user_profile_adoption_manifest.json")
_PROFILE_HOOKS = (
    "## User profile entry",
    "## User profile (resolve-only)",
    "## Maker communication profile",
)


def _manifest() -> dict[str, list[dict[str, object]]]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _paths(entries: list[dict[str, object]]) -> list[str]:
    return [str(entry["path"]) for entry in entries]


def _check_entries(entries: list[dict[str, object]]) -> None:
    paths = _paths(entries)
    assert len(paths) == len(set(paths)), "manifest paths must be unique"

    for entry in entries:
        path = _ROOT / str(entry["path"])
        assert path.is_file(), f"manifest path is missing: {entry['path']}"
        content = path.read_text(encoding="utf-8")
        anchor = entry["entry_anchor"]
        if anchor:
            assert str(anchor) in content, (
                f"entry anchor missing from {entry['path']}: {anchor}"
            )
        for protected_anchor in entry["protected_anchors"]:
            assert protected_anchor in content, (
                f"protected anchor missing from {entry['path']}: {protected_anchor}"
            )


def test_manifest_covers_every_prompt_and_skill_without_drift() -> None:
    manifest = _manifest()
    prompt_paths = _paths(manifest["prompts"])
    skill_paths = _paths(manifest["skills"])

    discovered_prompts = {
        path.relative_to(_ROOT).as_posix()
        for path in _PROMPTS_ROOT.glob("*.prompt.md")
    }
    discovered_skills = {
        path.relative_to(_ROOT).as_posix()
        for path in _SKILLS_ROOT.rglob("SKILL.md")
    }

    assert set(prompt_paths) == discovered_prompts
    assert len(prompt_paths) == 20
    assert set(skill_paths) == discovered_skills
    assert len(skill_paths) == 32
    _check_entries(manifest["prompts"])
    _check_entries(manifest["skills"])


def test_entry_ownership_is_explicit_and_exclusions_stay_excluded() -> None:
    manifest = _manifest()
    prompts = manifest["prompts"]
    owners = [str(row["path"]) for row in prompts if row["entry_owner"]]

    assert len(owners) == len(set(owners))
    assert {Path(path).name for path in owners} == {
        "flightcheck.prompt.md",
        "connect.prompt.md",
        "setup.prompt.md",
    }
    assert all(
        row["mode"] in {"excluded", "alias"} or row["entry_anchor"]
        for row in prompts
    )

    for row in prompts:
        if row["mode"] == "excluded":
            content = (_ROOT / str(row["path"])).read_text(encoding="utf-8")
            assert not any(hook in content for hook in _PROFILE_HOOKS)
            assert row["entry_owner"] is False

    for row in manifest["skills"]:
        if row["mode"] == "excluded":
            content = (_ROOT / str(row["path"])).read_text(encoding="utf-8")
            assert "## Maker communication profile" not in content

    connect_workday = next(
        row for row in prompts if row["path"].endswith("connect-workday.prompt.md")
    )
    assert connect_workday["owner"] == "connect.prompt.md"
    assert connect_workday["entry_owner"] is False


def test_nested_helpers_inherit_without_owning_entry() -> None:
    helpers = _manifest()["helpers"]
    assert _paths(helpers) == [
        "solutions/ess-maker-skills/src/skills/connect/shared/lifecycle-runner.md"
    ]
    assert {row["mode"] for row in helpers} == {"inherit_only"}
    _check_entries(helpers)


def test_only_flightcheck_connect_and_setup_have_profile_integration() -> None:
    manifest = _manifest()
    eligible_skills = {
        "connect/SKILL.md",
        "connect/workday/SKILL.md",
        "flightcheck/SKILL.md",
        "foundation-setup/SKILL.md",
        "setup/workday-da/SKILL.md",
    }
    actual_eligible = {
        (_ROOT / str(row["path"])).relative_to(_SKILLS_ROOT).as_posix()
        for row in manifest["skills"]
        if "eligible" in str(row["mode"])
    }
    assert actual_eligible == eligible_skills

    for row in manifest["prompts"] + manifest["skills"]:
        mode = str(row["mode"])
        if mode in {"excluded", "management", "alias"}:
            continue
        content = (_ROOT / str(row["path"])).read_text(encoding="utf-8")
        anchor = str(row["entry_anchor"])
        section = " ".join(
            (anchor + content.split(anchor, 1)[1].split("\n## ", 1)[0]).split()
        )
        assert "eligible" in mode
        assert "eligible" in section
        assert "onboarding" in section
        assert "src/skills/shared/user-profile-entry.md" in section


def test_excluded_skills_and_prompts_have_no_profile_hooks_or_inheritance() -> None:
    participating_roots = (
        _SKILLS_ROOT / "connect",
        _SKILLS_ROOT / "flightcheck",
        _SKILLS_ROOT / "foundation-setup",
        _SKILLS_ROOT / "setup" / "workday-da",
        _SKILLS_ROOT / "shared",
        _SKILLS_ROOT / "user-profile",
    )
    excluded_paths = {
        path
        for path in _SKILLS_ROOT.rglob("*.md")
        if not any(path.is_relative_to(root) for root in participating_roots)
    }
    excluded_paths.update(
        _ROOT / str(row["path"])
        for row in _manifest()["prompts"]
        if row["mode"] == "excluded"
    )
    for path in sorted(excluded_paths):
        content = path.read_text(encoding="utf-8").lower()
        for reference in ("user-profile", "user_profile", "communication profile"):
            assert reference not in content, f"{path} retains profile integration"


def test_eligible_entries_preserve_admission_and_same_request_continuation() -> None:
    entry = (_SKILLS_ROOT / "shared" / "user-profile-entry.md").read_text(
        encoding="utf-8"
    )
    assert "Only FlightCheck, Connect" in entry
    assert "and foundation Setup may own eligible entries" in entry
    assert "All other skills are excluded from profile handling" in entry
    assert "Do not pass profile context to excluded" in entry
    assert "including a FlightCheck or Connect called during Setup" in entry
    assert "src/skills/user-profile/onboarding.md" in entry
    assert "never starts a second eligible entry" in entry

    setup = (_SKILLS_ROOT / "foundation-setup" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Setup completion is not an admission requirement" in setup
    assert "Use the resolved launcher" in setup
    assert "Runtime failures, declined command approvals" in setup
    assert "onboarding is not an extra setup stage" in setup

    connect = (_SKILLS_ROOT / "connect" / "SKILL.md").read_text(encoding="utf-8")
    assert "Wait for the selected lifecycle's admission evidence" in connect
    assert "unsupported integrations, unavailable packages" in connect
    assert "resume the same connection request" in connect

    flightcheck = (_SKILLS_ROOT / "flightcheck" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "entry gate and required scope/target selections pass" in flightcheck
    assert "resume the same check" in flightcheck


def test_flightcheck_defines_independent_effects_for_all_six_preferences() -> None:
    content = (_SKILLS_ROOT / "flightcheck" / "SKILL.md").read_text(encoding="utf-8")
    skill = " ".join(content.split())
    rows = {
        line.split("|", 2)[1].strip(" `"): " ".join(line.split())
        for line in content.splitlines()
        if line.startswith("| `")
    }
    expected_effects = {
        "responseFormat": (
            "`auto`: compact counts",
            "`prose`: counts in a sentence",
            "`bullets`: flat labeled bullets",
            "`steps`: compact counts followed by numbered",
            "`table_first`: counts table followed by a findings table",
        ),
        "detailLevel": (
            "`concise`: all non-passing findings, passing count only",
            "`balanced`: the same non-passing findings, passing counts grouped by category",
            "`detailed`: every check, including each passing check",
        ),
        "toneOfVoice": (
            "`direct`: short, action-oriented",
            "`friendly_professional`: collaborative",
            "`formal`: reserved, precise",
            "`empathetic`: acknowledge the observed blocker",
        ),
        "confirmationFrequency": (
            "`minimal`: no optional check-ins",
            "`standard`: clarify only material ambiguity",
            "`frequent`: may add at most one scope/target recap",
        ),
        "maximumResponseLength": (
            "A soft word budget for the chat response",
            "Exceed the budget when protected content does not fit",
        ),
        "proactiveSuggestions": (
            "`off`: no optional tip",
            "`contextual`: at most one evidence-supported improvement",
            "`on`: at most one evidence-supported adjacent next step",
        ),
    }
    for preference, effects in expected_effects.items():
        for effect in effects:
            assert effect in rows[preference]
    assert "concise does not imply a word cap" in skill
    assert "a request for all results always includes every check" in skill.lower()


def test_flightcheck_adaptation_preserves_evidence_consent_and_full_report() -> None:
    skill = " ".join(
        (_SKILLS_ROOT / "flightcheck" / "SKILL.md").read_text(
            encoding="utf-8"
        ).split()
    )
    assert (
        "Always show every non-passing result individually: Failed, Blocked, Error, "
        "Warning, Manual, NotConfigured, and Skipped."
        in skill
    )
    for invariant in (
        "HTML report never change because of communication preferences",
        "complete `remediation`, `doc_link`, and next-step `roles`",
        "Never imply a skipped or manual check passed",
        "Do not reread the profile during rendering or rechecks",
        "Never ask an extra question solely to report results",
        "Keep the fix-selection table and consent question below contractual",
        "If WD-RUN-001 is NotConfigured, follow Step 3d before choosing a terminal",
        "Do not append it after a terminal message",
        "Do NOT write or run any code to render these results",
    ):
        assert invariant in skill
    assert "Want me to fix the auto-fixable issues listed above?" in skill
    assert "Show ALL results from the JSON" not in skill


def test_flightcheck_prompt_and_central_rules_allow_adaptive_chat() -> None:
    prompt = (_PROMPTS_ROOT / "flightcheck.prompt.md").read_text(encoding="utf-8")
    central = (_PROMPTS_ROOT.parent / "copilot-instructions.md").read_text(
        encoding="utf-8"
    )
    assert "using the adaptive chat contract in Step 3" in prompt
    assert "using the exact table format" not in prompt
    assert "The full HTML report always retains every check" in " ".join(prompt.split())
    assert "using the skill's adaptive chat contract" in central
    assert "all non-passing evidence" in " ".join(central.split())


def test_runtime_profile_instructions_do_not_depend_on_test_metadata() -> None:
    runtime_paths = {
        _ROOT / str(entry["path"])
        for entries in _manifest().values()
        for entry in entries
    }
    runtime_paths.update((_SKILLS_ROOT / "shared").glob("*.md"))
    runtime_paths.add(_PROMPTS_ROOT.parent / "copilot-instructions.md")

    for path in sorted(runtime_paths):
        content = path.read_text(encoding="utf-8")
        assert "user_profile_adoption_manifest.json" not in content, (
            f"{path} sends runtime requests outside the Maker Kit workspace"
        )
        assert "skill's manifest mode" not in content, (
            f"{path} must declare its runtime profile mode locally"
        )


def test_shared_entry_contract_preserves_single_owner_and_frozen_context() -> None:
    entry = (_SKILLS_ROOT / "shared" / "user-profile-entry.md").read_text(
        encoding="utf-8"
    )
    contract = (_SKILLS_ROOT / "shared" / "user-profile-contract.md").read_text(
        encoding="utf-8"
    )

    assert (
        "Participating nested skills inherit context and never become a second owner."
        in entry
    )
    assert "Call `experience begin` once" in entry
    assert "same immutable execution snapshot" in entry
    assert "nested skill reread or replace it" in entry
    assert "Exact Message blocks and required output contracts" in contract
    assert "terminal exact message" in contract
    assert "where another contract prohibits extra text" in contract
