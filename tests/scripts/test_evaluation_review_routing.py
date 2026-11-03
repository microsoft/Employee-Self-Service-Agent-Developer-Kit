from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLUTION_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills"


def _read(relative_path: str) -> str:
    return (SOLUTION_ROOT / relative_path).read_text(encoding="utf-8")


def _normalized(relative_path: str) -> str:
    return " ".join(_read(relative_path).split())


def test_review_testsets_routes_to_human_review_before_validation():
    review_prompt = _read(".github/prompts/review.prompt.md")
    evaluate_prompt = _read(".github/prompts/evaluate.prompt.md")
    review_skill = _read("src/skills/evaluations/review/SKILL.md")
    validate_skill = _read("src/skills/evaluations/validate/SKILL.md")
    normalized_review_skill = " ".join(review_skill.split())

    assert '"review testsets"' in review_prompt
    assert "src/skills/evaluations/review/SKILL.md" in review_prompt
    assert "does not mean quality validation" in evaluate_prompt
    assert "list tagged sets before invoking any validator" in evaluate_prompt
    assert "evaluation_review.py --list --status review_requested" in review_skill
    assert "Which test set would you like to review?" in review_skill
    assert 'Do not call the test sets "pending"' in review_skill
    assert "wait for the user to select" in review_skill.lower()
    assert "Do not use this skill as the entry point" in validate_skill
    assert 'Never describe this workflow as "view-only"' in normalized_review_skill
    assert "provides feedback, suggestions, or recommendations" in normalized_review_skill
    assert "does not edit test-case source files" in normalized_review_skill
    assert "quality validation is not invoked" in normalized_review_skill
    assert "structured question control" in review_skill
    assert "**Provide feedback or recommendations for the maker**" in normalized_review_skill
    assert "maker owns the official edits, validation, push" in normalized_review_skill


def test_review_route_does_not_require_setup_for_workspace_sets():
    review_prompt = _normalized(".github/prompts/review.prompt.md")
    update_prompt = _normalized(".github/prompts/update.prompt.md")

    assert "Do this before any setup gate" in review_prompt
    assert "Workspace-level evaluation sets can be reviewed without a configured agent" in review_prompt
    assert "Workspace-level evaluation updates and review-tag workflows do not" in update_prompt


def test_reviewer_flow_refreshes_configured_agent_automatically():
    review_skill = _normalized("src/skills/evaluations/review/SKILL.md")
    update_skill = _normalized("src/skills/evaluations/update/SKILL.md")

    for skill in (review_skill, update_skill):
        assert "python scripts/fetch_and_setup.py --refresh" in skill
        assert "creates a checkpoint" in skill
        assert "Do not ask" in skill
        assert "/setup --refresh" in skill
        assert "rather than" in skill
        assert "stale" in skill

    assert "The reviewer must not be asked to pull or refresh test sets manually" in review_skill
    assert "unless `fetch_and_setup.py --refresh` already completed successfully in the current turn" in update_skill


def test_native_review_discovery_never_routes_to_dataverse():
    review_skill = _normalized("src/skills/evaluations/review/SKILL.md")
    review_prompt = _normalized(".github/prompts/review.prompt.md")

    for fragment in (
        '`releaseLine: "da"`',
        "`powerPlatformApiEndpoint`",
        "no `dataverseEndpoint`",
        "python scripts/evaluation_review.py --list-all",
        "select rows whose `localStatus` is `review_requested`",
        "never invoke Dataverse MCP",
        "A Dataverse authentication prompt in this branch is a routing error",
    ):
        assert fragment in review_skill
    assert "native DA agents use local-inclusive review discovery" in review_prompt
    assert "must never trigger Dataverse MCP authentication" in review_prompt


def test_generic_tag_request_requires_all_sets_and_explicit_selection():
    update_skill = _read("src/skills/evaluations/update/SKILL.md")

    assert "evaluation_review.py --list-all" in update_skill
    assert "Display every returned workspace and configured-agent test set" in update_skill
    assert "Wait for an explicit selection" in update_skill
    assert "Do not infer a selection from the previous conversation" in update_skill
    assert "structured choice control" in update_skill


