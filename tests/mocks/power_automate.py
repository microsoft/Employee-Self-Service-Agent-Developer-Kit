# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Mock response builders for the Power Automate transient-flow lifecycle.

# ─────────────────────────────────────────────────────────────────
# MOCK_STATUS = "validated"
#
# Backed by a real captured cassette. Safe to use in FlightCheck
# integration tests under tests/flightcheck/.
#
# Cassette: tests/fixtures/cassettes/flightcheck_infra003_flow.yaml
# Recorder: tests/captures/record_infra003_flow.py
# Endpoints covered: see tests/fixtures/cassettes/INDEX.md
#   "Power Automate flow lifecycle" row + confirmed-endpoints rows.
# ─────────────────────────────────────────────────────────────────

Backs INFRA-003's opt-in ``--live-probe`` egress path (the kit's only
mutating path). A cloud flow is a Dataverse ``workflow`` row (category 5),
so create / activate / find / delete are Dataverse Web API calls; the
trigger callback URL comes from the Power Automate API; the trigger itself
POSTs the SAS-signed runtime URL.

Response shapes below are copied from the cassette interactions (all
identifiers already redacted to the standard mock values):
- create           workflows (POST 201)   -> cassette lines ~98-146
- activate         workflows({id}) (PATCH 204) -> ~167-212
- listCallbackUrl  (POST 200)             -> ~229-273
- invoke           SAS callback (POST 200) -> ~291-356
- find (orphan)    workflows?$filter (GET 200) -> ~13-63, ~599-642
- delete           workflows({id}) (DELETE 204) -> ~661-702

References:
- Manage flows with code: https://learn.microsoft.com/power-automate/manage-flows-with-code
- Production source:
  solutions/ess-maker-skills/scripts/flightcheck/live_egress_probe.py
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Validation status — read by tests/conftest.py:require_validated_mock().
MOCK_STATUS = "validated"
MOCK_CASSETTE = "tests/fixtures/cassettes/flightcheck_infra003_flow.yaml"

FLOW_BASE = "https://api.flow.microsoft.com"
FLOW_API_VERSION = "2016-11-01"
TRIGGER_NAME = "manual"

# Stable mock identity values (match the redacted cassette).
MOCK_ENV_URL = "https://orgmocktenant.crm.dynamics.com"
MOCK_ENV_ID = "00000000-0000-0000-0000-000000001111"
MOCK_WORKFLOW_ID = "00000000-0000-0000-0000-000000001111"
MOCK_CALLBACK_URL = (
    "https://mockenv.00.environment.api.powerplatform.com/powerautomate/"
    "automations/direct/cu/04/workflows/00000000000000000000000000000000/"
    "triggers/manual/paths/invoke"
    "?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=REDACTED_SAS_SIG"
)

_WORKFLOWS_PATH = "/api/data/v9.2/workflows"


# ────────────────────────────────────────────────────────────────────────
# Dataverse workflow-table operations
# ────────────────────────────────────────────────────────────────────────


def create_workflow(
    *,
    env_url: str = MOCK_ENV_URL,
    workflow_id: str = MOCK_WORKFLOW_ID,
    name: str = "flightcheck-infra003-probe",
    status: int = 201,
) -> dict[str, Any]:
    """Mock POST {env}/api/data/v9.2/workflows (create cloud flow).

    Returns the created row with ``return=representation`` so ``workflowid``
    is in the body (production also falls back to the ``OData-EntityId``
    header). Cassette: create 201.
    """
    return {
        "method": "POST",
        "url": f"{env_url.rstrip('/')}{_WORKFLOWS_PATH}",
        "json": {
            "@odata.context": (
                f"{env_url.rstrip('/')}{_WORKFLOWS_PATH}/$entity"
            ),
            "workflowid": workflow_id,
            "name": name,
            "category": 5,
            "type": 1,
            "statecode": 0,
            "statuscode": 1,
            "primaryentity": "none",
        },
        "status": status,
        "headers": {
            "OData-EntityId": (
                f"{env_url.rstrip('/')}{_WORKFLOWS_PATH}({workflow_id})"
            ),
            "Preference-Applied": "return=representation",
        },
    }


