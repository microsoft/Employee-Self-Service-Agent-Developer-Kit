# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Deterministic maker-facing copy; diagnostic evidence remains unchanged."""

from __future__ import annotations

import html


_LIMITATIONS = (
    (
        {"catalog_release_untrusted", "catalog_review_pending", "membership_review_pending",
         "missing_source", "stale_or_unverified_source"},
        "The source topic list has not completed release review.",
    ),
    (
        {"installed_package_unverified", "incomplete_membership", "incomplete_coverage",
         "set_coverage_unverified", "custom_dependency_coverage_unverified"},
        "Package coverage and additional dependencies have not been fully verified.",
    ),
    (
        {"classification_unverified", "required_coverage_unverified", "unknown_protection"},
        "Additional required or shared topics may not be identified by the source list.",
    ),
    (
        {"native_stale_write_protection_unqualified"},
        "Protection against concurrent edits has not been verified.",
    ),
    (
        {"native_batch_behavior_unqualified"},
        "All-or-nothing updates have not been verified.",
    ),
    (
        {"native_draft_published_effects_unqualified"},
        "Changes may affect published conversations; isolation has not been verified.",
    ),
    (
        {"previous_submission_outcome_uncertain"},
        "The previous submission could not be confirmed. Restore uses the saved original states.",
    ),
    (
        {"unrelated_topic_states_differ_from_original_and_will_be_preserved"},
        "Unrelated topic changes will be kept. Restore will not reset the entire agent.",
    ),
)

_BLOCKERS = (
    ({"approval_expired"}, "Approval expired. A new review and approval are required."),
    ({"evidence_changed", "baseline_changed_review_required"},
     "The reviewed information changed. A new review and approval are required."),
    ({"restore_conflict"}, "A previously changed topic was edited. Restore stopped to keep those edits."),
    ({"baseline_topic_identity_changed", "restore_membership_changed"},
     "The saved topics no longer match the current topic sets. Restore cannot safely continue."),
    ({"original_baseline_missing"},
     "No saved original topic states are available. Current states cannot establish an earlier original state."),
    ({"baseline_invalid", "baseline_storage_unavailable", "state_journal_update_failed"},
     "Saved topic-state records could not be read or updated safely. Keep the existing records."),
    ({"topic_operation_in_progress_or_interrupted", "operation_in_progress"},
     "Another topic operation is running or its result has not been recorded."),
    ({"previous_write_uncertain_restore_required"},
     "The previous change could not be confirmed. Request a review to restore the saved original states."),
    ({"setup_not_run", "setup_incomplete"},
     "Workspace preparation is incomplete. Run /setup for the selected agent, then make a new request."),
    ({"setup_broken", "workspace_missing"},
     "The selected agent's workspace could not be verified. Keep the existing setup and ask your ADK administrator to investigate."),
    ({"authentication_failed", "account_mismatch", "write_authentication_failed"},
     "The signed-in account could not be verified."),
    ({"access_denied"}, "The service denied read access to the selected agent or environment."),
    ({"write_access_denied"}, "The service denied permission to change topics."),
    ({"target_unverified", "target_not_found", "write_target_not_found"},
     "The selected agent could not be verified or accessed."),
    ({"missing_set", "ambiguous_or_unsupported_set", "unresolved_member", "missing_member",
      "ambiguous_member", "empty_membership"},
     "The complete topic list could not be resolved. No smaller selection was used. Ask your ADK administrator to investigate."),
    ({"unknown_state", "unknown_outside_state"},
     "Some topic states could not be verified."),
    ({"explicit_approval_required", "approval_interaction_failed"},
     "Explicit approval was not received. A new review is required."),
    ({"plan_all_protected"}, "All selected topics are protected and will stay unchanged."),
    ({"write_request_rejected"}, "The service rejected the change request."),
    ({"write_conflict"}, "The service reported a conflict with another change."),
    ({"write_request_too_large"}, "The service rejected the size of the change request."),
    ({"write_throttled"}, "The service temporarily limited change requests."),
    ({"write_transport_failed", "write_service_failed", "write_http_error",
      "write_acknowledgement_unverified", "submission_validation_failed"},
     "The change request could not be confirmed."),
    ({"readback_failed"}, "The topic states could not be read after submission."),
)


