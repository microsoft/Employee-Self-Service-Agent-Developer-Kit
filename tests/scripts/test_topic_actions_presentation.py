# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Exact maker copy and truthful presentation of synthetic topic evidence."""

from copy import deepcopy

import pytest

from topic_actions_execution import TopicActionSession, agent_set_overview
from topic_actions_catalog import load_catalog
from topic_actions_presentation import approval_question, result_text, review_text
from tests.scripts.test_topic_actions_runtime import dev_native_backend


def _review():
    return {
        "target": {"tenantId": "tenant", "environmentId": "environment", "agentId": "agent"},
        "account": "maker@example.com", "action": "enable", "selectedSets": ["alpha"],
        "setNames": {"alpha": "Synthetic alpha", "beta": "Synthetic beta"},
        "members": [
            {"setKey": "alpha", "schemaName": "alpha.topic", "componentId": "a"},
            {"setKey": "alpha", "schemaName": "alpha.shared", "componentId": "shared"},
        ],
        "currentStates": [
            {"componentId": "a", "state": "Off"},
            {"componentId": "shared", "state": "On"},
        ],
        "proposedChanges": [{"componentId": "a", "before": "Off", "after": "On"}],
        "alreadyCorrect": ["shared"], "protected": [],
        "blockers": [], "warnings": ["write_permission_enforced_by_service"],
    }


def _result(status="completed", *, submitted=True):
    return {
        "status": status, "completed": status in ("completed", "already_correct"),
        "writeStatus": "submitted" if submitted else "not_attempted",
        "plan": _review(), "blockers": [], "warnings": ["internal-warning"],
        "topics": [
            {"componentId": "a", "state": "On", "status": "changed"},
            {"componentId": "shared", "state": "On", "status": "already_correct"},
        ],
    }


def test_complete_review_has_exact_copy_without_routine_diagnostics():
    review = _review()
    original = deepcopy(review)
    assert review_text(review) == (
        "## Review topic changes\n"
        "- Action: Enable\n"
        "- Account: maker@example.com\n"
        "- Agent: agent\n"
        "- Environment: environment\n"
        "- Tenant: tenant\n"
        "- Topic sets: Synthetic alpha\n\n"
        "### Synthetic alpha\n\n"
        "| **#** | **Integration** | **Topic** | **Current state** | **Planned change** |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| 1 | Synthetic alpha | alpha.topic | Disabled | Enable |\n"
        "| 2 | Synthetic alpha | alpha.shared | Enabled | No change - already enabled |\n\n"
        "The skill will not publish."
    )
    assert review == original


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_review_omits_count_summary_when_every_topic_needs_change(action):
    review = _review()
    before, desired = ("Off", "On") if action == "enable" else ("On", "Off")
    review.update(action=action, alreadyCorrect=[])
    review["currentStates"] = [
        {"componentId": identity, "state": before} for identity in ("a", "shared")
    ]
    review["proposedChanges"] = [
        {"componentId": identity, "before": before, "after": desired}
        for identity in ("a", "shared")
    ]
    text = review_text(review)
    assert f"topics to {action}" not in text
    assert "0 no change" not in text
    assert text.count(f"| {action.title()} |") == 2


@pytest.mark.parametrize("action,before,desired", [
    ("enable", "Off", "On"), ("disable", "On", "Off"),
])
def test_chelsea_review_expresses_requested_action_in_planned_change_only(action, before, desired):
    review = _review()
    review.update(action=action, setIntegrations={"alpha": "Workday"})
    review["currentStates"] = [
        {"componentId": "a", "state": before}, {"componentId": "shared", "state": desired},
    ]
    review["proposedChanges"] = [{"componentId": "a", "before": before, "after": desired}]
    original = deepcopy(review)
    text = review_text(review)
    current = "Disabled" if before == "Off" else "Enabled"
    matching = "enabled" if desired == "On" else "disabled"
    assert "| **#** | **Integration** | **Topic** | **Current state** | **Planned change** |" in text
    assert f"| 1 | Workday | alpha.topic | {current} | {action.title()} |" in text
    assert f"| 2 | Workday | alpha.shared | {matching.title()} | No change - already {matching} |" in text
    assert "Requested state" not in text
    assert "- Account: maker@example.com" in text and "- Tenant: tenant" in text
    assert review == original


