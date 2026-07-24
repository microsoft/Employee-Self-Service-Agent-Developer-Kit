# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS FlightCheck — Live network-reachability probe via a temporary Power
Platform cloud flow (INFRA-002 support module).

WHY THIS EXISTS
===============
INFRA-002 needs to know whether **Power Platform's own egress** can reach
the customer's HR-system (Workday) endpoint. A local socket probe from the
maker's machine (INFRA-001 style) cannot answer that — the maker's laptop
and the Power Platform service boundary sit behind different firewalls. So
this module asks Power Platform to make the request *from its own infra*:

    create   -> a temporary cloud flow (HTTP-request trigger + HTTP HEAD + Response)
    activate -> turn the flow on so its trigger gets a callback URL
    callback -> ask Power Automate for the trigger's invoke (callback) URL
    trigger  -> POST the callback URL; the synchronous Response action returns
                the reachability result *as seen from Power Platform's infra*
    delete   -> remove the flow (net-zero state change)

MUTATION NOTICE
===============
Unlike every other FlightCheck probe, this module *creates and deletes* a
Dataverse ``workflow`` row. It runs ONLY behind explicit operator consent —
the ``--live-network-probe`` CLI flag, which the flightcheck skill sets after
the maker answers the network-connectivity consent prompt. The flow issues a
single unauthenticated HEAD request; **no business data is read, written, or
changed**, and no credentials are sent to the target. The flow is always
deleted in a ``finally`` so the environment is left net-zero. See
``checks/infrastructure.py`` (INFRA-002) for the consent gate and the
local-TCP fallback used when consent is withheld.

APIs used (see ``tests/fixtures/cassettes/INDEX.md`` → "API tier registry"):
  - Dataverse Web API v9.2 ``/workflows`` POST/PATCH/DELETE ....... documented
  - Power Automate ``.../triggers/manual/listCallbackUrl`` POST ... validated
    (issued by ``PowerPlatformAdminClient.list_callback_url``)
  - Logic Apps manual-trigger callback invoke ``POST {callbackUrl}`` validated

The flow definition, reachability classification, and robust delete are a
direct port of the validated INFRA-002 research spike (create -> activate ->
callback -> trigger -> delete), verified live against a real Dataverse env +
Workday endpoint.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # pragma: no cover - requests is a first-party framework dep
    raise

DATAVERSE_API_VERSION = "v9.2"

# Cloud flow (Modern Flow) discriminators on the Dataverse ``workflow`` entity.
WORKFLOW_CATEGORY_MODERN_FLOW = 5
WORKFLOW_TYPE_DEFINITION = 1
STATE_DRAFT = (0, 1)        # (statecode, statuscode)
STATE_ACTIVATED = (1, 2)

# Designer default name for the "When a HTTP request is received" trigger.
TRIGGER_NAME = "manual"
DEFAULT_FLOW_NAME_PREFIX = "ESS FlightCheck INFRA-002 probe (temporary)"

# Workday redirects an unrecognized instance URL to its "invalid-url" landing
# page, so seeing this in the response Location means: the host is reachable,
# but the instance URL itself is not valid. Workday-specific; extend for other
# SaaS targets as INFRA-002 grows beyond Workday.
INVALID_URL_MARKERS = ("/invalid-url", "community.workday.com/invalid-url")


class FlowProbeError(RuntimeError):
    """The live flow lifecycle could not complete.

    Raised for any create/activate/callback/trigger failure — insufficient
    Dataverse permissions, a DLP policy blocking the HTTP connector, a missing
    callback URL, transient 5xx, etc. INFRA-002 catches this and falls back to
    the local-TCP probe (the flow is always deleted first via ``run_live_probe``'s
    ``finally``, so net-zero is preserved even on failure).
    """


# ─────────────────────────────────────────────────────────────────────────
# Dataverse Web API — workflow create / activate / delete (documented tier)
# ─────────────────────────────────────────────────────────────────────────


def _dv_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }


def _dataverse_detail(resp: "requests.Response") -> str:
    try:
        return resp.json().get("error", {}).get("message", resp.text)
    except ValueError:
        return resp.text


