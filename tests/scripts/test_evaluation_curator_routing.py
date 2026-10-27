from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLUTION_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills"


def _read(relative_path: str) -> str:
    return (SOLUTION_ROOT / relative_path).read_text(encoding="utf-8")


def _normalized(relative_path: str) -> str:
    return " ".join(_read(relative_path).split())


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start) : text.index(end)]


def _assert_terms(text: str, *terms: str) -> None:
    missing = [term for term in terms if term not in text]
    assert not missing, f"Missing contract terms: {missing}"


def test_dispatcher_routes_local_knowledge_before_topic_matching():
    dispatcher = _read("src/skills/evaluations/dispatcher/SKILL.md")
    normalized = " ".join(dispatcher.split()).lower()

    assert "src/skills/evaluations/curate/SKILL.md" in dispatcher
    assert '"curate from a knowledge source"' in normalized
    assert "even when neither required path was supplied" in normalized
    assert "route immediately" in normalized
    assert "local knowledge source" in normalized
    assert "connected knowledge base" in normalized
    assert "agent-instructions file" in normalized
    assert dispatcher.index("src/skills/evaluations/curate/SKILL.md") < (
        dispatcher.index("### Matching topic found")
    )
    assert dispatcher.index("src/skills/evaluations/curate/SKILL.md") < (
        dispatcher.index("Which scenario or goal should I create evaluation tests for?")
    )


def test_curator_wrapper_resolves_and_confirms_connected_kb_connection():
    wrapper_text = _read("src/skills/evaluations/curate/SKILL.md")
    wrapper = " ".join(wrapper_text.split())
    normalized_lower = wrapper.lower()

    # Resolver shim runs ahead of the vendored curator body's Step 3b.
    assert "scripts/resolve_kb_connection.py" in wrapper
    assert "before proceeding into the curator body's step 3b" in normalized_lower
    assert wrapper.index("scripts/resolve_kb_connection.py") < wrapper.index(
        "existing Step 3b/3c flow"
    )

    # Error and none_bound both stop the flow and report the specific reason,
    # with no automatic fallback to local-file mode.
    assert '`status == "error"`' in wrapper
    assert '`status == "none_bound"`' in wrapper
    assert "stop and report" in normalized_lower
    assert "automatically switch to local" not in normalized_lower
    assert "automatically fall back to local" not in normalized_lower
    assert "must not silently fall back to local-file mode" in normalized_lower
    assert "restart mode selection" in normalized_lower

    # Single resolved connection requires explicit maker confirmation.
    assert '`status == "ok"`' in wrapper
    assert "exactly one connection" in normalized_lower
    assert "require" in normalized_lower and "explicit confirmation" in normalized_lower

    # Multiple resolved connections require the maker to pick one or more.
    assert "more than one connection" in normalized_lower
    assert "list all of them" in normalized_lower
    assert "pick one or more" in normalized_lower


def test_curator_wrapper_resolves_and_confirms_agent_instructions():
    wrapper_text = _read("src/skills/evaluations/curate/SKILL.md")
    wrapper = " ".join(wrapper_text.split())
    normalized_lower = wrapper.lower()

    # Step 1 resolves live agent instructions via the CLI shim instead of
    # asking the maker for an agent-instructions file.
    assert "scripts/resolve_agent_instructions.py" in wrapper
    assert "ask exactly one question for the agent instructions" not in normalized_lower
    assert "ask for the agent instructions file" not in normalized_lower

    # status == "ok" requires explicit maker confirmation of the resolved
    # instructions before proceeding.
    assert '`status == "ok"`' in wrapper
    assert "require" in normalized_lower and "explicit confirmation" in normalized_lower
    assert "resolved instructions" in normalized_lower

    # status == "not_found" and status == "error" both stop and report, with
    # no fallback to prompting for a file.
    assert '`status == "not_found"`' in wrapper
    assert '`status == "error"`' in wrapper
    assert "stop and report" in normalized_lower

    # Ordering: the resolver shim runs before the hand-off into the curator
    # body's grounding.
    assert wrapper.index("scripts/resolve_agent_instructions.py") < wrapper.index(
        "Follow the vendored curator skill"
    )


