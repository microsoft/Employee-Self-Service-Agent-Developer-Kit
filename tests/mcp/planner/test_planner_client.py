# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Request-construction contract for the AgentConfiguration planner/role client.

Every PlannerClient method is exercised through an httpx.MockTransport so the
exact route, HTTP method, camelCase body, OData query, and mutation headers each
endpoint builds are pinned without touching the network. Identity (tenant + the
caller object id) is decoded from a crafted access token, mirroring production;
no identity value is ever a method argument.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import pytest


REPO_ROOT = Path(__file__).parents[3]
MCP_ROOT = REPO_ROOT / "solutions" / "ess-maker-skills" / "src" / "mcp"
PLANNER_DIR = MCP_ROOT / "agentconfig_planner"
CORE_DIR = MCP_ROOT / "agentconfig_core"
sys.path.insert(0, str(CORE_DIR))
sys.path.insert(0, str(PLANNER_DIR))

import planner_client as planner_client_module  # noqa: E402
import base_client as base_client_module  # noqa: E402
import roles_surface as roles_module  # noqa: E402


TENANT_ID = "11111111-2222-3333-4444-555555555555"
CALLER_OID = "99999999-8888-7777-6666-555555555555"
BASE = "https://substrate.office.com/weveb2/api/beta"


def _token() -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": TENANT_ID, "oid": CALLER_OID}).encode("utf-8")
    ).rstrip(b"=")
    return f"header.{payload.decode('ascii')}.signature"


def _make_client(monkeypatch, handler) -> planner_client_module.PlannerClient:
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token())
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)
    monkeypatch.delenv("AGENTCONFIG_BASE_URL", raising=False)
    monkeypatch.delenv("AGENTCONFIG_PROJECTS_BASE_URL", raising=False)
    return planner_client_module.PlannerClient(transport=httpx.MockTransport(handler))


