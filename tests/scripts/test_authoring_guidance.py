# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Source contract guards for authoring; not runtime UX acceptance."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SOLUTION = ROOT / "solutions" / "ess-maker-skills"


def _read(relative: str) -> str:
    return (SOLUTION / relative).read_text(encoding="utf-8")


def test_authoring_catalog_union_covers_only_the_pinned_da_ga_template_families():
    reference = SOLUTION / "src" / "reference" / "topic-actions"
    catalogs = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(reference.glob("catalog.*.json"))
        if path.name != "catalog.schema.json"
    }
    additions = catalogs["catalog.authoring-additions.json"]
    primary = catalogs[additions["baseCatalog"]["file"]]
    assert len(catalogs) >= 2
    expected_counts = {"core": 3, "hr": 50, "it": 47}
    expected_keys = {
        f"source-family:gptagent_copilotforemployeeselfservice{suffix}"
        for suffix in expected_counts
    }
    assert {package["key"] for package in additions["packages"]} == expected_keys

    for package in additions["packages"]:
        schema, = package["agentSchemaNames"]
        suffix = schema.removeprefix("gptagent_copilotforemployeeselfservice")
        assert package["sourcePath"].startswith("/sources/dev/AgentTemplates/")
        assert package["sourceRevision"] == additions["source"]["revision"]
        assert package["packageVersion"]
        covered = [
            topic["schemaName"]
            for catalog in catalogs.values()
            for candidate in catalog["packages"]
            if candidate["key"] == package["key"]
            for topic in candidate["topics"]
        ]
        assert all(name.startswith(schema + ".topic.") for name in covered)
        assert len({name.casefold() for name in covered}) == len(set(covered))
        names = sorted(set(covered))
        source_coverage = package["combinedTopicInventory"]
        assert source_coverage["coverage"] == "complete_at_source_revision"
        assert len(names) == source_coverage["topicCount"] == expected_counts[suffix]
        digest = hashlib.sha256(("\n".join(names) + "\n").encode()).hexdigest()
        assert digest == source_coverage["schemaNamesSha256"]
        primary_names = {
            topic["schemaName"]
            for candidate in primary["packages"]
            if candidate["key"] == package["key"]
            for topic in candidate["topics"]
        }
        added_names = [topic["schemaName"] for topic in package["topics"]]
        assert len(added_names) == len(set(added_names))
        assert primary_names.isdisjoint(added_names)


def test_topic_actions_companion_artifacts_remain_byte_identical():
    reference = SOLUTION / "src" / "reference" / "topic-actions"
    additions = json.loads((reference / "catalog.authoring-additions.json").read_text())
    base = additions["baseCatalog"]
    for filename, expected_blob in (
        (base["file"], base["gitBlob"]),
        ("catalog.schema.json", "f20a61ef9fdf8c120f21706712153c509bf014a5"),
    ):
        content = (reference / filename).read_bytes()
        blob = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        assert blob == expected_blob, filename
    primary = json.loads((reference / base["file"]).read_text())
    schema = json.loads((reference / "catalog.schema.json").read_text())
    Draft202012Validator(schema).validate(primary)


def test_topic_routes_share_policy_and_inventory_protection_is_deletion_only():
    contract = _read("src/skills/topics/experience-contract.md")
    policy = contract.split("## Authoring policy for this release\n", 1)[1].split(
        "## Authorization and recovery\n", 1
    )[0]
    authoring, deletion = policy.split("### Template protection for deletion\n", 1)
    assert "catalog.*.json" not in authoring
    assert "src/reference/topic-actions/catalog.*.json" in deletion
    assert "excluding `catalog.schema.json`" in deletion
    assert "sources/dev/AgentTemplates" in deletion
    assert "Do not include those rows in DA-GA coverage" in deletion
    assert "Before deleting a local topic or dispatching its remote deletion" in deletion
    assert "Do not delete template-provided topics" in deletion
    assert "protected from deletion, including examples, helpers and integration topics" in deletion
    assert "A nonmatch is not proof of customer ownership." in policy
    assert "Preserve an existing draft unchanged." in policy
    for relative in (
        ".github/copilot-instructions.md",
        ".github/prompts/push.prompt.md",
        "src/skills/topics/create/SKILL.md",
        "src/skills/topics/update/SKILL.md",
        "src/skills/topics/delete/SKILL.md",
        "src/skills/topics/test/SKILL.md",
        "src/skills/cleanup/SKILL.md",
    ):
        guidance = _read(relative)
        assert "Authoring policy for this release" in guidance, relative
        assert "catalog.*.json" not in guidance, relative


def test_create_blocks_name_conflicts_but_keeps_intent_overlap_advisory():
    contract = _read("src/skills/topics/experience-contract.md")
    create = _read("src/skills/topics/create/SKILL.md")
    assert "unique display name in the selected agent" in contract
    assert "case-insensitively after trimming surrounding whitespace" in contract
    assert "Stop if the requested display name already exists." in create
    assert "meaningful intent overlap under a different name as advisory" in create


def test_missing_topic_origin_does_not_gate_mutation_or_claim_customer_ownership():
    contract = _read("src/skills/topics/experience-contract.md")
    policy = contract.split("## Authoring policy for this release\n", 1)[1].split(
        "## Authorization and recovery\n", 1
    )[0]
    assert "A nonmatch is not proof of customer ownership." in policy
    assert "Missing customer-origin evidence does not block authoring or deletion" in policy
    assert "topics created by another author or in another workspace" in policy
    assert (
        "Do not require creation receipts, shared provenance metadata or maker "
        "attestation as an eligibility prerequisite."
    ) in policy
    assert "Retain unknown origin as unknown" in policy
    assert "establish customer-authored origin independently" not in policy
    assert "no independent origin evidence settles it" not in policy
    assert "For a template-protected deletion" in policy
    assert "unavailable required reads and conflicting edits" in policy


def test_deletion_and_cleanup_do_not_reintroduce_the_topic_origin_gate():
    for relative in (
        ".github/copilot-instructions.md",
        ".github/prompts/push.prompt.md",
        "src/skills/topics/deletion-experience.md",
        "src/skills/topics/delete/SKILL.md",
        "src/skills/cleanup/SKILL.md",
    ):
        guidance = _read(relative)
        assert "Authoring policy for this release" in guidance, relative
        assert "unresolved ownership" not in guidance, relative
        assert "protected or unresolved" not in guidance, relative
        assert "customer-authored topic" not in guidance, relative
    deletion = _read("src/skills/topics/deletion-experience.md")
    assert "If its remote status is unknown, resolve that uncertainty first." in deletion
    assert "Selection is not deletion approval." in deletion
    cleanup = _read("src/skills/cleanup/SKILL.md")
    assert "template-protected deletions" in cleanup


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


