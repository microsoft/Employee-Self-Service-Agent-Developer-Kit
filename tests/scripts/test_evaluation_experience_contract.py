from pathlib import Path
import re

import pytest
import yaml


SOLUTION_ROOT = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills"


def _read(path):
    return (SOLUTION_ROOT / path).read_text(encoding="utf-8")


def _skill(flow):
    return _read(f"src/skills/evaluations/{flow}/SKILL.md")


def _normalized(text):
    return " ".join(re.sub(r"(?m)^\s*>\s?", "", text).split())


def _contract(name):
    return _read(f"src/skills/evaluations/{name}.md")


def test_preview_retains_all_rows_and_semantic_grouping():
    text = _normalized(_contract("experience-contract"))
    for fragment in (
        "--list-rows",
        "actual input, assertion, and source context",
        "not filename substrings",
        "--in-scope",
        "--out-of-scope",
        "--other-negative",
        "including identical prompts with different assertions",
        "multiline content",
        "never truncated tables",
        "Do not add server fields",
        "generate_set_csv",
        "actual returned path",
        "| Prompt | Expected Response |",
    ):
        assert fragment in text
    assert "hand-written CSV" in text
    assert "Omit a group flag; retain in Additional cases" in text
    assert "never assign a row to two groups" in text.lower()


@pytest.mark.parametrize("flow", ["create", "generate"])
def test_generation_explains_coverage_after_confirmation_before_generation(flow):
    text = _skill(flow)
    marker = "## Step 3: Generate Evaluation Files" if flow == "create" else "## Step 4: Generate cases"
    before_generation = text.split(marker)[0]
    assert "experience-contract.md" in before_generation
    assert "Before generating cases" in _normalized(before_generation)
    assert "confirm" in before_generation.lower()
    contract = _normalized(_contract("experience-contract"))
    assert "when configured for that scenario" in contract
    assert "out-of-scope and imperfectly worded" in contract
    assert "The owning generator, not the dispatcher" in contract
    assert "only views" in contract


@pytest.mark.parametrize("flow", ["create", "generate"])
def test_generated_quality_report_uses_exact_compact_scorecard(flow):
    text = _normalized(_skill(flow))
    assert "Post-generation quality report" in text
    assert "quality-fix-flow.md" in text
    assert "separate validation progress message or preamble" in text
    assert "Do not add a table" in text

    contract = _contract("experience-contract")
    ordered_fragments = (
        "I ran a quality report to make sure this eval follows best practices",
        "We're reviewing how effectively your test set covers positive, negative, "
        "and boundary scenarios. This is a review of the test set itself, not "
        "confirmation that the tests will work in your tenant. You'll get that "
        "information from running the eval set in your tenant.",
        "OVERALL EVAL QUALITY: {overall}/5 {overall-label}",
        "Positive: {positive-count} | Boundary: {boundary-count} | "
        "Negative: {negative-count} | Total: {total-count}",
        "Validity          {validity-bar}",
        "Realism           {realism-bar}",
        "Assertion Quality {assertion-quality-bar}",
        "Coverage          {coverage-bar}",
        "Diversity         {diversity-bar}",
        "Redundancy        {redundancy-bar}",
        "Failure Modes     {failure-modes-bar}",
        "Discriminative    {discriminative-bar}",
        "What to improve (optional)",
        "⚠ This test set is local only.",
    )
    positions = [contract.index(fragment) for fragment in ordered_fragments]
    assert positions == sorted(positions)
    scorecard_start = contract.index(ordered_fragments[0])
    scorecard = contract[scorecard_start:contract.index("```", scorecard_start)]
    for duplicate_prompt in (
        "NEXT STEPS:",
        "Do you want to mark this test set ready for review",
        "Are you ready to run this test set",
        "Do you want to further edit this test set",
        "Do you want to do another quality review",
    ):
        assert duplicate_prompt not in scorecard
    assert "structured question control" in contract
    assert "only place these options appear" in contract
    assert "Do not ask the same question in prose" in contract
    assert "always five blocks total" in _normalized(contract)
    assert "• No improvements suggested." in contract
    assert "three counts must sum to Total" in contract
    assert "not that the agent will pass" in contract