def _recorder(response_json=None, status: int = 200):
    """Return (captured_requests, handler) recording every request."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = response_json if response_json is not None else {"value": []}
        return httpx.Response(status, json=body)

    return requests, handler


def _run(client, coro_factory):
    async def run():
        try:
            return await coro_factory()
        finally:
            await client.aclose()

    return asyncio.run(run())


async def _no_sleep(*_args, **_kwargs):
    """Drop-in for asyncio.sleep so retry backoff is instant under test."""
    return None


# ---------------------------------------------------------------------------
# Identity / base URL wiring
# ---------------------------------------------------------------------------
def test_client_decodes_tenant_and_caller_and_defaults_base(monkeypatch) -> None:
    _, handler = _recorder()
    client = _make_client(monkeypatch, handler)

    assert client.tenant_id == TENANT_ID
    assert client._caller_object_id == CALLER_OID
    assert client.projects_base_url == BASE
    assert client.projects_base_url == planner_client_module._DEFAULT_AGENTCONFIG_PROJECTS_BASE_URL
    # The bearer token must never leak through the client's repr.
    assert _token() not in repr(client)


def test_projects_base_url_is_overridable_and_https_only(monkeypatch) -> None:
    _, handler = _recorder()
    monkeypatch.setenv(
        "AGENTCONFIG_PROJECTS_BASE_URL", "https://substrate.example.test/beta/"
    )
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", _token())
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)
    client = planner_client_module.PlannerClient(
        transport=httpx.MockTransport(handler)
    )
    assert client.projects_base_url == "https://substrate.example.test/beta"

    monkeypatch.setenv("AGENTCONFIG_PROJECTS_BASE_URL", "http://insecure.test")
    with pytest.raises(ValueError, match="HTTPS"):
        planner_client_module.PlannerClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def test_project_routes_methods_and_bodies(monkeypatch) -> None:
    requests, handler = _recorder()
    client = _make_client(monkeypatch, handler)

    def calls():
        return asyncio.gather(
            client.list_agent_configuration_projects(),
            client.get_agent_configuration_project("proj1", {"select": "name"}),
            client.create_agent_configuration_project(
                {"name": "Employee Self Serve"}, idempotency_key="idem-1"
            ),
            client.archive_agent_configuration_project("proj1", "etag-p"),
        )

    _run(client, calls)

    listing = next(r for r in requests if r.method == "GET" and r.url.path.endswith("agentConfigurationProjects"))
    assert str(listing.url) == f"{BASE}/me/agentConfigurationProjects"

    getting = next(
        r for r in requests if r.method == "GET" and "('proj1')" in str(r.url)
    )
    assert getting.url.params["$select"] == "name"

    creating = next(r for r in requests if r.method == "POST")
    assert str(creating.url) == f"{BASE}/me/agentConfigurationProjects"
    assert json.loads(creating.content) == {"name": "Employee Self Serve"}
    assert creating.headers["Idempotency-Key"] == "idem-1"

    archiving = next(r for r in requests if r.method == "PATCH")
    assert json.loads(archiving.content) == {"state": "Archived"}
    assert archiving.headers["If-Match"] == "etag-p"


def test_project_id_is_odata_escaped_and_url_encoded(monkeypatch) -> None:
    requests, handler = _recorder()
    client = _make_client(monkeypatch, handler)

    _run(client, lambda: client.get_agent_configuration_project("a'b/c"))

    assert b"agentConfigurationProjects('a%27%27b%2Fc')" in requests[0].url.raw_path


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------
def test_plan_routes_nest_under_project_and_archive_uses_status(monkeypatch) -> None:
    requests, handler = _recorder()
    client = _make_client(monkeypatch, handler)

    def calls():
        return asyncio.gather(
            client.create_project_plan("proj1", {"ownedById": "u1"}, "idem-2"),
            client.update_project_plan("proj1", "plan1", {"status": "Active"}, "etag-pl"),
            client.archive_project_plan("proj1", "plan1", "etag-pl"),
        )

    _run(client, calls)

    creating = next(r for r in requests if r.method == "POST")
    assert str(creating.url) == (
        f"{BASE}/me/agentConfigurationProjects('proj1')/agentPlans"
    )
    assert json.loads(creating.content) == {"ownedById": "u1"}
    assert creating.headers["Idempotency-Key"] == "idem-2"

    updating = next(
        r for r in requests if r.method == "PATCH" and json.loads(r.content) == {"status": "Active"}
    )
    assert str(updating.url) == (
        f"{BASE}/me/agentConfigurationProjects('proj1')/agentPlans('plan1')"
    )
    assert updating.headers["If-Match"] == "etag-pl"

    archiving = next(
        r for r in requests if r.method == "PATCH" and json.loads(r.content) == {"status": "Archived"}
    )
    # Plans archive via `status`, projects via `state` - the fields differ.
    assert "state" not in json.loads(archiving.content)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
def test_task_routes_lifecycle_and_headers(monkeypatch) -> None:
    requests, handler = _recorder()
    client = _make_client(monkeypatch, handler)

    def calls():
        return asyncio.gather(
            client.create_project_plan_task("proj1", "plan1", {"title": "T"}, "idem-3"),
            client.get_project_plan_task("proj1", "plan1", "task1"),
            client.set_project_plan_task_state("proj1", "plan1", "task1", "InProgress", "e"),
            client.delete_project_plan_task("proj1", "plan1", "task1", "etag-t"),
        )

    _run(client, calls)

    tasks_url = (
        f"{BASE}/me/agentConfigurationProjects('proj1')"
        "/agentPlans('plan1')/agentPlanTasks"
    )
    creating = next(r for r in requests if r.method == "POST")
    assert str(creating.url) == tasks_url
    assert json.loads(creating.content) == {"title": "T"}
    assert creating.headers["Idempotency-Key"] == "idem-3"

    setting = next(r for r in requests if r.method == "PATCH")
    assert str(setting.url) == f"{tasks_url}('task1')"
    assert json.loads(setting.content) == {"state": "InProgress"}

    deleting = next(r for r in requests if r.method == "DELETE")
    assert str(deleting.url) == f"{tasks_url}('task1')"
    assert deleting.headers["If-Match"] == "etag-t"


def test_task_caller_scoping_expands_to_caller_direct_and_active_roles(
    monkeypatch,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "agentRoleAssignments" in str(request.url):
            return httpx.Response(
                200,
                json={
                    # The assignment response projects the role name under
                    # ``role``; the $filter grammar keys it as ``roleId`` but
                    # the response body does not carry ``roleId``.
                    "value": [
                        {"role": "ServiceNowAdmin"},
                        {"role": "WorkdayAdmin"},
                    ]
                },
            )
        return httpx.Response(200, json={"value": []})

    client = _make_client(monkeypatch, handler)

    _run(
        client,
        lambda: client.list_project_plan_tasks_for_caller("proj1", "plan1"),
    )

    role_calls = [r for r in requests if "agentRoleAssignments" in str(r.url)]
    task_calls = [r for r in requests if "agentPlanTasks" in str(r.url)]
    # The caller's Active role assignments on this plan are resolved first...
    assert len(role_calls) == 1
    assert role_calls[0].url.params["$filter"] == (
        f"targetPlanId eq 'plan1' and subjectObjectId eq '{CALLER_OID}' "
        "and status eq 'Active'"
    )
    # ...then the task query expands to the caller oid plus every active role,
    # so role-pooled tasks (assignedToRoleId) are not silently dropped.
    assert len(task_calls) == 1
    assert task_calls[0].url.params["$filter"] == (
        f"(assignedToId eq '{CALLER_OID}' "
        "or (assignedToRoleId eq 'ServiceNowAdmin' and assignedToType eq 'Role') "
        "or (assignedToRoleId eq 'WorkdayAdmin' and assignedToType eq 'Role')) "
        "and state ne 'Completed'"
    )


def test_task_caller_scoping_preserves_caller_supplied_filter(monkeypatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "agentRoleAssignments" in str(request.url):
            return httpx.Response(
                200, json={"value": [{"role": "ServiceNowAdmin"}]}
            )
        return httpx.Response(200, json={"value": []})

    client = _make_client(monkeypatch, handler)

    _run(
        client,
        lambda: client.list_project_plan_tasks_for_caller(
            "proj1", "plan1", {"filter": "state eq 'InProgress'"}
        ),
    )

    task_call = next(r for r in requests if "agentPlanTasks" in str(r.url))
    assert task_call.url.params["$filter"] == (
        f"((assignedToId eq '{CALLER_OID}' "
        "or (assignedToRoleId eq 'ServiceNowAdmin' and assignedToType eq 'Role')) "
        "and state ne 'Completed') "
        "and (state eq 'InProgress')"
    )


def test_caller_scoping_requires_object_id_claim(monkeypatch) -> None:
    _, handler = _recorder()
    # A token with tid but no oid claim.
    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": TENANT_ID}).encode("utf-8")
    ).rstrip(b"=")
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", f"h.{payload.decode()}.s")
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)
    client = planner_client_module.PlannerClient(
        transport=httpx.MockTransport(handler)
    )
    assert client._caller_object_id is None

    with pytest.raises(base_client_module.AgentConfigApiError, match="oid"):
        _run(client, lambda: client.list_project_plan_tasks_for_caller("p", "pl"))


def test_role_assigned_task_targets_a_role_pool(monkeypatch) -> None:
    requests, handler = _recorder()
    client = _make_client(monkeypatch, handler)

    _run(
        client,
        lambda: client.create_role_assigned_project_plan_task(
            "proj1", "plan1", "ServiceNowAdmin", "Configure ServiceNow"
        ),
    )

    assert json.loads(requests[0].content) == {
        "title": "Configure ServiceNow",
        "assignedToId": "ServiceNowAdmin",
        "assignedToType": "Role",
        "assignedToRoleId": "ServiceNowAdmin",
    }


def test_complete_task_normalizes_outputs_and_enforces_environment_rule(
    monkeypatch,
) -> None:
    requests, handler = _recorder()
    client = _make_client(monkeypatch, handler)

    _run(
        client,
        lambda: client.complete_project_plan_task(
            "proj1",
            "plan1",
            "task1",
            [
                {
                    "key": "prod-env",
                    "kind": "Environment",
                    "attributes": [{"key": "environmentId", "value": "E-1"}],
                }
            ],
            "etag-t",
        ),
    )

    body = json.loads(requests[0].content)
    assert body["state"] == "Completed"
    assert body["outputs"][0] == {
        "key": "prod-env",
        "kind": "Environment",
        "attributes": [{"key": "environmentId", "value": "E-1"}],
    }


@pytest.mark.parametrize(
    ("method_name", "args", "match"),
    [
        ("set_project_plan_task_state", ("p", "pl", "t", "Bogus", "e"), "state must be"),
        (
            "update_project_plan_task",
            ("p", "pl", "t", {"state": "Completed"}, "e"),
            "not accepted here",
        ),
        (
            "create_role_assigned_project_plan_task",
            ("p", "pl", "NotARole", "title"),
            "role must be one of",
        ),
    ],
)
def test_task_validation_rejects_bad_input(
    monkeypatch, method_name: str, args: tuple, match: str
) -> None:
    _, handler = _recorder()
    client = _make_client(monkeypatch, handler)
    with pytest.raises(ValueError, match=match):
        _run(client, lambda: getattr(client, method_name)(*args))


def test_complete_task_rejects_environment_output_without_environment_id(
    monkeypatch,
) -> None:
    _, handler = _recorder()
    client = _make_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="environmentId"):
        _run(
            client,
            lambda: client.complete_project_plan_task(
                "p",
                "pl",
                "t",
                [{"key": "e", "kind": "Environment", "attributes": []}],
                "etag",
            ),
        )


def test_complete_task_rejects_duplicate_output_keys(monkeypatch) -> None:
    _, handler = _recorder()
    client = _make_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="duplicate key"):
        _run(
            client,
            lambda: client.complete_project_plan_task(
                "p",
                "pl",
                "t",
                [
                    {"key": "dup", "kind": "Custom", "attributes": []},
                    {"key": "dup", "kind": "Custom", "attributes": []},
                ],
                "etag",
            ),
        )


# ---------------------------------------------------------------------------
# Role attestation (tenant-sharded)
# ---------------------------------------------------------------------------
def test_role_assignment_routes_are_tenant_sharded(monkeypatch) -> None:
    requests, handler = _recorder()
    client = _make_client(monkeypatch, handler)

    def calls():
        return asyncio.gather(
            client.list_plan_role_assignments("plan1", role="WorkdayAdmin", status="Active"),
            client.get_role_assignment("assign1"),
            client.attest_plan_role("plan1", "subject-oid", "WorkdayAdmin"),
            client.revoke_role_assignment("assign1", "etag-a"),
        )

    _run(client, calls)

    collection = f"{BASE}/tenants('{TENANT_ID}')/agentRoleAssignments"

    listing = next(r for r in requests if r.method == "GET" and r.url.path.endswith("agentRoleAssignments"))
    assert str(listing.url).startswith(collection)
    assert listing.url.params["$filter"] == (
        "targetPlanId eq 'plan1' and roleId eq 'WorkdayAdmin' and status eq 'Active'"
    )

    getting = next(r for r in requests if r.method == "GET" and "('assign1')" in str(r.url))
    assert str(getting.url) == f"{collection}('assign1')"

    attesting = next(r for r in requests if r.method == "POST")
    assert str(attesting.url) == f"{collection}/attest"
    assert json.loads(attesting.content) == {
        "subjectId": "subject-oid",
        # Caller passes the compact id "WorkdayAdmin"; the client maps it to the
        # provider display name the backend validates the attest role against.
        "role": "Workday administrator",
        "target": {"type": "Plan", "id": "plan1"},
        "provider": "External",
    }

    revoking = next(r for r in requests if r.method == "DELETE")
    assert str(revoking.url) == f"{collection}('assign1')"
    assert revoking.headers["If-Match"] == "etag-a"


def test_list_role_assignments_requires_target_plan_equality(monkeypatch) -> None:
    requests, handler = _recorder()
    client = _make_client(monkeypatch, handler)

    _run(client, lambda: client.list_plan_role_assignments("plan1"))

    # Even with no optional filters, the plan-scoping equality is always present.
    assert requests[0].url.params["$filter"] == "targetPlanId eq 'plan1'"


@pytest.mark.parametrize(
    ("args", "kwargs", "match"),
    [
        (("plan1", "subj", "NotARole"), {}, "role must be one of"),
        (("plan1", "subj", "WorkdayAdmin"), {"provider": "Internal"}, "External"),
    ],
)
def test_attest_validation(monkeypatch, args, kwargs, match) -> None:
    _, handler = _recorder()
    client = _make_client(monkeypatch, handler)
    with pytest.raises(ValueError, match=match):
        _run(client, lambda: client.attest_plan_role(*args, **kwargs))


def test_attest_accepts_role_display_name_and_sends_it_verbatim(monkeypatch) -> None:
    # Callers may pass either the compact id or the backend display name; a
    # display name is already wire-shaped and must pass through unchanged.
    requests, handler = _recorder()
    client = _make_client(monkeypatch, handler)

    _run(
        client,
        lambda: client.attest_plan_role(
            "plan1", "subject-oid", "ServiceNow Administrator"
        ),
    )

    attesting = next(r for r in requests if r.method == "POST")
    assert json.loads(attesting.content)["role"] == "ServiceNow Administrator"


def test_planner_api_error_surfaces_target_and_details(monkeypatch) -> None:
    # The generic top-level Message is opaque ("...sent a bad request..."); the
    # planner overrides the error formatter to surface Target + Details[] so the
    # agent reads the real reason (e.g. the exact allowed attest role values)
    # and self-corrects. This is the planner counterpart to the landing page's
    # test_api_error_uses_top_level_code_message_and_http_status (which pins the
    # neutral core still dropping Details).
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "Code": "BadRequest",
                "Message": "The calling client sent a bad request to the service.",
                "Target": "agentRoleAssignments.role",
                "Details": [
                    {
                        "Code": "ValidationError",
                        "Message": (
                            "role must be one of Workday administrator, "
                            "ServiceNow Administrator, ServiceNow Knowledge Manager."
                        ),
                    }
                ],
            },
        )

    client = _make_client(monkeypatch, handler)

    with pytest.raises(base_client_module.AgentConfigApiError) as excinfo:
        _run(client, lambda: client.list_project_plan_tasks("proj1", "plan1"))

    message = str(excinfo.value)
    assert excinfo.value.http_status == 400
    assert message.startswith("BadRequest:")
    assert "agentRoleAssignments.role" in message  # Target surfaced
    assert "ValidationError" in message
    assert "ServiceNow Administrator" in message  # Details surfaced


def test_list_role_assignments_validates_status_and_orderby(monkeypatch) -> None:
    _, handler = _recorder()
    client = _make_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="Active or Revoked"):
        _run(client, lambda: client.list_plan_role_assignments("p", status="Nope"))
    with pytest.raises(ValueError, match="createdAt"):
        _run(client, lambda: client.list_plan_role_assignments("p", orderby="name asc"))


# ---------------------------------------------------------------------------
# Response passthrough
# ---------------------------------------------------------------------------
def test_planner_responses_are_returned_without_key_transformation(
    monkeypatch,
) -> None:
    # Planner/role payloads carry user-authored camelCase keys (e.g. assignedToId)
    # that must be returned verbatim, unlike the landing-page PascalCase surface.
    _, handler = _recorder(
        response_json={"value": [{"assignedToId": "user-1", "someKey": "keepMe"}]}
    )
    client = _make_client(monkeypatch, handler)

    result = _run(client, lambda: client.list_project_plan_tasks("p", "pl"))

    assert result == {"value": [{"assignedToId": "user-1", "someKey": "keepMe"}]}


def test_attestable_roles_constant_is_the_provider_owned_set() -> None:
    assert roles_module.ATTESTABLE_ROLES == (
        "WorkdayAdmin",
        "ServiceNowAdmin",
        "ServiceNowKnowledgeManager",
    )


# ---------------------------------------------------------------------------
# ETag / plan-state conflict recovery
#
# AgentConfiguration returns 412 PreconditionFailed for a stale/mismatched If-Match and
# 409 Conflict when a task mutation targets a non-Active plan. On the former the
# client re-reads only to raise an actionable "the ETag advanced, re-read and
# reapply" error -- it never replays the mutation, since replaying would defeat
# the If-Match lost-update guard. On the latter it turns the generic conflict
# into an actionable message. These tests pin both paths through MockTransport.
# ---------------------------------------------------------------------------
def _stale_then_ok_handler(requests, mutate_method, retry_response, refetch_json):
    """Handler: first mutation -> 412, re-GET -> refetch_json, retry -> ok."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == mutate_method:
            attempts = [r for r in requests if r.method == mutate_method]
            if len(attempts) == 1:
                return httpx.Response(
                    412, json={"Code": "PreconditionFailed", "Message": "stale"}
                )
            return retry_response
        if request.method == "GET":
            return httpx.Response(200, json=refetch_json)
        return httpx.Response(200, json={})

    return handler


