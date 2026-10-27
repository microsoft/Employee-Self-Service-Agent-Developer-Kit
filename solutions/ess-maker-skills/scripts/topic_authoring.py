# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Bounded native crafted-response topic operations for Maker sessions."""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse
import uuid

from adk_telemetry import emit_capability_use
from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderError,
    _acquire_token,
    cached_account_names,
    tenant_id_from_access_token,
)
from agentbuilder_object_model import object_models_to_yaml, yaml_to_object_models
from minimalbot_evaluation import MinimalBotEvaluationClient, MinimalBotEvaluationError
from setup_existing_da import (
    ExistingDASetupError,
    _validate_setup_target,
    validate_existing_dev_connection,
)


PATTERN_KEY = "EssAdkCraftedResponse"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def request_values(value: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "intent", "triggers", "response", "supportLink"}
    if set(value) - allowed:
        raise ValueError(f"Unknown request fields: {sorted(set(value) - allowed)}")
    for field in ("name", "intent", "response"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"{field} must be a non-empty string.")
    triggers = value.get("triggers")
    if (
        not isinstance(triggers, list)
        or not triggers
        or any(not isinstance(t, str) or not t.strip() for t in triggers)
    ):
        raise ValueError("triggers must contain non-empty strings.")
    link = value.get("supportLink")
    if link is not None and (
        not isinstance(link, str)
        or urlparse(link).scheme not in {"http", "https"}
        or not urlparse(link).netloc
        or urlparse(link).username is not None
        or urlparse(link).password is not None
    ):
        raise ValueError("supportLink must be an approved HTTP(S) URL without credentials.")
    return value


def build_dialog(value: dict[str, Any]) -> dict[str, Any]:
    text = value["response"]
    if value.get("supportLink"):
        text += "\n\n" + value["supportLink"]
    dialog = {
        "$kind": "AdaptiveDialog",
        "modelDescription": value["intent"],
        "beginDialog": {
            "$kind": "OnRecognizedIntent",
            "id": "main",
            "intent": {"$kind": "Intent", "triggerQueries": value["triggers"]},
            "actions": [
                {
                    "$kind": "SendActivity",
                    "id": "send_response",
                    "activity": {
                        "$kind": "Message",
                        "text": [{
                            "$kind": "TemplateLine",
                            "segments": [{"$kind": "TextSegment", "value": text}],
                        }],
                    },
                },
                {"$kind": "EndDialog", "id": "end"},
            ],
        },
    }
    projected = object_models_to_yaml([{"key": "topic", "objectModel": dialog}])[0]
    if projected.get("success") is not True:
        raise ValueError(f"Invalid native topic: {json.dumps(projected)}")
    converted = yaml_to_object_models([{"key": "topic", "yaml": projected["yaml"]}])[0]
    if converted.get("success") is not True or converted.get("elementType") != "AdaptiveDialog":
        raise ValueError(f"Invalid native topic YAML: {json.dumps(converted)}")
    if converted["objectModel"] != dialog:
        raise ValueError(
            "Native conversion changed the approved content. Revise the draft "
            "and obtain approval again before saving."
        )
    return dialog


def require_crafted(component: dict[str, Any]) -> None:
    if (
        component.get("$kind") != "DialogComponent"
        or component.get("extensionData", {}).get(PATTERN_KEY) is not True
        or component.get("managedProperties", {}).get("isManaged") is True
        or component.get("managedProperties", {}).get("isCustomizable") is False
    ):
        raise ValueError(
            "This is not an editable crafted-response topic created by this "
            "native authoring path. Packaged, system and integration topics "
            "are not supported."
        )
    dialog = component.get("dialog") or {}
    begin = dialog.get("beginDialog") or {}
    actions = begin.get("actions") or []
    if (
        dialog.get("$kind") != "AdaptiveDialog"
        or begin.get("$kind") != "OnRecognizedIntent"
        or [a.get("$kind") for a in actions] != ["SendActivity", "EndDialog"]
    ):
        raise ValueError("The saved topic no longer has the supported response-only shape.")
    activity = actions[0].get("activity") or {}
    text = activity.get("text") or []
    if (
        set(activity) != {"$kind", "text"}
        or activity["$kind"] != "Message"
        or len(text) != 1
        or text[0].get("$kind") != "TemplateLine"
        or len(text[0].get("segments") or []) != 1
        or text[0]["segments"][0].get("$kind") != "TextSegment"
    ):
        raise ValueError("The saved response contains unsupported dynamic content.")