def test_authoring_usage_precedes_drafting_and_excludes_later_saves():
    for operation in ("create", "update"):
        skill = _read(f"src/skills/topics/{operation}/SKILL.md")
        command = f"python scripts/emit_capability.py topic_{operation}"
        assert skill.count(command) == 1
        assert skill.index("## 2.") < skill.index(command) < skill.index("## 3.")
        assert "including when the maker later keeps the draft locally" in skill
        assert "Previewing, saving or recovering the same proposal adds no authoring count" in skill
        assert "unchanged draft for a later Push, skip this emission" in skill


def test_testing_usage_counts_attempted_passes_and_post_fix_retests():
    skill = _read("src/skills/topics/test/SKILL.md")
    command = "python scripts/emit_capability.py topic_test"
    assert skill.count(command) == 1
    assert skill.index("## Execute and interpret tests") < skill.index(command)
    assert skill.index(command) < skill.index("Use the reference's general `capture`")
    assert "first authorized `capture` or `run` attempt of each pass" in skill
    assert "readiness-only pauses add no count" in skill
    assert "resuming the same paused pass add no count" in skill
    assert "Each post-fix retest starts a new pass" in skill
    assert "count as two passes" in skill


def test_supported_authoring_scope_is_not_an_admission_restriction():
    contract = _read("src/skills/topics/experience-contract.md")
    scope = contract.split("## Supported authoring scope\n", 1)[1].split(
        "## Authoring policy for this release\n", 1
    )[0]
    assert "one employee intent" in scope
    assert "optional input collection and local conditional logic" in scope
    assert "ending in approved text" in scope
    assert "Makers may author outside this scope with an explicit disclaimer" in scope
    assert "permitted but unsupported in this release" in scope
    assert (
        "Examples include cross-topic calls, live lookups, business actions "
        "and modifications to shipped topics."
    ) in scope
    assert "The support boundary is not an authoring restriction." in scope
    assert "Do not silently remove requested or existing behavior" in scope
    assert "optional exact-response compatibility as a universal admission requirement" in scope
    for relative in (
        ".github/copilot-instructions.md",
        ".github/prompts/push.prompt.md",
        "src/skills/topics/create/SKILL.md",
        "src/skills/topics/update/SKILL.md",
        "src/skills/topics/test/SKILL.md",
        "src/skills/topics/push-experience.md",
        "src/skills/topics/testing-experience.md",
    ):
        assert "Supported authoring scope" in _read(relative), relative


def test_unsupported_authoring_disclaimer_leads_the_response_once():
    contract = _read("src/skills/topics/experience-contract.md")
    scope = contract.split("## Supported authoring scope\n", 1)[1].split(
        "## Authoring policy for this release\n", 1
    )[0]
    assert "For a request outside the supported scope above" in scope
    assert (
        "begin the first authoring review, clarification or outcome response in normal chat "
        "with the following callout, once per request"
    ) in scope
    assert "Keep it in that response, not in an interim progress message." in scope
    assert "Do not repeat it in revisions or continuations, or show it for supported requests." in scope
    assert scope.count("> > **Important**") == 1
    assert (
        "> > **Important**\n> >\n"
        "> > This release only supports text-response topic authoring. "
        "Customizations to shipped topics and more complex topic behavior may be attempted, "
        "but are outside this release's supported scope."
    ) in scope


def test_create_update_and_push_do_not_reintroduce_the_support_scope_gate():
    for relative in (
        ".github/copilot-instructions.md",
        ".github/prompts/push.prompt.md",
        ".github/prompts/test.prompt.md",
        "src/skills/topics/experience-contract.md",
        "src/skills/topics/create/SKILL.md",
        "src/skills/topics/update/SKILL.md",
        "src/skills/topics/test/SKILL.md",
        "src/skills/topics/push-experience.md",
        "src/skills/topics/testing-experience.md",
    ):
        guidance = " ".join(_read(relative).split())
        for restriction in (
            "business/ISV actions are prohibited",
            "seek an in-scope request",
            "without importing prohibited behavior",
            "not as permission to author backend-backed topics",
            "backend-backed topic authoring is outside ADK",
            "action-backed topic authoring is outside ADK",
            "do not author a live lookup",
            "do not edit, overwrite or delete it",
            "Do not route backend conversations through the bounded topic test",
        ):
            assert restriction not in guidance, (relative, restriction)
    push = _read("src/skills/topics/push-experience.md")
    assert "outside this push's scope or support boundary" not in push


def test_wording_review_preserves_supplied_text_and_distinguishes_local_drafts():
    contract = _read("src/skills/topics/authoring-experience.md")
    wording = contract.split("### Response wording and local drafts\n", 1)[1].split(
        "### Advisory entries in Notes\n", 1
    )[0]
    assert "Preserve wording supplied as the intended response, including links." in wording
    assert "Do not polish or paraphrase it unless requested." in wording
    assert "Distinguish intended response text from background material" in wording
    assert "Ask for missing essential facts rather than inventing them." in wording
    assert ">   ###### RESPONSE TEXT\n>\n>   > {Response text}" in wording
    assert ">   ###### SUGGESTED RESPONSE\n>\n>   > {Suggested response}" in wording
    assert "`.mcs.yml` file saved locally" in wording
    assert (
        "> The proposed changes are saved locally in your VS Code workspace. "
        "They have not been pushed to the agent."
    ) in wording
    assert "Keeping a draft locally does not accept a suggestion or authorize a remote save." in wording
    assert "If the proposed content is already authoritatively saved, report that state instead." in wording
    assert "without treating it as Push consent" in wording
    assert "do not infer acceptance from the file's presence or add persistent approval metadata" in wording
    assert "Preserve exact wording when requested" not in _read(
        "src/skills/topics/create/SKILL.md"
    )