def test_validator_maps_full_rubric_names_without_expanding_scorecard():
    text = _normalized(_skill("validate"))
    assert "Post-generation quality report" in text
    assert "Failure Mode Coverage" in text
    assert "Discriminative Power" in text
    assert "does not add a ninth scorecard line" in text
    assert "do not append them to the compact maker-facing scorecard" in text
    assert "Never repeat those case tables" in text
    assert "Return only the compact scorecard" in text


@pytest.mark.parametrize("flow", ["create", "generate"])
def test_quality_validation_never_repeats_generated_case_tables(flow):
    text = _normalized(_skill(flow))
    assert "appear once only" in text
    assert "never repeat them during or after quality validation" in text
    assert "show only those changed rows" in text

    contract = _normalized(_contract("experience-contract"))
    assert "Never repeat an unchanged generated-case table" in contract
    assert "quality validation must not reproduce" in contract
    assert "Render only this scorecard" in contract


def test_topic_preview_precedes_quality_review_and_menu():
    text = _skill("create")
    write = text.index("### 4.2")
    preview = text.index("**Generated-case preview**", write)
    quality = text.index("### 4.3", write)
    actions = text.index("### 4.4", quality)
    assert write < preview < quality < actions
    assert "Do not present the action menu yet" in text[preview:quality]


@pytest.mark.parametrize("flow", ["create", "generate"])
def test_returning_generation_offers_exact_set_edit_add_without_regeneration(flow):
    text = _normalized(_skill(flow))
    assert "evaluation_review.py --list-all" in text
    assert "**Edit this existing set**" in text
    assert "**Add test cases to this set**" in text
    assert "**Keep it unchanged**" in text
    assert "arbitrary slugs" in text
    assert "overflow" in text
    assert "src/skills/evaluations/update/SKILL.md" in text
    assert "exact" in text and "source" in text
    assert "replacement" in text.lower() and "approval" in text.lower()


def test_dispatcher_handles_existing_edit_before_new_scenario():
    text = _skill("dispatcher")
    assert text.index("existing-set edit/add request") < text.index("Extract the scenario")
    assert "never regenerate to reach editing" in _normalized(text)
    assert "Do not duplicate it here" in text


def test_append_uses_authoring_helper_and_preserves_case_identity():
    text = _normalized(_skill("update"))
    for fragment in (
        "**Add test cases to this set**",
        "does not require selecting an old case",
        "evaluation_authoring.py add",
        '--evaluation-folder "{set-folder}"',
        '--input "{new prompt}"',
        '--expected-output "{new expected response}"',
        "file plus row index",
        "Preserve duplicate inputs",
        "100 cases",
        "before writes",
        "do not add the same case again",
        "validate_evaluation_documents",
        "Preserve parent identity",
    ):
        assert fragment in text


@pytest.mark.parametrize(
    ("flow", "thresholds"),
    [("create", [0.7, 0.5]), ("generate", [0.7])],
)
def test_all_active_generation_parent_templates_are_compare_meaning_only(flow, thresholds):
    documents = [
        yaml.safe_load(block)
        for block in re.findall(r"```yaml\n(.*?)```", _skill(flow), re.DOTALL)
    ]
    parents = [doc for doc in documents if doc.get("kind") == "EvaluationSet"]
    assert len(parents) == len(thresholds)
    assert [doc["graders"] for doc in parents] == [
        [{"kind": "CompareMeaningGrader", "threshold": threshold}]
        for threshold in thresholds
    ]
    cases = [doc for doc in documents if doc.get("kind") == "EvaluationData"]
    assert cases
    assert all(row["input"].strip() and row["expectedOutput"].strip()
               for doc in cases for row in doc["rows"])
    assert all(doc.get("kind") != "MultiTurnEvaluationCase" for doc in documents)


@pytest.mark.parametrize("flow", ["create", "generate"])
def test_new_generation_admission_does_not_convert_multiturn_or_missing_assertions(flow):
    text = _normalized(_skill(flow))
    assert "evaluation_method_policy.py" in text
    assert "validate_evaluation_documents" in text
    assert "before writing" in text
    assert "multi-turn" in text
    assert "never silently flatten" in text.lower()
    assert "expected response" in text.lower()
    assert "0.7" in text and "100" in text


