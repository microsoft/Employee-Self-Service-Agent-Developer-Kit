# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""CLI entry for samples/ static validation.

Usage:
  python -m tools.validate_samples --diff-base origin/main
  python -m tools.validate_samples --paths-file changed.txt --repo-root .
  python -m tools.validate_samples --diff-base origin/main --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

from .checks import (
    RETIRED_WORKDAY_AREAS,
    WORKDAY_LEGACY,
    WORKDAY_PREVIEW,
    ChangedFile,
    Result,
    Status,
    run_all_checks,
)

_HERE = Path(__file__).resolve().parent
_DEFAULT_WHITELIST = _HERE / "whitelist.yml"


def _load_whitelist(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _git_changed(repo_root: Path, base: str) -> list[ChangedFile]:
    """Return changed files between `base` and HEAD using name-status."""
    out = subprocess.check_output(
        ["git", "-C", str(repo_root), "diff", "--name-status", f"{base}...HEAD"],
        text=True,
    )
    changed: list[ChangedFile] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        # Renames/copies look like "R100\told\tnew" or "C100\told\tnew" — treat the new path as added.
        if status.startswith(("R", "C")) and len(parts) >= 3:
            changed.append(ChangedFile(path=parts[2].replace("\\", "/"), change_type="A"))
        elif len(parts) >= 2:
            changed.append(ChangedFile(path=parts[1].replace("\\", "/"), change_type=status[:1]))
    return changed


def _parse_paths_file(path: Path) -> list[ChangedFile]:
    """Each line: '<STATUS>\\t<path>' or just '<path>' (treated as 'M')."""
    changed: list[ChangedFile] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            status, p = line.split("\t", 1)
        else:
            status, p = "M", line
        changed.append(ChangedFile(path=p.replace("\\", "/"), change_type=status[:1] or "M"))
    return changed


def _preserved_workday_migration(repo_root: Path, base: str) -> frozenset[str]:
    """Recognize a complete move with identical Git-normalized file contents."""
    merge_base = subprocess.check_output(
        ["git", "-C", str(repo_root), "merge-base", base, "HEAD"], text=True,
    ).strip()
    entries = subprocess.check_output(
        ["git", "-C", str(repo_root), "ls-tree", "-r",
         merge_base, "--", WORKDAY_LEGACY],
        text=True,
    ).splitlines()
    original = {
        path: metadata.split()[2]
        for entry in entries
        for metadata, path in [entry.split("\t", 1)]
    }
    if not original or not any(path.endswith("/topic.yaml") for path in original):
        return frozenset()
    legacy_root = repo_root / WORKDAY_LEGACY
    if legacy_root.exists() and any(path.is_file() for path in legacy_root.rglob("*")):
        return frozenset()
    expected = {
        path.replace(WORKDAY_LEGACY + "/", WORKDAY_PREVIEW + "/", 1)
        for path in original
    }
    preview_root = repo_root / WORKDAY_PREVIEW
    actual = {
        path.relative_to(repo_root).as_posix()
        for path in preview_root.rglob("*") if path.is_file()
    }
    if actual != expected:
        return frozenset()
    for old_path in original:
        new_path = old_path.replace(WORKDAY_LEGACY + "/", WORKDAY_PREVIEW + "/", 1)
        current_blob = subprocess.check_output(
            ["git", "-C", str(repo_root), "hash-object", "--path", new_path, new_path],
            text=True,
        ).strip()
        if current_blob != original[old_path]:
            return frozenset()
    return frozenset(expected)


def _retired_workday_areas(repo_root: Path, base: str) -> frozenset[str]:
    """Recognize complete removals of known obsolete sample areas, not edits."""
    merge_base = subprocess.check_output(
        ["git", "-C", str(repo_root), "merge-base", base, "HEAD"], text=True,
    ).strip()
    retired = set()
    for area in RETIRED_WORKDAY_AREAS:
        original = subprocess.check_output(
            ["git", "-C", str(repo_root), "ls-tree", "-r", "--name-only",
             merge_base, "--", area],
            text=True,
        ).splitlines()
        root = repo_root / area
        if original and not any(path.is_file() for path in root.rglob("*")):
            retired.add(area)
    return frozenset(retired)


def render_summary(results: list[Result]) -> str:
    lines = ["Validation"]
    label_map = {
        "YAML parse": "YAML parse",
        "AdaptiveDialog kind": "AdaptiveDialog kind",
        "XML parse": "XML parse",
        "Filename convention (new)": "Filename convention (new)",
        "Folder convention (new, incl. README.md)": "Folder convention (new, incl. README.md)",
        "Diff scope (samples/ only)": "Diff scope (samples/ only)",
        "Secrets / internal URLs": "Secrets / internal URLs",
    }
    for r in results:
        lines.append(f"- {label_map.get(r.name, r.name)}: {r.status.value}")
        for d in r.details:
            lines.append(f"    - {d}")
    return "\n".join(lines)


def results_to_json(results: list[Result]) -> str:
    return json.dumps(
        [{"name": r.name, "status": r.status.value, "details": r.details} for r in results],
        indent=2,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="validate_samples")
    p.add_argument("--repo-root", default=".", help="Repo root (default: cwd).")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--diff-base", help="Git ref to diff HEAD against (e.g. origin/main).")
    src.add_argument("--paths-file", help="File of changed paths (status\\tpath per line).")
    p.add_argument("--whitelist", default=str(_DEFAULT_WHITELIST))
    p.add_argument("--json", action="store_true", help="Emit JSON instead of summary block.")
    args = p.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    whitelist = _load_whitelist(Path(args.whitelist))

    if args.diff_base:
        changed = _git_changed(repo_root, args.diff_base)
        preserved_workday_paths = _preserved_workday_migration(repo_root, args.diff_base)
        retired_workday_areas = _retired_workday_areas(repo_root, args.diff_base)
    else:
        changed = _parse_paths_file(Path(args.paths_file))
        preserved_workday_paths = frozenset()
        retired_workday_areas = frozenset()

    results = run_all_checks(
        repo_root, changed, whitelist,
        preserved_workday_paths=preserved_workday_paths,
        retired_workday_areas=retired_workday_areas,
    )

    if args.json:
        print(results_to_json(results))
    else:
        print(render_summary(results))

    return 1 if any(r.status is Status.FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
