#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record the SN-RUN-001 active ServiceNow managed-connector probe (AC13
live-capture spike).

This is the ServiceNow twin of the connector-bound Workday probe. It stands
up ONE throwaway Power Automate cloud flow bound to the maker's existing
managed ServiceNow connection, runs ONE read-only ServiceNow operation through
the real managed connector (the AzureConnectors egress path the agent actually
uses), reads the synchronous result, then ALWAYS deletes the flow. It drives
the shared harness ``live_egress_probe.run_connector_probe`` exactly as the
live check does; nothing about the lifecycle is reimplemented here.

WARNING - THIS RECORDER MUTATES THE TENANT
------------------------------------------
It CREATES, ACTIVATES and DELETES a real cloud flow (the kit's only
tenant-mutating step). It is READ-ONLY against ServiceNow: the connector
operation is drawn from a read-only allowlist (default ``GetRecords`` / List
Records) and never writes. Run ONLY in a test tenant you own whose DLP allows
the ServiceNow connector. The flow is named deterministically
(``flightcheck-sn-run-001-probe``); a crashed prior run is swept by name on
the next run.

What AC13 needs this recorder to CONFIRM (the three open questions the story
lists - do NOT guess, capture the answer):
  1. The exact read-only ServiceNow connector operation id + parameters that
     succeeds against a real ServiceNow connection. Default candidate:
     ``GetRecords`` (List Records). Override with ESS_SN_PROBE_OPERATION_ID.
  2. ServiceNow faultstring granularity: does the connector separate
     endpoint-config vs authorization vs business-rule errors, or collapse
     them into one status (e.g. HTTP 400 / 500)? Pass a list of operations
     via ESS_SN_PROBE_OPERATIONS to probe several shapes in one run and read
     the (status_code, error_code) each returns.
  3. Whether a FlightCheck-authored transient flow can resolve the maker's
     ServiceNow connection under the running identity (connection sharing /
     RBAC). A ``create``/``activate`` failure or an authorization error here
     is the empirical answer.

Auth (identical to the INFRA-003 recorder):
  * Dataverse Web API token  -> auth.authenticate(env_url)
  * Power Automate token + BAP env id -> PPAdminClient(tenant).authenticate()
  These are the same four inputs the live check resolves in
  flightcheck/checks/infrastructure.py:_live_probe_context
  (env_url, dv_token, env_id, flow_headers).

The probe reads the two signals the connector's synchronous response exposes:
    @outputs('<action>')?['statusCode']   -> HTTP status
    @actions('<action>')?['code']         -> connector action code
The human-readable ServiceNow error.message is NOT available synchronously
(it sits behind the SAS-signed outputsLink FlightCheck never fetches), which
is exactly why the error map's HTTP 400 case is a single honest indeterminate
bucket. This capture confirms which of those two signals actually populate.

Pre-reqs:
    pip install -e .[test]
    $env:ESS_DATAVERSE_URL = "https://orgXXXX.crm.dynamics.com"
    # optional overrides:
    $env:ESS_SN_PROBE_OPERATION_ID = "GetRecords"
    $env:ESS_SN_PROBE_PARAMS_JSON  = '{"tableType":"sys_user","sysparm_limit":"1"}'
    $env:ESS_SN_PROBE_OPERATIONS   = "GetRecords,GetRecord"   # granularity probe

    python tests\\captures\\record_flightcheck_sn_connector_probe.py

Output: tests/fixtures/cassettes/flightcheck_sn_connector_probe.yaml

POST-RECORD SCRUB: the listCallbackUrl response and triggered run URL carry a
SAS ``sig=`` and bearer tokens. ``_common.py`` scrubs GUIDs, ``sig=``, and
Authorization; eyeball tests/fixtures/cassettes/.raw/ for any surviving
ServiceNow instance host, integration-user name, or record data before
committing.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# scripts/ is on sys.path via the kit; add it for standalone execution.
_KIT_SCRIPTS = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "scripts"
sys.path.insert(0, str(_KIT_SCRIPTS))

from _common import announce, build_cassette, chdir_kit_root, confirm_or_exit, get_dataverse_url  # noqa: E402

_PROBE_FLOW_NAME = "flightcheck-sn-run-001-probe"


def _read_operations() -> list[str]:
    """Operation ids to probe. A comma-list characterizes fault granularity
    (open question 2); a single id (default) just confirms the happy path."""
    multi = os.environ.get("ESS_SN_PROBE_OPERATIONS", "").strip()
    if multi:
        return [op.strip() for op in multi.split(",") if op.strip()]
    single = os.environ.get("ESS_SN_PROBE_OPERATION_ID", "").strip()
    return [single or "GetRecords"]


def _read_params() -> dict:
    raw = os.environ.get("ESS_SN_PROBE_PARAMS_JSON", "").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise SystemExit("ESS_SN_PROBE_PARAMS_JSON must be a JSON object.")
    return parsed


