# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit - Setup Script

One-shot script that handles everything after agent discovery:
  1. Derives agent slug from display name
  2. Extracts components from Dataverse JSON export to local files
  3. Generates snapshot.md with categorized topic/variable inventory
  4. Writes .local/config.json with setup = "complete"
  5. Cleans up temp files
  6. Prints a summary the agent shows to the user

Usage:
    python scripts/setup.py \
        --url https://org.crm.dynamics.com \
        --bot-id abc-123-def \
        --name "Employee Self-Service IT" \
        --schema msdyn_ESSAgent \
        --managed \
        --components workspace/agents/components.json \
        [--template-configs workspace/agents/template-configs.json]

Called by the onboarding skill Step 3. The agent:
  1. Queries Dataverse for components and template configs
  2. Saves the JSON responses to temp files
  3. Runs this script with the agent details as arguments
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date# Remove the import above

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TYPE_MAP = {
    9:  ("topics", ".mcs.yml"),
    12: ("variables", ".mcs.yml"),
    15: (None, "agent.mcs.yml"),
    18: (None, "settings.mcs.yml"),
    16: ("knowledge", ".mcs.yml"),
    14: ("attachments", ".mcs.yml"),
    19: ("evaluations", ".mcs.yml"),
}

CATEGORY_RULES = [
    ("ServiceNow", "ServiceNow"),
    ("Workday", "Workday"),
    ("ADP", "ADP"),
    ("[System]", "System"),
    ("Conversation Start", "System"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(name):
    """Convert agent display name to a folder-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def friendly_filename(name, schemaname):
    """Derive a short, readable filename from the friendly name or schema.

    Prefers the friendly name if available, otherwise extracts the last
    segment of the schema name (after the last dot).
    """
    raw = name if name else schemaname.rsplit(".", 1)[-1]
    # Strip common prefixes like [System] - , [Example] -
    raw = re.sub(r"^\[.*?\]\s*[-–—]\s*", "", raw)
    # Convert underscores to hyphens, then to kebab-case
    slug = raw.strip().replace("_", "-")
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-").lower()
    return slug or schemaname.rsplit(".", 1)[-1].lower()


def categorize_topic(name):
    """Derive category from topic name using simple prefix/substring rules."""
    for pattern, category in CATEGORY_RULES:
        if pattern in name:
            return category
    return "General"


def load_json(filepath):
    """Load JSON, handling both bare arrays and wrapper objects."""
    with open(filepath, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("value", "records", "results"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return [data]
    return []


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def extract_components(components, output_dir):
    """Write each component's data to the correct subfolder. Returns stats."""
    os.makedirs(output_dir, exist_ok=True)

    topics = []
    variables = []
    evaluations = []  # type-19 evaluation test sets and cases
    other_items = []
    component_map = {}  # relative_path -> {botcomponentid, schemaname, ...}
    topic_data = {}     # schemaname -> data blob (for flow cross-reference)
    written = 0
    skipped = 0

    for comp in components:
        data = comp.get("data")
        if not data:
            skipped += 1
            continue

        ctype = comp.get("componenttype")
        schemaname = comp.get("schemaname", "unknown")
        name = comp.get("name", schemaname)
        botcomponentid = comp.get("botcomponentid")

        mapping = TYPE_MAP.get(ctype)
        if mapping is None:
            subfolder, filename = "other", f"{friendly_filename(name, schemaname)}.mcs.yml"
        else:
            subfolder, ext = mapping
            if subfolder is None:
                # Singleton files like agent.mcs.yml / settings.mcs.yml
                subfolder, filename = "", ext
            else:
                filename = f"{friendly_filename(name, schemaname)}{ext}"

        if subfolder:
            folder = os.path.join(output_dir, subfolder)
            os.makedirs(folder, exist_ok=True)
            filepath = os.path.join(folder, filename)
            relative_path = f"{subfolder}/{filename}"
        else:
            filepath = os.path.join(output_dir, filename)
            relative_path = filename

        content = data.replace("\r\n", "\n")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        written += 1

        # Track component mapping for push-back capability
        map_entry = {
            "botcomponentid": botcomponentid,
            "schemaname": schemaname,
            "componenttype": ctype,
            "name": name,
        }
        # Store parent link for evaluation test cases (type 19)
        parent_id = comp.get("parentbotcomponentid")
        if parent_id:
            map_entry["parentbotcomponentid"] = parent_id
        component_map[relative_path] = map_entry

        if ctype == 9:
            topics.append({"name": name, "schema": schemaname,
                           "category": categorize_topic(name)})
            topic_data[schemaname] = data
        elif ctype == 12:
            variables.append({"name": name, "schema": schemaname})
        elif ctype == 19:
            evaluations.append({"name": name, "schema": schemaname,
                                "parentbotcomponentid": comp.get("parentbotcomponentid")})
        else:
            other_items.append({"name": name, "schema": schemaname,
                                "type": ctype})

    return {
        "written": written,
        "skipped": skipped,
        "topics": topics,
        "variables": variables,
        "evaluations": evaluations,
        "other": other_items,
        "component_map": component_map,
        "_topic_data": topic_data,
    }


def extract_template_configs(template_configs, output_dir):
    """Write each template config to a content file + companion .meta.json.

    Content goes to template-configs/{slug}.json (or .xml if XML).
    Metadata goes to template-configs/{slug}.meta.json.
    Returns stats dict with component_map entries.
    """
    tc_dir = os.path.join(output_dir, "template-configs")
    os.makedirs(tc_dir, exist_ok=True)

    component_map = {}
    written = 0

    for tc in template_configs:
        uname = tc.get("msdyn_uniquename", "") or tc.get("msdyn_name", "")
        if not uname:
            continue

        slug = friendly_filename(uname, uname)
        value = tc.get("msdyn_value", "") or ""

        # Detect content type
        is_xml = value.lstrip().startswith("<")
        ext = ".xml" if is_xml else ".json"
        content_filename = f"{slug}{ext}"
        meta_filename = f"{slug}.meta.json"

        # Write content file
        content_path = os.path.join(tc_dir, content_filename)
        content = value.replace("\r\n", "\n")

        # Pretty-print JSON content if possible
        if not is_xml and content.strip():
            try:
                parsed = json.loads(content)
                content = json.dumps(parsed, indent=2)
            except (json.JSONDecodeError, ValueError):
                pass

        with open(content_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Write metadata file
        meta = {
            "msdyn_name": tc.get("msdyn_name", ""),
            "msdyn_uniquename": tc.get("msdyn_uniquename", ""),
            "msdyn_employeeselfservicetemplateconfigid": tc.get(
                "msdyn_employeeselfservicetemplateconfigid", ""),
            "msdyn_description": tc.get("msdyn_description", ""),
            "statecode": tc.get("statecode", 0),
            "ismanaged": tc.get("ismanaged", False),
        }
        meta_path = os.path.join(tc_dir, meta_filename)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        # Track in component map
        rel_content = f"template-configs/{content_filename}"
        rel_meta = f"template-configs/{meta_filename}"
        config_id = tc.get("msdyn_employeeselfservicetemplateconfigid", "")
        component_map[rel_content] = {
            "templateconfigid": config_id,
            "msdyn_uniquename": tc.get("msdyn_uniquename", ""),
            "entity_set": "msdyn_employeeselfservicetemplateconfigs",
            "name": tc.get("msdyn_name", ""),
            "meta_file": rel_meta,
        }

        written += 1

    return {"written": written, "component_map": component_map}


def extract_workflows(workflows, output_dir):
    """Write each workflow to a subfolder with metadata.yml + workflow.json.

    Structure: workflows/{slug}-{workflowid}/metadata.yml + workflow.json
    Returns stats dict with component_map entries.
    """
    wf_dir = os.path.join(output_dir, "workflows")
    os.makedirs(wf_dir, exist_ok=True)

    component_map = {}
    written = 0

    for wf in workflows:
        wfid = wf.get("workflowid", "")
        name = wf.get("name", "Untitled")
        if not wfid:
            continue

        slug = friendly_filename(name, wfid)
        folder_name = f"{slug}-{wfid}"
        folder_path = os.path.join(wf_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)

        # Write metadata.yml
        state = wf.get("statecode", 0)
        status_map = {0: 1, 1: 2}  # statecode -> statuscode
        meta_lines = [
            f"jsonFileName: workflows/{folder_name}/workflow.json",
            f"workflowId: {wfid}",
            f"name: {name}",
            f"type: 1",
            f"description: \"{wf.get('description', '') or ''}\"",
            f"subprocess: {'true' if wf.get('subprocess') else 'false'}",
            f"category: {wf.get('category', 5)}",
            f"mode: 0",
            f"scope: 4",
            f"stateCode: {state}",
            f"statusCode: {status_map.get(state, 1)}",
            f"isTransacted: true",
        ]
        meta_path = os.path.join(folder_path, "metadata.yml")
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write("\n".join(meta_lines) + "\n")

        # Write workflow.json (the clientdata content)
        clientdata = wf.get("clientdata", "") or ""
        wf_json_path = os.path.join(folder_path, "workflow.json")

        # clientdata is a JSON string — parse and pretty-print
        if clientdata.strip():
            try:
                parsed = json.loads(clientdata)
                clientdata = json.dumps(parsed, indent=2)
            except (json.JSONDecodeError, ValueError):
                pass

        with open(wf_json_path, "w", encoding="utf-8") as f:
            f.write(clientdata)

        # Track in component map
        rel_wf = f"workflows/{folder_name}/workflow.json"
        rel_meta = f"workflows/{folder_name}/metadata.yml"
        component_map[rel_wf] = {
            "workflowid": wfid,
            "entity_set": "workflows",
            "name": name,
            "meta_file": rel_meta,
        }

        written += 1

    return {"written": written, "component_map": component_map}


def write_snapshot(output_dir, agent_info, stats, template_configs=None,
                   workflows=None):
    """Generate snapshot.md with agent inventory."""
    tc_count = len(template_configs) if template_configs else 0
    wf_count = len(workflows) if workflows else 0
    eval_sets = [e for e in stats.get('evaluations', [])
                 if not e.get('parentbotcomponentid')]
    eval_cases = [e for e in stats.get('evaluations', [])
                  if e.get('parentbotcomponentid')]

    lines = [
        f"# Agent Snapshot: {agent_info['name']}",
        "",
        f"Generated: {date.today().isoformat()}",
        f"Environment: {agent_info['url']}",
        "",
        "## Identity",
        "",
        f"- **Display name**: {agent_info['name']}",
        f"- **Schema name**: {agent_info['schema']}",
        f"- **Bot ID**: {agent_info['botId']}",
        f"- **Is Managed**: {agent_info['managed']}",
        "",
        "## Component Counts",
        "",
        f"- **Topics**: {len(stats['topics'])}",
        f"- **Variables**: {len(stats['variables'])}",
        f"- **Template Configs**: {tc_count}",
        f"- **Workflows**: {wf_count}",
        f"- **Evaluation Sets**: {len(eval_sets)} ({len(eval_cases)} test cases)",
        f"- **Other**: {len(stats['other'])}",
        "",
    ]

    if stats["topics"]:
        lines.append("## Topics")
        lines.append("")
        lines.append("| Name | Category |")
        lines.append("|------|----------|")
        for t in sorted(stats["topics"],
                        key=lambda x: (x["category"], x["name"])):
            lines.append(f"| {t['name']} | {t['category']} |")
        lines.append("")

    if stats["variables"]:
        lines.append("## Variables")
        lines.append("")
        lines.append("| Name |")
        lines.append("|------|")
        for v in sorted(stats["variables"], key=lambda x: x["name"] or ""):
            lines.append(f"| {v['name']} |")
        lines.append("")

    if template_configs:
        lines.append("## Template Configurations")
        lines.append("")
        lines.append("| Name | Unique Name | Type | Status | Description |")
        lines.append("|------|-------------|------|--------|-------------|")
        for tc in sorted(template_configs,
                         key=lambda x: x.get("msdyn_name", "")):
            name = tc.get("msdyn_name", "")
            uname = tc.get("msdyn_uniquename", "")
            desc = tc.get("msdyn_description", "") or ""
            value = tc.get("msdyn_value", "") or ""
            ctype = "XML" if value.lstrip().startswith("<") else "JSON"
            state = tc.get("statecode", 0)
            status = "Active" if state == 0 else "Inactive"
            lines.append(f"| {name} | {uname} | {ctype} | {status} | {desc} |")
        lines.append("")

    if workflows:
        # Build topic cross-reference
        flow_topics = _build_flow_topic_map(stats.get("topics", []),
                                            stats.get("_topic_data", {}))
        lines.append("## Workflows")
        lines.append("")
        lines.append("| Name | Workflow ID | Status | Referenced By |")
        lines.append("|------|-------------|--------|---------------|")
        for wf in sorted(workflows, key=lambda x: x.get("name", "")):
            name = wf.get("name", "")
            wfid = wf.get("workflowid", "")
            state = wf.get("statecode", 0)
            status = "Activated" if state == 1 else "Draft"
            refs = flow_topics.get(wfid.lower(), [])
            ref_str = ", ".join(refs) if refs else "(none)"
            lines.append(f"| {name} | {wfid[:8]}... | {status} | {ref_str} |")
        lines.append("")

    if eval_sets:
        lines.append("## Evaluation Test Sets")
        lines.append("")
        lines.append("| Set Name | Test Cases |")
        lines.append("|----------|------------|")
        # Build parent→child count mapping
        parent_counts = {}
        for e in stats.get('evaluations', []):
            pid = e.get('parentbotcomponentid')
            if pid:
                parent_counts[pid] = parent_counts.get(pid, 0) + 1
        # Map schema→botcomponentid for parent lookup
        for es in eval_sets:
            es_name = es.get('name', 'Unnamed')
            # Find the botcomponentid for this set from the component_map
            es_count = 0
            for path, entry in stats['component_map'].items():
                if (entry.get('schemaname') == es.get('schema')
                        and entry.get('componenttype') == 19
                        and not entry.get('parentbotcomponentid')):
                    es_count = parent_counts.get(
                        entry.get('botcomponentid'), 0)
                    break
            lines.append(f"| {es_name} | {es_count} |")
        lines.append("")

    filepath = os.path.join(output_dir, "snapshot.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _build_flow_topic_map(topics, topic_data):
    """Return {flowid_lower: [topic_name, ...]} from topic data blobs."""
    guid_re = re.compile(
        r'flowId:\s*["\']?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})',
    )
    result = {}
    for t in topics:
        data = topic_data.get(t.get("schema", ""), "")
        for m in guid_re.finditer(data):
            fid = m.group(1).lower()
            result.setdefault(fid, []).append(t["name"])
    return result


def write_config(agent_info, slug, output_dir, template_configs_discovered,
                 template_config_count=0, workflow_count=0,
                 evaluation_count=0):
    """Write .local/config.json with setup = complete.

    Atomic: writes to a .tmp sibling and os.replace()s into place so a
    crash mid-write cannot leave a corrupted half-JSON file that bricks
    the kit (the file gates every subsequent kit operation).

    Supports multiple agents: maintains an `agents` array with all discovered
    agents, `activeAgent` pointing to the current slug, and a backward-compat
    `agent` field that mirrors the active agent.
    """
    bot_id = agent_info["botId"]
    agent_entry = {
        "name": agent_info["name"],
        "botId": bot_id,
        "schemaName": agent_info["schema"],
        "isManaged": agent_info["managed"],
        "slug": slug,
        "folder": output_dir.replace("\\", "/"),
    }

    # Load existing config to preserve other agents and connections
    local_dir = ".local"
    config_path = os.path.join(local_dir, "config.json")
    existing = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Build or update agents array
    agents = existing.get("agents", [])

    # Remove existing entry for this slug if present (update case)
    agents = [a for a in agents if a.get("slug") != slug]
    agents.append(agent_entry)

    # Sort by name for consistent ordering
    agents.sort(key=lambda a: a.get("name", ""))

    config = {
        "setup": "complete",
        "agent": agent_entry,             # backward compat: active agent
        "activeAgent": slug,              # slug of the active agent
        "agents": agents,                 # all discovered agents
        "dataverseEndpoint": agent_info["url"],
        "templateConfigsDiscovered": template_configs_discovered,
        "templateConfigCount": template_config_count,
        "workflowCount": workflow_count,
        "evaluationCount": evaluation_count,
    }

    # Preserve existing connections and other user-set fields
    for key in ("connections", "workdayTestEmployeeId"):
        if key in existing and key not in config:
            config[key] = existing[key]

    os.makedirs(local_dir, exist_ok=True)
    tmp_path = config_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            # Some filesystems (e.g. certain network mounts) don't support
            # fsync. The os.replace below is still atomic on POSIX/Windows.
            pass
    os.replace(tmp_path, config_path)


def print_summary(stats, template_configs, workflows=None):
    """Print a human-readable summary for the agent to relay."""
    cats = {}
    for t in stats["topics"]:
        cats[t["category"]] = cats.get(t["category"], 0) + 1

    total_extracted = stats["written"]
    if template_configs:
        total_extracted += len(template_configs)
    if workflows:
        total_extracted += len(workflows)

    eval_sets = [e for e in stats.get('evaluations', [])
                 if not e.get('parentbotcomponentid')]
    eval_cases = [e for e in stats.get('evaluations', [])
                  if e.get('parentbotcomponentid')]

    print("")
    print("=" * 50)
    print("SETUP COMPLETE")
    print("=" * 50)
    print(f"Extracted {total_extracted} components "
          f"({stats['skipped']} skipped)")
    print("")
    print(f"Topics: {len(stats['topics'])}")
    for cat in sorted(cats.keys()):
        print(f"  {cat}: {cats[cat]}")
    print(f"Variables: {len(stats['variables'])}")
    if eval_sets or eval_cases:
        print(f"Evaluations: {len(eval_sets)} sets, {len(eval_cases)} test cases")
    if stats["other"]:
        print(f"Other: {len(stats['other'])}")
    if template_configs:
        print(f"Template Configs: {len(template_configs)}")
    if workflows:
        print(f"Workflows: {len(workflows)}")
    print("")


def write_component_map(output_dir, component_map):
    """Write .component-map.json mapping local files to Dataverse record IDs."""
    filepath = os.path.join(output_dir, ".component-map.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(component_map, f, indent=2)


def create_baseline(output_dir):
    """Copy working files to .baseline/ as an immutable safety net.

    Excludes .baseline/ and .checkpoints/ directories from the copy.
    Handles Windows file lock errors gracefully.
    """
    import stat
    import time

    baseline_dir = os.path.join(output_dir, ".baseline")

    def _on_rm_error(func, path, exc_info):
        """Handle read-only or locked files on Windows."""
        os.chmod(path, stat.S_IWRITE)
        func(path)

    if os.path.exists(baseline_dir):
        for attempt in range(5):
            try:
                shutil.rmtree(baseline_dir, onexc=_on_rm_error)
                break
            except (PermissionError, OSError):
                if attempt < 4:
                    time.sleep(1)
                else:
                    # Last resort: rename out of the way
                    stale = baseline_dir + f".old.{int(time.time())}"
                    os.rename(baseline_dir, stale)
                    shutil.rmtree(stale, ignore_errors=True)

    def _ignore(directory, contents):
        ignored = set()
        for item in contents:
            if item in (".baseline", ".checkpoints"):
                ignored.add(item)
        return ignored

    shutil.copytree(output_dir, baseline_dir, ignore=_ignore)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="ESS Copilot Kit — one-shot setup")
    parser.add_argument("--url", required=True,
                        help="Power Platform environment URL")
    parser.add_argument("--bot-id", required=True,
                        help="Selected bot ID from Dataverse")
    parser.add_argument("--name", required=True,
                        help="Agent display name")
    parser.add_argument("--schema", required=True,
                        help="Agent schema name")
    parser.add_argument("--managed", action="store_true",
                        help="Agent is managed (read-only base)")
    parser.add_argument("--components", required=True,
                        help="Path to components JSON file")
    parser.add_argument("--template-configs",
                        help="Path to template configs JSON (optional)")
    parser.add_argument("--workflows",
                        help="Path to workflows JSON (optional)")
    parser.add_argument("--refresh", action="store_true",
                        help="Merge into existing agent dir (checkpoint first)")
    args = parser.parse_args()

    # Derive slug and output path
    slug = slugify(args.name)
    output_dir = os.path.join("workspace", "agents", slug)

    agent_info = {
        "name": args.name,
        "botId": args.bot_id,
        "schema": args.schema,
        "managed": args.managed,
        "url": args.url,
    }

    # --- Refresh: checkpoint before overwriting ---
    if args.refresh and os.path.exists(output_dir):
        print("Creating checkpoint before refresh...")
        result = subprocess.run(
            [sys.executable, "scripts/checkpoint.py",
             "auto-save before refresh"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(result.stdout.strip())
        else:
            print(f"Warning: checkpoint failed: {result.stderr.strip()}")
        print("")

    # Load components JSON
    print(f"Loading components from {args.components}...")
    components = load_json(args.components)
    if not components:
        print("ERROR: No components found in JSON file.")
        sys.exit(1)

    # Load template configs if provided
    template_configs = None
    if args.template_configs and os.path.exists(args.template_configs):
        print(f"Loading template configs from {args.template_configs}...")
        template_configs = load_json(args.template_configs)

    # Load workflows if provided
    workflows = None
    if args.workflows and os.path.exists(args.workflows):
        print(f"Loading workflows from {args.workflows}...")
        workflows = load_json(args.workflows)

    # Extract components to local files
    print(f"Extracting to {output_dir}/...")
    stats = extract_components(components, output_dir)

    # Extract template configs to local files
    tc_stats = None
    if template_configs:
        tc_stats = extract_template_configs(template_configs, output_dir)
        # Merge template config entries into component map
        stats["component_map"].update(tc_stats["component_map"])

    # Extract workflows to local files
    wf_stats = None
    if workflows:
        wf_stats = extract_workflows(workflows, output_dir)
        # Merge workflow entries into component map
        stats["component_map"].update(wf_stats["component_map"])

    # Write component map (file -> Dataverse record ID mapping)
    write_component_map(output_dir, stats["component_map"])

    # Write snapshot
    write_snapshot(output_dir, agent_info, stats, template_configs, workflows)
    print(f"Snapshot: {output_dir}/snapshot.md")

    # Write config
    tc_count = len(template_configs) if template_configs else 0
    wf_count = len(workflows) if workflows else 0
    eval_count = len(stats.get('evaluations', []))
    write_config(agent_info, slug, output_dir,
                 template_configs is not None and tc_count > 0,
                 tc_count, wf_count, eval_count)
    print("Config:   .local/config.json")

    # Create baseline copy (immutable safety net)
    create_baseline(output_dir)
    print(f"Baseline: {output_dir}/.baseline/")

    # Clean up temp files
    for temp_path in [args.components, args.template_configs, args.workflows]:
        if temp_path:
            try:
                os.remove(temp_path)
                print(f"Cleaned:  {temp_path}")
            except OSError:
                pass

    # Print summary
    print_summary(stats, template_configs, workflows)


if __name__ == "__main__":
    main()