def test_curator_wrapper_defines_bounded_servicenow_retrieval_sequence():
    wrapper = _read("src/skills/evaluations/curate/SKILL.md")
    normalized = " ".join(wrapper.split())
    normalized_lower = normalized.lower()

    resolver = normalized.index("scripts/resolve_kb_connection.py")
    confirmation = normalized_lower.index("maker's confirmation or choice")
    graph_search = normalized.index("scripts/search_connected_kb.py")
    classification = normalized_lower.index("first bounded cli response")
    safe_mapping = normalized_lower.index("verified safe `sys_id` or article-number")
    identity_check = normalized_lower.index("fail-closed source identity check")
    mcp_fetch = normalized.index('get_record( table="kb_knowledge"')
    grounding = normalized_lower.index(
        "ground and generate only after all required canonical mcp content fetches"
    )

    assert resolver < confirmation < graph_search < classification
    assert classification < safe_mapping < identity_check < mcp_fetch < grounding
    _assert_terms(
        wrapper,
        '--connection "{CONFIRMED_CONNECTION_REFERENCE}"',
        '--query "{BOUNDED_QUERY}"',
        '--limit "{BOUNDED_LIMIT}"',
    )
    _assert_terms(
        normalized_lower,
        "parse only the cli's deterministic json",
        "3-5 broad queries",
        "top 5-10 results",
        "one targeted query",
        "top 10-20 results",
    )

    exact_fields = (
        "sys_id,number,short_description,text,"
        "kb_knowledge_base,workflow_state"
    )
    assert f'fields="{exact_fields}"' in wrapper
    assert 'query="numberIN{MAPPED_NUMBERS}"' in wrapper
    assert "limit={MAPPED_NUMBER_COUNT}" in wrapper


def test_curator_wrapper_branches_before_mapping_or_mcp():
    normalized = _normalized("src/skills/evaluations/curate/SKILL.md")
    normalized_lower = normalized.lower()

    classification = normalized_lower.index("first bounded cli response")
    branch_boundary = normalized_lower.index(
        "classification must be resolved before identifier mapping"
    )
    mapping = normalized_lower.index("verified safe `sys_id` or article-number")
    mcp = normalized_lower.index("before any servicenow mcp record fetch")

    assert classification < branch_boundary < mapping < mcp
    _assert_terms(
        normalized_lower,
        "classification is `servicenow`",
        "classification is `ambiguous`",
        "maker-confirmed servicenow",
        "classification is `other`",
        "discard the shim response for grounding",
        "exit this specialization before identifier mapping",
        "generic search/fetch contract unchanged",
        "do not map servicenow identifiers",
        "or invoke servicenow mcp on this branch",
    )


def test_curator_wrapper_fetches_every_safely_mapped_targeted_hit():
    normalized = _normalized("src/skills/evaluations/curate/SKILL.md").lower()

    _assert_terms(
        normalized,
        "each targeted top-10-20 graph result subset",
        "map every returned hit",
        "every such safely mapped hit is selected and must be fetched",
        "do not choose a smaller or more promising subset",
        "only a disclosed unmapped hit or a disclosed individual fetch failure",
    )


def test_curator_wrapper_verifies_servicenow_instance_and_fetch_identity():
    normalized = _normalized("src/skills/evaluations/curate/SKILL.md").lower()

    identity = normalized.index("fail-closed source identity check")
    fetch = normalized.index('get_record( table="kb_knowledge"')
    returned_identity = normalized.index("after each single or batch fetch")
    grounding = normalized.index(
        "ground and generate only after all required canonical mcp content fetches"
    )

    assert identity < fetch < returned_identity < grounding
    _assert_terms(
        normalized,
        "trusted normalized `sourceurl`",
        "exactly one servicenow hostname",
        "configured servicenow mcp instance url",
        "cannot be inspected programmatically",
        "ask the maker to confirm",
        "do not invent or call an mcp identity tool",
        "stop before fetching",
        "/connect servicenow",
        "returned `sys_id` and/or `number`",
        "exactly matches the mapped identifier requested",
        "mismatched requested identifier",
        "do not use that record's content for grounding",
    )


