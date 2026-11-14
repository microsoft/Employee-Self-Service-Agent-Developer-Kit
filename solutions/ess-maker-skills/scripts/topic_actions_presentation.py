# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Deterministic maker-facing copy; diagnostic evidence remains unchanged."""

from __future__ import annotations

import html


_BLOCKERS = (
    ({"review_unavailable", "review_invalid", "session_consumed"},
     "This review is unavailable or has already been used.",
     "Make a new request for a fresh review and approval."),
    ({"review_storage_unavailable"},
     "The pending review could not be saved or read safely.",
     "Make a new request for a fresh review."),
    ({"approval_expired"}, "Approval expired.",
     "Make a new request for a fresh review and approval."),
    ({"evidence_changed"},
     "The reviewed information changed.",
     "Make a new request for a fresh review and approval."),
    ({"operation_in_progress"},
     "Another topic operation is running or its result has not been recorded.",
     "Check that operation's outcome before starting a new request."),
    ({"invalid_request"},
     "The topic-change request is not supported. Restore is not supported.",
     "Specify Enable or Disable and the whole topic sets to change."),
    ({"setup_not_run", "setup_incomplete"},
     "Workspace preparation is incomplete.",
     "Run /setup for the selected agent, then make a new request."),
    ({"setup_broken", "workspace_missing"},
     "The selected agent's workspace could not be verified.",
     "Keep the existing setup and ask your ADK administrator to investigate."),
    ({"authentication_failed", "account_mismatch", "write_authentication_failed"},
     "The signed-in account could not be verified.",
     "Verify the signed-in account, then make a new request."),
    ({"access_denied"}, "The service denied read access to the selected agent or environment.",
     "Ask the administrator responsible for that agent and environment to check read access."),
    ({"write_access_denied"}, "The service denied permission to change topics.",
     "Ask the administrator responsible for that agent and environment to grant topic-edit access."),
    ({"target_unverified", "target_not_found", "write_target_not_found"},
     "The selected agent could not be verified or accessed.",
     "Keep the existing target and ask your ADK administrator to investigate."),
    ({"missing_set", "ambiguous_or_unsupported_set", "unresolved_member", "missing_member",
      "ambiguous_member", "empty_membership"},
     "I couldn't identify all the requested topics in this agent.",
     "Verify the topic identities in the selected agent, then make a new request."),
    ({"unknown_state", "unknown_outside_state"},
     "Some topic states could not be verified.",
     "Make a new request to read the current states again."),
    ({"explicit_approval_required", "approval_interaction_failed"},
     "Explicit approval was not received.",
     "Make a new request for a fresh review and approval."),
    ({"plan_all_protected"}, "All selected topics are protected and will stay unchanged.",
     "Choose a different topic set in a new request."),
    ({"write_request_rejected"}, "The service rejected the change request.",
     "Make a new request to check current states and review any further changes."),
    ({"write_conflict"}, "The service reported a conflict with another change.",
     "Make a new request to check current states and review any further changes."),
    ({"write_request_too_large"}, "The service rejected the size of the change request.",
     "Select fewer whole topic sets in a new request."),
    ({"write_throttled"}, "The service temporarily limited change requests.",
     "Wait for the service limit to clear, then make a new request."),
    ({"write_transport_failed", "write_service_failed", "write_http_error",
      "write_acknowledgement_unverified", "submission_validation_failed"},
     "The change request could not be confirmed.",
     "Make a new request to check current states and review any further changes."),
    ({"readback_failed"}, "The topic states could not be read after submission.",
     "Make a new request to read current states before considering further changes."),
    ({"authentication_or_evidence_failed", "evidence_read_failed"},
     "The account or topic information needed for this request could not be read.",
     "Make a new request to check the selected agent again."),
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


def _state(value: str) -> str:
    return {"On": "Enabled", "Off": "Disabled", "Mixed": "Mixed"}.get(value, "Unknown")


def _topic_count(count: int) -> str:
    return f"{count} topic" + ("" if count == 1 else "s")


def _set_names(plan: dict, keys) -> str:
    return "; ".join(plan.get("setNames", {}).get(key, key) for key in keys)


def _integration_names(plan: dict, keys) -> str:
    return "; ".join(dict.fromkeys(
        plan.get("setIntegrations", {}).get(key, _set_names(plan, (key,))) for key in keys
    ))


def _member_groups(plan: dict) -> list:
    members = {}
    for member in plan.get("members", ()):
        identity = member["componentId"]
        key = identity if identity is not None else (member["setKey"], member["schemaName"])
        if key not in members:
            members[key] = (member, [])
        if member["setKey"] not in members[key][1]:
            members[key][1].append(member["setKey"])
    groups = {}
    for member, keys in members.values():
        scope = tuple(key for key in plan.get("selectedSets", ()) if key in keys)
        groups.setdefault(scope, []).append(member)
    for key in plan.get("selectedSets", ()):
        if not any(key in scope for scope in groups):
            groups[(key,)] = []
    return list(groups.items())


def _group_heading(plan: dict, keys: tuple) -> str:
    return "### " + ("Shared topics: " if len(keys) > 1 else "") + _text(_set_names(plan, keys))


def _protection_text(plan: dict, protection: dict) -> str:
    return "required topic" if protection["reason"] == "required" else (
        "used by " + _set_names(plan, protection["protectingSets"])
    )


def _blocker_messages(result: dict) -> list[str]:
    blockers = result.get("blockers", ())
    codes = _codes(blockers)
    messages = []
    selected = result.get("selectedSets", ())
    for key in selected:
        if f"set_absent:{key}" in blockers:
            label = _text(_set_names(result, (key,)))
            suffix = "" if key in result.get("setNames", {}) else " topics"
            messages.append(f"{label}{suffix} are not available in this agent.")
    if messages:
        codes -= {"set_absent", "missing_member"}
        if all(
            f"set_absent:{value.split(':', 1)[1]}" in blockers
            for value in blockers if value.startswith("empty_membership:")
        ):
            codes.discard("empty_membership")
        # Unresolved placeholders have no state; this is not another read failure.
        if not any(
            value.startswith("unknown_state:") and not value.startswith("unknown_state:unresolved:")
            for value in blockers
        ):
            codes.discard("unknown_state")
    if not codes and result.get("reason"):
        codes.add(result["reason"].split(":", 1)[0])
    matches = [(message, step) for keys, message, step in _BLOCKERS if codes & keys]
    messages.extend(message for message, _ in matches)
    step = matches[0][1] if matches else (
        "Choose a topic set available on this agent." if messages else
        "Make a new request to check the selected agent again."
    )
    return [
        *(messages or ["The information needed to continue could not be verified."]),
        "", "**NEXT STEPS**", "", step,
    ]


def approval_question(review: dict) -> dict | None:
    changes = {item["componentId"] for item in review["proposedChanges"]}
    if review["blockers"] or not changes:
        return None
    action = {"enable": "Enable", "disable": "Disable"}[review["action"]]
    count = _topic_count(len(changes))
    names = [_set_names(review, (key,)) for key in review["selectedSets"]]
    sets = _text(
        names[0] if len(names) == 1 else
        " and ".join(names) if len(names) == 2 else
        ", ".join(names[:-1]) + ", and " + names[-1]
    )
    question = f"{action} the {count} shown above?"
    return {
        "header": question,
        "question": question,
        "multiSelect": False,
        "options": [
            {
                "label": f"{action} {count} for {sets}.",
                "description": "Apply only the changes shown above.",
            },
            {"label": "Not now", "description": "Leave topics unchanged."},
        ],
        "allowFreeformInput": True,
    }


def review_text(review: dict, *, preview: bool = False) -> str:
    if any(
        reason.startswith("set_absent:")
        for reason in review.get("blockers", ())
    ):
        return "\n".join(_blocker_messages(review))
    if preview:
        return _topic_list_text(review)
    action = {"enable": "Enable", "disable": "Disable"}[review["action"]]
    target = review["target"]
    lines = [
        "## Review topic changes",
        f"- Action: {action}",
    ]
    if review.get("account"):
        lines.append(f"- Account: {_text(review['account'])}")
    lines.extend((
        f"- Agent: {_text(target['agentId'])}",
        f"- Environment: {_text(target['environmentId'])}",
        f"- Tenant: {_text(target['tenantId'])}",
        "- Topic sets: " + _text(_set_names(review, review["selectedSets"])),
    ))
    current = {item["componentId"]: item["state"] for item in review.get("currentStates", ())}
    changes = {item["componentId"]: item for item in review["proposedChanges"]}
    correct = set(review["alreadyCorrect"])
    protected = {item["componentId"]: item for item in review["protected"]}
    blocked = bool(review["blockers"])
    for keys, members in _member_groups(review):
        lines.extend((
            "", _group_heading(review, keys), "",
            "| **#** | **Integration** | **Topic** | **Current state** | **Planned change** |",
            "| --- | --- | --- | --- | --- |",
        ))
        for index, member in enumerate(members, 1):
            identity = member["componentId"]
            desired = "On" if review["action"] == "enable" else "Off"
            change = changes.get(identity)
            state = current.get(identity, change["before"] if change else (
                desired if identity in correct else "Unknown"
            ))
            if identity in protected:
                plan = "Kept unchanged: " + _protection_text(review, protected[identity])
            else:
                plan = "Not eligible" if blocked else (
                    action if change else f"No change - already {_state(state).lower()}"
                    if identity in correct else "Unresolved"
                )
            lines.append("| " + " | ".join(_text(value) for value in (
                index, _integration_names(review, keys),
                _topic_name(member["schemaName"]), _state(state), plan,
            )) + " |")
    if blocked:
        lines.extend(("", "Could not proceed. No topics were changed.", *_blocker_messages(review)))
    if not blocked:
        lines.extend(("", "The skill will not publish."))
    return "\n".join(lines)


def _topic_list_text(review: dict) -> str:
    if review["blockers"]:
        return "\n".join(_blocker_messages(review))
    lines = ["## Topics"]
    current = {item["componentId"]: item["state"] for item in review.get("currentStates", ())}
    for keys, members in _member_groups(review):
        lines.extend((
            "", _group_heading(review, keys), "",
            "| **Topic** | **Current state** |", "| --- | --- |",
        ))
        for member in members:
            lines.append(
                f"| {_text(_topic_name(member['schemaName']))} | "
                f"{_state(current.get(member['componentId'], 'Unknown'))} |"
            )
        if not members:
            lines.append("| Unresolved | Unknown |")
    return "\n".join(lines)


def _topic_result_text(result: dict, topic: dict) -> str:
    plan = result.get("plan") or {}
    state = _state(topic["state"])
    desired = "Enabled" if plan.get("action") == "enable" else "Disabled"
    status = topic["status"]
    if state == desired:
        if status == "changed" and result["status"] in ("completed", "completed_with_protections"):
            return state
        if status == "already_correct":
            return f"Already {state.lower()} - unchanged"
        if status in ("changed", "observed_desired"):
            return f"{state} observed; cause unconfirmed"
    if status == "protected":
        protection = next(
            (item for item in plan.get("protected", ()) if item["componentId"] == topic["componentId"]),
            None,
        )
        label = f"Kept unchanged ({state})" if result.get("preservationStatus") == "verified" else (
            f"{state} observed; preservation not verified"
        )
        return label + (": " + _protection_text(plan, protection) if protection else "")
    return (
        "Unknown - final state could not be verified" if state == "Unknown"
        else f"{state} - requested state not verified"
    )


def _result_tables(result: dict) -> list[str]:
    plan = result.get("plan") or {}
    topics = {item["componentId"]: item for item in result.get("topics", ())}
    lines = []
    for keys, members in _member_groups(plan):
        rows = [member for member in members if member["componentId"] in topics]
        if not rows:
            continue
        integrations = _integration_names(plan, keys)
        lines.extend((
            "", _group_heading(plan, keys), "",
            "| **#** | **Integration** | **Topic** | **Result** |",
            "| --- | --- | --- | --- |",
        ))
        for index, member in enumerate(rows, 1):
            topic = topics[member["componentId"]]
            lines.append("| " + " | ".join(_text(value) for value in (
                index, integrations, _topic_name(member["schemaName"]),
                _topic_result_text(result, topic),
            )) + " |")
    return lines


def result_text(result: dict) -> str:
    status = result["status"]
    if status == "sets_listed":
        lines = ["## Topic sets"]
        if result["sets"]:
            lines.extend(("", "| **Topic set** | **Topics** | **State** |", "| --- | --- | --- |"))
            for item in result["sets"]:
                count = item["topicCount"] if item["topicCount"] is not None else "Unknown"
                lines.append(
                    f"| {_text(item['name'])} | {_text(count)} | {_text(item['state'])} |"
                )
        else:
            lines.extend(("", "No supported topic sets are available in this agent."))
        if not result["discoveryComplete"]:
            lines.extend(("", "Some topic sets could not be fully identified."))
        return "\n".join(lines)
    if status == "source_catalog_only":
        return "Source-defined topic sets (availability not yet checked):\n" + "\n".join(
            f"- {_text(item['name'])}: {_text(item['key'])}" for item in result["sets"]
        )
    if status == "preview":
        review = {**result["plan"], "blockers": result.get("blockers", ())}
        return review_text(review, preview=True)
    if status in ("cancelled", "denied"):
        return "Canceled." if status == "cancelled" else "Not approved."
    if status in ("blocked", "review_required") and result["writeStatus"] == "not_attempted":
        return "\n".join(_blocker_messages({**(result.get("plan") or {}), **result}))
    submitted = result["writeStatus"] == "submitted"
    if status == "partial" and submitted:
        heading = "## Changes submitted; verification incomplete."
    elif status == "unverified" and submitted:
        heading = "## Change outcome not fully verified"
    else:
        heading = {
            "completed": "## Topic changes completed",
            "completed_with_protections": "## Eligible topic changes completed.",
            "already_correct": "## No change needed." if result.get("completed") else (
                "## No change needed for eligible topics."
            ),
            "inspected": "Selected agent verified. Topic availability has not been checked.",
            "review_required": "## Review required",
        }.get(status, "## Could not proceed")
    lines = [heading]
    plan = result.get("plan") or {}
    topics = result.get("topics", ())
    if topics:
        desired = "On" if plan.get("action") == "enable" else "Off"
        matching = [item for item in topics if item["state"] == desired]
        if status in ("completed", "completed_with_protections", "already_correct"):
            changed = sum(item["status"] == "changed" for item in matching)
            unchanged = sum(item["status"] == "already_correct" for item in matching)
            label = "enabled" if plan["action"] == "enable" else "disabled"
            headline = "0 topics changed" if status == "already_correct" else (
                f"{_topic_count(changed)} {label}"
            )
            summary = [f"**{headline}{'.' if status == 'already_correct' else ' and verified.'}**"]
            if unchanged:
                summary.append(f"{unchanged} already {label}, unchanged.")
            lines.extend(("", " ".join(summary)))
        else:
            observed = sum(
                item["status"] in ("changed", "observed_desired", "already_correct")
                for item in matching
            )
            lines.extend(("", f"Requested states observed: {observed}/{len(topics)} topics."))
        target = plan.get("target", {})
        if target:
            lines.extend((
                "",
                f"- Agent: {_text(target['agentId'])}",
                f"- Environment: {_text(target['environmentId'])}",
            ))
            if plan.get("account"):
                lines.append(f"- Account: {_text(plan['account'])}")
        lines.extend(_result_tables(result))
    lines.append("")
    if result.get("preservationStatus") == "violated":
        lines.append("Other content, topic membership or outside-scope states did not match the reviewed evidence.")
    if status == "partial" and result.get("preservationStatus") != "violated":
        lines.append(
            "Preservation of other content and topic states could not be fully verified."
            if topics and all(
                item["status"] in ("changed", "observed_desired", "already_correct", "protected")
                for item in topics
            ) else "Some requested topic states could not be verified. Full completion is not confirmed."
        )
    if status == "partial":
        lines.extend((
            "", "**NEXT STEPS**", "",
            "Make a new request to check current states and review any further changes.",
        ))
    elif status == "unverified" and submitted:
        lines.append("Observed states do not confirm that this request made the changes.")
        if result.get("preservationStatus") == "unverified":
            lines.append("Preservation of other content and topic states could not be fully verified.")
        lines.extend(_blocker_messages(result))
    elif status == "unverified":
        lines.extend(_blocker_messages(result))
    return "\n".join(lines).rstrip()
