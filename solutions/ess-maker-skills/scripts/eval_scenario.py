# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validate eval-driven topic scenarios and materialize their eval artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - dependency error path
    print(
        "ERROR: PyYAML is required. Run: pip install -r scripts/requirements.txt",
        file=sys.stderr,
    )
    raise SystemExit(1)


SCHEMA_VERSION = 2
RUNTIME_MANIFEST_VERSION = 1
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PHASE = 1
PERSONAS = {"employee", "manager", "admin", "support"}
TOPIC_TYPES = {"informational", "clarification", "routing", "handoff"}
MATERIALIZE_OPERATIONS = {"create", "update"}
BLOCK_STAGES = {"generation", "push"}
EVAL_CATEGORIES = {
    "directTrigger",
    "paraphrase",
    "nonTrigger",
    "clarification",
    "missingInput",
    "correctedInput",
    "confirmation",
    "cancellation",
    "disambiguation",
    "notFound",
    "emptyOptionalField",
    "identityBoundary",
    "authorizationFailure",
    "actionBoundary",
    "downstreamError",
    "successWithData",
    "successNoData",
    "regression",
    "configuredValue",
}
EVAL_CATEGORY_KEYWORDS = (
    ("nontrigger", "nonTrigger"),
    ("nottrigger", "nonTrigger"),
    ("paraphrase", "paraphrase"),
    ("clarification", "clarification"),
    ("ambiguous", "clarification"),
    ("missinginput", "missingInput"),
    ("correctedinput", "correctedInput"),
    ("confirmation", "confirmation"),
    ("cancellation", "cancellation"),
    ("cancel", "cancellation"),
    ("disambiguation", "disambiguation"),
    ("multiplematch", "disambiguation"),
    ("notfound", "notFound"),
    ("emptyoptional", "emptyOptionalField"),
    ("identity", "identityBoundary"),
    ("authorization", "authorizationFailure"),
    ("actionboundary", "actionBoundary"),
    ("downstreamerror", "downstreamError"),
    ("nodata", "successNoData"),
    ("successwithdata", "successWithData"),
    ("regression", "regression"),
    ("configuredvalue", "configuredValue"),
)


class ScenarioValidationError(ValueError):
    """Raised when an eval-driven topic scenario is invalid."""

    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _reject_unknown_keys(
    value: dict[str, Any],
    allowed: set[str],
    location: str,
    errors: list[str],
) -> None:
    for key in sorted(set(value) - allowed):
        errors.append(f"{location}: unknown field '{key}'")


def load_scenario(path: Path) -> dict[str, Any]:
    """Load a YAML scenario document from disk."""
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ScenarioValidationError([f"scenario file not found: {path}"]) from exc
    except yaml.YAMLError as exc:
        raise ScenarioValidationError([f"invalid YAML: {exc}"]) from exc

    if not isinstance(loaded, dict):
        raise ScenarioValidationError(["scenario root must be a YAML object"])
    return loaded