def test_curator_wrapper_forbids_broad_servicenow_fallbacks():
    normalized_lower = _normalized(
        "src/skills/evaluations/curate/SKILL.md"
    ).lower()

    _assert_terms(
        normalized_lower,
        "blank",
        "unscoped",
        "broad `kb_knowledge` queries",
        "title-based lookup",
        "title-based fallback",
        "never broad-search servicenow as a fallback",
    )


def test_curator_wrapper_documents_servicenow_failure_boundaries():
    normalized = _normalized("src/skills/evaluations/curate/SKILL.md")
    normalized_lower = normalized.lower()

    _assert_terms(
        normalized_lower,
        "graph search, authentication, permission, transport, or malformed-response failure",
        "restart in local-file mode",
        "missing, stopped, or unauthenticated servicenow mcp",
        "/connect servicenow",
        "start or fix the configured server",
        "unmapped graph hit",
        "skip it and disclose",
        "individual required record fetch fails",
        "returned-identifier mismatch",
        "remaining bounded subset",
    )


def test_curator_wrapper_preserves_local_and_generic_connected_kb_flows():
    normalized = _normalized("src/skills/evaluations/curate/SKILL.md").lower()

    assert "skip that gate entirely in local-file mode" in normalized
    assert "generic search/fetch contract unchanged" in normalized
    assert "local-file and non-servicenow connected-kb flows remain unchanged" in normalized
    assert "maker kit validation" in normalized
    assert "promotion" in normalized
    assert "scoped push" in normalized


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


def test_curator_wrapper_reads_vendored_files_without_duplication():
    wrapper = _read("src/skills/evaluations/curate/SKILL.md")
    normalized = " ".join(wrapper.split())
    normalized_lower = normalized.lower()

    # Vendored, in-repo curator content — no submodule handshake.
    assert "curator/curate-evals.md" in wrapper
    assert "curator/check_eval_artifacts.py" in wrapper
    assert "read `curator/curate-evals.md` in full" in normalized_lower
    assert (
        "src/skills/evaluations/curate/curator/check_eval_artifacts.py" in wrapper
    )
    # Missing vendored files stop the flow with an actionable error.
    assert "curator is not available in this workspace" in normalized_lower
    # No submodule scaffolding leaks back in.
    assert "git submodule update" not in normalized_lower
    assert "submodule update --init" not in normalized_lower
    assert "eval_curator_submodule" not in wrapper
    assert "skillpath" not in normalized_lower
    assert "host-contract" not in normalized_lower
    assert "never duplicate the curator instructions" in normalized_lower
    assert "active GitHub Copilot session" in wrapper


def test_curator_wrapper_defines_host_parameters_and_mode_selection():
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
    # Wrapper asks the maker to choose local vs connected knowledge base first.
    assert "connected knowledge base" in normalized_lower
    assert "local files" in normalized_lower or "local folder" in normalized_lower
    assert "local-file mode only for v1" not in normalized_lower
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


def test_update_authorizes_every_curator_preselected_set_entry():
    wrapper = _normalized("src/skills/evaluations/curate/SKILL.md")
    update_text = _read("src/skills/evaluations/update/SKILL.md")
    update = " ".join(update_text.split())
    update_lower = update.lower()
    rules = " ".join(
        _section(update_text, "## Rules", "## Review-intent routing").split()
    ).lower()

    for choice in (
        "Edit the test sets myself",
        "Send them to a judge or SME for feedback",
        "Keep them unchanged",
    ):
        assert choice in wrapper
        assert f"**{choice}**" in update

    assert "exact generated workspace set folders already preselected" in update
    assert "enter the edit path at Step 2" in update
    assert "enter Flow R1 with the exact preselected sets" in update
    assert (
        "enter the **Four maker actions** menu from "
        "`src/skills/evaluations/experience-contract.md` with the exact "
        "preselected sets" in update
    )
    assert "without rediscovering or reselecting those sets" in update_lower
    assert "for normal update entries, always discover sets" in rules
    assert "curator-originated preselected-set handoffs are exempt" in rules
    assert "use only the exact folders supplied by the curator skill" in rules
    assert "normalized folder and csv paths returned by" in update_lower
    assert "must receive those paths unchanged" in update_lower


