"""
ESS Copilot Kit - Push Script

Compares local working files against the baseline and pushes changes to
Copilot Studio via the Dataverse REST API.

Supports three component types:
  - Bot components (topics, variables, agent/settings YAML)
  - Template configs (template-configs/ folder)
  - Workflows (workflows/ folder)

Usage:
    python scripts/push.py           — Push all changes (interactive)
    python scripts/push.py --dry-run — Show what would be pushed without pushing
"""

import json
import os
import subprocess
import sys

# Add scripts/ to path so we can import siblings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth import authenticate, update_record, create_record, delete_record, load_config

EXCLUDE_DIRS = {".baseline", ".checkpoints"}
EXCLUDE_FILES = {"snapshot.md", "_meta.json"}


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
    if filepath.endswith(".mcs.yml"):
        return "botcomponent"
    return None


def collect_files(root_dir):
    """Walk a directory and return {relative_path: content} for all files."""
    files = {}
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip excluded directories
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fname in filenames:
            if fname in EXCLUDE_FILES:
                continue
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, root_dir).replace("\\", "/")
            with open(full, "r", encoding="utf-8") as f:
                files[rel] = f.read()
    return files


def compute_diff(baseline_files, working_files):
    """Compare baseline and working files. Returns (changed, new, deleted)."""
    changed = []
    new = []
    deleted = []

    all_paths = set(baseline_files.keys()) | set(working_files.keys())
    for path in sorted(all_paths):
        in_baseline = path in baseline_files
        in_working = path in working_files

        if in_baseline and in_working:
            if baseline_files[path] != working_files[path]:
                changed.append(path)
        elif in_working and not in_baseline:
            new.append(path)
        elif in_baseline and not in_working:
            deleted.append(path)

    return changed, new, deleted