def validate_scenario(scenario: dict[str, Any]) -> None:
    """Validate the scenario contract and raise actionable errors."""
    errors: list[str] = []
    root_fields = {
        "schemaVersion",
        "id",
        "name",
        "intent",
        "topicType",
        "phase",
        "persona",
        "references",
        "sourceContent",
        "dependencyChecks",
        "evals",
    }
    _reject_unknown_keys(scenario, root_fields, "scenario", errors)

    required = {
        "schemaVersion",
        "id",
        "name",
        "intent",
        "topicType",
        "phase",
        "persona",
        "evals",
    }
    for field in sorted(required - set(scenario)):
        errors.append(f"scenario: missing required field '{field}'")

    if scenario.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion must be {SCHEMA_VERSION}")

    scenario_id = scenario.get("id")
    if not _non_empty_string(scenario_id) or not ID_PATTERN.fullmatch(scenario_id):
        errors.append("id must be lowercase kebab-case")

    for field in ("name", "intent"):
        if not _non_empty_string(scenario.get(field)):
            errors.append(f"{field} must be a non-empty string")

    topic_type = scenario.get("topicType")
    if topic_type not in TOPIC_TYPES:
        errors.append(f"topicType must be one of: {', '.join(sorted(TOPIC_TYPES))}")
    if topic_type == "informational" and not _non_empty_string(
        scenario.get("sourceContent")
    ):
        errors.append("sourceContent is required for informational topics")

    if scenario.get("phase") != PHASE:
        errors.append("phase must be 1 for eval-driven simple topics")

    persona = scenario.get("persona")
    if persona not in PERSONAS:
        errors.append(f"persona must be one of: {', '.join(sorted(PERSONAS))}")

    references = scenario.get("references")
    if references is not None:
        if _non_empty_string(references):
            pass
        elif isinstance(references, list) and references and all(
            _non_empty_string(reference) for reference in references
        ):
            pass
        else:
            errors.append(
                "references must be a non-empty string or a non-empty list of strings"
            )

    dependency_checks = scenario.get("dependencyChecks", [])
    if not isinstance(dependency_checks, list):
        errors.append("dependencyChecks must be a list")
    else:
        for index, check in enumerate(dependency_checks, start=1):
            _validate_dependency_check(check, index, errors)

    evals = scenario.get("evals")
    if not isinstance(evals, list) or not evals:
        errors.append("evals must contain at least one evaluation")
    else:
        for index, evaluation in enumerate(evals, start=1):
            _validate_evaluation(evaluation, index, errors)

    if errors:
        raise ScenarioValidationError(errors)


def _validate_dependency_check(
    check: Any,
    index: int,
    errors: list[str],
) -> None:
    location = f"dependencyChecks[{index}]"
    if not isinstance(check, dict):
        errors.append(f"{location} must be an object")
        return
    _reject_unknown_keys(check, {"condition", "blocks", "behavior"}, location, errors)
    if not _non_empty_string(check.get("condition")):
        errors.append(f"{location}.condition must be a non-empty string")
    if not _non_empty_string(check.get("behavior")):
        errors.append(f"{location}.behavior must be a non-empty string")
    if check.get("blocks", "generation") not in BLOCK_STAGES:
        errors.append(f"{location}.blocks must be 'generation' or 'push'")


def _validate_evaluation(
    evaluation: Any,
    index: int,
    errors: list[str],
) -> None:
    location = f"evals[{index}]"
    if not isinstance(evaluation, dict):
        errors.append(f"{location} must be an object")
        return

    fields = {
        "category",
        "input",
        "turns",
        "condition",
        "expectedOutput",
        "required",
        "threshold",
    }
    _reject_unknown_keys(evaluation, fields, location, errors)

    if evaluation.get("category") not in EVAL_CATEGORIES:
        errors.append(
            f"{location}.category must be one of: "
            + ", ".join(sorted(EVAL_CATEGORIES))
        )

    triggers = [
        name
        for name in ("input", "turns", "condition")
        if name in evaluation
    ]
    if len(triggers) != 1:
        errors.append(f"{location} must define exactly one of input, turns, condition")
        return

    trigger = triggers[0]
    if trigger in {"input", "condition"}:
        if not _non_empty_string(evaluation.get(trigger)):
            errors.append(f"{location}.{trigger} must be a non-empty string")
        if not _non_empty_string(evaluation.get("expectedOutput")):
            errors.append(
                f"{location}.expectedOutput is required for {trigger} evaluations"
            )
    else:
        turns = evaluation.get("turns")
        if not isinstance(turns, list) or not turns:
            errors.append(f"{location}.turns must contain at least one turn")
        elif len(turns) > 6:
            errors.append(f"{location}.turns cannot contain more than 6 turns")
        else:
            for turn_index, turn in enumerate(turns, start=1):
                turn_location = f"{location}.turns[{turn_index}]"
                if not isinstance(turn, dict):
                    errors.append(f"{turn_location} must be an object")
                    continue
                _reject_unknown_keys(
                    turn,
                    {"input", "expectedOutput"},
                    turn_location,
                    errors,
                )
                if not _non_empty_string(turn.get("input")):
                    errors.append(f"{turn_location}.input must be a non-empty string")
                elif len(turn["input"]) > 500:
                    errors.append(f"{turn_location}.input cannot exceed 500 characters")
                if "expectedOutput" in turn and not _non_empty_string(
                    turn["expectedOutput"]
                ):
                    errors.append(
                        f"{turn_location}.expectedOutput must be a non-empty string"
                    )

    if "required" in evaluation and not isinstance(evaluation["required"], bool):
        errors.append(f"{location}.required must be true or false")
    threshold = evaluation.get("threshold", 0.7)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        errors.append(f"{location}.threshold must be a number from 0 to 1")
    elif not 0 <= threshold <= 1:
        errors.append(f"{location}.threshold must be between 0 and 1")


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "eval"