def test_curator_edit_path_returns_to_mandatory_maker_gate():
    wrapper_text = _read("src/skills/evaluations/curate/SKILL.md")
    update_text = _read("src/skills/evaluations/update/SKILL.md")
    wrapper = " ".join(wrapper_text.split())
    update = " ".join(update_text.split())
    wrapper_gate = " ".join(
        _section(
            wrapper_text,
            "## Step 4: Validate, then ask for maker review",
            "Failed or partial validation",
        ).split()
    )
    curator_handoffs = " ".join(
        _section(
            update_text,
            "### Curator-originated preselected-set handoffs",
            "### Review-state reconciliation",
        ).split()
    ).lower()
    assert "Steps 2 through 6" in wrapper
    assert "return to this maker review gate" in wrapper
    assert "This curator gate has already selected the edit path" in wrapper_gate
    assert "skip its generic Edit/SME/Keep continuation question" in wrapper_gate
    assert "enter the edit path at Step 2" in update
    assert "the curator gate already selected the edit path" in curator_handoffs
    assert "show the current csv preview and cases" in curator_handoffs
    assert "skip step 2's generic continuation question" in curator_handoffs
    assert "proceed directly to selecting and editing cases" in curator_handoffs
    assert (
        "return control to the curator skill's mandatory maker review gate"
        in curator_handoffs
    )
    assert "do not fall through to step 6a or step 7" in curator_handoffs

    # The per-set "How would you like to continue with {set}?" question the
    # old architecture duplicated inline in Step 2 is gone: Step 2 now offers
    # only ONE generic continuation surface (the shared Four maker actions
    # menu, or its explicit edit/add variant), which is exactly the thing the
    # curator-handoff text above says to "skip." There is nothing left to
    # duplicate, so the guarantee now lives solely in the handoffs section
    # asserted above.
    step_2 = " ".join(
        _section(
            update_text,
            "## Step 2: Identify the requested changes",
            "## Step 3:",
        ).split()
    )
    assert "If this is an explicit edit/add handoff" in step_2
    assert "Otherwise show **Four maker actions**" in step_2
    assert "Keep/cancel does not mutate or deploy" in step_2


def test_dispatcher_delegates_required_agent_instructions_collection():
    dispatcher = _normalized("src/skills/evaluations/dispatcher/SKILL.md")

    assert "agent-instructions file remains required" in dispatcher
    assert "curator wrapper enforces that requirement" in dispatcher


def test_flow_r1_accepts_curator_preselected_sets_without_reselection():
    update_text = _read("src/skills/evaluations/update/SKILL.md")
    flow_r1 = " ".join(
        _section(
            update_text,
            "### Flow R1 — Tag selected test sets for review",
            "On Dataverse, the pushed parent description contains:",
        ).split()
    )

    assert "When Flow R1 is entered from the curator maker review gate" in flow_r1
    assert "exact generated workspace set folders as already preselected" in flow_r1
    assert "Do not run `evaluation_review.py --list-all`" in flow_r1
    assert "ask the maker to select them again" in flow_r1

    # The old architecture deferred a curator-originated handoff's actual push
    # to a separately-entered "Step 7," entered exactly once regardless of set
    # count. The new architecture has no such deferral: Flow R1 itself follows
    # deployment-flow.md inline (step 5) and persists the review marker (step
    # 6) for every preselected set, repeating that full sequence once per set
    # -- there is no longer a separate curator-only Step 7 hop to gate.
    assert "Continue directly at step 5 for every preselected set" in flow_r1
    assert "repeating steps 5 through 7 once per set" in flow_r1
    curator_entry = flow_r1.index(
        "Continue directly at step 5 for every preselected set"
    )
    status_update = flow_r1.index("--status review_requested")
    assert curator_entry < status_update

    assert (
        "Follow `src/skills/evaluations/deployment-flow.md` before remote mutation"
        in flow_r1
    )
    assert (
        "The selected Request Review action authorizes the required "
        "non-destructive push" in flow_r1
    )