def test_task_update_preserves_stale_etag_412_without_replaying(monkeypatch) -> None:
    # A moved ETag is indistinguishable from a concurrent edit to the same
    # fields, so the client must NOT auto-replay the PATCH; it re-reads only to
    # raise an actionable 412 telling the caller to re-read and reapply.
    requests: list[httpx.Request] = []
    client = _make_client(
        monkeypatch,
        _stale_then_ok_handler(
            requests, "PATCH", httpx.Response(200, json={"ok": True}), {"ETag": 'W/"2"'}
        ),
    )

    with pytest.raises(base_client_module.AgentConfigApiError) as excinfo:
        _run(
            client,
            lambda: client.update_project_plan_task(
                "proj1", "plan1", "task1", {"title": "New"}, 'W/"1"'
            ),
        )

    assert excinfo.value.http_status == 412
    message = str(excinfo.value)
    assert "re-read" in message.lower()
    assert 'W/"2"' in message  # surfaces the advanced ETag so the caller can act
    # Exactly one PATCH (no blind replay) and a single re-read GET.
    patches = [r for r in requests if r.method == "PATCH"]
    assert [p.headers["If-Match"] for p in patches] == ['W/"1"']
    gets = [r for r in requests if r.method == "GET"]
    assert len(gets) == 1
    assert str(gets[0].url).endswith("agentPlanTasks('task1')")


