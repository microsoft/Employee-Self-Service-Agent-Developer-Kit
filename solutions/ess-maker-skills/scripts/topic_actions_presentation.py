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
)

_BLOCKERS = (
    ({"review_unavailable", "review_invalid"},
     "This review is unavailable or has already been used. A new review and approval are required."),
    ({"review_storage_unavailable"},
     "The pending review could not be saved or read safely. A new review is required."),
    ({"approval_expired"}, "Approval expired. A new review and approval are required."),
    ({"evidence_changed"},
     "The reviewed information changed. A new review and approval are required."),
    ({"operation_in_progress"},
     "Another topic operation is running or its result has not been recorded."),
    ({"invalid_request"},
     "Provide a valid enable or disable request with explicit whole topic-set keys. Restore is not supported."),
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


def _topic_name(schema_name: str) -> str:
    return schema_name.rsplit(".topic.", 1)[-1]


def _blocker_messages(result: dict) -> list[str]:
    codes = _codes(result.get("blockers", ()))
    if not codes and result.get("reason"):
        codes.add(result["reason"].split(":", 1)[0])
    messages = [message for keys, message in _BLOCKERS if codes & keys]
    return messages or ["The information needed to continue could not be verified."]


def review_text(review: dict, *, preview: bool = False) -> str:
    if preview:
        return _topic_list_text(review)
    action = {"enable": "Enable", "disable": "Disable"}[review["action"]]
    target = review["target"]
    lines = [
        "## Review topic changes",
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
    blocked = bool(review["blockers"])
    lines.extend((
        "",
        "| Topic set | Topic | Current state | Requested state | Plan |",
        "| --- | --- | --- | --- | --- |",
    ))
    for member in review["members"]:
        identity = member["componentId"]
        desired = "On" if review["action"] == "enable" else "Off"
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
                "Change" if change else "No change" if identity in correct else "Unresolved"
            )
        lines.append("| " + " | ".join(_text(value) for value in (
            member["setKey"], _topic_name(member["schemaName"]), state, desired, plan,
        )) + " |")
    lines.extend((
        "",
        f"Eligible changes: {0 if blocked else len(changes)}. "
        f"No change: {len(correct)}. Protected: {len(protected)}.",
    ))
    if blocked:
        lines.extend(("", "Could not proceed. No topics were changed.", *_blocker_messages(review)))
    notes = []
    if review["action"] == "disable":
        notes.append("Turning topics Off may make capabilities that depend on them unavailable.")
    codes = _codes(review.get("warnings", ()))
    notes.extend(message for keys, message in _LIMITATIONS if codes & keys)
    known = {"write_permission_enforced_by_service"} | set().union(*(keys for keys, _ in _LIMITATIONS))
    if codes - known:
        notes.append("Additional limitations need review. Technical details are available on request.")
    if notes:
        lines.extend(("", "### About this review" if blocked else "### Before you approve"))
        lines.extend("- " + note for note in notes)
    if not blocked:
        lines.extend(("", "The skill will not publish."))
    return "\n".join(lines)


def _topic_list_text(review: dict) -> str:
    target = review["target"]
    lines = [
        "## Topics",
        f"Agent: {_text(target['agentId'])}",
        f"Environment: {_text(target['environmentId'])}",
        "",
        "| Topic set | Topic | Current state |",
        "| --- | --- | --- |",
    ]
    current = {item["componentId"]: item["state"] for item in review.get("currentStates", ())}
    for member in review["members"]:
        values = (
            member["setKey"], _topic_name(member["schemaName"]),
            current.get(member["componentId"], "Unknown"),
        )
        lines.append("| " + " | ".join(_text(value) for value in values) + " |")
    for key in review["selectedSets"]:
        if not any(member["setKey"] == key for member in review["members"]):
            lines.append(f"| {_text(key)} | Unresolved | Unknown |")
    if review["blockers"]:
        lines.extend(("", "Could not proceed. No topics were changed.", *_blocker_messages(review)))
    else:
        lines.extend(("", "No topics were changed."))
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
            "already_correct": "No change needed." if result.get("completed") else (
                "No change needed for eligible topics; protected topics kept unchanged."
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