@pytest.mark.parametrize("action", ["enable", "disable"])
@pytest.mark.parametrize("multiple", [False, True])
def test_approval_card_uses_reviewed_action_unique_changes_and_selected_set_names(action, multiple):
    review = _review()
    review["action"] = action
    if multiple:
        review["selectedSets"].append("beta")
        review["members"].append({**review["members"][0], "setKey": "beta"})
        review["proposedChanges"].extend([
            dict(review["proposedChanges"][0]),
            {"componentId": "b", "before": "Off", "after": "On"},
        ])
    original = deepcopy(review)
    count = "2 topics" if multiple else "1 topic"
    sets = "Synthetic alpha and Synthetic beta" if multiple else "Synthetic alpha"
    assert approval_question(review) == {
        "header": f"{action.title()} the {count} shown above?",
        "question": f"{action.title()} the {count} shown above?",
        "multiSelect": False,
        "options": [
            {
                "label": f"{action.title()} {count} for {sets}.",
                "description": "Apply only the changes shown above.",
            },
            {"label": "Not now", "description": "Leave topics unchanged."},
        ],
        "allowFreeformInput": True,
    }
    assert review == original


@pytest.mark.parametrize("blocked", [False, True])
def test_approval_card_is_absent_for_no_changes_or_blocked_review(blocked):
    review = _review()
    if blocked:
        review["blockers"] = ["unknown_state"]
    else:
        review["proposedChanges"] = []
    assert approval_question(review) is None


@pytest.mark.parametrize(("states", "expected"), [
    ({"a": "On", "shared": "On", "b": "On"}, ["Enabled", "Enabled"]),
    ({"a": "Off", "shared": "Off", "b": "Off"}, ["Disabled", "Disabled"]),
    ({"a": "On", "shared": "Off", "b": "Off"}, ["Mixed", "Disabled"]),
])
def test_agent_set_overview_aggregates_present_topics_without_a_topic_dump(states, expected):
    backend = dev_native_backend(selected=("alpha", "beta"), before=states)
    overview = agent_set_overview(backend.read(), backend.catalog)
    assert overview["setCount"] == 2
    assert overview["discoveryComplete"]
    assert [item["state"] for item in overview["sets"]] == expected
    assert [item["topicCount"] for item in overview["sets"]] == [2, 2]
    assert overview["selectionQuestion"] == {
        "header": "Which topic sets would you like to change?",
        "question": "Which topic sets would you like to change?",
        "multiSelect": True,
        "options": [
            {"label": "Synthetic alpha"},
            {"label": "Synthetic beta"},
        ],
        "allowFreeformInput": False,
    }
    assert overview["userMessage"] == (
        "## Topic sets\n\n"
        "| **Topic set** | **Topics** | **State** |\n"
        "| --- | --- | --- |\n"
        f"| Synthetic alpha | 2 | {expected[0]} |\n"
        f"| Synthetic beta | 2 | {expected[1]} |"
    )
    assert "synthetic.hr.topic" not in overview["userMessage"]
    assert "Before you approve" not in overview["userMessage"]
    assert overview["writeStatus"] == "not_attempted"
    backend.components.read_components.assert_called_once()
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("change", ["fewer_topics", "unknown_state", "ambiguous_identity", "absent"])
def test_agent_set_overview_distinguishes_smaller_sets_unknown_states_and_absence(change):
    backend = dev_native_backend(selected=("alpha", "beta"))
    body = deepcopy(next(backend.components.read_components.side_effect))
    if change == "fewer_topics":
        body["botComponentChanges"].pop(0)
    elif change == "unknown_state":
        body["botComponentChanges"][0]["component"]["status"] = "Active"
    elif change == "ambiguous_identity":
        duplicate = deepcopy(body["botComponentChanges"][0])
        duplicate["component"]["id"] = "duplicate"
        body["botComponentChanges"].append(duplicate)
    else:
        body["botComponentChanges"] = body["botComponentChanges"][-1:]
    backend.components.read_components.side_effect = [body]
    result = agent_set_overview(backend.read(), backend.catalog)
    if change == "absent":
        assert result["setCount"] == 0
        assert result["sets"] == []
        assert result["selectionQuestion"] is None
        assert "No supported topic sets are available in this agent." in result["userMessage"]
    else:
        alpha = result["sets"][0]
        assert alpha["key"] == "alpha"
        assert alpha["state"] == ("Disabled" if change == "fewer_topics" else "Unknown")
        assert alpha["topicCount"] == (
            1 if change == "fewer_topics" else None if change == "ambiguous_identity" else 2
        )
        assert result["discoveryComplete"] is (change != "ambiguous_identity")
        if change == "ambiguous_identity":
            assert result["selectionQuestion"] is None
    assert "No topics were changed." not in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize(("agent_schema", "expected"), [
    ("gptagent_copilotforemployeeselfservicehr", [
        ("workday-da-hr", "Workday HR Topics", "Enabled"),
        ("servicenow-hr", "ServiceNow HR Topics", "Disabled"),
    ]),
    ("msdyn_copilotforemployeeselfservicedahr", [
        ("workday-da-hr", "Workday HR Topics", "Enabled"),
    ]),
    ("msdyn_copilotforemployeeselfservicedait", [
        ("workday-da-it", "Workday IT Topics", "Enabled"),
    ]),
    ("gptagent_copilotforemployeeselfserviceit", [
        ("servicenow-it", "ServiceNow IT Topics", "Disabled"),
    ]),
])
@pytest.mark.parametrize("smaller_sets", [False, True])
def test_agent_set_overview_uses_bundled_names_and_only_present_sets(agent_schema, expected, smaller_sets):
    catalog = load_catalog()
    document = catalog.document()
    backend = dev_native_backend(selected=tuple(item["key"] for item in document["sets"]))
    backend.catalog = catalog
    body = deepcopy(next(backend.components.read_components.side_effect))
    template = body["botComponentChanges"][0]
    body["bot"]["schemaName"] = agent_schema
    body["botComponentChanges"] = []
    package = next(
        item["key"] for item in document["packages"] if agent_schema in item["agentSchemaNames"]
    )
    expected_counts = []
    for key, _, state in expected:
        topic_set = next(item for item in document["sets"] if item["key"] == key)
        variant = next(item for item in topic_set["sourceVariants"] if item["packageKey"] == package)
        schemas = variant["memberSchemaNames"][:2] if smaller_sets else variant["memberSchemaNames"]
        expected_counts.append(len(schemas))
        for schema in schemas:
            row = deepcopy(template)
            row["component"].update(
                id=f"synthetic-{len(body['botComponentChanges'])}", schemaName=schema,
                state="Active" if state == "Enabled" else "Inactive",
                status="Active" if state == "Enabled" else "Inactive",
            )
            body["botComponentChanges"].append(row)
    backend.components.read_components.side_effect = [body]
    result = agent_set_overview(backend.read(), catalog)
    assert result["setCount"] == len(expected) and result["discoveryComplete"]
    assert [(item["key"], item["name"], item["state"]) for item in result["sets"]] == expected
    assert [item["topicCount"] for item in result["sets"]] == expected_counts
    assert result["selectionQuestion"]["options"] == [
        {"label": name} for _, name, _ in expected
    ]
    assert "not available" not in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


