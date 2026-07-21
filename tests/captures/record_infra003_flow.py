#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record the cassette that backs the INFRA-003 live egress probe
(--runtime-reachability). It captures the flow lifecycle the transient-flow probe
uses to make ONE outbound HTTP request from the Power Platform
environment's own egress and read the result.

WARNING - THIS RECORDER MUTATES THE TENANT
------------------------------------------
Unlike every other recorder in this folder (which only issue GET/list
calls), this one CREATES, ACTIVATES and DELETES a real cloud flow. Run it
ONLY in a disposable test environment you own. The flow is named
deterministically (PROBE_FLOW_NAME) and is deleted at the end; if a
previous run crashed, the first step deletes the orphan by name.

Why the Dataverse workflow table (not api.flow.microsoft.com PUT)
----------------------------------------------------------------
An earlier draft created the flow with `PUT api.flow.microsoft.com/.../
flows/{name}`. A capture against a disposable tenant proved that returns
404 "No HTTP resource was found" - PUT-by-name is not a routable create
operation. The SUPPORTED, documented way to manage a cloud flow with code
is the Dataverse `workflow` table:
  https://learn.microsoft.com/en-us/power-automate/manage-flows-with-code

Cloud flows are rows in the Dataverse `workflow` table (category 5). So
this recorder splits the lifecycle across TWO hosts/audiences:

  A. Dataverse Web API  (host: {env}.crm.dynamics.com,
     path /api/data/v9.2/workflows, audience {env}/user_impersonation via
     auth.authenticate) - create, activate, list-by-name, delete.
  B. Power Automate API (host: api.flow.microsoft.com, provider
     Microsoft.ProcessSimple, api-version 2016-11-01, audience
     service.flow.microsoft.com via pp.flow_headers) - listCallbackUrl,
     trigger the run, poll runs. These key off the workflowid GUID that
     Dataverse assigns on create.

The lifecycle (each call is here to answer "can the environment reach the
external endpoint?" - a request from the maker's laptop cannot answer it,
only a request from inside Power Platform can):

  0. GET  {dv}/workflows?$filter=name eq '<name>' and category eq 5
                                              -> find + delete orphans
  1. POST {dv}/workflows  {category:5,type:1,name,primaryentity:none,
          clientdata}                         -> create (204/201 + workflowid)
  2. PATCH {dv}/workflows({workflowid}) {statecode:1}
                                              -> activate (204)
  3. POST {flow}/.../flows/{workflowid}/triggers/{trg}/listCallbackUrl
                                              -> the SAS-signed invoke URL
  4. POST <callback URL>                      -> trigger one run (the flow's
                                                 HTTP action makes an
                                                 outbound GET to the target)
  5. GET  {flow}/.../flows/{workflowid}/runs  -> poll the run result
  6. PATCH statecode:0 (if needed) + DELETE {dv}/workflows({workflowid})
                                              -> guaranteed cleanup

AC7 idempotency
---------------
The workflowid is a server-assigned GUID (new every create), so cleanup
cannot key off a fixed resource id. Instead the flow's DISPLAY NAME (the
`name` column) is deterministic (PROBE_FLOW_NAME), and orphan cleanup is a
`$filter=name eq '<name>'` scan + delete. The INFRA-003 live branch uses
the same deterministic name so a crashed run is always cleaned on the next
run. Deleting a missing flow is a no-op (the scan simply returns 0 rows).

Redaction
---------
The listCallbackUrl response and the triggered run URL carry a Shared
Access Signature (`sig=`) that authorizes anyone to invoke the trigger.
`tests/captures/_common.py` has a REDACT_REGEX rule that strips `sig=`.
The workflowid GUID and env/tenant GUIDs are redacted by the GUID rules.
AFTER running, eyeball the `.raw/` cassette and confirm no `sig=` value,
bearer token, or tenant-specific text survived.

DLP / licensing
---------------
The probe flow's action is the built-in HTTP action, which is premium and
can be blocked by DLP or require a premium license to ACTIVATE. Run this
capture in an environment whose DLP policy ALLOWS the HTTP connector and
whose account can activate premium flows - otherwise the activate or
trigger step fails (which is itself the real-world signal that the
INFRA-003 live path must fall back to the local probe). The recorder
records those failures too, so the mock can replay them.

Output
------
tests/fixtures/cassettes/flightcheck_infra003_flow.yaml