def _normalize_category_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _infer_eval_category(path: Path, expected_output: str = "") -> str:
    candidate = _normalize_category_text(f"{path.stem} {expected_output}")
    for keyword, category in EVAL_CATEGORY_KEYWORDS:
        if keyword in candidate:
            return category
    return "directTrigger"


def _activity_role(activity: dict[str, Any]) -> str | None:
    activity_value = activity.get("activity", {})
    if not isinstance(activity_value, dict):
        return None
    value = activity_value.get("value", {})
    if isinstance(value, dict):
        source = value.get("from", {})
        if isinstance(source, dict) and _non_empty_string(source.get("role")):
            return source["role"].lower()
    source = activity_value.get("from", {})
    if isinstance(source, dict) and _non_empty_string(source.get("role")):
        return source["role"].lower()
    return None


def _activity_text(activity: dict[str, Any]) -> str | None:
    text = activity.get("text")
    if isinstance(text, str):
        return text.strip() or None
    if isinstance(text, list):
        values = [value.strip() for value in text if _non_empty_string(value)]
        return "\n".join(values) or None
    return None


def _resolve_eval_files(inputs: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for input_path in inputs:
        if not input_path.exists():
            raise ValueError(f"eval input not found: {input_path}")
        if input_path.is_dir():
            for pattern in ("*.mcs.yml", "*.yml", "*.yaml"):
                files.update(path.resolve() for path in input_path.rglob(pattern))
        elif input_path.suffix.lower() in {".yml", ".yaml"}:
            files.add(input_path.resolve())
        else:
            raise ValueError(f"eval input must be a YAML file or directory: {input_path}")
    if not files:
        raise ValueError("no evaluation YAML files found")
    return sorted(files, key=lambda path: path.as_posix().lower())


def _load_eval_document(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"unable to read evaluation file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid evaluation YAML in {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"evaluation file must contain a YAML object: {path}")
    return loaded


def _evaluation_set_threshold(document: dict[str, Any]) -> float:
    graders = document.get("graders", [])
    if not isinstance(graders, list):
        return 0.7
    for grader in graders:
        if (
            isinstance(grader, dict)
            and grader.get("kind") == "CompareMeaningGrader"
            and isinstance(grader.get("threshold"), (int, float))
            and not isinstance(grader.get("threshold"), bool)
        ):
            threshold = float(grader["threshold"])
            if 0 <= threshold <= 1:
                return threshold
    return 0.7


def _normalize_single_turn(
    path: Path,
    document: dict[str, Any],
    threshold: float,
) -> list[dict[str, Any]]:
    rows = document.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"EvaluationData has no rows: {path}")
    evaluations: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"EvaluationData row {index} must be an object: {path}")
        input_text = row.get("input")
        expected_output = row.get("expectedOutput")
        if not _non_empty_string(input_text) or not _non_empty_string(expected_output):
            raise ValueError(
                f"EvaluationData row {index} requires input and expectedOutput: {path}"
            )
        evaluations.append(
            {
                "category": _infer_eval_category(path, expected_output),
                "input": input_text.strip(),
                "expectedOutput": expected_output.strip(),
                "threshold": threshold,
            }
        )
    return evaluations


