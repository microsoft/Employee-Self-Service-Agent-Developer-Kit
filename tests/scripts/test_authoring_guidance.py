# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Source contract guards for authoring; not runtime UX acceptance."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOLUTION = ROOT / "solutions" / "ess-maker-skills"


def _read(relative: str) -> str:
    return (SOLUTION / relative).read_text(encoding="utf-8")


def test_create_and_update_prompts_route_to_normal_topic_owners():
    create = _read(".github/prompts/create.prompt.md")
    update = _read(".github/prompts/update.prompt.md")

    assert "src/skills/topics/create/SKILL.md" in create
    assert "src/skills/topics/update/SKILL.md" in update
    assert "crafted-response" not in create
    assert "crafted-response" not in update
    assert "scenario/materializer" in create
    assert "eval-driven save/materialization" in update


def test_topic_owners_use_yaml_adapters_and_separate_instruction_approval():
    create = _read("src/skills/topics/create/SKILL.md")
    update = _read("src/skills/topics/update/SKILL.md")

    assert "topic_authoring.py create --draft" in create
    assert "topic_authoring.py update --draft" in update
    assert "agent_instructions.py update --draft" in create
    assert "agent_instructions.py update --draft" in update
    assert "separate approvals" in create
    assert "separate topic and instruction approvals" in update
    assert "Do not activate or publish" in create
    assert "Do not activate or publish" in update
    assert "conversation acceptance as pending" in create
    assert "conversation acceptance as pending" in update


def test_eval_driven_aliases_are_thin_and_scenario_lifecycle_is_retired():
    create = _read("src/skills/topics/create-eval-driven/SKILL.md")
    update = _read("src/skills/topics/update-eval-driven/SKILL.md")

    assert "provisional compatibility alias" in create
    assert "provisional compatibility alias" in update
    assert "src/skills/topics/create/SKILL.md" in create
    assert "src/skills/topics/update/SKILL.md" in update
    assert "eval_scenario.py" not in create + update
    assert not (SOLUTION / "scripts" / "eval_scenario.py").exists()
    assert not (
        SOLUTION
        / "src"
        / "skills"
        / "topics"
        / "create-eval-driven"
        / "eval-scenario.schema.json"
    ).exists()


def test_flow_and_retired_workday_routes_are_notice_only():
    create = _read("src/skills/workflows/create/SKILL.md")
    update = _read("src/skills/workflows/update/SKILL.md")
    workday = _read("src/skills/setup/workday/create-new-topic.md")

    for guidance in (create, update):
        assert "outside ADK" in guidance
        assert "Do not" in guidance
        assert "runtime testing" in guidance
    assert "does not author custom topics or template configurations" in workday
    assert "src/skills/setup/workday-da/" in workday


def test_evaluation_handoff_uses_remote_context_without_overwriting_drafts():
    dispatcher = _read("src/skills/evaluations/dispatcher/SKILL.md")
    create = _read("src/skills/evaluations/create/SKILL.md")

    assert "topic_authoring.py list" in dispatcher
    assert "never overwrite the working topic drafts" in dispatcher
    assert "current remote inventory/content" in create
    assert "without overwriting local drafts" in create


def test_crafted_response_owner_is_removed_and_global_routing_is_current():
    instructions = _read(".github/copilot-instructions.md")

    assert not (SOLUTION / "src/skills/topics/crafted-response/SKILL.md").exists()
    assert "src/skills/topics/crafted-response/SKILL.md" not in instructions
    assert "src/skills/topics/create/SKILL.md" in instructions
    assert "src/skills/topics/update/SKILL.md" in instructions


def test_testing_handoff_checks_runtime_availability_not_legacy_skill_presence():
    for path in (
        "src/skills/topics/create/SKILL.md",
        "src/skills/topics/update/SKILL.md",
        ".github/prompts/test.prompt.md",
    ):
        guidance = _read(path)
        assert "scripts/native_topic_test.py" in guidance
        assert "conversation acceptance as pending" in guidance
        assert "`src/skills/topics/test/SKILL.md` exists" not in guidance


def test_authoring_and_push_entry_points_consume_the_shared_experience():
    for path in (
        ".github/prompts/create.prompt.md",
        ".github/prompts/update.prompt.md",
        ".github/prompts/push.prompt.md",
        ".github/prompts/test.prompt.md",
        ".github/copilot-instructions.md",
    ):
        assert "src/skills/topics/experience-contract.md" in _read(path)
    for owner in ("create", "update", "test"):
        assert "../experience-contract.md" in _read(
            f"src/skills/topics/{owner}/SKILL.md"
        )


