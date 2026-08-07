#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Recorder — connector-bound Workday probe flow (WD-RUN-001 v2).

STATUS: VALIDATED capture wrapper. This recorder produced the committed
cassette `tests/fixtures/cassettes/flightcheck_wd_connector_probe.yaml`
from a REAL tenant run (create 201, activate 204, listCallbackUrl 200,
invoke 200, delete 204 for read-only `GetWorkerMe`; see the cassette's
INDEX.md row). It is a capture/recording wrapper, NOT a production
FlightCheck code path -- do not import it from production checks. It is
kept in-repo so the `validated` cassette it backs can be re-captured and
audited. Because it MUTATES the tenant (see the warning below), run it
ONLY against a disposable/test tenant with a read-only Workday operation.

WHAT THIS RECORDER CONFIRMED (the two questions the v2 design turned on)
-----------------------------------------------------------------------
The shipped WD-RUN-001 is passive (reads flow-run history). The v2 design
adds an ACTIVE probe that stands up a transient Power Automate flow bound
to the maker's EXISTING managed Workday connection (`shared_workdaysoap`),
runs ONE read-only Workday operation over the real AzureConnectors
managed-connector egress path, reads the result, then deletes the flow.
This recorder captured evidence for the two questions that gated the build:

  Q1 (make-or-break): Can a FlightCheck-authored transient flow REFERENCE
     and INVOKE the maker's existing Workday connection under the running
     identity? The ESS OAuthUser connection (`_ff0df`) uses
     runtimeSource: invoker (it authenticates AS the employee), so an
     admin/maker-triggered probe flow may authenticate as the wrong
     principal or be blocked by connection-sharing / RBAC. The capture
     confirmed a GO with `source: "Embedded"` binding by connection id.

  Q2: Is the connector error granular enough to separate an endpoint-config
     failure from a business-rule failure? If it collapses to a generic
     500 the design's AC3 cannot be met.

