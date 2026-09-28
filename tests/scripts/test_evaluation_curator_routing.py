from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLUTION_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills"


def _read(relative_path: str) -> str:
    return (SOLUTION_ROOT / relative_path).read_text(encoding="utf-8")


def _normalized(relative_path: str) -> str:
    return " ".join(_read(relative_path).split())


def test_dispatcher_routes_local_knowledge_before_topic_matching():
    dispatcher = _read("src/skills/evaluations/dispatcher/SKILL.md")
    normalized = " ".join(dispatcher.split()).lower()

    assert "src/skills/evaluations/curate/SKILL.md" in dispatcher
    assert '"curate from a knowledge source"' in normalized
    assert "even when neither required path was supplied" in normalized
    assert "route immediately" in normalized
    assert "local knowledge source" in normalized
    assert "agent-instructions file" in normalized
    assert dispatcher.index("src/skills/evaluations/curate/SKILL.md") < (
        dispatcher.index("### Matching topic found")
    )
    assert dispatcher.index("src/skills/evaluations/curate/SKILL.md") < (
        dispatcher.index("Which scenario or goal should I create evaluation tests for?")
    )


def test_dispatcher_preserves_topic_and_catalogue_routes():
    dispatcher = _read("src/skills/evaluations/dispatcher/SKILL.md")
    normalized = " ".join(dispatcher.split()).lower()

    assert "src/skills/evaluations/create/SKILL.md" in dispatcher
    assert "src/skills/evaluations/generate/SKILL.md" in dispatcher
    assert "plain named scenario" in normalized
    assert "explicit document grounding" in normalized


def test_evaluate_prompt_offers_curator_creation_through_dispatcher():
    prompt = _read(".github/prompts/evaluate.prompt.md")
    normalized = " ".join(prompt.split()).lower()

    assert "curate from a knowledge source" in normalized
    assert "configured or named scenario" in normalized
    assert "src/skills/evaluations/dispatcher/SKILL.md" in prompt


def test_curator_wrapper_uses_submodule_contract_without_duplication():
    wrapper = _read("src/skills/evaluations/curate/SKILL.md")
    normalized = " ".join(wrapper.split())
    normalized_lower = normalized.lower()

    assert "py -3.12 scripts/eval_curator_submodule.py status" in wrapper
    assert "exactly one JSON result" in normalized
    assert "skillPath" in wrapper
    assert "Read the returned curator skill in full" in wrapper
    assert "structuralValidatorPath" in wrapper
    assert "supportsHostOutputOverride" in wrapper
    assert "supportsHostLifecycleHandoff" in wrapper
    assert "both capability flags are exactly `true`" in normalized
    assert "before reading or invoking `skillPath`" in normalized
    assert "incompatible curator contract" in normalized_lower
    assert "never duplicate the curator instructions" in normalized_lower
    assert "active GitHub Copilot session" in wrapper


def test_curator_wrapper_defines_host_parameters_and_local_v1_boundary():
    wrapper = _read("src/skills/evaluations/curate/SKILL.md")
    normalized = " ".join(wrapper.split())
    normalized_lower = normalized.lower()

    assert "hostOutputRoot" in wrapper
    assert "workspace/evaluations" in wrapper
    assert "hostLifecycleHandoff" in wrapper
    assert (
        "Maker Kit validation, maker review choice, promotion, scoped push, "
        "and post-success run/results lifecycle"
    ) in normalized
    assert "local-file mode only for v1" in normalized_lower
    assert "knowledge source" in wrapper.lower()
    assert "agent instructions" in wrapper.lower()


def test_curator_wrapper_hands_off_to_maker_kit_lifecycle():
    wrapper = _read("src/skills/evaluations/curate/SKILL.md")
    normalized = " ".join(wrapper.split())
    normalized_lower = normalized.lower()

    assert "src/skills/evaluations/validate/SKILL.md" in wrapper
    assert "src/skills/evaluations/quality-fix-flow.md" in wrapper
    assert "src/skills/evaluations/update/SKILL.md" in wrapper
    assert "for each generated set" in normalized_lower
    assert "skip the curator local-only wrap-up" in normalized_lower
    assert "step 7 onward" in normalized_lower
    assert "explicitly preselected" in normalized_lower
    assert "one authoritative flow" in normalized_lower
    assert "do not duplicate" in normalized_lower


def test_curator_wrapper_requires_maker_choice_before_step_7_handoff():
    wrapper = _read("src/skills/evaluations/curate/SKILL.md")
    normalized = " ".join(wrapper.split())

    gate = normalized.index("What would you like to do with these test sets?")
    step_7_handoff = normalized.index("update **Step 7 onward**")

    assert gate < step_7_handoff
    assert "**Edit the test sets myself**" in wrapper
    assert "**Send them to a judge or SME for feedback**" in wrapper
    assert "**Keep them unchanged**" in wrapper
    assert "Wait for the maker's response" in normalized
    assert "Steps 2 through 6" in normalized
    assert "return to this maker review gate" in normalized
    assert "update **Flow R1**" in normalized
    assert "without implementing any mutation" in normalized


def test_run_skill_is_referenced_only_after_successful_push():
    wrapper = _read("src/skills/evaluations/curate/SKILL.md")
    update = _read("src/skills/evaluations/update/SKILL.md")
    normalized = " ".join(update.split())

    assert "src/skills/evaluations/run/SKILL.md" not in wrapper
    success_gate = normalized.index(
        "Only after `push.py --yes` completes successfully"
    )
    run_reference = normalized.index("src/skills/evaluations/run/SKILL.md")

    assert success_gate < run_reference
    assert "**Run an evaluation**" in update
    assert "**View results**" in update
    assert "**Finish**" in update
    assert "Wait for the user's response" in normalized
    assert "choosing a next action does not select a test set or run" in normalized
    assert "discovery and selection must remain separate user turns" in normalized
    assert "Do not offer **Run an evaluation** as immediately available" in update


def test_update_step_7_accepts_only_prevalidated_curator_handoff():
    update = _read("src/skills/evaluations/update/SKILL.md")
    normalized = " ".join(update.split()).lower()

    assert "authoritative post-validation lifecycle" in normalized
    assert "src/skills/evaluations/curate/SKILL.md" in update
    assert "preselected generated workspace set folders" in normalized
    assert (
        "curator validation and maker kit validation have both completed successfully"
        in normalized
    )
    assert "only this curator handoff may bypass steps 1 through 6" in normalized
    assert "enter step 7 directly" in normalized
    assert "do not repeat steps 1 through 6" in normalized
    assert "another skill" not in normalized
    assert "decline/keep-local" in normalized
    assert "optional review tagging" in normalized
    assert "setup check" in normalized
    assert "promotion" in normalized
    assert "scoped dry-run and push" in normalized
    assert "cleanup" in normalized
    assert "final status" in normalized


def test_curator_wrapper_blocks_on_missing_input_or_failed_validation():
    wrapper = _read("src/skills/evaluations/curate/SKILL.md")
    normalized = " ".join(wrapper.split()).lower()

    assert "ask exactly one question" in normalized
    assert "wait" in normalized
    assert "missing or incompatible" in normalized
    assert "stop" in normalized
    assert "failed or partial validation" in normalized
    assert "stays local" in normalized
    assert "blocks lifecycle handoff" in normalized
