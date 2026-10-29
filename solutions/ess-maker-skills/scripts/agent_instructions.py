# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Preview and save the instruction section from the selected agent YAML."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import yaml

from agentbuilder import AgentBuilderError
from agentbuilder_object_model import (
    ObjectModelConverterError,
    object_models_to_yaml,
    yaml_to_object_models,
)
from alm_enrollment import _exception_chain
from minimalbot_evaluation import (
    ComponentEditError,
    MinimalBotEvaluationClient,
    MinimalBotEvaluationError,
)
from setup_existing_da import (
    ExistingDASetupError,
    connect_selected_dev_workspace,
)
from workspace_state import _atomic_write_text, read_json


class InstructionBookkeepingError(ComponentEditError):
    """A baseline failure after a verified remote instruction result."""


def _active_agent_folder(root: Path) -> Path:
    config = read_json(root / ".local" / "config.json")
    folder = config.get("agent", {}).get("folder")
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError("The selected agent folder is missing from .local/config.json.")
    path = Path(folder)
    if not path.is_absolute():
        path = root / path
    return path.resolve()


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


def _metadata_from_yaml(content: str, key: str) -> dict[str, Any]:
    converted = yaml_to_object_models([{"key": key, "yaml": content}])[0]
    if converted.get("success") is not True:
        error = converted.get("error") or {}
        raise ValueError(
            "Could not convert agent YAML: "
            + str(error.get("message") or "unknown conversion error")
        )
    metadata = converted.get("objectModel")
    instructions = metadata.get("instructions") if isinstance(metadata, dict) else None
    if (
        not isinstance(metadata, dict)
        or not isinstance(instructions, dict)
        or instructions.get("$kind") != "TemplateLine"
        or not isinstance(instructions.get("segments"), list)
    ):
        raise ValueError(
            "agent.mcs.yml must contain TemplateLine instructions with segments."
        )
    return metadata


def _project_metadata(metadata: dict[str, Any], key: str) -> str:
    projected = object_models_to_yaml([{"key": key, "objectModel": metadata}])[0]
    if projected.get("success") is not True:
        error = projected.get("error") or {}
        raise ValueError(
            "Could not project agent YAML: "
            + str(error.get("message") or "unknown conversion error")
        )
    yaml_content = projected.get("yaml")
    if not isinstance(yaml_content, str) or not yaml_content.strip():
        raise ValueError("The agent converter returned empty YAML.")
    return yaml_content


def acknowledge_instruction_baseline(agent_dir: Path, submitted_yaml: str) -> None:
    """Acknowledge submitted instructions only; leave later drafts untouched."""
    path = Path(agent_dir) / ".baseline" / "agent.mcs.yml"
    baseline = yaml.safe_load(path.read_text(encoding="utf-8"))
    submitted = yaml.safe_load(submitted_yaml)
    if not isinstance(baseline, dict) or not isinstance(submitted, dict):
        raise ValueError("Instruction acknowledgement requires agent YAML mappings.")
    if "instructions" not in submitted:
        raise ValueError("Submitted agent YAML has no instructions section.")
    baseline["instructions"] = submitted["instructions"]
    _atomic_write_text(
        path, yaml.safe_dump(baseline, sort_keys=False, allow_unicode=True),
    )