def test_agent_set_overview_does_not_hide_unresolved_source_families_as_an_empty_list():
    catalog = load_catalog()
    document = catalog.document()
    backend = dev_native_backend(selected=tuple(item["key"] for item in document["sets"]))
    backend.catalog = catalog
    body = deepcopy(next(backend.components.read_components.side_effect))
    body["bot"]["schemaName"] = document["packages"][0]["agentSchemaNames"][0]
    body["botComponentChanges"] = body["botComponentChanges"][:1]
    topic_set = next(item for item in document["sets"] if item["key"] == "servicenow-it")
    body["botComponentChanges"][0]["component"]["schemaName"] = (
        topic_set["sourceVariants"][0]["memberSchemaNames"][0]
    )
    backend.components.read_components.side_effect = [body]
    result = agent_set_overview(backend.read(), catalog)
    assert result["setCount"] == 1
    assert not result["discoveryComplete"]
    assert result["selectionQuestion"] is None
    assert result["sets"][0]["key"] == "servicenow-it"
    assert result["sets"][0]["state"] == "Unknown"
    assert result["sets"][0]["topicCount"] is None
    assert "Some topic sets could not be fully identified." in result["userMessage"]
    assert result["userMessage"].endswith("Some topic sets could not be fully identified.")
    assert "No supported topic sets are available" not in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


def test_source_catalog_listing_keeps_availability_caveat_without_mutation_commentary():
    result = {
        "status": "source_catalog_only",
        "sets": [{"name": "Synthetic alpha", "key": "alpha"}],
    }
    assert result_text(result) == (
        "Source-defined topic sets (availability not yet checked):\n"
        "- Synthetic alpha: alpha"
    )


def test_agent_set_listing_does_not_require_a_write_change_token():
    backend = dev_native_backend(selected=("alpha", "beta"))
    body = deepcopy(next(backend.components.read_components.side_effect))
    body.pop("changeToken")
    backend.components.read_components.side_effect = [body]
    result = agent_set_overview(backend.read(), backend.catalog)
    assert result["setCount"] == 2
    assert result["discoveryComplete"]
    assert [item["state"] for item in result["sets"]] == ["Disabled", "Disabled"]
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("action", ["enable", "disable"])
@pytest.mark.parametrize("blocked", [False, True])
def test_review_omits_entire_approval_notes_section_but_preserves_diagnostics(action, blocked):
    review = _review()
    review["action"] = action
    review["blockers"] = ["unknown_state"] if blocked else []
    without_warnings = review_text(review)
    review["warnings"] += [
        "catalog_release_untrusted", "catalog_review_pending",
        "membership_review_pending", "installed_package_unverified",
        "incomplete_membership", "incomplete_coverage", "set_coverage_unverified",
        "custom_dependency_coverage_unverified", "classification_unverified",
        "required_coverage_unverified", "unknown_protection",
        "native_stale_write_protection_unqualified", "native_batch_behavior_unqualified",
        "native_draft_published_effects_unqualified", "future_sensitive_internal_detail",
    ]
    original = deepcopy(review)
    text = review_text(review)
    assert text == without_warnings
    assert "Before you approve" not in text
    assert "About this review" not in text
    assert "Turning topics Off" not in text
    assert all(code not in text for code in review["warnings"])
    assert "warning" not in text.casefold()
    assert review == original