def _normalize_multi_turn(
    path: Path,
    document: dict[str, Any],
) -> dict[str, Any]:
    activities = document.get("activities")
    if not isinstance(activities, list) or not activities:
        raise ValueError(f"MultiTurnEvaluationCase has no activities: {path}")

    turns: list[dict[str, str]] = []
    current_turn: dict[str, str] | None = None
    for activity in activities:
        if not isinstance(activity, dict):
            raise ValueError(f"multi-turn activity must be an object: {path}")
        role = _activity_role(activity)
        text = _activity_text(activity)
        if role == "user":
            if not text:
                raise ValueError(f"multi-turn user activity has no text: {path}")
            if current_turn is not None:
                turns.append(current_turn)
            current_turn = {"input": text}
        elif role in {"agent", "assistant", "bot"} and text:
            if current_turn is None:
                raise ValueError(
                    f"multi-turn agent activity appears before a user activity: {path}"
                )
            if "expectedOutput" in current_turn:
                current_turn["expectedOutput"] += f"\n{text}"
            else:
                current_turn["expectedOutput"] = text

    if current_turn is not None:
        turns.append(current_turn)
    if not turns:
        raise ValueError(f"MultiTurnEvaluationCase has no user turns: {path}")
    if len(turns) > 6:
        raise ValueError(f"MultiTurnEvaluationCase cannot exceed 6 user turns: {path}")

    expected_text = " ".join(
        turn.get("expectedOutput", "") for turn in turns
    )
    return {
        "category": _infer_eval_category(path, expected_text),
        "turns": turns,
        "threshold": 0.7,
    }


def normalize_native_evals(
    inputs: list[Path],
    scenario_id: str,
    name: str,
    intent: str,
    topic_type: str,
    persona: str,
    source_content: str | None = None,
) -> dict[str, Any]:
    """Convert native Copilot Studio eval files into a scenario contract."""
    files = _resolve_eval_files(inputs)
    documents = [(path, _load_eval_document(path)) for path in files]
    thresholds = {
        path.parent: _evaluation_set_threshold(document)
        for path, document in documents
        if document.get("kind") == "EvaluationSet"
    }

    evaluations: list[dict[str, Any]] = []
    references = [path.as_posix() for path, _ in documents]
    for path, document in documents:
        kind = document.get("kind")
        if kind == "EvaluationSet":
            continue
        if kind == "EvaluationData":
            evaluations.extend(
                _normalize_single_turn(
                    path,
                    document,
                    thresholds.get(path.parent, 0.7),
                )
            )
        elif kind == "MultiTurnEvaluationCase":
            evaluations.append(_normalize_multi_turn(path, document))
        else:
            raise ValueError(f"unsupported evaluation kind '{kind}' in {path}")

    if not evaluations:
        raise ValueError("no EvaluationData or MultiTurnEvaluationCase files found")

    scenario: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "id": scenario_id,
        "name": name,
        "intent": intent,
        "topicType": topic_type,
        "phase": PHASE,
        "persona": persona,
        "references": references,
        "evals": evaluations,
    }
    if source_content is not None:
        scenario["sourceContent"] = source_content
    validate_scenario(scenario)
    return scenario