def test_shared_experience_preserves_approved_copy_and_template_boundary():
    contract = _read("src/skills/topics/experience-contract.md")
    for literal in (
        "> **Push topic to agent** / **Keep as draft**",
        "**Topic pushed to agent.**",
        "**Draft kept locally. Agent unchanged.**",
        "**Topic was not pushed.**",
        "**Topic push could not be confirmed.**",
        "**Topic pushed; workspace update incomplete.**",
        "> **Push this change** / **Keep pending** / **Cancel remaining push**",
        "> | Item | Current | Proposed |",
        "> - {Verified preservation fact summary}",
        "> | Component | Outcome | Details |",
        "> **Test {Topic title} and fix any issues found?**",
        "> **Activate {Topic title}, test it and fix any issues found?**",
        "> After you confirm readiness, I will test {Topic title} against its "
        "intended behavior, investigate and fix issues observed during execution, "
        "and retest the affected behavior.",
        "> I will summarize the outcome and recommend any next action needed.",
        "> **Goal:** {Latest authoring goal}",
        "> **Outcome:** {Observed runtime outcome}",
        "> **Recommendation:** {Concrete tweak or next action}",
        "> **Testing paused.**\n>\n> Let me know when the test browser is ready.",
        "> **Testing stopped.**",
    ):
        assert literal in contract
    quoted = "\n".join(line for line in contract.splitlines() if line.startswith(">"))
    for instruction in (
        "Keep instructions, variable definitions",
        "Render the literal wording and paragraph structure",
        "Place any additional relevant context separately from the literal block",
        "Use the freshly read saved state",
        "Describe behavior and its limits rather than attempts or iterations",
        "not whatever reply happens to be saved",
    ):
        assert instruction in contract
        assert instruction not in quoted
    assert "Test {Topic title} now?" not in contract
    assert "Review note" not in contract
    assert "W06" not in contract


def test_push_uses_one_inventory_scoped_consent_and_composed_results():
    push = " ".join(_read(".github/prompts/push.prompt.md").split())
    contract = _read("src/skills/topics/experience-contract.md")
    assert "initially none" in push
    assert "Empty selection never means all changes" in push
    assert "Do not ask for independent owner approval again" in push
    assert "Pause dependent work" in contract
    assert "independently safe approved changes" in push
    assert "one `{composed_push_report}`" in push
    assert "Do not concatenate owner reports or menus" in push
    assert "does not combine topic, instruction, and evaluation approvals" not in push
    assert "Do not introduce Blocked as a separate Push status" in contract
    comparison = contract.split("### Compact change comparison\n", 1)[1].split(
        "### Push statuses:", 1
    )[0]
    assert "> [Full draft]" not in comparison


def test_advisories_have_structured_issue_effect_and_own_action_line():
    contract = _read("src/skills/topics/experience-contract.md")
    advisory = (
        "> - {Advisory issue}. {Practical effect}.\n>\n"
        ">   **Suggested action:** {Concrete next action}."
    )
    assert contract.count(advisory) == 3
    assert (
        "`{Concrete next action}` is a specific, relevant recommended step "
        "to investigate or address the issue, identifying what to inspect, "
        "test or change and its purpose."
    ) in contract
    assert "Ordinary factual notes retain their existing form." in contract


def test_readiness_message_has_maker_actions_and_a_separate_readiness_control():
    contract = _read("src/skills/topics/experience-contract.md")
    assert (
        "> **Test browser readiness**\n>\n"
        "> **Topic:** {Topic title}\n>\n"
        "> **Target:** {Agent name}, {Environment name}\n>\n"
        "> In the prepared test browser, sign in with a test account.\n>\n"
        "> Open the Test chat pane and leave its message box empty and idle.\n>\n"
        "> After you confirm readiness,"
    ) in contract
    assert (
        "> **Is the test browser ready?**\n>\n"
        "> **Ready to test** / **Not ready, keep paused** / **Stop without sending**"
    ) in contract
    assert (
        "> I will summarize the outcome and recommend any next action needed.\n\n"
        "Render the readiness message using the quoted wording, emphasis and paragraph breaks. "
        "Start any additional scope context after a blank line following the readiness message.\n\n"
        "Follow with this separate readiness-only control."
    ) in contract
    assert "resolve the browser connection internally" in contract
    assert "Collect missing browser connection/account details" not in contract
    assert "no additional input is needed for either choice to take effect" in contract
    assert "Use the corresponding acknowledgement exactly." in contract