def _text(value: object) -> str:
    # Treat remote labels as text, not Markdown, HTML or terminal controls.
    value = " ".join(str(value).split())
    value = "".join(char for char in value if char.isprintable())
    value = html.escape(value, quote=False)
    for char in ("\\", "`", "*", "_", "[", "]", "|", "#", "~"):
        value = value.replace(char, "\\" + char)
    return value


def _codes(values) -> set[str]:
    return {value.split(":", 1)[0] for value in values}


def _blocker_messages(result: dict) -> list[str]:
    codes = _codes(result.get("blockers", ()))
    if not codes and result.get("reason"):
        codes.add(result["reason"].split(":", 1)[0])
    messages = [message for keys, message in _BLOCKERS if codes & keys]
    return messages or ["The information needed to continue could not be verified."]


def review_text(review: dict, *, preview: bool = False) -> str:
    action = {"enable": "Enable", "disable": "Disable", "restore": "Restore"}[review["action"]]
    target = review["target"]
    lines = [
        "## Topic preview" if preview else "## Review topic changes",
        f"Action: {action}",
    ]
    if review.get("account"):
        lines.append(f"Account: {_text(review['account'])}")
    lines.extend((
        f"Agent: {_text(target['agentId'])}",
        f"Environment: {_text(target['environmentId'])}",
        f"Tenant: {_text(target['tenantId'])}",
        "Topic sets: " + ", ".join(_text(key) for key in review["selectedSets"]),
    ))
    current = {item["componentId"]: item["state"] for item in review.get("currentStates", ())}
    changes = {item["componentId"]: item for item in review["proposedChanges"]}
    correct = set(review["alreadyCorrect"])
    protected = {item["componentId"]: item for item in review["protected"]}
    restore = {item["componentId"]: item["state"] for item in review["restoreStates"]}
    blocked = bool(review["blockers"])
    if preview:
        lines.extend((
            "",
            "| Topic set | Matched / expected | On | Off | Unknown |",
            "| --- | --- | --- | --- | --- |",
        ))
        for key in review["selectedSets"]:
            members = [item for item in review["members"] if item["setKey"] == key]
            if not members:
                counts = ["Unresolved", "Not established", "Not established", "Not established"]
            else:
                matched = sum(item["componentId"] is not None for item in members)
                states = [current.get(item["componentId"], "Unknown") for item in members]
                counts = [f"{matched}/{len(members)}", *(str(states.count(state)) for state in ("On", "Off", "Unknown"))]
            lines.append("| " + " | ".join(_text(value) for value in (key, *counts)) + " |")
    lines.extend((
        "",
        "| Topic set | Topic | Current state | Requested state | Plan |",
        "| --- | --- | --- | --- | --- |",
    ))
    for member in review["members"]:
        identity = member["componentId"]
        desired = restore.get(identity, "Unknown") if review["action"] == "restore" else (
            "On" if review["action"] == "enable" else "Off"
        )
        change = changes.get(identity)
        state = current.get(identity, change["before"] if change else (
            desired if identity in correct else "Unknown"
        ))
        if identity in protected:
            protection = protected[identity]
            plan = "Keep unchanged: required topic" if protection["reason"] == "required" else (
                "Keep unchanged: used by " + ", ".join(protection["protectingSets"])
            )
        else:
            plan = "Not eligible" if blocked else (
                "Change" if change else "Already correct" if identity in correct else "Unresolved"
            )
        lines.append("| " + " | ".join(_text(value) for value in (
            member["setKey"], member["schemaName"], state, desired, plan,
        )) + " |")
    lines.extend((
        "",
        f"Eligible changes: {0 if blocked else len(changes)}. "
        f"Already correct: {len(correct)}. Protected: {len(protected)}.",
    ))
    if blocked:
        lines.extend(("", "Could not proceed. No topics were changed.", *_blocker_messages(review)))
    notes = []
    baseline = review.get("baseline") or {}
    if baseline.get("status") == "capture_before_first_write":
        notes.append(
            "Approval confirms these are the original topic states, before this skill made any changes, "
            "and allows them to be saved for restore."
        )
    elif baseline.get("capturedAt"):
        notes.append("Saved original states: " + _text(baseline["capturedAt"]) + ".")
    if review["action"] == "disable" or any(item["state"] == "Off" for item in review["restoreStates"]):
        notes.append("Turning topics Off may make capabilities that depend on them unavailable.")
    codes = _codes(review.get("warnings", ()))
    notes.extend(message for keys, message in _LIMITATIONS if codes & keys)
    known = {"write_permission_enforced_by_service"} | set().union(*(keys for keys, _ in _LIMITATIONS))
    if codes - known:
        notes.append("Additional limitations need review. Technical details are available on request.")
    if notes:
        lines.extend(("", "### About this preview" if preview or blocked else "### Before you approve"))
        lines.extend("- " + note for note in notes)
    if preview:
        lines.extend(("", "Topic presence does not confirm package installation or runtime health."))
    if not blocked:
        lines.extend(("", "No topics were changed." if preview else "The skill will not publish."))
    return "\n".join(lines)