def test_unsupported_method_copy_is_concise_and_editable():
    contract = _normalized(_contract("experience-contract"))
    assert (
        "The eval skill currently only supports **Compare Meaning**. "
        "You can still edit the prompts and expected responses."
    ) in contract
    assert "I haven't changed the test method" not in contract


def test_catalogue_positive_budget_and_split_grader_are_preserved():
    text = _normalized(_skill("generate"))
    assert "**21**" in text
    assert "2 boundary + 2 negative" in text
    assert "stricter 21-positive family split" in text
    assert "each with exactly one CompareMeaningGrader" in text


@pytest.mark.parametrize("flow", ["create", "generate"])
def test_out_of_scope_generation_distinguishes_scenario_and_agent_boundaries(flow):
    text = _normalized(_skill(flow))
    assert "Outside this scenario" in text
    assert "supported elsewhere" in text or "valid ESS" in text
    assert "not refuse" in text or "not decline" in text
    assert "travel" in text
    assert "domain across" in text or "different domains" in text

    contract = _normalized(_contract("experience-contract"))
    assert "outside the selected scenario but grounded in another configured" in contract
    assert 'outside this evaluation goal" with "unsupported by the agent' in contract


def test_csv_only_sync_uses_strict_cli_and_returned_path():
    contract = _normalized(_contract("experience-contract"))
    assert 'evaluation_csv.py --evaluation-folder "{set-folder}" --exports-folder "{exports-folder}"' in contract
    assert "returned JSON `csv` field" in contract
    assert "default `strict=True`" in contract
    assert "Never pass `strict=False`" in contract
    assert "at least one and at most 100 rows" in contract
    for flow in ("create", "generate", "update"):
        text = _normalized(_skill(flow))
        assert "evaluation_csv.py --evaluation-folder" in text
        assert "csv" in text and "strict" in text.lower()


def test_deployment_binds_confirmation_to_real_helper_and_selected_action():
    text = _normalized(_contract("deployment-flow"))
    for fragment in (
        "evaluation_deployment.py preview",
        "evaluation_deployment.py deploy",
        '--set-folder "{set-folder}"',
        '--confirmation-token "{confirmationToken}" --yes',
        "`request-review`, `run`, and `push`",
        "status=ready",
        "status=pushed",
        "status=up_to_date",
        "preview and confirm again",
        "do not call `deploy` separately",
        "evaluation_runs.py run-prepared",
        "Never reuse the pre-marker token",
        "deployedReviewStatus=review_completed",
        "deployedReviewStatus=review_requested",
        "`promotion.required`, `promotion.replacesLocalFiles`, and `promotion.changes`",
        "Even when `requiresPush=false`, continue through `deploy`",
        "A preview alone is not synchronization proof",
        "`remoteCommitted=true`",
        "`deploymentMayHaveCommitted`",
        "never blindly repeat the remote write",
    ):
        assert fragment in text


def test_request_review_selection_authorizes_immediate_push():
    deployment = _normalized(_contract("deployment-flow"))
    update = _normalized(_skill("update"))
    experience = _normalized(_contract("experience-contract"))

    for fragment in (
        "selected Request Review action authorizes its required non-destructive",
        "deploy it immediately without showing a separate scope confirmation",
        '--action "request-review" --confirmation-token "{confirmationToken}" --yes',
        "Request Review does not pause for confirmation",
        "destructive Dataverse deletions",
        "replacement of different local files",
    ):
        assert fragment in deployment
    assert "do not ask for another confirmation" in update
    assert "Flow R1 pushes immediately without another confirmation" in update
    assert "selection authorizes its immediate non-destructive push" in experience


def test_request_review_and_reviewer_completion_remain_separate():
    update = _normalized(_skill("update"))
    assert "helper action `request-review`" in update
    assert "no notification/run claim" in update
    assert "Flow R2" in update and "Do not enter it during Flow R1" in update
    assert "**Provide more feedback**" in update
    assert "retaining all earlier feedback" in update
    assert "same workflow" in update
    deployment = _normalized(_contract("deployment-flow"))
    assert 'evaluation_review.py --set-folder "{set-folder}" --status review_completed' in deployment
    assert "ordinary explicit push must never perform this marker step" in deployment.lower()
    for flow in ("update", "review"):
        text = _normalized(_skill(flow))
        assert "`reviewMetadataPersisted=false`" in text
        assert "`deployedReviewStatus=null`" in text
        assert "`reviewWarning`" in text


