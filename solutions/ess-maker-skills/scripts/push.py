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
    associate_ref,
    delete_record,
    query_all,
    record_exists,
    load_config,
    AuthExpiredError,
)

EXCLUDE_DIRS = {".baseline", ".checkpoints"}
EXCLUDE_FILES = {"snapshot.md", "_meta.json"}


def _ensure_utf8_stdout(stream=None):
    """Reconfigure a text stream to UTF-8 so the emoji status glyphs this
    script prints (✅/❌/➕/✏️) don't raise ``UnicodeEncodeError`` and abort
    the push on a legacy Windows console (cp1252). Mirrors the guard the
    sibling CLI scripts (scan_config, merge_findings, check_isv_coverage, …)
    apply at import.

    No-op when the stream is already UTF-8, exposes no ``encoding``, or has no
    ``reconfigure`` (e.g. a captured buffer). Returns ``True`` iff a
    reconfigure was applied.
    """
    if stream is None:
        stream = sys.stdout
    encoding = getattr(stream, "encoding", None)
    if (
        encoding
        and encoding.lower() != "utf-8"
        and hasattr(stream, "reconfigure")
    ):
        stream.reconfigure(encoding="utf-8", errors="replace")
        return True
    return False


_ensure_utf8_stdout()


def _workflow_create_payload(parsed_wf_meta, *, name, clientdata, description):
    """Build the Dataverse ``workflows`` create payload for an agent flow.

    A Copilot Studio agent flow must be ``modernflowtype=1``
    (CopilotStudioFlow); creating it as the default 0 (PowerAutomateFlow)
    is why the agent later can't resolve it (``flowNotFound``). The modern-flow
    attributes (category=5 Modern Flow, type=1 Definition, scope=4, etc.) each
    default here and are overridable from the flow's companion ``metadata.yml``.
    """
    meta = parsed_wf_meta or {}
    payload = {
        "name": name,
        "clientdata": clientdata,
        "description": description,
        "category": meta.get("category", 5),        # 5 = Modern Flow
        "type": meta.get("type", 1),                 # 1 = Definition
        "primaryentity": meta.get("primaryentity", "none"),
        "mode": meta.get("mode", 0),
        "scope": meta.get("scope", 4),
        "modernflowtype": meta.get("modernflowtype", 1),  # 1 = CopilotStudioFlow
    }
    # Preserve the maker's client-generated GUID as the Dataverse primary key
    # so it stays equal to the topic's InvokeFlowAction flowId. Dropping it
    # (letting Dataverse assign a new GUID) desyncs the two → the agent can't
    # resolve the flow (flowNotFound) and the botcomponent_workflow link is no
    # longer derivable from the authored clientdata.
    client_workflow_id = meta.get("workflowId")
    if client_workflow_id:
        payload["workflowid"] = str(client_workflow_id)
    return payload


def _extract_flow_ids(content):
    """Return the flowId of every ``InvokeFlowAction`` in a topic's clientdata.

    A system topic invokes a flow via an ``InvokeFlowAction`` node whose
    ``flowId`` is the client-generated GUID (kept equal to the workflow's
    Dataverse ``workflowid``). These are the workflows the topic's botcomponent
    must be ``botcomponent_workflow``-linked to. Order-preserving and
    de-duplicated; returns ``[]`` on unparseable YAML.
    """
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return []

    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("kind") == "InvokeFlowAction" and node.get("flowId"):
                flow_id = str(node["flowId"])
                if flow_id not in found:
                    found.append(flow_id)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return found