def test_update_mixed_declines_do_not_stop_approved_pushes():
    update = _normalized("src/skills/evaluations/update/SKILL.md").lower()

    # The old "push-approved sets" bookkeeping collection, and the guarantee
    # that declining one set in a batch must not block another set's already
    # approved push, no longer exist as a bookkeeping problem at all: per the
    # Curator-originated preselected-set handoffs section,
    # `evaluation_deployment.py` deploys exactly one set per invocation, so a
    # decline on one set has no shared state through which it could block a
    # push for a different set.
    assert "push-approved sets" not in update
    assert "repeat the applicable handoff independently per set" in update
    assert (
        "`evaluation_deployment.py` previews and deploys exactly one set per "
        "invocation" in update
    )
    assert (
        "runs its deployment-flow sequence once per set, never a single "
        "batched command" in update
    )


def test_run_skill_is_referenced_only_after_successful_push():
    wrapper = _read("src/skills/evaluations/curate/SKILL.md")
    update = _read("src/skills/evaluations/update/SKILL.md")
    deployment_flow = _read("src/skills/evaluations/deployment-flow.md")
    experience_contract = _read("src/skills/evaluations/experience-contract.md")
    run = _read("src/skills/evaluations/run/SKILL.md")
    run_handoff = " ".join(
        _section(
            run,
            "### Eligible-set handoff from the update skill",
            "## Flow A: Start an evaluation run",
        ).split()
    )

    assert "src/skills/evaluations/run/SKILL.md" not in wrapper

    # update/SKILL.md no longer builds its own post-push Run/View/Finish menu
    # gated on "one or more selected sets completed push.py --yes
    # successfully": that batch-eligibility bookkeeping was replaced by the
    # shared, per-set Four maker actions menu (experience-contract.md), whose
    # Run option hands a single verified deployed set identity straight to
    # run/SKILL.md Flow A.
    assert "src/skills/evaluations/run/SKILL.md" in update
    deployment_table_row = (
        "Run | Pass the verified deployed set identity to `run/SKILL.md`; "
        "complete connection prerequisites and start exactly once"
    )
    assert deployment_table_row in deployment_flow

    experience_run_row = (
        "`run/SKILL.md` Flow A; preserve its separate discovery/selection "
        "turn, review and connection gates; it owns required deployment and run"
    )
    assert experience_run_row in experience_contract

    # run/SKILL.md's own eligible-set-handoff section still scopes discovery
    # and selection to whatever update actually hands it, in case a future
    # caller hands over more than one successfully pushed name.
    assert "Whenever `src/skills/evaluations/update/SKILL.md` enters" in run_handoff
    assert "from its post-push next actions" in run_handoff
    assert "whether every selected set succeeded or only some did" in run_handoff
    assert "only for returned sets whose name or ID is in that scope" in run_handoff
    assert (
        "only for runs whose test-set name or `testSetId` is in that scope"
        in run_handoff
    )
    assert "Do not widen the scope to unrelated deployed sets or runs" in run_handoff