def result_text(result: dict) -> str:
    status = result["status"]
    if status == "source_catalog_only":
        return "Source-defined topic sets (availability not yet checked):\n" + "\n".join(
            f"- {_text(item['name'])}: {_text(item['key'])}" for item in result["sets"]
        ) + "\nNo topics were changed."
    if status == "preview" or (status == "blocked" and result.get("plan")):
        review = {**result["plan"], "blockers": result.get("blockers", ())}
        return review_text(review, preview=True)
    if status in ("cancelled", "denied"):
        return "Canceled. No topics were changed." if status == "cancelled" else (
            "Not approved. No topics were changed."
        )
    submitted = result["writeStatus"] == "submitted"
    if status in ("partial", "unverified") and submitted:
        heading = "Changes submitted; verification incomplete."
    else:
        heading = {
            "completed": "Completed.",
            "completed_with_protections": "Eligible changes completed; protected topics kept unchanged.",
            "already_correct": "Already correct." if result.get("completed") else (
                "Eligible topics already correct; protected topics kept unchanged."
            ),
            "inspected": "Selected agent verified. Topic availability has not been checked.",
        }.get(status, "Could not proceed.")
    lines = [heading]
    plan = result.get("plan") or {}
    if plan.get("selectedSets"):
        lines.append("Topic sets: " + ", ".join(_text(key) for key in plan["selectedSets"]) + ".")
    topics = result.get("topics", ())
    if topics:
        observed = sum(item["status"] in ("changed", "observed_desired", "already_correct") for item in topics)
        label = "Requested states observed" if status in ("partial", "unverified") else "Verified requested states"
        lines.append(f"{label}: {observed}/{len(topics)} topics.")
        lines.append("Current states: " + ", ".join(
            f"{state} {sum(item['state'] == state for item in topics)}" for state in ("On", "Off", "Unknown")
        ) + ".")
    if status == "partial":
        lines.append(
            "Preservation of other content and topic states could not be fully verified."
            if topics and all(
                item["status"] in ("changed", "observed_desired", "already_correct", "protected")
                for item in topics
            ) else "Some requested topic states could not be verified. Full completion is not confirmed."
        )
    elif status == "unverified" and submitted:
        lines.append("Observed states do not confirm that this request made the changes.")
        lines.extend(_blocker_messages(result))
    elif status in ("blocked", "review_required", "unverified"):
        lines.extend(_blocker_messages(result))
    lines.append("One submission was attempted. The skill did not publish." if submitted else "No topics were changed.")
    return "\n".join(lines)