def build_client_data(target_url: str) -> str:
    """Return the ``clientdata`` JSON string for an INFRA-002 reachability flow.

    Trigger: "When a HTTP request is received" (Request/Http).
    Action : native HTTP action (type ``Http``, no connector -> no connection
             reference), method HEAD against the target -> no credentials leave
             Power Platform.
    Action : Response returns the outcome synchronously so the caller learns
             reachability without polling run history.

    ``reachable`` is true when the target returned ANY HTTP status (a 3xx login
    redirect or a 4xx still proves the network path is open); only a timeout or
    DNS failure (no statusCode) yields ``reachable=false``. ``redirect_location``
    is surfaced so INFRA-002 can detect Workday's invalid-instance redirect.
    """
    definition = {
        "$schema": (
            "https://schema.management.azure.com/providers/Microsoft.Logic/"
            "schemas/2016-06-01/workflowdefinition.json#"
        ),
        "contentVersion": "1.0.0.0",
        "parameters": {},
        "triggers": {
            TRIGGER_NAME: {
                "type": "Request",
                "kind": "Http",
                "inputs": {"schema": {}},
            }
        },
        "actions": {
            "HTTP_HEAD": {
                "type": "Http",
                "inputs": {"method": "HEAD", "uri": target_url},
                "runAfter": {},
            },
            "Response": {
                "type": "Response",
                "kind": "Http",
                "runAfter": {"HTTP_HEAD": ["Succeeded", "Failed", "TimedOut"]},
                "inputs": {
                    "statusCode": 200,
                    "body": {
                        "reachable": (
                            "@greater(int(coalesce("
                            "actions('HTTP_HEAD')?['outputs']?['statusCode'], 0)), 0)"
                        ),
                        "action_status": "@actions('HTTP_HEAD')['status']",
                        "http_status": "@actions('HTTP_HEAD')?['outputs']?['statusCode']",
                        "redirect_location": (
                            "@coalesce("
                            "actions('HTTP_HEAD')?['outputs']?['headers']?['Location'], "
                            "actions('HTTP_HEAD')?['outputs']?['headers']?['location'], '')"
                        ),
                        "error": "@actions('HTTP_HEAD')?['error']?['message']",
                    },
                },
            },
        },
    }
    client_data = {
        "properties": {"connectionReferences": {}, "definition": definition},
        "schemaVersion": "1.0.0.0",
    }
    return json.dumps(client_data)


