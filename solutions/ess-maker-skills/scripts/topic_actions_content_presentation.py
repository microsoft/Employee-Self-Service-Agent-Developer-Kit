# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Maker-facing text for adding content-backed topic sets."""

from topic_actions_presentation import (
    _blocker_messages, _result_tables, _text, _topic_count, _topic_name, result_text,
)


_MEMBER_PROBLEMS = {
    "partial_set": "incomplete set", "incomplete_set": "incomplete set",
    "content_differs": "content differs", "wrong_component_kind": "wrong component kind",
    "ambiguous_member": "duplicate or mismatched schema name",
}


def member_problems(blockers) -> list[str]:
    return [
        f"{_text(_topic_name(parts[2]))}: {_MEMBER_PROBLEMS[parts[0]]}."
        for reason in blockers
        if len(parts := reason.split(":", 2)) == 3 and parts[0] in _MEMBER_PROBLEMS
    ]


def content_topic_result(topic: dict, state: str) -> str:
    if topic["status"] == "changed":
        return "Added, disabled"
    if topic["status"] == "already_correct":
        return "Already present, unchanged"
    if topic["reason"] == "blocking_diagnostic":
        return "Blocking diagnostic; addition failed"
    return f"{state} observed; operation not verified"


def _result_note(result: dict, action: str | None) -> str:
    action = action or (result.get("plan") or {}).get("action") or result.get("action")
    if action == "add":
        if result["writeStatus"] == "submitted":
            return "The change is in the draft. Microsoft 365 Copilot sees it after you publish in Copilot Studio."
        if result["status"] != "review_ready":
            return "No topics were changed."
    reason = result.get("reason", "")
    if reason == "invalid_request" or reason.startswith(("content_", "invalid_content_")):
        return "No topics were changed."
    return ""


def content_message(result: dict) -> str:
    """Replace the state-only wording; keep the shared status messages otherwise."""
    status = result["status"]
    message = result["message"]
    if status == "completed":
        message = "The requested topic additions were verified."
    elif status == "already_correct":
        message = "The shipped topics are already present."
    note = _result_note(result, "add")
    return message + " " + note if note else message


def _sets_text(result: dict) -> str:
    lines = [f"## Topic sets to {result['action']}"]
    if result["sets"]:
        lines.extend(("", "| **Topic set** | **Present topics** | **Presence** |", "| --- | --- | --- |"))
        for item in result["sets"]:
            lines.append(
                f"| {_text(item['name'])} | {item['topicCount']} of {item['expectedTopicCount']} | {item['presence']} |"
            )
        lines.extend(("", "Presence does not establish whether the set can be changed. Review checks content and eligibility."))
    elif result["discoveryComplete"]:
        lines.extend(("", f"No supported content-backed topic sets are available to {result['action']}."))
    if not result["discoveryComplete"]:
        lines.extend(("", "Some topic sets could not be fully identified."))
    return "\n".join(lines)


def _outcome_text(result: dict) -> str:
    """Follow the enable/disable result layout with add counts and recovery steps."""
    status = result["status"]
    plan = result["plan"]
    topics = result["topics"]
    if status in ("completed", "already_correct"):
        changed = sum(item["status"] == "changed" for item in topics)
        unchanged = sum(item["status"] == "already_correct" for item in topics)
        headline = "0 topics changed." if status == "already_correct" else f"{_topic_count(changed)} added and verified."
        summary = [f"**{headline}**"]
        if unchanged:
            summary.append(f"{unchanged} already present, unchanged.")
        heading = "## No change needed." if status == "already_correct" else "## Topic addition completed"
        lines = [heading, "", " ".join(summary)]
    else:
        observed = sum(item["status"] in ("changed", "observed_desired", "already_correct") for item in topics)
        heading = "## Changes submitted; verification incomplete." if status == "partial" else (
            "## Change outcome not fully verified"
        )
        lines = [heading, "", f"Requested states observed: {observed}/{len(topics)} topics."]
    target = plan["target"]
    lines.extend(("", f"- Agent: {_text(target['agentId'])}", f"- Environment: {_text(target['environmentId'])}"))
    if plan.get("account"):
        lines.append(f"- Account: {_text(plan['account'])}")
    lines.extend(_result_tables(result))
    lines.append("")
    if status == "already_correct":
        lines.append("The topics are already present with the shipped content.")
    if status in ("completed", "already_correct"):
        lines.append("Use enable to turn them on, or turn them on in Copilot Studio.")
    if result.get("preservationStatus") == "violated":
        lines.append("Other content, topic membership or outside-scope states did not match the reviewed evidence.")
    blocking = any(topic.get("reason") == "blocking_diagnostic" for topic in topics)
    if blocking:
        lines.append("The service reported a blocking topic diagnostic; addition failed.")
    if status == "partial":
        if result.get("preservationStatus") != "violated":
            lines.append(
                "Preservation of other content and topic states could not be fully verified."
                if all(item["status"] in ("changed", "observed_desired", "already_correct") for item in topics)
                else "Some requested topic states could not be verified. Full completion is not confirmed."
            )
        step = "Make a new request to check current states and review any further changes."
        if blocking:
            step = (
                "The inserted topics remain off. Delete them in Copilot Studio before trying add again."
                if all(topic["state"] == "Off" for topic in topics)
                else "Check the reported states and disable any enabled topics. Then delete the inserted "
                "topics in Copilot Studio and run add again."
            )
        else:
            step = (
                "If only part of the set was inserted, disable any enabled topics, then delete the inserted "
                "topics in Copilot Studio and run add again."
            )
        lines.extend(("", "**NEXT STEPS**", "", step))
    elif status == "unverified":
        lines.append("Observed states do not confirm that this request made the changes.")
        if result.get("preservationStatus") == "unverified":
            lines.append("Preservation of other content and topic states could not be fully verified.")
        lines.extend(_blocker_messages(result))
    return "\n".join(lines).rstrip()


def content_result_text(result: dict, action: str | None) -> str | None:
    """Return add text, or None to keep the shared enable/disable layout."""
    listed = result["status"] == "sets_listed" and result.get("action") == "add"
    outcome = (result.get("plan") or {}).get("action") == "add" and result["status"] in (
        "completed", "already_correct", "partial", "unverified",
    ) and result["topics"]
    note = _result_note(result, action)
    if not (listed or outcome or note):
        return None
    text = _sets_text(result) if listed else _outcome_text(result) if outcome else result_text(result, plain=True)
    if not note:
        return text
    paragraph = listed or (result.get("plan") or {}).get("action") == "add" and result["status"] != "review_ready"
    return text + ("\n\n" if paragraph else " ") + note
