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
    servicenow      — ServiceNow deep validation
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
from flightcheck.pva_client import PVAClient

# Check modules
from flightcheck.checks.prerequisites import run_prerequisites_checks
from flightcheck.checks.environment import run_environment_checks
from flightcheck.checks.authentication import run_authentication_checks
from flightcheck.checks.external_systems import run_external_systems_checks
from flightcheck.checks.workday import run_workday_checks
from flightcheck.checks.servicenow import run_servicenow_checks
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
    "servicenow": [
        ("External Systems", run_external_systems_checks),
        ("ServiceNow", run_servicenow_checks),
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
    ("ServiceNow", run_servicenow_checks),
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
        "--environment-url",
        help="Override the Dataverse environment URL (used by environment_picker.py)",
    )
    parser.add_argument(
        "--environment-id",
        help="Override the Power Platform environment ID (used by environment_picker.py)",
    )
    args = parser.parse_args()

    # Load config
    config_path = os.path.join(".local", "config.json")
    if not os.path.exists(config_path):
        print("ERROR: .local/config.json not found. Run /setup first.")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    env_url = args.environment_url or config.get("dataverseEndpoint", "")
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
        pp_admin = None

    # Derive the BAP environment ID. This MUST run after pp_admin is
    # authenticated: the correct id comes from the BAP env list
    # (matched on linkedEnvironmentMetadata.instanceUrl), not from the
    # Dataverse WhoAmI OrganizationId (which is a different guid for
    # almost every tenant — see derive_environment_id docstring).
    #
    # derive_environment_id intentionally tolerates pp_admin=None and
    # falls back to the WhoAmI/OrganizationId path so that operators
    # whose Power Platform sign-in failed (network issue, cancelled
    # browser, MSAL error) can still run the substantial fraction of
    # FlightCheck that doesn't need pp_admin — PRE-* (license SKUs),
    # AUTH-*, WD-ENV-* (Workday env vars / ISU format), WD-WF-*
    # (Workday SOAP runtime), and CONFIG-* (local agent / topic /
    # knowledge source). Erroring out here would block those.
    print("Deriving Power Platform environment ID...")
    if args.environment_id:
        env_id = args.environment_id
        print(f"Environment ID: {env_id} (provided via --environment-id)")
    else:
        env_id = derive_environment_id(env_url, dv_token, pp_admin=pp_admin)
        if env_id and pp_admin is not None:
            print(f"Environment ID: {env_id}")
        elif env_id:
            print(
                f"Environment ID: {env_id} (Dataverse OrganizationId fallback "
                "— Power Platform sign-in failed, so BAP-scoped checks "
                "(ENV-*, EXT-*, WD-CONN-*) will be skipped)"
            )
        else:
            print(
                f"WARNING: Could not derive environment ID for {env_url}. "
                "BAP-scoped checks (ENV-*, EXT-*, WD-CONN-*) will be skipped; "
                "license, auth, Workday env-var, Workday SOAP, and local-file "
                "checks will still run."
            )

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
    print(f"  [PASS] Passed:         {result.passed}")
    print(f"  [FAIL] Failed:         {result.failed}")
    print(f"  [WARN] Warnings:       {result.warnings}")
    print(f"  [INFO] Not Configured: {result.not_configured}")
    print(f"  Duration:              {result.duration_secs}s")
    print()

    if result.overall == "READY":
        print("  [PASS] READY FOR DEPLOYMENT")
    elif result.overall == "READY_WITH_WARNINGS":
        print("  [WARN] READY WITH WARNINGS")
    else:
        print("  [FAIL] NOT READY -- ISSUES FOUND")

    print("=" * 64)

    # Print failures
    failures = [r for r in result.results if r.status == Status.FAILED.value]
    if failures:
        print(f"\n  FAILED CHECKS ({len(failures)}):\n")
        for r in failures:
            print(f"    [FAIL] {r.checkpoint_id}: {r.result}")
            if r.remediation:
                print(f"       -> {r.remediation}")
        print()

    # Save results
    save_results(result, args.output)

    # Exit code
    sys.exit(1 if result.failed > 0 else 0)


if __name__ == "__main__":
    main()