def test_disable_review_keeps_protection_and_current_state_without_approval_notes():
    review = _review()
    review.update(action="disable", alreadyCorrect=[], proposedChanges=[])
    review["protected"] = [{"componentId": "shared", "reason": "shared", "protectingSets": ["beta"]}]
    text = review_text(review)
    assert "| alpha.shared | Enabled | Kept unchanged: used by Synthetic beta |" in text
    assert "Before you approve" not in text


def test_preview_does_not_infer_membership_or_collect_approval():
    review = _review()
    review["selectedSets"].append("unresolved-set")
    review["members"][0]["componentId"] = None
    text = review_text(review, preview=True)
    assert "| alpha.topic | Unknown |" in text
    assert "### unresolved-set\n\n| **Topic** | **Current state** |\n| --- | --- |\n| Unresolved | Unknown |" in text
    assert "Before you approve" not in text
    assert "Requested state" not in text
    assert "Plan" not in text
    assert "No topics were changed." not in text


def test_preview_is_only_inventory_even_with_write_limitations():
    review = _review()
    review["warnings"] += [code for code in (
        "catalog_release_untrusted", "installed_package_unverified", "unknown_protection",
        "native_stale_write_protection_unqualified", "native_batch_behavior_unqualified",
        "native_draft_published_effects_unqualified", "future_limitation",
    )]
    review["action"] = "disable"
    original = deepcopy(review)
    assert review_text(review, preview=True) == (
        "## Topics\n\n"
        "### Synthetic alpha\n\n"
        "| **Topic** | **Current state** |\n"
        "| --- | --- |\n"
        "| alpha.topic | Disabled |\n"
        "| alpha.shared | Enabled |"
    )
    assert review == original
    result = _result("preview", submitted=False)
    result["plan"] = review
    assert result_text(result) == review_text(review, preview=True)


@pytest.mark.parametrize("preview", [False, True])
def test_topic_names_are_shortened_only_for_display(preview):
    review = _review()
    schema = "gptagent_copilotforemployeeselfservicehr.topic.WorkdayGetVisas"
    review["members"][0]["schemaName"] = schema
    text = review_text(review, preview=preview)
    assert "| WorkdayGetVisas | Disabled |" in text
    assert "gptagent" not in text
    assert review["members"][0]["schemaName"] == schema


def test_blocked_inventory_keeps_resolution_failure_without_showing_an_execution_plan():
    review = _review()
    review["blockers"] = ["missing_member"]
    review["members"][0]["componentId"] = None
    text = review_text(review, preview=True)
    assert "I couldn't identify all the requested topics in this agent." in text
    assert "**NEXT STEPS**\n\nVerify the topic identities in the selected agent, then make a new request." in text
    assert "Requested state" not in text
    assert "Eligible changes" not in text
    result = _result("blocked", submitted=False)
    result.update(plan=review, blockers=review["blockers"])
    assert result_text(result) == text


