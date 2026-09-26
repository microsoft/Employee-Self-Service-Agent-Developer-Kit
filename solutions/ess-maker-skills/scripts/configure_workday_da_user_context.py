# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Preview, configure, and verify the Workday DA user-context redirect."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Any, Callable

import yaml

from auth import authenticate, query_all, update_record


SETUP_TOPIC_NAME = "[Admin] - User Context - Setup"
SETUP_SCHEMA_SUFFIX = ".topic.setusercontext"
TARGET_TOPIC_NAME = "Workday [System] - 1: Set User Context V2"
TARGET_SCHEMA_SUFFIX = ".topic.workdaysystemgetusercontextv2"
PLAN_MARKER = "WORKDAY_DA_USER_CONTEXT_PLAN_JSON:"
APPLIED_MARKER = "WORKDAY_DA_USER_CONTEXT_APPLIED_JSON:"
FAILED_MARKER = "WORKDAY_DA_USER_CONTEXT_FAILED_JSON:"


class WorkdayDAUserContextError(RuntimeError):
    """Raised when the user-context redirect cannot be changed safely."""


def _normalized_bot_id(bot_id: str) -> str:
    try:
        return str(uuid.UUID(str(bot_id)))
    except (ValueError, AttributeError) as exc:
        raise WorkdayDAUserContextError(
            "The active Workday DA agent has an invalid bot ID."
        ) from exc


def _topic_matches(
    topic: dict[str, Any],
    *,
    display_name: str,
    schema_suffix: str,
) -> bool:
    name = str(topic.get("name") or "").casefold()
    schema = str(topic.get("schemaname") or "").casefold()
    return name == display_name.casefold() or schema.endswith(schema_suffix)


def _single_topic(
    topics: list[dict[str, Any]],
    *,
    display_name: str,
    schema_suffix: str,
) -> dict[str, Any]:
    matches = [
        topic
        for topic in topics
        if _topic_matches(
            topic,
            display_name=display_name,
            schema_suffix=schema_suffix,
        )
    ]
    if len(matches) != 1:
        raise WorkdayDAUserContextError(
            f"Expected exactly one '{display_name}' topic in the active agent; "
            f"found {len(matches)}."
        )
    return matches[0]


def _dialog_document(data: str) -> dict[str, Any] | None:
    if not data.strip():
        return {}
    try:
        document = yaml.safe_load(data)
    except yaml.YAMLError:
        return None
    return document if isinstance(document, dict) else None


def _begin_dialog(document: dict[str, Any]) -> dict[str, Any]:
    begin = document.get("beginDialog")
    if isinstance(begin, dict):
        return begin
    dialog = document.get("dialog")
    if isinstance(dialog, dict) and isinstance(dialog.get("beginDialog"), dict):
        return dialog["beginDialog"]
    return {}


def _redirects_exactly(data: str, target_schema: str) -> bool:
    document = _dialog_document(data)
    if document is None:
        return False
    actions = _begin_dialog(document).get("actions")
    if not isinstance(actions, list) or len(actions) != 1:
        return False
    action = actions[0]
    return (
        isinstance(action, dict)
        and str(action.get("kind") or "").casefold() == "begindialog"
        and str(action.get("dialog") or "").casefold()
        == target_schema.casefold()
    )


def _is_bare_scaffold(data: str) -> bool:
    document = _dialog_document(data)
    if document is None:
        return False
    if not document:
        return True
    begin = _begin_dialog(document)
    if str(begin.get("kind") or "").casefold() != "onredirect":
        return False
    actions = begin.get("actions")
    return actions in (None, [])


def _redirect_yaml(target_schema: str) -> str:
    return (
        "kind: AdaptiveDialog\n"
        "beginDialog:\n"
        "  kind: OnRedirect\n"
        "  id: main\n"
        "  priority: 0\n"
        "  actions:\n"
        "    - kind: BeginDialog\n"
        "      id: QVk2yi\n"
        f"      dialog: {target_schema}\n"
    )