def _emit_result(result: dict[str, Any], output: Path | None) -> None:
    content = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    print(content, end="")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("read", "update"))
    parser.add_argument("--kit-root", type=Path, default=Path.cwd())
    parser.add_argument("--account")
    parser.add_argument("--draft", type=Path, help="Desired agent.mcs.yml draft.")
    parser.add_argument("--expected", type=Path, help="Fresh native read snapshot.")
    parser.add_argument("--output", type=Path, help="Reusable JSON result path.")
    parser.add_argument("--yaml-output", type=Path, help="Optional reusable read projection.")
    parser.add_argument("--yes", action="store_true", help="Apply the separately approved save.")
    args = parser.parse_args(argv)

    if args.operation == "read" and (args.yes or args.draft or args.expected):
        parser.error("read does not accept --yes, --draft, or --expected.")
    if args.operation == "update" and (args.draft is None or args.expected is None):
        parser.error("update requires --draft and --expected.")
    if args.yaml_output and args.operation != "read":
        parser.error("--yaml-output is valid only for read.")

    root = args.kit_root.resolve()
    client, target = connect_selected_dev_workspace(root, args.account)
    agent_folder = _active_agent_folder(root)
    native = _native_client(client, target)
    current = native.read_agent_instructions()
    result: dict[str, Any] = {
        "target": target,
        "operation": args.operation,
        **current,
        "published": False,
        "conversationVerified": False,
    }

    if args.operation == "read":
        _emit_result(result, args.output)
        if args.yaml_output:
            metadata = {
                **current["component"]["metadata"],
                "displayName": current["component"].get("displayName"),
            }
            args.yaml_output.parent.mkdir(parents=True, exist_ok=True)
            args.yaml_output.write_text(
                _project_metadata(metadata, "agent"),
                encoding="utf-8",
                newline="",
            )
        return 0

    assert args.draft is not None and args.expected is not None
    draft_path = args.draft.resolve()
    if draft_path != (agent_folder / "agent.mcs.yml").resolve():
        raise ValueError("Instruction updates use the selected agent's agent.mcs.yml draft.")
    captured_yaml = draft_path.read_text(encoding="utf-8")
    desired_metadata = _metadata_from_yaml(captured_yaml, "agent")
    desired_instructions = desired_metadata["instructions"]
    expected = read_json(args.expected)
    if not _target_matches(expected.get("target", {}), target):
        raise ValueError("The expected instruction snapshot belongs to a different target.")
    expected_component = expected.get("component")
    if not isinstance(expected_component, dict):
        raise ValueError("The expected instruction snapshot contains no GPT component.")
    expected_instructions = expected_component.get("metadata", {}).get("instructions")
    if not isinstance(expected_instructions, dict):
        raise ValueError("The expected instruction snapshot contains no instructions.")
    current_identity = {
        key: current["component"].get(key)
        for key in ("id", "schemaName", "parentBotId")
    }
    expected_identity = {
        key: expected_component.get(key)
        for key in ("id", "schemaName", "parentBotId")
    }
    if current_identity != expected_identity:
        raise ValueError("The native GPT component identity changed after the read.")
    if current["component"]["metadata"]["instructions"] != expected_instructions:
        raise ValueError("Native instructions changed after the expected read.")

    result.update(
        {
            "expectedInstructions": expected_instructions,
            "desiredInstructions": desired_instructions,
            "changed": desired_instructions != expected_instructions,
            "saved": False,
        }
    )
    if args.yes:
        update = native.update_agent_instructions(
            expected_component,
            desired_instructions=desired_instructions,
        )
        result.update(update)
        result["saved"] = update["verifiedComponents"] == 1
        try:
            acknowledge_instruction_baseline(agent_folder, captured_yaml)
        except (ObjectModelConverterError, OSError, ValueError) as exc:
            result["bookkeepingComplete"] = False
            raise InstructionBookkeepingError(
                "The instruction result was verified, but baseline acknowledgement failed.",
                {"remoteResult": result, "localError": _exception_chain(exc)},
            ) from exc
        result["bookkeepingComplete"] = True

    try:
        _emit_result(result, args.output)
    except OSError as exc:
        if args.yes and result.get("saved") is True:
            result["outputComplete"] = False
            raise InstructionBookkeepingError(
                "The instruction result was verified, but reusable output writing failed.",
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
        InstructionBookkeepingError,
        MinimalBotEvaluationError,
        ObjectModelConverterError,
        ValueError,
        OSError,
    ) as exc:
        print(
            json.dumps(
                {
                    "completed": False,
                    "errors": _exception_chain(exc),
                    **getattr(exc, "evidence", {}),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