def test_absent_topics_have_short_copy_without_approval_or_submission():
    backend = dev_native_backend()
    body = backend.components.read_components.side_effect
    packets = list(body)
    for packet in packets:
        packet["botComponentChanges"] = [
            row for row in packet["botComponentChanges"]
            if row["component"]["id"] not in {"a", "shared", "b"}
        ]
    backend.components.read_components.side_effect = packets
    result = TopicActionSession(backend, "disable").run(
        lambda _: pytest.fail("Missing topics must not request approval."),
    )
    assert result["status"] == "blocked"
    assert result["userMessage"] == (
        "Synthetic alpha are not available in this agent.\n\n"
        "**NEXT STEPS**\n\nChoose a topic set available on this agent."
    )
    assert result["blockers"]
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("agent_schema", [
    package["agentSchemaNames"][0] for package in load_catalog().document()["packages"]
])
@pytest.mark.parametrize("action", ["enable", "disable"])
@pytest.mark.parametrize("preview", [False, True])
def test_absent_servicenow_it_has_friendly_copy_across_bundled_agent_families(
    agent_schema, action, preview,
):
    backend = dev_native_backend(selected=("servicenow-it",))
    backend.catalog = load_catalog()
    body = deepcopy(next(backend.components.read_components.side_effect))
    body["bot"]["schemaName"] = agent_schema
    backend.components.read_components.side_effect = [body]
    result = TopicActionSession(backend, action).run(
        lambda _: pytest.fail("An absent set must not request approval."),
        preview=preview, review_only=not preview,
    )
    assert result["status"] == "blocked"
    assert result["writeStatus"] == "not_attempted"
    assert "set_absent:servicenow-it" in result["blockers"]
    assert result["userMessage"] == (
        "ServiceNow IT Topics are not available in this agent.\n\n"
        "**NEXT STEPS**\n\nChoose a topic set available on this agent."
    )
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("case_alias", [False, True])
def test_unsupported_family_with_matching_topics_is_not_reported_as_absent(case_alias):
    backend = dev_native_backend(selected=("servicenow-it",))
    backend.catalog = load_catalog()
    document = backend.catalog.document()
    topic_set = next(item for item in document["sets"] if item["key"] == "servicenow-it")
    schema = topic_set["sourceVariants"][0]["memberSchemaNames"][0]
    body = deepcopy(next(backend.components.read_components.side_effect))
    body["bot"]["schemaName"] = document["packages"][0]["agentSchemaNames"][0]
    body["botComponentChanges"][0]["component"]["schemaName"] = schema.upper() if case_alias else schema
    backend.components.read_components.side_effect = [body]
    result = TopicActionSession(backend, "disable").run(
        lambda _: pytest.fail("An unsupported family cannot request approval."),
    )
    assert result["status"] == "blocked"
    assert "ambiguous_or_unsupported_set:servicenow-it" in result["blockers"]
    assert "not available" not in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


def test_missing_set_copy_names_the_set_and_keeps_other_failures_visible():
    review = _review()
    review["selectedSets"] = ["servicenow-it"]
    review["blockers"] = ["set_absent:servicenow-it", "authentication_failed"]
    assert review_text(review, preview=True) == (
        "servicenow-it topics are not available in this agent.\n"
        "The signed-in account could not be verified.\n\n"
        "**NEXT STEPS**\n\nVerify the signed-in account, then make a new request."
    )


def test_ambiguous_topics_are_not_reported_as_absent():
    review = _review()
    review["blockers"] = ["ambiguous_member:alpha:alpha.topic"]
    text = review_text(review, preview=True)
    assert "I couldn't identify all the requested topics in this agent." in text
    assert "not available" not in text
    assert "administrator" not in text


def test_entry_blockers_override_an_otherwise_executable_plan_in_display():
    result = _result("blocked", submitted=False)
    result["blockers"] = ["authentication_failed"]
    text = result_text(result)
    assert "**NEXT STEPS**\n\nVerify the signed-in account, then make a new request." in text
    assert "The signed-in account could not be verified." in text
    assert "Eligible changes:" not in text
    assert "| alpha.topic |" not in text
    assert "Before you approve" not in text


@pytest.mark.parametrize(("status", "text"), [
    ("cancelled", "Canceled."),
    ("denied", "Not approved."),
])
def test_cancellation_and_denial_have_exact_short_copy(status, text):
    assert result_text(_result(status, submitted=False)) == text


def test_completed_and_noop_results_do_not_repeat_review_notices():
    result = _result()
    assert result_text(result) == (
        "## Topic changes completed\n\n"
        "**1 topic enabled and verified.** 1 already enabled, unchanged.\n\n"
        "- Agent: agent\n- Environment: environment\n- Account: maker@example.com\n\n"
        "### Synthetic alpha\n\n"
        "| **#** | **Integration** | **Topic** | **Result** |\n| --- | --- | --- | --- |\n"
        "| 1 | Synthetic alpha | alpha.topic | Enabled |\n"
        "| 2 | Synthetic alpha | alpha.shared | Already enabled - unchanged |"
    )
    result.update(status="already_correct", writeStatus="not_attempted")
    text = result_text(result)
    assert text.startswith("## No change needed.\n")
    assert "No topics were changed." not in text
    assert "internal-warning" not in text


def test_partial_state_success_is_not_presented_as_complete_preservation():
    result = _result("partial")
    result["topics"][0]["status"] = "observed_desired"
    text = result_text(result)
    assert text.startswith("## Changes submitted; verification incomplete.\n")
    assert "Requested states observed: 2/2 topics." in text
    assert "Preservation of other content and topic states could not be fully verified." in text
    assert text.endswith(
        "**NEXT STEPS**\n\n"
        "Make a new request to check current states and review any further changes."
    )
    assert "Next step:" not in text
    result["topics"][0].update(state="Off", status="unchanged")
    text = result_text(result)
    assert "Requested states observed: 1/2 topics." in text
    assert "Some requested topic states could not be verified. Full completion is not confirmed." in text
    assert "Preservation of other content" not in text
    assert text.count("**NEXT STEPS**\n\n") == 1
    assert "Next step:" not in text


