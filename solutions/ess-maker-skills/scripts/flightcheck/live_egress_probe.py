# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Live egress probe for INFRA-003 (opt-in ``--runtime-reachability``).

WHAT THIS IS
------------
Every other FlightCheck code path is strictly read-only. This module is
the ONE deliberate exception: it stands up a transient Power Automate
cloud flow, triggers it once so the flow makes a single outbound HTTP
request from the Power Platform environment's OWN egress, reads the
resulting HTTP status, then deletes the flow. That is the only way to
answer INFRA-003's real question -- "can the agent runtime reach this
endpoint?" -- because the maker's laptop sits on a different network path
than Power Platform's outbound IP ranges.

It is opt-in (``/flightcheck --runtime-reachability``) precisely because it mutates
the environment. When it is not run, INFRA-003 returns MANUAL guidance
rather than a local probe (see ``checks/infrastructure.py``): a laptop
TCP/TLS probe runs from the wrong network and never sends HTTP, so it
cannot prove the runtime path.

SUPPORTED API (confirmed by capture, not guessed)
-------------------------------------------------
A cloud flow is a row in the Dataverse ``workflow`` table (category 5).
The lifecycle spans two hosts / audiences:

  Dataverse Web API ({env}.crm.dynamics.com, /api/data/v9.2/workflows,
  audience {env}/user_impersonation):
    create   POST   /workflows                 -> 201 + workflowid
    activate PATCH  /workflows({id})           -> 204   ({"statecode":1})
    find     GET    /workflows?$filter=name..   -> 200  (orphan detection)
    delete   DELETE /workflows({id})           -> 204

  Power Automate API (api.flow.microsoft.com, provider
  Microsoft.ProcessSimple, api-version 2016-11-01, audience
  service.flow.microsoft.com):
    callback POST .../flows/{workflowid}/triggers/manual/listCallbackUrl
                                                -> 200 (SAS-signed URL)

  Trigger (the SAS URL itself, no bearer):
    invoke   POST <callback> (Prefer: wait)    -> 200
             body {"reachableStatusCode": <int|null>, "actionStatus": ...}

The probe flow's synchronous Response action returns the probed HTTP
status directly, so no run polling is needed. ``reachableStatusCode`` is
an int when the environment REACHED the endpoint (any 2xx/3xx/4xx/5xx --
even a 401/403 proves egress); it is null when the request never got an
HTTP response (DNS / TLS / connection / DLP block).

Backed by cassette ``tests/fixtures/cassettes/flightcheck_infra003_flow.yaml``
(recorder ``tests/captures/record_infra003_flow.py``, which drives the same
create/activate/callback/invoke/delete lifecycle this module implements). See
``tests/fixtures/cassettes/INDEX.md`` for the tier registry entry.

AC7 idempotency / cleanup
-------------------------
The workflowid is server-assigned (new every create), so cleanup keys off
the deterministic DISPLAY NAME (``PROBE_FLOW_NAME``): a ``$filter=name eq
'...'`` scan + delete. ``run_live_probe`` always deletes the flow it
created (``finally``), and callers run ``cleanup_orphan_probe_flows`` so a
flow leaked by a crashed prior run is swept on the next run. Deleting a
missing flow is a no-op.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests

# Deterministic DISPLAY NAME (the workflow `name` column). Cleanup and
# orphan detection key off this, so it MUST stay stable and match the
# recorder. Do not make it per-run unique.
PROBE_FLOW_NAME = "flightcheck-infra003-probe"

DATAVERSE_API = "/api/data/v9.2"
FLOW_BASE = "https://api.flow.microsoft.com"
FLOW_API_VERSION = "2016-11-01"
FLOW_CATEGORY = 5           # modern cloud flow
FLOW_TYPE_DEFINITION = 1
STATECODE_ACTIVE = 1
STATECODE_DRAFT = 0
TRIGGER_NAME = "manual"
_HTTP_TIMEOUT = 60