def main() -> None:
    announce("flightcheck_sn_connector_probe (SN-RUN-001 active, AC13)")

    print()
    print("!" * 78)
    print("! THIS RECORDER MUTATES THE TENANT: it CREATES, ACTIVATES and DELETES")
    print("! a cloud flow. It is READ-ONLY against ServiceNow. Run ONLY in a test")
    print("! tenant you own whose DLP allows the ServiceNow connector.")
    print("!" * 78)
    print()

    env_url = get_dataverse_url().rstrip("/")
    if not env_url:
        print("ERROR: set ESS_DATAVERSE_URL to the target environment's Dataverse URL.")
        sys.exit(1)

    operations = _read_operations()
    params = _read_params()
    print(f"  Dataverse URL: {env_url}")
    print(f"  Operation(s):  {', '.join(operations)}")
    print(f"  Parameters:    {params or '(none)'}")
    print("  Endpoint:      managed ServiceNow connector via transient Power Automate flow")
    print()
    confirm_or_exit()
    chdir_kit_root()

    import auth
    from flightcheck import live_egress_probe
    from flightcheck.checks.servicenow import (
        _SN_CONNECTOR_API_ID,
        _SN_CONNECTOR_NAME,
        _SN_PROBE_ACTION_NAME,
        _is_servicenow_connection,
        _servicenow_runtime_source,
    )
    from flightcheck.checks.connections import get_connection_status
    from flightcheck.pp_admin_client import PPAdminClient

    dv_token = auth.authenticate(env_url)
    tenant_id = auth.discover_tenant(env_url)
    pp = PPAdminClient(tenant_id=tenant_id)
    pp.authenticate()
    env_id = pp.find_environment_id_by_dataverse_url(env_url)
    if not env_id:
        print(f"ERROR: no BAP environment matched Dataverse URL {env_url!r}.")
        sys.exit(1)
    print(f"  Resolved env_id: {env_id}")

    conns = pp.get_connections(env_id)
    if not isinstance(conns, list):
        print("ERROR: could not list Power Platform connections.")
        sys.exit(1)
    servicenow = [c for c in conns if isinstance(c, dict) and _is_servicenow_connection(c)]
    connected = [c for c in servicenow if get_connection_status(c) == "Connected"]
    if not connected:
        print(
            f"ABORT: found {len(servicenow)} ServiceNow connection(s), "
            f"{len(connected)} Connected. Connect ServiceNow first."
        )
        return
    forced_id = os.environ.get("ESS_SN_PROBE_CONNECTION_ID", "").strip()
    if forced_id:
        forced = [c for c in connected if (c.get("name") or "") == forced_id]
        if not forced:
            print(
                f"ABORT: ESS_SN_PROBE_CONNECTION_ID={forced_id!r} is not a Connected "
                f"ServiceNow connection in this env."
            )
            return
        chosen = forced[0]
    else:
        service_account = [c for c in connected if _servicenow_runtime_source(c) != "invoker"]
        chosen = (service_account or connected)[0]
    connection_id = chosen.get("name") or ""
    identity_path = (
        "service-account / integration-user"
        if _servicenow_runtime_source(chosen) != "invoker"
        else "OAuth-invoker (maker/employee)"
    )
    print(f"  ServiceNow connection: {connection_id} [{identity_path}]")

    live_env = {
        "env_url": env_url,
        "dv_token": dv_token,
        "env_id": env_id,
        "flow_headers": pp.flow_headers,
    }

    summary: list[tuple[str, object]] = []
    with build_cassette("flightcheck_sn_connector_probe"):
        # Sweep any orphan from a crashed prior run (AC7 idempotency).
        live_egress_probe.cleanup_orphan_probe_flows(
            env_url, dv_token, probe_flow_name=_PROBE_FLOW_NAME
        )
        for op in operations:
            action = live_egress_probe.ConnectorProbeAction(
                connector_api_id=_SN_CONNECTOR_API_ID,
                connection_id=connection_id,
                operation_id=op,
                parameters=params,
                action_name=_SN_PROBE_ACTION_NAME,
                connection_ref_key=_SN_CONNECTOR_NAME,
            )
            print(f"\n  >>> probing operation '{op}'...")
            try:
                res = live_egress_probe.run_connector_probe(
                    **live_env,
                    action=action,
                    probe_flow_name=_PROBE_FLOW_NAME,
                    description="FlightCheck SN-RUN-001 transient ServiceNow connector probe.",
                )
            finally:
                live_egress_probe.cleanup_orphan_probe_flows(
                    env_url, dv_token, probe_flow_name=_PROBE_FLOW_NAME
                )
            line = (
                f"succeeded={res.succeeded} status={res.action_status} "
                f"http={res.status_code} code={res.error_code} stage={res.stage}"
            )
            print(f"      -> {line}")
            print(f"      -> detail: {res.detail}")
            summary.append((op, line))

    print()
    print("Cassette written: tests/fixtures/cassettes/flightcheck_sn_connector_probe.yaml")
    print()
    print("AC13 open-question evidence (record the go / no-go from this):")
    print(f"  identity path exercised: {identity_path}")
    print("  operation -> (succeeded, status, http, code):")
    for op, line in summary:
        print(f"    {op}: {line}")
    print()
    print("Interpretation guide:")
    print("  Q1 read-only op: the operation whose result is succeeded=True is the")
    print("     confirmed read-only op id -> set _SN_DEFAULT_READ_OPERATION.")
    print("  Q2 granularity: compare the (http, code) across operations. If a")
    print("     wrong endpoint and a business fault BOTH return HTTP 400, the")
    print("     error map's single indeterminate 400 bucket is correct; if they")
    print("     split (e.g. 404 vs 422), tighten _servicenow_probe_layer.")
    print("  Q3 connection resolution: a clean create/activate + a non-auth")
    print("     result proves the transient flow resolves the maker's connection")
    print("     under the running identity. An 'authorization layer' result or a")
    print("     create/activate failure is a NO-GO signal to record.")
    print()
    print("Then add a row to tests/fixtures/cassettes/INDEX.md and eyeball .raw/")
    print("for any ServiceNow instance host, integration-user name, or record data.")


if __name__ == "__main__":
    main()