def _plan_topic_workflow_links(topic_items, created_workflow_ids,
                               resolve_botcomponentid):
    """Plan the ``botcomponent_workflow`` links to create after a push.

    ``topic_items`` is an iterable of ``(filepath, clientdata)`` for the system
    topics pushed this run. ``created_workflow_ids`` is the set of workflow ids
    created in this push. ``resolve_botcomponentid`` maps a topic filepath to
    its Dataverse ``botcomponentid``. Returns an ordered, de-duplicated list of
    ``(botcomponentid, workflowid)`` pairs — one per (topic, invoked flow) —
    restricted to flows created this run.

    Scoping to newly-created flows targets the new-flow-registration gap: a
    fresh flow has no existing link (no duplicate-link risk) and a failed link
    is a real error; an unchanged flow is not re-linked on a subsequent push.
    """
    links = []
    seen = set()
    for filepath, content in topic_items:
        flow_ids = [
            fid for fid in _extract_flow_ids(content)
            if fid in created_workflow_ids
        ]
        if not flow_ids:
            continue
        botcomponentid = resolve_botcomponentid(filepath)
        if not botcomponentid:
            continue
        for flow_id in flow_ids:
            pair = (botcomponentid, flow_id)
            if pair not in seen:
                seen.add(pair)
                links.append(pair)
    return links


def _plan_flow_connrefs(workflow_json, agent_schema, workflowid):
    """Plan flow-scoped connection references for a created flow.

    Copilot Studio resolves an agent flow's connection through a connref named
    ``{agent_schema}.{workflowid}.{connector}``. The flow's ``workflow.json``
    only names a shared *design* connref (under
    ``properties.connectionReferences[*].connection.connectionReferenceLogicalName``),
    so push must mint the flow-scoped one by mirroring that design connref.

    Returns a list of dicts (one per connector that names a design connref):
    ``{connector_api_name, design_logical_name, new_logical_name}``.
    """
    try:
        conn_refs = workflow_json["properties"]["connectionReferences"]
    except (KeyError, TypeError):
        return []
    if not isinstance(conn_refs, dict):
        return []

    plan = []
    for key, entry in conn_refs.items():
        if not isinstance(entry, dict):
            continue
        connector = (entry.get("api") or {}).get("name") or key
        design_logical = (entry.get("connection") or {}).get(
            "connectionReferenceLogicalName"
        )
        if not design_logical:
            continue
        plan.append({
            "connector_api_name": connector,
            "design_logical_name": design_logical,
            "new_logical_name": f"{agent_schema}.{workflowid}.{connector}",
        })
    return plan


def _flow_connref_payload(new_logical_name, mirror):
    """Build the ``connectionreferences`` create body for a flow-scoped connref.

    Mirrors a design connref record (``mirror``): same connector, connection,
    and parameter-set config, under ``new_logical_name``. The parameter-set
    config is copied only when present on the mirror.
    """
    payload = {
        "connectionreferencelogicalname": new_logical_name,
        "connectionreferencedisplayname": new_logical_name,
        "connectorid": mirror.get("connectorid"),
        "connectionid": mirror.get("connectionid"),
    }
    param_config = mirror.get("connectionparametersetconfig")
    if param_config:
        payload["connectionparametersetconfig"] = param_config
    return payload


def _build_connref_mirror(design_row, sibling_rows):
    """Derive the connection fields for a new flow-scoped connref.

    ``design_row`` is the design connref the flow's workflow.json names; it
    supplies the ``connectionid`` and ``connectorid``. Its
    ``connectionparametersetconfig`` may be empty (the shared ``cr.*`` connref
    has none), in which case the config is taken from a sibling connref bound
    to the SAME connection — matching the known-good flow-scoped connref shape.
    Returns ``None`` if there is no design row.
    """
    if not design_row:
        return None
    conn_id = design_row.get("connectionid")
    param = design_row.get("connectionparametersetconfig")
    if not param:
        for row in sibling_rows or []:
            if (row.get("connectionid") == conn_id
                    and row.get("connectionparametersetconfig")):
                param = row["connectionparametersetconfig"]
                break
    return {
        "connectionid": conn_id,
        "connectorid": design_row.get("connectorid"),
        "connectionparametersetconfig": param,
    }


def _flow_connref_delete_filter(agent_schema, workflowid):
    """OData ``$filter`` selecting a flow's flow-scoped connection references.

    push mints connrefs named ``{agent_schema}.{workflowid}.{connector}`` on
    flow-create; this matches all of them for a workflow so they can be cleaned
    up when the flow is deleted (otherwise they orphan).
    """
    prefix = f"{agent_schema}.{workflowid}.".replace("'", "''")
    return f"startswith(connectionreferencelogicalname,'{prefix}')"


