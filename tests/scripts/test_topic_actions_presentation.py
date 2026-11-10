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
        "alreadyCorrect": ["shared"], "protected": [], "restoreStates": [],
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
        "| alpha | alpha.shared | On | On | Already correct |\n\n"
        "Eligible changes: 1. Already correct: 1. Protected: 0.\n\n"
        "The skill will not publish."
    )
    assert review == original


def test_material_notes_are_fixed_deduplicated_and_keep_original_state_consent():
    review = _review()
    review["warnings"] += [
        "catalog_release_untrusted", "catalog_review_pending",
        "native_draft_published_effects_unqualified", "unknown_protection",
    ]
    review["baseline"] = {"status": "capture_before_first_write"}
    text = review_text(review)
    assert "### Before you approve" in text
    assert text.count("The source topic list has not completed release review.") == 1
    assert "Changes may affect published conversations; isolation has not been verified." in text
    assert "Additional required or shared topics may not be identified by the source list." in text
    assert "Approval confirms these are the original topic states, before this skill made any changes" in text
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
    assert "| alpha | 1/2 | 1 | 0 | 1 |" in text
    assert "| unresolved-set | Unresolved | Not established | Not established | Not established |" in text
    assert "Before you approve" not in text
    assert "Topic presence does not confirm package installation or runtime health." in text
    assert text.endswith("No topics were changed.")


def test_entry_blockers_override_an_otherwise_executable_plan_in_display():
    result = _result("blocked", submitted=False)
    result["blockers"] = ["original_baseline_missing"]
    text = result_text(result)
    assert "Could not proceed. No topics were changed." in text
    assert "No saved original topic states are available." in text
    assert "Eligible changes: 0." in text
    assert "| alpha | alpha.topic | Off | On | Not eligible |" in text
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
    assert text.startswith("Already correct.\n")
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
    result.update(status="unverified", blockers=["state_journal_update_failed"])
    text = result_text(result)
    assert "Saved topic-state records could not be read or updated safely." in text
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
