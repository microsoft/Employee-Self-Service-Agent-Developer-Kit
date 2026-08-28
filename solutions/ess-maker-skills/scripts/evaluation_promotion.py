# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Safely promote workspace evaluation sets and remove staging copies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any

from evaluation_csv import evaluation_export_stem, generate_set_csv


class EvaluationPromotionError(RuntimeError):
    """Raised when evaluation promotion or cleanup is unsafe."""


def _has_parent_set(folder: Path) -> bool:
    return any(
        "kind: EvaluationSet" in path.read_text(encoding="utf-8")
        for path in folder.glob("*.mcs.yml")
    )


def _promotion_payload(folder: Path) -> dict[str, bytes]:
    paths = list(folder.glob("*.mcs.yml"))
    review = folder / "review.json"
    if review.is_file():
        paths.append(review)
    return {
        path.name: path.read_bytes()
        for path in paths
        if path.is_file()
    }


def _is_resumable_staging(source: Path, destination: Path) -> bool:
    return (
        destination.is_dir()
        and _has_parent_set(destination)
        and _promotion_payload(source) == _promotion_payload(destination)
    )


def _paths(
    workspace_evaluations: str | Path,
    agent_folder: str | Path,
    set_name: str,
) -> tuple[Path, Path, Path]:
    workspace_root = Path(workspace_evaluations).resolve()
    agent = Path(agent_folder).resolve()
    source = (workspace_root / set_name).resolve()
    destination = (agent / "evaluations" / set_name).resolve()
    baseline = (agent / ".baseline" / "evaluations" / set_name).resolve()
    if source.parent != workspace_root:
        raise EvaluationPromotionError("Invalid workspace evaluation set name.")
    if destination.parent != (agent / "evaluations").resolve():
        raise EvaluationPromotionError("Invalid agent evaluation set name.")
    if source == destination:
        raise EvaluationPromotionError(
            "Workspace source and agent destination must be different."
        )
    return source, destination, baseline


def promote_workspace_set(
    workspace_evaluations: str | Path,
    agent_folder: str | Path,
    set_name: str,
    replace: bool = False,
) -> dict[str, Any]:
    """Copy one workspace set into the agent without deleting its source."""
    source, destination, baseline = _paths(
        workspace_evaluations,
        agent_folder,
        set_name,
    )
    if not source.is_dir() or not _has_parent_set(source):
        raise EvaluationPromotionError(
            f"Workspace evaluation set not found or invalid: {source}"
        )
    if not baseline.exists() and _is_resumable_staging(source, destination):
        csv_path = generate_set_csv(
            destination,
            destination.parent / "exports",
        )
        return {
            "source": str(source),
            "destination": str(destination),
            "csv": str(csv_path),
            "replaced": False,
            "resumed": True,
        }
    if (destination.exists() or baseline.exists()) and not replace:
        raise EvaluationPromotionError(
            "The evaluation set already exists in the configured agent or "
            "deployed baseline. Confirm replacement before using --replace."
        )
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
    csv_path = generate_set_csv(
        destination,
        destination.parent / "exports",
    )
    return {
        "source": str(source),
        "destination": str(destination),
        "csv": str(csv_path),
        "replaced": replace,
        "resumed": False,
    }


def cleanup_workspace_set(
    workspace_evaluations: str | Path,
    agent_folder: str | Path,
    set_name: str,
) -> dict[str, Any]:
    """Delete only workspace staging after verifying the agent copy."""
    source, destination, _ = _paths(
        workspace_evaluations,
        agent_folder,
        set_name,
    )
    if not destination.is_dir() or not _has_parent_set(destination):
        raise EvaluationPromotionError(
            "Refusing workspace cleanup because the promoted agent copy is "
            f"missing or invalid: {destination}"
        )
    if source.is_dir() and _promotion_payload(source) != _promotion_payload(
        destination
    ):
        raise EvaluationPromotionError(
            "Refusing workspace cleanup because the staging set changed after "
            "promotion or no longer matches the configured-agent copy."
        )

    removed_csvs: list[str] = []
    exports = source.parent / "exports"
    if exports.is_dir():
        safe_name = evaluation_export_stem(destination)
        csv_patterns = (
            f"{set_name}-eval-testset-*.csv",
            f"????????_{safe_name}.csv",
        )
        for csv_path in {
            path for pattern in csv_patterns for path in exports.glob(pattern)
        }:
            if csv_path.is_file():
                csv_path.unlink()
                removed_csvs.append(str(csv_path))
    source_removed = False
    if source.is_dir():
        shutil.rmtree(source)
        source_removed = True
    return {
        "source": str(source),
        "destination": str(destination),
        "sourceRemoved": source_removed,
        "removedCsvs": removed_csvs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Promote and clean up workspace evaluation test sets."
    )
    parser.add_argument(
        "command",
        choices=("promote", "cleanup"),
    )
    parser.add_argument("--set-name", required=True)
    parser.add_argument("--agent-folder", required=True)
    parser.add_argument(
        "--workspace-evaluations",
        default="workspace/evaluations",
    )
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    try:
        if args.command == "promote":
            result = promote_workspace_set(
                args.workspace_evaluations,
                args.agent_folder,
                args.set_name,
                args.replace,
            )
        else:
            if args.replace:
                parser.error("--replace is valid only with promote")
            result = cleanup_workspace_set(
                args.workspace_evaluations,
                args.agent_folder,
                args.set_name,
            )
    except EvaluationPromotionError as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
