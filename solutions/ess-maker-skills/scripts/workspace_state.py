# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Local workspace comparison and persistence, without remote operations."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import tempfile
from typing import Mapping


EXCLUDE_DIRS = {".baseline", ".checkpoints"}
EXCLUDE_FILES = {
    "snapshot.md", "_meta.json", ".component-map.json",
    ".evaluation-pending.json", ".evaluation-preview.json",
    ".evaluation-deployment.lock",
}


def _ensure_utf8_stdout(stream=None):
    """Keep observable Unicode output usable on legacy Windows consoles."""
    if stream is None:
        stream = sys.stdout
    encoding = getattr(stream, "encoding", None)
    if encoding and encoding.lower() != "utf-8" and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")
        return True
    return False


def collect_files(root_dir):
    """Return UTF-8 working content keyed by normalized relative path."""
    def fail(error):
        raise error

    files = {}
    for directory, directories, filenames in os.walk(root_dir, onerror=fail):
        directories[:] = [name for name in directories if name not in EXCLUDE_DIRS]
        for name in filenames:
            if name in EXCLUDE_FILES:
                continue
            path = Path(directory) / name
            relative = path.relative_to(root_dir).as_posix()
            files[relative] = path.read_text(encoding="utf-8")
    return files


def compute_diff(baseline_files, working_files):
    """Return sorted modified, new, and deleted relative paths."""
    changed, new, deleted = [], [], []
    for path in sorted(baseline_files.keys() | working_files.keys()):
        if path not in baseline_files:
            new.append(path)
        elif path not in working_files:
            deleted.append(path)
        elif baseline_files[path] != working_files[path]:
            changed.append(path)
    return changed, new, deleted


def matches_only(filepath, only_globs):
    """Match normalized relative paths against an optional explicit scope."""
    return not only_globs or any(
        fnmatch.fnmatch(filepath.replace("\\", "/"), pattern.replace("\\", "/"))
        for pattern in only_globs
    )


def inspect_pending_changes(agent_dir, only_globs=None):
    """Compare local files only; a baseline is bookkeeping, not remote state."""
    root = Path(agent_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Agent folder not found: {root}")
    baseline = root / ".baseline"
    if not baseline.is_dir():
        raise FileNotFoundError(f"Workspace baseline not found: {baseline}")
    changed, new, deleted = compute_diff(collect_files(baseline), collect_files(root))
    return {
        key: [path for path in paths if matches_only(path, only_globs)]
        for key, paths in (("modified", changed), ("new", new), ("deleted", deleted))
    }


def _atomic_write_text(path, text):
    """Replace one UTF-8 file without exposing a partially written destination."""
    destination = Path(path)
    descriptor, temporary = tempfile.mkstemp(
        prefix=destination.name + ".", suffix=".tmp", dir=destination.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException as exc:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError as cleanup:
            exc.add_note(f"Temporary file cleanup also failed: {cleanup}")
        raise


def load_component_map(agent_dir):
    path = Path(agent_dir) / ".component-map.json"
    return read_json(path)


def read_json(path: Path):
    """Read an expected JSON object without configuration or auth fallback."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def save_component_map(agent_dir, component_map):
    _atomic_write_text(
        Path(agent_dir) / ".component-map.json",
        json.dumps(component_map, indent=2) + "\n",
    )


def acknowledge_files(agent_dir, submitted: Mapping[str, str]):
    """Acknowledge captured, verified content, never a later working-file edit."""
    root = Path(agent_dir).resolve() / ".baseline"
    destinations = []
    for relative, content in submitted.items():
        path = PurePosixPath(relative.replace("\\", "/"))
        destination = root.joinpath(*path.parts).resolve()
        if (
            path.is_absolute() or PureWindowsPath(relative).drive
            or ".." in path.parts or not path.parts or any(":" in part for part in path.parts)
            or not destination.is_relative_to(root) or not isinstance(content, str)
        ):
            raise ValueError(f"Invalid acknowledged workspace path: {relative}")
        destinations.append((destination, content))
    for destination, content in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(destination, content)


def classify_path(filepath):
    """Determine the component type from a file's relative path.

    Returns one of: 'botcomponent', 'template-config', 'workflow',
    'workflow-meta', or None.
    """
    parts = filepath.replace("\\", "/").split("/")
    if parts[0] == "template-configs":
        # Only content files (.json/.xml) with a matching .meta.json
        if filepath.endswith(".meta.json"):
            return None  # skip meta files as standalone push targets
        return "template-config"
    if parts[0] == "workflows":
        if parts[-1] == "workflow.json":
            return "workflow"
        if parts[-1] == "metadata.yml":
            return "workflow-meta"
        return None
    if parts[0] == "evaluations" and parts[-1] == "review.json":
        return "evaluation-review"
    if filepath.endswith(".mcs.yml"):
        return "botcomponent"
    return None