def _write_yaml(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def _single_turn_parent(display_name: str, threshold: float) -> dict[str, Any]:
    return {
        "kind": "EvaluationSet",
        "displayName": display_name,
        "graders": [
            {"kind": "GeneralQualityGrader"},
            {"kind": "CompareMeaningGrader", "threshold": threshold},
        ],
    }


def _multi_turn_parent(display_name: str) -> dict[str, Any]:
    return {
        "kind": "EvaluationSet",
        "displayName": display_name,
        "graders": [{"kind": "GeneralQualityGrader"}],
    }


def _single_turn_child(evaluation: dict[str, Any], display_order: int) -> dict[str, Any]:
    return {
        "kind": "EvaluationData",
        "rows": [
            {
                "source": "Imported",
                "expectedOutput": evaluation["expectedOutput"],
                "input": evaluation["input"],
            }
        ],
        "extensionData": {"displayOrder": str(display_order)},
    }


def _multi_turn_child(evaluation: dict[str, Any], display_order: int) -> dict[str, Any]:
    activities: list[dict[str, Any]] = []
    for turn in evaluation["turns"]:
        activities.append(
            {
                "activity": {"value": {"from": {"role": "user"}}},
                "text": [turn["input"]],
            }
        )
        if _non_empty_string(turn.get("expectedOutput")):
            activities.append(
                {
                    "activity": {"value": {"from": {"role": "agent"}}},
                    "text": [turn["expectedOutput"]],
                }
            )
    return {
        "kind": "MultiTurnEvaluationCase",
        "source": "Imported",
        "activities": activities,
        "extensionData": {"displayOrder": str(display_order)},
    }


def _clear_generated_eval_folders(evaluations_root: Path, base_folder: str) -> None:
    """Remove stale files only from folders owned by this scenario."""
    if not evaluations_root.exists():
        return
    owned_pattern = re.compile(
        rf"^{re.escape(base_folder)}(?:-t\d+|-multi-turn)?$"
    )
    for folder in evaluations_root.iterdir():
        if not folder.is_dir():
            continue
        if not owned_pattern.fullmatch(folder.name):
            continue
        for child in folder.iterdir():
            if child.is_file() and child.name.endswith(".mcs.yml"):
                child.unlink()
        if not any(folder.iterdir()):
            folder.rmdir()


def materialize_scenario(
    scenario: dict[str, Any],
    agent_folder: Path,
    topic_file: Path,
    runtime_output: Path,
    operation: str = "create",
) -> dict[str, Any]:
    """Write native eval files and the runtime handoff manifest."""
    validate_scenario(scenario)
    if operation not in MATERIALIZE_OPERATIONS:
        raise ValueError(
            "operation must be one of: "
            + ", ".join(sorted(MATERIALIZE_OPERATIONS))
        )

    agent_root = agent_folder.resolve()
    topic_path = topic_file.resolve()
    try:
        topic_relative = topic_path.relative_to(agent_root)
    except ValueError as exc:
        raise ValueError("topic file must be inside the agent folder") from exc
    if not topic_path.is_file():
        raise ValueError(f"topic file not found: {topic_file}")

    scenario_id = scenario["id"]
    single_turn_groups: dict[float, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    multi_turn: list[tuple[int, dict[str, Any]]] = []
    manifest_evals: list[dict[str, Any]] = []

    for index, evaluation in enumerate(scenario["evals"], start=1):
        eval_id = f"{scenario_id}-{index:03d}-{_slug(evaluation['category'])}"
        manifest_eval = {
            "id": eval_id,
            "category": evaluation["category"],
            "required": evaluation.get("required", True),
            "threshold": evaluation.get("threshold", 0.7),
            "nativeEvalPath": None,
        }
        for field in ("input", "turns", "condition", "expectedOutput"):
            if field in evaluation:
                manifest_eval[field] = evaluation[field]
        manifest_evals.append(manifest_eval)

        if "input" in evaluation:
            single_turn_groups[float(evaluation.get("threshold", 0.7))].append(
                (index, evaluation)
            )
        elif "turns" in evaluation:
            multi_turn.append((index, evaluation))

    evaluations_root = agent_root / "evaluations"
    base_folder = f"eval-driven-{scenario_id}"
    _clear_generated_eval_folders(evaluations_root, base_folder)
    multiple_thresholds = len(single_turn_groups) > 1
    written_files: list[str] = []

    for threshold, evaluations in sorted(single_turn_groups.items()):
        suffix = f"-t{round(threshold * 100):02d}" if multiple_thresholds else ""
        folder_name = f"{base_folder}{suffix}"
        folder = evaluations_root / folder_name
        parent_path = folder / f"{folder_name}.mcs.yml"
        display_name = f"Eval Driven - {scenario['name']}"
        if multiple_thresholds:
            display_name = f"{display_name} - {threshold:g}"
        _write_yaml(
            parent_path,
            _single_turn_parent(display_name, threshold),
        )
        written_files.append(parent_path.relative_to(agent_root).as_posix())

        for index, evaluation in evaluations:
            filename = f"{index:03d}-{_slug(evaluation['category'])}.mcs.yml"
            child_path = folder / filename
            _write_yaml(child_path, _single_turn_child(evaluation, index))
            child_relative = child_path.relative_to(agent_root).as_posix()
            manifest_evals[index - 1]["nativeEvalPath"] = child_relative
            written_files.append(child_relative)

    if multi_turn:
        folder_name = f"{base_folder}-multi-turn"
        folder = evaluations_root / folder_name
        parent_path = folder / f"{folder_name}.mcs.yml"
        _write_yaml(
            parent_path,
            _multi_turn_parent(f"Eval Driven - {scenario['name']} - Multi-Turn"),
        )
        written_files.append(parent_path.relative_to(agent_root).as_posix())

        for index, evaluation in multi_turn:
            filename = f"{index:03d}-{_slug(evaluation['category'])}.mcs.yml"
            child_path = folder / filename
            _write_yaml(child_path, _multi_turn_child(evaluation, index))
            child_relative = child_path.relative_to(agent_root).as_posix()
            manifest_evals[index - 1]["nativeEvalPath"] = child_relative
            written_files.append(child_relative)

    manifest_scenario = {
        "schemaVersion": scenario["schemaVersion"],
        "id": scenario_id,
        "name": scenario["name"],
        "intent": scenario["intent"],
        "topicType": scenario["topicType"],
        "phase": scenario["phase"],
        "operation": operation,
    }

    manifest = {
        "schemaVersion": RUNTIME_MANIFEST_VERSION,
        "scenario": manifest_scenario,
        "topic": {"path": topic_relative.as_posix()},
        "evals": manifest_evals,
        "nativeEvalFiles": written_files,
    }
    runtime_output.parent.mkdir(parents=True, exist_ok=True)
    runtime_output.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and materialize eval-driven topic scenarios."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("scenario", type=Path)

    normalize_parser = subparsers.add_parser("normalize")
    normalize_parser.add_argument("inputs", nargs="+", type=Path)
    normalize_parser.add_argument("--id", dest="scenario_id", required=True)
    normalize_parser.add_argument("--name", required=True)
    normalize_parser.add_argument("--intent", required=True)
    normalize_parser.add_argument(
        "--topic-type",
        choices=sorted(TOPIC_TYPES),
        required=True,
    )
    normalize_parser.add_argument(
        "--persona",
        choices=sorted(PERSONAS),
        required=True,
    )
    normalize_parser.add_argument("--source-content")
    normalize_parser.add_argument("--output", type=Path, required=True)

    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("scenario", type=Path)
    materialize_parser.add_argument("--agent-folder", type=Path, required=True)
    materialize_parser.add_argument("--topic-file", type=Path, required=True)
    materialize_parser.add_argument("--runtime-output", type=Path, required=True)
    materialize_parser.add_argument(
        "--operation",
        choices=sorted(MATERIALIZE_OPERATIONS),
        default="create",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "normalize":
            scenario = normalize_native_evals(
                args.inputs,
                args.scenario_id,
                args.name,
                args.intent,
                args.topic_type,
                args.persona,
                args.source_content,
            )
            _write_yaml(args.output, scenario)
            print(
                f"NORMALIZED: {len(scenario['evals'])} evaluation(s) "
                f"to {args.output}"
            )
            return 0

        scenario = load_scenario(args.scenario)
        validate_scenario(scenario)
        if args.command == "validate":
            print(
                f"VALID: {scenario['id']} "
                f"({len(scenario['evals'])} evaluation(s))"
            )
            return 0

        manifest = materialize_scenario(
            scenario,
            args.agent_folder,
            args.topic_file,
            args.runtime_output,
            args.operation,
        )
        print(
            f"MATERIALIZED: {len(manifest['nativeEvalFiles'])} native eval file(s)"
        )
        print(f"RUNTIME MANIFEST: {args.runtime_output}")
        return 0
    except (ScenarioValidationError, ValueError) as exc:
        if isinstance(exc, ScenarioValidationError):
            for error in exc.errors:
                print(f"ERROR: {error}", file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
