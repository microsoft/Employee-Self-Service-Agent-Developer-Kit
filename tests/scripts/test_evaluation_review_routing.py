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


def test_generic_tag_request_requires_all_sets_and_explicit_selection():
    update_skill = _read("src/skills/evaluations/update/SKILL.md")

    assert "evaluation_review.py --list-all" in update_skill
    assert "Display every returned workspace and configured-agent test set" in update_skill
    assert "Wait for an explicit selection" in update_skill
    assert "Do not infer a selection from the previous conversation" in update_skill
    assert "structured choice control" in update_skill


def test_maker_is_offered_edit_review_or_keep_choices():
    create_skill = _read("src/skills/evaluations/create/SKILL.md")
    generate_skill = _read("src/skills/evaluations/generate/SKILL.md")
    update_skill = _read("src/skills/evaluations/update/SKILL.md")
    normalized_generate = " ".join(generate_skill.split())

    assert "**Edit the test sets myself**" in create_skill
    assert "**Send them to a judge or SME for feedback**" in create_skill
    assert "**Push without requesting review**" in create_skill
    assert "**Edit the test set myself**" in generate_skill
    assert "**Prepare it to send to a judge or SME for feedback**" in generate_skill
    assert "**Edit the test set myself**" in update_skill
    assert "**Send it to a judge or SME for feedback**" in update_skill
    assert "**Keep it unchanged**" in update_skill
    assert "closing question is mandatory" in create_skill
    assert "closing question is mandatory" in normalized_generate


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
    normalized_update_skill = " ".join(update_skill.split())
    assert '--only "evaluations/{set}/*" --dry-run' in update_skill
    assert '--only "evaluations/{set}/*" --yes' in update_skill
    assert '--yes --force-delete' in update_skill
    assert "Never use an unscoped" in update_skill
    assert ".baseline/evaluations/{set}/" in update_skill
    assert "pushing a replacement will delete those cases" in update_skill
    assert "unrelated local topic or workflow deletions" in update_skill
    assert "evaluation_promotion.py promote" in update_skill
    assert "evaluation_promotion.py cleanup" in update_skill
    assert "Do not manually delete promotion paths" in normalized_update_skill


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
    assert "when this push records `review_completed`" in update_skill
    assert "You can now run this test set" in update_skill


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


def test_catalogue_generation_mandatorily_invokes_validation_subagent():
    generate_skill = _read("src/skills/evaluations/generate/SKILL.md")
    copilot_instructions = _read(".github/copilot-instructions.md")

    assert "Invoke `runSubagent` for each generated set" in generate_skill
    assert "evaluate_evals.py --evaluation-folder" in generate_skill
    assert "do not skip validation" in generate_skill
    assert "catalogue-grounded eval generate flow" in copilot_instructions
    assert "whether or not the requested scenario matched" in copilot_instructions


def test_catalogue_generation_previews_prompts_and_csv_before_validation():
    generate_skill = _read("src/skills/evaluations/generate/SKILL.md")

    preview = generate_skill.index(
        "## Step 6: Present the generated preview before validation"
    )
    validation = generate_skill.index("## Step 7: Quality validation")
    assert preview < validation
    assert "show the generated golden prompts grouped" in generate_skill
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

    assert "return in 10-15 minutes" in run_skill
    assert "Copy `userGuidance` verbatim" in normalized_run_skill
    assert "hard postcondition" in normalized_run_skill
    assert "copy its `userGuidance` field verbatim" in run_prompt
    assert "10-15-minute wait notice is mandatory" in evaluate_prompt
    assert "do not route results to a separate" in run_skill
    assert "**Results by scenario group**" in run_skill
    assert "**Failure analysis - grouped by observed cause**" in run_skill
    assert "rather than inventing categories" in normalized_run_skill
    assert "Never invent an owner" in normalized_run_skill


def test_all_evaluation_flows_use_date_first_csv_names():
    create_skill = _read("src/skills/evaluations/create/SKILL.md")
    generate_skill = _read("src/skills/evaluations/generate/SKILL.md")
    update_skill = _read("src/skills/evaluations/update/SKILL.md")

    assert "{YYYYMMDD}_{Evaluation_Set_Display_Name}.csv" in create_skill
    assert "{YYYYMMDD}_{Confirmed_Set_Name}.csv" in generate_skill
    assert "{YYYYMMDD}_{Evaluation_Set_Display_Name}.csv" in update_skill


def test_unpushed_evaluation_sets_require_reviewer_handoff_reminder():
    generate_skill = _read("src/skills/evaluations/generate/SKILL.md")
    update_skill = _read("src/skills/evaluations/update/SKILL.md")
    create_skill = _read("src/skills/evaluations/create/SKILL.md")

    reminder = "To make this test set available to an authorized judge or SME"
    assert reminder in generate_skill
    assert reminder in update_skill
    assert "Copying the set into the configured agent's local" in generate_skill
    assert "Remove it only after" in update_skill
    assert "not available to another authorized" in create_skill
    assert "available to authorized judges and SMEs" in create_skill
    assert "initial setup" not in generate_skill
    assert "next refresh" not in update_skill