def test_maker_is_offered_shared_four_actions():
    contract = _normalized("src/skills/evaluations/experience-contract.md")
    for option in (
        "Do you want to mark this test set ready for review so another user can provide feedback?",
        "Are you ready to run this test set in Copilot Studio?",
        "Do you want to further edit this test set?",
        "Do you want to do another quality review on this test set?",
    ):
        assert f"**{option}**" in contract
    assert "these exact option labels in order" in contract
    assert "only place these options appear" in contract
    assert "Do not show a separate Push menu item" in contract
    assert "never auto-select" in contract
    for flow in ("create", "generate", "update"):
        skill = _normalized(f"src/skills/evaluations/{flow}/SKILL.md")
        assert "src/skills/evaluations/experience-contract.md" in skill
        assert "Four maker actions" in skill
        assert "**Push without requesting review**" not in skill


def test_reviewer_recommendations_return_ownership_to_maker():
    update_skill = _read("src/skills/evaluations/update/SKILL.md")
    normalized = " ".join(update_skill.split())

    assert "**Provide feedback or recommendations for the maker**" in update_skill
    assert "The reviewer does not edit the test-case source files" in normalized
    assert "The maker should apply the official test-case changes" in normalized
    assert "Recommendations alone do not modify the test-set files" in normalized
    assert "Do not claim that conversational recommendations were automatically written" in normalized


def test_evaluation_push_is_scoped_and_warns_about_replacement_deletions():
    update_skill = _read("src/skills/evaluations/update/SKILL.md")
    deployment = _normalized("src/skills/evaluations/deployment-flow.md")
    assert "src/skills/evaluations/deployment-flow.md" in update_skill
    assert '--only "evaluations/{set}/*" --dry-run' in deployment
    assert '--only "evaluations/{set}/*" --yes' in deployment
    assert '--yes --force-delete' in deployment
    assert "Never use an unscoped" in deployment
    assert ".baseline/evaluations/{set}/" in deployment
    assert "pushing a replacement will delete those cases" in deployment
    assert "unrelated local topic or workflow deletions" in deployment
    assert "evaluation_promotion.py promote" in deployment
    assert "evaluation_promotion.py cleanup" in deployment
    assert "Do not manually delete promotion paths" in deployment
    assert "On Dataverse, explain that pushing a replacement" in deployment
    assert "new-copy behavior and old-copy retention instead" in deployment
    assert "not case omissions in a native new copy" in deployment


def test_review_requested_update_resolves_review_before_push():
    update_skill = _read("src/skills/evaluations/update/SKILL.md")
    normalized = " ".join(update_skill.split())

    assert "## Step 6a: Review completion gate" in update_skill
    assert "Do not show or ask the push question until" in update_skill
    assert "**Mark review complete**" in update_skill
    assert "**Provide feedback or recommendations for the maker**" in update_skill
    assert "--status review_completed" in update_skill
    assert "completion requires the user's explicit choice" in update_skill
    assert "keeps the review open" in normalized
    assert "review is finished" in update_skill
    assert "When this push records `review_completed`" in update_skill
    assert "You can now run this test set" in update_skill
    assert "on Dataverse and verifies it" in normalized
    assert "For native success, report the actual deployed ID and local completion" in normalized
    assert "Do not say completion was published to other users" in normalized


def test_review_requested_resume_does_not_imply_review_completion():
    update_skill = _read("src/skills/evaluations/update/SKILL.md")
    normalized = " ".join(update_skill.split())

    assert "Review state and review activity are separate" in update_skill
    assert "does not prove that another user has received" in normalized
    assert "Never route a normal or resumed push into review completion" in normalized
    assert "Enter this gate only when the current interaction originated" in normalized
    assert "Do not enter it during Flow R1" in normalized
    assert "must resume promotion/push with the existing tag" in normalized
    assert "Do not offer **Mark review complete**" in update_skill
    assert "already `review_requested`, do not ask again" in normalized
    assert "same scoped push workflow" in normalized


