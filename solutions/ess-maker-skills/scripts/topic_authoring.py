# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Preview and save ordinary topic YAML for the selected editable Dev agent."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any
import uuid

from adk_telemetry import emit_capability_use
from agentbuilder import AgentBuilderError
from agentbuilder_object_model import (
    ObjectModelConverterError,
    object_models_to_yaml,
    yaml_to_object_models,
)
from alm_enrollment import _exception_chain
from minimalbot_evaluation import MinimalBotEvaluationClient, MinimalBotEvaluationError
from setup_existing_da import (
    ExistingDASetupError,
    connect_selected_dev_workspace,
)


class TopicBookkeepingError(RuntimeError):
    """A local tracking failure after a verified remote topic result."""

    def __init__(self, message: str, evidence: dict[str, Any]) -> None:
        self.evidence = evidence
        super().__init__(message)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _active_agent_folder(root: Path) -> Path:
    config = read_json(root / ".local" / "config.json")
    folder = config.get("agent", {}).get("folder")
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError("The selected agent folder is missing from .local/config.json.")
    path = Path(folder)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _topic_path(agent_folder: Path, path: Path) -> tuple[Path, str]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(agent_folder).as_posix()
    except ValueError as exc:
        raise ValueError("Topic drafts must be inside the selected agent folder.") from exc
    if (
        not relative.startswith("topics/")
        or not resolved.name.endswith(".mcs.yml")
        or resolved.name == ".mcs.yml"
    ):
        raise ValueError("Topic drafts must use topics/<name>.mcs.yml.")
    return resolved, relative


def _load_component_map(agent_folder: Path) -> dict[str, Any]:
    path = agent_folder / ".component-map.json"
    value = read_json(path)
    if any(not isinstance(key, str) or not isinstance(entry, dict)
           for key, entry in value.items()):
        raise ValueError(".component-map.json contains an invalid entry.")
    return value


def _convert_topic_yaml(content: str, key: str) -> dict[str, Any]:
    converted = yaml_to_object_models([{"key": key, "yaml": content}])[0]
    if converted.get("success") is not True:
        error = converted.get("error") or {}
        raise ValueError(
            "Could not convert topic YAML: "
            + str(error.get("message") or "unknown conversion error")
        )
    if converted.get("elementType") != "AdaptiveDialog":
        raise ValueError("The topic draft must contain one AdaptiveDialog.")
    dialog = converted.get("objectModel")
    if not isinstance(dialog, dict):
        raise ValueError("The topic converter returned no dialog object.")
    return dialog


def _project_topic(component: dict[str, Any]) -> str:
    projected = object_models_to_yaml(
        [{"key": str(component.get("id") or "topic"), "objectModel": component["dialog"]}]
    )[0]
    if projected.get("success") is not True:
        error = projected.get("error") or {}
        raise ValueError(
            "Could not project topic YAML: "
            + str(error.get("message") or "unknown conversion error")
        )
    yaml_content = projected.get("yaml")
    if not isinstance(yaml_content, str) or not yaml_content.strip():
        raise ValueError("The topic converter returned empty YAML.")
    return yaml_content


def _components(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        change["component"]
        for change in payload.get("botComponentChanges", [])
        if isinstance(change, dict)
        and isinstance(change.get("component"), dict)
        and change["component"].get("$kind") == "DialogComponent"
    ]


