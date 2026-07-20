# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Push Script

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

import fnmatch
import json
import os
import subprocess
import sys
import time
import uuid

try:
    import yaml
except ImportError:
    print("ERROR: 'PyYAML' package not found. Run: pip install -r scripts/requirements.txt")
    sys.exit(1)

# Add scripts/ to path so we can import siblings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth import (
    authenticate,
    update_record,
    create_record,
    delete_record,
    dataverse_get,
    load_config,
    AuthExpiredError,
)

EXCLUDE_DIRS = {".baseline", ".checkpoints"}
EXCLUDE_FILES = {"snapshot.md", "_meta.json"}


class _AuthHolder:
    """Mutable token wrapper so the 401-retry helper can refresh in place.

    A long push (200+ components) can outlive an MSAL access token (~1 hour),
    so update/create/delete calls go through _call_with_refresh which catches
    AuthExpiredError, re-authenticates, and retries the call once.
    """

    def __init__(self, env_url):
        self.env_url = env_url
        self.token = None

    def acquire(self):
        self.token = authenticate(self.env_url)
        return self.token

    def refresh(self):
        print("  ! Access token expired - re-authenticating...")
        return self.acquire()


def _call_with_refresh(auth, fn, *args, **kwargs):
    """Call a Dataverse helper with one auto-retry on 401."""
    try:
        return fn(*args, **kwargs)
    except AuthExpiredError:
        auth.refresh()
        # Replace the stale token positional - by convention the second
        # positional arg of update/create/delete_record is `token`.
        new_args = list(args)
        if len(new_args) >= 2:
            new_args[1] = auth.token
        return fn(*new_args, **kwargs)


def _verify_bot_exists(auth, env_url, bot_id):
    """Fail fast if the configured agent bot is missing from this environment.

    A stale/mismatched ``botId`` (the agent was deleted and recreated, or the
    config points at a different environment) otherwise makes EVERY component
    create/update fail with Dataverse's misleading 404 ("bot ... Does Not
    Exist"), which the friendly error layer renders as "Could not find agent
    components / solution may not be deployed" — a dead end that sends users
    chasing a solution-install problem that isn't real. Surface the true
    cause once, up front, instead.

    Exits the process with status 2 when the bot cannot be resolved (404).
    Other errors propagate unchanged so genuine transient failures are not
    masked as a stale-config problem.
    """
    try:
        _call_with_refresh(auth, dataverse_get, env_url, auth.token,
                           f"bots({bot_id})", {"$select": "botid"})
    except Exception as exc:  # noqa: BLE001 — surface the real cause below
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            print(
                f"ERROR: The configured agent (botId {bot_id}) does not exist "
                f"in this environment ({env_url}).\n"
                "This usually means the agent was deleted and recreated, or the "
                "config points at a different environment.\n"
                "Fix: re-run /setup (or update agent.botId in .local/config.json) "
                "so it matches the current agent, then push again."
            )
            sys.exit(2)
        raise


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
            # OneDrive placeholders can occasionally enumerate but be unreadable.
            try:
                with open(full, "r", encoding="utf-8") as f:
                    files[rel] = f.read()
            except FileNotFoundError:
                continue
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


def _read_only_manifest(path):
    """Read a push scope manifest: one relative path/glob per line.

    Blank lines and lines starting with '#' are ignored. Backslashes are
    normalized to forward slashes so entries match the forward-slash
    relative paths compute_diff produces.
    """
    globs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                globs.append(line.replace("\\", "/"))
    return globs


def parse_only_globs(argv):
    """Collect --only GLOB / --only=GLOB (repeatable) and --only-from FILE.

    Returns a list of glob patterns. An empty list means "no scoping" —
    push behaves exactly as before and touches every changed file.
    """
    globs = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--only" and i + 1 < len(argv):
            globs.append(argv[i + 1].replace("\\", "/"))
            i += 2
            continue
        if arg.startswith("--only="):
            globs.append(arg.split("=", 1)[1].replace("\\", "/"))
            i += 1
            continue
        if arg == "--only-from" and i + 1 < len(argv):
            globs.extend(_read_only_manifest(argv[i + 1]))
            i += 2
            continue
        if arg.startswith("--only-from="):
            globs.extend(_read_only_manifest(arg.split("=", 1)[1]))
            i += 1
            continue
        i += 1
    return globs


