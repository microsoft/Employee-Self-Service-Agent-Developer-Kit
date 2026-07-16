#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Record the cassette that backs the INFRA-003 live egress probe
(--live-probe). This captures the Power Automate flow-lifecycle API that
the transient-flow probe uses to make an HTTP request from the Power
Platform environment's own egress.

WARNING — THIS RECORDER MUTATES THE TENANT
------------------------------------------
Unlike every other recorder in this folder (which only issue GET/list
calls), this one CREATES and DELETES a real cloud flow. Run it ONLY in a
disposable test environment you own. The flow it creates is named
deterministically (see PROBE_FLOW_NAME) and is deleted at the end of the
run; if a previous run crashed, the first step deletes the orphan.

Why each call is here (the INFRA-003 live-probe lifecycle)
----------------------------------------------------------
The probe answers one question: "can the Power Platform environment reach
the external endpoint?" A local socket from the maker's laptop cannot
answer it — only a request from inside Power Platform can. So the probe
stands up a throwaway HTTP-triggered flow whose single action makes an
outbound HTTP HEAD to the target, then reads the result:

  Power Automate flow lifecycle (host: api.flow.microsoft.com,
  provider Microsoft.ProcessSimple, api-version=2016-11-01, audience
  service.flow.microsoft.com//.default — same token as get_flows):

  1. DELETE .../flows/{name}                 -> orphan cleanup (ignore 404)
  2. PUT    .../flows/{name}   state=Started -> create + activate the probe
  3. POST   .../flows/{name}/triggers/{trg}/listCallbackUrl
                                             -> the SAS-signed invoke URL
  4. POST   <callback URL>                   -> trigger one run (HTTP HEAD
                                                to the target endpoint)
  5. GET    .../flows/{name}/runs            -> poll the run result
     (this endpoint is ALREADY validated — flightcheck_workday_runs.yaml)
  6. DELETE .../flows/{name}                 -> guaranteed cleanup

Operation names confirmed against the Power Automate Management connector
reference:
  https://learn.microsoft.com/en-us/connectors/flowmanagement/
  (Create Flow / Delete Flow / Turn On Flow / List Callback URL)

Bootstrapping note
------------------
pp_admin_client.py does NOT yet have create/listCallbackUrl/delete
methods (per AGENTS.md, we don't ship code against an unverified API).
This recorder therefore issues the raw requests directly, reusing the
client's authenticated `flow_headers` and the shared `_SESSION`. Once
this cassette is captured and the shapes are confirmed, we add the
validated pp_admin_client methods AND the INFRA-003 live branch against
the captured shapes.

Redaction
---------
The listCallbackUrl response and the triggered run URL carry a
Shared Access Signature (`sig=`) that authorizes anyone to invoke the
trigger. `tests/captures/_common.py` has a REDACT_REGEX rule that strips
`sig=` (added alongside this recorder). AFTER running, eyeball the
`.raw/` cassette and confirm no `sig=` value survived.

DLP
---
The probe flow's action is the built-in HTTP connector, which is premium
and can be blocked by a Data Loss Prevention policy. Run this capture in
an environment whose DLP policy ALLOWS the HTTP connector — otherwise the
create/activate or trigger step fails (which is itself the real-world
signal that the INFRA-003 live path must fall back to the local probe).

Output
------
tests/fixtures/cassettes/flightcheck_infra003_flow.yaml

Operator workflow
-----------------
1. Authenticate against a DISPOSABLE test tenant once (run flightcheck
   interactively, or any recorder, to populate .local/.token_cache.bin).
2. $env:ESS_DATAVERSE_URL   = "https://<your-test-tenant>.crm.dynamics.com"
3. $env:ESS_PROBE_TARGET_URL = "https://<an-endpoint-you-want-to-probe>"
      (a real https endpoint; the flow does a HEAD to it. No creds sent.)
4. python tests/captures/record_infra003_flow.py
5. Read the on-screen summary. Confirm and report back:
   - PUT create returned 200/201 and the response carries the flow
     `name` (id) and a trigger under properties.definition.triggers,
   - listCallbackUrl returned 200 with a `response.value` (or
     top-level `value`) URL that includes `sig=`,
   - the triggered run reached a terminal status, and which field
     carries the HTTP status the target returned (so the check knows
     where to read <400 / 401 / 403),
   - the final DELETE returned 200/202/204,
   - the orphan-cleanup DELETE on a missing flow returned 404 (needed
     for the AC7 idempotency test).
6. Eyeball tests/fixtures/cassettes/.raw/ for any surviving `sig=` value,
   bearer token, or tenant-specific text the redactor missed.
7. Commit tests/fixtures/cassettes/flightcheck_infra003_flow.yaml and
   tell me the shape confirmations from step 5 — I'll add the validated
   pp_admin_client methods, the INFRA-003 live branch, the mock, the
   INDEX.md "Confirmed cassette endpoints" rows, and the live-path tests
   against the captured shapes.

# TODO(confirm-during-capture): the probe flow DEFINITION below is a
# first draft (HTTP-request trigger + one HTTP HEAD action). The exact
# schema that api.flow.microsoft.com accepts on PUT must be confirmed by
# this capture run — if create returns 4xx, adjust the definition until
# it returns 200/201, then note the accepted shape so we pin it.
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

# Deterministic name so a rerun detects + deletes a leftover probe flow
# from a crashed run before creating a new one. MUST match the name the
# INFRA-003 live branch will use.
PROBE_FLOW_NAME = "flightcheck-infra003-probe"
API_VERSION = "2016-11-01"
POLL_ATTEMPTS = 10
POLL_INTERVAL_S = 3


def _probe_flow_body(target_url: str) -> dict:
    """First-draft definition: an HTTP-request trigger + one HTTP HEAD
    action to the target. See the TODO in the module docstring — the
    accepted PUT shape is confirmed by running this capture.
    """
    return {
        "properties": {
            "displayName": "FlightCheck INFRA-003 reachability probe (transient)",
            "state": "Started",
            "definition": {
                "$schema": (
                    "https://schema.management.azure.com/providers/"
                    "Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#"
                ),
                "contentVersion": "1.0.0.0",
                "triggers": {
                    "manual": {
                        "type": "Request",
                        "kind": "Http",
                        "inputs": {"schema": {}},
                    }
                },
                "actions": {
                    "Probe_HEAD": {
                        "type": "Http",
                        "inputs": {"method": "HEAD", "uri": target_url},
                        "runAfter": {},
                    }
                },
            },
        }
    }


def _flow_path(env_id: str, suffix: str = "") -> str:
    return (
        f"/providers/Microsoft.ProcessSimple/environments/{env_id}"
        f"/flows/{PROBE_FLOW_NAME}{suffix}"
    )


def _extract_callback_url(resp: object) -> str | None:
    """Pull the trigger invoke URL out of a listCallbackUrl response.

    The exact shape is what this capture confirms, so extraction is
    defensive: it tries the known Logic Apps / Power Automate shapes and
    returns None (caller warns + skips the trigger) if none match.

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
    print("! THIS RECORDER MUTATES THE TENANT: it CREATES and DELETES a cloud flow.")
    print("! Run ONLY in a disposable test environment you own.")
    print("!" * 78)
    print()

    env_url = get_dataverse_url()
    target_url = os.environ.get("ESS_PROBE_TARGET_URL")
    if not target_url:
        print("ERROR: set ESS_PROBE_TARGET_URL to the https endpoint to probe.")
        sys.exit(1)
    print(f"  Probe target: {target_url}")
    confirm_or_exit()

    # auth.py / pp_admin_client.py use relative paths (.local token cache).
    chdir_kit_root()

    import auth
    from flightcheck.pp_admin_client import FLOW_BASE, _SESSION, PPAdminClient

    tenant_id = auth.discover_tenant(env_url)
    pp = PPAdminClient(tenant_id=tenant_id)
    pp.authenticate()

    env_id = pp.find_environment_id_by_dataverse_url(env_url)
    if not env_id:
        print(f"ERROR: no BAP environment matched Dataverse URL {env_url!r}.")
        sys.exit(1)
    print(f"  Resolved env_id: {env_id}")

    def _req(method: str, url: str, *, body: dict | None = None) -> object:
        """Issue one raw flow-audience request and print a short summary.

        Returns the parsed JSON (or None). Never raises on HTTP status —
        the capture wants to record 4xx (e.g. the orphan-cleanup 404) too.
        """
        headers = dict(pp.flow_headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        resp = _SESSION.request(
            method,
            url,
            headers=headers,
            data=json.dumps(body) if body is not None else None,
            timeout=60,
        )
        label = f"{method} {urlparse(url).path or url}"
        print(f"  {label}: {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            return None

    def _delete_flow_with_retries(
        url: str, *, attempts: int = 4, base_delay: float = 1.0
    ) -> bool:
        """DELETE the probe flow with exponential backoff.

        Treats 2xx and 404 as success (404 = already gone). Retries on
        network errors, 429 (throttling), and 5xx. Stops early on a
        non-retryable 4xx (e.g. 403). Returns True only when deletion is
        confirmed, so the caller can warn on an unconfirmed leak.
        """
        delay = base_delay
        for attempt in range(1, attempts + 1):
            status: int | None
            try:
                resp = _SESSION.request(
                    "DELETE", url, headers=dict(pp.flow_headers), timeout=60
                )
                status = resp.status_code
                print(f"  DELETE probe flow (attempt {attempt}/{attempts}): {status}")
            except Exception as exc:  # network error — retry
                status = None
                print(
                    f"  DELETE probe flow (attempt {attempt}/{attempts}): "
                    f"ERROR {type(exc).__name__}: {exc}"
                )
            if status in (200, 202, 204, 404):
                return True
            if status is not None and status != 429 and status < 500:
                return False  # non-retryable client error
            if attempt < attempts:
                time.sleep(delay)
                delay *= 2
        return False

    with build_cassette("flightcheck_infra003_flow"):
        base = FLOW_BASE
        params = f"?api-version={API_VERSION}"
        delete_url = f"{base}{_flow_path(env_id)}{params}"

        # 1. Orphan cleanup — delete any leftover probe flow (expect 404
        #    on a clean env; that 404 is what the AC7 idempotency test
        #    replays). Runs BEFORE the try so a create failure below still
        #    leaves a clean env, and uses the same backoff as the final
        #    delete so a throttled cleanup does not leak.
        _delete_flow_with_retries(delete_url)

        # The lifecycle create -> trigger -> poll is wrapped so the final
        # DELETE ALWAYS runs, even if any step raises. Deletion is by the
        # deterministic flow name, so it is safe whether or not create
        # returned (a delete of a missing flow is a harmless 404).
        try:
            # 2. Create + activate.
            created = _req(
                "PUT",
                f"{base}{_flow_path(env_id)}{params}",
                body=_probe_flow_body(target_url),
            )

            # 3. Get the trigger callback URL. The trigger name comes from
            #    the definition ("manual"); confirm against the create
            #    response.
            trigger_name = "manual"
            if isinstance(created, dict):
                triggers = (
                    created.get("properties", {})
                    .get("definition", {})
                    .get("triggers", {})
                )
                if triggers:
                    trigger_name = next(iter(triggers))
            callback = _req(
                "POST",
                f"{base}{_flow_path(env_id, f'/triggers/{trigger_name}/listCallbackUrl')}"
                f"{params}",
                body={},
            )

            # 4. Trigger the run — POST the SAS-signed callback URL with no
            #    body and NO bearer header (the `sig=` in the URL is the
            #    auth). This is the actual HTTP probe: the flow's HTTP
            #    action makes an outbound HEAD to the target from Power
            #    Platform's egress.
            callback_url = _extract_callback_url(callback)
            if callback_url:
                resp = _SESSION.post(callback_url, json={}, timeout=60)
                # urlparse().path hides the SAS query from the console; the
                # cassette itself is scrubbed by the sig= redactor.
                print(f"  POST <callback url>: {resp.status_code}")
            else:
                print(
                    "  POST <callback url>: SKIPPED — could not find the URL "
                    f"in the listCallbackUrl response (keys: "
                    f"{list(callback.keys()) if isinstance(callback, dict) else type(callback).__name__}). "
                    "Confirm the response shape and update _extract_callback_url."
                )

            # 5. Poll the run history (already-validated endpoint).
            for _ in range(POLL_ATTEMPTS):
                runs = _req("GET", f"{base}{_flow_path(env_id, '/runs')}{params}")
                values = runs.get("value", []) if isinstance(runs, dict) else []
                if values:
                    break
                time.sleep(POLL_INTERVAL_S)
        finally:
            # 6. Guaranteed cleanup — always delete the probe flow, even if
            #    create/trigger/poll raised above. Backoff retry handles a
            #    transient failure; delete-by-name is safe and idempotent
            #    (404 if nothing was created).
            deleted = _delete_flow_with_retries(delete_url)
            if not deleted:
                print()
                print("!" * 78)
                print(
                    f"! WARNING: could not confirm deletion of probe flow "
                    f"'{PROBE_FLOW_NAME}'."
                )
                print(
                    f"! Manually delete it from environment '{env_id}' in Power "
                    f"Automate,"
                )
                print(
                    "! or re-run this recorder — its first step deletes leftovers "
                    "by name."
                )
                print("!" * 78)

    print()
    print("=" * 78)
    print("Cassette written: tests/fixtures/cassettes/flightcheck_infra003_flow.yaml")
    print("=" * 78)
    print()
    print("NEXT STEPS — confirm these shapes and report back (see docstring):")
    print("  1. PUT create -> 200/201, response carries flow `name` + trigger.")
    print("  2. listCallbackUrl -> 200 with a URL containing `sig=`.")
    print("  3. run reached terminal status; which field = target HTTP status?")
    print("  4. final DELETE -> 200/202/204; orphan DELETE -> 404.")
    print()
    print("Then eyeball tests/fixtures/cassettes/.raw/ for surviving `sig=` /")
    print("bearer tokens, confirm the flow is gone from the env, and commit.")


if __name__ == "__main__":
    main()