def _schemaname_looks_kebab(schemaname):
    """Return True if a schemaname's final segment is hyphenated (kebab).

    A system topic's schemaname must be PascalCase to match the caller's
    ``BeginDialog`` reference. A hyphen in the last segment means the topic
    file was kebab-named (e.g. a fetched file pushed as new) and the reference
    will dangle. Only hyphenation is the tell — a single lowercase word is a
    valid schemaname.
    """
    segment = schemaname.rsplit(".", 1)[-1]
    return "-" in segment


def _ensure_skills_response(clientdata):
    """Coerce every Response action in a flow's clientdata to kind:Skills.

    A Copilot Studio agent flow (Skills trigger) requires its Response actions
    ("Respond to Copilot") to be ``kind: Skills``; a ``kind: PowerApp`` (or
    missing kind) yields an empty output picker and InvalidBindingInvokeAction
    at publish. push creates only agent flows (modernflowtype=1), so this is a
    safe, deterministic correction. Returns ``(clientdata, num_fixed)``; the
    original string is returned unchanged when nothing needed fixing.
    """
    try:
        data = json.loads(clientdata)
    except (ValueError, TypeError):
        return clientdata, 0

    fixed = 0

    def walk(node):
        nonlocal fixed
        if isinstance(node, dict):
            if node.get("type") == "Response" and node.get("kind") != "Skills":
                node["kind"] = "Skills"
                fixed += 1
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    if fixed == 0:
        return clientdata, 0
    return json.dumps(data), fixed


def _botcomponent_recreate_payload(entry, content, bot_id):
    """Rebuild the ``botcomponents`` create body for a stale-id self-heal.

    When a botcomponent's mapped record was deleted out-of-band and no
    same-``schemaname`` replacement exists to adopt, push recreates it. The
    stable identity (``schemaname``, ``componenttype``, ``name``) comes from the
    component-map ``entry``; the topic body is the current file ``content``. The
    component is (re)parented to the bot. Returns ``None`` if the entry lacks a
    ``schemaname`` (can't safely recreate without preserving identity).
    """
    schema = entry.get("schemaname")
    if not schema:
        return None
    payload = {
        "data": content,
        "name": entry.get("name") or schema,
        "schemaname": schema,
        "parentbotid@odata.bind": f"/bots({bot_id})",
    }
    if entry.get("componenttype") is not None:
        payload["componenttype"] = entry["componenttype"]
    if entry.get("parentbotcomponentid"):
        payload["ParentBotComponentId@odata.bind"] = \
            f"/botcomponents({entry['parentbotcomponentid']})"
    return payload


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


