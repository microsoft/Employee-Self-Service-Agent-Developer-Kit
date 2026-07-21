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
    associate_ref,
    delete_record,
    query_all,
    record_exists,
    dataverse_get,
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

    The authored ``flowId`` and the created ``workflowid`` are matched
    case-insensitively: the topic carries the maker's authored-case GUID while
    the created id is whatever ``create_record`` returned (Dataverse emits the
    ``OData-EntityId`` GUID canonical/lowercase), so a case-sensitive test would
    silently skip the link. The emitted pair uses the id from
    ``created_workflow_ids`` so the ``botcomponent_workflow`` ``/$ref`` targets
    the actual record.
    """
    canonical_by_fold = {
        str(wid).casefold(): wid for wid in created_workflow_ids
    }
    links = []
    seen = set()
    for filepath, content in topic_items:
        flow_ids = [
            canonical_by_fold[fid.casefold()]
            for fid in _extract_flow_ids(content)
            if fid.casefold() in canonical_by_fold
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


def _connref_needs_create(target_logical_name, existing_rows):
    """Return whether a flow-scoped connref must be created.

    Guards connref-create idempotency. When registration is re-driven — an
    adopt-on-existing flow or an explicit ``--repair`` — the flow-scoped connref
    may already exist, and a blind create would 400 on a duplicate key. Returns
    ``False`` when ``target_logical_name`` already appears in ``existing_rows``
    (matched case-insensitively on ``connectionreferencelogicalname``).
    """
    target = (target_logical_name or "").casefold()
    for row in existing_rows or []:
        if (row.get("connectionreferencelogicalname") or "").casefold() == target:
            return False
    return True


_DUPLICATE_ERROR_MARKERS = (
    "already exists",
    "duplicate",
    "0x80040237",  # duplicate lookup / cannot insert duplicate key
    "0x80060891",  # duplicate record
)


def _is_benign_duplicate_error(exc):
    """Return whether an exception is a Dataverse already-exists/duplicate error.

    Lets a re-driven link or connref treat an already-registered record as
    success rather than a failure, so re-running registration (adopt / repair)
    reports the true state instead of a spurious "incomplete". Matches on the
    error text/code, which is stable across the API error envelope.
    """
    if exc is None:
        return False
    text = str(exc).casefold()
    return any(marker in text for marker in _DUPLICATE_ERROR_MARKERS)


def _registration_report(incomplete):
    """Compose the honest terminal signal for best-effort registration failures.

    ``incomplete`` is a list of ``{"flow", "step", "detail"}`` records, one per
    registration step (connref/link/activate) that failed for a created flow.
    Registration is best-effort so these never poison the atomic map save, but a
    flow that was created yet left non-invocable must NOT be reported as a silent
    green success. Returns ``{"lines", "exit_code", "telemetry_outcome"}``: an
    empty input is a clean success; otherwise a banner naming each flow + failed
    step, a non-zero exit code, and a ``failure`` telemetry outcome.
    """
    if not incomplete:
        return {"lines": [], "exit_code": 0, "telemetry_outcome": "success"}
    lines = [
        "WARNING: flow(s) created but NOT yet agent-invocable "
        "(registration incomplete):",
    ]
    for item in incomplete:
        lines.append(
            f"  - flow {item.get('flow')}: {item.get('step')} step failed"
            f" ({item.get('detail')})"
        )
    lines.append(
        "Complete registration by re-running: python push.py --repair"
        " (optionally pass a flow name to scope it)."
    )
    return {"lines": lines, "exit_code": 2, "telemetry_outcome": "failure"}


def _plan_repair_flows(component_map, name_filter=None):
    """Select the flows ``--repair`` re-drives from the component map.

    Workflow entries only (an entry with a ``workflowid``), with an optional
    case-insensitive filter matched against the entry's ``name``, its
    ``workflowid``, or its file path. Deterministic order. Bounded by design so
    ``--repair`` never fans out over the pre-installed pack orchestrators the way
    an unfiltered readiness scan would.
    """
    needle = (name_filter or "").casefold()
    selected = []
    for filepath, entry in (component_map or {}).items():
        wf_id = entry.get("workflowid")
        if not wf_id:
            continue
        if needle:
            haystack = " ".join([
                str(entry.get("name") or ""),
                str(wf_id),
                str(filepath),
            ]).casefold()
            if needle not in haystack:
                continue
        selected.append((filepath, wf_id))
    return sorted(selected)


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

    Intentionally corrects only the pushed payload, not the on-disk
    ``workflow.json``: push is otherwise read-only w.r.t. the maker's source, so
    rewriting their file on every push would be surprising. The source may keep
    ``kind: PowerApp``; a later ``fetch`` converges it to the server's Skills
    copy.
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


def _flow_response_kinds(clientdata):
    """List the ``kind`` of every Response action in a flow's clientdata.

    Read-only companion to ``_ensure_skills_response`` used by the readiness
    report. Returns ``[]`` on invalid JSON.
    """
    try:
        data = json.loads(clientdata)
    except (ValueError, TypeError):
        return []
    kinds = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "Response":
                kinds.append(node.get("kind"))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return kinds


def _evaluate_flow_registration(*, statecode, statuscode, modernflowtype,
                                response_kinds, connref_bound_count,
                                link_count):
    """Compose the agent-invocability checks for a created flow.

    Returns ``{"ready": bool, "checks": {name: bool}}``. Mirrors the manual
    5-step registration check: the flow must be Activated, a modern
    (CopilotStudio) flow, have all Response actions as kind:Skills, have at
    least one bound flow-scoped connection reference, and be linked to a system
    topic via botcomponent_workflow.
    """
    checks = {
        "activated": statecode == 1 and statuscode == 2,
        "modern_flow": modernflowtype == 1,
        "response_skills": (
            len(response_kinds) > 0
            and all(k == "Skills" for k in response_kinds)
        ),
        "flow_scoped_connref": connref_bound_count > 0,
        "botcomponent_workflow_link": link_count > 0,
    }
    return {"ready": all(checks.values()), "checks": checks}


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


def _register_flow(auth, env_url, schema_name, wf_id, wf_json):
    """Mint a created flow's flow-scoped connref(s) and activate it.

    Idempotent so it is safe to re-drive (adopt-on-existing create or an
    explicit ``--repair``): an already-present connref is skipped, an
    already-active flow re-PATCHes harmlessly, and a benign duplicate error is
    treated as already-registered. Best-effort — it never raises for a step
    failure; instead it returns a list of ``{"flow", "step", "detail"}`` for the
    steps that genuinely failed (connector unreachable, design connref missing,
    etc.) so the caller can surface an honest 'not yet agent-invocable' signal.
    """
    incomplete = []
    for cr in _plan_flow_connrefs(wf_json, schema_name, wf_id):
        target = cr["new_logical_name"]
        try:
            existing = _call_with_refresh(
                auth, query_all, env_url, auth.token,
                "connectionreferences", "connectionreferencelogicalname",
                filter_expr=(
                    "connectionreferencelogicalname eq "
                    f"'{target.replace(chr(39), chr(39) * 2)}'"),
            )
            if not _connref_needs_create(target, existing):
                print(f"  🔌 Connref exists: {target}")
                continue
            design = cr["design_logical_name"].replace("'", "''")
            design_rows = _call_with_refresh(
                auth, query_all, env_url, auth.token,
                "connectionreferences",
                "connectionid,connectorid,connectionparametersetconfig",
                filter_expr=f"connectionreferencelogicalname eq '{design}'",
            )
            if not design_rows:
                print(
                    f"  ! No design connref '{cr['design_logical_name']}' "
                    f"to mirror; flow {wf_id} left unconnected"
                )
                incomplete.append({"flow": wf_id, "step": "connref",
                                   "detail": "design connref not found"})
                continue
            design_row = design_rows[0]
            # The shared design connref may lack the parameter-set config; pull
            # it from a sibling connref on the same connection.
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
            payload = _flow_connref_payload(target, mirror)
            _call_with_refresh(
                auth, create_record, env_url, auth.token,
                "connectionreferences", payload)
            print(f"  🔌 Connref: {target}")
        except Exception as e:  # noqa: BLE001 — best-effort registration
            if _is_benign_duplicate_error(e):
                print(f"  🔌 Connref exists: {target}")
            else:
                print(
                    f"  ! Connref failed for flow {wf_id} "
                    f"({cr['connector_api_name']}): {e}"
                )
                incomplete.append({"flow": wf_id, "step": "connref",
                                   "detail": str(e)})
    try:
        _call_with_refresh(
            auth, update_record, env_url, auth.token, "workflows", wf_id,
            {"statecode": 1, "statuscode": 2})
        # The PATCH was accepted; `validate.py` re-reads statecode/statuscode to
        # confirm the flow held activation (a flow can revert to Draft if a later
        # connector-schema check fails), so this line reports the request, not a
        # verified end state.
        print(f"  ▶ Activation requested for flow {wf_id}")
    except Exception as e:  # noqa: BLE001 — best-effort registration
        print(
            f"  ! Activation failed for flow {wf_id} "
            f"(run: python push.py --repair once the connector is reachable):"
            f" {e}"
        )
        incomplete.append({"flow": wf_id, "step": "activate", "detail": str(e)})
    return incomplete


def _run_repair(env_url, schema_name, agent_dir, component_map, name_filter,
                dry_run=False):
    """Re-drive registration for already-created flows (the ``--repair`` path).

    Closes the gap where a flow was created but a best-effort registration step
    (connref/link/activation) failed: because the flow is already in the map, a
    plain re-push sees no diff and never re-enters registration. ``--repair``
    re-runs the idempotent link + connref + activation for the selected mapped
    flow(s). Isolated from the atomic map save — link/connref/activation live in
    Dataverse, not the component map, so no local state changes. Returns the
    process exit code (0 all-registered, non-zero if any step is still failing).
    """
    flows = _plan_repair_flows(component_map, name_filter)
    # Scope to maker-authored flows only: a flow whose workflow.json is present
    # on disk. This keeps --repair from re-driving registration (and toggling
    # activation) on solution/pack-installed orchestrators that happen to be in
    # the component map but register their connection differently.
    flows = [
        (fp, wf_id) for fp, wf_id in flows
        if os.path.exists(os.path.join(agent_dir, fp))
    ]
    if not flows:
        scope = f" matching '{name_filter}'" if name_filter else ""
        print(f"No maker-authored flows{scope} to repair.")
        return 0

    if dry_run:
        print("(Dry run) --repair would re-drive registration for:")
        for filepath, wf_id in flows:
            print(f"  - {wf_id} ({filepath})")
        return 0

    print("\nAuthenticating to Dataverse...")
    auth = _AuthHolder(env_url)
    auth.acquire()
    print("Authenticated.\n")

    incomplete = []
    target_ids = {wf_id for _, wf_id in flows}

    # Re-drive topic -> flow links for the selected flows, reconstructing the
    # topic/flow pairing from the system topics on disk (the same derivation the
    # normal push uses, minus the "created this run" scoping).
    topic_items = []
    for filepath in component_map:
        if classify_path(filepath) != "botcomponent":
            continue
        try:
            with open(os.path.join(agent_dir, filepath), "r",
                      encoding="utf-8") as fh:
                topic_items.append((filepath, fh.read()))
        except OSError:
            continue

    def _resolve_botcomponentid(fp):
        return (component_map.get(fp) or {}).get("botcomponentid")

    for bc_id, wf_id in _plan_topic_workflow_links(
        topic_items, target_ids, _resolve_botcomponentid
    ):
        try:
            _call_with_refresh(
                auth, associate_ref, env_url, auth.token,
                "botcomponents", bc_id, "botcomponent_workflow",
                "workflows", wf_id,
            )
            print(f"  🔗 Linked: topic {bc_id} → flow {wf_id}")
        except Exception as e:  # noqa: BLE001
            if _is_benign_duplicate_error(e):
                print(f"  🔗 Link already present: topic {bc_id} → flow {wf_id}")
            else:
                print(f"  ! Link failed: topic {bc_id} → flow {wf_id}: {e}")
                incomplete.append({"flow": wf_id, "step": "link",
                                   "detail": str(e)})

    for filepath, wf_id in flows:
        try:
            with open(os.path.join(agent_dir, filepath), "r",
                      encoding="utf-8") as fh:
                wf_json = json.loads(fh.read())
        except (OSError, ValueError) as e:
            print(f"  ! Could not read {filepath}: {e}")
            wf_json = {}
        print(f"Repairing flow {wf_id} ({filepath})...")
        incomplete.extend(
            _register_flow(auth, env_url, schema_name, wf_id, wf_json))

    report = _registration_report(incomplete)
    for line in report["lines"]:
        print(line)
    if not incomplete:
        print(f"\nRepair complete: {len(flows)} flow(s) registered.")
    return report["exit_code"]


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
    repair_mode = "--repair" in sys.argv
    repair_name = None
    if repair_mode:
        _idx = sys.argv.index("--repair")
        if _idx + 1 < len(sys.argv) and not sys.argv[_idx + 1].startswith("-"):
            repair_name = sys.argv[_idx + 1]
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

    if repair_mode:
        sys.exit(_run_repair(
            env_url, schema_name, agent_dir, component_map, repair_name,
            dry_run=dry_run))

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
            except Exception:  # noqa: BLE001 — probe failed; proceed but warn
                # The stale-id self-heal (adopt/recreate) only runs on a clean
                # 404. A transient probe failure (5xx/network) is treated as
                # "assume present" and falls through to a blind PATCH; surface it
                # so an opaque 400 that follows is traceable to the skipped probe.
                print(f"  ! Existence probe failed for {filepath}; assuming the "
                      f"mapped record is present and updating in place.")
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
            # No stale-id self-heal here (unlike botcomponents above): workflows
            # are keyed by the maker's preserved client GUID, which is stable and
            # not subject to the out-of-band delete+recreate churn that motivated
            # the botcomponent probe. A stale id would surface an opaque 400 via
            # the except below; extend the record_exists pattern here if that is
            # ever observed in practice.
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
            client_wf_id = record_data.get("workflowid")
            try:
                adopted_id = None
                if client_wf_id:
                    # Idempotent create: a prior push may have committed this
                    # flow row (the client workflowId is preserved as the PK)
                    # but failed to save the component map — a blind re-create
                    # with the same id would 400 on a duplicate key and wedge the
                    # maker. Probe first; on a hit, adopt the existing row
                    # (best-effort definition refresh) instead of re-creating.
                    try:
                        if _call_with_refresh(
                                auth, record_exists, env_url, auth.token,
                                "workflows", client_wf_id, "workflowid"):
                            adopted_id = client_wf_id
                    except Exception:  # noqa: BLE001 — probe failed; try create
                        adopted_id = None
                if adopted_id:
                    try:
                        _call_with_refresh(
                            auth, update_record, env_url, auth.token,
                            "workflows", adopted_id, {"clientdata": content})
                    except Exception as ue:  # noqa: BLE001
                        print(f"  ! Adopted flow {adopted_id} but could not "
                              f"refresh its definition: {ue}")
                    new_id = adopted_id
                    print(f"  ↻ Adopted existing flow: {filepath} "
                          f"(ID: {new_id})")
                else:
                    new_id = _call_with_refresh(auth, create_record,
                                                env_url, auth.token,
                                                "workflows", record_data)
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

    # Best-effort registration steps (link + connref + activation) append here
    # instead of incrementing `errors`, so a transient registration failure
    # never poisons the atomic map save (which would discard the created flow's
    # map entry and force a duplicate-key re-create next push). The list drives
    # an honest 'not yet agent-invocable' terminal signal + a `--repair` hint.
    registration_incomplete = []

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
                if _is_benign_duplicate_error(e):
                    print(f"  🔗 Link already present: topic {bc_id} → "
                          f"flow {wf_id}")
                else:
                    # Best-effort like connref/activation: a link failure must
                    # not increment `errors`, else the atomic gate discards the
                    # created flow's map entry and the next push re-creates it
                    # with the same client id -> duplicate-key 400.
                    print(f"  ! Link failed: topic {bc_id} → flow {wf_id}: {e}")
                    registration_incomplete.append(
                        {"flow": wf_id, "step": "link", "detail": str(e)})

    # Register each newly-created flow: mint its flow-scoped connection
    # reference(s) and activate it. A flow created via the Web API is Draft with
    # no runtime connection; Copilot Studio resolves the connection through a
    # connref named `{schema}.{workflowid}.{connector}`, mirrored from the design
    # connref the flow's workflow.json names. Activation triggers live
    # connector-schema validation, so it runs last.
    #
    # BEST-EFFORT (see `registration_incomplete` above): the flow record and its
    # id are already persisted this run, so failing the push here would block the
    # atomic map save and force a duplicate create on the next push (same client
    # workflowid). `_register_flow` is idempotent, so `--repair` (or a later
    # edit+push) can finish registration without corrupting local state.
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
        registration_incomplete.extend(
            _register_flow(auth, env_url, schema_name, wf_id, wf_json))

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

    # Honest terminal signal: best-effort registration failures do not increment
    # `errors` (so the atomic map save is preserved), but a flow that was created
    # yet left non-invocable must NOT be reported as a silent green success.
    _reg = _registration_report(registration_incomplete)
    if _reg["lines"]:
        print("")
        for _line in _reg["lines"]:
            print(_line)

    # Telemetry: emit build.complete + agent.deploy with the push outcome.
    # Best-effort, synchronous flush so the events make it out before exit.
    try:
        import adk_telemetry

        _duration_ms = int((time.perf_counter() - _push_start) * 1000)
        _failed = bool(errors) or bool(registration_incomplete)
        _outcome = "failure" if _failed else "success"
        _deploy_target = _resolve_deploy_target(config, env_url)
        if errors:
            _error_message = f"{errors} component(s) failed"
        elif registration_incomplete:
            _error_message = (
                f"{len(registration_incomplete)} flow registration step(s) "
                "incomplete"
            )
        else:
            _error_message = ""
        _err_kwargs = {}
        if _failed:
            _err_kwargs = {
                "error_code": ("PUSH_PARTIAL_FAILURE" if errors
                               else "REGISTRATION_INCOMPLETE"),
                "error_category": "runtime",
                "error_message": _error_message,
            }
        adk_telemetry.emit_build_complete(
            agent_id=bot_id, adk_capability="publishing",
            outcome=_outcome, duration_ms=_duration_ms, **_err_kwargs,
        )
        adk_telemetry.emit_agent_deploy(
            agent_id=bot_id, deploy_target=_deploy_target, adk_capability="publishing",
            outcome=("server_error" if _failed else "success"),
            duration_ms=_duration_ms,
            **({"error_code": ("DEPLOY_PARTIAL_FAILURE" if errors
                               else "REGISTRATION_INCOMPLETE"),
                "error_category": "runtime",
                "error_message": _error_message} if _failed else {}),
        )
        adk_telemetry.flush(timeout=5)
    except Exception:  # noqa: BLE001 — telemetry must never break push
        pass

    if errors:
        print(f"Errors:  {errors}")
        sys.exit(1)
    if _reg["exit_code"]:
        sys.exit(_reg["exit_code"])
    print("")


if __name__ == "__main__":
    main()
