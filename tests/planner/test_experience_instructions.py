# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Skill contracts for the maker-facing Planner orchestration."""

import json
import re
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "src" / "skills"


def _text(name):
    return (SKILLS / name).read_text(encoding="utf-8")


def test_plan_orientation_precedes_questions_and_permissions():
    text = _text("planner/SKILL.md")
    assert text.index("## Orient the maker") < text.index("## Gate")
    for phrase in ("A plan is your ESS rollout checklist", "not just", "resume", "share and activate", "pending"):
        assert phrase in text
    assert "tool approval" in _text("planner/sync.md").lower() or "Host trust" in text


def test_scenario_and_system_choices_explain_consequences_and_deferral():
    text = _text("planner/interview.md")
    forms = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", text, re.S)]
    assert len(forms) == 2
    for form in forms:
        question = form[0]
        assert question["multiSelect"] is True
        assert question["allowFreeformInput"] is True
        assert any(option["label"] == "Not sure yet" for option in question["options"])
        assert all(len(option["description"]) > 50 for option in question["options"])
    assert "add-system --area <scenario-id> --pending" in text
    assert "do not substitute SharePoint" in text
    assert "already-clear choices instead of reconfirming them" in text


def test_experience_is_inferred_after_scenarios_not_selected_up_front():
    expected = {
        "planner/SKILL.md": "Infer the experience from the scenarios",
        "planner/interview.md": "## Infer the experience from the scenarios",
        "planner/sync.md": "Reuse the scenario-inferred target",
    }
    for path, phrase in expected.items():
        assert phrase in " ".join(_text(path).split())
    prompt = (SKILLS.parents[1] / ".github" / "prompts" / "planner.prompt.md").read_text(encoding="utf-8")
    assert "Never open with an ESS experience picker" in " ".join(prompt.split())
    interview = _text("planner/interview.md")
    assert "Pick a focus" not in interview
    assert "ask only if the target agent" not in interview
    assert "sponsor still picks" not in _text("planner/sync.md")


def test_scenario_domains_ground_hr_and_it_inference():
    interview = _text("planner/interview.md")
    for name, examples in (
        ("EmployeeSelfServiceHRDA", ("profile", "HR cases", "manager")),
        ("EmployeeSelfServiceITDA", ("IT knowledge", "troubleshooting", "IT tickets")),
    ):
        row = next(line for line in interview.splitlines() if line.startswith("|") and name in line)
        assert all(example in row for example in examples)
    prose = " ".join(interview.split())
    assert "scenario_catalogue.md" in prose
    assert "Do not infer from a connector alone" in prose
    assert "Unknown systems do not delay" in prose


def test_experience_confirmation_is_part_of_draft_review():
    prose = " ".join(_text("planner/interview.md").split())
    assert "This looks like an ESS HR rollout" in prose
    assert "This looks like an ESS IT rollout" in prose
    assert "not a separate approval turn" in prose
    assert "Preserve an explicit or saved target" in prose
    assert "Do not silently retarget a shared plan" in prose


def test_unclear_or_mixed_experience_keeps_planning_open():
    prose = " ".join(_text("planner/interview.md").split())
    assert "mixed HR/IT" in prose
    assert "Facilities" in prose
    assert "--key experience" in prose
    assert "--group pendingDecision" in prose
    assert "remove-context --key experience" in prose
    assert "Keep all requested scenarios" in prose
    assert "local draft without a target" in prose


def test_planner_evaluations_generate_in_flow_with_existing_safety_gates():
    text = _text("planner/evaluate.md")
    assert "--group evaluationCase" in text
    for path in ("topics/create-eval-driven/SKILL.md", "evaluations/create/SKILL.md"):
        assert f"src/skills/{path}" in text
        assert (SKILLS / path).is_file()
    assert "push approval" in " ".join(text.split())
    assert "not a test run" in _text("planner/SKILL.md")
    assert "Generate only missing coverage" in text
    handoff = _text("evaluations/create/SKILL.md")
    assert "Planner handoff: reuse the supplied scope" in handoff
    assert "Do not ask the maker to invoke `/evaluate` separately" in handoff