def inspect_workday_da_user_context(
    environment_url: str,
    token: str,
    bot_id: str,
    *,
    query: Callable[..., list[dict[str, Any]]] = query_all,
) -> dict[str, Any]:
    """Inspect the active agent's setup and Workday V2 target topics."""
    normalized_bot_id = _normalized_bot_id(bot_id)
    topics = query(
        environment_url.rstrip("/"),
        token,
        "botcomponents",
        "botcomponentid,name,schemaname,data,statecode,statuscode",
        (
            f"_parentbotid_value eq '{normalized_bot_id}' "
            "and componenttype eq 9"
        ),
    )
    setup = _single_topic(
        topics,
        display_name=SETUP_TOPIC_NAME,
        schema_suffix=SETUP_SCHEMA_SUFFIX,
    )
    target = _single_topic(
        topics,
        display_name=TARGET_TOPIC_NAME,
        schema_suffix=TARGET_SCHEMA_SUFFIX,
    )
    target_schema = str(target.get("schemaname") or "")
    if not target_schema:
        raise WorkdayDAUserContextError(
            f"'{TARGET_TOPIC_NAME}' has no schema name."
        )

    setup_data = str(setup.get("data") or "")
    if _redirects_exactly(setup_data, target_schema):
        action = "unchanged"
    elif _is_bare_scaffold(setup_data):
        action = "configure"
    else:
        action = "blocked-custom-content"

    return {
        "environmentUrl": environment_url.rstrip("/"),
        "botId": normalized_bot_id,
        "action": action,
        "redirectConfigured": action == "unchanged",
        "targetTopicActive": target.get("statecode") == 0,
        "setupTopic": {
            "id": str(setup.get("botcomponentid") or ""),
            "name": str(setup.get("name") or SETUP_TOPIC_NAME),
            "schemaName": str(setup.get("schemaname") or ""),
        },
        "targetTopic": {
            "id": str(target.get("botcomponentid") or ""),
            "name": str(target.get("name") or TARGET_TOPIC_NAME),
            "schemaName": target_schema,
        },
    }


def configure_workday_da_user_context(
    environment_url: str,
    bot_id: str,
    *,
    apply: bool,
    preferred_username: str | None = None,
    token_provider: Callable[..., str] = authenticate,
    query: Callable[..., list[dict[str, Any]]] = query_all,
    updater: Callable[..., bool] = update_record,
) -> dict[str, Any]:
    """Preview or apply the Workday V2 user-context redirect."""
    environment_url = environment_url.rstrip("/")
    token = token_provider(
        environment_url,
        preferred_username=preferred_username,
    )
    result = inspect_workday_da_user_context(
        environment_url,
        token,
        bot_id,
        query=query,
    )
    result["mode"] = "apply" if apply else "preview"

    if result["action"] == "blocked-custom-content":
        raise WorkdayDAUserContextError(
            f"'{SETUP_TOPIC_NAME}' contains custom actions. Refusing to "
            "overwrite them automatically; use the Copilot Studio fallback."
        )
    if not apply:
        return result

    if result["action"] == "configure":
        setup_id = result["setupTopic"]["id"]
        if not setup_id:
            raise WorkdayDAUserContextError(
                f"'{SETUP_TOPIC_NAME}' has no botcomponentid."
            )
        updater(
            environment_url,
            token,
            "botcomponents",
            setup_id,
            {"data": _redirect_yaml(result["targetTopic"]["schemaName"])},
        )

    verified = inspect_workday_da_user_context(
        environment_url,
        token,
        bot_id,
        query=query,
    )
    if not verified["redirectConfigured"]:
        raise WorkdayDAUserContextError(
            "Post-write verification did not find the Workday V2 redirect."
        )
    result["action"] = (
        "unchanged" if result["action"] == "unchanged" else "configured"
    )
    result["redirectConfigured"] = True
    result["targetTopicActive"] = verified["targetTopicActive"]
    result["verified"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Preview, configure, and verify the Workday DA user-context "
            "redirect."
        )
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--bot-id", required=True)
    parser.add_argument("--preferred-username")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    marker = APPLIED_MARKER if args.apply else PLAN_MARKER
    try:
        result = configure_workday_da_user_context(
            args.url,
            args.bot_id,
            apply=args.apply,
            preferred_username=args.preferred_username,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"{FAILED_MARKER}{json.dumps({'error': str(error)})}")
        sys.exit(1)
    print(f"{marker}{json.dumps(result, sort_keys=True)}")


if __name__ == "__main__":
    main()