WHY A DEDICATED RECORDER (not INFRA-003's)
------------------------------------------
INFRA-003 (`tests/captures/record_infra003_flow.py`, cassette
`flightcheck_infra003_flow.yaml`) proved the create/activate/
listCallbackUrl/invoke/delete lifecycle, but with `connectionReferences={}`
and a NATIVE HTTP action. That travels the LogicApps native-HTTP egress
path, NOT the AzureConnectors managed-connector path Workday actually uses.
This recorder keeps the SAME proven lifecycle and changes exactly two
things (the delta the spike must prove):
  1. `properties.connectionReferences` is POPULATED with the maker's
     Workday connection (discovered, not invented).
  2. The single action is an `OpenApiConnection` action bound to
     `shared_workdaysoap`, NOT a native `Http` action.

GROUNDING (what the candidate shape is based on, per tests/AGENTS.md)
--------------------------------------------------------------------
* The `OpenApiConnection` action shape + `connectionReferences` entry shape
  are taken from REAL deployed ESS Workday shared flows read via
  `GET .../flows/{id}` (observed operationId `RaaS_Operation` on
  `shared_workdaysoap`, host `{apiId, operationId, connectionName}`; ref
  entries carry `connectionReferenceLogicalName` + `apiDefinition`).
* The Dataverse `workflow`-row create/activate/delete envelope and the
  `listCallbackUrl` + SAS invoke are taken verbatim from the proven
  INFRA-003 lifecycle.
* The CREATE-time `connectionReferences` shape for a *newly authored*
  connector-bound flow was the ONE piece with no prior committed capture.
  Running this recorder against a real tenant confirmed it: the committed
  cassette `flightcheck_wd_connector_probe.yaml` is that capture, and the
  `source: "Embedded"` binding by connection id is what the cassette
  records (see INDEX.md, WD-RUN-001 v2 rows).

IMPORTANT — path fidelity caveat (AC2)
--------------------------------------
Deployed ESS flows call Workday two different ways: RaaS reads use a DIRECT
`shared_workdaysoap` OpenApiConnection action (what this probe replicates),
but GENERIC SOAP scenarios tunnel through a Dataverse plugin
(`msdyn_WorkdayXmlRequestPlugin` via `PerformUnboundAction`), which this
direct-connector probe does NOT replicate. So a GO here proves the
connector path for RaaS-style operations; it does not, by itself, prove the
plugin-tunneled path. Record which operation you probed.

WARNING — THIS RECORDER MUTATES THE TENANT
------------------------------------------
It CREATES, ACTIVATES, TRIGGERS and DELETES a real cloud flow bound to a
real Workday connection, and runs ONE Workday operation. Use ONLY:
  * a read-only Workday operation (default `RaaS_Operation` against a
    benign report you name), and
  * a disposable / test tenant whose data you own.
The flow is named deterministically (PROBE_FLOW_NAME) and is always deleted
in a `finally`; a crashed prior run is swept by name before create.

OPERATOR WORKFLOW (see the runbook for full detail)
---------------------------------------------------
1. Authenticate against your tenant (uses .local/.token_cache.bin; may pop
   an interactive sign-in the first time).
2. Set env vars in PowerShell:
     $env:ESS_DATAVERSE_URL       = "https://<your-tenant>.crm.dynamics.com"
     $env:ESS_WD_PROBE_OPERATION_ID = "RaaS_Operation"   # read-only op
     $env:ESS_WD_PROBE_PARAMS_JSON  = '{"accountName":"...","reportName":"...","reportInstanceName":""}'
   Optional binding overrides (else the recorder auto-discovers):
     $env:ESS_WD_PROBE_CONN_LOGICALNAME = "new_sharedworkdaysoap_d6081"
     $env:ESS_WD_PROBE_CONN_APIID       = "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"
     $env:ESS_WD_PROBE_CASSETTE         = "flightcheck_wd_connector_probe"
3. python tests\captures\record_flightcheck_wd_connector_probe.py
4. Read the on-screen summary; confirm the shapes listed at the end;
   eyeball tests/fixtures/cassettes/.raw/ for any surviving secret/PII;
   record the go/no-go on US 7500446 and the US 7670878 log.
"""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.parse import urlparse

from _common import (
    announce,
    build_cassette,
    chdir_kit_root,
    confirm_or_exit,
    get_dataverse_url,
)

# Deterministic DISPLAY NAME (the workflow `name` column). Distinct from the
# INFRA-003 probe name so the two spikes never collide. Cleanup + orphan
# detection key off this, so it MUST stay stable.
PROBE_FLOW_NAME = "flightcheck-wd-run-001-probe"

DATAVERSE_API = "/api/data/v9.2"
API_VERSION = "2016-11-01"
POLL_ATTEMPTS = 12
POLL_INTERVAL_S = 3

# Modern cloud flow: workflow.category == 5, workflow.type == 1 (Definition).
FLOW_CATEGORY = 5
FLOW_TYPE_DEFINITION = 1
STATECODE_ACTIVE = 1
STATECODE_DRAFT = 0

TRIGGER_NAME = "manual"
PROBE_ACTION_NAME = "Probe_Workday"
WORKDAY_CONNECTOR_API = "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"
WORKDAY_CONNECTOR_NAME = "shared_workdaysoap"
# The key we give our new flow's connection reference. Arbitrary but stable;
# the action's host.connectionName points at it.
PROBE_CONN_REF_KEY = "shared_workdaysoap"


def _discover_workday_binding(pp, env_id: str) -> dict | None:
    """Best-effort read of ONE Workday connection binding from the maker's
    existing flows.

    Returns a dict {logicalName, apiId} for a `shared_workdaysoap`
    connection reference, or None if none could be read. The operator can
    override via ESS_WD_PROBE_CONN_LOGICALNAME / ESS_WD_PROBE_CONN_APIID,
    which takes precedence over discovery.

    Grounding: mirrors how `checks/workday.py::_get_in_use_workday_connection
    _names` reads `properties.connectionReferences.{key}.apiId` /
    `apiDefinition.name`, and how the WD-CONN write-mapping recorder reads
    per-flow detail because the flow LIST does not always expand
    connectionReferences.
    """
    override_ln = os.environ.get("ESS_WD_PROBE_CONN_LOGICALNAME", "").strip()
    override_api = os.environ.get("ESS_WD_PROBE_CONN_APIID", "").strip()
    if override_ln:
        return {
            "logicalName": override_ln,
            "apiId": override_api or WORKDAY_CONNECTOR_API,
        }

    try:
        flows = pp.get_flows(env_id)
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort
        print(f"  discovery: get_flows failed ({type(exc).__name__}); "
              "supply ESS_WD_PROBE_CONN_LOGICALNAME to proceed.")
        return None
    if not isinstance(flows, list):
        print("  discovery: get_flows returned no list; supply "
              "ESS_WD_PROBE_CONN_LOGICALNAME to proceed.")
        return None

    # The flow LIST endpoint does NOT expand connectionReferences (confirmed
    # against a real full-install env: list-level refs are empty even when the
    # flow is Workday-bound). We MUST read each flow's DETAIL to see the
    # binding. Same reason the WD-CONN write-mapping recorder fetches detail.
    for f in flows:
        if not isinstance(f, dict):
            continue
        flow_id = f.get("name") or f.get("id")
        if not flow_id:
            continue
        try:
            detail = pp.get_flow(env_id, flow_id)
        except Exception:  # noqa: BLE001 - skip unreadable flows
            continue
        refs = (detail.get("properties") or {}).get("connectionReferences") or {}
        if not isinstance(refs, dict):
            continue
        for _key, ref in refs.items():
            if not isinstance(ref, dict):
                continue
            api_def = ref.get("apiDefinition") or {}
            api_id = (
                ref.get("apiId")
                or api_def.get("id")
                or (ref.get("api") or {}).get("name", "")
                or ""
            )
            if "workday" not in str(api_id).lower():
                continue
            logical = ref.get("connectionReferenceLogicalName") or ""
            if logical:
                print(f"  discovery: found Workday binding logicalName="
                      f"{logical!r} apiId={api_id!r}")
                return {"logicalName": logical, "apiId": str(api_id) or WORKDAY_CONNECTOR_API}
    print("  discovery: no shared_workdaysoap connection reference found in "
          "any flow detail; supply ESS_WD_PROBE_CONN_LOGICALNAME to proceed.")
    return None


def _probe_clientdata(binding: dict, operation_id: str, params: dict) -> str:
    """Build the CANDIDATE `clientdata` for the connector-bound probe flow.

    OPTION 1 (runtime binding by connection id GUID). The first live run
    (2026-08-05) proved the solution-style
    `connectionReferenceLogicalName` + `apiDefinition` shape is NO-GO on an
    ad-hoc non-solution flow (activate -> 400 FlowMissingConnection, api
    '<null>'). Option 1 instead binds the maker's EXISTING connection by its
    real connection id GUID with `source: "Embedded"`, which targets that one
    connection deterministically. This recorder's real-tenant run confirmed
    that shape activates + invokes; the committed
    `flightcheck_wd_connector_probe.yaml` is the green cassette.

    Structure mirrors INFRA-003's `_probe_clientdata`, with the two deltas:
    a populated `connectionReferences` (embedded-GUID shape) and a single
    `OpenApiConnection` action instead of a native `Http` action.
    """
    definition = {
        "$schema": (
            "https://schema.management.azure.com/providers/"
            "Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#"
        ),
        "contentVersion": "1.0.0.0",
        "parameters": {
            "$connections": {"defaultValue": {}, "type": "Object"},
            "$authentication": {"defaultValue": {}, "type": "SecureObject"},
        },
        "triggers": {
            TRIGGER_NAME: {
                "metadata": {},
                "type": "Request",
                "kind": "Http",
                "inputs": {
                    "schema": {"type": "object", "properties": {}, "required": []}
                },
            }
        },
        "actions": {
            PROBE_ACTION_NAME: {
                "runAfter": {},
                "metadata": {},
                "type": "OpenApiConnection",
                "inputs": {
                    "parameters": params,
                    "host": {
                        "apiId": binding["apiId"],
                        "operationId": operation_id,
                        "connectionName": PROBE_CONN_REF_KEY,
                    },
                },
            },
            "Respond": {
                # Always respond, whatever the connector action does, so the
                # trigger can reply synchronously with the connector result.
                "runAfter": {
                    PROBE_ACTION_NAME: [
                        "Succeeded",
                        "Failed",
                        "TimedOut",
                        "Skipped",
                    ]
                },
                "metadata": {},
                "type": "Response",
                "kind": "Http",
                "inputs": {
                    "statusCode": 200,
                    # Capture EVERYTHING the connector surfaces so the spike
                    # can judge error granularity (Q2). We do not yet know
                    # which fields the connector populates; the capture tells
                    # us. statusCode may be absent for OpenApiConnection.
                    "body": {
                        "workdayActionStatus": f"@actions('{PROBE_ACTION_NAME}')?['status']",
                        "workdayStatusCode": f"@outputs('{PROBE_ACTION_NAME}')?['statusCode']",
                        "errorMessage": f"@actions('{PROBE_ACTION_NAME}')?['error']?['message']",
                        "errorCode": f"@actions('{PROBE_ACTION_NAME}')?['error']?['code']",
                    },
                },
            },
        },
    }
    clientdata = {
        "properties": {
            "connectionReferences": {
                PROBE_CONN_REF_KEY: {
                    # Option 1: bind by the REAL connection id GUID with
                    # source Embedded, NOT the solution
                    # connectionReferenceLogicalName (proved NO-GO
                    # 2026-08-05: api '<null>'). Embedded targets this one
                    # specific connection deterministically, which is what
                    # pins the probe to the ISU/service-account identity.
                    "connectionName": binding["connectionId"],
                    "source": "Embedded",
                    "id": binding["apiId"],
                    "tier": "Integrated",
                }
            },
            "definition": definition,
        },
        "schemaVersion": "1.0.0.0",
    }
    return json.dumps(clientdata)


def _probe_workflow_body(clientdata: str) -> dict:
    """The Dataverse `workflows` create payload (POST body)."""
    return {
        "category": FLOW_CATEGORY,
        "name": PROBE_FLOW_NAME,
        "type": FLOW_TYPE_DEFINITION,
        "description": "FlightCheck WD-RUN-001 v2 AC9 spike connector probe.",
        "primaryentity": "none",
        "clientdata": clientdata,
    }


def _extract_callback_url(resp: object) -> str | None:
    """Pull the trigger invoke URL out of a listCallbackUrl response.

    Defensive across the known Logic Apps / Power Automate shapes (same
    extraction the proven INFRA-003 recorder uses).
    """
    if not isinstance(resp, dict):
        return None
    for container in (resp, resp.get("response") or {}):
        if not isinstance(container, dict):
            continue
        value = container.get("value")
        if isinstance(value, str) and value.lower().startswith("http"):
            return value
        base_path = container.get("basePath")
        queries = container.get("queries")
        if isinstance(base_path, str) and isinstance(queries, dict):
            query_str = "&".join(f"{k}={v}" for k, v in queries.items())
            sep = "&" if "?" in base_path else "?"
            return f"{base_path}{sep}{query_str}" if query_str else base_path
    return None


def _resolve_connection_id(pp, env_id: str) -> str | None:
    """Resolve the maker's Workday connection id GUID for Option 1 binding.

    Env override ESS_WD_PROBE_CONN_ID takes precedence. Otherwise lists the
    environment's connections (admin scope) and returns the first Connected
    `shared_workdaysoap` connection's `name` (the GUID), falling back to any
    Workday connection if none report Connected.
    """
    override = os.environ.get("ESS_WD_PROBE_CONN_ID", "").strip()
    if override:
        return override
    try:
        conns = pp.get_connections(env_id)
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort
        print(f"  conn discovery: get_connections failed ({type(exc).__name__}); "
              "supply ESS_WD_PROBE_CONN_ID to proceed.")
        return None
    if not isinstance(conns, list):
        return None
    fallback = None
    for c in conns:
        if not isinstance(c, dict):
            continue
        props = c.get("properties", {}) or {}
        api = props.get("apiId") or (props.get("api") or {}).get("name", "")
        if "workday" not in str(api).lower():
            continue
        name = c.get("name")
        statuses = props.get("statuses") or []
        connected = any(
            isinstance(s, dict) and s.get("status") == "Connected" for s in statuses
        )
        if connected:
            return name
        fallback = fallback or name
    return fallback


def _require_read_only_params() -> tuple[str, dict]:
    """Read the probe operationId + params from env. No guessing: the
    operator must supply the exact read-only operation for their install."""
    operation_id = os.environ.get("ESS_WD_PROBE_OPERATION_ID", "").strip() or "RaaS_Operation"
    raw = os.environ.get("ESS_WD_PROBE_PARAMS_JSON", "").strip()
    if not raw:
        print("ERROR: set ESS_WD_PROBE_PARAMS_JSON to the JSON parameters of a "
              "READ-ONLY Workday operation.")
        print('  Example (RaaS): {"accountName":"<acct>","reportName":"<report>",'
              '"reportInstanceName":"","requestBody":""}')
        sys.exit(1)
    try:
        params = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: ESS_WD_PROBE_PARAMS_JSON is not valid JSON: {exc}")
        sys.exit(1)
    if not isinstance(params, dict):
        print("ERROR: ESS_WD_PROBE_PARAMS_JSON must be a JSON object.")
        sys.exit(1)
    return operation_id, params


def main() -> None:
    cassette_name = (
        os.environ.get("ESS_WD_PROBE_CASSETTE", "").strip()
        or "flightcheck_wd_connector_probe"
    )
    if cassette_name != os.path.basename(cassette_name):
        print("ERROR: ESS_WD_PROBE_CASSETTE must be a bare file name, no path.")
        sys.exit(1)

    announce(cassette_name)

    print("!" * 78)
    print("! AC9 SPIKE — MUTATES THE TENANT and runs ONE Workday operation.")
    print("! Use a READ-ONLY operation and a disposable/test tenant you own.")
    print("! This flow binds to your REAL Workday connection.")
    print("!" * 78)
    print()

    env_url = get_dataverse_url().rstrip("/")
    operation_id, params = _require_read_only_params()
    print(f"  Dataverse env:   {env_url}")
    print(f"  Probe operation: {operation_id}")
    print(f"  Probe params:    {sorted(params.keys())}")
    print(f"  Cassette:        {cassette_name}")
    confirm_or_exit()

    # auth.py / pp_admin_client.py use relative paths (.local token cache).
    chdir_kit_root()

    import auth
    from flightcheck.pp_admin_client import FLOW_BASE, _SESSION, PPAdminClient

    dv_token = auth.authenticate(env_url)  # Dataverse audience.
    tenant_id = auth.discover_tenant(env_url)
    pp = PPAdminClient(tenant_id=tenant_id)
    pp.authenticate()
    env_id = pp.find_environment_id_by_dataverse_url(env_url)
    if not env_id:
        print(f"ERROR: no BAP environment matched Dataverse URL {env_url!r}.")
        sys.exit(1)
    print(f"  Resolved env_id: {env_id}")

    binding = _discover_workday_binding(pp, env_id)
    if not binding:
        print("ERROR: could not resolve a Workday connection binding. Supply "
              "ESS_WD_PROBE_CONN_LOGICALNAME (and optionally "
              "ESS_WD_PROBE_CONN_APIID) and re-run.")
        sys.exit(1)

    conn_id = _resolve_connection_id(pp, env_id)
    if not conn_id:
        print("ERROR: could not resolve a Workday connection id GUID for the "
              "Option 1 embedded binding. Supply ESS_WD_PROBE_CONN_ID and "
              "re-run.")
        sys.exit(1)
    binding["connectionId"] = conn_id
    print(f"  connection id:   {conn_id}")

    clientdata = _probe_clientdata(binding, operation_id, params)

    def _dv_headers(extra: dict | None = None) -> dict:
        h = {
            "Authorization": f"Bearer {dv_token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
        }
        if extra:
            h.update(extra)
        return h

    def _summ(method: str, url: str, resp: object) -> object:
        status = getattr(resp, "status_code", "ERR")
        print(f"  {method} {urlparse(url).path or url}: {status}")
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return None

    def _find_probe_flows() -> list[str]:
        url = f"{env_url}{DATAVERSE_API}/workflows"
        params_q = {
            "$select": "workflowid,name,statecode",
            "$filter": f"name eq '{PROBE_FLOW_NAME}' and category eq {FLOW_CATEGORY}",
        }
        try:
            resp = _SESSION.get(url, headers=_dv_headers(), params=params_q, timeout=60)
        except Exception as exc:  # noqa: BLE001
            print(f"  orphan scan: ERROR {type(exc).__name__}: {exc}")
            return []
        body = _summ("GET", url, resp)
        rows = body.get("value", []) if isinstance(body, dict) else []
        ids = [r.get("workflowid") for r in rows if isinstance(r, dict) and r.get("workflowid")]
        print(f"  orphan scan: {len(ids)} matching probe flow(s)")
        return ids

    def _delete_workflow(workflow_id: str, *, attempts: int = 4) -> bool:
        url = f"{env_url}{DATAVERSE_API}/workflows({workflow_id})"
        delay = 1.0
        deactivated = False
        for attempt in range(1, attempts + 1):
            try:
                resp = _SESSION.delete(url, headers=_dv_headers(), timeout=60)
                status: int | None = resp.status_code
                print(f"  DELETE workflow (attempt {attempt}/{attempts}): {status}")
            except Exception as exc:  # noqa: BLE001
                status = None
                print(f"  DELETE workflow (attempt {attempt}/{attempts}): "
                      f"ERROR {type(exc).__name__}: {exc}")
            if status in (200, 202, 204, 404):
                return True
            if status in (400, 409) and not deactivated:
                deactivated = True
                try:
                    d = _SESSION.patch(
                        url,
                        headers=_dv_headers({"Content-Type": "application/json", "If-Match": "*"}),
                        data=json.dumps({"statecode": STATECODE_DRAFT}),
                        timeout=60,
                    )
                    print(f"  PATCH statecode=0 (deactivate for delete): {d.status_code}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  PATCH statecode=0: ERROR {type(exc).__name__}: {exc}")
                continue
            if status is not None and status != 429 and status < 500:
                return False
            if attempt < attempts:
                time.sleep(delay)
                delay *= 2
        return False

    def _cleanup_all() -> None:
        for wid in _find_probe_flows():
            if not _delete_workflow(wid):
                print("!" * 78)
                print(f"! WARNING: could not confirm deletion of probe flow {wid!r} "
                      f"('{PROBE_FLOW_NAME}'). Delete it manually in env "
                      f"'{env_id}'.")
                print("!" * 78)

    with build_cassette(cassette_name):
        # 0. Orphan sweep BEFORE create (AC6 idempotency).
        _cleanup_all()

        workflow_id: str | None = None
        try:
            # 1. Create the (draft) connector-bound probe flow.
            create_url = f"{env_url}{DATAVERSE_API}/workflows"
            create_resp = _SESSION.post(
                create_url,
                headers=_dv_headers(
                    {"Content-Type": "application/json", "Prefer": "return=representation"}
                ),
                data=json.dumps(_probe_workflow_body(clientdata)),
                timeout=60,
            )
            created = _summ("POST", create_url, create_resp)
            if isinstance(created, dict):
                workflow_id = created.get("workflowid")
            if not workflow_id:
                entity_id = create_resp.headers.get("OData-EntityId", "")
                if "(" in entity_id and entity_id.endswith(")"):
                    workflow_id = entity_id.rsplit("(", 1)[1].rstrip(")")
            print(f"  workflowid: {workflow_id}")

            if workflow_id:
                # 2. Activate (statecode -> 1). If Q1 fails, this or the
                #    trigger below is where it typically surfaces.
                activate_url = f"{env_url}{DATAVERSE_API}/workflows({workflow_id})"
                activate_resp = _SESSION.patch(
                    activate_url,
                    headers=_dv_headers({"Content-Type": "application/json", "If-Match": "*"}),
                    data=json.dumps({"statecode": STATECODE_ACTIVE}),
                    timeout=60,
                )
                _summ("PATCH", activate_url, activate_resp)

                # 3. Trigger callback URL (Power Automate host).
                cb_url = (
                    f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/environments/"
                    f"{env_id}/flows/{workflow_id}/triggers/{TRIGGER_NAME}/"
                    f"listCallbackUrl?api-version={API_VERSION}"
                )
                cb_resp = _SESSION.post(
                    cb_url,
                    headers={**pp.flow_headers, "Content-Type": "application/json"},
                    data="{}",
                    timeout=60,
                )
                callback = _summ("POST", cb_url, cb_resp)

                # 4. Trigger one run over the SAS callback URL (no bearer).
                callback_url = _extract_callback_url(callback)
                if callback_url:
                    trig = _SESSION.post(
                        callback_url, json={}, headers={"Prefer": "wait"}, timeout=60
                    )
                    print(f"  POST <callback url>: {trig.status_code}")
                    try:
                        print(f"  trigger response body: {trig.json()}")
                    except ValueError:
                        pass
                else:
                    keys = list(callback.keys()) if isinstance(callback, dict) else type(callback).__name__
                    print("  POST <callback url>: SKIPPED - no URL in "
                          f"listCallbackUrl response (keys: {keys}).")

                # 5. Poll runs, then read the ACTION-level result — this is
                #    where the connector's status/code/error (Q2 granularity)
                #    and any SAS outputsLink live.
                runs_url = (
                    f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/environments/"
                    f"{env_id}/flows/{workflow_id}/runs?api-version={API_VERSION}"
                )
                run_name: str | None = None
                run_status: str | None = None
                for _ in range(POLL_ATTEMPTS):
                    runs_resp = _SESSION.get(runs_url, headers=pp.flow_headers, timeout=60)
                    runs = _summ("GET", runs_url, runs_resp)
                    values = runs.get("value", []) if isinstance(runs, dict) else []
                    if values and isinstance(values[0], dict):
                        run_name = values[0].get("name")
                        run_status = values[0].get("properties", {}).get("status")
                        print(f"  latest run status: {run_status}")
                        if run_status not in (None, "Running", "Waiting"):
                            break
                    time.sleep(POLL_INTERVAL_S)

                if run_name:
                    actions_url = (
                        f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/environments/"
                        f"{env_id}/flows/{workflow_id}/runs/{run_name}/actions"
                        f"?api-version={API_VERSION}"
                    )
                    actions_resp = _SESSION.get(actions_url, headers=pp.flow_headers, timeout=60)
                    actions = _summ("GET", actions_url, actions_resp)
                    action_values = actions.get("value", []) if isinstance(actions, dict) else []
                    for act in action_values:
                        if not isinstance(act, dict):
                            continue
                        props = act.get("properties", {})
                        print(f"  action {act.get('name')!r}: status={props.get('status')} "
                              f"code={props.get('code')} error={props.get('error')}")
                        link = props.get("outputsLink") or {}
                        if isinstance(link, dict) and link.get("uri"):
                            try:
                                out_resp = _SESSION.get(link["uri"], timeout=60)
                                print(f"  GET <action outputsLink>: {out_resp.status_code}")
                            except Exception as exc:  # noqa: BLE001
                                print(f"  GET <action outputsLink>: ERROR "
                                      f"{type(exc).__name__}: {exc}")
        finally:
            # 6. Guaranteed cleanup — always delete the probe flow (AC6).
            _cleanup_all()

    print()
    print("=" * 78)
    print(f"Cassette written: tests/fixtures/cassettes/{cassette_name}.yaml")
    print("=" * 78)
    print()
    print("RECORD THE GO/NO-GO on US 7500446 + US 7670878 (see runbook):")
    print("  Q1 (bind+invoke under running identity):")
    print("     - create -> 2xx + workflowid?")
    print("     - activate -> 2xx, or did it reject the connection binding?")
    print("     - trigger -> did the Probe_Workday action RUN (not skip on a")
    print("       missing/denied connection)? which identity did it use?")
    print("  Q2 (error granularity): on a forced error, does the action")
    print("     status/code/error distinguish endpoint-config vs business-rule,")
    print("     or collapse to a generic 500?")
    print("  Also record: install flavor (simplified/full) + the operation used.")
    print()
    print("Then eyeball tests/fixtures/cassettes/.raw/ for any surviving SAS")
    print("`sig=`, bearer token, or tenant-specific text before committing.")


if __name__ == "__main__":
    main()
