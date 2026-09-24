# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Checkpoint Script

Creates, restores, and manages snapshots of the agent's working files.
All operations are relative to the agent folder in .local/config.json.

Usage:
    python scripts/checkpoint.py "reason for checkpoint"
    python scripts/checkpoint.py --revert
    python scripts/checkpoint.py --revert-reason "reason for checkpoint" [--only "glob"]
    python scripts/checkpoint.py --baseline
    python scripts/checkpoint.py --list
"""

import json
import os
import shutil
import sys
import time
from glob import glob
from datetime import datetime, timezone

EXCLUDE_DIRS = {".baseline", ".checkpoints"}


def load_config():
    config_path = os.path.join(".local", "config.json")
    if not os.path.exists(config_path):
        print("ERROR: .local/config.json not found. Run /setup first.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_agent_dir(config):
    return config["agent"]["folder"]


def get_checkpoints_dir(agent_dir):
    return os.path.join(agent_dir, ".checkpoints")


def get_baseline_dir(agent_dir):
    return os.path.join(agent_dir, ".baseline")


def next_checkpoint_number(checkpoints_dir):
    if not os.path.exists(checkpoints_dir):
        return 1
    existing = [int(d) for d in os.listdir(checkpoints_dir)
                if d.isdigit() and os.path.isdir(
                    os.path.join(checkpoints_dir, d))]
    return max(existing, default=0) + 1


def copy_working_files(agent_dir, dest_dir):
    """Copy all working files (excluding .baseline/ and .checkpoints/)."""
    _reject_reparse_points(agent_dir)
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)

    def _ignore(directory, contents):
        # Only apply exclusion at the top level of agent_dir
        if os.path.normpath(directory) == os.path.normpath(agent_dir):
            return {c for c in contents if c in EXCLUDE_DIRS}
        return set()

    shutil.copytree(agent_dir, dest_dir, ignore=_ignore)


def _is_reparse_point(path):
    """Return whether path redirects filesystem access outside its parent."""
    if os.path.islink(path):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    return bool(isjunction and isjunction(path))


def _reject_reparse_points(root):
    """Reject symlinks/junctions so checkpoint copies never dereference them."""
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            path = os.path.join(directory, name)
            if _is_reparse_point(path):
                relative = os.path.relpath(path, root)
                raise ValueError(
                    f"Checkpoint path is a reparse point: {relative}"
                )


def _is_protected_relative_path(relative_path):
    normalized = os.path.normpath(relative_path)
    if normalized in ("", "."):
        return True
    first_part = normalized.split(os.sep, 1)[0]
    return first_part in EXCLUDE_DIRS


def _require_physical_containment(root, path, *, label):
    """Require path and its existing parents to resolve beneath root."""
    resolved_root = os.path.realpath(root)
    resolved_path = os.path.realpath(path)
    try:
        contained = os.path.commonpath(
            [resolved_root, resolved_path]
        ) == resolved_root
    except ValueError:
        contained = False
    if not contained:
        raise ValueError(f"{label} resolves outside its root: {path}")

    current = os.path.abspath(path)
    root_abs = os.path.abspath(root)
    while current != root_abs:
        if os.path.lexists(current) and _is_reparse_point(current):
            raise ValueError(f"{label} traverses a reparse point: {path}")
        parent = os.path.dirname(current)
        if parent == current:
            raise ValueError(f"{label} escapes its root: {path}")
        current = parent


def restore_from(agent_dir, source_dir):
    """Replace working files with contents of source_dir.

    Removes all working files/folders (except .baseline/ and .checkpoints/),
    then copies everything from source_dir. Retries on Windows lock errors.
    """
    # Remove current working files
    for item in os.listdir(agent_dir):
        if item in EXCLUDE_DIRS:
            continue
        path = os.path.join(agent_dir, item)
        for attempt in range(5):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                break
            except PermissionError:
                if attempt < 4:
                    time.sleep(1)
                else:
                    print(f"Warning: could not remove {item} (file locked). "
                          f"Overwriting in place.")

    # Copy from source
    for item in os.listdir(source_dir):
        src = os.path.join(source_dir, item)
        dst = os.path.join(agent_dir, item)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def restore_matching(agent_dir, source_dir, pattern):
    """Restore only paths matching pattern from a checkpoint."""
    source_root, agent_root, relative_paths = _matching_restore_paths(
        agent_dir, source_dir, pattern
    )

    for relative_path in relative_paths:
        source_path = os.path.abspath(os.path.join(source_root, relative_path))
        target_path = os.path.abspath(os.path.join(agent_root, relative_path))
        _require_physical_containment(
            source_root, source_path, label="Checkpoint path"
        )
        _require_physical_containment(
            agent_root, target_path, label="Agent path"
        )

        if os.path.isdir(target_path):
            shutil.rmtree(target_path)
        elif os.path.exists(target_path):
            os.remove(target_path)

        if os.path.isdir(source_path):
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copytree(source_path, target_path)
        elif os.path.isfile(source_path):
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            shutil.copy2(source_path, target_path)


def _matching_restore_paths(agent_dir, source_dir, pattern):
    """Validate a scoped restore and return its relative matching paths."""
    source_root = os.path.abspath(source_dir)
    agent_root = os.path.abspath(agent_dir)
    source_pattern = os.path.abspath(os.path.join(source_root, pattern))
    agent_pattern = os.path.abspath(os.path.join(agent_root, pattern))
    if os.path.commonpath([source_root, source_pattern]) != source_root:
        raise ValueError(f"Restore pattern escapes checkpoint: {pattern}")
    if os.path.commonpath([agent_root, agent_pattern]) != agent_root:
        raise ValueError(f"Restore pattern escapes agent folder: {pattern}")
    if source_pattern == source_root or agent_pattern == agent_root:
        raise ValueError(f"Restore pattern matches agent root: {pattern}")

    source_matches = set()
    current_matches = set()
    for path in glob(source_pattern, recursive=True):
        relative = os.path.relpath(path, source_root)
        if _is_protected_relative_path(relative):
            raise ValueError(
                f"Restore pattern matches protected path: {pattern}"
            )
        _require_physical_containment(
            source_root, path, label="Checkpoint path"
        )
        source_matches.add(relative)
    for path in glob(agent_pattern, recursive=True):
        relative = os.path.relpath(path, agent_root)
        if _is_protected_relative_path(relative):
            raise ValueError(
                f"Restore pattern matches protected path: {pattern}"
            )
        _require_physical_containment(agent_root, path, label="Agent path")
        current_matches.add(relative)
    if not source_matches and not current_matches:
        raise ValueError(f'Restore pattern matched no paths: "{pattern}"')

    return source_root, agent_root, sorted(source_matches | current_matches)


def create_checkpoint(agent_dir, reason):
    """Create a new checkpoint of current working files. Returns the number."""
    checkpoints_dir = get_checkpoints_dir(agent_dir)
    num = next_checkpoint_number(checkpoints_dir)
    dest = os.path.join(checkpoints_dir, str(num))

    copy_working_files(agent_dir, dest)

    meta = {
        "number": num,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }
    with open(os.path.join(dest, "_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    return num


def cmd_create(agent_dir, reason):
    num = create_checkpoint(agent_dir, reason)
    print(f"Checkpoint {num} created: {reason}")


def cmd_revert(agent_dir):
    checkpoints_dir = get_checkpoints_dir(agent_dir)
    if not os.path.exists(checkpoints_dir):
        print("ERROR: No checkpoints exist. Nothing to revert.")
        sys.exit(1)

    existing = sorted(
        [int(d) for d in os.listdir(checkpoints_dir)
         if d.isdigit() and os.path.isdir(
             os.path.join(checkpoints_dir, d))])
    if not existing:
        print("ERROR: No checkpoints exist. Nothing to revert.")
        sys.exit(1)

    # Save current state first (so revert is reversible)
    save_num = create_checkpoint(agent_dir, "auto-save before revert")
    print(f"Checkpoint {save_num} created: auto-save before revert")

    # Restore from the checkpoint before the auto-save
    # (the last user-created checkpoint)
    target = existing[-1]
    source_dir = os.path.join(checkpoints_dir, str(target))
    restore_from(agent_dir, source_dir)
    print(f"Reverted to checkpoint {target}.")


def cmd_revert_reason(agent_dir, reason, only=None):
    """Restore the newest checkpoint whose metadata reason exactly matches."""
    checkpoints_dir = get_checkpoints_dir(agent_dir)
    if not os.path.exists(checkpoints_dir):
        print("ERROR: No checkpoints exist. Nothing to revert.")
        sys.exit(1)

    matches = []
    for entry in os.listdir(checkpoints_dir):
        checkpoint_dir = os.path.join(checkpoints_dir, entry)
        if not entry.isdigit() or not os.path.isdir(checkpoint_dir):
            continue
        meta_path = os.path.join(checkpoint_dir, "_meta.json")
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        if meta.get("reason") == reason:
            matches.append(int(entry))

    if not matches:
        print(f'ERROR: No checkpoint found with reason: "{reason}"')
        sys.exit(1)

    target = max(matches)
    source_dir = os.path.join(checkpoints_dir, str(target))
    if only:
        _matching_restore_paths(agent_dir, source_dir, only)

    save_num = create_checkpoint(agent_dir, "auto-save before named revert")
    print(f"Checkpoint {save_num} created: auto-save before named revert")

    if only:
        restore_matching(agent_dir, source_dir, only)
        print(
            f'Restored "{only}" from checkpoint {target}: "{reason}".'
        )
    else:
        restore_from(agent_dir, source_dir)
        print(f'Reverted to checkpoint {target}: "{reason}".')


def cmd_baseline(agent_dir):
    baseline_dir = get_baseline_dir(agent_dir)
    if not os.path.exists(baseline_dir):
        print("ERROR: No baseline exists. Run /setup first.")
        sys.exit(1)

    # Save current state first
    save_num = create_checkpoint(agent_dir, "auto-save before baseline restore")
    print(f"Checkpoint {save_num} created: auto-save before baseline restore")

    restore_from(agent_dir, baseline_dir)
    print("Restored to baseline (original environment state).")


def cmd_list(agent_dir):
    checkpoints_dir = get_checkpoints_dir(agent_dir)
    if not os.path.exists(checkpoints_dir):
        print("No checkpoints yet.")
        return

    dirs = sorted(
        [d for d in os.listdir(checkpoints_dir)
         if d.isdigit() and os.path.isdir(
             os.path.join(checkpoints_dir, d))],
        key=int)

    if not dirs:
        print("No checkpoints yet.")
        return

    print(f"{'#':<4} {'Timestamp':<28} {'Reason'}")
    print(f"{'—'*3:<4} {'—'*26:<28} {'—'*30}")
    for d in dirs:
        meta_path = os.path.join(checkpoints_dir, d, "_meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            ts = meta.get("timestamp", "?")[:19].replace("T", " ")
            reason = meta.get("reason", "")
        else:
            ts = "?"
            reason = ""
        print(f"{d:<4} {ts:<28} {reason}")


def main():
    config = load_config()
    agent_dir = get_agent_dir(config)

    if not os.path.exists(agent_dir):
        print(f"ERROR: Agent folder not found: {agent_dir}")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage:")
        print('  checkpoint.py "reason"   — Create a checkpoint')
        print("  checkpoint.py --revert   — Revert to last checkpoint")
        print('  checkpoint.py --revert-reason "reason" [--only "glob"] '
              '— Revert all or matching paths to a named checkpoint')
        print("  checkpoint.py --baseline — Restore original environment state")
        print("  checkpoint.py --list     — List all checkpoints")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--revert":
        cmd_revert(agent_dir)
    elif arg == "--revert-reason":
        if len(sys.argv) < 3:
            print("ERROR: --revert-reason requires an exact checkpoint reason.")
            sys.exit(1)
        extra_args = sys.argv[2:]
        only = None
        if "--only" in extra_args:
            only_index = extra_args.index("--only")
            if only_index == len(extra_args) - 1:
                print("ERROR: --only requires a path or glob.")
                sys.exit(1)
            only = extra_args[only_index + 1]
            reason_parts = extra_args[:only_index]
            if len(extra_args) != only_index + 2:
                print("ERROR: Unexpected arguments after --only.")
                sys.exit(1)
        else:
            reason_parts = extra_args
        if not reason_parts:
            print("ERROR: --revert-reason requires an exact checkpoint reason.")
            sys.exit(1)
        try:
            cmd_revert_reason(agent_dir, " ".join(reason_parts), only=only)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            sys.exit(1)
    elif arg == "--baseline":
        cmd_baseline(agent_dir)
    elif arg == "--list":
        cmd_list(agent_dir)
    elif arg.startswith("--"):
        print(f"ERROR: Unknown option: {arg}")
        sys.exit(1)
    else:
        reason = " ".join(sys.argv[1:])
        cmd_create(agent_dir, reason)


if __name__ == "__main__":
    main()