def test_native_deployment_reuses_existing_insert_with_action_aware_consent():
    text = _normalized(_contract("deployment-flow"))
    for fragment in (
        "`BotComponentInsert`: new or changed YAML creates a new deployed copy",
        "Unchanged YAML, including local review-only changes, uses verified reuse",
        "Do not require a new in-place update/delete API",
        "A sidecar or modified native set is not itself a deployment blocker",
        "For native previews used by Run, explicit push, or reviewer completion, "
        "show `deploymentBehavior` before consent",
        "`new_copy`",
        "old remote copy will be retained",
        "removed cases are absent only from the new copy, not deleted from the old set",
        "`reuse` means the helper will verify the existing mapped copy",
        "not case omissions in a native new copy",
        "Native `--force-delete` remains rejected",
        "pending insertion retry retain their verified or confirmed planned IDs",
        "Do not convert that existing limitation into a failed push",
        "python scripts/analytics_pointer.py --post-deploy",
        "one-time reminder",
        "DA environment/agent association",
    ):
        assert fragment in text
    run = _normalized(_skill("run"))
    assert "For native `deploymentBehavior=new_copy`, explain before consent" in run
    assert "Start only the actual ID returned by preparation" in run
    assert "Native local completion is not a remote review marker" in run
    assert "Never clear a pending tag to run" in run
    assert "`currentlyRunnable=null` means readiness is unknown" in run


def test_review_outcomes_preserve_dataverse_metadata_without_native_parity_claims():
    deployment = _normalized(_contract("deployment-flow"))
    assert "Dataverse `push.py` persists `review.json` in the evaluation-parent description" in deployment
    assert "Native `review.json` remains in the selected local/promoted folder" in deployment
    assert "confirmed plan fingerprint, not the deployed `.baseline`" in deployment
    assert "native metadata-only changes: verify YAML reuse, retain local review intent" in deployment
    assert "Render the returned warning verbatim" in deployment
    assert (
        "Existing native Push uploads evaluation YAML only. review.json stays local "
        "and is not published as shared review state."
    ) in deployment
    assert "success reports `reviewMetadataPersisted=true`" in deployment
    assert "Native success reports `reviewMetadataPersisted=false` and `deployedReviewStatus=null`" in deployment
    update = _normalized(_skill("update"))
    assert "After verified Dataverse success with `reviewMetadataPersisted=true`" in update
    assert "For native success with `reviewMetadataPersisted=false`, say instead" in update
    assert "shared review state was not published" in update
    assert "do not promise cross-user discovery" in update.lower()
    review = _normalized(_skill("review"))
    assert "**Review requested locally**" in review
    assert "do not block the existing local review workflow" in review
    assert "completion is local, not published to other users" in review
    experience = _normalized(_contract("experience-contract"))
    assert "not new blockers or additional maker actions" in experience


def test_native_local_review_does_not_require_unpublished_baseline_state():
    review = _normalized(_skill("review"))
    assert "For native local review, use the existing local-inclusive discovery instead" in review
    assert "evaluation_review.py --list-all" in review
    assert "Select returned rows with `localStatus=review_requested`" in review
    assert "not deployed `.baseline`" in review
    assert "or matching `deployedStatus`/`nextAction=review`" in review
    update = _normalized(_skill("update"))
    assert "In an active Dataverse Flow R2 review, require `nextAction=review`" in update
    assert "For native local review, require explicit selection from the local requested rows instead" in update
    assert "A local requested marker keeps Run blocked" in update
    assert "explicit local completion can proceed through verified YAML push/reuse" in update


def test_public_guidance_records_existing_api_scope_not_native_parity_blockers():
    readme = _normalized(_read("README.md"))
    assert "These flows use the existing push APIs" in readme
    assert "new copy with a new deployed ID" in readme
    assert "not published as shared review metadata" in readme
    assert "same flow and report this limitation" in readme