def test_update_step_7_is_direct_curator_handoff_not_only_curator_entry():
    update_text = _read("src/skills/evaluations/update/SKILL.md")
    step_7 = _section(
        update_text,
        "## Step 7: Continue the selected deployment action",
        "## Step 8:",
    )
    normalized = " ".join(step_7.split()).lower()
    curator_handoffs = " ".join(
        _section(
            update_text,
            "### Curator-originated preselected-set handoffs",
            "### Review-state reconciliation",
        ).split()
    )

    # Step 7 itself no longer special-cases curator entries at all: it is one
    # generic deployment gate, entered for Request Review, explicit push, or
    # confirmed reviewer completion, regardless of how the set was selected.
    assert "curator" not in normalized
    assert (
        "enter only for request review, explicit evaluation push, or "
        "confirmed reviewer completion" in normalized
    )
    assert "deployment-flow.md" in normalized
    assert (
        "owns setup/backend admission, review reconciliation, promotion "
        "collisions, scoped dry-run visibility, action-aware authorization, "
        "verified push/no-op, and success-only cleanup" in normalized
    )

    # The replaced guarantee: the curator's "Keep them unchanged" handoff no
    # longer gets a bespoke direct-to-Step-7 entry point. It enters the same
    # shared Four maker actions menu as any other set, and deployment happens
    # only if the maker explicitly chooses Request Review or Run -- exactly
    # like any other set, with no special curator-only Step-7 bypass needed.
    assert "**Keep them unchanged**" in curator_handoffs
    assert "enter the **Four maker actions** menu from" in curator_handoffs
    assert (
        'do not ask an implicit "push it now?" question for this handoff'
        in curator_handoffs.lower()
    )
    assert (
        "follow flow r1 or `run/skill.md` flow a exactly as for any other set"
        in curator_handoffs.lower()
    )
    assert (
        "each preselected set finishes local-only, exactly like any other "
        "set for which no push action was selected" in curator_handoffs.lower()
    )


def test_mixed_push_outcomes_limit_run_and_view_to_successful_sets():
    deployment_flow_text = _read("src/skills/evaluations/deployment-flow.md")
    deployment_flow = " ".join(deployment_flow_text.split())

    # The old "mixed multi-set outcomes" bookkeeping assumed one push could
    # cover several sets at once, needing to recompute which ones succeeded
    # before offering Run/View. That bookkeeping is gone: every action
    # (Request Review, Run, explicit push, reviewer completion) is its own
    # independently previewed, authorized, and verified deployment of exactly
    # one set, so there is no batch outcome left to disambiguate.
    assert "For mixed multi-set outcomes" not in deployment_flow

    continue_table_header = "## Continue exactly the intended action"
    assert continue_table_header in deployment_flow_text
    continuation = " ".join(
        _section(
            deployment_flow_text, continue_table_header, "On error or cancellation"
        ).split()
    )
    assert "Request Review / Flow R1" in continuation
    assert (
        "Run | Pass the verified deployed set identity to `run/SKILL.md`"
        in continuation
    )
    assert "Explicit evaluation push | Report deployment only" in continuation
    assert "Reviewer completion / Flow R2" in continuation

    # Each row's continuation is conditioned on this exact set's verified
    # deployment, never on a batch-wide success/failure tally.
    assert "Only after verified success" in deployment_flow
    assert "A preview alone is not synchronization proof" in deployment_flow
    assert "never claim review availability" in deployment_flow
    assert "after failed verification" in deployment_flow


def test_curator_wrapper_blocks_on_missing_input_or_failed_validation():
    wrapper = _read("src/skills/evaluations/curate/SKILL.md")
    normalized = " ".join(wrapper.split()).lower()

    assert "stop and report" in normalized
    assert "wait" in normalized
    assert "curator is not available in this workspace" in normalized
    assert "missing vendored curator file" in normalized
    assert "stop" in normalized
    assert "failed or partial validation" in normalized
    assert "stays local" in normalized
    assert "blocks lifecycle handoff" in normalized


def test_curator_wrapper_accepts_only_complete_successful_handoffs():
    wrapper = _normalized("src/skills/evaluations/curate/SKILL.md")

    assert "`structuralValidation` is exactly `passed`" in wrapper
    assert "`qualityValidation` is exactly `passed`" in wrapper
    assert "one or more generated set entries" in wrapper
    assert "every entry in `sets`" in wrapper
    assert "successful Maker Kit quality validation" in wrapper
    assert "even when the curator reports `qualityValidation: passed`" in wrapper
    assert "malformed, failed, or partial handoff" in wrapper
    assert "remain local" in wrapper
    assert "must not enter the update skill" in wrapper
    assert "promotion, push, cleanup, or run" in wrapper
    assert "scripts/eval_curator_handoff.py validate" in wrapper
    assert "Before invoking Maker Kit validation" in wrapper
    assert "traversal" in wrapper
    assert "symlink or junction escape" in wrapper
    assert "`exports/` as a set folder" in wrapper