Operator workflow
-----------------
1. Authenticate against a DISPOSABLE test tenant (this recorder calls
   auth.authenticate / pp.authenticate, which use .local/.token_cache.bin
   and may pop an interactive browser sign-in the first time).
2. $env:ESS_DATAVERSE_URL    = "https://<your-test-tenant>.crm.dynamics.com"
3. $env:ESS_PROBE_TARGET_URL = "https://<an-endpoint-you-want-to-probe>"
      (a real https endpoint; the flow does a GET to it. No creds sent.)
4. python tests\captures\record_infra003_flow.py
5. Read the on-screen summary. Confirm + report back:
   - create returned 204/201 and the workflowid was captured,
   - activate returned 204,
   - listCallbackUrl returned 200 with a URL containing `sig=`,
   - the triggered run reached a terminal status, and which field carries
     the HTTP status the target returned (so the check knows where to read
     <400 / 401 / 403),
   - the final DELETE returned 2xx,
   - the orphan scan returned 0 rows on a clean env.
6. Eyeball tests/fixtures/cassettes/.raw/ for any surviving `sig=` value,
   bearer token, or tenant-specific text the redactor missed.
7. Commit the cassette and tell me the shape confirmations - I'll add the
   validated pp_admin_client methods, the INFRA-003 live branch, the mock,
   the INDEX.md "Confirmed endpoints" rows, and the live-path tests.
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

# Deterministic DISPLAY NAME (the workflow `name` column). A rerun finds +
# deletes a leftover probe flow with this name before creating a new one.
# MUST match the name the INFRA-003 live branch will use.
PROBE_FLOW_NAME = "flightcheck-infra003-probe"
DATAVERSE_API = "/api/data/v9.2"
API_VERSION = "2016-11-01"
POLL_ATTEMPTS = 12
POLL_INTERVAL_S = 3

# Modern cloud flow: workflow.category == 5, workflow.type == 1 (Definition).
FLOW_CATEGORY = 5
FLOW_TYPE_DEFINITION = 1
STATECODE_ACTIVE = 1
STATECODE_DRAFT = 0


def _probe_clientdata(target_url: str) -> str:
    """Build the `clientdata` string for the probe flow.

    `clientdata` is a STRING-encoded JSON holding the flow's
    connectionReferences + Logic Apps definition (see the MS Learn doc).
    The definition is a "When an HTTP request is received" trigger (Request
    / kind Http, so it is invocable via a SAS callback URL) plus one native
    HTTP action that does a GET to the target. The native HTTP action needs
    NO connection, so connectionReferences is empty.

    A non-2xx from the target still means the environment REACHED it; a DNS
    / TLS / network / DLP failure means it could not. The INFRA-003 check
    reads the run + action outputs to tell those apart - this capture
    confirms exactly which fields carry the status.
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
            "manual": {
                "metadata": {},
                "type": "Request",
                "kind": "Http",
                "inputs": {
                    "schema": {"type": "object", "properties": {}, "required": []}
                },
            }
        },
        "actions": {
            "Probe_HTTP": {
                "runAfter": {},
                "metadata": {},
                "type": "Http",
                "inputs": {"method": "GET", "uri": target_url},
            },
            "Respond": {
                # Runs whatever Probe_HTTP does (a non-2xx like 302/401/403
                # marks the HTTP action "Failed" but still yields outputs),
                # so the trigger can reply synchronously with the probed
                # status. A true egress block leaves statusCode null.
                "runAfter": {
                    "Probe_HTTP": ["Succeeded", "Failed", "TimedOut", "Skipped"]
                },
                "metadata": {},
                "type": "Response",
                "kind": "Http",
                "inputs": {
                    "statusCode": 200,
                    "body": {
                        "reachableStatusCode": "@outputs('Probe_HTTP')?['statusCode']",
                        "actionStatus": "@actions('Probe_HTTP')?['status']",
                    },
                },
            },
        },
    }
    clientdata = {
        "properties": {
            "connectionReferences": {},
            "definition": definition,
        },
        "schemaVersion": "1.0.0.0",
    }
    return json.dumps(clientdata)


def _probe_workflow_body(target_url: str) -> dict:
    """The Dataverse `workflows` create payload (POST body)."""
    return {
        "category": FLOW_CATEGORY,
        "name": PROBE_FLOW_NAME,
        "type": FLOW_TYPE_DEFINITION,
        "description": "FlightCheck INFRA-003 transient reachability probe.",
        "primaryentity": "none",
        "clientdata": _probe_clientdata(target_url),
    }


def _extract_callback_url(resp: object) -> str | None:
    """Pull the trigger invoke URL out of a listCallbackUrl response.

    Extraction is defensive across the known Logic Apps / Power Automate
    shapes; returns None (caller warns + skips the trigger) if none match.
      - Logic Apps: {"value": "https://...&sig=...", "method": "POST"}
      - some variants nest it under "response": {"value": ...}
      - or split into {"basePath": "...", "queries": {"sig": ..., ...}}
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


