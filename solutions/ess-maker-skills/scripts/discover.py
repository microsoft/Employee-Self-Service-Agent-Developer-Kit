# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Dataverse Environment Discovery Script

Lists Dataverse-linked Power Platform environments for FlightCheck and
extension setup flows that still require one. Standalone FlightCheck can also
list agents after an environment is selected.

Usage:
    # List all environments in the tenant (no URL required)
    python scripts/discover.py --list-environments

    # Select environment #2 and output JSON
    python scripts/discover.py --list-environments --select 2

    # Resolve a known Dataverse URL
    python scripts/discover.py \
        --resolve-environment-url https://org.crm.dynamics.com

    # List agents for standalone FlightCheck
    python scripts/discover.py --url https://org.crm.dynamics.com

    # Select agent #2 and output JSON
    python scripts/discover.py \
        --url https://org.crm.dynamics.com --select 2
"""

import argparse
import json
import os
import sys

# Add scripts/ to path so we can import environment helpers.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def discover_agents(env_url, token):
    """Query Dataverse for agents without classifying setup products."""
    from auth import query_all

    raw = query_all(
        env_url,
        token,
        entity_set="bots",
        select="botid,name,schemaname,ismanaged",
    )
    return [
        {
            "botid": record.get("botid"),
            "name": record.get("name"),
            "schemaname": record.get("schemaname"),
            "ismanaged": record.get("ismanaged", False),
        }
        for record in raw
    ]


def print_agent_table(agents):
    """Print a numbered agent table."""
    name_width = max(
        10,
        max((len(agent["name"] or "") for agent in agents), default=0),
    )
    schema_width = max(
        11,
        max((len(agent["schemaname"] or "") for agent in agents), default=0),
    )
    header = (
        f"  {'#':<4} {'Agent Name':<{name_width}}  "
        f"{'Schema Name':<{schema_width}}  {'Managed'}"
    )
    separator = (
        f"  {'-' * 4} {'-' * name_width}  "
        f"{'-' * schema_width}  {'-' * 7}"
    )
    print()
    print(header)
    print(separator)
    for index, agent in enumerate(agents, 1):
        managed = "Yes" if agent["ismanaged"] else "No"
        print(
            f"  {index:<4} {agent['name'] or '':<{name_width}}  "
            f"{agent['schemaname'] or '':<{schema_width}}  {managed}"
        )
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Discover FlightCheck environments and agents")
    parser.add_argument(
        "--url",
        help="Dataverse environment URL for standalone FlightCheck agent discovery",
    )
    parser.add_argument("--list-environments", action="store_true",
                        help="List all environments in the tenant (no URL needed)")
    parser.add_argument(
        "--resolve-environment-url",
        help="Resolve one environment URL to its Power Platform metadata",
    )
    parser.add_argument("--select", type=int, default=None,
                        help="Select environment by number and output JSON")
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

    if not args.url:
        parser.error(
            "choose --list-environments, --resolve-environment-url, or --url"
        )

    env_url = args.url.rstrip("/")
    from auth import authenticate
    from http_errors import APIError

    try:
        agents = discover_agents(env_url, authenticate(env_url))
    except APIError as error:
        print(error.format_for_terminal())
        sys.exit(1)

    print(f"AGENT_DISCOVERY_JSON:{json.dumps(agents)}")
    if not agents:
        print("No agents found in this environment.")
        sys.exit(1)

    print(f"Found {len(agents)} agent(s):")
    print_agent_table(agents)

    if args.select is not None:
        index = args.select
        if index < 1 or index > len(agents):
            print(
                f"ERROR: Invalid selection '{index}'. "
                f"Choose a number between 1 and {len(agents)}."
            )
            sys.exit(1)
        print(f"SELECTED_AGENT_JSON:{json.dumps(agents[index - 1])}")


if __name__ == "__main__":
    main()