def _mapped_component(
    component_map: dict[str, Any],
    relative_path: str,
    components: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = component_map.get(relative_path)
    if not isinstance(entry, dict) or entry.get("componentKind") != "DialogComponent":
        raise ValueError(
            f"The selected topic is not registered in .component-map.json: {relative_path}"
        )
    component_id = str(entry.get("componentId") or "")
    schema_name = str(entry.get("schemaName") or "")
    matches = [
        component
        for component in components
        if str(component.get("id") or "").casefold() == component_id.casefold()
    ]
    if (
        len(matches) != 1
        or not component_id
        or not schema_name
        or str(matches[0].get("schemaName") or "").casefold() != schema_name.casefold()
    ):
        raise ValueError("The selected topic mapping no longer identifies one live topic.")
    return entry, matches[0]


def _target_matches(expected: dict[str, Any], target: dict[str, Any]) -> bool:
    return all(
        expected.get(section, {}).get(field) == target.get(section, {}).get(field)
        for section, fields in (
            ("environment", ("id", "tenantId", "ring", "powerPlatformApiEndpoint")),
            ("agent", ("id", "schemaName", "realm")),
        )
        for field in fields
    )


def _native_client(client: Any, target: dict[str, Any]) -> MinimalBotEvaluationClient:
    return MinimalBotEvaluationClient(
        target["environment"]["id"],
        target["agent"]["id"],
        target["environment"]["tenantId"],
        ring=target["environment"]["ring"],
        host=client.host,
        access_token=client.headers["Authorization"].split(" ", 1)[1],
        session=client.session,
    )


def _acknowledge_topic(
    agent_folder: Path,
    relative_path: str,
    captured_yaml: str,
) -> None:
    baseline = agent_folder / ".baseline" / Path(relative_path)
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text(captured_yaml, encoding="utf-8", newline="")


def _register_created_topic(
    agent_folder: Path,
    relative_path: str,
    component: dict[str, Any],
) -> None:
    component_map = _load_component_map(agent_folder)
    if relative_path in component_map:
        raise ValueError(
            "The created topic path became registered during the save. "
            "The remote topic is verified, but local mapping was not replaced."
        )
    component_map[relative_path] = {
        "componentKind": "DialogComponent",
        "componentId": component.get("id"),
        "schemaName": component.get("schemaName"),
        "displayName": component.get("displayName"),
        "version": component.get("version"),
    }
    _write_json(agent_folder / ".component-map.json", component_map)


def _emit_result(result: dict[str, Any], output: Path | None) -> None:
    content = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    print(content, end="")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("list", "read", "create", "update"))
    parser.add_argument("--kit-root", type=Path, default=Path.cwd())
    parser.add_argument("--account")
    parser.add_argument("--topic", type=Path, help="Mapped topic path for read.")
    parser.add_argument("--draft", type=Path, help="Submitted .mcs.yml draft.")
    parser.add_argument("--display-name", help="Creation-only display name.")
    parser.add_argument("--description", help="Creation-only component description.")
    parser.add_argument("--expected", type=Path, help="Fresh read snapshot for update.")
    parser.add_argument("--output", type=Path, help="Reusable JSON result path.")
    parser.add_argument("--yaml-output", type=Path, help="Optional reusable read projection.")
    parser.add_argument("--yes", action="store_true", help="Apply the separately approved save.")
    args = parser.parse_args(argv)

    if args.operation == "read" and args.topic is None:
        parser.error("read requires --topic.")
    if args.operation in {"create", "update"} and args.draft is None:
        parser.error(f"{args.operation} requires --draft.")
    if args.operation == "create" and not str(args.display_name or "").strip():
        parser.error("create requires --display-name.")
    if args.operation == "update" and args.expected is None:
        parser.error("update requires --expected from a fresh read.")
    if args.operation not in {"create", "update"} and args.yes:
        parser.error("--yes is valid only for create or update.")
    if args.yaml_output and args.operation != "read":
        parser.error("--yaml-output is valid only for read.")

    root = args.kit_root.resolve()
    client, target = connect_selected_dev_workspace(root, args.account)
    agent_folder = _active_agent_folder(root)
    component_map = _load_component_map(agent_folder)
    live_components = _components(client.fetch_components(target["agent"]["id"]))
    mapped_paths = {
        str(entry.get("componentId") or "").casefold(): path
        for path, entry in component_map.items()
        if entry.get("componentKind") == "DialogComponent"
    }
    result: dict[str, Any] = {"target": target, "operation": args.operation}

    if args.operation == "list":
        result["topics"] = [
            {
                **{
                    key: component.get(key)
                    for key in ("id", "schemaName", "displayName", "state", "status")
                },
                "path": mapped_paths.get(str(component.get("id") or "").casefold()),
            }
            for component in live_components
        ]
        _emit_result(result, args.output)
        return 0

    if args.operation == "read":
        assert args.topic is not None
        _, relative_path = _topic_path(agent_folder, args.topic)
        _, component = _mapped_component(component_map, relative_path, live_components)
        result.update({"path": relative_path, "component": component})
        _emit_result(result, args.output)
        if args.yaml_output:
            args.yaml_output.parent.mkdir(parents=True, exist_ok=True)
            args.yaml_output.write_text(
                _project_topic(component),
                encoding="utf-8",
                newline="",
            )
        return 0

    assert args.draft is not None
    draft_path, relative_path = _topic_path(agent_folder, args.draft)
    captured_yaml = draft_path.read_text(encoding="utf-8")
    desired_dialog = _convert_topic_yaml(captured_yaml, relative_path)
    native = _native_client(client, target)
    result.update(
        {
            "path": relative_path,
            "desiredDialog": desired_dialog,
            "saved": False,
            "published": False,
            "conversationVerified": False,
        }
    )

    if args.operation == "create":
        if relative_path in component_map:
            raise ValueError(
                "The draft path already identifies an existing topic. Use update."
            )
        filename_stem = draft_path.name[: -len(".mcs.yml")]
        schema_name = f"{target['agent']['schemaName']}.topic.{filename_stem}"
        display_name = str(args.display_name).strip()
        result["advisories"] = [
            {
                "kind": "same-name",
                "componentId": component.get("id"),
                "schemaName": component.get("schemaName"),
                "displayName": component.get("displayName"),
            }
            for component in live_components
            if str(component.get("displayName") or "").strip().casefold()
            == display_name.casefold()
        ]
        component = {
            "$kind": "DialogComponent",
            "id": str(uuid.uuid4()),
            "schemaName": schema_name,
            "displayName": display_name,
            "description": args.description
            if args.description is not None
            else desired_dialog.get("modelDescription"),
            "parentBotId": target["agent"]["id"],
            "state": "Inactive",
            "status": "Inactive",
            "dialog": desired_dialog,
            "extensionData": {"UseProvidedBotComponentId": True},
        }
        result["componentPreview"] = component
        if args.yes:
            emit_capability_use("topic_create")
            saved = native.create_dialog_component(component)
            result.update(saved)
            result["saved"] = True
            try:
                _register_created_topic(agent_folder, relative_path, saved["component"])
                _acknowledge_topic(agent_folder, relative_path, captured_yaml)
            except (OSError, ValueError) as exc:
                result["bookkeepingComplete"] = False
                raise TopicBookkeepingError(
                    "The topic was created and verified, but local tracking failed.",
                    {"remoteResult": result, "localError": _exception_chain(exc)},
                ) from exc
            result["bookkeepingComplete"] = True
    else:
        assert args.expected is not None
        expected = read_json(args.expected)
        if not _target_matches(expected.get("target", {}), target):
            raise ValueError("The expected topic snapshot belongs to a different target.")
        if expected.get("path") != relative_path:
            raise ValueError("The expected topic snapshot belongs to a different path.")
        entry, current = _mapped_component(component_map, relative_path, live_components)
        expected_component = expected.get("component")
        if not isinstance(expected_component, dict):
            raise ValueError("The expected topic snapshot contains no component.")
        if (
            str(expected_component.get("id") or "").casefold()
            != str(entry.get("componentId") or "").casefold()
            or str(expected_component.get("schemaName") or "").casefold()
            != str(entry.get("schemaName") or "").casefold()
        ):
            raise ValueError("The expected topic identity differs from its current mapping.")
        result["before"] = current
        if args.yes:
            emit_capability_use("topic_update")
            update = native.update_dialog_components(
                [
                    {
                        "componentId": entry["componentId"],
                        "schemaName": entry["schemaName"],
                        "expectedDialog": expected_component["dialog"],
                        "dialog": desired_dialog,
                        "requireCleanDiagnostics": True,
                    }
                ],
                _retry_on_conflict=False,
            )
            result.update(update)
            result["saved"] = True
            try:
                _acknowledge_topic(agent_folder, relative_path, captured_yaml)
            except OSError as exc:
                result["bookkeepingComplete"] = False
                raise TopicBookkeepingError(
                    "The topic update was verified, but baseline acknowledgement failed.",
                    {"remoteResult": result, "localError": _exception_chain(exc)},
                ) from exc
            result["bookkeepingComplete"] = True

    try:
        _emit_result(result, args.output)
    except OSError as exc:
        if args.yes and result.get("saved") is True:
            result["outputComplete"] = False
            raise TopicBookkeepingError(
                "The topic result was verified, but reusable output writing failed.",
                {"remoteResult": result, "localError": _exception_chain(exc)},
            ) from exc
        raise
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        AgentBuilderError,
        ExistingDASetupError,
        MinimalBotEvaluationError,
        ObjectModelConverterError,
        TopicBookkeepingError,
        ValueError,
        OSError,
    ) as exc:
        error = {
            "completed": False,
            "errors": _exception_chain(exc),
            **getattr(exc, "evidence", {}),
        }
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1) from exc