def test_shared_completion_requires_state_output_readback_and_explicit_activation():
    text = _text("planner/capture.md")
    assert "state **and the expected output" in text
    assert "Never publish or activate" in text
    assert "no partial-output write endpoint" in text
    assert "set_project_plan_task_state" in text
    assert "preserve the original ETag" in text


def test_next_steps_explain_share_and_activate_with_separate_prompts():
    text = _text("planner/interview.md").split("## After the plan is shown", 1)[1]
    readout = text.split("Then **end the turn.**", 1)[0]
    steps = re.findall(r"^> (\d+)\. (.*?)(?=^> \d+\.|\Z)", readout, re.M | re.S)
    assert [number for number, _ in steps] == ["1", "2", "3", "4"]
    share = " ".join(steps[1][1].replace(">", "").split())
    activate = " ".join(steps[2][1].replace(">", "").split())
    for phrase in ("shared draft", "colleagues with access can review", "read-only until activation"):
        assert phrase in share
    assert '**Prompt:** "Share this plan."' in share
    assert "Activate this plan." not in share
    for phrase in ("active rollout plan", "start ready tasks", "record progress"):
        assert phrase in activate
    assert "does not run tasks or deploy ESS automatically" in activate
    assert '**Prompt:** "Activate this plan."' in activate
    assert "Share this plan." not in activate
    assert "displaying an example is not permission to perform it" in " ".join(readout.split())
    main = " ".join(_text("planner/SKILL.md").split())
    assert "Share and Activate are separate steps" in main
    assert '"Share this plan."' in main
    assert '"Activate this plan."' in main


def test_shared_draft_follow_up_explains_activation_and_waits_for_request():
    text = _text("planner/sync.md").split("5. **Confirm it's saved", 1)[1]
    follow_up = " ".join(text.split("6. **Activate when", 1)[0].split())
    assert "active rollout plan" in follow_up
    assert "does not run tasks or deploy ESS automatically" in follow_up
    assert '**Prompt:** "Activate this plan."' in follow_up
    assert "only when the sponsor asks to activate" in follow_up


@pytest.mark.parametrize(
    ("state", "prompt"),
    [
        ("Local draft", "Share this plan."),
        ("Shared draft", "Activate this plan."),
        ("Active", "Assign people to the roles."),
    ],
)
def test_maker_status_next_step_matches_plan_lifecycle(state, prompt):
    rows = _text("planner/status.md").splitlines()
    row = next((line for line in rows if line.startswith(f"| Maker / sponsor | {state} |")), "")
    assert row, f"Missing maker next-step policy for {state}"
    assert prompt in row
    assert "/setup" not in row
    if state == "Shared draft":
        assert "plan owner" in row
        assert "does not run tasks or deploy ESS automatically" in row


def test_status_separates_team_readiness_from_caller_execution():
    text = " ".join(_text("planner/status.md").split())
    for phrase in (
        "**Team readiness**",
        "**Your next step**",
        "not the first ready task in the overall plan",
        "list_project_plan_tasks_for_caller",
        "InProgress",
        "NotStarted",
        "`blockedBy`",
        "shared draft remains read-only",
        "never substitute another person's ready work",
    ):
        assert phrase in text
    row = next(
        line
        for line in _text("planner/status.md").splitlines()
        if line.startswith("| Assignee | Active, own in-progress or ready task |")
    )
    assert "/setup" in row
    assert "Start my environment setup task." in row
    assert "Continue setup." in row


def test_status_reuses_context_without_forcing_sharing_or_stealing_work():
    text = " ".join(_text("planner/status.md").split())
    for phrase in (
        "Reuse the known maker/sponsor context",
        "Do not ask for a role that is already known",
        "local-only drafting",
        "do not keep prompting them to share",
        "no shared plan ID",
        "403/access denied",
        "do not guess who the requester is",
        "Never share, activate, assign, claim, or run a skill",
        "no unfinished work remains",
        "Completed or Archived",
    ):
        assert phrase in text


