# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Evaluation review metadata shared by setup, pull, and push flows.

The working review.json is the desired local state. The matching baseline
review.json is the latest pulled or successfully pushed Copilot Studio state.
Human-authored description text is preserved in baseDescription.
"""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import re
from pathlib import Path
from typing import Any


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


def strip_review_marker(description: str | None) -> str:
    """Remove ADK review markers while preserving human-authored text."""
    if not description:
        return ""
    return _MARKER_RE.sub("", description).strip()


def compose_review_description(
    base_description: str | None,
    status: str,
) -> str:
    """Append the canonical ADK review marker to a human description."""
    if status not in VALID_STATUSES:
        raise ReviewMetadataError(f"Unsupported review status: {status}")
    base = strip_review_marker(base_description)
    marker = f"[ADK-REVIEW status={status}]"
    return f"{base}\n\n{marker}" if base else marker


def metadata_from_description(description: str | None) -> dict[str, str] | None:
    """Build local review.json content from a tagged description."""
    marker = parse_review_marker(description)
    if marker is None:
        return None
    return {
        "status": marker["status"],
        "baseDescription": strip_review_marker(description),
    }


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
    return {
        "status": status,
        "baseDescription": strip_review_marker(base_description),
    }


def metadata_description(content: str) -> str:
    """Convert validated review.json content to a Dataverse description."""
    metadata = parse_review_metadata(content)
    return compose_review_description(
        metadata["baseDescription"],
        metadata["status"],
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
    normalized = parse_review_metadata(json.dumps(metadata))
    review_path.write_text(
        json.dumps(normalized, indent=2) + "\n",
        encoding="utf-8",
    )
    return review_path


def _evaluation_case_count(folder: Path) -> int:
    """Count EvaluationData files in an evaluation set folder."""
    count = 0
    for candidate in folder.glob("*.mcs.yml"):
        try:
            if "kind: EvaluationData" in candidate.read_text(encoding="utf-8"):
                count += 1
        except OSError as exc:
            raise ReviewMetadataError(
                f"Unable to read evaluation file {candidate}: {exc}"
            ) from exc
    return count


def _configured_agent_folders(
    config_path: Path,
    solution_root: Path,
) -> list[tuple[str, Path]]:
    """Return configured agent labels and resolved workspace folders."""
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
    agents = config.get("agents")
    if isinstance(agents, list):
        configured.extend(item for item in agents if isinstance(item, dict))

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
    parser.add_argument("--base-description")
    parser.add_argument("--workspace-root", default="workspace")
    parser.add_argument("--config", default=".local/config.json")
    parser.add_argument("--query")
    args = parser.parse_args()

    try:
        if args.list_sets or args.list_all:
            if args.set_folder or args.base_description:
                parser.error(
                    "--set-folder and --base-description cannot be used "
                    "with list operations."
                )
            if args.list_all:
                if args.status:
                    parser.error("--status cannot be used with --list-all.")
                sets = discover_evaluation_sets(
                    args.workspace_root,
                    args.config,
                )
            else:
                sets = discover_review_sets(
                    args.workspace_root,
                    args.config,
                    args.status or REVIEW_REQUESTED,
                )
            print(json.dumps(match_evaluation_sets(sets, args.query), indent=2))
        else:
            if args.query:
                parser.error("--query can only be used with list operations.")
            if not args.set_folder or not args.status:
                parser.error("--set-folder and --status are required.")
            path = set_review_metadata(
                args.set_folder,
                args.status,
                args.base_description,
            )
            print(path)
    except ReviewMetadataError as exc:
        parser.error(str(exc))