def main():
    dry_run = "--dry-run" in sys.argv
    auto_yes = "--yes" in sys.argv
    force_delete = "--force-delete" in sys.argv

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
            # Self-heal a stale map id. If the mapped record was deleted +
            # recreated out-of-band (ADK/canvas/manual churn), the map holds a
            # dead id and a blind PATCH returns an opaque 400. Detect it with a
            # clean GET; on a miss, adopt the current record by its stable
            # schemaname (the recreate-with-new-id case — avoids a duplicate),
            # else recreate it fresh. The repaired/new id is staged into the
            # atomic gate via pending_creates.
            target_id = entry["botcomponentid"]
            healed = None
            try:
                exists = _call_with_refresh(
                    auth, record_exists, env_url, auth.token,
                    "botcomponents", target_id, "botcomponentid")
            except Exception:  # noqa: BLE001 — treat probe failure as "assume present"
                exists = True
            if not exists:
                schema = entry.get("schemaname")
                adopted = None
                if schema:
                    try:
                        rows = _call_with_refresh(
                            auth, query_all, env_url, auth.token,
                            "botcomponents", "botcomponentid",
                            filter_expr=(
                                f"schemaname eq '{schema.replace(chr(39), chr(39)*2)}'"
                            ),
                        )
                        if rows:
                            adopted = rows[0]["botcomponentid"]
                    except Exception as e:  # noqa: BLE001
                        print(f"  ! schemaname lookup failed for {filepath}: {e}")
                if adopted:
                    target_id = adopted
                    healed = dict(entry, botcomponentid=adopted)
                    print(f"  ↻ Adopted recreated component {filepath} "
                          f"(id {adopted})")
                else:
                    payload = _botcomponent_recreate_payload(
                        entry, content, bot_id)
                    if payload is None:
                        print(f"  ❌ Failed: {filepath}: mapped component is gone "
                              f"and cannot be recreated (no schemaname in map). "
                              f"Re-run /setup.")
                        errors += 1
                        continue
                    try:
                        new_id = _call_with_refresh(
                            auth, create_record, env_url, auth.token,
                            "botcomponents", payload)
                        print(f"  ♻ Recreated: {filepath} (ID: {new_id})")
                        pending_creates[filepath] = dict(
                            entry, botcomponentid=new_id)
                        success += 1
                    except Exception as e:  # noqa: BLE001
                        print(f"  ❌ Failed to recreate {filepath}: {e}")
                        errors += 1
                    continue  # recreate carries current content; no PATCH
            try:
                _call_with_refresh(auth, update_record,
                                   env_url, auth.token, "botcomponents",
                                   target_id, {"data": content})
                print(f"  ✅ Updated: {filepath}")
                if healed is not None:
                    pending_creates[filepath] = healed
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
            content, _skills_fixed = _ensure_skills_response(content)
            if _skills_fixed:
                print(f"  ⚙ {filepath}: set {_skills_fixed} Response action(s) "
                      f"to kind:Skills for agent-flow compatibility")
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
            if comp_type == 9 and _schemaname_looks_kebab(schema):
                print(
                    f"  ⚠ {filepath}: created with kebab schemaname "
                    f"'{schema.rsplit('.', 1)[-1]}'. Topics are referenced by "
                    f"PascalCase schemaname in BeginDialog — if another topic "
                    f"calls this one, that reference will dangle. Rename the "
                    f"file to PascalCase (e.g. ServiceNowITSMSystemGetOptions"
                    f".mcs.yml) and re-push. schemaname is immutable once set."
                )
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
            parsed_wf_meta = {}
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
            content, _skills_fixed = _ensure_skills_response(content)
            if _skills_fixed:
                print(f"  ⚙ {filepath}: set {_skills_fixed} Response action(s) "
                      f"to kind:Skills for agent-flow compatibility")
            record_data = _workflow_create_payload(
                parsed_wf_meta,
                name=wf_name,
                clientdata=content,
                description=wf_desc,
            )
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
                continue
            # Symmetric cleanup: remove the flow-scoped connection reference(s)
            # push minted for this flow on create, so they don't orphan. Runs
            # after the flow delete (dependency ordering) and is best-effort —
            # a connref still pinned by an unresolved dependency warns rather
            # than failing the delete.
            try:
                orphans = _call_with_refresh(
                    auth, query_all, env_url, auth.token,
                    "connectionreferences",
                    "connectionreferenceid,connectionreferencelogicalname",
                    filter_expr=_flow_connref_delete_filter(
                        schema_name, entry["workflowid"]),
                )
                for row in orphans:
                    try:
                        _call_with_refresh(
                            auth, delete_record, env_url, auth.token,
                            "connectionreferences",
                            row["connectionreferenceid"])
                        print(f"  🔌 Removed connref: "
                              f"{row['connectionreferencelogicalname']}")
                    except Exception as e:
                        print(f"  ! Could not remove connref "
                              f"{row['connectionreferencelogicalname']}: {e}")
            except Exception as e:
                print(f"  ! Connref cleanup skipped for "
                      f"{entry['workflowid']}: {e}")

    # Wire newly-created flows to the system topics that invoke them. A flow
    # created via the Web API lands as an orphan `workflows` record; Copilot
    # Studio cannot resolve it as one of the agent's flows until a
    # `botcomponent_workflow` association ties the invoking system topic to the
    # workflow (missing link = CloudFlow-not-found at publish/runtime). Scoped
    # to flows created in THIS push, and relies on the client `workflowId`
    # being preserved on create so it equals the topic's InvokeFlowAction
    # flowId.
    created_workflow_ids = {
        entry["workflowid"]
        for entry in pending_creates.values()
        if entry.get("entity_set") == "workflows" and entry.get("workflowid")
    }
    if created_workflow_ids:
        def _resolve_botcomponentid(fp):
            entry = pending_creates.get(fp) or component_map.get(fp) or {}
            return entry.get("botcomponentid")

        topic_items = [
            (fp, working_files[fp])
            for fp in changed + new
            if classify_path(fp) == "botcomponent" and fp in working_files
        ]
        for bc_id, wf_id in _plan_topic_workflow_links(
            topic_items, created_workflow_ids, _resolve_botcomponentid
        ):
            try:
                _call_with_refresh(
                    auth, associate_ref, env_url, auth.token,
                    "botcomponents", bc_id, "botcomponent_workflow",
                    "workflows", wf_id,
                )
                print(f"  🔗 Linked: topic {bc_id} → flow {wf_id}")
                success += 1
            except Exception as e:
                print(f"  ❌ Failed to link topic {bc_id} → flow {wf_id}: {e}")
                errors += 1

    # Register each newly-created flow: mint its flow-scoped connection
    # reference(s) and activate it. A flow created via the Web API is Draft with
    # no runtime connection; Copilot Studio resolves the connection through a
    # connref named `{schema}.{workflowid}.{connector}`, mirrored from the design
    # connref the flow's workflow.json names. Activation triggers live
    # connector-schema validation, so it runs last.
    #
    # Both steps are BEST-EFFORT (warn, never increment `errors`): the flow
    # record and its id are already persisted this run, so failing the push here
    # would block the atomic map save and cause a duplicate create on the next
    # push (same client workflowid). A warning lets the maker finish/retry
    # registration without corrupting local state.
    created_flows = [
        (fp, entry["workflowid"])
        for fp, entry in pending_creates.items()
        if entry.get("entity_set") == "workflows" and entry.get("workflowid")
    ]
    for fp, wf_id in created_flows:
        try:
            wf_json = json.loads(working_files[fp])
        except (KeyError, ValueError):
            wf_json = {}
        for cr in _plan_flow_connrefs(wf_json, schema_name, wf_id):
            try:
                design = cr["design_logical_name"].replace("'", "''")
                design_rows = _call_with_refresh(
                    auth, query_all, env_url, auth.token,
                    "connectionreferences",
                    "connectionid,connectorid,connectionparametersetconfig",
                    filter_expr=(
                        f"connectionreferencelogicalname eq '{design}'"
                    ),
                )
                if not design_rows:
                    print(
                        f"  ! No design connref '{cr['design_logical_name']}' "
                        f"to mirror; flow {wf_id} left unconnected"
                    )
                    continue
                design_row = design_rows[0]
                # The shared design connref may lack the parameter-set config;
                # pull it from a sibling connref on the same connection.
                sibling_rows = []
                if not design_row.get("connectionparametersetconfig"):
                    conn_id = (design_row.get("connectionid") or "").replace(
                        "'", "''")
                    if conn_id:
                        sibling_rows = _call_with_refresh(
                            auth, query_all, env_url, auth.token,
                            "connectionreferences",
                            "connectionid,connectionparametersetconfig",
                            filter_expr=f"connectionid eq '{conn_id}'",
                        )
                mirror = _build_connref_mirror(design_row, sibling_rows)
                payload = _flow_connref_payload(
                    cr["new_logical_name"], mirror)
                _call_with_refresh(
                    auth, create_record, env_url, auth.token,
                    "connectionreferences", payload)
                print(f"  🔌 Connref: {cr['new_logical_name']}")
            except Exception as e:
                print(
                    f"  ! Connref failed for flow {wf_id} "
                    f"({cr['connector_api_name']}): {e}"
                )
        try:
            _call_with_refresh(
                auth, update_record, env_url, auth.token, "workflows", wf_id,
                {"statecode": 1, "statuscode": 2})
            print(f"  ▶ Activated flow {wf_id}")
        except Exception as e:
            print(
                f"  ! Activation failed for flow {wf_id} "
                f"(activate manually or re-run once the connector is reachable):"
                f" {e}"
            )

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
