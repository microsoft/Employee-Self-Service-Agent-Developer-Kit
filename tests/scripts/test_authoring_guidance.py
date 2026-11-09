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


def test_flow_routes_are_notice_only_and_retired_workday_route_is_removed():
    create = _read("src/skills/workflows/create/SKILL.md")
    update = _read("src/skills/workflows/update/SKILL.md")

    for guidance in (create, update):
        assert "outside ADK" in guidance
        assert "Do not" in guidance
        assert "runtime testing" in guidance
    retired_route = "src/skills/setup/workday/create-new-topic.md"
    assert not (SOLUTION / retired_route).exists()
    assert retired_route not in _read("src/skills/topics/create/SKILL.md")


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
        if literal.startswith("> |"):
            assert " ".join(literal.split()) in " ".join(contract.split())
        else:
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
    assert (
        "> **Not included**\n>\n> **{Component type}**\n>\n"
        "> - {Component name}: {Exclusion reason}"
    ) in comparison
    assert "even when those entries appeared earlier in the conversation" in comparison
    assert "one named bullet with its reason per component" in contract
    assert "parsed instruction section with the baseline separately from metadata" in push
    assert "unchanged instructions out of pending and excluded changes" in push
    assert "rename as Display name" in push


def test_already_satisfied_topic_outcome_does_not_claim_a_new_push():
    contract = _read("src/skills/topics/experience-contract.md")
    update = _read("src/skills/topics/update/SKILL.md")
    assert "**Topic already up to date. No push needed.**" in contract
    assert "`writeAttempted: false`" in contract
    assert "`updatedComponents: 0`" in contract
    assert "Do not attribute the existing change to this operation." in contract
    assert "no-write outcome" in update
    assert "verified saved content" in update


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


def test_initial_routing_conflict_decision_precedes_push_and_preserves_exact_scope():
    contract = _read("src/skills/topics/experience-contract.md")
    initial = contract.split("### Initial routing-conflict decision\n", 1)[1].split(
        "### Authorization and recovery\n", 1
    )[0]
    assert (
        "> **Resolve the routing conflict in the Agent Instructions** / "
        "**Push topic anyway** / **Keep as draft**"
    ) in initial
    assert "before any topic or instruction push" in initial
    assert "does not approve a topic push, instruction push, activation or testing" in initial
    assert "Review the topic draft and targeted instruction correction together" in initial
    assert "exclude unrelated pending edits" in initial
    assert "pause dependent work" in initial
    assert "Push topic anyway approves only the displayed topic save" in initial
    assert "declined routing correction as an explicit exclusion" in initial
    assert "Do not immediately offer the same resolution decision again" in initial
    assert "do not offer runnable testing of unsaved topic changes" in initial


def test_new_conflict_after_push_combines_state_aware_testing_without_instruction_consent():
    contract = _read("src/skills/topics/experience-contract.md")
    follow_up = contract.split(
        "### Combined routing-conflict and testing follow-up\n", 1
    )[1].split("### Targeted instruction-change preview and approval\n", 1)[0]
    assert (
        "> **How would you like to continue with {Topic title}?**\n>\n"
        "> **Resolve the routing conflict in the Agent Instructions** / "
        "**Not now, Activate and test anyway.**"
    ) in follow_up
    assert "**Not now, Test anyway.**" in follow_up
    assert "does not approve an instruction push, activation or testing" in follow_up
    assert "Confirm authoritative Active state before sending a test message" in follow_up
    assert "do not silently repair it during testing" in follow_up
    assert "scoped batch/debugging consent rules" in follow_up
    assert "deliberate topic-only save" in follow_up
    assert "only when a routing conflict is newly discovered or materially changed" in follow_up
    assert "Do not repeat the resolution choice for the same conflict" in follow_up
    assert "Prepare instruction change for review" not in contract
    assert "> **Routing Conflicts**" in follow_up
    assert "This routing conflict will likely block topic execution." in follow_up
    assert "Check the installed testing capability before offering a runnable test" in follow_up
    testing = _read("src/skills/topics/test/SKILL.md")
    assert "does not include automated conversation testing" in testing
    assert "Do not display runnable testing or activation choices" in testing
    assert not (SOLUTION / "scripts" / "native_topic_test.py").exists()


