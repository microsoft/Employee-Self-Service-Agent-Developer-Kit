"""
ESS Copilot Kit - Agent Discovery Script

Authenticates to Dataverse via MSAL and lists available agents (bots).
Designed to be called by the onboarding flow so that any model — including
less-capable ones — can complete setup by running a terminal command instead
of navigating MCP tool calls.

Usage:
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


def print_agent_table(agents):
    """Print a numbered table of agents to stdout."""
    # Calculate column widths
    name_width = max((len(a["name"] or "") for a in agents), default=10)
    schema_width = max((len(a["schemaname"] or "") for a in agents), default=11)
    name_width = max(name_width, 10)
    schema_width = max(schema_width, 11)

    header = f"  {'#':<4} {'Agent Name':<{name_width}}  {'Schema Name':<{schema_width}}  {'Managed'}"
    sep = f"  {'─'*4} {'─'*name_width}  {'─'*schema_width}  {'─'*7}"
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
    parser.add_argument("--url", required=True,
                        help="Power Platform environment URL")
    parser.add_argument("--select", type=int, default=None,
                        help="Select agent by number and output JSON")
    args = parser.parse_args()

    env_url = args.url.rstrip("/")

    print("Authenticating to Dataverse...")
    token = authenticate(env_url)
    print("Authenticated.\n")

    print("Discovering agents...")
    agents = discover_agents(env_url, token)

    if not agents:
        print("No agents found in this environment.")
        print("Make sure your ESS agent is installed in Copilot Studio.")
        sys.exit(1)

    print(f"Found {len(agents)} agent(s):")
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