@pytest.mark.parametrize("entry", ["skill", "prompt"])
def test_status_entrypoints_require_the_requesting_persons_next_step(entry):
    if entry == "skill":
        text = _text("planner/SKILL.md")
    else:
        path = SKILLS.parents[1] / ".github" / "prompts" / "planner.prompt.md"
        text = path.read_text(encoding="utf-8")
    prose = " ".join(text.split())
    assert "**Your next step**" in prose
    assert "requesting person" in prose
    assert "plan lifecycle" in prose
    assert "status.md" in prose


def test_next_step_presentation_has_a_heading_bold_action_and_continuation():
    guidelines = (SKILLS.parent / "reference" / "ui-formatting-guidelines.md").read_text(encoding="utf-8")
    handoffs = guidelines.split("## Next-step handoffs", 1)[1].split("\n## ", 1)[0]
    for phrase in (
        "## Your next step",
        "bold the action itself",
        "**Say:**",
        "**Run:**",
        "**Open:**",
        "one primary action",
        "not a buried sentence",
        "No action is needed from you right now",
        "not permission to execute",
    ):
        assert phrase in " ".join(handoffs.split())
    assert "## Next steps" in handoffs
    assert "after activation" in handoffs


@pytest.mark.parametrize("phase", [
    "assign", "capture", "edit", "evaluate", "import", "interview",
    "model", "mytasks", "research", "status", "sync",
])
def test_each_planner_phase_inherits_shared_response_presentation(phase):
    text = _text(f"planner/{phase}.md")
    entry = (
        text.split("## Entry preflight", 1)[1].split("**Rules that never bend:**", 1)[0]
        if phase == "sync"
        else text.split("\n\n", 2)[1]
    )
    assert "**Communication rules**" in entry
    assert "every reply" in entry
    main = " ".join(_text("planner/SKILL.md").split())
    assert "src/reference/ui-formatting-guidelines.md" in main
    assert "Next-step handoffs" in main


@pytest.mark.parametrize("entry", ["skill", "prompt"])
def test_native_entrypoints_keep_next_step_presentation_visible(entry):
    path = (
        SKILLS.parents[1] / ".github" / "skills" / "planner" / "SKILL.md"
        if entry == "skill"
        else SKILLS.parents[1] / ".github" / "prompts" / "planner.prompt.md"
    )
    text = " ".join(path.read_text(encoding="utf-8").split())
    assert "Communication rules" in text
    assert "every reply" in text


def test_activation_follow_up_uses_the_prominent_action_block():
    text = _text("planner/status.md")
    example = text.split("### After activation", 1)[1].split("## Step 2", 1)[0]
    assert "> ## Your next step\n>\n> **Assign people to the rollout roles.**" in example
    assert '> **Say:** "Assign people to the roles."' in example
    assert "confirmed on the shared plan" in example
    assert "Activation did not run tasks or deploy ESS." in example
    assert "only when readback confirms" in example
    assert "unfinished work still have no owners" in example


def test_initial_plan_and_import_do_not_bury_or_misroute_next_steps():
    interview = _text("planner/interview.md").split("## After the plan is shown", 1)[1]
    assert "> ## Next steps\n" in interview
    assert '**Prompt:** "Review the plan."' in interview
    assert '**Prompt:** "Assign people to the roles."' in interview
    imported = " ".join(_text("planner/import.md").split("## Step 6", 1)[1].split())
    assert "requesting person's next step" in imported
    assert "status.md" in imported
    assert "Do not send an unshared, unassigned draft straight to an admin" in imported
    assert "The next step is to ask your" not in imported