def test_uncertain_submission_and_read_failure_never_claim_success_or_no_write():
    result = _result("unverified")
    result["blockers"] = ["readback_failed", "fresh_approval_required"]
    result["topics"][0].update(state="Unknown", status="unverified")
    text = result_text(result)
    assert "Observed states do not confirm that this request made the changes." in text
    assert "The topic states could not be read after submission." in text
    assert "No topics were changed." not in text
    assert "Completed." not in text


def test_expired_review_and_storage_failure_are_plain_language_without_a_submission():
    result = _result("review_required", submitted=False)
    result["topics"] = []
    result["blockers"] = ["approval_expired"]
    assert result_text(result) == (
        "Approval expired.\n\n"
        "**NEXT STEPS**\n\n"
        "Make a new request for a fresh review and approval."
    )
    result.update(status="review_required", blockers=["review_storage_unavailable"])
    text = result_text(result)
    assert "The pending review could not be saved or read safely." in text
    assert "Changes submitted" not in text
    assert text.endswith("**NEXT STEPS**\n\nMake a new request for a fresh review.")


def test_remote_labels_cannot_break_the_review_table_or_inject_markup():
    review = _review()
    review["members"][0]["schemaName"] = "topic|<script>\n`approve`\x1b"
    text = review_text(review)
    assert "topic\\|&lt;script&gt; \\`approve\\`" in text
    assert "<script>" not in text and "\x1b" not in text
    assert "\n`approve`" not in text


def test_native_controller_attaches_fixed_copy_without_dropping_diagnostics_or_approval():
    backend = dev_native_backend(after={"a": "On", "shared": "On"})
    reviews = []
    result = TopicActionSession(backend, "enable").run(
        lambda review: reviews.append(deepcopy(review)) or "approve",
    )
    assert result["completed"] and len(reviews) == 1
    assert reviews[0]["userMessage"] == review_text(reviews[0])
    assert result["userMessage"] == result_text(result)
    assert "native_draft_published_effects_unqualified" in reviews[0]["warnings"]
    assert "native_draft_published_effects_unqualified" not in reviews[0]["userMessage"]
    assert "Current state" in reviews[0]["userMessage"]
    assert reviews[0]["setNames"]["alpha"] == "Synthetic alpha"
    assert reviews[0]["setIntegrations"]["alpha"] == "Synthetic"
    assert "| Synthetic | a | Enabled |" in result["userMessage"]
    assert "### Synthetic alpha" in reviews[0]["userMessage"]
    assert result["plan"]["selectedSets"] == ["alpha"]
    assert {topic["state"] for topic in result["topics"]} == {"On"}
    backend.components.submit_state_payload.assert_called_once()


@pytest.mark.parametrize("action", ["enable", "disable"])
@pytest.mark.parametrize("surface", ["review", "preview", "result"])
def test_grouped_tables_show_shared_members_once_with_all_associated_sets(action, surface):
    review = _review()
    before, desired = ("Off", "On") if action == "enable" else ("On", "Off")
    review.update(
        action=action, selectedSets=["alpha", "beta"],
        setIntegrations={"alpha": "Workday", "beta": "ServiceNow"},
    )
    review["members"].extend([
        {"setKey": "beta", "schemaName": "alpha.shared", "componentId": "shared"},
        {"setKey": "beta", "schemaName": "beta.topic", "componentId": "b"},
    ])
    review["currentStates"] = [
        {"componentId": "a", "state": before},
        {"componentId": "shared", "state": desired},
        {"componentId": "b", "state": before},
    ]
    review["proposedChanges"] = [
        {"componentId": identity, "before": before, "after": desired} for identity in ("a", "b")
    ]
    original = deepcopy(review)
    if surface == "result":
        result = _result()
        result.update(plan=review, topics=[
            {"componentId": identity, "state": desired, "status": status}
            for identity, status in (("a", "changed"), ("shared", "already_correct"), ("b", "changed"))
        ])
        text = result_text(result)
        assert f"**2 topics {'enabled' if action == 'enable' else 'disabled'} and verified.**" in text
    else:
        text = review_text(review, preview=surface == "preview")
        if surface == "review":
            assert f"topics to {action}" not in text
            assert "1 no change" not in text
            assert "protected" not in text
            assert f"| 1 | Workday | alpha.topic | {'Disabled' if action == 'enable' else 'Enabled'} |" in text
            assert f"| 1 | ServiceNow | beta.topic | {'Disabled' if action == 'enable' else 'Enabled'} |" in text
            assert "| 1 | Workday; ServiceNow | alpha.shared |" in text
            assert "Requested state" not in text
    assert "### Synthetic alpha" in text
    assert "### Synthetic beta" in text
    assert "### Shared topics: Synthetic alpha; Synthetic beta" in text
    assert text.count("| alpha.shared |") == 1
    assert text.count("| alpha.topic |") == 1
    assert text.count("| beta.topic |") == 1
    assert " On " not in text and " Off " not in text
    assert review == original


