# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Environment Listing Script

Authenticates to the Power Platform Admin API and lists all environments
the user has access to. Designed to be called during onboarding (/setup)
so the user can pick their environment without typing the URL manually.

Usage:
    # List all environments in the tenant
    python scripts/list_environments.py

    # Select environment #2 and output JSON for the next step
    python scripts/list_environments.py --select 2
"""

import argparse
import json
import os
import sys

# Add scripts/ to path so we can import shared modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flightcheck.pp_admin_client import PPAdminClient


def list_environments(pp_admin: PPAdminClient) -> list[dict]:
    """Fetch all environments from the Power Platform Admin API.

    Returns a list of environment records with extracted metadata
    useful for display and selection.
    """
    raw_envs = pp_admin.get_environments()
    if isinstance(raw_envs, dict) and "_error" in raw_envs:
        print("ERROR: Could not list environments. Insufficient permissions.")
        sys.exit(1)

    environments = []
    for env in raw_envs:
        props = env.get("properties", {})
        linked = props.get("linkedEnvironmentMetadata", {})
        instance_url = linked.get("instanceUrl", "").rstrip("/")
        display_name = props.get("displayName", "Unknown")
        env_type = props.get("environmentType", "Unknown")
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


def print_environment_table(environments: list[dict]):
    """Print a numbered table of environments to stdout."""
    name_width = max((len(e["displayName"] or "") for e in environments), default=12)
    type_width = max((len(e["type"] or "") for e in environments), default=4)
    name_width = max(name_width, 12)
    type_width = max(type_width, 4)

    header = f"  {'#':<4} {'Environment Name':<{name_width}}  {'Type':<{type_width}}  {'Region':<8}  {'URL'}"
    sep = f"  {'─'*4} {'─'*name_width}  {'─'*type_width}  {'─'*8}  {'─'*40}"
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


def main():
    parser = argparse.ArgumentParser(
        description="List Power Platform environments in the tenant")
    parser.add_argument("--select", type=int, default=None,
                        help="Select environment by number and output JSON")
    args = parser.parse_args()

    # Authenticate using "organizations" authority (multi-tenant, no prior
    # config needed). The user signs in interactively and the token will
    # be scoped to their home tenant.
    print("Authenticating to Power Platform Admin API...")
    print("A browser window will open for sign-in.")
    pp_admin = PPAdminClient("organizations")
    try:
        pp_admin.authenticate()
    except Exception as e:
        print(f"ERROR: Power Platform authentication failed — {e}")
        print("Ensure you have Power Platform environment access.")
        sys.exit(1)
    print("Authenticated.\n")

    print("Fetching environments...")
    environments = list_environments(pp_admin)

    if not environments:
        print("No environments found.")
        print("Ensure your account has access to at least one Power Platform environment.")
        sys.exit(1)

    # Filter to only environments with a linked Dataverse URL
    dv_environments = [e for e in environments if e["instanceUrl"]]
    non_dv = len(environments) - len(dv_environments)

    print(f"Found {len(dv_environments)} Dataverse-linked environment(s).")
    if non_dv:
        print(f"  ({non_dv} environment(s) without Dataverse were excluded.)")

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
        # Output JSON on a clearly marked line for easy parsing
        print(f"SELECTED_ENV_JSON:{json.dumps(selected)}")
        sys.exit(0)


if __name__ == "__main__":
    main()