def build_probe_clientdata(target_url: str) -> str:
    """Return the ``clientdata`` string for the transient probe flow.

    ``clientdata`` is a STRING-encoded JSON holding the flow's
    connectionReferences (empty -- the native HTTP action needs none) plus
    the Logic Apps definition: a "When an HTTP request is received"
    trigger (Request / kind Http, so it is invocable via a SAS callback
    URL), one native HTTP GET to the target, and a synchronous Response
    action that returns the probed status code.

    The Response action runs after the HTTP action whether it Succeeded or
    Failed (a non-2xx like 302/401/403 marks the HTTP action "Failed" but
    still yields outputs), so the trigger can reply synchronously with the
    status. A true egress block leaves ``reachableStatusCode`` null.

    Kept in lock-step with the capture recorder
    ``tests/captures/record_infra003_flow.py`` so the validated cassette
    matches what production sends.
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
            "Probe_HTTP": {
                "runAfter": {},
                "metadata": {},
                "type": "Http",
                "inputs": {"method": "GET", "uri": target_url},
            },
            "Respond": {
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
        "properties": {"connectionReferences": {}, "definition": definition},
        "schemaVersion": "1.0.0.0",
    }
    return json.dumps(clientdata)


@dataclass
class LiveProbeResult:
    """Outcome of one live egress probe.

    ``reachable`` is the tri-state answer:
      - True  -> the environment reached the endpoint (got an HTTP status).
      - False -> the request ran but got NO HTTP status (egress blocked:
                 DNS / TLS / connection / DLP).
      - None  -> the probe itself could not run to completion (create /
                 activate / callback failed), so egress is UNKNOWN and the
                 caller should fall back to the local probe result.
    """

    reachable: bool | None
    status_code: int | None = None
    stage: str = ""            # last stage reached: create/activate/callback/invoke/done
    detail: str = ""           # human-readable status/error for the finding


def _dv_headers(dv_token: str, extra: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {dv_token}",
        "Accept": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }
    if extra:
        headers.update(extra)
    return headers


def _workflows_url(env_url: str, key: str = "") -> str:
    base = f"{env_url.rstrip('/')}{DATAVERSE_API}/workflows"
    return f"{base}({key})" if key else base


def find_probe_flow_ids(
    env_url: str, dv_token: str, *, session: requests.Session | None = None
) -> list[str]:
    """Return the workflowids of every probe flow matching PROBE_FLOW_NAME.

    Read-only. Used for orphan detection (AC7) and to confirm cleanup.
    """
    sess = session or requests
    resp = sess.get(
        _workflows_url(env_url),
        headers=_dv_headers(dv_token),
        params={
            "$select": "workflowid,name,statecode",
            "$filter": f"name eq '{PROBE_FLOW_NAME}' and category eq {FLOW_CATEGORY}",
        },
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    rows = body.get("value", []) if isinstance(body, dict) else []
    return [r["workflowid"] for r in rows if isinstance(r, dict) and r.get("workflowid")]


def delete_probe_flow(
    env_url: str,
    dv_token: str,
    workflow_id: str,
    *,
    session: requests.Session | None = None,
) -> bool:
    """Delete one probe flow by workflowid. Deactivates first if an active
    flow refuses deletion. Treats 2xx + 404 as success. Never raises."""
    sess = session or requests
    url = _workflows_url(env_url, workflow_id)
    for deactivate_first in (False, True):
        if deactivate_first:
            try:
                sess.patch(
                    url,
                    headers=_dv_headers(
                        dv_token, {"Content-Type": "application/json", "If-Match": "*"}
                    ),
                    data=json.dumps({"statecode": STATECODE_DRAFT}),
                    timeout=_HTTP_TIMEOUT,
                )
            except requests.RequestException:
                return False
        try:
            resp = sess.delete(url, headers=_dv_headers(dv_token), timeout=_HTTP_TIMEOUT)
        except requests.RequestException:
            return False
        if resp.status_code in (200, 202, 204, 404):
            return True
        if resp.status_code not in (400, 409):
            return False  # non-retryable (e.g. 403)
    return False


def cleanup_orphan_probe_flows(
    env_url: str, dv_token: str, *, session: requests.Session | None = None
) -> int:
    """Delete every leftover probe flow matching PROBE_FLOW_NAME. Returns the
    count deleted. Best-effort; never raises. Call before/after probing so a
    crashed prior run cannot leave a residual flow."""
    try:
        ids = find_probe_flow_ids(env_url, dv_token, session=session)
    except requests.RequestException:
        return 0
    deleted = 0
    for wid in ids:
        if delete_probe_flow(env_url, dv_token, wid, session=session):
            deleted += 1
    return deleted


def _create_probe_flow(
    env_url: str, dv_token: str, target_url: str, session: requests.Session
) -> str | None:
    """POST the probe flow to the Dataverse workflow table. Returns the new
    workflowid (from the representation body or OData-EntityId header)."""
    body = {
        "category": FLOW_CATEGORY,
        "name": PROBE_FLOW_NAME,
        "type": FLOW_TYPE_DEFINITION,
        "description": "FlightCheck INFRA-003 transient reachability probe.",
        "primaryentity": "none",
        "clientdata": build_probe_clientdata(target_url),
    }
    resp = session.post(
        _workflows_url(env_url),
        headers=_dv_headers(
            dv_token,
            {"Content-Type": "application/json", "Prefer": "return=representation"},
        ),
        data=json.dumps(body),
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    try:
        parsed = resp.json()
        if isinstance(parsed, dict) and parsed.get("workflowid"):
            return parsed["workflowid"]
    except ValueError:
        pass
    entity_id = resp.headers.get("OData-EntityId", "")
    if "(" in entity_id and entity_id.endswith(")"):
        return entity_id.rsplit("(", 1)[1].rstrip(")")
    return None


def _activate_probe_flow(
    env_url: str, dv_token: str, workflow_id: str, session: requests.Session
) -> None:
    resp = session.patch(
        _workflows_url(env_url, workflow_id),
        headers=_dv_headers(
            dv_token, {"Content-Type": "application/json", "If-Match": "*"}
        ),
        data=json.dumps({"statecode": STATECODE_ACTIVE}),
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()


def _list_callback_url(
    flow_headers: dict, env_id: str, workflow_id: str, session: requests.Session
) -> str | None:
    """POST listCallbackUrl (Power Automate host) and extract the SAS URL.

    Non-mutating. Defensive across the known Logic Apps / Power Automate
    response shapes.
    """
    url = (
        f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/environments/{env_id}"
        f"/flows/{workflow_id}/triggers/{TRIGGER_NAME}/listCallbackUrl"
        f"?api-version={FLOW_API_VERSION}"
    )
    resp = session.post(
        url,
        headers={**flow_headers, "Content-Type": "application/json"},
        data="{}",
        timeout=_HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return _extract_callback_url(resp.json())


def _extract_callback_url(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    for container in (payload, payload.get("response") or {}):
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


def interpret_probe_response(body: Any) -> LiveProbeResult:
    """Map the synchronous trigger-response body to a LiveProbeResult.

    Body shape (confirmed by capture):
      {"reachableStatusCode": <int|null>, "actionStatus": "<str>"}

    An int status (any 2xx/3xx/4xx/5xx) means the environment REACHED the
    endpoint. A null status means the HTTP action ran but got no response
    (egress blocked).
    """
    status = body.get("reachableStatusCode") if isinstance(body, dict) else None
    if isinstance(status, bool):  # guard: bool is an int subclass
        status = None
    if isinstance(status, int):
        return LiveProbeResult(
            reachable=True,
            status_code=status,
            stage="done",
            detail=f"HTTP {status}",
        )
    return LiveProbeResult(
        reachable=False,
        status_code=None,
        stage="done",
        detail="no HTTP response (DNS / TLS / connection / DLP block)",
    )


def run_live_probe(
    *,
    env_url: str,
    dv_token: str,
    env_id: str,
    flow_headers: dict,
    target_url: str,
    session: requests.Session | None = None,
) -> LiveProbeResult:
    """Run one transient-flow egress probe against ``target_url``.

    Creates + activates a probe flow, triggers it once, reads the probed
    HTTP status, and ALWAYS deletes the flow (``finally``). Returns a
    LiveProbeResult; ``reachable is None`` means the probe could not run
    (caller should fall back to the local probe). Never raises.
    """
    sess = session or requests
    workflow_id: str | None = None
    stage = "create"
    try:
        workflow_id = _create_probe_flow(env_url, dv_token, target_url, sess)
        if not workflow_id:
            return LiveProbeResult(
                reachable=None, stage=stage, detail="flow create returned no id"
            )

        stage = "activate"
        _activate_probe_flow(env_url, dv_token, workflow_id, sess)

        stage = "callback"
        callback_url = _list_callback_url(flow_headers, env_id, workflow_id, sess)
        if not callback_url:
            return LiveProbeResult(
                reachable=None, stage=stage, detail="no trigger callback URL returned"
            )

        stage = "invoke"
        trig = sess.post(
            callback_url, json={}, headers={"Prefer": "wait"}, timeout=_HTTP_TIMEOUT
        )
        trig.raise_for_status()
        try:
            body = trig.json()
        except ValueError:
            body = None
        return interpret_probe_response(body)
    except requests.RequestException as exc:
        return LiveProbeResult(
            reachable=None,
            stage=stage,
            detail=f"egress probe {stage} failed: {type(exc).__name__}",
        )
    finally:
        if workflow_id:
            delete_probe_flow(env_url, dv_token, workflow_id, session=sess)
