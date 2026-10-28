# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Bounded native crafted-response topic operations for Maker sessions."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse
import uuid

from adk_telemetry import emit_capability_use
from agentbuilder import AgentBuilderError
from alm_enrollment import _exception_chain, _redact_evidence
from agentbuilder_object_model import object_models_to_yaml, yaml_to_object_models
from agentbuilder_object_model import ObjectModelConverterError
from minimalbot_evaluation import (
    ComponentEditError, MinimalBotEvaluationClient, MinimalBotEvaluationError,
    resolve_workday_dialogs,
)
from workspace_state import (
    acknowledge_files, collect_files, compute_diff, load_component_map, matches_only,
    read_json,
)
from setup_existing_da import (
    ExistingDASetupError,
    connect_selected_dev_workspace,
)


PATTERN_KEY = "EssAdkCraftedResponse"


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


def plan_workspace_topic_updates(
    agent_dir,
    only_globs,
    *,
    activate_topics=False,
    agent_schema=None,
):
    """Build guarded updates for scoped, existing MinimalBot topics."""
    if not only_globs:
        return []
    baseline_dir = os.path.join(agent_dir, ".baseline")
    if not os.path.isdir(baseline_dir):
        if activate_topics or any(
            pattern.replace("\\", "/").startswith("topics/") for pattern in only_globs
        ):
            raise MinimalBotEvaluationError("The selected topic workspace has no baseline.")
        return []
    baseline = collect_files(baseline_dir)
    working = collect_files(agent_dir)
    changed, new, deleted = compute_diff(baseline, working)
    selected_changed = sorted(
        path
        for path in changed
        if matches_only(path, only_globs)
        and path.replace("\\", "/").startswith("topics/")
        and path.endswith(".mcs.yml")
    )
    selected_new_or_deleted = sorted(
        path
        for path in (*new, *deleted)
        if matches_only(path, only_globs)
        and path.replace("\\", "/").startswith("topics/")
    )
    if selected_new_or_deleted:
        raise MinimalBotEvaluationError(
            "MinimalBot scoped topic push supports updates to existing topics "
            "only; create/delete is not allowed: "
            + ", ".join(selected_new_or_deleted)
        )
    if not selected_changed and not activate_topics:
        return []
    raw_component_map = load_component_map(agent_dir)
    component_map = {}
    for raw_path, entry in raw_component_map.items():
        normalized_path = str(raw_path).replace("\\", "/")
        if normalized_path in component_map:
            raise MinimalBotEvaluationError(
                "The component map contains duplicate normalized paths."
            )
        component_map[normalized_path] = entry

    selected_activation = []
    if activate_topics:
        workday_entries = resolve_workday_dialogs(
            agent_dir,
            agent_schema or "",
        )
        workday_by_path = {
            entry["path"]: entry
            for entry in workday_entries
        }
        selected_activation = sorted(
            path
            for path in workday_by_path
            if matches_only(path, only_globs)
        )
        missing = sorted(set(workday_by_path) - set(selected_activation))
        selected_dialogs = {
            str(path).replace("\\", "/")
            for path, entry in component_map.items()
            if isinstance(path, str)
            and isinstance(entry, dict)
            and entry.get("componentKind") == "DialogComponent"
            and matches_only(path, only_globs)
        }
        non_workday = sorted(selected_dialogs - set(workday_by_path))
        if missing or non_workday:
            details = []
            if missing:
                details.append(
                    f"{len(missing)} mapped Workday topic(s) were omitted"
                )
            if non_workday:
                details.append(
                    "the activation scope also matched non-Workday topics: "
                    + ", ".join(non_workday)
                )
            raise MinimalBotEvaluationError(
                "Workday activation must target exactly the complete mapped "
                "Workday topic set; "
                + "; ".join(details)
                + "."
            )
        changed_workday = sorted(
            path for path in selected_changed if path in workday_by_path
        )
        if changed_workday:
            raise MinimalBotEvaluationError(
                "Workday activation cannot publish pending topic content "
                "changes. Push or discard these changes separately before "
                "activation: "
                + ", ".join(changed_workday)
            )
        selected_changed = []
    selected_paths = sorted(
        set(selected_changed) | set(selected_activation)
    )
    if not selected_paths:
        return []

    conversion_items = []
    for path in selected_changed:
        conversion_items.extend(
            (
                {"key": f"{path}:baseline", "yaml": baseline[path]},
                {"key": f"{path}:working", "yaml": working[path]},
            )
        )
    try:
        converted = yaml_to_object_models(conversion_items)
    except ObjectModelConverterError as exc:
        raise MinimalBotEvaluationError(
            f"Could not convert scoped topic YAML: {exc}"
        ) from exc
    converted_by_key = {entry["key"]: entry for entry in converted}

    updates = []
    for path in selected_paths:
        entry = component_map.get(path)
        if not isinstance(entry, dict):
            raise MinimalBotEvaluationError(
                f"Scoped topic is missing from .component-map.json: {path}"
            )
        if entry.get("componentKind") != "DialogComponent":
            raise MinimalBotEvaluationError(
                f"Scoped path is not a dialog component: {path}"
            )
        component_id = str(entry.get("componentId") or "").strip()
        schema_name = str(entry.get("schemaName") or "").strip()
        if not component_id or not schema_name:
            raise MinimalBotEvaluationError(
                f"Scoped topic identity is incomplete in the component map: "
                f"{path}"
            )
        update = {
            "path": path,
            "componentId": component_id,
            "schemaName": schema_name,
            "displayName": str(entry.get("displayName") or path),
        }
        if path in selected_changed:
            baseline_result = converted_by_key[f"{path}:baseline"]
            working_result = converted_by_key[f"{path}:working"]
            failed = next(
                (
                    result
                    for result in (baseline_result, working_result)
                    if result.get("success") is not True
                ),
                None,
            )
            if failed:
                error = failed.get("error") or {}
                raise MinimalBotEvaluationError(
                    f"Could not convert scoped topic {path}: "
                    f"{error.get('message') or 'unknown conversion error'}"
                )
            if (
                baseline_result.get("elementType") != "AdaptiveDialog"
                or working_result.get("elementType") != "AdaptiveDialog"
            ):
                raise MinimalBotEvaluationError(
                    f"Scoped topic is not an AdaptiveDialog: {path}"
                )
            update["expectedDialog"] = baseline_result["objectModel"]
            update["dialog"] = working_result["objectModel"]
            update["submittedYaml"] = working[path]
        if path in selected_activation:
            update["state"] = "Active"
            update["status"] = "Active"
        updates.append(update)
    return updates