def activate_workflow(
    *,
    env_url: str = MOCK_ENV_URL,
    workflow_id: str = MOCK_WORKFLOW_ID,
    status: int = 204,
) -> dict[str, Any]:
    """Mock PATCH {env}/api/data/v9.2/workflows({id}) {"statecode":1}.

    Cassette: activate 204 (empty body).
    """
    return {
        "method": "PATCH",
        "url": f"{env_url.rstrip('/')}{_WORKFLOWS_PATH}({workflow_id})",
        "status": status,
    }


def find_workflows(
    *,
    env_url: str = MOCK_ENV_URL,
    workflows: Iterable[Mapping[str, Any]] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """Mock GET {env}/api/data/v9.2/workflows?$filter=name eq '...'.

    Registered without a query string so it matches the $select/$filter
    narrowing (server-side narrowing on the same path = one mock).
    ``workflows`` defaults to an empty collection (no orphans). Cassette:
    orphan-scan 200.
    """
    return {
        "method": "GET",
        "url": f"{env_url.rstrip('/')}{_WORKFLOWS_PATH}",
        "json": {"value": list(workflows) if workflows is not None else []},
        "status": status,
    }


def workflow_row(
    *, workflow_id: str = MOCK_WORKFLOW_ID, name: str = "flightcheck-infra003-probe",
    statecode: int = 1,
) -> dict[str, Any]:
    """A single ``workflows`` row for assembling a find_workflows collection."""
    return {"workflowid": workflow_id, "name": name, "statecode": statecode}


def delete_workflow(
    *,
    env_url: str = MOCK_ENV_URL,
    workflow_id: str = MOCK_WORKFLOW_ID,
    status: int = 204,
) -> dict[str, Any]:
    """Mock DELETE {env}/api/data/v9.2/workflows({id}). Cassette: delete 204."""
    return {
        "method": "DELETE",
        "url": f"{env_url.rstrip('/')}{_WORKFLOWS_PATH}({workflow_id})",
        "status": status,
    }


# ────────────────────────────────────────────────────────────────────────
# Power Automate trigger callback + invoke
# ────────────────────────────────────────────────────────────────────────


def list_callback_url(
    *,
    env_id: str = MOCK_ENV_ID,
    workflow_id: str = MOCK_WORKFLOW_ID,
    callback_url: str = MOCK_CALLBACK_URL,
    status: int = 200,
) -> dict[str, Any]:
    """Mock POST .../flows/{id}/triggers/manual/listCallbackUrl.

    The SAS-signed URL is nested under ``response.value`` (also exposed via
    ``basePath`` + ``queries``). Cassette: listCallbackUrl 200.
    """
    return {
        "method": "POST",
        "url": (
            f"{FLOW_BASE}/providers/Microsoft.ProcessSimple/environments/"
            f"{env_id}/flows/{workflow_id}/triggers/{TRIGGER_NAME}/"
            f"listCallbackUrl?api-version={FLOW_API_VERSION}"
        ),
        "json": {
            "response": {
                "value": callback_url,
                "method": "POST",
                "basePath": callback_url.split("?", 1)[0],
                "queries": {
                    "api-version": "1",
                    "sp": "/triggers/manual/run",
                    "sv": "1.0",
                    "sig": "REDACTED_SAS_SIG",
                },
            },
            "httpStatusCode": "OK",
        },
        "status": status,
    }


def invoke_probe(
    *,
    callback_url: str = MOCK_CALLBACK_URL,
    reachable_status_code: int | None = 302,
    action_status: str = "Failed",
    status: int = 200,
) -> dict[str, Any]:
    """Mock POST <SAS callback URL> (Prefer: wait) — the synchronous trigger.

    Body carries the probed HTTP status: an int (``302`` here) means the
    environment REACHED the endpoint; ``None`` means egress was blocked (no
    HTTP response). Cassette: invoke 200 (``reachableStatusCode: 302``).
    """
    return {
        "method": "POST",
        "url": callback_url,
        "json": {
            "reachableStatusCode": reachable_status_code,
            "actionStatus": action_status,
        },
        "status": status,
    }