def main() -> None:
    announce("flightcheck_infra003_flow")

    print()
    print("!" * 78)
    print("! THIS RECORDER MUTATES THE TENANT: it CREATES, ACTIVATES and DELETES")
    print("! a cloud flow. Run ONLY in a disposable test environment you own.")
    print("!" * 78)
    print()

    env_url = get_dataverse_url().rstrip("/")
    target_url = os.environ.get("ESS_PROBE_TARGET_URL")
    if not target_url:
        print("ERROR: set ESS_PROBE_TARGET_URL to the https endpoint to probe.")
        sys.exit(1)
    print(f"  Dataverse env: {env_url}")
    print(f"  Probe target:  {target_url}")
    confirm_or_exit()

    # auth.py / pp_admin_client.py use relative paths (.local token cache).
    chdir_kit_root()

    import auth
    from flightcheck.pp_admin_client import FLOW_BASE, _SESSION, PPAdminClient

    # Dataverse Web API token (audience = {env}/user_impersonation).
    dv_token = auth.authenticate(env_url)

    # Flow admin token (audience = service.flow.microsoft.com) + BAP env id.
    tenant_id = auth.discover_tenant(env_url)
    pp = PPAdminClient(tenant_id=tenant_id)
    pp.authenticate()
    env_id = pp.find_environment_id_by_dataverse_url(env_url)
    if not env_id:
        print(f"ERROR: no BAP environment matched Dataverse URL {env_url!r}.")
        sys.exit(1)
    print(f"  Resolved env_id: {env_id}")

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
        """Print a short summary line (path only, hiding any SAS query)."""
        status = getattr(resp, "status_code", "ERR")
        print(f"  {method} {urlparse(url).path or url}: {status}")
        try:
            return resp.json()
        except Exception:
            return None

    def _dv_find_probe_flows() -> list[str]:
        """Return workflowids of every probe flow matching the deterministic
        display name (orphan detection for AC7 idempotency)."""
        url = f"{env_url}{DATAVERSE_API}/workflows"
        params = {
            "$select": "workflowid,name,statecode",
            "$filter": f"name eq '{PROBE_FLOW_NAME}' and category eq {FLOW_CATEGORY}",
        }
        try:
            resp = _SESSION.get(
                url, headers=_dv_headers(), params=params, timeout=60
            )
        except Exception as exc:
            print(f"  GET workflows (orphan scan): ERROR {type(exc).__name__}: {exc}")
            return []
        body = _summ("GET", url, resp)
        rows = body.get("value", []) if isinstance(body, dict) else []
        ids = [r.get("workflowid") for r in rows if r.get("workflowid")]
        print(f"  orphan scan: {len(ids)} matching probe flow(s)")
        return ids

    def _dv_delete_workflow(
        workflow_id: str, *, attempts: int = 4, base_delay: float = 1.0
    ) -> bool:
        """DELETE a workflow row with backoff. Deactivates first if a delete
        is rejected because the flow is still active. Treats 2xx + 404 as
        success. Returns True only when deletion is confirmed."""
        url = f"{env_url}{DATAVERSE_API}/workflows({workflow_id})"
        delay = base_delay
        deactivated = False
        for attempt in range(1, attempts + 1):
            try:
                resp = _SESSION.delete(url, headers=_dv_headers(), timeout=60)
                status: int | None = resp.status_code
                print(
                    f"  DELETE workflow (attempt {attempt}/{attempts}): {status}"
                )
            except Exception as exc:
                status = None
                print(
                    f"  DELETE workflow (attempt {attempt}/{attempts}): "
                    f"ERROR {type(exc).__name__}: {exc}"
                )
            if status in (200, 202, 204, 404):
                return True
            # An active flow can refuse deletion; deactivate once then retry.
            if status in (400, 409) and not deactivated:
                deactivated = True
                try:
                    d = _SESSION.patch(
                        url,
                        headers=_dv_headers(
                            {"Content-Type": "application/json", "If-Match": "*"}
                        ),
                        data=json.dumps({"statecode": STATECODE_DRAFT}),
                        timeout=60,
                    )
                    print(f"  PATCH statecode=0 (deactivate for delete): {d.status_code}")
                except Exception as exc:
                    print(f"  PATCH statecode=0: ERROR {type(exc).__name__}: {exc}")
                continue
            if status is not None and status != 429 and status < 500:
                return False  # non-retryable client error
            if attempt < attempts:
                time.sleep(delay)
                delay *= 2
        return False

    def _cleanup_all() -> None:
        """Guaranteed cleanup: delete every probe flow matching the name."""
        remaining = _dv_find_probe_flows()
        for wid in remaining:
            if not _dv_delete_workflow(wid):
                print("!" * 78)
                print(
                    f"! WARNING: could not confirm deletion of probe flow "
                    f"{wid!r} ('{PROBE_FLOW_NAME}')."
                )
                print(
                    f"! Manually delete it from environment '{env_id}' in Power "
                    f"Automate."
                )
                print("!" * 78)

    with build_cassette("flightcheck_infra003_flow"):
        # 0. Orphan cleanup BEFORE create, so a create failure below still
        #    leaves a clean env and the orphan-scan-returns-0 shape is
        #    captured for the AC7 idempotency test.
        _cleanup_all()

        workflow_id: str | None = None
        try:
            # 1. Create the (draft) probe flow.
            create_url = f"{env_url}{DATAVERSE_API}/workflows"
            create_resp = _SESSION.post(
                create_url,
                headers=_dv_headers(
                    {
                        "Content-Type": "application/json",
                        "Prefer": "return=representation",
                    }
                ),
                data=json.dumps(_probe_workflow_body(target_url)),
                timeout=60,
            )
            created = _summ("POST", create_url, create_resp)
            # workflowid comes from the representation body, or the
            # OData-EntityId response header (…/workflows(<guid>)).
            if isinstance(created, dict):
                workflow_id = created.get("workflowid")
            if not workflow_id:
                entity_id = create_resp.headers.get("OData-EntityId", "")
                if "(" in entity_id and entity_id.endswith(")"):
                    workflow_id = entity_id.rsplit("(", 1)[1].rstrip(")")
            print(f"  workflowid: {workflow_id}")

            if workflow_id:
                # 2. Activate (statecode -> 1).
                activate_url = f"{env_url}{DATAVERSE_API}/workflows({workflow_id})"
                activate_resp = _SESSION.patch(
                    activate_url,
                    headers=_dv_headers(
                        {"Content-Type": "application/json", "If-Match": "*"}
                    ),
                    data=json.dumps({"statecode": STATECODE_ACTIVE}),
                    timeout=60,
                )
                _summ("PATCH", activate_url, activate_resp)

                # 3. Get the trigger callback URL (Power Automate host).
                trigger_name = "manual"
                cb_url = (
                    f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/environments/"
                    f"{env_id}/flows/{workflow_id}/triggers/{trigger_name}/"
                    f"listCallbackUrl?api-version={API_VERSION}"
                )
                cb_resp = _SESSION.post(
                    cb_url,
                    headers={**pp.flow_headers, "Content-Type": "application/json"},
                    data="{}",
                    timeout=60,
                )
                callback = _summ("POST", cb_url, cb_resp)

                # 4. Trigger the run - POST the SAS-signed callback URL with
                #    no bearer header (the `sig=` in the URL is the auth).
                callback_url = _extract_callback_url(callback)
                if callback_url:
                    # `Prefer: wait` asks the Request/Response flow to reply
                    # synchronously with the Response action's body (the
                    # probed statusCode) instead of a bare 202.
                    trig = _SESSION.post(
                        callback_url,
                        json={},
                        headers={"Prefer": "wait"},
                        timeout=60,
                    )
                    print(f"  POST <callback url>: {trig.status_code}")
                    try:
                        print(f"  trigger response body: {trig.json()}")
                    except ValueError:
                        pass
                else:
                    keys = (
                        list(callback.keys())
                        if isinstance(callback, dict)
                        else type(callback).__name__
                    )
                    print(
                        "  POST <callback url>: SKIPPED - no URL in "
                        f"listCallbackUrl response (keys: {keys}). Confirm the "
                        "shape and update _extract_callback_url."
                    )

                # 5. Poll the run history until a run appears / terminates.
                runs_url = (
                    f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/environments/"
                    f"{env_id}/flows/{workflow_id}/runs?api-version={API_VERSION}"
                )
                run_name: str | None = None
                run_status: str | None = None
                for _ in range(POLL_ATTEMPTS):
                    runs_resp = _SESSION.get(
                        runs_url, headers=pp.flow_headers, timeout=60
                    )
                    runs = _summ("GET", runs_url, runs_resp)
                    values = runs.get("value", []) if isinstance(runs, dict) else []
                    if values and isinstance(values[0], dict):
                        run_name = values[0].get("name")
                        run_status = values[0].get("properties", {}).get("status")
                        print(f"  latest run status: {run_status}")
                        if run_status not in (None, "Running", "Waiting"):
                            break
                    time.sleep(POLL_INTERVAL_S)

                # 5b. Capture the run detail + the ACTION-level result. The
                #     runs LIST only carries the run/trigger status; the
                #     INFRA-003 check must tell "reached target, got non-2xx"
                #     (egress works) apart from "DNS / TLS / DLP block"
                #     (egress fails), and that distinction lives in the
                #     Probe_HTTP action's error/outputs, not the run summary.
                if run_name:
                    run_detail_url = (
                        f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/"
                        f"environments/{env_id}/flows/{workflow_id}/runs/"
                        f"{run_name}?api-version={API_VERSION}"
                    )
                    detail_resp = _SESSION.get(
                        run_detail_url, headers=pp.flow_headers, timeout=60
                    )
                    _summ("GET", run_detail_url, detail_resp)

                    actions_url = (
                        f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/"
                        f"environments/{env_id}/flows/{workflow_id}/runs/"
                        f"{run_name}/actions?api-version={API_VERSION}"
                    )
                    actions_resp = _SESSION.get(
                        actions_url, headers=pp.flow_headers, timeout=60
                    )
                    actions = _summ("GET", actions_url, actions_resp)
                    action_values = (
                        actions.get("value", []) if isinstance(actions, dict) else []
                    )
                    outputs_link: str | None = None
                    for act in action_values:
                        if not isinstance(act, dict):
                            continue
                        props = act.get("properties", {})
                        acode = props.get("code")
                        astatus = props.get("status")
                        aerr = props.get("error")
                        print(
                            f"  action {act.get('name')!r}: status={astatus} "
                            f"code={acode} error={aerr}"
                        )
                        link = props.get("outputsLink") or {}
                        if isinstance(link, dict) and link.get("uri"):
                            outputs_link = link["uri"]

                    # Follow the action's outputsLink to read the HTTP
                    # statusCode the target returned (present only if the
                    # request actually reached the endpoint). SAS `sig=` in
                    # the URL is redacted by _common; the body (a public
                    # endpoint's response) is capped by the action itself.
                    if outputs_link:
                        try:
                            out_resp = _SESSION.get(outputs_link, timeout=60)
                            print(f"  GET <action outputsLink>: {out_resp.status_code}")
                            try:
                                out_json = out_resp.json()
                                if isinstance(out_json, dict):
                                    print(
                                        "  action output statusCode: "
                                        f"{out_json.get('statusCode')}"
                                    )
                            except ValueError:
                                pass
                        except Exception as exc:
                            print(
                                f"  GET <action outputsLink>: ERROR "
                                f"{type(exc).__name__}: {exc}"
                            )
        finally:
            # 6. Guaranteed cleanup - delete every probe flow by name, even
            #    if create/activate/trigger raised above.
            _cleanup_all()

    print()
    print("=" * 78)
    print("Cassette written: tests/fixtures/cassettes/flightcheck_infra003_flow.yaml")
    print("=" * 78)
    print()
    print("NEXT STEPS - confirm these shapes and report back (see docstring):")
    print("  1. POST create -> 204/201; workflowid captured.")
    print("  2. PATCH activate -> 204.")
    print("  3. listCallbackUrl -> 200 with a URL containing `sig=`.")
    print("  4. run reached terminal status; which field = target HTTP status?")
    print("  5. final cleanup: orphan scan -> 0 rows; DELETE -> 2xx.")
    print()
    print("Then eyeball tests/fixtures/cassettes/.raw/ for surviving `sig=` /")
    print("bearer tokens, confirm the flow is gone from the env, and commit.")


if __name__ == "__main__":
    main()
