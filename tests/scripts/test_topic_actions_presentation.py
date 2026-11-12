# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Exact maker copy and truthful presentation of synthetic topic evidence."""

from copy import deepcopy

import pytest

from topic_actions_execution import TopicActionSession, agent_set_overview
from topic_actions_catalog import load_catalog
from topic_actions_presentation import result_text, review_text
from tests.scripts.test_topic_actions_runtime import dev_native_backend


def _review():
    return {
        "target": {"tenantId": "tenant", "environmentId": "environment", "agentId": "agent"},
        "account": "maker@example.com", "action": "enable", "selectedSets": ["alpha"],
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
        "Action: Enable\n"
        "Account: maker@example.com\n"
        "Agent: agent\n"
        "Environment: environment\n"
        "Tenant: tenant\n"
        "Topic sets: alpha\n\n"
        "| Topic set | Topic | Current state | Requested state | Plan |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| alpha | alpha.topic | Off | On | Change |\n"
        "| alpha | alpha.shared | On | On | No change |\n\n"
        "Eligible changes: 1. No change: 1. Protected: 0.\n\n"
        "The skill will not publish."
    )
    assert review == original


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
        "header": "Topic sets",
        "question": "Which topic sets would you like to change?",
        "multiSelect": True,
        "options": [
            {"label": "Synthetic alpha", "description": f"{expected[0]}; 2 topics"},
            {"label": "Synthetic beta", "description": f"{expected[1]}; 2 topics"},
        ],
        "allowFreeformInput": False,
    }
    assert "Topic sets found: 2." in overview["userMessage"]
    assert f"| Synthetic alpha | 2 | {expected[0]} |" in overview["userMessage"]
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
    assert [item["label"] for item in result["selectionQuestion"]["options"]] == [
        name for _, name, _ in expected
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
    assert "No supported topic sets are available" not in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


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
    assert "| alpha | alpha.shared | On | Off | Keep unchanged: used by beta |" in text
    assert "Before you approve" not in text


def test_preview_does_not_infer_membership_or_collect_approval():
    review = _review()
    review["selectedSets"].append("unresolved-set")
    review["members"][0]["componentId"] = None
    text = review_text(review, preview=True)
    assert "| alpha | alpha.topic | Unknown |" in text
    assert "| unresolved-set | Unresolved | Unknown |" in text
    assert "Before you approve" not in text
    assert "Requested state" not in text
    assert "Plan" not in text
    assert text.endswith("No topics were changed.")


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
        "## Topics\nAgent: agent\nEnvironment: environment\n\n"
        "| Topic set | Topic | Current state |\n"
        "| --- | --- | --- |\n"
        "| alpha | alpha.topic | Off |\n"
        "| alpha | alpha.shared | On |\n\n"
        "No topics were changed."
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
    assert "| alpha | WorkdayGetVisas | Off |" in text
    assert "gptagent" not in text
    assert review["members"][0]["schemaName"] == schema


def test_blocked_inventory_keeps_resolution_failure_without_showing_an_execution_plan():
    review = _review()
    review["blockers"] = ["missing_member"]
    review["members"][0]["componentId"] = None
    text = review_text(review, preview=True)
    assert "| alpha | alpha.topic | Unknown |" in text
    assert "I couldn't identify all the requested topics in this agent." in text
    assert "Could not proceed. No topics were changed." in text
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
    assert result["userMessage"] == "alpha topics are not available in this agent.\nNo topics were changed."
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
        "servicenow-it topics are not available in this agent.\nNo topics were changed."
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
        "The signed-in account could not be verified.\nNo topics were changed."
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
    assert "Could not proceed. No topics were changed." in text
    assert "The signed-in account could not be verified." in text
    assert "Eligible changes:" not in text
    assert "| alpha | alpha.topic | Off |" in text
    assert "Before you approve" not in text


@pytest.mark.parametrize(("status", "text"), [
    ("cancelled", "Canceled. No topics were changed."),
    ("denied", "Not approved. No topics were changed."),
])
def test_cancellation_and_denial_have_exact_short_copy(status, text):
    assert result_text(_result(status, submitted=False)) == text


def test_completed_and_noop_results_do_not_repeat_review_notices():
    result = _result()
    assert result_text(result) == (
        "Completed.\nTopic sets: alpha.\n"
        "Verified requested states: 2/2 topics.\nCurrent states: On 2, Off 0, Unknown 0.\n"
        "One submission was attempted. The skill did not publish."
    )
    result.update(status="already_correct", writeStatus="not_attempted")
    text = result_text(result)
    assert text.startswith("No change needed.\n")
    assert text.endswith("No topics were changed.")
    assert "internal-warning" not in text


def test_partial_state_success_is_not_presented_as_complete_preservation():
    result = _result("partial")
    result["topics"][0]["status"] = "observed_desired"
    text = result_text(result)
    assert text.startswith("Changes submitted; verification incomplete.\n")
    assert "Requested states observed: 2/2 topics." in text
    assert "Preservation of other content and topic states could not be fully verified." in text
    result["topics"][0].update(state="Off", status="unchanged")
    text = result_text(result)
    assert "Requested states observed: 1/2 topics." in text
    assert "Some requested topic states could not be verified. Full completion is not confirmed." in text
    assert "Preservation of other content" not in text


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
    assert "Approval expired. A new review and approval are required." in result_text(result)
    result.update(status="review_required", blockers=["review_storage_unavailable"])
    text = result_text(result)
    assert "The pending review could not be saved or read safely." in text
    assert "Changes submitted" not in text
    assert text.endswith("No topics were changed.")


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
    backend.components.submit_state_payload.assert_called_once()