def test_roles_distinguish_setup_context_from_explicit_assignment():
    text = " ".join(_text("roles/SKILL.md").split())
    for phrase in (
        "setup role statement is not a plan-assignment request",
        "I am the Power Platform admin",
        "src/skills/foundation-setup/SKILL.md",
        "explicit assignment request",
        "main chat",
        "does not require completed environment setup",
        "src/skills/planner/SKILL.md",
    ):
        assert phrase in text
    assert "this is not a pre-setup experience" not in text


def test_self_assignment_reuses_verified_identity_without_guessing_or_hidden_questions():
    text = " ".join(_text("roles/resolve-person.md").split())
    for phrase in (
        "I", "me", "verified signed-in identity", "intended tenant",
        "main chat", "first or partial name", "Leave unassigned for now",
        "user is not available", "not an answer",
        "Do not infer", "plan owner", "operating-system",
        "do not write an assignment",
    ):
        assert phrase in text
    assert "src/reference/ui-formatting-guidelines.md" in text


def test_role_follow_ups_are_confirmed_requester_scoped_and_nonblocking():
    attest = " ".join(_text("roles/attest.md").split())
    assert "Only confirm an assignment after a successful shared result" in attest
    assert "Reuse an explicit or already-confirmed role choice" in attest
    assert "ask only when the mapping is ambiguous" in attest
    for path in ("roles/attest.md", "roles/list.md"):
        text = " ".join(_text(path).split())
        assert "Refresh after progress" in text
        assert "requesting person" in text
    nudge = _text("roles/nudge.md")
    assert "Active" in nudge
    assert "unfinished work" in nudge
    assert "> ## Your next step" in nudge
    assert "not a blocking question" in nudge
    assert "Who should be" not in nudge


def test_signin_guidance_matches_the_bounded_transport_behavior():
    text = " ".join(_text("planner/sync.md").split())
    assert "does not automatically refresh and replay a rejected HTTP 401" in text
    assert "not proof of a fresh browser sign-in" in text
    assert "do not loop, change accounts automatically" in text
    assert "renews in place" not in text


def test_foundation_task_handoff_uses_setup_for_environment_and_installation():
    text = _text("planner/mytasks.md")
    for phrase in ("primaryEnvironment", "provisionedEnvironment", "essAgent"):
        assert phrase in text
    assert "src/skills/foundation-setup/SKILL.md" in text
    assert "Continue `/setup`" in text
    prose = " ".join(text.split())
    assert "`kitSetup` because this task needs the pinned environment" in prose
    assert "do not invent an environment dependency" in prose
    assert "description or the foundation outputs" in prose
    manual = text.split("2. **The task is a portal / manual step**", 1)[1]
    assert "provision the Power Platform environment" not in manual


def test_progress_refreshes_next_action_from_current_state_for_the_same_person():
    text = _text("planner/status.md")
    assert "## Refresh after progress" in text
    refresh = " ".join(text.split("## Refresh after progress", 1)[1].split("## Step 2", 1)[0].split())
    for phrase in (
        "same requester",
        "Do not reuse the previous recommendation",
        "list_project_plan_tasks_for_caller",
        "pendingSync",
        "partial",
        "no open work",
        "do not automatically start",
    ):
        assert phrase in refresh
    for path in ("planner/SKILL.md", "planner/capture.md", "planner/sync.md", "planner/assign.md"):
        assert "Refresh after progress" in _text(path)


def test_native_planner_preserves_explicit_sharing_and_activation():
    path = SKILLS.parents[1] / ".github" / "skills" / "planner" / "SKILL.md"
    text = " ".join(path.read_text(encoding="utf-8").split())
    assert "local draft" in text
    assert "explicitly asks to share" in text
    assert "explicit activation" in text
    assert "declined shared access" in text
    assert "once built, it is published" not in text


def test_intent_capture_precedes_scoped_research():
    main = _text("planner/SKILL.md")
    assert main.index("| 1. Interview |") < main.index("| 2. Research |") < main.index("| 3. Model |")
    research = " ".join(_text("planner/research.md").split())
    assert "Capture intent before research" in research
    assert "unknown systems" in research
    interview = " ".join(_text("planner/interview.md").split())
    assert "one batched `vscode_askQuestions` call" in interview
    assert "Do not ask each area in a separate turn" in interview
    assert "Ask once per captured area" not in interview