def test_instruction_correction_has_separate_preview_approval_and_truthful_outcomes():
    contract = _read("src/skills/topics/experience-contract.md")
    preview = contract.split(
        "### Targeted instruction-change preview and approval\n", 1
    )[1].split("### Instruction-push outcomes and testing\n", 1)[0]
    assert "> **Current wording**" in preview
    assert "> **Proposed wording**" in preview
    assert "> **Push instruction change** / **Keep as draft**" in preview
    assert "It does not authorize activation, testing or publication." in preview
    assert "concurrency and readback safeguards" in preview
    assert "**Instruction draft kept locally.**" in preview
    assert "Agent instructions already up to date." in contract
    assert "Instruction push could not be confirmed." in contract
    assert "Topic execution has not yet been verified." in contract
    assert "complete `{Verified instruction-save result}` statement" in contract


def test_draft_and_partial_instruction_results_do_not_assume_a_topic_push():
    contract = _read("src/skills/topics/experience-contract.md")
    preview = contract.split(
        "### Targeted instruction-change preview and approval\n", 1
    )[1].split("### Instruction-push outcomes and testing\n", 1)[0]
    outcomes = contract.split("### Instruction-push outcomes and testing\n", 1)[1].split(
        "## ", 1
    )[0]
    assert "{topic_save_state}" in preview
    assert "The new topic remains local and has not been pushed." in preview
    assert "The proposed changes remain local; distinguish them from the existing saved topic." in preview
    assert "review the topic and isolated instruction correction together" in preview
    assert (
        "**Summarize each change**, **Push all listed changes**, "
        "**Choose what to push**, and **Cancel**"
    ) in preview
    assert "**Only when the proposed topic content is already authoritatively saved:**" in preview
    assert "Do not offer runnable testing of unsaved topic changes" in preview
    assert "The topic was already pushed." not in preview
    assert "Report the actual topic-save state" in outcomes
    assert "verified already current" in outcomes
    assert "topic Push is still pending" in outcomes
    assert "instruction update saves or activates the topic" in outcomes
    assert "explicitly requests testing despite the remaining conflict" in outcomes
    assert "Do not automatically repeat resolution for the same conflict" in outcomes
    assert "For partial saves, use the composed report" in contract


def test_topic_and_push_handoffs_honor_initial_decisions_and_limit_fallbacks():
    for owner in ("create", "update"):
        guidance = _read(f"src/skills/topics/{owner}/SKILL.md")
        assert "initial routing-conflict decision" in guidance
        assert "Resolve the routing conflict in the Agent Instructions / Push topic anyway / Keep as draft" in guidance
        assert "newly discovered or materially changed conflict" in guidance
        assert "does not itself authorize testing" in guidance
    for entry in ("create", "update", "push"):
        prompt = " ".join(_read(f".github/prompts/{entry}.prompt.md").split())
        assert "initial routing-conflict decision" in prompt
        assert "combined routing-conflict/testing decision" in prompt
        assert "newly discovered or materially changed conflict" in prompt
    contract = _read("src/skills/topics/experience-contract.md")
    composed = contract.split("### Composed Push report:", 1)[1].split(
        "## Topic testing continuation", 1
    )[0]
    assert "honor the initial routing-conflict decision" in composed
    assert "Only for a newly discovered or materially changed conflict" in composed
    assert "Do not offer runnable testing of topic changes left local" in composed


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
    assert "Link actual available evidence after the complete outcome block" in contract
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
    assert "re-render the change-focused Update summary from step 2" in update
    assert "Do not reduce the re-review to conflicting reply excerpts alone." in update
    assert "the freshly read current wording versus the proposal" in contract
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
