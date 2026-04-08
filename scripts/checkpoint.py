"""
ESS Copilot Kit - Checkpoint Script

Creates, restores, and manages snapshots of the agent's working files.
All operations are relative to the agent folder in my/config.json.

Usage:
    python scripts/checkpoint.py "reason for checkpoint"
    python scripts/checkpoint.py --revert
    python scripts/checkpoint.py --baseline
    python scripts/checkpoint.py --list
"""

import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

EXCLUDE_DIRS = {".baseline", ".checkpoints"}


def load_config():
    config_path = os.path.join("my", "config.json")
    if not os.path.exists(config_path):
        print("ERROR: my/config.json not found. Run /setup first.")
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
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)

    def _ignore(directory, contents):
        # Only apply exclusion at the top level of agent_dir
        if os.path.normpath(directory) == os.path.normpath(agent_dir):
            return {c for c in contents if c in EXCLUDE_DIRS}
        return set()

    shutil.copytree(agent_dir, dest_dir, ignore=_ignore)


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
        print("  checkpoint.py --baseline — Restore original environment state")
        print("  checkpoint.py --list     — List all checkpoints")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--revert":
        cmd_revert(agent_dir)
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