def load_component_map(agent_dir):
    map_path = os.path.join(agent_dir, ".component-map.json")
    if not os.path.exists(map_path):
        print("ERROR: .component-map.json not found. Run /setup first.")
        sys.exit(1)
    with open(map_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_component_map(agent_dir, component_map):
    map_path = os.path.join(agent_dir, ".component-map.json")
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(component_map, f, indent=2)


def run_checkpoint(reason):
    """Run checkpoint.py to save current state before pushing."""
    result = subprocess.run(
        [sys.executable, "scripts/checkpoint.py", reason],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(result.stdout.strip())
    else:
        print(f"Warning: checkpoint failed: {result.stderr.strip()}")


def update_baseline(agent_dir):
    """Update .baseline/ to match current working files (post-push)."""
    import shutil
    import time

    baseline_dir = os.path.join(agent_dir, ".baseline")
    if os.path.exists(baseline_dir):
        for attempt in range(3):
            try:
                shutil.rmtree(baseline_dir)
                break
            except PermissionError:
                if attempt < 2:
                    time.sleep(1)
                else:
                    print(f"Warning: could not remove old baseline "
                          f"(file locked). Overwriting in place.")
                    # Fall through — copytree with dirs_exist_ok will overlay

    def _ignore(directory, contents):
        if os.path.normpath(directory) == os.path.normpath(agent_dir):
            return {c for c in contents if c in EXCLUDE_DIRS}
        return set()

    shutil.copytree(agent_dir, baseline_dir, ignore=_ignore,
                    dirs_exist_ok=True)


def main():
    dry_run = "--dry-run" in sys.argv
    auto_yes = "--yes" in sys.argv

    config = load_config()
    agent_dir = config["agent"]["folder"]
    env_url = config["dataverseEndpoint"]
    bot_id = config["agent"]["botId"]
    schema_name = config["agent"]["schemaName"]

    if not os.path.exists(agent_dir):
        print(f"ERROR: Agent folder not found: {agent_dir}")
        sys.exit(1)

    baseline_dir = os.path.join(agent_dir, ".baseline")
    if not os.path.exists(baseline_dir):
        print("ERROR: No baseline found. Run /setup first.")
        sys.exit(1)

    # Collect files
    baseline_files = collect_files(baseline_dir)
    working_files = collect_files(agent_dir)
    component_map = load_component_map(agent_dir)

    # Compute diff
    changed, new, deleted = compute_diff(baseline_files, working_files)

    # Filter to pushable files by type
    def is_pushable(f):
        return classify_path(f) is not None

    changed = [f for f in changed if is_pushable(f)]
    new = [f for f in new if is_pushable(f)]
    deleted = [f for f in deleted if is_pushable(f)]

    if not changed and not new and not deleted:
        print("Nothing to push. Working files match the baseline.")
        return

    # Show summary
    print("\n" + "=" * 50)
    print("PUSH SUMMARY")
    print("=" * 50)

    if changed:
        print(f"\nModified ({len(changed)}):")
        for f in changed:
            ctype = classify_path(f)
            entry = component_map.get(f, {})
            cid = (entry.get('botcomponentid') or
                   entry.get('templateconfigid') or
                   entry.get('workflowid') or '?')
            label = f"  \u270f\ufe0f  {f}"
            if cid and cid != '?':
                label += f"  ({cid[:8]}...)"
            print(label)

    if new:
        print(f"\nNew ({len(new)}):")
        for f in new:
            print(f"  ➕  {f}")

    if deleted:
        print(f"\nDeleted ({len(deleted)}):")
        for f in deleted:
            print(f"  ❌  {f}")

    print(f"\nTotal: {len(changed)} modified, {len(new)} new, {len(deleted)} deleted")

    if dry_run:
        print("\n(Dry run — no changes pushed)")
        return

    # Confirm
    if not auto_yes:
        response = input("\nPush these changes to Copilot Studio? (yes/no): ").strip().lower()
        if response not in ("yes", "y"):
            print("Push cancelled.")
            return

    # Checkpoint before pushing
    run_checkpoint("auto-save before push")

    # Authenticate
    print("\nAuthenticating to Dataverse...")
    token = authenticate(env_url)
    print("Authenticated.\n")

    success = 0
    errors = 0

    # Push modified files
    for filepath in changed:
        ctype = classify_path(filepath)
        entry = component_map.get(filepath)
        content = working_files[filepath]

        if ctype == "botcomponent":
            if not entry or not entry.get("botcomponentid"):
                print(f"  SKIP {filepath}: no component ID in map")
                errors += 1
                continue
            try:
                update_record(env_url, token, "botcomponents",
                              entry["botcomponentid"], {"data": content})
                print(f"  ✅ Updated: {filepath}")
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

        elif ctype == "template-config":
            if not entry or not entry.get("templateconfigid"):
                print(f"  SKIP {filepath}: no template config ID in map")
                errors += 1
                continue
            # Read companion meta file for metadata updates
            meta_rel = entry.get("meta_file", "")
            meta_data = {}
            if meta_rel:
                meta_full = os.path.join(agent_dir, meta_rel)
                if os.path.exists(meta_full):
                    with open(meta_full, "r", encoding="utf-8") as mf:
                        meta_data = json.load(mf)
            record = {"msdyn_value": content}
            if meta_data.get("msdyn_name"):
                record["msdyn_name"] = meta_data["msdyn_name"]
            if meta_data.get("msdyn_description"):
                record["msdyn_description"] = meta_data["msdyn_description"]
            try:
                update_record(
                    env_url, token,
                    "msdyn_employeeselfservicetemplateconfigs",
                    entry["templateconfigid"], record)
                print(f"  ✅ Updated: {filepath}")
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

        elif ctype == "workflow":
            if not entry or not entry.get("workflowid"):
                print(f"  SKIP {filepath}: no workflow ID in map")
                errors += 1
                continue
            try:
                update_record(env_url, token, "workflows",
                              entry["workflowid"],
                              {"clientdata": content})
                print(f"  ✅ Updated: {filepath}")
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

        elif ctype == "workflow-meta":
            # Metadata-only change (e.g., rename). Look up workflow entry
            # via the corresponding workflow.json path.
            folder = "/".join(filepath.replace("\\", "/").split("/")[:-1])
            wf_json_path = f"{folder}/workflow.json"
            entry = component_map.get(wf_json_path)
            if not entry or not entry.get("workflowid"):
                print(f"  SKIP {filepath}: no workflow ID in map")
                errors += 1
                continue
            # Parse name/description from metadata.yml
            record = {}
            for line in content.splitlines():
                if line.startswith("name: "):
                    record["name"] = line[6:].strip()
                elif line.startswith("description: "):
                    val = line[13:].strip().strip('"')
                    if val:
                        record["description"] = val
            if not record:
                print(f"  SKIP {filepath}: no pushable metadata changes")
                continue
            try:
                update_record(env_url, token, "workflows",
                              entry["workflowid"], record)
                print(f"  ✅ Updated: {filepath}")
                if "name" in record:
                    entry["name"] = record["name"]
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

    # Push new files
    for filepath in new:
        ctype = classify_path(filepath)
        content = working_files[filepath]

        if ctype == "botcomponent":
            parts = filepath.replace("\\", "/").split("/")
            fname = parts[-1].replace(".mcs.yml", "")
            if parts[0] == "topics":
                schema = f"{schema_name}.topic.{fname}"
                comp_type = 9
            elif parts[0] == "variables":
                schema = f"{schema_name}.variable.{fname}"
                comp_type = 12
            else:
                print(f"  SKIP {filepath}: unsupported component type")
                errors += 1
                continue
            record_data = {
                "componenttype": comp_type,
                "data": content,
                "name": fname.replace("-", " ").title(),
                "schemaname": schema,
                "parentbotid@odata.bind": f"/bots({bot_id})",
            }
            try:
                new_id = create_record(env_url, token,
                                       "botcomponents", record_data)
                print(f"  ✅ Created: {filepath} (ID: {new_id})")
                component_map[filepath] = {
                    "botcomponentid": new_id,
                    "schemaname": schema,
                    "componenttype": comp_type,
                    "name": record_data["name"],
                }
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

        elif ctype == "template-config":
            # Read companion meta file
            base = filepath.rsplit(".", 1)[0]
            meta_rel = base + ".meta.json"
            meta_full = os.path.join(agent_dir, meta_rel)
            meta_data = {}
            if os.path.exists(meta_full):
                with open(meta_full, "r", encoding="utf-8") as mf:
                    meta_data = json.load(mf)
            record_data = {
                "msdyn_name": meta_data.get("msdyn_name",
                                            os.path.basename(filepath)),
                "msdyn_uniquename": meta_data.get("msdyn_uniquename", ""),
                "msdyn_value": content,
                "msdyn_description": meta_data.get("msdyn_description", ""),
            }
            try:
                new_id = create_record(
                    env_url, token,
                    "msdyn_employeeselfservicetemplateconfigs",
                    record_data)
                print(f"  ✅ Created: {filepath} (ID: {new_id})")
                component_map[filepath] = {
                    "templateconfigid": new_id,
                    "msdyn_uniquename": record_data["msdyn_uniquename"],
                    "entity_set": "msdyn_employeeselfservicetemplateconfigs",
                    "name": record_data["msdyn_name"],
                    "meta_file": meta_rel,
                }
                # Update meta file with new ID
                meta_data[
                    "msdyn_employeeselfservicetemplateconfigid"] = new_id
                with open(meta_full, "w", encoding="utf-8") as mf:
                    json.dump(meta_data, mf, indent=2)
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

        elif ctype == "workflow-meta":
            continue  # new metadata.yml handled by workflow.json creation

        elif ctype == "workflow":
            # Read companion metadata.yml for name/description
            parts = filepath.replace("\\", "/").split("/")
            folder = "/".join(parts[:-1])
            meta_rel = f"{folder}/metadata.yml"
            meta_full = os.path.join(agent_dir, meta_rel)
            wf_name = "New Workflow"
            wf_desc = ""
            if os.path.exists(meta_full):
                with open(meta_full, "r", encoding="utf-8") as mf:
                    for line in mf:
                        if line.startswith("name: "):
                            wf_name = line[6:].strip()
                        elif line.startswith("description: "):
                            wf_desc = line[13:].strip().strip('"')
            record_data = {
                "name": wf_name,
                "clientdata": content,
                "category": 5,  # Modern Flow
                "type": 1,      # Definition
                "description": wf_desc,
            }
            try:
                new_id = create_record(env_url, token, "workflows",
                                       record_data)
                print(f"  ✅ Created: {filepath} (ID: {new_id})")
                component_map[filepath] = {
                    "workflowid": new_id,
                    "entity_set": "workflows",
                    "name": wf_name,
                    "meta_file": meta_rel,
                }
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

    # Push deletions
    for filepath in deleted:
        ctype = classify_path(filepath)
        entry = component_map.get(filepath)

        if ctype == "botcomponent":
            if not entry or not entry.get("botcomponentid"):
                print(f"  SKIP {filepath}: no component ID in map")
                errors += 1
                continue
            try:
                delete_record(env_url, token, "botcomponents",
                              entry["botcomponentid"])
                print(f"  ✅ Deleted: {filepath}")
                del component_map[filepath]
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

        elif ctype == "template-config":
            if not entry or not entry.get("templateconfigid"):
                print(f"  SKIP {filepath}: no template config ID in map")
                errors += 1
                continue
            try:
                delete_record(
                    env_url, token,
                    "msdyn_employeeselfservicetemplateconfigs",
                    entry["templateconfigid"])
                print(f"  ✅ Deleted: {filepath}")
                del component_map[filepath]
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

        elif ctype == "workflow-meta":
            continue  # metadata.yml deletion handled by workflow.json deletion

        elif ctype == "workflow":
            if not entry or not entry.get("workflowid"):
                print(f"  SKIP {filepath}: no workflow ID in map")
                errors += 1
                continue
            try:
                delete_record(env_url, token, "workflows",
                              entry["workflowid"])
                print(f"  ✅ Deleted: {filepath}")
                del component_map[filepath]
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

    # Save updated component map
    save_component_map(agent_dir, component_map)

    # Update baseline to match what was pushed
    if success > 0:
        update_baseline(agent_dir)

    # Summary
    print(f"\n{'=' * 50}")
    print("PUSH COMPLETE")
    print(f"{'=' * 50}")
    print(f"Success: {success}")
    if errors:
        print(f"Errors:  {errors}")
    print("")


if __name__ == "__main__":
    main()