def test_review_next_action_reconciles_local_and_deployed_status():
    update_skill = _read("src/skills/evaluations/update/SKILL.md")
    review_skill = _read("src/skills/evaluations/review/SKILL.md")
    normalized_update = " ".join(update_skill.split())
    normalized_review = " ".join(review_skill.split())

    assert "Review-state reconciliation" in update_skill
    assert "`localStatus` - the desired working change" in normalized_update
    assert "`deployedStatus` - the latest pulled" in normalized_update
    assert "`push_review_request`" in update_skill
    assert "`push_review_completion`" in update_skill
    assert "Never derive these actions from `localStatus` alone" in normalized_update
    assert "localStatus` and `deployedStatus` are both" in normalized_review
    assert "nextAction=push_review_request" in review_skill


def test_review_tagging_explains_collaboration_meaning():
    update_skill = _read("src/skills/evaluations/update/SKILL.md")
    normalized = " ".join(update_skill.split())
    assert "**Mark for review** indicates" in update_skill
    assert "inspect and provide feedback, suggestions, or" in update_skill
    assert "The maker remains responsible for editing the test set" in update_skill
    assert "tag must be pushed to Copilot Studio before it is shared" in normalized
    assert "Native push uploads the test-set YAML but retains review status" in normalized
    assert "do not add a native review-persistence or in-place-update prerequisite" in normalized.lower()


def test_named_update_filters_candidates_before_selection():
    update_skill = _read("src/skills/evaluations/update/SKILL.md")

    assert 'evaluation_review.py --list-all --query "{user text}"' in update_skill
    assert "Do not silently choose a fuzzy match" in update_skill


def test_run_prompt_and_skill_cover_start_history_and_results():
    run_prompt = _read(".github/prompts/run.prompt.md")
    evaluate_prompt = _read(".github/prompts/evaluate.prompt.md")
    run_skill = _read("src/skills/evaluations/run/SKILL.md")
    normalized_run_skill = " ".join(run_skill.split())

    assert "src/skills/evaluations/run/SKILL.md" in run_prompt
    assert "**run** / **execute test sets**" in evaluate_prompt
    assert "evaluation_runs.py list-sets" in run_skill
    assert "evaluation_runs.py run" in run_skill
    assert "no local run mapping is" in run_skill
    assert "evaluation_runs.py list-runs" in run_skill
    assert "evaluation_runs.py results" in run_skill
    assert "joins each run's `testSetId`" in normalized_run_skill
    assert "Mandatory user-selection gate" in run_skill
    assert "two separate user turns" in run_skill
    assert "Stop after asking, even" in run_skill
    assert "candidate discovery and execution must occur in" in run_prompt
    assert "discovery and execution require separate user turns" in evaluate_prompt


def test_evaluation_validator_uses_exact_set_folder():
    validator = _read("src/skills/evaluations/validate/SKILL.md")
    script = _read("scripts/evaluate_evals.py")

    assert '--evaluation-folder "{set-folder}"' in validator
    assert "Do not reconstruct it from the display name" in validator
    assert "--evaluation-folder" in script
    assert "resolve_evaluation_folder" in script
    assert "Automated scoring failed ({reason})" in validator


def test_evaluation_validator_recovers_auth_before_manual_fallback():
    validator = _read("src/skills/evaluations/validate/SKILL.md")
    normalized = " ".join(validator.split())
    script = _read("scripts/evaluate_evals.py")

    assert "status=authentication_required" in validator
    assert "Do not perform manual scoring yet" in normalized
    assert "Sign in or switch GitHub account and retry automated scoring" in validator
    assert "Continue with manual scoring" in validator
    assert "gh auth status --hostname github.com" in validator
    assert "gh auth switch --hostname github.com --user" in validator
    assert "gh auth login --hostname github.com --web" in validator
    assert "gh auth refresh --hostname github.com" in validator
    assert "gh api --hostname github.com user --jq .login" in validator
    assert "`authenticationRetry=true`" in validator
    assert "`manualFallbackAuthorized=true`" in validator
    assert '`fallbackReason="{reason}"`' in validator
    assert "Skip Step 1 and begin at Step 2" in normalized
    assert "explicitly selected manual scoring or declined authentication" in normalized
    assert "Incomplete login, installation, restart, or identity verification never" in normalized
    assert "Do not launch either interactive browser command" in normalized
    assert "restart VS Code and resume the same selected set" in normalized
    assert "Do not retry in the current agent process" in normalized
    assert "Never enter an authentication loop" in validator
    assert "environment variable takes precedence" in validator
    assert "never unset or replace it without the user's action" in normalized
    assert "stdout is one JSON object" in normalized
    assert "Exit code `2` remains argparse usage failure" in normalized
    assert "AUTHENTICATION_REQUIRED_EXIT = 3" in script
    assert '"status": "authentication_required"' in script