def test_suggested_response_revision_returns_to_review_without_save_consent():
    contract = _read("src/skills/topics/authoring-experience.md")
    decision = contract.split("### Suggested-response decision\n", 1)[1].split(
        "### Initial routing-conflict decision\n", 1
    )[0]
    assert (
        "For Create and Update, use the [Topic save control](#topic-save-decision) with "
        "**Push topic to agent**, **I want to update the response** and **Keep as draft**"
    ) in decision
    assert "accepts the displayed suggested wording and approves the topic save together" in decision
    assert "Do not add a separate mandatory wording-approval step." in decision
    assert "does not accept the suggestion or authorize a remote save" in decision
    assert (
        "> What would you like to change? Describe the edits or paste the response you want."
    ) in decision
    assert "return to the applicable decision control before any save" in decision
    assert decision.index("Obtain a fresh save preview") < decision.index(
        "Then show the revised summary and wording"
    )
    assert "Keep as draft retains the suggestion locally without accepting it." in decision
    assert "[Topic outcomes](#topic-outcomes)" in decision
    outcomes = contract.split("### Topic outcomes\n", 1)[1].split(
        "### Combined routing-conflict and testing follow-up\n", 1
    )[0]
    assert (
        "For a retained draft with unaccepted suggested wording, "
        "`{Contextual trailer}` begins with the following fixed block."
    ) in outcomes
    assert (
        "> {Topic title} is saved locally in your VS Code workspace. "
        "The suggested response remains available for review or revision."
    ) in outcomes
    assert "put additional factual context after a blank line" in outcomes
    for owner in ("create", "update"):
        guidance = _read(f"src/skills/topics/{owner}/SKILL.md")
        assert "../authoring-experience.md#topic-save-decision" in guidance
        assert "Revisions return to a fresh preview" in guidance
    push = " ".join(_read(".github/prompts/push.prompt.md").split())
    assert "unaccepted or acceptance-unknown response wording before any batch Push approval" in push
    assert "**I want to update the response** before Keep pending" in push
    assert "Return to this component's refreshed review before saving it." in push
    assert "before Keep as draft and use the response-revision continuation" in contract
    assert "resolving the instruction conflict alone does not accept it" in contract


def test_debugging_preserves_wording_without_claiming_verbatim_runtime_delivery():
    contract = _read("src/skills/topics/testing-experience.md")
    goal = contract.split("### Scoped runtime correctness goal\n", 1)[1].split(
        "### Topic debugging outcome:", 1
    )[0]
    assert "Preserve supplied or accepted response wording and links during debugging" in goal
    assert "unless the maker authorizes a wording change" in goal
    assert "Do not replace wording merely to obtain a passing test." in goal
    assert "literal saved content and verbatim runtime delivery are distinct claims" in goal
    assert "a save alone does not establish the last" in goal
    assert "without restricting read-only inspection of existing topics" in goal
    testing = _read("src/skills/topics/test/SKILL.md")
    assert "Preserve supplied or accepted response wording and links" in testing
    assert "Distinguish literal saved content from observed runtime delivery" in testing
    assert "Apply the shared Supported authoring scope to proposed topic fixes" in testing


def test_eval_driven_aliases_are_thin_and_scenario_lifecycle_is_retired():
    create = _read("src/skills/topics/create-eval-driven/SKILL.md")
    update = _read("src/skills/topics/update-eval-driven/SKILL.md")

    assert "provisional compatibility alias" in create
    assert "provisional compatibility alias" in update
    assert "Reassess this alias" not in create + update
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
    for owner, references in {
        "create": ("authoring", "push", "testing"),
        "update": ("authoring", "push", "testing"),
        "delete": ("deletion", "push"),
        "test": ("testing",),
    }.items():
        guidance = _read(f"src/skills/topics/{owner}/SKILL.md")
        assert "../experience-contract.md" in guidance
        for reference in references:
            assert f"../{reference}-experience.md" in guidance
    push = _read(".github/prompts/push.prompt.md")
    for reference in ("experience-contract", "authoring-experience", "deletion-experience",
                      "push-experience", "testing-experience"):
        assert f"src/skills/topics/{reference}.md" in push
    assert "src/skills/topics/testing-experience.md" in _read(".github/prompts/test.prompt.md")
    assert "src/skills/topics/experience-contract.md" in _read(".github/copilot-instructions.md")


def test_focused_experience_and_review_links_resolve():
    topics = SOLUTION / "src" / "skills" / "topics"
    documents = [topics / "experience-contract.md", *topics.glob("*-experience.md")]
    documents += [topics / owner / "SKILL.md" for owner in ("create", "update", "delete", "test", "review")]
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for destination in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if "://" in destination or destination.startswith("{"):
                continue
            path, _, anchor = destination.partition("#")
            target = document.parent / path if path else document
            assert target.is_file(), (document, destination)
            if anchor:
                headings = re.findall(r"^#{1,6} (.+)$", target.read_text(encoding="utf-8"), re.MULTILINE)
                anchors = {
                    re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
                    for heading in headings
                }
                assert anchor in anchors, (document, destination)


def test_native_progress_preserves_other_operations_and_setup():
    foundation = _read("src/skills/topics/experience-contract.md")
    assert "not native todo lists or Markdown progress checklists" in foundation
    assert "Setup and other operations retain their own progress rules." in foundation
    formatting = _read("src/reference/ui-formatting-guidelines.md")
    native = " ".join(
        formatting.split("## Native task progress\n", 1)[1]
        .split("## Progress checklists\n", 1)[0].split()
    )
    assert "For topic authoring, deletion, Push, testing and cleanup" in native
    assert "../skills/topics/experience-contract.md#status-update-markers" in native
    assert "Delegated entry points reuse the performing owner's updates." in native
    assert "native todo tool exposed by the current chat" in native
    assert "Use its actual schema and supported states" in native
    assert "If no native todo tool is available, continue" in native
    assert "Do not substitute Markdown progress checklists" in native
    assert "send the full current list rather than only changed items" in native
    assert "A todo is not consent." in native
    assert "only when its stated completion condition is observed" in native
    assert "remove unattempted work from the active plan" in native
    assert "report it as cancelled, not completed" in native
    markdown = " ".join(formatting.split("## Progress checklists\n", 1)[1].split())
    assert "only when an operation explicitly defines its own progress-checklist Message block" in markdown
    assert "Send each progress snapshot as its own complete chat message" in markdown


