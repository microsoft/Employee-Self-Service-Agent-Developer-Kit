# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Archive the current local ESS agent setup so this workspace can be reused."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RESULT_MARKER = "DA_RESET_WORKSPACE_JSON"
BACKUP_ROOT = Path(".local") / "workspace-reset-backups"
RESET_TARGETS = (
    Path(".local") / "setup",
    Path(".local") / "config.json",
    Path("workspace") / "flightcheck",
)


class LocalWorkspaceResetError(RuntimeError):
    """Raised when local setup cannot be archived safely."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _next_backup_path(root: Path, timestamp: str) -> Path:
    candidate = root / timestamp
    suffix = 2
    while candidate.exists():
        candidate = root / f"{timestamp}-{suffix}"
        suffix += 1
    return candidate


def _workspace_targets(kit_root: Path) -> list[Path]:
    targets = [path for path in RESET_TARGETS if (kit_root / path).exists()]
    agents_root = kit_root / "workspace" / "agents"
    if agents_root.is_dir():
        targets.extend(
            path.relative_to(kit_root)
            for path in sorted(agents_root.iterdir(), key=lambda item: item.name)
            if path.name != ".gitkeep"
        )
    return targets


def reset_local_workspace(
    kit_root: Path,
    *,
    timestamp_factory: Callable[[], str] = _timestamp,
) -> dict[str, Any]:
    """Archive setup-owned state and generated agent workspaces."""
    kit_root = kit_root.expanduser().resolve()
    targets = _workspace_targets(kit_root)
    if not targets:
        return {
            "outcome": "nothing-to-reset",
            "kitRoot": str(kit_root),
            "backupRoot": None,
            "archivedPaths": [],
        }

    backup_parent = (kit_root / BACKUP_ROOT).resolve()
    if not backup_parent.is_relative_to(kit_root):
        raise LocalWorkspaceResetError(
            f"Backup root is outside the Developer Kit folder: {backup_parent}"
        )
    backup_root = _next_backup_path(backup_parent, timestamp_factory())
    planned = [(path, backup_root / path) for path in targets]
    for source_path, destination_path in planned:
        source = kit_root / source_path
        if not source.resolve().is_relative_to(kit_root):
            raise LocalWorkspaceResetError(
                f"Reset target is outside the Developer Kit folder: {source}"
            )
        if destination_path.exists():
            raise LocalWorkspaceResetError(
                f"Backup destination already exists: {destination_path}"
            )

    moved: list[tuple[Path, Path]] = []
    try:
        for source_path, destination_path in planned:
            source = kit_root / source_path
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination_path))
            moved.append((source, destination_path))
    except OSError as exc:
        rollback_failures: list[str] = []
        for source, destination in reversed(moved):
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
            except OSError as rollback_error:
                rollback_failures.append(
                    f"{destination}: {type(rollback_error).__name__}: "
                    f"{rollback_error}"
                )
        error = LocalWorkspaceResetError(
            f"Local workspace reset failed: {type(exc).__name__}: {exc}"
        )
        for rollback_failure in rollback_failures:
            error.add_note(f"Rollback failed for {rollback_failure}")
        raise error from exc

    return {
        "outcome": "workspace-reset",
        "kitRoot": str(kit_root),
        "backupRoot": str(backup_root),
        "archivedPaths": [path.as_posix() for path in targets],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=Path.cwd(),
        help="ESS Maker Skills folder to reset.",
    )
    parser.add_argument(
        "--confirm-reset",
        action="store_true",
        help="Confirm that local setup and generated workspace files may be archived.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.confirm_reset:
        print(
            "ERROR: Local workspace reset requires --confirm-reset.",
            file=sys.stderr,
        )
        return 2
    try:
        result = reset_local_workspace(args.kit_root)
    except (LocalWorkspaceResetError, OSError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", ()):
            print(f"NOTE: {note}", file=sys.stderr)
        return 1
    print(f"{RESULT_MARKER}:{json.dumps(result, ensure_ascii=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