def test_catalogue_generation_mandatorily_invokes_validation_subagent():
    generate_skill = _read("src/skills/evaluations/generate/SKILL.md")
    experience = _normalized("src/skills/evaluations/experience-contract.md")

    assert "Invoke `runSubagent` for each generated set" in generate_skill
    assert "evaluate_evals.py --evaluation-folder" in generate_skill
    assert "do not skip validation" in generate_skill
    assert "Keep the complete quality report separate" in experience
    assert "quality-fix-flow.md" in experience


def test_catalogue_generation_previews_prompts_and_csv_before_validation():
    generate_skill = _read("src/skills/evaluations/generate/SKILL.md")

    preview = generate_skill.index(
        "## Step 6: Present the generated preview before validation"
    )
    validation = generate_skill.index("## Step 7: Quality validation")
    assert preview < validation
    assert "Prompt / Expected Response" in generate_skill
    assert 'evaluation_presentation.py --evaluation-folder "{set-folder}" --list-rows' in generate_skill
    assert "CSV is provided for preview and sharing" in generate_skill
    assert "{YYYYMMDD}_{Confirmed_Set_Name}.csv" in generate_skill


def test_update_shows_preview_csv_before_detailed_cases():
    update_skill = _read("src/skills/evaluations/update/SKILL.md")
    normalized_update_skill = " ".join(update_skill.split())

    csv_preview = normalized_update_skill.index(
        "show the downloadable CSV link first"
    )
    case_table = normalized_update_skill.index(
        "| # | Input | Expected output | File |"
    )
    assert csv_preview < case_table
    assert "The CSV file is for preview purposes only" in update_skill
    assert "automatically reflected in the CSV" in update_skill


def test_run_ux_sets_duration_and_evidence_based_result_analysis():
    run_skill = _read("src/skills/evaluations/run/SKILL.md")
    run_prompt = _read(".github/prompts/run.prompt.md")
    evaluate_prompt = _read(".github/prompts/evaluate.prompt.md")
    normalized_run_skill = " ".join(run_skill.split())

    assert "This may take 10-15" in normalized_run_skill
    assert "Return here to view the results" in normalized_run_skill
    assert "you don't" in normalized_run_skill
    assert "need to open Copilot Studio" in normalized_run_skill
    assert "Copy `userGuidance` verbatim" in normalized_run_skill
    assert "hard postcondition" in normalized_run_skill
    assert "copy its `userGuidance` field verbatim" in run_prompt
    assert "direction to return to chat are mandatory" in evaluate_prompt
    assert "do not route results to a separate" in run_skill
    assert "**Results by scenario group**" in run_skill
    assert "rather than inventing categories" in normalized_run_skill


def test_all_evaluation_flows_use_date_first_csv_names():
    create_skill = _read("src/skills/evaluations/create/SKILL.md")
    generate_skill = _read("src/skills/evaluations/generate/SKILL.md")
    update_skill = _read("src/skills/evaluations/update/SKILL.md")

    assert "{YYYYMMDD}_{Evaluation_Set_Display_Name}.csv" in create_skill
    assert "{YYYYMMDD}_{Confirmed_Set_Name}.csv" in generate_skill
    assert "{YYYYMMDD}_{Evaluation_Set_Display_Name}.csv" in update_skill


def test_unpushed_sets_explain_state_without_requiring_separate_push():
    experience = _normalized("src/skills/evaluations/experience-contract.md")
    assert "saved locally, but are not shared" in experience
    assert "Run or Request Review will publish" in experience
    assert "Do not claim local save, promotion, dry run, push, or run are equivalent" in experience
    for flow in ("create", "generate", "update"):
        skill = _normalized(f"src/skills/evaluations/{flow}/SKILL.md")
        assert "local-only reminder" in skill
        assert '**"push {set name}"** when you are ready' not in skill
