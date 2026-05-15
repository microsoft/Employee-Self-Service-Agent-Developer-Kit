# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Wire Flow Runtime Bindings

Enables Workday flows post-ISV-install and prints manual CPS wiring
instructions (the user-connections API requires legacy PVA permissions
not grantable to custom Entra apps — see step3.md §3.9).

Usage:
    python scripts/wire_flow_bindings.py \\
        --env-url https://orgxyz.crm.dynamics.com \\
        --persona hr --workday-connection-name MyWorkdayConn

Exit codes: 0 success, 1 auth, 2 flow discovery/enable, 3 unexpected.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import requests
except ImportError:
    print("ERROR: 'requests' required. Run: pip install -r scripts/requirements.txt", file=sys.stderr)
    sys.exit(3)

from auth import authenticate, query_all, update_record
from pp_helpers import VALID_PERSONAS


def discover_workday_flows(env_url, dataverse_token, persona):
    """Query workflows table for Workday-related flows.

    Persona is validated against VALID_PERSONAS before OData interpolation
    (defense in depth against injection if argparse is bypassed).
    """
    if persona.lower() not in VALID_PERSONAS:
        raise ValueError(f"persona must be one of {sorted(VALID_PERSONAS)}, got {persona!r}")
    persona_specific = f"ESS {persona.upper()} Workday"
    name_filter = (
        f"(name eq '{persona_specific}' or name eq 'WorkdayRESTExecution')"
    )
    rows = query_all(
        env_url,
        dataverse_token,
        "workflows",
        "workflowid,name,statecode,statuscode",
        name_filter,
    )
    return rows


def enable_workflow_if_disabled(env_url, dataverse_token, workflow):
    """Set statecode=1, statuscode=2 (Activated) on a workflow if not already."""
    wf_id = workflow.get("workflowid")
    current_state = workflow.get("statecode")
    if current_state == 1:
        return {"workflowId": wf_id, "name": workflow.get("name"), "action": "already-enabled"}

    try:
        update_record(env_url, dataverse_token, "workflows", wf_id, {"statecode": 1, "statuscode": 2})
        return {"workflowId": wf_id, "name": workflow.get("name"), "action": "enabled"}
    except Exception as e:
        return {"workflowId": wf_id, "name": workflow.get("name"), "action": "enable-failed", "error": str(e)[:200]}


def main():
    parser = argparse.ArgumentParser(description="Enable Workday flows and print manual wiring instructions")
    parser.add_argument("--env-url", required=True, help="Dataverse env URL")
    parser.add_argument("--persona", required=True, choices=["hr", "it"], help="ESS persona (hr or it)")
    parser.add_argument("--workday-connection-name", default="", help="Workday connection display name (for instructions)")
    args = parser.parse_args()

    # 1) Dataverse auth.
    dataverse_token = authenticate(args.env_url)

    # 2) Discover the Workday flows in this env.
    flows = discover_workday_flows(args.env_url, dataverse_token, args.persona)
    if not flows:
        print(
            "ERROR: no Workday flows found in env. Workday ISV install may not have completed, "
            "or the flow names do not match expected patterns.",
            file=sys.stderr,
        )
        sys.exit(2)

    # Verify both expected flows are present.
    persona_specific = f"ESS {args.persona.upper()} Workday"
    expected_names = {persona_specific, "WorkdayRESTExecution"}
    found_names = {f.get("name") for f in flows}
    missing = expected_names - found_names
    if missing:
        print(
            f"ERROR: missing expected Workday flow(s): {missing}. "
            f"Found: {found_names}. Workday ISV install may be incomplete.",
            file=sys.stderr,
        )
        sys.exit(2)

    print(f"Found {len(flows)} Workday flow(s):", file=sys.stderr)
    for f in flows:
        print(f"  - {f.get('name')} (statecode={f.get('statecode')})", file=sys.stderr)

    # 3) Enable any disabled flows.
    enable_results = []
    for f in flows:
        result = enable_workflow_if_disabled(args.env_url, dataverse_token, f)
        enable_results.append(result)
        print(f"  enable: {result.get('name')}: {result.get('action')}", file=sys.stderr)

    # 4) Output results + manual wiring instructions.
    conn_name = args.workday_connection_name or "(your Workday connection)"
    flow_names = sorted(found_names)

    output = {
        "flowEnables": enable_results,
        "manualWiringRequired": True,
        "instructions": {
            "summary": "Flow runtime bindings must be wired manually in Copilot Studio.",
            "reason": "The user-connections API requires legacy PowerVirtualAgents.* permissions not available in the current API catalog.",
            "steps": [
                "Open Copilot Studio (copilotstudio.microsoft.com or copilotstudio.preview.microsoft.com for preprod)",
                "Switch to the target environment",
                f"Open the Employee Self-Service {args.persona.upper()} agent -> Actions",
                *[f"Select '{fn}' -> Connect -> choose '{conn_name}'" for fn in flow_names],
                "For EACH flow: click 'See details' under Manage -> Connection parameters tab -> toggle 'Allow permission to share parameters' ON -> Save",
            ],
        },
    }
    print(json.dumps(output, indent=2))

    enable_failures = [r for r in enable_results if r.get("action") == "enable-failed"]
    sys.exit(0 if not enable_failures else 2)


if __name__ == "__main__":
    main()