def test_research_reuses_fetched_content_and_exposes_freshness():
    text = " ".join(_text("planner/research.md").split())
    for phrase in ("research-context.json", "24 hours", "--refresh", "Do not fetch selected pages again"):
        assert phrase in text
    assert "no persisted" not in text
    assert "Read the selected pages** with your fetch tool" not in text


def test_servicenow_grounding_uses_its_existing_connect_checklist():
    text = _text("planner/model.md")
    assert "setup/servicenow/tasks.md" not in text
    assert "src/skills/connect/servicenow/steps.md" in text
    assert (SKILLS / "connect" / "servicenow" / "steps.md").is_file()
    row = next(line for line in text.splitlines() if line.startswith("| Connect ServiceNow |"))
    assert "Learn" in row
    assert "role:` items" not in row


def test_workspace_collapses_display_without_changing_models():
    path = SKILLS.parents[1] / ".vscode" / "settings.json"
    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["chat.agent.thinkingStyle"] == "collapsed"
    assert settings["chat.agent.thinking.collapsedTools"] == "always"
    assert settings["chat.experimental.persistentProgress"] == "off"
    assert not any("model" in key.lower() or "reasoningEffort" in key for key in settings)


def test_native_planner_discovers_existing_plan_lifecycle_requests():
    path = SKILLS.parents[1] / ".github" / "skills" / "planner" / "SKILL.md"
    metadata = " ".join(path.read_text(encoding="utf-8").split("---", 2)[1].split())
    for phrase in (
        "VS Code", "share and activate the plan", "resume", "status", "before setup",
        "import", "edit", "assign owners", "record task completion",
    ):
        assert phrase in metadata


def test_planner_intent_is_checked_before_orientation_bootstrap_and_resume():
    text = _text("planner/SKILL.md")
    assert text.index("## Intent gate") < text.index("## Orient the maker") < text.index("## Gate")
    gate = " ".join(text.split("## Intent gate", 1)[1].split("\n## ", 1)[0].split())
    for phrase in (
        "current user request",
        "passive context is not intent",
        "open or attached `plan.json`",
        "Do not inspect or resume a plan",
        "materialize Planner MCPs",
        "discover tools",
        "request shared access",
        "greeting does not answer",
        "do not add a confirmation turn",
    ):
        assert phrase in gate
    bootstrap = " ".join(text.split("## Gate", 1)[1].split("## First", 1)[0].split())
    assert "not the first message in every chat" in bootstrap
    assert "does not relax other skills' setup requirements" in bootstrap


@pytest.mark.parametrize(("message", "context", "route"), [
    ("Hi", "`plan.json` is open", "Normal welcome"),
    ("Hello", "A plan is attached", "Normal welcome"),
    ("Thanks", "A plan is active", "Acknowledge"),
    ("What does /planner do?", "Any", "Explain"),
    ("Share and activate it", "A saved plan supplies the target", "Planner"),
    ("Show my plan status", "A saved plan supplies the target", "Planner"),
    ("Hi, show my plan status", "A saved plan supplies the target", "Planner"),
    ("Yes", "Reply to an offered Planner action", "Planner"),
    ("Workday", "Reply to the current Planner system question", "Planner"),
])
def test_intent_examples_distinguish_context_from_requested_work(message, context, route):
    rows = _text("planner/SKILL.md").splitlines()
    row = next(line for line in rows if line.startswith(f'| "{message}" | {context} |'))
    assert row.split("|")[3].strip().startswith(route)
    if route != "Planner":
        assert "no Planner tools" in row