def matches_only(filepath, only_globs):
    """True if filepath matches any scope glob (or scoping is disabled)."""
    if not only_globs:
        return True
    fn = filepath.replace("\\", "/")
    return any(fnmatch.fnmatch(fn, g) for g in only_globs)


def load_component_map(agent_dir):
    map_path = os.path.join(agent_dir, ".component-map.json")
    if not os.path.exists(map_path):
        print("ERROR: .component-map.json not found. Run /setup first.")
        sys.exit(1)
    with open(map_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _atomic_write_text(path, text):
    """Write text to *.tmp sibling and os.replace() into place.

    Mirrors the write_config pattern in setup.py. Use this for any file
    that gates subsequent kit operations (.component-map.json, template
    config meta files): a crash mid-write must not leave a half-written
    file on disk.
    """
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            # Some filesystems don't support fsync; the os.replace below
            # is still atomic on POSIX/Windows.
            pass
    os.replace(tmp_path, path)


def save_component_map(agent_dir, component_map):
    map_path = os.path.join(agent_dir, ".component-map.json")
    _atomic_write_text(map_path, json.dumps(component_map, indent=2))


def _cache_environment_sku(sku):
    """Persist the resolved environment SKU into .local/config.json so future
    pushes can classify deploy telemetry without another BAP round-trip.

    Best-effort and non-fatal — a failure here never affects the push.
    """
    if not sku:
        return
    try:
        config_path = os.path.join(".local", "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("environmentSku") == sku:
            return
        data["environmentSku"] = sku
        _atomic_write_text(config_path, json.dumps(data, indent=2))
    except Exception:  # noqa: BLE001 — caching is best-effort only
        pass


def _lookup_environment_sku_silent(env_url):
    """Best-effort, SILENT lookup of the target environment's BAP SKU.

    Never prompts for sign-in (uses only the cached MSAL token) and never
    raises — returns the SKU string or None. Used purely for telemetry
    attribution, so it must not add latency-blocking auth to /push.
    """
    if not env_url:
        return None
    try:
        from auth import discover_tenant
        from flightcheck.pp_admin_client import PPAdminClient

        tenant_id = discover_tenant(env_url)
        client = PPAdminClient(tenant_id)
        if not client.authenticate_silent():
            return None
        return client.get_environment_sku_by_dataverse_url(env_url)
    except Exception:  # noqa: BLE001 — best-effort telemetry attribution
        return None


def _resolve_deploy_target(config, env_url):
    """Resolve the deploy-target bucket for agent.deploy telemetry.

    Power Platform only lets us reliably distinguish two buckets — sandbox
    vs production — via the BAP ``environmentSku`` (there is no "staging"
    environment concept). Resolution priority:

      1. Explicit ``ESS_ADK_DEPLOY_TARGET`` override, but ONLY when it names a
         current bucket (``sandbox``/``production``). A stale override naming a
         retired bucket (``test``/``staging``) is ignored so it can't resurface
         wedges the dashboards no longer model — we fall through to SKU
         detection instead.
      2. ``environmentSku`` cached in .local/config.json from a prior push.
      3. Best-effort SILENT BAP lookup of the target env's SKU (never
         prompts); the result is cached back into config.json.
      4. Default ``production`` (real deploys are overwhelmingly prod, and
         this preserves the historical default).
    """
    try:
        import adk_telemetry
    except Exception:  # noqa: BLE001
        return "production"
    override = os.environ.get("ESS_ADK_DEPLOY_TARGET", "").strip().lower()
    if override in (
        adk_telemetry.DEPLOY_TARGET_SANDBOX,
        adk_telemetry.DEPLOY_TARGET_PRODUCTION,
    ):
        return override
    sku = (config.get("environmentSku") or "").strip()
    if not sku:
        sku = _lookup_environment_sku_silent(env_url) or ""
        if sku:
            _cache_environment_sku(sku)
    return adk_telemetry.classify_deploy_target(sku)


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
                    print("Warning: could not remove old baseline "
                          "(file locked). Overwriting in place.")
                    # Fall through — copytree with dirs_exist_ok will overlay

    def _ignore(directory, contents):
        if os.path.normpath(directory) == os.path.normpath(agent_dir):
            return {c for c in contents if c in EXCLUDE_DIRS}
        return set()

    shutil.copytree(agent_dir, baseline_dir, ignore=_ignore,
                    dirs_exist_ok=True)


def update_baseline_scoped(agent_dir, only_globs):
    """Refresh ONLY the scoped subset of the baseline after a scoped push.

    A scoped push (--only / --only-from) sends just the matching files to
    Dataverse. If we then ran the full update_baseline(), every OTHER
    changed/new file in the working tree would get copied into the baseline
    too — silently marking files that were never pushed as "pushed", so the
    next /push would not retry them. That is a correctness bug, so scoped
    pushes must refresh the baseline for the scoped files only and leave all
    other pending working-tree changes still pending.

    For each working file matching a scope glob, copy it (exact bytes) into
    the baseline. Template-config .xml files also drag in their .meta.json
    companion. Baseline files that match a scope glob but no longer exist in
    the working tree are removed (a scoped delete).
    """
    import shutil

    baseline_dir = os.path.join(agent_dir, ".baseline")
    working = collect_files(agent_dir)

    scoped = {rel for rel in working if matches_only(rel, only_globs)}
    for rel in list(scoped):
        if rel.startswith("template-configs/") and rel.endswith(".xml"):
            meta = rel[:-4] + ".meta.json"
            if meta in working:
                scoped.add(meta)

    for rel in scoped:
        src = os.path.join(agent_dir, *rel.split("/"))
        dst = os.path.join(baseline_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

    # Scoped deletions: drop baseline files matching the scope that are gone.
    for rel in collect_files(baseline_dir):
        if matches_only(rel, only_globs) and rel not in working:
            try:
                os.remove(os.path.join(baseline_dir, *rel.split("/")))
            except OSError:
                pass


def main():
    dry_run = "--dry-run" in sys.argv
    auto_yes = "--yes" in sys.argv
    force_delete = "--force-delete" in sys.argv
    only_globs = parse_only_globs(sys.argv[1:])

    config = load_config()
    agent_dir = config["agent"]["folder"]
    env_url = config["dataverseEndpoint"]
    bot_id = config["agent"]["botId"]
    schema_name = config["agent"]["schemaName"]
    _push_start = time.perf_counter()

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

    # Optional scoping: --only / --only-from restrict the push (and the
    # baseline refresh) to files matching the given globs. Applied AFTER the
    # pushable filter so scope patterns match the same relative paths shown.
    if only_globs:
        changed = [f for f in changed if matches_only(f, only_globs)]
        new = [f for f in new if matches_only(f, only_globs)]
        deleted = [f for f in deleted if matches_only(f, only_globs)]

    if not changed and not new and not deleted:
        if only_globs:
            print("Nothing to push in the selected scope.")
        else:
            print("Nothing to push. Working files match the baseline.")
        return

    # Show summary
    print("\n" + "=" * 50)
    print("PUSH SUMMARY")
    print("=" * 50)
    if only_globs:
        print(f"\n(Scoped push — {len(only_globs)} filter(s) active)")

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

    # Pre-push schema validation: parse-check each file we're about to send
    # so a malformed YAML/JSON surfaces a clear local error rather than a
    # cryptic Dataverse 400/500 mid-push.
    parse_errors = []
    for filepath in changed + new:
        ctype = classify_path(filepath)
        content = working_files[filepath]
        if ctype in ("botcomponent", "workflow-meta") or filepath.endswith(".mcs.yml"):
            # YAML parse-check (use the safe loader to avoid arbitrary code exec).
            try:
                yaml.safe_load(content)
            except yaml.YAMLError as exc:
                parse_errors.append(f"  YAML parse error in {filepath}: {exc}")
        elif ctype == "workflow":
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                parse_errors.append(f"  JSON parse error in {filepath}: {exc}")
        elif ctype == "template-config":
            # Either JSON or XML; only validate JSON, XML may be templated.
            stripped = content.lstrip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    json.loads(content)
                except json.JSONDecodeError as exc:
                    parse_errors.append(f"  JSON parse error in {filepath}: {exc}")

    if parse_errors:
        print("\nERROR: pre-push schema validation failed. Fix these and re-run:")
        for err in parse_errors:
            print(err)
        sys.exit(2)

    # Confirm general push
    if not auto_yes:
        response = input("\nPush these changes to Copilot Studio? (yes/no): ").strip().lower()
        if response not in ("yes", "y"):
            print("Push cancelled.")
            return

    # Separate confirmation for destructive operations. --yes covers
    # creates and updates; deletes additionally require --force-delete
    # OR an interactive 'delete' confirmation.
    if deleted and not force_delete:
        if auto_yes:
            print(
                f"\nERROR: Refusing to delete {len(deleted)} component(s) without"
                " --force-delete. Re-run with --force-delete (alongside --yes)"
                " if you really want to delete these:"
            )
            for d in deleted:
                print(f"  - {d}")
            sys.exit(2)
        print(f"\nWARNING: this will DELETE {len(deleted)} component(s):")
        for d in deleted:
            print(f"  - {d}")
        confirm = input("\nType 'delete' to confirm deletion, or anything else to abort: ").strip().lower()
        if confirm != "delete":
            print("Push cancelled (deletes not confirmed).")
            return

    # Checkpoint before pushing
    run_checkpoint("auto-save before push")

    # Authenticate
    print("\nAuthenticating to Dataverse...")
    auth = _AuthHolder(env_url)
    auth.acquire()
    print("Authenticated.\n")

    # Pre-flight: verify the configured agent bot still exists in this
    # environment (see _verify_bot_exists for why this matters).
    _verify_bot_exists(auth, env_url, bot_id)

    # Telemetry: a push is the ADK "build" of an agent's components into
    # Copilot Studio. Best-effort; never affects the push.
    try:
        import adk_telemetry

        adk_telemetry.emit_build_start(agent_id=bot_id, adk_capability="publishing")
    except Exception:  # noqa: BLE001 — telemetry must never break push
        pass

    success = 0
    errors = 0

    # Side-collections for the partial-failure gate. Mutating component_map
    # in-loop and only saving the file on full success leaves the in-memory
    # map and the on-disk map out of sync after a partial failure: the next
    # /push retries already-completed CRUD operations against records that
    # no longer exist (delete) or duplicates them (create). Track creates,
    # deletes, and post-create meta-file writes here; apply only inside the
    # `errors == 0 and success > 0` block at the end.
    pending_creates: dict = {}     # filepath -> component_map entry
    pending_deletes: set = set()   # filepaths to remove from component_map
    pending_meta_writes: list = []  # list[(meta_full_path, meta_data_dict)]
    pending_renames: dict = {}     # filepath -> new name (workflow-meta
                                   # rename mutations staged for the gate)

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
                _call_with_refresh(auth, update_record,
                                   env_url, auth.token, "botcomponents",
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
                _call_with_refresh(auth, update_record,
                                   env_url, auth.token,
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
                _call_with_refresh(auth, update_record,
                                   env_url, auth.token, "workflows",
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
            # Parse name/description from metadata.yml using yaml.safe_load
            # (was hand-rolled startswith; broke on quoted values, leading
            # whitespace, and inline comments). PyYAML is already required
            # by the pre-push schema validation step above; reuse it here.
            try:
                parsed_meta = yaml.safe_load(content) or {}
            except yaml.YAMLError as exc:
                print(f"  ❌ Failed: {filepath}: invalid YAML: {exc}")
                errors += 1
                continue
            record = {}
            if parsed_meta.get("name"):
                record["name"] = str(parsed_meta["name"])
            if parsed_meta.get("description"):
                record["description"] = str(parsed_meta["description"])
            if not record:
                print(f"  SKIP {filepath}: no pushable metadata changes")
                continue
            try:
                _call_with_refresh(auth, update_record,
                                   env_url, auth.token, "workflows",
                                   entry["workflowid"], record)
                print(f"  ✅ Updated: {filepath}")
                if "name" in record:
                    # Stage the rename for the success gate, keyed by the
                    # workflow.json path because that is how component_map
                    # tracks workflow entries (the metadata.yml path is
                    # NOT a component_map key). Keying by `filepath` here
                    # would silently drop the rename at the gate, leaving
                    # the on-disk map with the old name even after a
                    # successful Dataverse PATCH.
                    pending_renames[wf_json_path] = record["name"]
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

    # Push new files — separate evaluations for two-pass parent→child ordering
    eval_new = []
    non_eval_new = []
    for filepath in new:
        parts = filepath.replace("\\", "/").split("/")
        if parts[0] == "evaluations":
            eval_new.append(filepath)
        else:
            non_eval_new.append(filepath)

    for filepath in non_eval_new:
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
                new_id = _call_with_refresh(auth, create_record,
                                            env_url, auth.token,
                                            "botcomponents", record_data)
                print(f"  ✅ Created: {filepath} (ID: {new_id})")
                pending_creates[filepath] = {
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
                new_id = _call_with_refresh(
                    auth, create_record,
                    env_url, auth.token,
                    "msdyn_employeeselfservicetemplateconfigs",
                    record_data)
                print(f"  ✅ Created: {filepath} (ID: {new_id})")
                pending_creates[filepath] = {
                    "templateconfigid": new_id,
                    "msdyn_uniquename": record_data["msdyn_uniquename"],
                    "entity_set": "msdyn_employeeselfservicetemplateconfigs",
                    "name": record_data["msdyn_name"],
                    "meta_file": meta_rel,
                }
                # Defer the meta-file write back to disk until the final
                # success gate. Otherwise a partial-failure leaves the meta
                # file stamped with a new ID while the on-disk component_map
                # is unchanged - next push picks the file up as new again.
                meta_data["msdyn_employeeselfservicetemplateconfigid"] = new_id
                pending_meta_writes.append((meta_full, dict(meta_data)))
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

        elif ctype == "workflow-meta":
            continue  # new metadata.yml handled by workflow.json creation

        elif ctype == "workflow":
            # Read companion metadata.yml for name/description (yaml-safe).
            parts = filepath.replace("\\", "/").split("/")
            folder = "/".join(parts[:-1])
            meta_rel = f"{folder}/metadata.yml"
            meta_full = os.path.join(agent_dir, meta_rel)
            wf_name = "New Workflow"
            wf_desc = ""
            if os.path.exists(meta_full):
                with open(meta_full, "r", encoding="utf-8") as mf:
                    try:
                        parsed_wf_meta = yaml.safe_load(mf) or {}
                    except yaml.YAMLError as exc:
                        print(f"  ❌ Failed: {filepath}: invalid YAML in {meta_rel}: {exc}")
                        errors += 1
                        continue
                if parsed_wf_meta.get("name"):
                    wf_name = str(parsed_wf_meta["name"])
                if parsed_wf_meta.get("description"):
                    wf_desc = str(parsed_wf_meta["description"])
            record_data = {
                "name": wf_name,
                "clientdata": content,
                "category": 5,  # Modern Flow
                "type": 1,      # Definition
                "description": wf_desc,
            }
            try:
                new_id = _call_with_refresh(auth, create_record,
                                            env_url, auth.token, "workflows",
                                            record_data)
                print(f"  ✅ Created: {filepath} (ID: {new_id})")
                pending_creates[filepath] = {
                    "workflowid": new_id,
                    "entity_set": "workflows",
                    "name": wf_name,
                    "meta_file": meta_rel,
                }
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

    # Push new evaluations (two-pass: parents first, then children)
    if eval_new:
        eval_parents = []
        eval_children = []
        for filepath in eval_new:
            content = working_files[filepath]
            if "kind: EvaluationSet" in content:
                eval_parents.append(filepath)
            else:
                eval_children.append(filepath)

        # Pass 1: Create parent EvaluationSet records
        # Map local filepath → new botcomponentid for child linking
        eval_parent_ids = {}
        for filepath in eval_parents:
            content = working_files[filepath]
            fname = filepath.replace("\\", "/").split("/")[-1].replace(".mcs.yml", "")
            schema = f"mspva_{uuid.uuid4()}"
            record_data = {
                "componenttype": 19,
                "data": content,
                "name": fname.replace("-", " ").title(),
                "schemaname": schema,
                "parentbotid@odata.bind": f"/bots({bot_id})",
            }
            try:
                new_id = _call_with_refresh(auth, create_record,
                                            env_url, auth.token,
                                            "botcomponents", record_data)
                print(f"  ✅ Created: {filepath} (ID: {new_id})")
                pending_creates[filepath] = {
                    "botcomponentid": new_id,
                    "schemaname": schema,
                    "componenttype": 19,
                    "name": record_data["name"],
                }
                eval_parent_ids[filepath] = new_id
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

        # Pass 2: Create child EvaluationData records
        for filepath in eval_children:
            content = working_files[filepath]
            fname = filepath.replace("\\", "/").split("/")[-1].replace(".mcs.yml", "")
            schema = f"mspva_{uuid.uuid4()}"

            # Resolve the parent for this child. Three lookup paths in
            # priority order, all scoped to the child's evaluations/<set>/
            # folder. Fail closed (do NOT create the child as an orphan)
            # if all three miss.
            #
            #   1. Re-pushing a known child -> use its stored parent
            #      (component_map[filepath].parentbotcomponentid).
            #   2. Parent created earlier in THIS push, same folder ->
            #      eval_parent_ids lookup.
            #   3. Existing parent already in component_map, same folder
            #      (the common case: customer adds a new test case under
            #      an eval set previously extracted by /setup).
            #
            # If you change the priority or add a fourth path, update
            # this block at the same time.
            parent_id = None
            child_folder = "/".join(
                filepath.replace("\\", "/").split("/")[:-1]
            )

            # 1. Re-pushing a known child? Use its stored parent.
            entry = component_map.get(filepath)
            if entry and entry.get("parentbotcomponentid"):
                parent_id = entry["parentbotcomponentid"]

            child_fname = filepath.replace("\\", "/").split("/")[-1]

            def _match_parent_by_prefix(candidates):
                """Pick the candidate whose filename stem is the longest
                prefix of *child_fname*.  Returns the matched parent ID
                or None."""
                best_id = None
                best_stem_len = -1
                for p_path, p_id in candidates:
                    p_stem = (
                        p_path.replace("\\", "/").split("/")[-1]
                        .replace(".mcs.yml", "")
                    )
                    if child_fname.startswith(p_stem + "-") and len(p_stem) > best_stem_len:
                        best_id = p_id
                        best_stem_len = len(p_stem)
                return best_id

            # 2. Parent created in THIS push, same folder.
            #    When multiple parents share a folder, prefer the one
            #    whose filename stem is a prefix of the child filename
            #    (e.g. parent "topic-triggering.mcs.yml" matches child
            #    "topic-triggering-base-compensation.mcs.yml").
            if parent_id is None:
                _folder_matches = []
                for p_path, p_id in eval_parent_ids.items():
                    p_folder = "/".join(
                        p_path.replace("\\", "/").split("/")[:-1]
                    )
                    if p_folder == child_folder:
                        _folder_matches.append((p_path, p_id))
                if len(_folder_matches) == 1:
                    parent_id = _folder_matches[0][1]
                elif len(_folder_matches) > 1:
                    parent_id = _match_parent_by_prefix(_folder_matches)
                    if parent_id is None:
                        # No prefix match; fall back to first.
                        parent_id = _folder_matches[0][1]

            # 3. Existing parent already in component_map, same folder.
            #    This is the common case: customer adds a new test case
            #    under an evaluation set that was extracted by /setup.
            if parent_id is None:
                _cm_matches = []
                for p_path, p_entry in component_map.items():
                    if p_entry.get("componenttype") != 19:
                        continue
                    if p_entry.get("parentbotcomponentid"):
                        continue  # this is a child, not a parent
                    p_folder = "/".join(
                        p_path.replace("\\", "/").split("/")[:-1]
                    )
                    if p_folder == child_folder:
                        _cm_matches.append(
                            (p_path, p_entry.get("botcomponentid")))
                if len(_cm_matches) == 1:
                    parent_id = _cm_matches[0][1]
                elif len(_cm_matches) > 1:
                    parent_id = _match_parent_by_prefix(_cm_matches)
                    if parent_id is None:
                        print(
                            f"  ❌ Failed: {filepath}: multiple eval parents found "
                            f"in {child_folder}/ but none matches the filename "
                            f"prefix deterministically. Rename the case to use a "
                            f"parent prefix or remove the ambiguity."
                        )

            if parent_id is None:
                # Fail closed: don't create an orphan eval case in
                # Dataverse. The customer needs a parent eval set in this
                # folder before the case can be pushed.
                print(
                    f"  ❌ Failed: {filepath}: no eval parent found in "
                    f"{child_folder}/. Add a parent eval set in this folder "
                    f"before pushing the case."
                )
                errors += 1
                continue

            record_data = {
                "componenttype": 19,
                "data": content,
                "name": fname.replace("-", " ").title(),
                "schemaname": schema,
                "parentbotid@odata.bind": f"/bots({bot_id})",
            }
            record_data["ParentBotComponentId@odata.bind"] = \
                f"/botcomponents({parent_id})"
            try:
                new_id = _call_with_refresh(auth, create_record,
                                            env_url, auth.token,
                                            "botcomponents", record_data)
                print(f"  ✅ Created: {filepath} (ID: {new_id})")
                pending_creates[filepath] = {
                    "botcomponentid": new_id,
                    "schemaname": schema,
                    "componenttype": 19,
                    "name": record_data["name"],
                    "parentbotcomponentid": parent_id,
                }
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

    # Push deletions — order evaluations: children before parents
    eval_deleted = []
    non_eval_deleted = []
    for filepath in deleted:
        parts = filepath.replace("\\", "/").split("/")
        entry = component_map.get(filepath, {})
        if parts[0] == "evaluations" or entry.get("componenttype") == 19:
            eval_deleted.append(filepath)
        else:
            non_eval_deleted.append(filepath)

    # Sort evaluation deletions: children (have parentbotcomponentid) first
    eval_children_del = [f for f in eval_deleted
                         if component_map.get(f, {}).get("parentbotcomponentid")]
    eval_parents_del = [f for f in eval_deleted
                        if not component_map.get(f, {}).get("parentbotcomponentid")]
    ordered_deleted = eval_children_del + eval_parents_del + non_eval_deleted

    for filepath in ordered_deleted:
        ctype = classify_path(filepath)
        entry = component_map.get(filepath)

        if ctype == "botcomponent":
            if not entry or not entry.get("botcomponentid"):
                print(f"  SKIP {filepath}: no component ID in map")
                errors += 1
                continue
            try:
                _call_with_refresh(auth, delete_record,
                                   env_url, auth.token, "botcomponents",
                                   entry["botcomponentid"])
                print(f"  ✅ Deleted: {filepath}")
                pending_deletes.add(filepath)
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
                _call_with_refresh(
                    auth, delete_record,
                    env_url, auth.token,
                    "msdyn_employeeselfservicetemplateconfigs",
                    entry["templateconfigid"])
                print(f"  ✅ Deleted: {filepath}")
                pending_deletes.add(filepath)
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
                _call_with_refresh(auth, delete_record,
                                   env_url, auth.token, "workflows",
                                   entry["workflowid"])
                print(f"  ✅ Deleted: {filepath}")
                pending_deletes.add(filepath)
                success += 1
            except Exception as e:
                print(f"  ❌ Failed: {filepath}: {e}")
                errors += 1

    # Apply pending state mutations atomically with the baseline + map save.
    # The full-success gate is the contract: if everything pushed, persist
    # the new component_map (with creates merged in and deletes removed),
    # write back any template-config meta-files with their new IDs, and
    # refresh the baseline. On partial failure, do NONE of these and warn
    # the user. The next /push then sees an unchanged baseline and retries
    # the failed operations against an unchanged remote state.
    #
    # Why side-collections instead of mutating component_map / disk in-loop:
    # a partial failure used to leave the in-memory map and on-disk map out
    # of sync, so the next push retried already-completed CRUD operations
    # against records that no longer existed (delete) or duplicated them
    # (create). The atomic gate preserves the contract.
    if errors == 0 and success > 0:
        # Atomic two-phase persist:
        #   Phase 1: mutate the in-memory component_map.
        #   Phase 2: write every disk artifact to a *.tmp sibling first.
        #            On any failure here, clean up tmps and abort BEFORE
        #            any rename happens, so on-disk state is unchanged.
        #   Phase 3: os.replace each tmp into place. The atomic renames
        #            commit the new state. component_map.json is renamed
        #            LAST because it is the file the next /push reads to
        #            know what is already in Dataverse; if a meta file
        #            commits but component_map does not, the next push
        #            sees the template config as `new` and duplicates it.
        #   Phase 4: refresh the baseline (best-effort directory copy;
        #            failure here only causes the next diff to over-report).
        #
        # API operations have already committed remotely at this point.
        # If we cannot persist locally, surface a clear recovery message
        # and exit non-zero so the customer knows local state did not
        # catch up to remote state. The next /setup --refresh resyncs.
        for path, entry in pending_creates.items():
            component_map[path] = entry
        for path in pending_deletes:
            component_map.pop(path, None)
        for path, new_name in pending_renames.items():
            if path in component_map:
                component_map[path]["name"] = new_name

        # Phase 2: stage every write to a .tmp sibling.
        map_path = os.path.join(agent_dir, ".component-map.json")
        map_tmp = map_path + ".tmp"
        meta_tmps = []  # list[(meta_full, meta_tmp)]
        try:
            for meta_full, meta_data in pending_meta_writes:
                meta_tmp = meta_full + ".tmp"
                with open(meta_tmp, "w", encoding="utf-8") as mf:
                    json.dump(meta_data, mf, indent=2)
                    mf.flush()
                    try:
                        os.fsync(mf.fileno())
                    except OSError:
                        pass
                meta_tmps.append((meta_full, meta_tmp))
            with open(map_tmp, "w", encoding="utf-8") as mf:
                json.dump(component_map, mf, indent=2)
                mf.flush()
                try:
                    os.fsync(mf.fileno())
                except OSError:
                    pass
        except OSError as exc:
            for _, meta_tmp in meta_tmps:
                try:
                    os.remove(meta_tmp)
                except OSError:
                    pass
            try:
                os.remove(map_tmp)
            except OSError:
                pass
            print(
                "\nERROR: local persist failed staging tmp files after API"
                f" operations succeeded. Remote state is committed but"
                f" local map and baseline are stale. Detail: {exc}\n"
                "Run '/setup --refresh' to resync the baseline against the"
                " current remote state before the next push."
            )
            sys.exit(3)

        # Phase 3: commit all renames atomically. Meta files first, then
        # component_map.json last. os.replace is atomic on the same
        # filesystem; if a rename does fail mid-loop, the customer still
        # has a usable component_map (old or new) plus the recovery hint.
        # Track which tmps we've already committed so a partial failure
        # can clean up the leftovers (otherwise `/setup --refresh` fixes
        # the baseline but the next `/push` would re-encounter the stale
        # *.tmp siblings on disk).
        committed = 0
        try:
            for meta_full, meta_tmp in meta_tmps:
                os.replace(meta_tmp, meta_full)
                committed += 1
            os.replace(map_tmp, map_path)
        except OSError as exc:
            for _, meta_tmp in meta_tmps[committed:]:
                try:
                    os.remove(meta_tmp)
                except OSError:
                    pass
            try:
                os.remove(map_tmp)
            except OSError:
                pass
            print(
                "\nERROR: local persist failed committing tmp files after"
                f" API operations succeeded. Remote state is committed"
                f" but local map and baseline may be partially updated."
                f" Detail: {exc}\n"
                "Run '/setup --refresh' to resync the baseline against"
                " the current remote state before the next push."
            )
            sys.exit(3)

        # Phase 4: refresh baseline. Directory copy isn't atomic; failure
        # here only causes the next diff to over-report (false changes).
        try:
            if only_globs:
                update_baseline_scoped(agent_dir, only_globs)
            else:
                update_baseline(agent_dir)
        except OSError as exc:
            print(
                "\nWARNING: baseline refresh failed; component map and"
                f" remote state are in sync. Detail: {exc}\n"
                "The next /push may report stale changes; run"
                " /setup --refresh to resync."
            )
    elif errors > 0:
        print(
            f"\nBaseline NOT updated: {errors} component(s) failed. Re-run"
            " push to retry; baseline, component map, and template-config"
            " meta files will be updated only after a fully successful push."
        )

    # Summary
    print(f"\n{'=' * 50}")
    print("PUSH COMPLETE")
    print(f"{'=' * 50}")
    print(f"Success: {success}")

    # Telemetry: emit build.complete + agent.deploy with the push outcome.
    # Best-effort, synchronous flush so the events make it out before exit.
    try:
        import adk_telemetry

        _duration_ms = int((time.perf_counter() - _push_start) * 1000)
        _outcome = "failure" if errors else "success"
        _deploy_target = _resolve_deploy_target(config, env_url)
        _err_kwargs = {}
        if errors:
            _err_kwargs = {
                "error_code": "PUSH_PARTIAL_FAILURE",
                "error_category": "runtime",
                "error_message": f"{errors} component(s) failed",
            }
        adk_telemetry.emit_build_complete(
            agent_id=bot_id, adk_capability="publishing",
            outcome=_outcome, duration_ms=_duration_ms, **_err_kwargs,
        )
        adk_telemetry.emit_agent_deploy(
            agent_id=bot_id, deploy_target=_deploy_target, adk_capability="publishing",
            outcome=("server_error" if errors else "success"),
            duration_ms=_duration_ms,
            **({"error_code": "DEPLOY_PARTIAL_FAILURE", "error_category": "runtime",
                "error_message": f"{errors} component(s) failed"} if errors else {}),
        )
        adk_telemetry.flush(timeout=5)
    except Exception:  # noqa: BLE001 — telemetry must never break push
        pass

    if errors:
        print(f"Errors:  {errors}")
        sys.exit(1)
    print("")


if __name__ == "__main__":
    main()
