# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Environment Listing Module

Lists all Power Platform environments in a tenant via the BAP Admin API.
Used by discover.py during onboarding so users can pick their environment
without typing the URL manually.

Usage (standalone):
    python scripts/list_environments.py

    python scripts/list_environments.py --select 2
"""

import json
import os
import sys

# Add scripts/ to path so we can import shared modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flightcheck.pp_admin_client import PPAdminClient


def parse_raw_environments(raw_envs):
    """Parse raw BAP environment records into normalized dicts.

    Args:
        raw_envs: List of environment records from PPAdminClient.get_environments().

    Returns:
        List of dicts with keys: id, displayName, type, state, instanceUrl, region.
    """
    environments = []
    for env in raw_envs:
        props = env.get("properties", {})
        linked = props.get("linkedEnvironmentMetadata", {})
        instance_url = linked.get("instanceUrl", "").rstrip("/")
        display_name = props.get("displayName", "Unknown")
        env_type = props.get("environmentSku", props.get("environmentType", "Unknown"))
        state = props.get("states", {}).get("runtime", {}).get("id", "Unknown")
        env_id = env.get("name", "")

        environments.append({
            "id": env_id,
            "displayName": display_name,
            "type": env_type,
            "state": state,
            "instanceUrl": instance_url,
            "region": linked.get("geo", ""),
        })

    return environments


def list_environments():
    """Fetch all environments from the Power Platform Admin API.

    Authenticates using "organizations" authority (multi-tenant) so no
    prior configuration or URL is needed.

    Returns a list of environment records with extracted metadata.
    """
    print("Authenticating to Power Platform Admin API...")
    print("A browser window will open for sign-in.")
    pp_admin = PPAdminClient("organizations")
    try:
        pp_admin.authenticate()
    except Exception as e:
        print(f"ERROR: Power Platform authentication failed - {e}")
        print("Ensure you have Power Platform environment access.")
        sys.exit(1)
    print("Authenticated.\n")

    print("Fetching environments...")
    raw_envs = pp_admin.get_environments()
    if isinstance(raw_envs, dict) and "_error" in raw_envs:
        print("ERROR: Could not list environments. Insufficient permissions.")
        sys.exit(1)

    return parse_raw_environments(raw_envs)


def get_dataverse_environments():
    """List environments and filter to only Dataverse-linked ones.

    Returns (dv_environments, excluded_count) tuple.
    """
    environments = list_environments()
    dv_environments = [e for e in environments if e["instanceUrl"]]
    excluded = len(environments) - len(dv_environments)
    return dv_environments, excluded


def print_environment_table(environments):
    """Print a numbered table of environments to stdout."""
    name_width = max((len(e["displayName"] or "") for e in environments), default=12)
    type_width = max((len(e["type"] or "") for e in environments), default=4)
    name_width = max(name_width, 12)
    type_width = max(type_width, 4)

    header = f"  {'#':<4} {'Environment Name':<{name_width}}  {'Type':<{type_width}}  {'Region':<8}  {'URL'}"
    sep = f"  {'-'*4} {'-'*name_width}  {'-'*type_width}  {'-'*8}  {'-'*40}"
    print()
    print(header)
    print(sep)
    for i, e in enumerate(environments, 1):
        url_display = e["instanceUrl"] or "(no Dataverse linked)"
        region = e.get("region", "") or ""
        print(
            f"  {i:<4} {e['displayName'] or '':<{name_width}}  "
            f"{e['type'] or '':<{type_width}}  {region:<8}  {url_display}"
        )
    print()


def write_environment_markdown(environments, path="workspace/onboarding/environments.md"):
    """Write a clean, numbered Markdown table of environments to a file.

    The onboarding flow reads this file to show the user a complete,
    untruncated table — rather than scraping the terminal scrollback, which
    Copilot Chat may truncate. Returns the path written.
    """
    lines = [
        "| # | Environment Name | Type | Region | URL |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i, e in enumerate(environments, 1):
        name = (e.get("displayName") or "").replace("|", "\\|")
        env_type = (e.get("type") or "").replace("|", "\\|")
        region = (e.get("region") or "").replace("|", "\\|")
        url = e.get("instanceUrl") or "(no Dataverse linked)"
        lines.append(f"| {i} | {name} | {env_type} | {region} | {url} |")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main():
    """Standalone entry point for listing environments."""
    import argparse

    parser = argparse.ArgumentParser(
        description="List Power Platform environments in the tenant")
    parser.add_argument("--select", type=int, default=None,
                        help="Select environment by number and output JSON")
    args = parser.parse_args()

    dv_environments, excluded = get_dataverse_environments()

    print(f"Found {len(dv_environments)} Dataverse-linked environment(s).")
    if excluded:
        print(f"  ({excluded} environment(s) without Dataverse were excluded.)")

    if not dv_environments:
        print("ERROR: No environments with linked Dataverse found.")
        print("ESS requires a Dataverse-enabled environment.")
        sys.exit(1)

    print_environment_table(dv_environments)

    if args.select is not None:
        idx = args.select
        if idx < 1 or idx > len(dv_environments):
            print(f"ERROR: Invalid selection '{idx}'. "
                  f"Choose a number between 1 and {len(dv_environments)}.")
            sys.exit(1)
        selected = dv_environments[idx - 1]
        print(f"SELECTED_ENV_JSON:{json.dumps(selected)}")
        sys.exit(0)


if __name__ == "__main__":
    main()