def test_curator_wrapper_delegates_push_contract_without_commands():
    wrapper = _normalized("src/skills/evaluations/curate/SKILL.md")

    assert (
        "Topic confirmation, generation preview, and the maker review choice "
        "are not push approval"
    ) in wrapper
    assert "explicit push approval inside update Step 7" in wrapper
    assert "sole source of truth" in wrapper
    assert "evaluation_promotion.py" not in wrapper
    assert "push.py" not in wrapper
    assert "--dry-run" not in wrapper
    assert "--yes" not in wrapper


def test_update_owns_concrete_workspace_push_and_cleanup_gates():
    deployment_text_raw = _read("src/skills/evaluations/deployment-flow.md")
    update_text = _read("src/skills/evaluations/update/SKILL.md")

    # The concrete promote/dry-run/push/cleanup commands moved out of
    # update/SKILL.md's old Step 8/9 (which no longer exist) and into
    # deployment-flow.md's "Promotion, scoped deployment, and verification"
    # section, which every deployment-triggering action now shares.
    section_raw = _section(
        deployment_text_raw,
        "## Promotion, scoped deployment, and verification",
        "## Continue exactly the intended action",
    )
    section = " ".join(section_raw.split())

    dry_run = 'python scripts/push.py --only "evaluations/{set}/*" --dry-run'
    confirmed_push = 'python scripts/push.py --only "evaluations/{set}/*" --yes'

    assert "evaluation_promotion.py promote" in section
    assert "preserving `review.json` and the workspace source" in section
    assert dry_run in section
    assert confirmed_push in section
    assert (
        "Use `--yes --force-delete` only after showing and approving the "
        "exact selected" in section
    )
    assert "evaluation_promotion.py cleanup" in section

    promote_index = section.index("evaluation_promotion.py promote")
    dry_run_index = section.index(dry_run)
    push_index = section.index(confirmed_push)
    verify_index = section.index("Verify the deployed identity")
    cleanup_index = section.index("evaluation_promotion.py cleanup")

    assert promote_index < dry_run_index < push_index < verify_index < cleanup_index
    assert (
        "A dry run, failure, cancellation, or failed verification never "
        "authorizes cleanup" in section
    )
    deployment_text = " ".join(deployment_text_raw.split())
    assert "preserve source files and the returned recovery details" in deployment_text

    # update/SKILL.md delegates ownership of this concrete sequence rather
    # than duplicating it inline.
    step_7 = " ".join(
        _section(
            update_text,
            "## Step 7: Continue the selected deployment action",
            "## Step 8:",
        ).split()
    )
    assert "src/skills/evaluations/deployment-flow.md" in step_7
    assert "do not run the same push from both skills" in step_7.lower()


def test_mixed_push_approval_scopes_every_mutation_to_approved_sets():
    deployment_text = _normalized("src/skills/evaluations/deployment-flow.md")
    update_text_raw = _read("src/skills/evaluations/update/SKILL.md")
    update_text = _normalized("src/skills/evaluations/update/SKILL.md")

    # The old "push-approved sets" bookkeeping collection -- which scoped
    # every mutation to a maker-approved subset of a multi-set batch -- no
    # longer exists, and the cross-set leakage it guarded against is now
    # structurally impossible: every promotion/dry-run/push/cleanup call is
    # already scoped to exactly one set via `--only "evaluations/{set}/*"`,
    # and `evaluation_deployment.py` deploys exactly one set per invocation.
    assert "push-approved sets" not in deployment_text
    assert "push-approved sets" not in update_text

    assert 'The selected-set scope is `--only "evaluations/{set}/*"`' in deployment_text
    assert "for each selected set" in deployment_text
    assert (
        "Never use an unscoped push: unrelated pending topics, workflows, "
        "and sets must remain local" in deployment_text
    )
    assert "Use the existing push APIs for the selected backend" in deployment_text

    curator_handoffs = " ".join(
        _section(
            update_text_raw,
            "### Curator-originated preselected-set handoffs",
            "### Review-state reconciliation",
        ).split()
    )
    assert (
        "`evaluation_deployment.py` previews and deploys exactly one set per "
        "invocation" in curator_handoffs
    )
    assert (
        "runs its deployment-flow sequence once per set, never a single "
        "batched command" in curator_handoffs
    )