def test_task_delete_preserves_stale_etag_412_without_replaying(monkeypatch) -> None:
    # A moved ETag on DELETE is just as ambiguous as on PATCH: the entity may
    # have been edited after the caller read it, so replaying the DELETE could
    # destroy work done in between. The client re-reads only to raise.
    requests: list[httpx.Request] = []
    client = _make_client(
        monkeypatch,
        _stale_then_ok_handler(
            requests, "DELETE", httpx.Response(204), {"ETag": 'W/"5"'}
        ),
    )

    with pytest.raises(base_client_module.AgentConfigApiError) as excinfo:
        _run(
            client,
            lambda: client.delete_project_plan_task("proj1", "plan1", "task2", 'W/"4"'),
        )

    assert excinfo.value.http_status == 412
    assert 'W/"5"' in str(excinfo.value)  # advanced ETag surfaced to the caller
    # Exactly one DELETE (no blind replay) and a single re-read GET.
    deletes = [r for r in requests if r.method == "DELETE"]
    assert [d.headers["If-Match"] for d in deletes] == ['W/"4"']
    assert len([r for r in requests if r.method == "GET"]) == 1


def test_plan_update_preserves_stale_etag_412_without_replaying(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    client = _make_client(
        monkeypatch,
        _stale_then_ok_handler(
            requests,
            "PATCH",
            httpx.Response(200, json={"Status": "Active"}),
            {"ETag": 'W/"7"', "Status": "Draft"},
        ),
    )

    with pytest.raises(base_client_module.AgentConfigApiError) as excinfo:
        _run(
            client,
            lambda: client.update_project_plan(
                "proj1", "plan1", {"status": "Active"}, 'W/"6"'
            ),
        )

    assert excinfo.value.http_status == 412
    assert 'W/"7"' in str(excinfo.value)
    patches = [r for r in requests if r.method == "PATCH"]
    assert [p.headers["If-Match"] for p in patches] == ['W/"6"']  # no replay


def test_stale_etag_retry_gives_up_when_version_did_not_move(monkeypatch) -> None:
    # A 412 whose re-read ETag is unchanged is a genuine precondition failure,
    # not reconciliation drift: re-raise it rather than loop or clobber.
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PATCH":
            return httpx.Response(
                412, json={"Code": "PreconditionFailed", "Message": "stale"}
            )
        if request.method == "GET":
            return httpx.Response(200, json={"ETag": 'W/"1"'})
        return httpx.Response(200, json={})

    client = _make_client(monkeypatch, handler)

    with pytest.raises(base_client_module.AgentConfigApiError) as excinfo:
        _run(
            client,
            lambda: client.update_project_plan_task(
                "proj1", "plan1", "task1", {"title": "X"}, 'W/"1"'
            ),
        )

    assert excinfo.value.http_status == 412
    assert len([r for r in requests if r.method == "PATCH"]) == 1


def test_task_mutation_on_non_active_plan_gets_actionable_409(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    generic = (
        "The request could not be completed due to a conflict with the "
        "current state of the resource."
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PATCH":
            return httpx.Response(409, json={"Code": "Conflict", "Message": generic})
        if request.method == "GET":
            return httpx.Response(200, json={"Status": "Draft", "ETag": 'W/"1"'})
        return httpx.Response(200, json={})

    client = _make_client(monkeypatch, handler)

    with pytest.raises(base_client_module.AgentConfigApiError) as excinfo:
        _run(
            client,
            lambda: client.set_project_plan_task_state(
                "proj1", "plan1", "task1", "InProgress", 'W/"1"'
            ),
        )

    assert excinfo.value.http_status == 409
    message = str(excinfo.value)
    assert "not Active" in message
    assert "update_project_plan" in message and '"status": "Active"' in message
    # The clarifier re-reads the plan (not the task) to learn the status.
    gets = [r for r in requests if r.method == "GET"]
    assert len(gets) == 1
    assert str(gets[0].url).endswith("agentPlans('plan1')")


def test_task_mutation_409_with_active_plan_is_reraised_unchanged(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    generic = (
        "The request could not be completed due to a conflict with the "
        "current state of the resource."
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PATCH":
            return httpx.Response(409, json={"Code": "Conflict", "Message": generic})
        if request.method == "GET":
            return httpx.Response(200, json={"Status": "Active", "ETag": 'W/"9"'})
        return httpx.Response(200, json={})

    client = _make_client(monkeypatch, handler)

    with pytest.raises(base_client_module.AgentConfigApiError) as excinfo:
        _run(
            client,
            lambda: client.set_project_plan_task_state(
                "proj1", "plan1", "task1", "InProgress", 'W/"9"'
            ),
        )

    assert excinfo.value.http_status == 409
    # An Active plan means the 409 is some other invariant: keep it verbatim.
    assert "not Active" not in str(excinfo.value)
    assert generic in str(excinfo.value)


# ---------------------------------------------------------------------------
# Archive routing (PR #251 review): update_project_plan must never perform the
# destructive archive that also cancels tasks -- that belongs to the separately
# annotated archive_project_plan tool. The guard is case/whitespace-insensitive.
# ---------------------------------------------------------------------------
def test_update_project_plan_refuses_archived_status(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("archive must be rejected before any HTTP request")

    client = _make_client(monkeypatch, handler)
    for patch in (
        {"status": "Archived"},
        {"Status": "archived"},
        {"status": " ARCHIVED "},
    ):
        with pytest.raises(ValueError, match="archive_project_plan"):
            _run(
                client,
                lambda p=patch: client.update_project_plan("proj1", "plan1", p, 'W/"1"'),
            )


# ---------------------------------------------------------------------------
# Task-patch key casing (PR #251 review): the live surface is case-insensitive,
# but the client emits a deterministic camelCase body and rejects a field named
# twice under different casing.
# ---------------------------------------------------------------------------
def test_task_update_normalizes_key_casing_to_camelcase(monkeypatch) -> None:
    requests, handler = _recorder(response_json={"ok": True})
    client = _make_client(monkeypatch, handler)

    _run(
        client,
        lambda: client.update_project_plan_task(
            "proj1",
            "plan1",
            "task1",
            {"Title": "New", "ASSIGNEDTOID": "u1", "produces": ["a"]},
            'W/"1"',
        ),
    )

    body = json.loads(requests[-1].content)
    assert body == {"title": "New", "assignedToId": "u1", "produces": ["a"]}


def test_task_update_rejects_keys_differing_only_by_casing(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("ambiguous duplicate key must be rejected pre-flight")

    client = _make_client(monkeypatch, handler)
    with pytest.raises(ValueError, match="duplicates field title"):
        _run(
            client,
            lambda: client.update_project_plan_task(
                "proj1", "plan1", "task1", {"title": "a", "Title": "b"}, 'W/"1"'
            ),
        )


# ---------------------------------------------------------------------------
# Retry safety (PR #251 review): an ambiguous gateway failure (502/503/504) on
# an unkeyed create must NOT be replayed -- it may already have committed and a
# retry would duplicate it. An Idempotency-Key makes the create retry-safe.
# ---------------------------------------------------------------------------
def test_unkeyed_create_is_not_retried_on_ambiguous_5xx(monkeypatch) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            503, json={"Code": "ServiceUnavailable", "Message": "down"}
        )

    client = _make_client(monkeypatch, handler)
    with pytest.raises(base_client_module.AgentConfigApiError) as excinfo:
        _run(
            client,
            lambda: client.create_project_plan(
                "proj1", {"configuringAgentName": "EmployeeSelfServiceHRCEA"}
            ),
        )

    assert excinfo.value.http_status == 503
    assert len([r for r in calls if r.method == "POST"]) == 1  # surfaced, not replayed


def test_keyed_create_is_retried_on_ambiguous_5xx(monkeypatch) -> None:
    monkeypatch.setattr(base_client_module.asyncio, "sleep", _no_sleep)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len([r for r in calls if r.method == "POST"]) == 1:
            return httpx.Response(
                503, json={"Code": "ServiceUnavailable", "Message": "down"}
            )
        return httpx.Response(200, json={"PlanId": "p1"})

    client = _make_client(monkeypatch, handler)
    result = _run(
        client,
        lambda: client.create_project_plan(
            "proj1", {"configuringAgentName": "EmployeeSelfServiceHRCEA"}, "idem-1"
        ),
    )

    assert result == {"PlanId": "p1"}
    posts = [r for r in calls if r.method == "POST"]
    assert len(posts) == 2  # an Idempotency-Key makes the create retry-safe
    assert all("Idempotency-Key" in p.headers for p in posts)
