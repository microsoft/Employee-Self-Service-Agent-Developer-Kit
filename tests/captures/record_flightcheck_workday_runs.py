#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering the Power Automate *runtime* run-history
endpoint used by WD-RUN-001 (Workday shared-flow run health).

Endpoint (runtime / maker scope — NOT /scopes/admin):
    GET https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple
        /environments/{bapEnvId}/flows/{flowId}/runs?api-version=2016-11-01

Auth: Microsoft Entra bearer token with the
`service.flow.microsoft.com//.default` audience — the same token the kit's
``PPAdminClient`` already acquires for flow listing. Run history requires
owner/maker access to the flow.

The check reads two fields per run:
    properties.status         -> "Succeeded" / "Failed" / ...
    properties.response.name  -> the flow's success-vs-failure Response action

This recorder discovers the Workday shared flow(s) automatically from the
flow inventory (display name contains "Workday") and records their run
history. To capture the FAILURE shapes too, generate a failed run before
recording (e.g. exercise a Workday scenario whose template config points at
an invalid Workday service, or whose security domain was revoked) — see the
WD-RUN-001 comment in checks/workday.py for the empirically-confirmed shapes.

Pre-reqs:
    pip install -e .[test]
    $env:ESS_DATAVERSE_URL = "https://orgXXXX.crm.dynamics.com"

    python tests\\captures\\record_flightcheck_workday_runs.py

Output: tests/fixtures/cassettes/flightcheck_workday_runs.yaml

⚠️ POST-RECORD SCRUB: the run records carry
``properties.correlation.clientKeywords`` with the agent's BotSchemaName /
CdsBotId. The global redactor scrubs GUIDs; eyeball the cassette for any
remaining BotSchemaName values before committing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# scripts/ is on sys.path via the kit; add it for standalone execution.
_KIT_SCRIPTS = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "scripts"
sys.path.insert(0, str(_KIT_SCRIPTS))

from _common import announce, build_cassette, chdir_kit_root, confirm_or_exit, get_dataverse_url


def main() -> None:
    announce("Power Automate runtime run history (Workday WD-RUN-001)")

    env_url = get_dataverse_url()
    if not env_url:
        print("ERROR: set ESS_DATAVERSE_URL to the target environment's Dataverse URL.")
        sys.exit(1)

    print(f"  Dataverse URL: {env_url}")
    print("  Endpoint:      GET api.flow.microsoft.com/.../environments/{env}/flows/{flow}/runs")
    print()
    confirm_or_exit()
    chdir_kit_root()

    from flightcheck.pp_admin_client import PPAdminClient

    with build_cassette("flightcheck_workday_runs"):
        client = PPAdminClient(tenant_id="organizations")
        client.authenticate()

        bap_env_id = client.find_environment_id_by_dataverse_url(env_url)
        if not bap_env_id:
            print("  ABORT: could not resolve BAP environment id for that Dataverse URL.")
            return
        print(f"  BAP env id: {bap_env_id}")

        flows = client.get_flows(bap_env_id)
        if isinstance(flows, dict) and "_error" in flows:
            print(f"  ABORT: could not list flows: {flows['_error']}")
            return

        wd_flows = [
            f for f in flows
            if "workday" in (f.get("properties", {}).get("displayName", "") or "").lower()
        ]
        if not wd_flows:
            print("  ABORT: no Workday flows found in this environment.")
            return

        for f in wd_flows:
            flow_id = f.get("name")
            fname = f.get("properties", {}).get("displayName", flow_id)
            print(f"  GET runs for '{fname}' ({flow_id})...")
            runs = client.get_flow_runs(bap_env_id, flow_id)
            if isinstance(runs, dict) and "_error" in runs:
                print(f"    -> {runs['_error']}")
                continue
            statuses: dict[str, int] = {}
            for run in runs:
                p = run.get("properties", {})
                key = f"{p.get('status')}/{(p.get('response') or {}).get('name')}"
                statuses[key] = statuses.get(key, 0) + 1
            print(f"    -> {len(runs)} run(s): {statuses}")

    print()
    print("Cassette written: tests/fixtures/cassettes/flightcheck_workday_runs.yaml")
    print("Eyeball it for BotSchemaName / customer identifiers before committing,")
    print("and confirm it contains at least one failure-branch run (response.name")
    print("!= Respond_to_Copilot_with_Success) so the BAD-state test is cassette-backed.")


if __name__ == "__main__":
    main()
