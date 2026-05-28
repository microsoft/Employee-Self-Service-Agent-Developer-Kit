# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — FlightCheck Environment Picker

Wrapper around FlightCheck that queries the Power Platform tenant for all
available environments and lets the user choose which one to validate.

Usage:
    python scripts/flightcheck/environment_picker.py [--scope SCOPE]

The picker authenticates to the Power Platform Admin API, lists all
environments the user has access to, presents a numbered menu, and then
runs FlightCheck against the selected environment.
"""

import argparse
import json
import os
import sys
from urllib.parse import urlparse

# Ensure scripts/ is on the path so we can import auth and flightcheck modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auth import discover_tenant
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


def display_environment_menu(environments: list[dict]) -> int:
    """Display a numbered list of environments and return the user's choice (0-based index)."""
    print()
    print("=" * 64)
    print("  AVAILABLE POWER PLATFORM ENVIRONMENTS")
    print("=" * 64)
    print()

    for i, env in enumerate(environments, 1):
        type_badge = f"[{env['type']}]" if env["type"] else ""
        region_badge = f"({env['region']})" if env["region"] else ""
        url_display = env["instanceUrl"] or "(no Dataverse linked)"

        print(f"  {i:>3}. {env['displayName']} {type_badge} {region_badge}")
        print(f"       URL: {url_display}")
        print()

    print("=" * 64)
    print()

    while True:
        try:
            choice = input(f"Select an environment [1-{len(environments)}]: ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(environments):
                return idx
            print(f"  Please enter a number between 1 and {len(environments)}.")
        except ValueError:
            print("  Please enter a valid number.")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(0)


def run_flightcheck_for_environment(env: dict, scope: str, output: str):
    """Run FlightCheck CLI targeting the selected environment.

    Updates .local/config.json temporarily with the selected environment's
    Dataverse URL, then invokes the FlightCheck CLI main() function.
    """
    instance_url = env.get("instanceUrl", "")
    if not instance_url:
        print(f"ERROR: Environment '{env['displayName']}' has no linked Dataverse URL.")
        print("FlightCheck requires a Dataverse-linked environment.")
        sys.exit(1)

    print()
    print(f"Running FlightCheck against: {env['displayName']}")
    print(f"  Environment ID: {env['id']}")
    print(f"  Dataverse URL:  {instance_url}")
    print()

    # Override sys.argv to pass through to cli.main()
    sys.argv = [
        "flightcheck",
        "--scope", scope,
        "--output", output,
        "--environment-url", instance_url,
        "--environment-id", env["id"],
    ]

    from flightcheck.cli import main as flightcheck_main
    flightcheck_main()


def main():
    parser = argparse.ArgumentParser(
        description="ESS FlightCheck — Environment Picker & Runner"
    )
    parser.add_argument(
        "--scope", default="full",
        choices=["full", "prerequisites", "environment", "authentication",
                 "external", "workday", "local", "publishing"],
        help="Validation scope (default: full)",
    )
    parser.add_argument(
        "--output", default="workspace/flightcheck",
        help="Output directory (default: workspace/flightcheck)",
    )
    args = parser.parse_args()

    # Load config to get tenant info
    config_path = os.path.join(".local", "config.json")
    if not os.path.exists(config_path):
        print("ERROR: .local/config.json not found. Run /setup first.")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    env_url = config.get("dataverseEndpoint", "")
    if not env_url:
        print("ERROR: No dataverseEndpoint in .local/config.json.")
        sys.exit(1)

    # Discover tenant and authenticate to Power Platform
    print()
    print("=" * 64)
    print("  ESS FLIGHTCHECK — Environment Picker")
    print("=" * 64)
    print()
    print("Discovering tenant...")
    tenant_id = discover_tenant(env_url)
    print(f"Tenant: {tenant_id}")

    print("Authenticating to Power Platform Admin API...")
    pp_admin = PPAdminClient(tenant_id)
    try:
        pp_admin.authenticate()
        print("  Power Platform: OK")
    except Exception as e:
        print(f"ERROR: Power Platform authentication failed — {e}")
        print("Cannot list environments without Power Platform Admin access.")
        sys.exit(1)

    # List and display environments
    print("\nFetching environments...")
    environments = list_environments(pp_admin)

    if not environments:
        print("ERROR: No environments found. Check your Power Platform Admin permissions.")
        sys.exit(1)

    print(f"Found {len(environments)} environment(s).")

    # Mark the currently configured environment
    current_host = (urlparse(env_url.rstrip("/")).hostname or "").lower()
    for env in environments:
        env_host = (urlparse(env["instanceUrl"]).hostname or "").lower()
        env["isCurrent"] = (env_host == current_host) if env_host else False

    # Display menu and get selection
    choice_idx = display_environment_menu(environments)
    selected = environments[choice_idx]

    print(f"\n  ✓ Selected: {selected['displayName']}")
    if selected["isCurrent"]:
        print("    (This is your currently configured environment)")

    # Run FlightCheck against the selected environment
    run_flightcheck_for_environment(selected, args.scope, args.output)


if __name__ == "__main__":
    main()