def test_status_update_markers_interpret_outcomes_without_assuming_success():
    foundation = _read("src/skills/topics/experience-contract.md")
    markers = foundation.split("## Status update markers\n", 1)[1].split(
        "## Presentation and scope\n", 1
    )[0]
    assert "{EMIT_STATUS_UPDATE: point}" in markers
    assert "Before the marked work, load the point's completion condition and message" in markers
    assert "Reuse those definitions while they remain available in context." in markers
    assert "only when its completion condition is satisfied" in markers
    assert "select or compose a concise status update appropriate to the observed result" in markers
    assert "failed, remains incomplete, required no change, or cannot be confirmed" in markers
    assert "Preserve known successful effects" in markers
    assert "standalone normal-chat message before proceeding to the next step" in markers
    assert "Keep required reviews, outcome reports and questions in separate subsequent messages" in markers
    assert "continuation, pause or recovery instructions without expanding its authorization" in markers
    assert "including failed or incomplete attempts, rather than after every tool call" in markers
    assert "If the marked work stops before its normal reporting point" in markers
    assert "emit its observed outcome before pausing or returning" in markers
    assert "Do not enter reporting points for work that was never requested or selected." in markers
    assert "Reuse an existing still-current assessment" in markers
    assert "The operation performing the work owns its status update." in markers
    assert "reuses the owner's update without emitting it again" in markers
    assert "Required composed reports remain separate." in markers
    assert "When the caller performs work without an emitting owner" in markers
    assert "Pause and stop acknowledgements take precedence" in markers


def test_authoring_status_markers_resolve_local_copy_at_the_reporting_points():
    formatting = _read("src/reference/ui-formatting-guidelines.md")
    assert "For topic authoring, deletion, Push, testing and cleanup" in formatting
    assert "../skills/topics/experience-contract.md#status-update-markers" in formatting
    authoring = _read("src/skills/topics/authoring-experience.md")
    progress = authoring.split("## Authoring status updates\n", 1)[1].split(
        "## Authoring summaries\n", 1
    )[0]
    assert "For Create, Update and related instruction corrections" in progress
    assert "experience-contract.md#status-update-markers" in progress
    definitions = {
        point: (condition.strip(), message.strip())
        for point, condition, message in re.findall(
            r"^\|\s*`([^`]+)`\s*\|([^|]+)\|([^|]+)\|", progress, re.MULTILINE
        )
    }
    assert set(definitions) == {
        "draft-preparation", "instruction-preparation", "topic-save", "instruction-save",
    }
    assert "saved or verified unchanged" in definitions["draft-preparation"][0]
    assert definitions["draft-preparation"][1] == "✅ Prepared the draft for **{Topic title}**."
    assert "approved topic save and authoritative readback both succeed" in definitions["topic-save"][0]
    assert "a new remote write is confirmed" in definitions["topic-save"][0]
    assert "required local recording is complete" in definitions["topic-save"][0]
    assert definitions["topic-save"][1] == "✅ Pushed and verified **{Topic title}**."
    assert "failed or incomplete local draft" in progress
    assert "[Topic outcomes](#topic-outcomes)" in progress
    assert "already-current no-write result" in progress
    assert "rejected or unconfirmed save" in progress
    assert "confirmed remote success with an incomplete workspace update" in progress
    assert "A retained draft does not enter this reporting point." in progress
    assert "Keep the full Create or Update review and existing outcome report" in progress
    assert "Do not prepopulate activation, testing or publication." in progress
    create = _read("src/skills/topics/create/SKILL.md")
    entry = create.split("## Boundaries\n", 1)[0]
    assert "../authoring-experience.md#authoring-status-updates" in entry
    assert "Reuse those status definitions at the marked reporting points below." in entry
    points = re.findall(r"\{EMIT_STATUS_UPDATE: ([^}]+)\}", create)
    assert points == list(definitions)
    drafting = create.split("## 2. Draft ordinary topic YAML\n", 1)[1].split(
        "## 3. Assess agent-instruction alignment\n", 1
    )[0]
    assert "including a failed or incomplete attempt" in drafting
    assert "For a revision, return to this reporting point" in drafting
    assert "{EMIT_STATUS_UPDATE: draft-preparation}" in drafting
    assert "Render the completed summary after the current instruction-alignment assessment and save preview" in drafting
    saving = create.split("## 5. Save and report authoritative results\n", 1)[1].split(
        "## 6. Testing and evaluation handoff\n", 1
    )[0]
    assert "including rejected, no-write, partial or unconfirmed outcomes" in saving
    assert (
        saving.index('--yes --output ".local\\topic-authoring\\topic-result.json"')
        < saving.index("{EMIT_STATUS_UPDATE: topic-save}")
        < saving.index("After the applicable instruction approval")
    )
    for _, message in definitions.values():
        assert message not in create