def create_flow(env_url: str, dv_token: str, name: str, target_url: str, *, timeout: float = 60.0) -> str:
    """Create a draft cloud flow and return its Dataverse ``workflowid`` (GUID)."""
    body = {
        "category": WORKFLOW_CATEGORY_MODERN_FLOW,
        "type": WORKFLOW_TYPE_DEFINITION,
        "name": name,
        "description": "Temporary INFRA-002 network-reachability probe. Safe to delete.",
        "primaryentity": "none",
        "statecode": STATE_DRAFT[0],
        "statuscode": STATE_DRAFT[1],
        "clientdata": build_client_data(target_url),
    }
    try:
        resp = requests.post(
            f"{env_url}/api/data/{DATAVERSE_API_VERSION}/workflows",
            headers={**_dv_headers(dv_token), "Prefer": "return=representation"},
            json=body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise FlowProbeError(f"Dataverse create workflow request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise FlowProbeError(
            f"Dataverse create workflow failed ({resp.status_code}): {_dataverse_detail(resp)}"
        )
    workflow_id = None
    if resp.content:
        try:
            workflow_id = resp.json().get("workflowid")
        except ValueError:
            workflow_id = None
    if not workflow_id:
        match = re.search(r"\(([^)]+)\)", resp.headers.get("OData-EntityId", ""))
        workflow_id = match.group(1) if match else None
    if not workflow_id:
        raise FlowProbeError("Dataverse create succeeded but no workflowid was returned.")
    return workflow_id


def set_flow_state(env_url: str, dv_token: str, flow_id: str, state: tuple[int, int], *, timeout: float = 60.0) -> None:
    """Activate ``(1, 2)`` or deactivate ``(0, 1)`` a cloud flow."""
    try:
        resp = requests.patch(
            f"{env_url}/api/data/{DATAVERSE_API_VERSION}/workflows({flow_id})",
            headers=_dv_headers(dv_token),
            json={"statecode": state[0], "statuscode": state[1]},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise FlowProbeError(f"Dataverse set-state request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise FlowProbeError(
            f"Dataverse set-state failed ({resp.status_code}): {_dataverse_detail(resp)}"
        )


def delete_flow(env_url: str, dv_token: str, flow_id: str, *, attempts: int = 5, timeout: float = 60.0) -> None:
    """Delete a cloud flow (net-zero cleanup), robust to transient Dataverse 5xx.

    Two realities are handled here:
      * an activated flow cannot be deleted, so we deactivate first and give the
        state change a moment to commit;
      * the Dataverse ``workflow`` DELETE intermittently returns a 500
        "There is no active transaction" error, which clears on retry.
    A 404 means the row is already gone, which we treat as success.
    """
    try:
        set_flow_state(env_url, dv_token, flow_id, STATE_DRAFT, timeout=timeout)
        time.sleep(2)  # let the deactivation commit before deleting
    except FlowProbeError:
        # Benign (already draft, or deactivation raced); the delete retry loop
        # below surfaces any genuinely blocking issue.
        pass

    last_detail = ""
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.delete(
                f"{env_url}/api/data/{DATAVERSE_API_VERSION}/workflows({flow_id})",
                headers=_dv_headers(dv_token),
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_detail = str(exc)
            if attempt < attempts:
                time.sleep(2 * attempt)
                continue
            raise FlowProbeError(f"Dataverse delete workflow request failed: {exc}") from exc
        if resp.status_code < 400 or resp.status_code == 404:
            return
        last_detail = _dataverse_detail(resp)
        if resp.status_code in (500, 502, 503, 504) and attempt < attempts:
            time.sleep(2 * attempt)
            continue
        raise FlowProbeError(
            f"Dataverse delete workflow failed ({resp.status_code}): {last_detail}"
        )
    raise FlowProbeError(
        f"Dataverse delete workflow failed after {attempts} attempts: {last_detail}"
    )


# ─────────────────────────────────────────────────────────────────────────
# Trigger invoke — POST the SAS callback URL (Logic Apps, validated tier)
# ─────────────────────────────────────────────────────────────────────────


def _poll_async_run(session: "requests.Session", poll_url: str, timeout: float, attempts: int = 20) -> dict[str, Any]:
    """Poll an async run URL until it stops returning 202, then return the result."""
    for _ in range(attempts):
        resp = session.get(poll_url, allow_redirects=True, timeout=timeout)
        if resp.status_code == 202:
            time.sleep(float(resp.headers.get("Retry-After", "2")))
            continue
        try:
            body: Any = resp.json()
        except ValueError:
            body = resp.text
        return {"http_status": resp.status_code, "body": body}
    return {"http_status": 202, "note": "still running after polling budget exhausted"}


def trigger_and_read(callback_url: str, *, max_redirects: int = 5, timeout: float = 120.0) -> dict[str, Any]:
    """Invoke the callback URL and return the flow's result.

    Handles the two non-2xx outcomes a Power Automate "Request" trigger can give:
      * 3xx redirect  -> the gateway points us at another host; we re-POST there
                         (method + body preserved) so we still get the Response.
      * 202 Accepted  -> the run is async; we poll the Location until it finishes.
    The redirect chain is reported so a stuck 302 is diagnosable.
    """
    redirect_chain: list[dict[str, str]] = []
    url = callback_url
    session = requests.Session()
    try:
        for _ in range(max_redirects):
            try:
                resp = session.post(url, json={}, allow_redirects=False, timeout=timeout)
            except requests.RequestException as exc:
                raise FlowProbeError(f"Flow trigger invoke failed: {exc}") from exc

            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location", "")
                redirect_chain.append({"status": str(resp.status_code), "location": location})
                if not location:
                    break
                url = location
                continue

            if resp.status_code == 202:  # async run: poll the Location to completion
                poll_url = resp.headers.get("Location", "")
                final = _poll_async_run(session, poll_url, timeout) if poll_url else None
                return {
                    "http_status": resp.status_code,
                    "note": "async run; polled Location for the terminal result",
                    "final": final,
                    "redirect_chain": redirect_chain,
                }

            try:
                payload: Any = resp.json()
            except ValueError:
                payload = resp.text
            return {
                "http_status": resp.status_code,
                "location": resp.headers.get("Location"),
                "body": payload,
                "redirect_chain": redirect_chain,
            }

        return {
            "http_status": "unresolved",
            "note": "too many redirects (>%d) without a terminal response" % max_redirects,
            "redirect_chain": redirect_chain,
        }
    finally:
        session.close()


# ─────────────────────────────────────────────────────────────────────────
# Verdict classification
# ─────────────────────────────────────────────────────────────────────────


def _result_body(result: dict[str, Any]) -> dict[str, Any]:
    """Extract the flow Response body from a trigger_and_read result.

    Synchronous runs carry it at ``result['body']``; async runs nest it under
    ``result['final']['body']``.
    """
    if not isinstance(result, dict):
        return {}
    body = result.get("body")
    if not isinstance(body, dict):
        final = result.get("final")
        if isinstance(final, dict):
            body = final.get("body")
    return body if isinstance(body, dict) else {}


def _response_location(body: dict[str, Any]) -> str:
    location = body.get("redirect_location")
    if isinstance(location, str):
        return location
    return ""


def classify(result: dict[str, Any]) -> dict[str, Any]:
    """Classify the raw flow result into reachability + instance-validity + access.

    reachable      : did the host answer at all (network path open)?  <- INFRA-002
    instance_valid : did it answer *without* redirecting to an invalid-url page?
    access         : ALWAYS "not_tested" — the probe sends no credentials, so
                     authorization cannot be (and is not) determined here.
    """
    body = _result_body(result)
    status = body.get("http_status") if body else None
    reachable = (body.get("reachable") is True) or (isinstance(status, int) and status > 0)
    location = _response_location(body)
    invalid_instance = any(marker in location.lower() for marker in INVALID_URL_MARKERS)

    if not reachable:
        return {
            "reachable": False,
            "instance_valid": False,
            "access": "not_tested",
            "http_status": status,
            "action_status": body.get("action_status"),
            "redirect_location": location or None,
            "error": body.get("error"),
        }
    if invalid_instance:
        return {
            "reachable": True,
            "instance_valid": False,
            "access": "not_tested",
            "http_status": status,
            "action_status": body.get("action_status"),
            "redirect_location": location,
            "error": body.get("error"),
        }
    return {
        "reachable": True,
        "instance_valid": True,
        "access": "not_tested",
        "http_status": status,
        "action_status": body.get("action_status"),
        "redirect_location": location or None,
        "error": body.get("error"),
    }


# ─────────────────────────────────────────────────────────────────────────
# Orchestration — the full net-zero probe
# ─────────────────────────────────────────────────────────────────────────


def run_live_probe(
    *,
    env_url: str,
    dv_token: str,
    pp_admin: Any,
    env_id: str,
    target_url: str,
    name_prefix: str = DEFAULT_FLOW_NAME_PREFIX,
    settle_secs: float = 3.0,
) -> dict[str, Any]:
    """Run the full create -> activate -> callback -> trigger -> delete chain.

    Returns the classified verdict dict (see ``classify``) augmented with:
      - ``flow_id`` / ``flow_name`` — the temporary flow's identity
      - ``deleted`` (bool) — whether net-zero cleanup succeeded
      - ``cleanup_note`` (str) — manual-deletion guidance if cleanup failed
      - ``raw`` — the raw trigger_and_read result (diagnostics)

    Raises ``FlowProbeError`` if the flow could not be created/activated/triggered
    (INFRA-002 catches this and falls back to a local-TCP probe). The temporary
    flow is always deleted in ``finally`` so the environment stays net-zero even
    when the trigger step fails.
    """
    name = f"{name_prefix} {uuid.uuid4().hex[:8]}"
    flow_id: str | None = None
    deleted = False
    cleanup_note = ""
    result: dict[str, Any]
    try:
        flow_id = create_flow(env_url, dv_token, name, target_url)
        set_flow_state(env_url, dv_token, flow_id, STATE_ACTIVATED)
        callback_url = pp_admin.list_callback_url(env_id, flow_id)
        if not callback_url:
            raise FlowProbeError(
                "Power Automate returned no trigger callback URL "
                "(flow not activated, or the trigger name is not 'manual')."
            )
        time.sleep(settle_secs)  # small grace period for the trigger URL to go live
        result = trigger_and_read(callback_url)
    finally:
        if flow_id:
            try:
                delete_flow(env_url, dv_token, flow_id)
                deleted = True
            except FlowProbeError as exc:
                cleanup_note = (
                    f"The temporary probe flow could not be deleted automatically: "
                    f"'{name}' (workflowid {flow_id}). {exc} "
                    f"Delete it manually at https://make.powerautomate.com (My flows)."
                )

    verdict = classify(result)
    verdict["flow_id"] = flow_id
    verdict["flow_name"] = name
    verdict["deleted"] = deleted
    verdict["cleanup_note"] = cleanup_note
    verdict["raw"] = result
    return verdict
