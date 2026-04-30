# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit - Dataverse Extraction Script

Authenticates to Dataverse via MSAL and fetches all agent components,
template configs, and workflows using the REST API with automatic
pagination. This avoids the Dataverse MCP server's 20-row-per-query limit.

After fetching, it runs setup.py to extract files and generate the snapshot.

Usage:
    python scripts/fetch_and_setup.py \\
        --url https://org.crm.dynamics.com \\
        --bot-id abc-123-def \\
        --name "Employee Self-Service IT" \\
        --schema msdyn_ESSAgent \\
        [--managed]

    python scripts/fetch_and_setup.py --refresh

Prerequisites:
    pip install msal requests
"""

import argparse
import json
import os
import re
import subprocess
import sys

# Add scripts/ to path so we can import auth
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth import authenticate, load_config, query_all


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

def normalize_components(raw_records):
    """Map Dataverse REST API field names to the format setup.py expects.

    REST API returns _parentbotid_value for lookups and lowercased names.
    _parentbotcomponentid_value is the lookup column for parent-child
    relationships (used by evaluation test cases, componenttype 19).
    """
    normalized = []
    for r in raw_records:
        normalized.append({
            "botcomponentid": r.get("botcomponentid"),
            "name": r.get("name"),
            "schemaname": r.get("schemaname"),
            "componenttype": r.get("componenttype"),
            "data": r.get("data"),
            "parentbotcomponentid": r.get("_parentbotcomponentid_value"),
        })
    return normalized


def normalize_template_configs(raw_records):
    """Map REST API fields to the format setup.py expects."""
    normalized = []
    for r in raw_records:
        normalized.append({
            "msdyn_name": r.get("msdyn_name"),
            "msdyn_uniquename": r.get("msdyn_uniquename"),
            "msdyn_description": r.get("msdyn_description"),
            "msdyn_value": r.get("msdyn_value"),
            "msdyn_employeeselfservicetemplateconfigid": r.get(
                "msdyn_employeeselfservicetemplateconfigid"),
            "statecode": r.get("statecode"),
            "ismanaged": r.get("ismanaged"),
        })
    return normalized


def normalize_workflows(raw_records):
    """Map REST API fields to the format setup.py expects."""
    normalized = []
    for r in raw_records:
        normalized.append({
            "workflowid": r.get("workflowid"),
            "name": r.get("name"),
            "clientdata": r.get("clientdata"),
            "connectionreferences": r.get("connectionreferences"),
            "statecode": r.get("statecode"),
            "category": r.get("category"),
            "subprocess": r.get("subprocess"),
            "description": r.get("description"),
            "inputs": r.get("inputs"),
            "outputs": r.get("outputs"),
        })
    return normalized


def discover_flow_ids_from_components(components):
    """Scan component data blobs for flowId references."""
    flow_ids = set()
    guid_pattern = re.compile(
        r'flowId:\s*["\']?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})',
    )
    for comp in components:
        data = comp.get("data", "") or ""
        for match in guid_pattern.finditer(data):
            flow_ids.add(match.group(1).lower())
    return flow_ids


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fetch_all(env_url, token, bot_id, components=None):
    """Fetch components, template configs, and workflows from Dataverse.

    If *components* is provided (list), skip the components fetch and reuse
    the given list (used by --refresh to avoid re-downloading unchanged data).

    Returns (components, template_configs, workflows).
    """
    import requests as _requests  # local import to avoid top-level dep

    # --- Fetch components ---
    if components is None:
        print("Fetching agent components...")
        raw_components = query_all(
            env_url, token,
            entity_set="botcomponents",
            select="botcomponentid,name,schemaname,componenttype,data,_parentbotcomponentid_value",
            filter_expr=f"_parentbotid_value eq '{bot_id}'",
        )
        components = normalize_components(raw_components)
        print(f"  {len(components)} components fetched.\n")

    # --- Fetch template configs (full records) ---
    print("Fetching template configurations...")
    template_configs = None
    try:
        raw_configs = query_all(
            env_url, token,
            entity_set="msdyn_employeeselfservicetemplateconfigs",
            select=(
                "msdyn_name,msdyn_uniquename,msdyn_description,"
                "msdyn_value,msdyn_employeeselfservicetemplateconfigid,"
                "statecode,ismanaged"
            ),
        )
        template_configs = normalize_template_configs(raw_configs)
        print(f"  {len(template_configs)} template configs fetched.\n")
    except _requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            print("  Table not found (ESS template configs not deployed). "
                  "Skipping.\n")
        else:
            raise

    # --- Fetch workflows ---
    # 1. Copilot Studio agent flows (modernflowtype = 1)
    print("Fetching workflows...")
    raw_workflows = query_all(
        env_url, token,
        entity_set="workflows",
        select=(
            "workflowid,name,clientdata,connectionreferences,"
            "statecode,category,subprocess,description,inputs,outputs"
        ),
        filter_expr="modernflowtype eq 1",
    )

    # 2. Also fetch any flows referenced by topic flowId that aren't type 1
    referenced_ids = discover_flow_ids_from_components(components)
    fetched_ids = {r.get("workflowid", "").lower() for r in raw_workflows}
    missing_ids = referenced_ids - fetched_ids
    if missing_ids:
        for fid in missing_ids:
            try:
                extra = query_all(
                    env_url, token,
                    entity_set="workflows",
                    select=(
                        "workflowid,name,clientdata,connectionreferences,"
                        "statecode,category,subprocess,description,"
                        "inputs,outputs"
                    ),
                    filter_expr=f"workflowid eq '{fid}'",
                )
                raw_workflows.extend(extra)
            except Exception:
                pass  # flow may have been deleted

    workflows = normalize_workflows(raw_workflows)
    print(f"  {len(workflows)} workflows fetched.\n")

    return components, template_configs, workflows


def save_temp_files(components, template_configs, workflows):
    """Write fetched data to temp JSON files. Returns paths dict."""
    os.makedirs(os.path.join("my", "agents"), exist_ok=True)
    paths = {}

    comp_path = os.path.join("my", "agents", "components.json")
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump(components, f, indent=2)
    print(f"Saved components to {comp_path}")
    paths["components"] = comp_path

    if template_configs is not None:
        tc_path = os.path.join("my", "agents", "template-configs.json")
        with open(tc_path, "w", encoding="utf-8") as f:
            json.dump(template_configs, f, indent=2)
        print(f"Saved template configs to {tc_path}")
        paths["template_configs"] = tc_path

    if workflows:
        wf_path = os.path.join("my", "agents", "workflows.json")
        with open(wf_path, "w", encoding="utf-8") as f:
            json.dump(workflows, f, indent=2)
        print(f"Saved workflows to {wf_path}")
        paths["workflows"] = wf_path

    return paths


def run_setup(env_url, args_bot_id, args_name, args_schema, args_managed,
              paths, extra_flags=None):
    """Run setup.py with the given temp file paths."""
    print("\nRunning setup...\n")
    cmd = [
        sys.executable, "scripts/setup.py",
        "--url", env_url,
        "--bot-id", args_bot_id,
        "--name", args_name,
        "--schema", args_schema,
        "--components", paths["components"],
    ]
    if args_managed:
        cmd.append("--managed")
    if "template_configs" in paths:
        cmd.extend(["--template-configs", paths["template_configs"]])
    if "workflows" in paths:
        cmd.extend(["--workflows", paths["workflows"]])
    if extra_flags:
        cmd.extend(extra_flags)

    result = subprocess.run(cmd)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="Fetch agent components from Dataverse and run setup")
    parser.add_argument("--url",
                        help="Power Platform environment URL "
                             "(e.g. https://org.crm.dynamics.com)")
    parser.add_argument("--bot-id",
                        help="Bot ID (GUID) from Dataverse")
    parser.add_argument("--name",
                        help="Agent display name")
    parser.add_argument("--schema",
                        help="Agent schema name")
    parser.add_argument("--managed", action="store_true",
                        help="Agent is managed (read-only base)")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch from existing config (no full setup)")
    args = parser.parse_args()

    # --- Refresh mode: read config for existing agent details ---
    if args.refresh:
        config = load_config()
        env_url = config["dataverseEndpoint"]
        bot_id = config["agent"]["botId"]
        name = config["agent"]["name"]
        schema = config["agent"]["schemaName"]
        managed = config["agent"].get("isManaged", False)

        print("Authenticating to Dataverse...")
        token = authenticate(env_url)
        print("Authenticated.\n")

        components, template_configs, workflows = fetch_all(
            env_url, token, bot_id)
        paths = save_temp_files(components, template_configs, workflows)
        rc = run_setup(env_url, bot_id, name, schema, managed,
                       paths, extra_flags=["--refresh"])
        sys.exit(rc)

    # --- Normal mode: requires all arguments ---
    if not all([args.url, args.bot_id, args.name, args.schema]):
        parser.error(
            "--url, --bot-id, --name, and --schema are required "
            "(or use --refresh)")

    env_url = args.url.rstrip("/")

    print("Authenticating to Dataverse...")
    token = authenticate(env_url)
    print("Authenticated.\n")

    components, template_configs, workflows = fetch_all(
        env_url, token, args.bot_id)
    paths = save_temp_files(components, template_configs, workflows)
    rc = run_setup(env_url, args.bot_id, args.name, args.schema,
                   args.managed, paths)
    sys.exit(rc)


if __name__ == "__main__":
    main()
