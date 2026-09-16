# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Create a clean sibling Git worktree for another ESS agent workspace.

The current Developer Kit folder is never modified. The new worktree is
detached at the selected committed revision so it does not require or create a
long-lived source branch. Local setup state and agent content are gitignored
and therefore do not carry into the new worktree.

Usage:
    python scripts/create_fresh_workspace.py --destination <path>
    python scripts/create_fresh_workspace.py --destination <path> --open-vscode
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any


KIT_SUBFOLDER = Path("solutions") / "ess-maker-skills"
RESULT_MARKER = "DA_FRESH_WORKSPACE_JSON"


class FreshWorkspaceError(RuntimeError):
    """Raised when a fresh worktree cannot be created or opened safely."""


def _run_git(
    git_executable: str,
    repo_root: Path,
    arguments: Sequence[str],
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [git_executable, "-C", str(repo_root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise FreshWorkspaceError(
            f"Git could not {' '.join(arguments[:2])}: "
            f"{detail or 'no diagnostic was returned'}"
        )
    return completed


def _resolve_repo_root(source: Path, git_executable: str) -> Path:
    completed = _run_git(
        git_executable,
        source,
        ["rev-parse", "--show-toplevel"],
    )
    return Path(completed.stdout.strip()).resolve()


def create_worktree(
    source: Path,
    destination: Path,
    *,
    source_ref: str = "HEAD",
) -> dict[str, Any]:
    """Create one detached worktree from a clean committed source revision."""
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise FreshWorkspaceError(
            f"The destination already exists: {destination}. Choose a new folder."
        )

    git_executable = shutil.which("git")
    if git_executable is None:
        raise FreshWorkspaceError("Git is required to create a fresh workspace.")

    repo_root = _resolve_repo_root(source, git_executable)
    if destination.parent != repo_root.parent:
        raise FreshWorkspaceError(
            "The new worktree must be a sibling folder outside the current "
            "Developer Kit repository."
        )
    source_kit_root = repo_root / KIT_SUBFOLDER
    if not source_kit_root.is_dir():
        raise FreshWorkspaceError(
            f"The repository does not contain {KIT_SUBFOLDER}."
        )

    status = _run_git(
        git_executable,
        repo_root,
        ["status", "--porcelain", "--untracked-files=normal"],
    ).stdout.strip()
    if status:
        raise FreshWorkspaceError(
            "The Developer Kit repository has uncommitted files. Commit, stash, "
            "or remove them before creating a fresh workspace so the new folder "
            "cannot silently omit current source changes."
        )

    source_commit = _run_git(
        git_executable,
        repo_root,
        ["rev-parse", "--verify", f"{source_ref}^{{commit}}"],
    ).stdout.strip()
    local_prefix = f"{KIT_SUBFOLDER.as_posix()}/.local"
    workspace_prefix = f"{KIT_SUBFOLDER.as_posix()}/workspace"
    tracked_workspace_state = _run_git(
        git_executable,
        repo_root,
        [
            "ls-tree",
            "-r",
            "--name-only",
            source_commit,
            "--",
            local_prefix,
            workspace_prefix,
        ],
    ).stdout.splitlines()
    allowed_scaffolding = {f"{local_prefix}/.gitkeep"}
    unexpected_state = [
        path for path in tracked_workspace_state if path not in allowed_scaffolding
    ]
    if unexpected_state:
        raise FreshWorkspaceError(
            "The committed revision tracks local state that must not enter a "
            f"fresh workspace: {', '.join(unexpected_state)}"
        )
    _run_git(
        git_executable,
        repo_root,
        ["worktree", "add", "--detach", str(destination), source_commit],
    )

    kit_root = destination / KIT_SUBFOLDER
    if not kit_root.is_dir():
        raise FreshWorkspaceError(
            "Git created the worktree, but its ESS Maker Skills folder is "
            f"missing: {kit_root}"
        )

    return {
        "outcome": "workspace-created",
        "sourceCommit": source_commit,
        "worktreeRoot": str(destination),
        "kitRoot": str(kit_root.resolve()),
        "vscodeOpened": False,
    }


def open_vscode_workspace(
    kit_root: Path,
    *,
    code_executable: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    """Open the new ESS Maker Skills folder in a separate VS Code window."""
    kit_root = kit_root.expanduser().resolve()
    if not kit_root.is_dir():
        raise FreshWorkspaceError(
            f"The ESS Maker Skills folder does not exist: {kit_root}"
        )
    executable = code_executable or shutil.which("code")
    if executable is None:
        raise FreshWorkspaceError(
            "The VS Code command-line launcher `code` is not available."
        )
    completed = runner(
        [executable, "-n", str(kit_root)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise FreshWorkspaceError(
            "VS Code did not open the new workspace: "
            f"{detail or 'no diagnostic was returned'}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.cwd(),
        help="Path inside the current Developer Kit repository.",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="New sibling worktree path. The path must not already exist.",
    )
    parser.add_argument(
        "--source-ref",
        default="HEAD",
        help="Committed Git revision for the new detached worktree.",
    )
    parser.add_argument(
        "--open-vscode",
        action="store_true",
        help="Open the new solutions/ess-maker-skills folder in a VS Code window.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = create_worktree(
            args.source,
            args.destination,
            source_ref=args.source_ref,
        )
    except (FreshWorkspaceError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.open_vscode:
        try:
            open_vscode_workspace(Path(result["kitRoot"]))
            result["vscodeOpened"] = True
        except (FreshWorkspaceError, OSError) as exc:
            result["outcome"] = "workspace-created-open-failed"
            result["openError"] = str(exc)
            print(f"{RESULT_MARKER}:{json.dumps(result, ensure_ascii=True)}")
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    print(f"{RESULT_MARKER}:{json.dumps(result, ensure_ascii=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