@pytest.mark.parametrize("action,desired,label", [
    ("enable", "On", "enabled"), ("disable", "Off", "disabled"),
])
def test_verified_no_change_shows_matching_topic_without_new_change_or_controls(action, desired, label):
    result = _result("already_correct", submitted=False)
    result["plan"]["action"] = action
    result["topics"] = [
        {"componentId": "a", "state": desired, "status": "already_correct"},
    ]
    text = result_text(result)
    assert f"**0 topics changed.** 1 already {label}, unchanged." in text
    assert "No topics were changed." not in text
    assert "| **#** | **Integration** | **Topic** | **Result** |" in text
    assert f"Already {label} - unchanged" in text and "Approve" not in text


def test_uncertain_results_keep_observed_states_separate_from_request_attribution():
    result = _result("unverified")
    result["blockers"] = ["write_request_rejected"]
    result["topics"][0]["status"] = "observed_desired"
    original = deepcopy(result)
    text = result_text(result)
    assert "| **#** | **Integration** | **Topic** | **Result** |" in text
    assert "| alpha.topic | Enabled observed; cause unconfirmed |" in text
    assert "| alpha.shared | Already enabled - unchanged |" in text
    assert "The service rejected the change request." in text
    assert "No topics were changed." not in text
    result["topics"][0].update(state="Unknown", status="unverified")
    assert "| alpha.topic | Unknown - final state could not be verified |" in result_text(result)
    result["topics"][0] = original["topics"][0]
    assert result == original


@pytest.mark.parametrize("preservation,status,expected", [
    ("verified", "completed_with_protections", "Kept unchanged (Enabled): used by Synthetic beta"),
    ("unverified", "unverified", "Enabled observed; preservation not verified: used by Synthetic beta"),
    ("violated", "partial", "Enabled observed; preservation not verified: used by Synthetic beta"),
])
def test_protected_result_does_not_claim_unchanged_when_preservation_is_unconfirmed(
    preservation, status, expected,
):
    result = _result(status)
    result.update(preservationStatus=preservation)
    result["plan"].update(action="disable", alreadyCorrect=[], protected=[
        {"componentId": "shared", "reason": "shared", "protectingSets": ["beta"]},
    ])
    result["topics"][0].update(
        state="Off", status="changed" if preservation == "verified" else "observed_desired",
    )
    result["topics"][1]["status"] = "protected"
    text = result_text(result)
    assert f"| alpha.shared | {expected} |" in text
    assert "protected" not in text.lower()
    assert text.count("### Synthetic alpha") == 1
    assert "| 1 | Synthetic alpha | alpha.topic |" in text
    assert "| 2 | Synthetic alpha | alpha.shared |" in text
    if preservation == "violated":
        assert "did not match the reviewed evidence." in text
        assert "could not be fully verified" not in text
    elif preservation == "unverified":
        assert "could not be fully verified" in text
        assert "did not match" not in text
    else:
        assert "Eligible topic changes completed." in text
        assert "**1 topic disabled and verified.**" in text


def test_friendly_group_and_protection_labels_cannot_inject_markdown_or_html():
    review = _review()
    review["setNames"]["alpha"] = "HR | <script>\n`approve`\x1b"
    review["setNames"]["beta"] = "IT | <script>\n`approve`\x1b"
    review.update(action="disable", protected=[
        {"componentId": "shared", "reason": "shared", "protectingSets": ["beta"]},
    ])
    text = review_text(review)
    assert "### HR \\| &lt;script&gt; \\`approve\\`" in text
    assert "used by IT \\| &lt;script&gt; \\`approve\\`" in text
    assert "<script>" not in text and "\x1b" not in text


@pytest.mark.parametrize("surface", ["review", "result"])
def test_integration_comes_from_metadata_and_cannot_inject_markup(surface):
    result = _result()
    result["plan"]["setNames"]["alpha"] = "Unrelated set display name"
    result["plan"]["setIntegrations"] = {"alpha": "Workday | <script>\n`approve`\x1b"}
    original = deepcopy(result)
    text = review_text(result["plan"]) if surface == "review" else result_text(result)
    assert "### Unrelated set display name" in text
    assert "| 1 | Workday \\| &lt;script&gt; \\`approve\\` | alpha.topic |" in text
    assert "<script>" not in text and "\x1b" not in text
    assert "0 protected" not in text and "submission was attempted" not in text
    if surface == "result":
        assert "did not publish" not in text and "Topic sets:" not in text
    assert result == original


