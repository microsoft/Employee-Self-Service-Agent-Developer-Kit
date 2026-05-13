# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — FlightCheck CLI

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
    provision       — Smoke test for /provision skill (env + external + workday)
"""

import argparse
import json
import os
import sys

# Force UTF-8 on stdout/stderr so the summary's emoji (checkmarks, warnings,
# em dashes) render on Windows consoles too. cp1252 is the default on
# Windows and chokes on these glyphs. Available on Python 3.7+.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure scripts/ is on the path so we can import auth
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from flightcheck.runner import FlightCheckRunner, save_results, Status
from flightcheck.graph_client import GraphClient
from flightcheck.pp_admin_client import PPAdminClient, derive_environment_id
from flightcheck.pva_client import PVAClient

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
    "provision": [
        ("Environment", run_environment_checks),
        ("External Systems", run_external_systems_checks),
        ("Workday", run_workday_checks),
    ],
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
    parser.add_argument(
        "--config",
        help="Path to config JSON file (default: .local/config.json). "
             "Allows callers like /provision to pass a custom config "
             "without overwriting .local/config.json.",
    )
    args = parser.parse_args()

    # Load config
    config_path = args.config or os.path.join(".local", "config.json")
    if not os.path.exists(config_path):
        print(f"ERROR: {config_path} not found. Run /setup first (or pass --config).")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    env_url = config.get("dataverseEndpoint", "")
    if not env_url:
        print(f"ERROR: No dataverseEndpoint in {config_path}.")
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

    # Derive PP environment ID — prefer config value (provision writes it),
    # fall back to Dataverse organizations query.  The `environmentid` column
    # does not exist on all Dataverse builds (missing in some preprod rings),
    # so the config override is the reliable path for /provision callers.
    env_id = config.get("envId") or config.get("environmentId")
    if env_id:
        env_id = env_id.lower().strip("{}")
        print(f"Environment ID (from config): {env_id}")
    else:
        print("Deriving Power Platform environment ID...")
        env_id = derive_environment_id(env_url, dv_token)
        if env_id:
            print(f"Environment ID: {env_id}")
        else:
            print("WARNING: Could not derive environment ID. Some checks may be limited.")

    # Gate Microsoft Graph auth on scope. Graph is needed for license,
    # role, and Entra checks (prerequisites / authentication / environment / full).
    # Narrow scopes like `provision`, `workday`, `local`, `external` only
    # run Dataverse + Workday checks and do not need Graph. Skipping Graph
    # for these scopes avoids an interactive browser sign-in that would
    # hang the /provision flow for users without a cached Graph token.
    # (See test-run4-details.md trace for the original failure mode.)
    graph = None
    if args.scope in ("full", "prerequisites", "authentication", "environment"):
        print("Authenticating to Microsoft Graph...")
        graph = GraphClient(tenant_id)
        try:
            graph.authenticate()
            print("  Graph: OK")
        except Exception as e:
            print(f"  Graph: WARNING — {e}")
            print("  (Some checks will be skipped)")
            graph = None
    else:
        print("Skipping Microsoft Graph auth (not required for this scope).")

    # Read ring from config (provision writes it; default to prod for
    # existing /setup configs that don't have it).
    ring = config.get("ring", "prod")

    print("Authenticating to Power Platform Admin API...")
    pp_admin = PPAdminClient(tenant_id, ring=ring)
    try:
        pp_admin.authenticate()
        print("  Power Platform: OK")
    except Exception as e:
        print(f"  Power Platform: WARNING — {e}")
        print("  (Some checks will be skipped)")

    # Gate PVA (Copilot Studio Island Gateway) auth on scope.
    # Only CONFIG-013 needs PVA today, and it lives in run_local_file_checks.
    # Authenticating unconditionally would prompt for a second interactive login
    # on scopes like --scope prerequisites that don't need it.
    pva = None
    if args.scope in ("full", "local"):
        print("Authenticating to Copilot Studio (Island Gateway)...")
        pva = PVAClient(tenant_id, env_url)
        try:
            pva.authenticate()
            if pva.is_configured:
                print("  Copilot Studio: OK")
            else:
                print("  Copilot Studio: WARNING — Could not discover gateway URL")
                print("  (Knowledge source status check will use local-only validation)")
        except Exception as e:
            print(f"  Copilot Studio: WARNING — {e}")
            print("  (Knowledge source status check will use local-only validation)")
            pva = None
    else:
        print("Skipping Copilot Studio auth (not required for this scope).")

    # --- Build runner ---
    runner = FlightCheckRunner(scope=args.scope)
    runner.config = config
    runner.env_url = env_url
    runner.dv_token = dv_token
    runner.env_id = env_id
    runner.graph = graph
    runner.pp_admin = pp_admin
    runner.pva = pva

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

    # Print blocking checks (failures + provision-scope blockers)
    blocking_statuses = {Status.FAILED.value}
    if args.scope == "provision":
        blocking_statuses |= {Status.ERROR.value, Status.NOT_CONFIGURED.value}
    blockers = [r for r in result.results if r.status in blocking_statuses]
    if blockers:
        print(f"\n  BLOCKING CHECKS ({len(blockers)}):\n")
        for r in blockers:
            icon = "❌" if r.status == Status.FAILED.value else "🚫"
            print(f"    {icon} {r.checkpoint_id} [{r.status}]: {r.result}")
            if r.remediation:
                print(f"       → {r.remediation}")
        print()

    # Save results
    save_results(result, args.output)

    # Exit code: non-zero when overall verdict is NOT_READY
    sys.exit(1 if result.overall == "NOT_READY" else 0)


if __name__ == "__main__":
    main()