def test_create_review_uses_h5_fields_nested_h6_headings_and_explained_choices():
    authoring = _read("src/skills/topics/authoring-experience.md")
    summary = authoring.split("### Create summary\n", 1)[1].split(
        "### Update summary\n", 1
    )[0]
    labels = re.findall(r"^> ##### (.+)\n>", summary, re.MULTILINE)
    assert labels == [
        "TITLE", "AGENT", "BEHAVIOR", "INPUTS", "OUTPUTS",
        "STARTS WHEN", "NOTES", "SUGGESTED ACTION",
        "ROUTING CONFLICTS",
    ]
    assert "Suggested action labels in Notes" in summary
    assert "Preserve the response quotation" in summary
    assert "> **Title:**" not in summary
    assert not re.search(r"^>\s{2,}##### ", summary, re.MULTILINE)
    assert not re.search(r"^>\s*(?:---|\*\*\*)\s*$", summary, re.MULTILINE)
    outputs = summary.split("> ##### OUTPUTS\n", 1)[1].split(
        "> ##### STARTS WHEN\n", 1
    )[0]
    assert (
        "> - {Output description}\n>\n"
        ">   ###### RESPONSE TEXT\n>\n"
        ">   > {Response text}"
    ) in outputs
    assert "including Response text and Suggested response" in summary
    assert "indented level-six headings in ALL CAPS within the corresponding output bullet" in summary
    assert "use SUGGESTED RESPONSE for newly generated wording that has not been accepted" in summary
    assert "Omit the response heading and quotation for outputs without literal response wording" in summary
    assert "Apply the same treatment in Update and component reviews." in summary
    wording = authoring.split("### Response wording and local drafts\n", 1)[1].split(
        "### Advisory entries in Notes\n", 1
    )[0]
    assert ">   ###### RESPONSE TEXT" in wording
    assert ">   ###### SUGGESTED RESPONSE" in wording
    conflicts = summary.split("> ##### ROUTING CONFLICTS\n", 1)[1].split(
        "> [Full draft]", 1
    )[0]
    assert re.findall(r"^>   ###### (.+)$", conflicts, re.MULTILINE) == [
        "SUGGESTED ACTIONS",
    ]
    assert (
        "> - {Routing conflict}. This routing conflict will likely block topic execution.\n>\n"
        ">   ###### SUGGESTED ACTIONS\n"
        ">   - {Concrete next action}."
    ) in conflicts
    assert "Follow the complete conflict list with exactly one indented level-six" in summary
    assert "even when there is only one action" in summary
    assert "Do not repeat this block for each conflict." in summary
    assert "Other operations retain" not in summary
    decision = authoring.split("### Topic save decision\n", 1)[1].split(
        "### Suggested-response decision\n", 1
    )[0]
    assert "> ##### YOUR CHOICES" in decision
    assert "immediately before that control" in decision
    assert "Retain the existing short picker labels" in decision
    assert '"enum": ["Push topic to agent", "Keep as draft"]' in decision
    testing = _read("src/skills/topics/testing-experience.md")
    assert "For an inactive topic after any confirmed authoring or Push outcome" in testing
    assert "> ##### YOUR CHOICES" in testing
    for section, title, choices in (
        (decision, "Topic save", ["Push topic to agent", "Keep as draft"]),
        (testing, "Topic testing", ["Activate and test", "Not now"]),
    ):
        question = json.loads(re.search(r"```json\n(.*?)\n```", section, re.DOTALL)[1])
        assert question["message"] == ""
        field = question["requestedSchema"]["properties"]["action"]
        assert field["title"] == title
        assert field["description"] == "How would you like to continue?"
        assert field["enum"] == choices
        assert "allow custom text" in section


def test_authoring_save_control_preserves_question_metadata_across_branches():
    authoring = _read("src/skills/topics/authoring-experience.md")
    decision = authoring.split("### Topic save decision\n", 1)[1].split(
        "### Suggested-response decision\n", 1
    )[0]
    assert "For every Create or Update topic-save decision" in decision
    assert "replace only `enum` with that branch's applicable choices" in decision
    assert "including any conditional response-revision choice" in decision
    for heading, following, legacy_question in (
        (
            "Suggested-response decision", "Initial routing-conflict decision",
            "> **Use this suggested response and push {Topic title} to {Destination agent}?**",
        ),
        (
            "Initial routing-conflict decision", "Topic outcomes",
            "> **How would you like to continue with {Topic title}?**",
        ),
    ):
        branch = authoring.split(f"### {heading}\n", 1)[1].split(
            f"### {following}\n", 1
        )[0]
        assert "For Create and Update, use the [Topic save control](#topic-save-decision)" in branch
        assert legacy_question not in branch
    assert (
        "When suggested wording remains unaccepted, include "
        "**I want to update the response** before Keep as draft"
    ) in branch


def test_authoring_status_updates_preserve_selected_work_and_known_outcomes():
    authoring = _read("src/skills/topics/authoring-experience.md")
    status = authoring.split("## Authoring status updates\n", 1)[1].split(
        "## Authoring summaries\n", 1
    )[0]
    assert "Preparation does not authorize either save." in status
    assert "A retained draft does not enter this reporting point." in status
    assert "Instruction readback does not establish topic execution or a topic save." in status
    assert "earlier confirmed saves remain completed work" in status
    assert "Do not prepopulate activation, testing or publication." in status
    assert "Do not announce work that is starting or still running." in status
    update = _read("src/skills/topics/update/SKILL.md")
    assert "Do not prepare it merely because a topic is being authored" in update
    assert "When the caller has already selected local-only changes" in update
    assert "without offering or executing a remote save" in update
    assert "including valid unchanged batch/debugging consent" in update


def test_push_and_testing_statuses_preserve_evidence_and_consent_boundaries():
    push = _read("src/skills/topics/push-experience.md")
    status = push.split("## Push status updates\n", 1)[1].split(
        "## Component inventory:", 1
    )[0]
    assert "Inventory discovery is not remote validation or save approval." in status
    assert "reuse the performing owner's update without a second caller update" in status
    assert "already-current, failed, unconfirmed or partially completed saves" in status
    assert "Preserve confirmed remote effects when local recording fails." in status
    assert "Pause dependent work after a failed or uncertain prerequisite" in status
    assert "continue only independently safe approved operations" in status
    telemetry = push.split("## Push telemetry\n", 1)[1]
    assert "Status updates and telemetry have separate ownership." in telemetry
    assert "Reporting a result does not create another batch" in telemetry
    testing = _read("src/skills/topics/testing-experience.md").split(
        "## Testing status updates\n", 1
    )[1].split("## Topic testing continuation\n", 1)[0]
    assert "only after testing is requested or selected" in testing
    assert "Not now adds no testing work." in testing
    assert "explicitly approved activation is confirmed" in testing
    assert "authoritative readback shows Active state" in testing
    assert "a completed capture is not correctness" in testing
    assert "already-Active no-write result" in testing
    assert "not universal runtime correctness" in testing
    assert "Report a revised assessment after a post-fix retest" in testing
    assert "Stop sending immediately; do not finish more work to reach a marker." in testing