@pytest.mark.parametrize("reason,problem,step", [
    ("access_denied", "denied read access", "check read access"),
    ("write_access_denied", "denied permission to change topics", "grant topic-edit access"),
    ("evidence_read_failed", "could not be read", "check the selected agent again"),
    ("setup_incomplete", "Workspace preparation is incomplete.", "Run /setup"),
    ("unknown_future_reason", "information needed to continue could not be verified",
     "check the selected agent again"),
])
def test_errors_show_specific_problem_and_one_supported_next_step(reason, problem, step):
    result = _result("blocked", submitted=False)
    result["blockers"] = [reason]
    original = deepcopy(result)
    text = result_text(result)
    assert problem in text and step in text
    assert text.count("**NEXT STEPS**\n\n") == 1
    assert "Next step:" not in text
    assert "| " not in text and "## Could not proceed" not in text
    assert "No topics were changed." not in text
    if reason == "access_denied":
        assert "topic-edit" not in text
    assert result == original


def test_reused_session_does_not_deny_that_an_earlier_invocation_changed_topics():
    result = _result("blocked", submitted=False)
    result.update(plan=None, topics=[], blockers=["session_consumed"])
    text = result_text(result)
    assert "has already been used" in text
    assert text.endswith("**NEXT STEPS**\n\nMake a new request for a fresh review and approval.")
    assert "No topics were changed." not in text


@pytest.mark.parametrize("action,state,label", [
    ("enable", "On", "enabled"), ("disable", "Off", "disabled"),
])
def test_native_no_change_report_keeps_full_grouped_results_without_approval(action, state, label):
    backend = dev_native_backend(
        selected=("alpha", "beta"), before={"a": state, "shared": state, "b": state},
    )
    result = TopicActionSession(backend, action).run(
        lambda _: pytest.fail("A no-change report must not introduce approval."),
        review_only=True,
    )
    text = result["userMessage"]
    assert result["status"] == "already_correct" and result["completed"]
    assert "**0 topics changed.** 3 already " + label + ", unchanged." in text
    assert "### Synthetic alpha" in text and "### Synthetic beta" in text
    assert "### Shared topics: Synthetic alpha; Synthetic beta" in text
    assert "| **#** | **Integration** | **Topic** | **Result** |" in text
    assert text.count("| a |") == 1
    assert text.count("| shared |") == 1
    assert text.count("| b |") == 1
    assert f"Already {label} - unchanged" in text
    assert "No topics were changed." not in text
    assert "Approve" not in text and "submission was attempted" not in text
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("surface", ["review", "preview", "overview", "result", "unverified"])
def test_native_tables_explicitly_emphasize_headers_without_html_or_spacing_hacks(surface):
    if surface in ("review", "preview"):
        text = review_text(_review(), preview=surface == "preview")
    elif surface == "overview":
        backend = dev_native_backend()
        text = agent_set_overview(backend.read(), backend.catalog)["userMessage"]
    else:
        text = result_text(_result(surface if surface == "unverified" else "completed"))
    header = next(line for line in text.splitlines() if line.startswith("| **"))
    assert all(cell.strip().startswith("**") and cell.strip().endswith("**")
               for cell in header.strip("|").split("|"))
    assert "<table" not in text and "style=" not in text
    assert "&nbsp;" not in text and "\u00a0" not in text


def test_41_topic_no_change_report_keeps_every_row_in_both_selected_sets():
    result = _result("already_correct", submitted=False)
    plan = result["plan"]
    plan.update(selectedSets=["alpha", "beta"], proposedChanges=[], setNames={
        "alpha": "Workday HR Topics", "beta": "ServiceNow HR Topics",
    })
    plan["members"] = [
        {"setKey": "alpha" if index < 21 else "beta",
         "schemaName": f"synthetic.hr.topic.ExampleTopic{index:02}",
         "componentId": str(index)}
        for index in range(41)
    ]
    plan["alreadyCorrect"] = [str(index) for index in range(41)]
    plan["currentStates"] = [{"componentId": str(index), "state": "On"} for index in range(41)]
    result["topics"] = [
        {"componentId": str(index), "state": "On", "status": "already_correct"} for index in range(41)
    ]
    original = deepcopy(result)
    text = result_text(result)
    assert "**0 topics changed.** 41 already enabled, unchanged." in text
    assert "### Workday HR Topics" in text and "### ServiceNow HR Topics" in text
    assert text.count("| **#** | **Integration** | **Topic** | **Result** |") == 2
    assert text.count(" | Already enabled - unchanged |") == 41
    assert "| ExampleTopic00 |" in text and "| ExampleTopic40 |" in text
    assert "submission was attempted" not in text and "Approve" not in text
    assert result == original