def save_workspace_topic_updates(
    client, agent_dir, updates, *, retry_on_conflict=True,
):
    """Save mapped Object Model updates and acknowledge their captured YAML."""
    submitted = {}
    for update in updates:
        if "dialog" in update:
            if not isinstance(update.get("submittedYaml"), str) or not update.get("path"):
                raise ValueError("Content updates require a path and captured submitted YAML.")
            submitted[update["path"]] = update["submittedYaml"]
    result = (
        client.update_dialog_components(updates)
        if retry_on_conflict
        else client.update_dialog_components(updates, _retry_on_conflict=False)
    )
    try:
        acknowledge_files(agent_dir, submitted)
    except (OSError, ValueError) as exc:
        raise ComponentEditError(
            "Topic save was verified remotely, but local acknowledgement failed. "
            "Do not repeat the remote write to repair local bookkeeping.",
            {"remoteResult": result, "acknowledgementComplete": False},
        ) from exc
    return result


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
    client, target = connect_selected_dev_workspace(args.kit_root.resolve(), args.account)
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
                result["saved"] = True
                try:
                    require_crafted(result["component"])
                except ValueError as exc:
                    raise ComponentEditError(
                        f"Native create returned componentId={component_id}, "
                        f"schemaName={component['schemaName']}, but its supported "
                        f"authoring boundary could not be verified: {exc}. "
                        "Inspect native saved state; do not repeat creation.",
                        {"remoteResult": result},
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
                result["saved"] = True
                result["component"] = next(
                    c for c in result["components"]
                    if str(c.get("id") or "").casefold() == str(expected["id"]).casefold()
                )
        result["saved"] = args.yes
        result["published"] = False
        result["conversationVerified"] = False
    try:
        output = json.dumps(_redact_evidence(result), indent=2, ensure_ascii=False) + "\n"
        print(output, end="")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
    except Exception as exc:
        raise ComponentEditError(
            "The topic operation result was observed, but writing its output failed.",
            {"operationResult": result, "outputComplete": False},
        ) from exc
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        AgentBuilderError, ExistingDASetupError, MinimalBotEvaluationError,
        ValueError, OSError,
    ) as exc:
        print(json.dumps({
            "errors": _exception_chain(exc), "evidence": getattr(exc, "evidence", {}),
        }), file=sys.stderr)
        raise SystemExit(1) from exc
