# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only source preflight; no API client or live-agent mutation."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml


SETUP_FILENAME = "WorkdayOSSTemplateConfigurationSetup.yaml"
UNAPPROVED_ACTIONS = {"AnswerQuestionWithAI"}


class PlanError(ValueError):
    pass


def action_nodes(value: Any, parent_key: str = "") -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if parent_key in ("actions", "elseActions") and isinstance(item, dict):
                if isinstance(item.get("kind"), str):
                    nodes.append(item)
            nodes.extend(action_nodes(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            nodes.extend(action_nodes(item, key))
    return nodes


def read_dialog(path: Path, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not path.resolve().is_relative_to(root):
        raise PlanError(f"Sample path escapes the selected root: {path.name}")
    raw = path.read_bytes()
    document = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(document, dict) or document.get("kind") != "AdaptiveDialog":
        raise PlanError(f"Expected AdaptiveDialog: {path.relative_to(root)}")
    actions = action_nodes(document)
    kinds = Counter(node["kind"] for node in actions)
    references = sorted({
        node["dialog"] for node in actions
        if node["kind"] == "BeginDialog" and isinstance(node.get("dialog"), str)
    })
    blocked = sorted(UNAPPROVED_ACTIONS.intersection(kinds))
    return document, {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "actionKinds": dict(sorted(kinds.items())),
        "childDialogsToResolve": references,
        "unapprovedActionKinds": blocked,
    }


def build_plan(
    samples_root: Path, topics: list[str] | None = None, *, select_all: bool = False
) -> dict[str, Any]:
    root = samples_root.resolve(strict=True)
    if bool(topics) == select_all:
        raise PlanError("Select either explicit topics or --all.")
    candidates: dict[str, Path] = {}
    for persona in ("Employee", "Manager"):
        for path in sorted((root / persona).glob("*/topic.yaml")):
            if path.parent.name in candidates:
                raise PlanError(f"Ambiguous scenario folder: {path.parent.name}")
            candidates[path.parent.name] = path
    if not candidates:
        raise PlanError("No Employee/Manager scenario topic.yaml files found.")
    selected = sorted(candidates) if select_all else list(topics or [])
    if len(set(selected)) != len(selected):
        raise PlanError("Topic selection contains duplicates.")
    missing = sorted(set(selected) - candidates.keys())
    if missing:
        raise PlanError("Unknown scenario folders: " + ", ".join(missing))

    setup, setup_info = read_dialog(root / SETUP_FILENAME, root)
    setup_actions = action_nodes(setup)
    variables = [
        node["variable"] for node in setup_actions
        if node["kind"] == "SetVariable"
        and isinstance(node.get("variable"), str)
        and node["variable"].startswith("Topic.msdyn_")
    ]
    mappings = [
        node.get("value") for node in setup_actions
        if node.get("variable") == "Topic.OSSTemplateConfigurations"
    ]
    if len(mappings) != 1 or not isinstance(mappings[0], str):
        raise PlanError("Shared configuration mapping is missing or ambiguous.")
    pairs = re.findall(
        r'Key:\s*"([^"]+)"\s*,\s*Value:\s*Topic\.([A-Za-z0-9_]+)', mappings[0]
    )
    keys = [key for key, _ in pairs]
    if (
        not variables
        or len(set(variables)) != len(variables)
        or len(set(keys)) != len(keys)
        or len(pairs) != len(variables)
        or set(keys) != {name.removeprefix("Topic.") for name in variables}
        or any(key != variable for key, variable in pairs)
    ):
        raise PlanError("Shared template variables/keys are missing, duplicate or misaligned.")
    merge_actions = [
        node for node in setup_actions
        if node.get("variable") == "Global.ESS_WorkdayHCM_Template_Configurations"
    ]
    if len(merge_actions) != 1 or (
        "ShowColumns(Topic.OSSTemplateConfigurations, Key)"
        not in str(merge_actions[0].get("value"))
    ):
        raise PlanError("Expected ShowColumns-based shared configuration merge.")

    planned = []
    for name in selected:
        _, info = read_dialog(candidates[name], root)
        planned.append({"scenario": name, **info})
    blockers = [
        {"path": info["path"], "actionKinds": info["unapprovedActionKinds"]}
        for info in [setup_info, *planned] if info["unapprovedActionKinds"]
    ]
    return {
        "mode": "local-plan-only",
        "networkRequests": 0,
        "liveWrites": 0,
        "applyAllowed": False,
        "availableScenarioCount": len(candidates),
        "selectedScenarioCount": len(selected),
        "sharedTemplateCount": len(keys),
        "sharedTemplateKeys": sorted(keys),
        "sharedTemplateConfigSetup": setup_info,
        "topics": planned,
        "localCompatibilityBlockers": blockers,
        "remainingGates": [
            "selected target/authentication and dependency inventory",
            "target-version node/card/Power Fx support",
            "reviewed creation contract and create-capable client",
            "explicit mutation approval",
            "baseline/concurrency checks and post-write read-back",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-root", required=True, type=Path)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--topics", nargs="+")
    selection.add_argument("--all", action="store_true", dest="select_all")
    args = parser.parse_args()
    try:
        plan = build_plan(args.samples_root, args.topics, select_all=args.select_all)
    except (OSError, UnicodeError, yaml.YAMLError, PlanError) as error:
        print(f"OSS import plan failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