def test_testing_reports_and_missing_permissions_reuse_scoped_contracts():
    contract = _read("src/skills/topics/experience-contract.md")
    instructions = " ".join(_read(".github/copilot-instructions.md").split())
    assert (
        "for existing topic conversation results, read "
        "`src/skills/topics/experience-contract.md` and use "
        "`{topic_test_results}` with saved observations."
    ) in instructions
    assert "retrieving topic results does not start new testing or authorize changes" in instructions
    assert "### Topic debugging outcome: `{topic_test_results}`" in contract
    assert "> **Evidence:** {Available evidence links}" in contract
    assert "including `evidenceDirectory` for native topic tests" in contract
    assert "A missing screenshot does not make a saved result file unavailable." in contract
    assert "For pause/stop, keep the fixed acknowledgement separate" in contract
    assert "unfinished or unobserved behavior and material uncertainty" in contract
    assert (
        "> **Activate {Topic title} for testing?**\n>\n"
        "> **Activate and test** / **Not now**"
    ) in contract
    assert "Preserve completed work and report it separately using `{topic_test_results}`." in contract
    assert "reusing valid context and permissions" in contract
    assert "This is an informational report, not another approval gate." in contract


def test_debugging_outcome_has_goal_and_only_needed_recommendation_without_loop_ledger():
    contract = _read("src/skills/topics/experience-contract.md")
    report = contract.split("### Topic debugging outcome: `{topic_test_results}`", 1)[1].split(
        "### Testing offers", 1
    )[0]
    prefix = (
        "> **Topic debugging outcome**\n>\n"
        "> **Topic:** {Topic title}\n>\n"
        "> **Target:** {Agent name}, {Environment name}\n>\n"
        "> **Goal:** {Latest authoring goal}\n>\n"
    )
    assert prefix + "> **Outcome:** {Observed runtime outcome}\n\n" in report
    assert (
        prefix + "> **Outcome:** {Current outcome and obstacle}\n>\n"
        "> **Recommendation:** {Concrete tweak or next action}\n\n"
    ) in report
    assert report.count("> **Recommendation:**") == 1
    for retired in ("| Test |", "**Fixes made**", "**Remaining issues**", "Retest:", "fn:"):
        assert retired not in report
    assert "When the requested behavior is observed, render:" in report
    assert "When a change or assistance is needed, render:" in report
    assert "These are applicable examples, not mandatory report categories." in report
    assert "conditional-section markers" not in contract


def test_scoped_runtime_goal_is_advisory_and_keeps_fixable_work_in_scope():
    contract = _read("src/skills/topics/experience-contract.md")
    prompt = _read(".github/prompts/test.prompt.md")
    assert "scoped runtime correctness goal" in prompt
    assert "offer manual testing guidance" in prompt
    assert "observed runtime behavior meets the latest authoring request" in contract
    assert "lightweight, best-effort check" in contract
    assert "preserve matching eval intent; keep those evals read-only" in contract
    assert "not a graded eval run or a mandatory case-by-case coverage exercise" in contract
    assert "Continue useful in-scope investigation and corrections" in contract
    assert "A fixable in-scope mismatch calls for further investigation and correction" in contract
    assert "When conflicting goals or constraints prevent progress" in contract
    assert "When tools, access or available evidence prevent further safe progress" in contract
    assert "Honor explicit test-only, pause and stop requests." in contract


def test_authoring_carries_context_and_honors_scoped_debugging():
    update = _read("src/skills/topics/update/SKILL.md")
    contract = _read("src/skills/topics/experience-contract.md")
    assert "Topic selection is a fallback, not a mandatory question" in update
    assert "discovered titles with short purposes plus free text" in update
    assert "A test-only request must not silently authorize edits" in contract
    assert (
        "repeated necessary fixes, pushes and retests do not each need fresh approval"
        in contract
    )
    assert (
        "An already-requested test does not waive missing activation permission"
        in contract
    )
    assert "Honor explicit no-activation requests" in contract