def connect(root: Path, account: str | None) -> tuple[AgentBuilderClient, dict[str, Any]]:
    config = read_json(root / ".local" / "config.json")
    setup = read_json(root / ".local" / "setup" / "config.json")
    agent = config["agent"]
    selected = [
        entry for entry in setup.get("agents", {}).values()
        if entry.get("agent", {}).get("workspace_slug") == config.get("activeAgent")
    ]
    if (
        setup.get("schema_version") != 4
        or len(selected) != 1
        or selected[0].get("connect_ready") is not True
        or selected[0]["agent"].get("id") != agent.get("botId")
        or selected[0]["agent"].get("realm") != "dev"
    ):
        raise ValueError("Complete setup for the selected editable Dev agent first.")
    tenant = setup["environment"]["tenant_id"]
    cache = root / ".local" / ".agentbuilder_token_cache.bin"
    accounts = cached_account_names(cache)
    if account is None and len(accounts) != 1:
        raise ValueError(
            "Authentication requires one selected Maker account. Run /setup "
            "or supply --account; no account was selected automatically."
        )
    selected_account = account or accounts[0]
    with contextlib.redirect_stdout(sys.stderr):
        authenticated = _acquire_token(
            authority=f"https://login.microsoftonline.com/{tenant}",
            ring=config["ring"], cache_path=cache,
            force_account_selection=False, account_hint=selected_account,
            return_account_identity=True,
        )
    if not isinstance(authenticated, tuple):
        raise ValueError("Authentication did not return the selected Maker identity.")
    token, actual_account = authenticated
    if str(actual_account or "").casefold() != selected_account.casefold():
        raise ValueError("Authentication used a different account from the selected Maker.")
    if tenant_id_from_access_token(token).casefold() != tenant.casefold():
        raise ValueError("The authenticated tenant does not match the selected environment.")
    client = AgentBuilderClient(
        config["powerPlatformApiEndpoint"], token,
        ring=config["ring"], tenant_id=tenant,
        api_version=config["agentBuilderApiVersion"],
    )
    target = validate_existing_dev_connection(
        client, environment_id=config["environmentId"], agent_id=agent["botId"],
        expected_schema_name=agent["schemaName"],
    )
    _validate_setup_target(root, target)
    return client, target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("list", "read", "create", "update"))
    parser.add_argument("--kit-root", type=Path, default=Path.cwd())
    parser.add_argument("--account")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--component-id")
    parser.add_argument("--expected", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--yes", action="store_true", help="Apply the explicitly approved save.")
    args = parser.parse_args(argv)
    value = None
    if args.operation in {"create", "update"}:
        if args.request is None:
            parser.error("--request is required.")
        value = request_values(read_json(args.request))
        desired = build_dialog(value)
    if args.operation == "update" and args.expected is None:
        parser.error("--expected must identify the saved read snapshot.")
    if args.operation == "create" and args.yes and args.expected is None:
        parser.error("--expected must identify the approved create preview.")
    if args.operation == "read" and not args.component_id:
        parser.error("--component-id is required.")
    if args.output and args.output.exists():
        raise FileExistsError(f"Choose a new output path; this file exists: {args.output}")
    client, target = connect(args.kit_root.resolve(), args.account)
    agent_id = target["agent"]["id"]
    payload = client.fetch_components(agent_id)
    components = [
        change["component"] for change in payload.get("botComponentChanges", [])
        if isinstance(change.get("component"), dict)
    ]
    result: dict[str, Any] = {"target": target, "operation": args.operation}
    if args.operation == "list":
        result["topics"] = [
            {key: c.get(key) for key in ("id", "schemaName", "displayName", "state", "status")}
            for c in components
            if c.get("$kind") == "DialogComponent"
            and c.get("extensionData", {}).get(PATTERN_KEY) is True
        ]
    elif args.operation == "read":
        matches = [c for c in components if c.get("id") == args.component_id]
        if len(matches) != 1:
            raise ValueError("The selected topic is missing or ambiguous.")
        require_crafted(matches[0])
        result["component"] = matches[0]
    else:
        assert value is not None
        snapshot = read_json(args.expected) if args.expected else None
        if snapshot is not None:
            for section, fields in (
                ("environment", ("id", "tenantId", "ring", "powerPlatformApiEndpoint")),
                ("agent", ("id", "schemaName", "realm")),
            ):
                if any(
                    snapshot["target"][section].get(field) != target[section].get(field)
                    for field in fields
                ):
                    raise ValueError("The expected snapshot belongs to a different target.")
        if args.operation == "create" and args.yes:
            assert snapshot is not None
            if (
                snapshot.get("operation") != "create"
                or snapshot.get("saved") is not False
                or snapshot.get("approvedValues") != value
            ):
                raise ValueError(
                    "The create request differs from its approved preview. "
                    "Preview the exact change and obtain approval before saving."
                )
        native = MinimalBotEvaluationClient(
            target["environment"]["id"], agent_id, client.tenant_id,
            ring=client.ring, host=client.host,
            access_token=client.headers["Authorization"].split(" ", 1)[1],
            session=client.session,
        )
        result.update({"approvedValues": value, "desiredDialog": desired, "saved": False})
        if args.operation == "create":
            if any(
                c.get("$kind") == "DialogComponent"
                and str(c.get("displayName") or "").strip().casefold()
                == value["name"].strip().casefold()
                for c in components
            ):
                raise ValueError("A topic with this name already exists. No create was sent.")
            component_id = str(uuid.uuid4())
            component = {
                "$kind": "DialogComponent", "id": component_id,
                "schemaName": target["agent"]["schemaName"] + ".topic.CraftedResponse"
                + component_id.replace("-", ""),
                "displayName": value["name"], "description": value["intent"],
                "parentBotId": agent_id, "state": "Inactive", "status": "Inactive",
                "dialog": desired,
                "extensionData": {"UseProvidedBotComponentId": True, PATTERN_KEY: True},
            }
            if args.yes:
                emit_capability_use("topic_create")
                result.update(native.create_dialog_component(component))
                try:
                    require_crafted(result["component"])
                except ValueError as exc:
                    raise ValueError(
                        f"Native create returned componentId={component_id}, "
                        f"schemaName={component['schemaName']}, but its supported "
                        f"authoring boundary could not be verified: {exc}. "
                        "Inspect native saved state; do not repeat creation."
                    ) from exc
        else:
            assert snapshot is not None
            expected = snapshot["component"]
            require_crafted(expected)
            current = [c for c in components if c.get("id") == expected["id"]]
            if len(current) != 1:
                raise ValueError("The selected native topic identity is no longer unique.")
            require_crafted(current[0])
            if value["name"] != current[0]["displayName"]:
                raise ValueError("Topic renaming is not supported by this bounded operation.")
            if current[0]["schemaName"] != expected["schemaName"]:
                raise ValueError("The selected topic schema changed after the read.")
            # Preserve the saved node identities and all unedited native fields.
            desired = copy.deepcopy(expected["dialog"])
            desired["modelDescription"] = value["intent"]
            desired["beginDialog"]["intent"]["triggerQueries"] = value["triggers"]
            desired["beginDialog"]["actions"][0]["activity"] = build_dialog(value)[
                "beginDialog"
            ]["actions"][0]["activity"]
            result.update({"before": current[0], "desiredDialog": desired})
            if args.yes:
                emit_capability_use("topic_update")
                result.update(native.update_dialog_components([{
                    "componentId": expected["id"], "schemaName": expected["schemaName"],
                    "expectedDialog": expected["dialog"], "dialog": desired,
                    "requireCleanDiagnostics": True,
                }], _retry_on_conflict=False))
                saved = client.fetch_components(agent_id)
                result["component"] = next(
                    c["component"] for c in saved["botComponentChanges"]
                    if c.get("component", {}).get("id") == expected["id"]
                )
        result["saved"] = args.yes
        result["published"] = False
        result["conversationVerified"] = False
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        AgentBuilderError, ExistingDASetupError, MinimalBotEvaluationError,
        ValueError, OSError,
    ) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