def test_rollout_markers_resolve_owned_definitions_without_duplicate_caller_updates():
    for owner, reference, heading in (
        ("topics/update", "topics/authoring-experience.md", "Authoring"),
        ("topics/delete", "topics/deletion-experience.md", "Deletion"),
        ("topics/test", "topics/testing-experience.md", "Testing"),
        ("cleanup", "cleanup/SKILL.md", "Cleanup"),
    ):
        guidance = _read(f"src/skills/{owner}/SKILL.md")
        experience = _read(f"src/skills/{reference}")
        status = experience.split(f"## {heading} status updates\n", 1)[1].split(
            "\n## ", 1
        )[0]
        definitions = {
            point: (condition.strip(), message.strip())
            for point, condition, message in re.findall(
                r"^\|\s*`([^`]+)`\s*\|([^|]+)\|([^|]+)\|", status, re.MULTILINE
            )
        }
        points = re.findall(r"\{EMIT_STATUS_UPDATE: ([^}]+)\}", guidance)
        assert definitions and set(points) == set(definitions), owner
        for condition, message in definitions.values():
            assert condition and message, owner
            if owner != "cleanup":
                assert message not in guidance, owner

    push = _read(".github/prompts/push.prompt.md")
    assert set(re.findall(r"\{EMIT_STATUS_UPDATE: ([^}]+)\}", push)) == {
        "push-inventory", "instruction-save", "evaluation-save",
    }
    assert "do not echo a delegated owner's update" in push
    assert "before execution" in push.split("without an emitting authoring owner", 1)[1]
    for relative in (
        ".github/prompts/create.prompt.md",
        ".github/prompts/update.prompt.md",
        ".github/prompts/delete.prompt.md",
        ".github/prompts/test.prompt.md",
        ".github/prompts/scan.prompt.md",
        "src/skills/topics/create-eval-driven/SKILL.md",
        "src/skills/topics/update-eval-driven/SKILL.md",
    ):
        assert "{EMIT_STATUS_UPDATE:" not in _read(relative), relative


def test_rollout_reviews_and_native_choices_keep_the_shared_presentation_contract():
    for relative in (
        "topics/experience-contract.md",
        "topics/authoring-experience.md",
        "topics/deletion-experience.md",
        "topics/push-experience.md",
        "topics/testing-experience.md",
        "cleanup/SKILL.md",
    ):
        guidance = _read(f"src/skills/{relative}")
        headings = re.findall(r"^>\s*(#{1,6}) (.+)$", guidance, re.MULTILINE)
        assert headings, relative
        for level, label in headings:
            assert level in {"#####", "######"}, (relative, label)
            literal_label = re.sub(r"\{[^}]+\}", "", label)
            assert literal_label == literal_label.upper(), (relative, label)
            assert not label.endswith(":"), (relative, label)

        controls = list(re.finditer(r"```json\n(.*?)\n```", guidance, re.DOTALL))
        assert controls, relative
        for control in controls:
            question = json.loads(control[1])
            assert question["message"] == "", relative
            explanation = guidance[:control.start()].rsplit("> ##### YOUR CHOICES", 1)[1]
            rows = {
                label.strip(): meaning.strip()
                for label, meaning in re.findall(
                    r"^> \|\s*([^|]+)\|\s*([^|]+)\|", explanation, re.MULTILINE
                )
            }
            for field in question["requestedSchema"]["properties"].values():
                assert field["title"], relative
                assert field["description"] == "How would you like to continue?", relative
                if field["type"] == "array":
                    assert field["default"] == [], relative
                    choices = field["items"]["enum"]
                else:
                    choices = field["enum"]
                for choice in choices:
                    assert rows.get(choice), (relative, choice)
                    assert rows[choice] != choice, (relative, choice)


def test_shared_experience_preserves_approved_copy_and_template_boundary():
    foundation = _read("src/skills/topics/experience-contract.md")
    assert "../../reference/ui-formatting-guidelines.md#authoring-pattern" in foundation
    assert "These baselines govern coverage; the template's fixed copy remains verbatim." in foundation
    assert "Place any additional relevant context separately from the literal block" not in foundation
    contract = "\n".join(
        _read(f"src/skills/topics/{reference}.md")
        for reference in (
            "experience-contract", "authoring-experience", "deletion-experience",
            "push-experience", "testing-experience",
        )
    )
    for literal in (
        '"enum": ["Push topic to agent", "Keep as draft"]',
        "> ##### TOPIC PUSHED TO AGENT",
        "**DRAFT KEPT LOCALLY AGENT UNCHANGED**",
        "**TOPIC WAS NOT PUSHED**",
        "**TOPIC PUSH COULD NOT BE CONFIRMED**",
        "**TOPIC PUSHED WORKSPACE UPDATE INCOMPLETE**",
        "Cancel remaining push",
        "> | Item | Current | Proposed |",
        "> - {Verified preservation fact summary}",
        "> | Component | Outcome | Details |",
        '["Test topic now", "Not now"]',
        '"enum": ["Activate and test", "Not now"]',
        "> After you confirm readiness, I will test {Topic title} against its "
        "intended behavior, investigate and fix issues observed during execution, "
        "and retest the affected behavior.",
        "> I will summarize the outcome and recommend any next action needed.",
        "> ##### GOAL\n>\n> {Latest authoring goal}",
        "> ##### OUTCOME\n>\n> {Observed runtime outcome}",
        "> ##### RECOMMENDATION\n>\n> {Concrete tweak or next action}",
        "> ##### TESTING PAUSED\n>\n> Let me know when the test browser is ready.",
        "> ##### TESTING STOPPED",
    ):
        if literal.startswith("> |"):
            assert " ".join(literal.split()) in " ".join(contract.split())
        else:
            assert literal in contract
    quoted = "\n".join(line for line in contract.splitlines() if line.startswith(">"))
    for instruction in (
        "Read and apply [Authoring pattern]",
        "These baselines govern coverage",
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
    contract = _read("src/skills/topics/push-experience.md")
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
        "> ##### NOT INCLUDED\n>\n> ###### {COMPONENT TYPE}\n>\n"
        "> - {Component name}: {Exclusion reason}"
    ) in comparison
    assert "even when those entries appeared earlier in the conversation" in comparison
    assert "one named bullet with its reason per component" in contract
    assert "parsed instruction section with the baseline separately from metadata" in push
    assert "unchanged instructions out of pending and excluded changes" in push
    assert "rename as Display name" in push
    assert "from all discovered agent changes" in push
    assert (
        "mark other discovered pending components Not included rather than "
        "dropping them from the inventory"
    ) in push
    assert "entry review, compact comparison and results" in contract
    assert "Do not collapse exclusions into prose" in contract


def test_already_satisfied_topic_outcome_does_not_claim_a_new_push():
    contract = _read("src/skills/topics/authoring-experience.md")
    update = _read("src/skills/topics/update/SKILL.md")
    assert "**TOPIC ALREADY UP TO DATE NO PUSH NEEDED**" in contract
    assert "`writeAttempted: false`" in contract
    assert "`updatedComponents: 0`" in contract
    assert "Do not attribute the existing change to this operation." in contract
    assert "no-write outcome" in update
    assert "verified saved content" in update