@pytest.mark.parametrize("entry", ["native", "prompt", "sync"])
def test_direct_entries_admit_intent_before_workspace_bootstrap(entry):
    path = {
        "native": SKILLS.parents[1] / ".github" / "skills" / "planner" / "SKILL.md",
        "prompt": SKILLS.parents[1] / ".github" / "prompts" / "planner.prompt.md",
        "sync": SKILLS / "planner" / "sync.md",
    }[entry]
    text = " ".join(path.read_text(encoding="utf-8").split())
    assert text.index("Intent gate") < text.index("workspace bootstrap")
    assert '"Hi"' in text
    assert "passive" in text
    assert "A saved local plan in a fresh chat is enough context" not in text


def test_existing_draft_and_visible_tools_do_not_skip_workspace_bootstrap():
    text = _text("planner/SKILL.md")
    gate, resume = text.split("## Gate", 1)[1].split("## First", 1)
    assert "After completing the Gate above" in resume
    prose = " ".join(gate.split())
    assert gate.index("materialize-defaults") < gate.index("validate --server ess-planner")
    for phrase in (
        "first Planner use in each chat",
        "existing local draft",
        "tools are already visible",
        ".vscode/mcp.json",
        "configured",
        "earlier session",
    ):
        assert phrase in prose


def test_planner_bootstrap_is_reused_across_flows_but_not_across_chats():
    gate = _text("planner/SKILL.md").split("## Gate", 1)[1].split("## First", 1)[0]
    prose = " ".join(gate.split())
    for phrase in (
        "same chat and workspace",
        "later turns or phases",
        "workspace or MCP configuration changes",
        "no bootstrap attempt is recorded",
        "failed bootstrap",
        "validate --server workiq-preview",
        "does not grant shared access",
    ):
        assert phrase in prose
    assert "current interaction" not in gate
    assert "once per Planner entry" not in gate


@pytest.mark.parametrize(
    "phase",
    sorted(path.name for path in (SKILLS / "planner").glob("*.md") if path.name != "SKILL.md"),
)
def test_every_planner_phase_enters_through_the_shared_chat_bootstrap(phase):
    entry = " ".join(_text(f"planner/{phase}").splitlines()[:18])
    assert "src/skills/planner/SKILL.md" in entry
    assert "Intent gate" in entry
    assert "Gate" in entry
    assert "workspace bootstrap" in entry
    assert "first Planner use" in entry
    assert "same chat and workspace" in entry


@pytest.mark.parametrize("entry", ["native", "prompt", "sync"])
def test_lifecycle_entrypoints_bootstrap_before_shared_calls(entry):
    if entry == "native":
        path = SKILLS.parents[1] / ".github" / "skills" / "planner" / "SKILL.md"
    elif entry == "prompt":
        path = SKILLS.parents[1] / ".github" / "prompts" / "planner.prompt.md"
    else:
        path = SKILLS / "planner" / "sync.md"
    prose = " ".join(path.read_text(encoding="utf-8").split())
    assert "workspace bootstrap" in prose
    assert "before any shared tool call" in prose


def test_bootstrap_recovers_missing_config_or_host_tools_after_success():
    gate = " ".join(_text("planner/SKILL.md").split("## Gate", 1)[1].split("## First", 1)[0].split())
    for phrase in (
        "At the start of each request",
        "If the file is missing",
        "unavailable MCP connection",
        "invalidate the earlier success",
        "once for that failure",
        "even if Planner already checked earlier",
    ):
        assert phrase in gate
    assert "is not an unavailable MCP connection" in gate
    assert "Preserve overrides" in gate


def test_size_guidance_requires_export_and_stops_unchanged_retries():
    text = " ".join(_text("planner/sync.md").split())
    for phrase in (
        "25,600 bytes", "aggregate UTF-8 preflight", "server-added",
        "Do not retry unchanged", "Require a successful export",
        "confirm the intended tenant/account", "never include access tokens",
        "generic 500 without size evidence",
    ):
        assert phrase in text
    assert text.index("PlanPayloadTooLarge / OpenTypeTooLarge") < text.index("Network error or 5xx")
