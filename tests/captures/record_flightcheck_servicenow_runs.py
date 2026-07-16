#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record a cassette covering the Power Automate *runtime* run-history
endpoint used by SN-RUN-001 (ServiceNow flow run health).

This is the ServiceNow twin of ``record_flightcheck_workday_runs.py``. It
exists to CONFIRM how the ServiceNow flows report success vs failure in run
history. Confirmed live 2026-06 (see the CONFIRMED model below): ServiceNow is
a MULTI-FLOW orchestration whose user-facing orchestrator run responds to
Copilot with ``Respond_to_Copilot`` on success and
``Respond_to_Copilot_-_Failure`` on failure. Orchestrator failures surface as
``status=Failed`` (unlike Workday's caught ``status=Succeeded`` faults);
child/utility flow runs respond to their parent and are non-scoring.

Endpoint (runtime / maker scope — NOT /scopes/admin) — identical to the
Workday recorder; only the flow display-name filter differs:
    GET https://api.flow.microsoft.com/providers/Microsoft.ProcessSimple
        /environments/{bapEnvId}/flows/{flowId}/runs?api-version=2016-11-01

Auth: Microsoft Entra bearer token with the
`service.flow.microsoft.com//.default` audience — the same token the kit's
``PPAdminClient`` already acquires for flow listing. Run history requires
owner/maker access to the flow.

The check reads two fields per run:
    properties.status         -> "Succeeded" / "Failed" / ...
    properties.response.name  -> the flow's success-vs-failure Response action

This recorder discovers the ServiceNow shared flow(s) automatically from the
flow inventory (display name contains "ServiceNow") and records their run
history. To capture the FAILURE shapes too, generate a failed run before
recording (e.g. exercise a ServiceNow scenario whose template config points at
an invalid table, or whose ACL/role was revoked for the signed-in user) — see
the SN-RUN-001 comment in checks/servicenow.py for the expected shapes.

The summary printed at the end groups every run by ``status/response.name`` so
you can confirm, at a glance, the CONFIRMED ServiceNow model (verified live
2026-06 across ESS_MODEL_UPGRADE_PREVIEW_FRE_2, test_CA, and SunbreakDev
Workday+Snow):
  * orchestrator SUCCESS -> ``Succeeded/Respond_to_Copilot``
  * orchestrator FAILURE -> ``Failed/Respond_to_Copilot_-_Failure``
  * child/utility flows   -> non-Copilot actions
    (``Respond_back_to_Orchestrator_-_Success``,
    ``Respond_to_a_Power_App_or_flow[_-_Success]``, ...) — NON-scoring.
The check (``_classify_run`` in checks/servicenow.py) scores ONLY runs whose
``response.name`` starts with ``Respond_to_Copilot``; the success action is
``Respond_to_Copilot`` (NOT ``Respond_to_Copilot_with_Success`` — that is the
Workday name). If a future tenant shows a different success action, update
``_SN_SUCCESS_RESPONSE_ACTION`` in checks/servicenow.py.

Pre-reqs:
    pip install -e .[test]
    $env:ESS_DATAVERSE_URL = "https://orgXXXX.crm.dynamics.com"

    python tests\\captures\\record_flightcheck_servicenow_runs.py

Output: tests/fixtures/cassettes/flightcheck_servicenow_runs.yaml

NOTE on cassettes: the runtime runs endpoint is product-agnostic (same
method + path + response shape as the Workday capture), so per the validated-
tier "same endpoint" rule the existing ``flightcheck_workday_runs.yaml`` already
backs the API contract for SN-RUN-001. This recorder's primary job is to
EMPIRICALLY CONFIRM the ServiceNow flow's response-branch behaviour. Commit the
resulting ``flightcheck_servicenow_runs.yaml`` only if you want a ServiceNow-
specific capture on record (then add a row to INDEX.md "Confirmed endpoints").

WARNING — POST-RECORD SCRUB: the run records carry
``properties.correlation.clientKeywords`` with the agent's BotSchemaName /
CdsBotId. The global redactor scrubs GUIDs; eyeball the cassette for any
remaining BotSchemaName values before committing.
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ is on sys.path via the kit; add it for standalone execution.
_KIT_SCRIPTS = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "scripts"
sys.path.insert(0, str(_KIT_SCRIPTS))

from _common import announce, build_cassette, chdir_kit_root, confirm_or_exit, get_dataverse_url  # noqa: E402


def main() -> None:
    announce("Power Automate runtime run history (ServiceNow SN-RUN-001)")

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

    with build_cassette("flightcheck_servicenow_runs"):
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

        sn_flows = [
            f for f in flows
            if "servicenow" in (f.get("properties", {}).get("displayName", "") or "").lower()
        ]
        if not sn_flows:
            print("  ABORT: no ServiceNow flows found in this environment.")
            return

        overall: dict[str, int] = {}
        for f in sn_flows:
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
                overall[key] = overall.get(key, 0) + 1
            print(f"    -> {len(runs)} run(s): {statuses}")

    print()
    print("Cassette written: tests/fixtures/cassettes/flightcheck_servicenow_runs.yaml")
    print("ServiceNow run shapes seen (status/response.name -> count):")
    for key, count in sorted(overall.items()):
        print(f"    {key}: {count}")
    print()
    print("VERIFY vs the CONFIRMED ServiceNow model:")
    print("  * success runs should be 'Succeeded/Respond_to_Copilot'")
    print("  * orchestrator failures should be 'Failed/Respond_to_Copilot_-_Failure'")
    print("  * child flows ('Respond_back_to_Orchestrator', 'Respond_to_a_Power_App_or_flow')")
    print("    are non-scoring.")
    print("If the success action name differs, update _SN_SUCCESS_RESPONSE_ACTION")
    print("in solutions/ess-maker-skills/scripts/flightcheck/checks/servicenow.py.")
    print("Eyeball the cassette for BotSchemaName / customer identifiers before committing.")


if __name__ == "__main__":
    main()