def test_maker_readme_documents_all_evaluation_generation_sources():
    readme = " ".join(_read("README.md").split()).lower()

    assert "configured agent topics" in readme
    assert "behavior already present in the active agent" in readme
    assert "local knowledge source" in readme
    assert "connected knowledge base" in readme
    assert "agent instructions" in readme
    assert "grounded knowledge" in readme
    assert "instruction-adherence" in readme
    assert "vendored curator" in readme
    assert "bundled ess catalogue" in readme
    assert "without configured topics or documents" in readme
    assert "native `.mcs.yml`" in readme
    assert "csv" in readme
    assert "review, push, run, and results lifecycle" in readme


def test_maker_readme_documents_servicenow_curation_prerequisites():
    readme = _normalized("README.md").lower()

    assert "active graph connection" in readme
    assert "servicenow-backed curation" in readme
    assert "resolves and searches" in readme
    assert "servicenow mcp" in readme
    assert "already be configured" in readme
    assert "/connect servicenow" in readme
    assert "foundation `/setup`" in readme
    assert "does not configure vendor mcp credentials" in readme


def test_evaluation_docs_preserve_generation_skill_boundaries():
    generate = " ".join(
        _read("src/skills/evaluations/generate/SKILL.md").split()
    ).lower()
    create = " ".join(_read("src/skills/evaluations/create/SKILL.md").split()).lower()

    assert "bundled-catalogue-only" in generate
    assert "must not handle user-supplied document folders" in generate
    assert "configured-topic-grounded" in create
    assert "must not absorb" in create
    assert "document-grounding" in create
    assert "curator workflow" in create


def test_curator_wrapper_cites_source_urls_on_grounded_connected_kb_cases():
    wrapper_text = _read("src/skills/evaluations/curate/SKILL.md")
    wrapper = " ".join(wrapper_text.split())
    normalized_lower = wrapper.lower()

    # 2a: positive/boundary connected-KB cases carry the grounding document's
    # URL in both a `Source URL` CSV column and an `extensionData.sourceUrl` key.
    assert "Source URL" in wrapper
    assert "extensionData.sourceUrl" in wrapper or "`sourceUrl`" in wrapper
    assert "positive" in normalized_lower and "boundary" in normalized_lower

    # The value comes from the grounding hit's `sourceUrl` produced by the
    # connected-KB search shim.
    assert "scripts/search_connected_kb.py" in wrapper
    assert "sourceUrl" in wrapper

    # Citation is BLANK for negative cases and for ALL local-file cases.
    assert "never for negative" in normalized_lower or "never on negative" in normalized_lower
    assert "blank" in normalized_lower
    assert "local-file" in normalized_lower

    # Layered on top of the vendored Step 6 shape without editing the curator body.
    assert "without editing the curator" in normalized_lower
    assert "step 6" in normalized_lower


def test_curator_wrapper_generates_conditional_citation_adherence_cases():
    wrapper_text = _read("src/skills/evaluations/curate/SKILL.md")
    wrapper = " ".join(wrapper_text.split())
    normalized_lower = wrapper.lower()

    # 2b: citation-adherence graded cases are generated ONLY when the resolved
    # agent instructions actually require citing sources.
    assert "citation-adherence" in normalized_lower
    assert "only when" in normalized_lower or "only if" in normalized_lower
    assert "require" in normalized_lower and "citing sources" in normalized_lower

    # They draw from positive/boundary grounding and NEVER from negatives.
    assert "positive" in normalized_lower and "boundary" in normalized_lower
    assert "never" in normalized_lower and "negative" in normalized_lower

    # Their expected output describes citation as observable behavior without
    # naming a backend system (consistent with the vendored no-backend rule).
    assert "observable" in normalized_lower
    assert "backend" in normalized_lower
