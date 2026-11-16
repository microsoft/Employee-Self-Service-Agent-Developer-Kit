# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Evaluation review metadata shared by setup, pull, and push flows.

The working review.json is the desired local state. The matching baseline
review.json is the latest pulled or successfully pushed Copilot Studio state.
Human-authored description text is preserved in baseDescription.
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from difflib import SequenceMatcher
import json
import re
from pathlib import Path
import sys
from typing import Any

import yaml


REVIEW_REQUESTED = "review_requested"
REVIEW_COMPLETED = "review_completed"
VALID_STATUSES = {REVIEW_REQUESTED, REVIEW_COMPLETED}
REVIEW_FILENAME = "review.json"
UNTAGGED = "untagged"
NOT_DEPLOYED = "not_deployed"

_MARKER_RE = re.compile(
    r"(?:\r?\n){0,2}\[ADK-REVIEW "
    r"status=(review_requested|review_completed)\]"
)
_FEEDBACK_START = "[ADK-REVIEW-FEEDBACK]"
_FEEDBACK_END = "[/ADK-REVIEW-FEEDBACK]"
_FEEDBACK_RE = re.compile(
    r"(?:\r?\n){0,2}\[ADK-REVIEW-FEEDBACK\]\r?\n(.*?)\r?\n\[/ADK-REVIEW-FEEDBACK\]",
    re.DOTALL,
)
# Copilot Studio does not document a test-set description limit for every
# backend, so feedback is capped well below Dataverse's limit.
FEEDBACK_MAX_CHARS = 4000


class ReviewMetadataError(ValueError):
    """Raised when local review metadata is malformed."""


def parse_review_marker(description: str | None) -> dict[str, str] | None:
    """Parse the ADK review marker from a Dataverse description."""
    if not description:
        return None
    match = _MARKER_RE.search(description)
    if not match:
        return None
    return {"status": match.group(1)}


def parse_review_feedback(description: str | None) -> str | None:
    """Return reviewer feedback stored in a description, if any."""
    if not description:
        return None
    match = _FEEDBACK_RE.search(description)
    if not match:
        return None
    return match.group(1).replace("\r\n", "\n").strip() or None


def strip_review_marker(description: str | None) -> str:
    """Remove ADK review markers while preserving human-authored text."""
    if not description:
        return ""
    return _MARKER_RE.sub("", _FEEDBACK_RE.sub("", description)).strip()


def _validate_feedback(feedback: Any) -> str | None:
    if feedback is None:
        return None
    if not isinstance(feedback, str):
        raise ReviewMetadataError("feedback must be a string.")
    feedback = feedback.replace("\r\n", "\n").strip()
    if not feedback:
        return None
    if "[ADK-REVIEW" in feedback or _FEEDBACK_END in feedback:
        raise ReviewMetadataError("Feedback cannot contain ADK review markers.")
    if len(feedback) > FEEDBACK_MAX_CHARS:
        raise ReviewMetadataError(
            f"Feedback is {len(feedback)} characters; the limit is "
            f"{FEEDBACK_MAX_CHARS}. Shorten it before saving."
        )
    return feedback


def compose_review_description(
    base_description: str | None,
    status: str,
    feedback: str | None = None,
) -> str:
    """Append reviewer feedback and the canonical ADK review marker."""
    if status not in VALID_STATUSES:
        raise ReviewMetadataError(f"Unsupported review status: {status}")
    parts = [strip_review_marker(base_description)]
    feedback = _validate_feedback(feedback)
    if feedback:
        parts.append(f"{_FEEDBACK_START}\n{feedback}\n{_FEEDBACK_END}")
    parts.append(f"[ADK-REVIEW status={status}]")
    return "\n\n".join(part for part in parts if part)


def metadata_from_description(description: str | None) -> dict[str, str] | None:
    """Build local review.json content from a tagged description."""
    marker = parse_review_marker(description)
    if marker is None:
        return None
    metadata = {
        "status": marker["status"],
        "baseDescription": strip_review_marker(description),
    }
    feedback = parse_review_feedback(description)
    if feedback:
        metadata["feedback"] = feedback
    return metadata


