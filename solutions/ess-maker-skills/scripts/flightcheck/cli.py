# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit — FlightCheck CLI

Entry point for running pre-deployment validation checks.

Usage:
    python scripts/flightcheck/cli.py [--scope SCOPE]

Scopes:
    full            — Run all checks (default)
    prerequisites   — Licenses, roles only
    environment     — PP environment, Dataverse, DLP
    authentication  — Entra ID, SSO, CA policies
    external        — Integration discovery (flows)
    workday         — Workday deep validation
    local           — Local agent file validation
    publishing      — Publishing/QA checklist
"""

import argparse
import json
import os
import sys

# Ensure scripts/ is on the path so we can import auth
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flightcheck.runner import FlightCheckRunner, save_results, Status
from flightcheck.graph_client import GraphClient
from flightcheck.pp_admin_client import PPAdminClient, derive_environment_id

# Check modules
from flightcheck.checks.prerequisites import run_prerequisites_checks
from flightcheck.checks.environment import run_environment_checks
from flightcheck.checks.authentication import run_authentication_checks
from flightcheck.checks.external_systems import run_external_systems_checks
from flightcheck.checks.workday import run_workday_checks
from flightcheck.checks.local_files import run_local_file_checks
from flightcheck.checks.publishing import run_publishing_checks


SCOPE_MAP = {
    "prerequisites": [("Prerequisites", run_prerequisites_checks)],
    "environment": [("Environment", run_environment_checks)],
    "authentication": [("Authentication", run_authentication_checks)],
    "external": [("External Systems", run_external_systems_checks)],
    "workday": [
        ("External Systems", run_external_systems_checks),
        ("Workday", run_workday_checks),
    ],
    "local": [("Local Files", run_local_file_checks)],
    "publishing": [("Publishing", run_publishing_checks)],
}

FULL_SCOPE = [
    ("Prerequisites", run_prerequisites_checks),
    ("Environment", run_environment_checks),
    ("Authentication", run_authentication_checks),
    ("External Systems", run_external_systems_checks),
    ("Workday", run_workday_checks),
    ("Local Files", run_local_file_checks),
    ("Publishing", run_publishing_checks),
]


def main():
    parser = argparse.ArgumentParser(description="ESS FlightCheck — Pre-deployment Validator")
    parser.add_argument(
        "--scope", default="full",
        choices=["full"] + list(SCOPE_MAP.keys()),
        help="Validation scope (default: full)",
    )
    parser.add_argument(
        "--output", default="workspace/flightcheck",
        help="Output directory (default: workspace/flightcheck)",
    )
    args = parser.parse_args()

    # Load config
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

    # --- Banner ---
    agents = config.get("agents", [])
    active = config.get("activeAgent", config.get("agent", {}).get("slug", ""))
    if not agents:
        # Backward compat: single agent in config
        agent_entry = config.get("agent", {})
        if agent_entry:
            agents = [agent_entry]

    print()
    print("=" * 64)
    print("  ESS FLIGHTCHECK — Pre-deployment Validation")
    print("=" * 64)
    if len(agents) == 1:
        print(f"  Agent:       {agents[0].get('name', 'N/A')}")
    else:
        print(f"  Agents:      {len(agents)} discovered")
        for a in agents:
            marker = "→" if a.get("slug") == active else " "
            print(f"    {marker} {a.get('name', 'Unknown')}")
    print(f"  Environment: {env_url}")
    print(f"  Scope:       {args.scope}")
    print("=" * 64)
    print()

    # --- Authenticate ---
    from auth import authenticate, discover_tenant

    print("Authenticating to Dataverse...")
    dv_token = authenticate(env_url)

    tenant_id = discover_tenant(env_url)
    print(f"Tenant: {tenant_id}")

    # Derive PP environment ID
    print("Deriving Power Platform environment ID...")
    env_id = derive_environment_id(env_url, dv_token)
    if env_id:
        print(f"Environment ID: {env_id}")
    else:
        print("WARNING: Could not derive environment ID. Some checks may be limited.")

    # Initialize clients
    print("Authenticating to Microsoft Graph...")
    graph = GraphClient(tenant_id)
    try:
        graph.authenticate()
        print("  Graph: OK")
    except Exception as e:
        print(f"  Graph: WARNING — {e}")
        print("  (Some checks will be skipped)")

    print("Authenticating to Power Platform Admin API...")
    pp_admin = PPAdminClient(tenant_id)
    try:
        pp_admin.authenticate()
        print("  Power Platform: OK")
    except Exception as e:
        print(f"  Power Platform: WARNING — {e}")
        print("  (Some checks will be skipped)")

    # --- Build runner ---
    runner = FlightCheckRunner(scope=args.scope)
    runner.config = config
    runner.env_url = env_url
    runner.dv_token = dv_token
    runner.env_id = env_id
    runner.graph = graph
    runner.pp_admin = pp_admin

    # Register checks based on scope
    if args.scope == "full":
        checks = FULL_SCOPE
    else:
        checks = SCOPE_MAP.get(args.scope, FULL_SCOPE)

    for category, fn in checks:
        runner.register(category, fn)

    # --- Execute ---
    print("\nRunning checks...\n")
    result = runner.run()

    # --- Print summary ---
    print()
    print("=" * 64)
    print("  FLIGHTCHECK SUMMARY")
    print("=" * 64)
    print(f"  Total checks: {result.total}")
    print(f"  ✅ Passed:         {result.passed}")
    print(f"  ❌ Failed:         {result.failed}")
    print(f"  ⚠️  Warnings:       {result.warnings}")
    print(f"  ℹ️  Not Configured: {result.not_configured}")
    print(f"  Duration:          {result.duration_secs}s")
    print()

    if result.overall == "READY":
        print("  ✅ READY FOR DEPLOYMENT")
    elif result.overall == "READY_WITH_WARNINGS":
        print("  ⚠️  READY WITH WARNINGS")
    else:
        print("  ❌ NOT READY — ISSUES FOUND")

    print("=" * 64)

    # Print failures
    failures = [r for r in result.results if r.status == Status.FAILED.value]
    if failures:
        print(f"\n  FAILED CHECKS ({len(failures)}):\n")
        for r in failures:
            print(f"    ❌ {r.checkpoint_id}: {r.result}")
            if r.remediation:
                print(f"       → {r.remediation}")
        print()

    # Save results
    save_results(result, args.output)

    # Exit code
    sys.exit(1 if result.failed > 0 else 0)


if __name__ == "__main__":
    main()