def test_push_owners_share_batch_telemetry_without_changing_other_evaluation_actions():
    push = _read(".github/prompts/push.prompt.md")
    assert "nested owners without duplicate events" in push
    for operation in ("create", "update"):
        owner = _read(f"src/skills/topics/{operation}/SKILL.md")
        assert "**Push telemetry**" in owner
        assert "Reuse an enclosing approved batch's lifecycle without emitting again" in owner
    evaluations = _read("src/skills/evaluations/deployment-flow.md")
    assert "../topics/push-experience.md#push-telemetry" in evaluations
    assert "Reuse an enclosing approved Push batch's lifecycle without emitting again" in evaluations
    assert "Run, Request Review and reviewer completion do not acquire a Push lifecycle" in evaluations
    authoring = _read("src/skills/topics/authoring-experience.md")
    assert "otherwise own the standalone instruction-save batch" in authoring
    push_experience = _read("src/skills/topics/push-experience.md")
    assert "Separate later approvals start separate batches" in push_experience
    assert "recovery of the same approved operation does not" in push_experience


def test_push_telemetry_keeps_legacy_results_separate_from_save_evidence():
    telemetry = _read("src/skills/topics/push-experience.md").split(
        "## Push telemetry\n", 1,
    )[1]
    normalized = " ".join(telemetry.split())
    assert "cancellation before execution emits no Push events" in telemetry
    assert "Do not add an initial `push` usage call" in telemetry
    assert "A returned write error counts as operation failure" in telemetry
    assert "Preserve uncertainty and any confirmed saves in the maker-facing report" in telemetry
    assert "non-fatal baseline-refresh or cleanup warning remains telemetry success" in telemetry
    assert "omit the terminal sequence while that failure remains" in telemetry
    assert "all verified already-current content without writing" in telemetry
    assert "On cancellation after execution starts, omit completion, deploy and usage events" in telemetry
    assert "including when some components were already saved" in telemetry
    assert "Separately completed batches retain their events" in telemetry
    assert "authoritative no-write verification for every approved operation" in telemetry
    assert "A zero update count alone is insufficient" in telemetry
    assert (
        "Failed, unconfirmed, paused or cancelled operations and unresolved "
        "hard local failures do not qualify"
    ) in telemetry
    assert "For verified already-current execution, omit the `agent-deploy` command" in telemetry
    assert "still emit one `push` usage event" in telemetry
    assert "| `success` | not emitted | empty | empty | empty |" in normalized
    assert "Missing or negative elapsed time is unavailable evidence, not zero" in telemetry
    assert "Do not retry unknown delivery" in telemetry
    assert (
        "| `failure` | `server_error` | `PUSH_PARTIAL_FAILURE` | "
        "`DEPLOY_PARTIAL_FAILURE` | `runtime` |"
    ) in normalized


def test_push_telemetry_uses_known_environment_metadata_without_lookup():
    telemetry = _read("src/skills/topics/push-experience.md").split(
        "## Push telemetry\n", 1,
    )[1]
    assert "only for a result that emits `agent-deploy`" in telemetry
    assert "not the agent's Dev/Prod realm" in telemetry
    assert "Honor `ESS_ADK_DEPLOY_TARGET` only when it is `sandbox` or `production`" in telemetry
    assert "do not borrow another agent's cached SKU" in telemetry
    assert "Use an empty string when no matching SKU is available" in telemetry
    assert "adk_telemetry.classify_deploy_target(sys.argv[1])" in telemetry
    assert "a telemetry default, not proof of environment type" in telemetry
    assert "Do not make an additional environment API request solely for telemetry" in telemetry
    assert "Do not switch identity, prompt for authentication or mutate environment configuration" in telemetry


def test_advisories_have_structured_issue_effect_and_own_action_line():
    contract = _read("src/skills/topics/authoring-experience.md")
    advisory = (
        "> - {Advisory issue}. {Practical effect}.\n>\n"
        "> ##### SUGGESTED ACTION\n>\n"
        "> {Concrete next action}."
    )
    assert contract.count(advisory) == 3
    assert ">   **Suggested action:**" not in contract
    assert (
        "`{Concrete next action}` is a specific, relevant recommended step "
        "to investigate or address the issue, identifying what to inspect, "
        "test or change and its purpose."
    ) in contract
    assert "Ordinary factual notes retain their existing form." in contract


