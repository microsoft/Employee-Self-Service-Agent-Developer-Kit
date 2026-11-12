# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Exact maker copy and truthful presentation of synthetic topic evidence."""

from copy import deepcopy

import pytest

from topic_actions_execution import TopicActionSession
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


def test_material_notes_are_fixed_deduplicated_without_original_state_consent():
    review = _review()
    review["warnings"] += [
        "catalog_release_untrusted", "catalog_review_pending",
        "native_draft_published_effects_unqualified", "unknown_protection",
    ]
    text = review_text(review)
    assert "### Before you approve" in text
    assert text.count("The source topic list has not completed release review.") == 1
    assert "Changes may affect published conversations; isolation has not been verified." in text
    assert "Additional required or shared topics may not be identified by the source list." in text
    assert "original topic states" not in text
    assert all(code not in text for code in review["warnings"])
    assert "warning" not in text.casefold()
    review["warnings"].reverse()
    assert review_text(review) == text


def test_unknown_limitations_are_not_silently_discarded():
    review = _review()
    review["warnings"].append("future_sensitive_internal_detail")
    text = review_text(review)
    assert "Additional limitations need review. Technical details are available on request." in text
    assert "future_sensitive_internal_detail" not in text


def test_disable_review_explains_shared_capability_impact_and_current_state():
    review = _review()
    review.update(action="disable", alreadyCorrect=[], proposedChanges=[])
    review["protected"] = [{"componentId": "shared", "reason": "shared", "protectingSets": ["beta"]}]
    text = review_text(review)
    assert "| alpha | alpha.shared | On | Off | Keep unchanged: used by beta |" in text
    assert "Turning topics Off may make capabilities that depend on them unavailable." in text


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
    assert "The complete topic list could not be resolved." in text
    assert "Could not proceed. No topics were changed." in text
    assert "Requested state" not in text
    assert "Eligible changes" not in text
    result = _result("blocked", submitted=False)
    result.update(plan=review, blockers=review["blockers"])
    assert result_text(result) == text


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