def test_integrated_run_preserves_selection_connection_and_token_gates():
    text = _normalized(_skill("run"))
    for fragment in (
        "two separate user turns",
        "list-sets --include-local",
        "`canPrepare`",
        "`currentlyRunnable`",
        "never silently choose a fuzzy match",
        "Require explicit connection selection, even if only one profile exists",
        "evaluation_deployment.py preview",
        "--action run",
        "evaluation_runs.py run-prepared",
        '--confirmation-token "{confirmationToken}" --yes',
        '--mcs-connection-id "{connectionId}"',
        "Do not also call",
        "do not repeat deployment blindly",
    ):
        assert fragment.lower() in text.lower()
    assert "use it automatically" not in text


def test_start_link_is_immediate_truthful_and_keeps_guidance():
    text = _normalized(_skill("run"))
    assert "[Open this run in Copilot Studio]({agentStudioUrl}) (optional)" in text
    assert "Copy `userGuidance` verbatim" in text
    assert "10-15 minutes" in text
    assert "Return here to view the results" in text
    assert "you don't need to open Copilot Studio" in text
    assert "no valid run ID" in text
    assert "do not fabricate a url" in text.lower()
    assert "retry start for navigation" in text
    assert "`navigationWarning`" in text
    assert "Native HTTP 202 means accepted, not completed" in text
    assert "Done. I ran your test set through [Copilot Studio]({agentStudioUrl})" in text


def test_completed_run_results_use_decision_ready_report_format():
    text = _skill("run")
    normalized = _normalized(text)
    ordered_fragments = (
        "Done. I ran your test set through [Copilot Studio]({agentStudioUrl}).",
        "**Eval run complete — {passed} of {total} passed, {failed} failed "
        "({pass-rate}%)**",
        "Verdict: {verdict against the stated target}",
        "**Results by scenario group**",
        "| Group | Cases | Pass | Fail | Pass rate |",
        "**Expected failures**",
        "**Failure analysis — grouped by root cause**",
        "| # | Root cause category | Cases | Owner | Suggested action | "
        "Representative evidence |",
        "📌 Pattern:",
        "**Who needs to do what**",
        "• Gate:",
    )
    positions = [text.index(fragment) for fragment in ordered_fragments]
    assert positions == sorted(positions)
    for fragment in (
        "No failures were explicitly marked as expected for this run.",
        "evidence-based root-cause hypothesis",
        "Never invent an owner",
        "consolidate actions by returned owner",
        "do not append another detailed-results table",
        "fallback rather than inventing categories",
        "95% is the reporting target, not an API-provided threshold",
    ):
        assert fragment.lower() in normalized.lower()


def test_both_backends_require_discovered_explicit_connection_and_truthful_failure():
    text = _normalized(_skill("run"))
    assert "For both Dataverse and native MinimalBot agents, run:" in text
    assert "evaluation_runs.py list-connections" in text
    assert "`matchesSignedInAccount` is context, not permission to select automatically" in text
    assert "Missing, disconnected, or unverified selected profiles block both backends" in text
    assert "`list-connections` is not supported" not in text
    assert "`stage=deployment` is not run success" in text
    assert "`status=run_failed`, `stage=run`" in text
    assert "recovery `userGuidance`, not a success link" in text


def test_entry_prompts_preserve_explicit_push_without_general_deployment_override():
    push = _read(".github/prompts/push.prompt.md")
    assert push.index("## Explicit evaluation push") < push.index("## General component push")
    assert "evaluation_deployment" not in push  # Shared guide owns the CLI.
    assert "deployment-flow.md" in push
    assert "python scripts/analytics_pointer.py --post-deploy" in push
    assert "--show" not in push
    assert "only after deployment verification" in push
    assert "do not substitute the Copilot Studio home page" in push
    assert "Do NOT add `--yes`" in push.split("## General component push", 1)[1]
    assert "never launch an interactive evaluation push" in _normalized(push).lower()
    update = _normalized(_read(".github/prompts/update.prompt.md"))
    assert "For **topic and workflow updates only**" in update
    assert "This restriction does not apply to evaluation operations" in update
    evaluate = _normalized(_read(".github/prompts/evaluate.prompt.md"))
    assert "**quality review** / **Run another quality review**" in evaluate
    assert "agentStudioUrl" in evaluate
    run = _normalized(_read(".github/prompts/run.prompt.md"))
    assert "run-prepared" in run and "userGuidance" in run and "agentStudioUrl" in run