def test_initial_routing_conflict_decision_precedes_push_and_preserves_exact_scope():
    contract = _read("src/skills/topics/authoring-experience.md")
    initial = contract.split("### Initial routing-conflict decision\n", 1)[1].split(
        "### Topic outcomes\n", 1
    )[0]
    assert (
        "**Resolve the routing conflict in the Agent Instructions**, "
        "**Push topic anyway** and **Keep as draft**"
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
    contract = _read("src/skills/topics/authoring-experience.md")
    follow_up = contract.split(
        "### Combined routing-conflict and testing follow-up\n", 1
    )[1].split("### Targeted instruction-change preview and approval\n", 1)[0]
    question = json.loads(re.search(r"```json\n(.*?)\n```", follow_up, re.DOTALL)[1])
    assert question["requestedSchema"]["properties"]["action"]["enum"] == [
        "Resolve the routing conflict in the Agent Instructions",
        "Not now, Activate and test anyway.",
    ]
    assert "**Not now, Test anyway.**" in follow_up
    assert "does not approve an instruction push, activation or testing" in follow_up
    assert "Confirm authoritative Active state before sending a test message" in follow_up
    assert "do not silently repair it during testing" in follow_up
    assert "scoped batch/debugging consent rules" in follow_up
    assert "deliberate topic-only save" in follow_up
    assert "only when a routing conflict is newly discovered or materially changed" in follow_up
    assert "Do not repeat the resolution choice for the same conflict" in follow_up
    assert "Prepare instruction change for review" not in contract
    assert "> ##### ROUTING CONFLICTS" in follow_up
    assert "This routing conflict will likely block topic execution." in follow_up
    assert "Check the installed testing capability before offering a runnable test" in follow_up
    testing = _read("src/skills/topics/test/SKILL.md")
    assert "declined routing correction as an explicit exclusion" in testing
    assert "not blanket debugging consent" in testing
    assert "later authorized testing after Push topic anyway" in testing
    assert "Push topic anyway authorizes only the topic save, not testing" in testing


def test_instruction_correction_has_separate_preview_approval_and_truthful_outcomes():
    contract = _read("src/skills/topics/authoring-experience.md")
    preview = contract.split(
        "### Targeted instruction-change preview and approval\n", 1
    )[1].split("### Instruction-push outcomes and testing\n", 1)[0]
    assert "> ##### CURRENT WORDING" in preview
    assert "> ##### PROPOSED WORDING" in preview
    assert '"enum": ["Push instruction change", "Keep as draft"]' in preview
    assert "It does not authorize activation, testing or publication." in preview
    assert "concurrency and readback safeguards" in preview
    assert "> ##### INSTRUCTION DRAFT KEPT LOCALLY" in preview
    assert "AGENT INSTRUCTIONS ALREADY UP TO DATE" in contract
    assert "INSTRUCTION PUSH COULD NOT BE CONFIRMED" in contract
    assert "Topic execution has not yet been verified." in contract
    assert "complete `{Verified instruction-save result}` statement" in contract


def test_draft_and_partial_instruction_results_do_not_assume_a_topic_push():
    contract = _read("src/skills/topics/authoring-experience.md")
    preview = contract.split(
        "### Targeted instruction-change preview and approval\n", 1
    )[1].split("### Instruction-push outcomes and testing\n", 1)[0]
    outcomes = contract.split("### Instruction-push outcomes and testing\n", 1)[1].split(
        "\n## ", 1
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
        assert "../authoring-experience.md#initial-routing-conflict-decision" in guidance
        assert "../testing-experience.md#topic-testing-continuation" in guidance
        assert "existing authorization and declined corrections" in guidance
    for entry in ("create", "update", "push"):
        prompt = " ".join(_read(f".github/prompts/{entry}.prompt.md").split())
        assert "declined corrections" in prompt
        assert "newly discovered or materially changed conflict" not in prompt
    push = _read("src/skills/topics/push-experience.md")
    composed = push.split("### Composed Push report:", 1)[1].split(
        "## Push telemetry", 1
    )[0]
    assert "testing-experience.md#topic-testing-continuation" in composed
    testing = _read("src/skills/topics/testing-experience.md")
    offers = testing.split("### Testing offers\n", 1)[1].split("### Browser readiness", 1)[0]
    assert "honor the initial routing-conflict decision" in offers
    assert "only for a newly discovered or materially changed conflict" in offers
    assert "The topic-only Push did not authorize testing." in offers
    assert "Do not offer runnable testing of topic changes left local" in offers
    assert "do not repeat the ordinary testing offer or silently fix that conflict" in offers


def test_readiness_message_has_maker_actions_and_a_separate_readiness_control():
    contract = _read("src/skills/topics/testing-experience.md")
    assert (
        "> ##### TEST BROWSER READINESS\n>\n"
        "> ##### TOPIC\n>\n> {Topic title}\n>\n"
        "> ##### TARGET\n>\n> {Agent name}, {Environment name}\n>\n"
        "> In the prepared test browser, sign in with a test account.\n>\n"
        "> Open the Test chat pane and leave its message box empty and idle.\n>\n"
        "> After you confirm readiness,"
    ) in contract
    readiness = contract.split("### Browser readiness and testing goal\n", 1)[1].split(
        "### Pause, stop and resume\n", 1
    )[0]
    question = json.loads(re.search(r"```json\n(.*?)\n```", readiness, re.DOTALL)[1])
    assert question["requestedSchema"]["properties"]["action"]["enum"] == [
        "Ready to test", "Not ready, keep paused", "Stop without sending",
    ]
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
    contract = _read("src/skills/topics/testing-experience.md")
    instructions = " ".join(_read(".github/copilot-instructions.md").split())
    assert (
        "for existing topic conversation results, read "
        "`src/skills/topics/testing-experience.md` and use "
        "`{topic_test_results}` with saved observations."
    ) in instructions
    assert "retrieving topic results does not start new testing or authorize changes" in instructions
    assert "### Topic debugging outcome: `{topic_test_results}`" in contract
    assert "> ##### EVIDENCE\n>\n> {Available evidence links}" in contract
    assert "including `evidenceDirectory` for topic tests" in contract
    assert "A missing screenshot does not make a saved result file unavailable." in contract
    assert "For pause/stop, keep the fixed acknowledgement separate" in contract
    assert "unfinished or unobserved behavior and material uncertainty" in contract
    assert "activation-only explanations and control" in contract
    assert "activation permission adds no edit permission" in contract
    assert '"title": "Topic activation"' in contract
    assert "Preserve completed work and report it separately using `{topic_test_results}`." in contract
    assert "reusing valid context and permissions" in contract
    assert "This is an informational report, not another approval gate." in contract


def test_debugging_outcome_has_goal_and_only_needed_recommendation_without_loop_ledger():
    contract = _read("src/skills/topics/testing-experience.md")
    report = contract.split("### Topic debugging outcome: `{topic_test_results}`", 1)[1].split(
        "### Testing offers", 1
    )[0]
    prefix = (
        "> ##### TOPIC DEBUGGING OUTCOME\n>\n"
        "> ##### TOPIC\n>\n> {Topic title}\n>\n"
        "> ##### TARGET\n>\n> {Agent name}, {Environment name}\n>\n"
        "> ##### GOAL\n>\n> {Latest authoring goal}\n>\n"
    )
    assert prefix + "> ##### OUTCOME\n>\n> {Observed runtime outcome}\n\n" in report
    assert (
        prefix + "> ##### OUTCOME\n>\n> {Current outcome and obstacle}\n>\n"
        "> ##### RECOMMENDATION\n>\n> {Concrete tweak or next action}\n\n"
    ) in report
    assert report.count("> ##### RECOMMENDATION") == 1
    for retired in ("| Test |", "**Fixes made**", "**Remaining issues**", "Retest:", "fn:"):
        assert retired not in report
    assert "When the requested behavior is observed, render:" in report
    assert "When a change or assistance is needed, render:" in report
    assert "These are applicable examples, not mandatory report categories." in report
    assert "conditional-section markers" not in contract


def test_scoped_runtime_goal_is_advisory_and_keeps_fixable_work_in_scope():
    contract = _read("src/skills/topics/testing-experience.md")
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
    assert "../experience-contract.md#topic-selection" in update
    assert "candidate titles and short purposes" in contract
    assert "Accept a free-text name or description without requiring name recall" in contract
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
        in _read("src/skills/topics/testing-experience.md")
    )
    assert "Honor explicit no-activation requests" in _read("src/skills/topics/testing-experience.md")
