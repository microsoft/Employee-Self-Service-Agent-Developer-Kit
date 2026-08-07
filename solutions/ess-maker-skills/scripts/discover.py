# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Agent Discovery Script

Authenticates to Dataverse via MSAL and lists available agents (bots).
Designed to be called by the onboarding flow so that any model — including
less-capable ones — can complete setup by running a terminal command instead
of navigating MCP tool calls.

Usage:
    # List all environments in the tenant (no URL required)
    python scripts/discover.py --list-environments

    # Select environment #2 and output JSON
    python scripts/discover.py --list-environments --select 2

    # List agents in the environment
    python scripts/discover.py --url https://org.crm.dynamics.com

    # Select agent #2 and output JSON for the next step
    python scripts/discover.py --url https://org.crm.dynamics.com --select 2
"""

import argparse
import json
import sys
import os

# Add scripts/ to path so we can import auth
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth import authenticate, query_all
from http_errors import APIError
from install_ess_agent import (
    build_installation_options,
    load_installation_config,
)


def discover_agents(env_url, token):
    """Query Dataverse for all bots and return the list."""
    raw = query_all(
        env_url, token,
        entity_set="bots",
        select="botid,name,schemaname,ismanaged",
    )
    agents = []
    for r in raw:
        agents.append({
            "botid": r.get("botid"),
            "name": r.get("name"),
            "schemaname": r.get("schemaname"),
            "ismanaged": r.get("ismanaged", False),
        })
    return agents


def build_ess_agent_inventory(agents, config):
    """Classify supported ESS bots and list products that remain installable."""
    options = build_installation_options(config)
    options_by_schema = {
        option["schemaName"].casefold(): option
        for option in options
    }
    ess_agents = []
    installed_keys = set()

    for agent in agents:
        schema_name = agent.get("schemaname")
        if not isinstance(schema_name, str):
            continue
        option = options_by_schema.get(schema_name.casefold())
        if option is None:
            continue
        ess_agents.append({
            **agent,
            "installationKey": option["key"],
            "configKey": option["configKey"],
        })
        installed_keys.add(option["key"])

    return {
        "agents": ess_agents,
        "installedInstallationKeys": sorted(installed_keys),
        "availableInstallations": [
            option
            for option in options
            if option["key"] not in installed_keys
        ],
    }


def print_agent_table(agents):
    """Print a numbered table of agents to stdout."""
    # Calculate column widths
    name_width = max((len(a["name"] or "") for a in agents), default=10)
    schema_width = max((len(a["schemaname"] or "") for a in agents), default=11)
    name_width = max(name_width, 10)
    schema_width = max(schema_width, 11)

    header = f"  {'#':<4} {'Agent Name':<{name_width}}  {'Schema Name':<{schema_width}}  {'Managed'}"
    sep = f"  {'-'*4} {'-'*name_width}  {'-'*schema_width}  {'-'*7}"
    print()
    print(header)
    print(sep)
    for i, a in enumerate(agents, 1):
        managed = "Yes" if a["ismanaged"] else "No"
        print(f"  {i:<4} {a['name'] or '':<{name_width}}  {a['schemaname'] or '':<{schema_width}}  {managed}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Discover agents in a Dataverse environment")
    parser.add_argument("--url",
                        help="Power Platform environment URL")
    parser.add_argument("--list-environments", action="store_true",
                        help="List all environments in the tenant (no URL needed)")
    parser.add_argument(
        "--resolve-environment-url",
        help="Resolve one environment URL to its Power Platform metadata",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Output ESS agent inventory JSON without requiring an installed agent",
    )
    parser.add_argument("--select", type=int, default=None,
                        help="Select agent by number and output JSON")
    args = parser.parse_args()

    if args.resolve_environment_url:
        from list_environments import resolve_environment_for_user

        selected = resolve_environment_for_user(args.resolve_environment_url)
        if selected is None:
            print(
                "ERROR: The provided URL did not match a Dataverse-linked "
                "Power Platform environment available to the signed-in account."
            )
            sys.exit(1)
        print(f"SELECTED_ENV_JSON:{json.dumps(selected)}")
        return

    # --- Environment listing mode ---
    if args.list_environments:
        from list_environments import (
            get_dataverse_environments,
            print_environment_table,
        )

        dv_environments, excluded = get_dataverse_environments()

        print(f"Found {len(dv_environments)} Dataverse-linked environment(s).")
        if excluded:
            print(f"  ({excluded} environment(s) without Dataverse were excluded.)")

        if not dv_environments:
            print("ERROR: No environments with linked Dataverse found.")
            print("ESS requires a Dataverse-enabled environment.")
            sys.exit(1)

        print_environment_table(dv_environments)
        print(f"ENVIRONMENT_LIST_JSON:{json.dumps(dv_environments)}")

        if args.select is not None:
            idx = args.select
            if idx < 1 or idx > len(dv_environments):
                print(f"ERROR: Invalid selection '{idx}'. "
                      f"Choose a number between 1 and {len(dv_environments)}.")
                sys.exit(1)
            selected = dv_environments[idx - 1]
            print(f"SELECTED_ENV_JSON:{json.dumps(selected)}")
            sys.exit(0)

        return

    # --- Agent discovery mode (requires --url) ---
    if not args.url:
        parser.error("--url is required when not using --list-environments")

    env_url = args.url.rstrip("/")

    token = authenticate(env_url)
    try:
        inventory = build_ess_agent_inventory(
            discover_agents(env_url, token),
            load_installation_config(),
        )
    except APIError as e:
        print(e.format_for_terminal())
        sys.exit(1)
    except (OSError, ValueError) as e:
        print(f"ERROR: Could not load ESS installation catalog: {e}")
        sys.exit(1)

    print(f"ESS_AGENT_DISCOVERY_JSON:{json.dumps(inventory)}")
    agents = inventory["agents"]

    if args.inventory_only:
        return

    if not agents:
        print("No supported ESS agents found in this environment.")
        sys.exit(1)

    print(f"Found {len(agents)} supported ESS agent(s):")
    print_agent_table(agents)

    if args.select is not None:
        idx = args.select
        if idx < 1 or idx > len(agents):
            print(f"ERROR: Invalid selection '{idx}'. "
                  f"Choose a number between 1 and {len(agents)}.")
            sys.exit(1)
        selected = agents[idx - 1]
        # Output JSON on a clearly marked line for easy parsing
        print(f"SELECTED_AGENT_JSON:{json.dumps(selected)}")
        sys.exit(0)


if __name__ == "__main__":
    main()