def parse_review_metadata(content: str) -> dict[str, str]:
    """Validate and normalize review.json content."""
    try:
        raw: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ReviewMetadataError(f"Invalid review metadata JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ReviewMetadataError("Review metadata must be a JSON object.")

    status = raw.get("status")
    if status not in VALID_STATUSES:
        raise ReviewMetadataError(
            "Review status must be review_requested or review_completed."
        )
    base_description = raw.get("baseDescription", "")
    if not isinstance(base_description, str):
        raise ReviewMetadataError("baseDescription must be a string.")
    metadata = {
        "status": status,
        "baseDescription": strip_review_marker(base_description),
    }
    feedback = _validate_feedback(raw.get("feedback"))
    if feedback:
        metadata["feedback"] = feedback
    return metadata


def metadata_description(content: str) -> str:
    """Convert validated review.json content to a Dataverse description."""
    metadata = parse_review_metadata(content)
    return compose_review_description(
        metadata["baseDescription"],
        metadata["status"],
        metadata.get("feedback"),
    )


def requested_marker() -> str:
    """Return the canonical pending-review marker."""
    return compose_review_description("", REVIEW_REQUESTED)


def _description_from_component_map(folder: Path) -> str:
    """Find the parent set's Dataverse description in its agent component map."""
    parent_yaml = None
    for candidate in folder.glob("*.mcs.yml"):
        if "kind: EvaluationSet" in candidate.read_text(encoding="utf-8"):
            parent_yaml = candidate
            break
    if parent_yaml is None:
        return ""

    for root in (folder, *folder.parents):
        map_path = root / ".component-map.json"
        if not map_path.is_file():
            continue
        try:
            component_map = json.loads(map_path.read_text(encoding="utf-8"))
            relative = parent_yaml.relative_to(root).as_posix()
            entry = component_map.get(relative, {})
            description = entry.get("description", "")
            return description if isinstance(description, str) else ""
        except (OSError, ValueError, json.JSONDecodeError):
            return ""
    return ""


def set_review_metadata(
    set_folder: str | Path,
    status: str,
    base_description: str | None = None,
) -> Path:
    """Create or update review.json while preserving its base description."""
    folder = Path(set_folder)
    if not folder.is_dir():
        raise ReviewMetadataError(f"Evaluation set folder not found: {folder}")

    review_path = folder / REVIEW_FILENAME
    existing: dict[str, str] = {}
    if review_path.exists():
        existing = parse_review_metadata(
            review_path.read_text(encoding="utf-8"))
        preserved_description = existing["baseDescription"]
    else:
        if base_description is None:
            base_description = _description_from_component_map(folder)
        preserved_description = strip_review_marker(base_description)

    metadata = {
        "status": status,
        "baseDescription": preserved_description,
    }
    if existing.get("feedback"):
        metadata["feedback"] = existing["feedback"]
    normalized = parse_review_metadata(json.dumps(metadata))
    review_path.write_text(
        json.dumps(normalized, indent=2) + "\n",
        encoding="utf-8",
    )
    return review_path


def add_review_feedback(set_folder: str | Path, feedback: str) -> Path:
    """Append reviewer feedback to review.json without changing its status."""
    folder = Path(set_folder)
    review_path = folder / REVIEW_FILENAME
    if not review_path.is_file():
        raise ReviewMetadataError(
            "Feedback can only be added to a test set that was marked for review."
        )
    entry = _validate_feedback(feedback)
    if not entry:
        raise ReviewMetadataError("Feedback is empty.")
    existing = parse_review_metadata(review_path.read_text(encoding="utf-8"))
    previous = existing.get("feedback")
    combined = f"{previous}\n\n{entry}" if previous else entry
    metadata = {**existing, "feedback": combined}
    normalized = parse_review_metadata(json.dumps(metadata))
    review_path.write_text(
        json.dumps(normalized, indent=2) + "\n",
        encoding="utf-8",
    )
    return review_path


def _evaluation_case_count(folder: Path) -> int:
    """Count single-turn and multi-turn case files in a set folder."""
    count = 0
    for candidate in folder.glob("*.mcs.yml"):
        try:
            content = candidate.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReviewMetadataError(
                f"Unable to read evaluation file {candidate}: {exc}"
            ) from exc
        if (
            "kind: EvaluationData" in content
            or "kind: MultiTurnEvaluationCase" in content
        ):
            count += 1
    return count


def _configured_agent_folders(
    config_path: Path,
    solution_root: Path,
) -> list[tuple[str, Path]]:
    """Return the active configured agent's label and workspace folder.

    Only the active agent (``config["agent"]``) is returned, mirroring the
    single agent that ``push.py`` operates on. Discovering sets across every
    entry in ``config["agents"]`` would surface sets that the review-completion
    push cannot reach, producing "Nothing to push in the selected scope" when a
    different agent is active. Keeping discovery and push scoped to the same
    agent keeps the review handoff actionable.
    """
    if not config_path.is_file():
        return []
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewMetadataError(
            f"Unable to read configured agents from {config_path}: {exc}"
        ) from exc

    configured: list[dict[str, Any]] = []
    agent = config.get("agent")
    if isinstance(agent, dict):
        configured.append(agent)

    folders: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for item in configured:
        folder_value = item.get("folder")
        if not isinstance(folder_value, str) or not folder_value.strip():
            continue
        folder = Path(folder_value)
        if not folder.is_absolute():
            folder = solution_root / folder
        folder = folder.resolve()
        if folder in seen:
            continue
        seen.add(folder)
        label = item.get("name") or item.get("slug") or folder.name
        folders.append((str(label), folder))
    return folders


def _evaluation_locations(
    workspace: Path,
    config: Path,
) -> list[tuple[str, Path]]:
    """Return workspace and configured-agent evaluation locations."""
    solution_root = config.parent.parent
    locations: list[tuple[str, Path]] = [
        ("Workspace", workspace / "evaluations"),
    ]
    locations.extend(
        (f"Configured agent: {label}", folder / "evaluations")
        for label, folder in _configured_agent_folders(config, solution_root)
    )
    return locations


def _is_evaluation_set_folder(folder: Path) -> bool:
    """Return whether a folder contains an EvaluationSet parent file."""
    for candidate in folder.glob("*.mcs.yml"):
        try:
            if "kind: EvaluationSet" in candidate.read_text(encoding="utf-8"):
                return True
        except OSError as exc:
            raise ReviewMetadataError(
                f"Unable to read evaluation file {candidate}: {exc}"
            ) from exc
    return False


def _local_review_status(folder: Path) -> str:
    """Return a set's local review status or untagged."""
    review_path = folder / REVIEW_FILENAME
    if not review_path.is_file():
        return UNTAGGED
    try:
        return parse_review_metadata(
            review_path.read_text(encoding="utf-8")
        )["status"]
    except OSError as exc:
        raise ReviewMetadataError(
            f"Unable to read review metadata {review_path}: {exc}"
        ) from exc


def _review_feedback(folder: Path) -> str | None:
    """Return the reviewer feedback saved in a set folder, if any."""
    review_path = folder / REVIEW_FILENAME
    if not review_path.is_file():
        return None
    try:
        return parse_review_metadata(
            review_path.read_text(encoding="utf-8")
        ).get("feedback")
    except OSError as exc:
        raise ReviewMetadataError(
            f"Unable to read review metadata {review_path}: {exc}"
        ) from exc


def _deployed_review_feedback(
    source: str,
    evaluations_folder: Path,
    set_folder: Path,
) -> str | None:
    """Return the latest pulled/pushed reviewer feedback for one set."""
    if source == "Workspace":
        return None
    return _review_feedback(
        evaluations_folder.parent / ".baseline" / "evaluations" / set_folder.name
    )


def _deployed_review_status(
    source: str,
    evaluations_folder: Path,
    set_folder: Path,
) -> str:
    """Return the latest pulled/pushed review status for one set."""
    if source == "Workspace":
        return NOT_DEPLOYED
    baseline_set = (
        evaluations_folder.parent
        / ".baseline"
        / "evaluations"
        / set_folder.name
    )
    if not baseline_set.is_dir() or not _is_evaluation_set_folder(baseline_set):
        return NOT_DEPLOYED
    return _local_review_status(baseline_set)


def _review_transition(
    local_status: str,
    deployed_status: str,
) -> tuple[str, str]:
    """Return synchronization state and the next valid review action."""
    sync_state = (
        "in_sync" if local_status == deployed_status else "pending_push"
    )
    if local_status == REVIEW_REQUESTED:
        if deployed_status == REVIEW_REQUESTED:
            return sync_state, "review"
        return sync_state, "push_review_request"
    if local_status == REVIEW_COMPLETED:
        if deployed_status == REVIEW_COMPLETED:
            return sync_state, "run_or_view_results"
        if deployed_status == REVIEW_REQUESTED:
            return sync_state, "push_review_completion"
        return sync_state, "push_review_completion"
    if deployed_status == REVIEW_REQUESTED:
        return sync_state, "pull_latest_review_state"
    return sync_state, "none"


def discover_evaluation_sets(
    workspace_root: str | Path = "workspace",
    config_path: str | Path = ".local/config.json",
) -> list[dict[str, Any]]:
    """Discover all workspace and configured-agent evaluation sets."""
    workspace = Path(workspace_root).resolve()
    config = Path(config_path).resolve()
    results: list[dict[str, Any]] = []
    seen: set[Path] = set()

    for source, evaluations_folder in _evaluation_locations(workspace, config):
        if not evaluations_folder.is_dir():
            continue
        for set_folder in evaluations_folder.iterdir():
            if (
                not set_folder.is_dir()
                or set_folder.name.casefold() == "exports"
                or not _is_evaluation_set_folder(set_folder)
            ):
                continue
            resolved = set_folder.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            local_status = _local_review_status(set_folder)
            deployed_status = _deployed_review_status(
                source,
                evaluations_folder,
                set_folder,
            )
            sync_state, next_action = _review_transition(
                local_status,
                deployed_status,
            )
            feedback = _review_feedback(set_folder)
            deployed_feedback = _deployed_review_feedback(
                source,
                evaluations_folder,
                set_folder,
            )
            if feedback != deployed_feedback:
                sync_state = "pending_push"
            results.append({
                "name": set_folder.name,
                "source": source,
                "folder": str(resolved),
                "testCaseCount": _evaluation_case_count(set_folder),
                "status": local_status,
                "localStatus": local_status,
                "deployedStatus": deployed_status,
                "syncState": sync_state,
                "nextAction": next_action,
                "feedback": feedback,
                "feedbackPushed": bool(feedback) and feedback == deployed_feedback,
            })

    return sorted(
        results,
        key=lambda item: (item["source"].casefold(), item["name"].casefold()),
    )


def match_evaluation_sets(
    evaluation_sets: list[dict[str, Any]],
    query: str | None,
) -> list[dict[str, Any]]:
    """Rank local evaluation sets by exact, substring, and fuzzy name match."""
    if not query:
        return evaluation_sets
    target = re.sub(r"[^a-z0-9]+", " ", query.casefold()).strip()
    ranked = []
    for item in evaluation_sets:
        name = str(item.get("name", ""))
        normalized = re.sub(
            r"[^a-z0-9]+",
            " ",
            name.casefold(),
        ).strip()
        if normalized == target:
            score = 1.0
        elif target and (target in normalized or normalized in target):
            score = 0.9
        else:
            score = SequenceMatcher(None, target, normalized).ratio()
        if score >= 0.45:
            ranked.append((score, name.casefold(), item))
    ranked.sort(key=lambda value: (-value[0], value[1]))
    return [
        {**item, "matchScore": round(score, 3)}
        for score, _, item in ranked
    ]


def discover_review_sets(
    workspace_root: str | Path = "workspace",
    config_path: str | Path = ".local/config.json",
    status: str = REVIEW_REQUESTED,
) -> list[dict[str, Any]]:
    """Discover review-tagged sets synchronized with Copilot Studio."""
    if status not in VALID_STATUSES:
        raise ReviewMetadataError(f"Unsupported review status: {status}")

    workspace = Path(workspace_root).resolve()
    config = Path(config_path).resolve()
    return [
        item
        for item in discover_evaluation_sets(workspace, config)
        if (
            item["localStatus"] == status
            and item["deployedStatus"] == status
        )
    ]


def refresh_native_review_sets(config_path: str | Path = ".local/config.json") -> None:
    """Pull shared native evaluation review state without overwriting local edits."""
    from evaluation_method_policy import validate_evaluation_documents
    from minimalbot_evaluation import (
        MinimalBotEvaluationClient, MinimalBotEvaluationError, is_minimalbot,
    )
    from push import _atomic_write_text, run_checkpoint

    config_path = Path(config_path).resolve()
    if not config_path.is_file():
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not is_minimalbot(config):
        return
    agent_config = config.get("agent")
    if not isinstance(agent_config, dict) or not agent_config.get("folder"):
        raise ReviewMetadataError("Configured native agent folder is missing.")
    agent = Path(agent_config["folder"])
    if not agent.is_absolute():
        agent = config_path.parent.parent / agent
    agent = agent.resolve()
    if not agent.is_dir():
        raise ReviewMetadataError("Configured agent folder is missing; refresh was not performed.")
    if (agent / ".evaluation-pending.json").is_file():
        raise ReviewMetadataError("Reconcile the pending native deployment before refreshing review state.")
    map_path = agent / ".component-map.json"
    component_map = json.loads(map_path.read_text(encoding="utf-8")) if map_path.is_file() else {}
    if not isinstance(component_map, dict):
        raise ReviewMetadataError("Invalid native component tracking.")
    try:
        client = MinimalBotEvaluationClient.from_config(config)
        with redirect_stdout(sys.stderr):
            client.authenticate()
            components = client._remote_components(client.read_components())
    except MinimalBotEvaluationError as exc:
        raise ReviewMetadataError(str(exc)) from exc
    target = {
        "environmentId": client.environment_id, "botId": client.bot_id, "ring": client.ring,
    }

    def local_files(folder):
        return {
            path.name: path.read_text(encoding="utf-8")
            for path in folder.glob("*")
            if path.is_file() and (path.name.endswith(".mcs.yml") or path.name == REVIEW_FILENAME)
        }

    def yaml_document(value):
        if isinstance(value, dict):
            return {("kind" if key == "$kind" else key): yaml_document(item)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [yaml_document(item) for item in value]
        return value

    planned = []
    for parent_id, parent in components.items():
        if parent.get("$kind") != "TestCaseComponent" or (
            parent.get("definition") or {}
        ).get("$kind") != "EvaluationSet":
            continue
        mapped = [
            path for path, entry in component_map.items()
            if isinstance(entry, dict) and entry.get("botcomponentid") == parent_id
            and path.startswith("evaluations/") and not entry.get("parentbotcomponentid")
        ]
        if len(mapped) > 1:
            raise ReviewMetadataError("Native evaluation parent tracking is ambiguous.")
        if mapped:
            relative = Path(mapped[0])
            if len(relative.parts) != 3 or relative.suffix != ".yml":
                raise ReviewMetadataError("Invalid native evaluation parent path.")
            folder = (agent / relative).resolve().parent
            if folder.parent != (agent / "evaluations").resolve():
                raise ReviewMetadataError("Native evaluation path leaves the configured agent.")
            parent_name = relative.name
        else:
            slug = re.sub(r"[^a-zA-Z0-9-]", "-", parent_id)
            if not slug:
                raise ReviewMetadataError("Native evaluation parent identity is missing.")
            folder = agent / "evaluations" / f"native-{slug}"
            parent_name = "set.mcs.yml"
        baseline = agent / ".baseline" / "evaluations" / folder.name
        metadata = metadata_from_description(parent.get("description"))
        if metadata is None and not (baseline / REVIEW_FILENAME).is_file():
            continue
        working, previous = local_files(folder), local_files(baseline)
        if previous and not folder.exists():
            # The maker deleted this set locally; deletion is local-only, so
            # leave it deleted instead of restoring it or blocking review.
            continue
        if working != previous:
            raise ReviewMetadataError(
                f"Local changes in {folder} would be overwritten. "
                "Push or preserve them before refreshing shared review state."
            )
        children = [
            component for component in components.values()
            if component.get("parentBotComponentId") == parent_id
        ]
        validate_evaluation_documents(
            parent["definition"], [child.get("definition") for child in children],
            context=f"Native review set {parent_id}",
        )
        files, entries = {}, {}
        for component in [parent, *children]:
            component_id = component["id"]
            names = [
                Path(path).name for path, entry in component_map.items()
                if isinstance(entry, dict) and entry.get("botcomponentid") == component_id
                and (agent / path).resolve().parent == folder
            ]
            name = parent_name if component_id == parent_id else (
                names[0] if len(names) == 1
                else "case-" + re.sub(r"[^a-zA-Z0-9-]", "-", component_id) + ".mcs.yml"
            )
            if name in files:
                raise ReviewMetadataError("Native review component filenames collide.")
            files[name] = yaml.safe_dump(
                yaml_document(component["definition"]), sort_keys=False, allow_unicode=True,
            )
            entries[f"evaluations/{folder.name}/{name}"] = {
                "botcomponentid": component_id,
                "parentbotcomponentid": component.get("parentBotComponentId"),
                "componenttype": 19, "schemaname": component.get("schemaName"),
                "name": component["definition"].get("displayName") or Path(name).stem,
                "description": component.get("description") or "",
                "nativeDefinition": component["definition"], "nativeTarget": target,
            }
        if metadata:
            files[REVIEW_FILENAME] = json.dumps(metadata, indent=2) + "\n"
        planned.append((folder, baseline, working, files, entries))

    if not planned:
        return
    with redirect_stdout(sys.stderr):
        run_checkpoint("pre-refresh-native-evaluation-review")
    for folder, baseline, working, files, entries in planned:
        for location in (folder, baseline):
            location.mkdir(parents=True, exist_ok=True)
            for name in working.keys() - files.keys():
                (location / name).unlink(missing_ok=True)
            for name, content in files.items():
                _atomic_write_text(str(location / name), content)
        prefix = f"evaluations/{folder.name}/"
        component_map = {
            path: entry for path, entry in component_map.items() if not path.startswith(prefix)
        }
        component_map.update(entries)
    _atomic_write_text(str(map_path), json.dumps(component_map, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create or update evaluation review metadata.")
    list_group = parser.add_mutually_exclusive_group()
    list_group.add_argument(
        "--list",
        action="store_true",
        dest="list_sets",
        help="List review-tagged sets synchronized with Copilot Studio.",
    )
    list_group.add_argument(
        "--list-all",
        action="store_true",
        help="List all workspace and configured-agent evaluation sets.",
    )
    parser.add_argument("--set-folder")
    parser.add_argument("--status", choices=sorted(VALID_STATUSES))
    parser.add_argument(
        "--add-feedback",
        help="Append reviewer feedback to the set's review.json.",
    )
    parser.add_argument("--base-description")
    parser.add_argument("--workspace-root", default="workspace")
    parser.add_argument("--config", default=".local/config.json")
    parser.add_argument("--query")
    args = parser.parse_args()

    try:
        if args.list_sets or args.list_all:
            if args.set_folder or args.base_description or args.add_feedback is not None:
                parser.error(
                    "--set-folder, --base-description, and --add-feedback "
                    "cannot be used with list operations."
                )
            if args.list_all:
                if args.status:
                    parser.error("--status cannot be used with --list-all.")
                sets = discover_evaluation_sets(
                    args.workspace_root,
                    args.config,
                )
            else:
                refresh_native_review_sets(args.config)
                sets = discover_review_sets(
                    args.workspace_root,
                    args.config,
                    args.status or REVIEW_REQUESTED,
                )
            print(json.dumps(match_evaluation_sets(sets, args.query), indent=2))
        else:
            if args.query:
                parser.error("--query can only be used with list operations.")
            if args.add_feedback is not None:
                if not args.set_folder:
                    parser.error("--add-feedback requires --set-folder.")
                path = add_review_feedback(args.set_folder, args.add_feedback)
                if args.status:
                    path = set_review_metadata(args.set_folder, args.status)
                print(path)
                sys.exit(0)
            if not args.set_folder or not args.status:
                parser.error("--set-folder and --status are required.")
            path = set_review_metadata(
                args.set_folder,
                args.status,
                args.base_description,
            )
            print(path)
    except (ReviewMetadataError, OSError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))
