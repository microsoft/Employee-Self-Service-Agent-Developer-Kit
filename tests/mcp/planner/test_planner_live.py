# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Opt-in, two-identity ER checks against the real Planner MCP and service.

See scripts/planner/README.md for consent, isolation, and sign-in requirements.
This tests shared-service behavior, not a VS Code conversation or provisioning.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

import msal
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from planner import capture, sync
from planner.plan_model import Plan, new_task, principal_person, principal_pool


MCP_ROOT = Path(__file__).parents[3] / "solutions" / "ess-maker-skills" / "src" / "mcp"
ADMIN_ROLE = "EntraPowerPlatformAdministrator"


@dataclass(frozen=True)
class _Actor:
    oid: str
    token: str = field(repr=False)


def _checked_actor(result: dict[str, Any], tenant: str, username: str) -> _Actor:
    from base_client import _decode_jwt_payload

    token = result.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"Live sign-in failed ({result.get('error', 'no_access_token')}).")
    claims = _decode_jwt_payload(token)
    identity = result.get("id_token_claims", {})
    signed_in = identity.get("preferred_username") or claims.get("upn") or claims.get("unique_name")
    token_tenant = claims.get("tid")
    if not isinstance(token_tenant, str) or token_tenant.casefold() != tenant.casefold():
        raise RuntimeError("Signed-in tenant differs from the authorized test tenant.")
    if not isinstance(signed_in, str) or signed_in.casefold() != username.casefold():
        raise RuntimeError(
            f"Signed in as {signed_in!r}, not {username!r}. "
            "Select 'Use another account' and the requested test identity."
        )
    oid = claims.get("oid")
    if not isinstance(oid, str) or not oid:
        raise RuntimeError("The test actor's token has no object ID.")
    return _Actor(oid=oid, token=token)


def _sign_in(tenant: str, username: str) -> _Actor:
    from base_client import _CLIENT_ID, _acquire_token_interactive_form_post

    print(f"\nPlanner sign-in: select {username}", flush=True)
    app = msal.PublicClientApplication(
        _CLIENT_ID, authority=f"https://login.microsoftonline.com/{tenant}",
        token_cache=msal.SerializableTokenCache(),
    )
    app.initiate_auth_code_flow = partial(app.initiate_auth_code_flow, login_hint=username)
    return _checked_actor(_acquire_token_interactive_form_post(app), tenant, username)


def _resolve_environment(tenant: str, username: str, admin: _Actor, url: str) -> str:
    from flightcheck.pp_admin_client import CLIENT_ID, PP_SCOPE, PPAdminClient

    print(f"\nRead-only environment lookup: select {username}", flush=True)
    app = msal.PublicClientApplication(
        CLIENT_ID, authority=f"https://login.microsoftonline.com/{tenant}",
        token_cache=msal.SerializableTokenCache(),
    )
    result = app.acquire_token_interactive(
        [PP_SCOPE], login_hint=username, prompt="select_account", timeout=300,
    )
    actor = _checked_actor(result, tenant, username)
    if actor.oid != admin.oid:
        raise RuntimeError("Power Platform sign-in differs from the Planner administrator.")
    client = PPAdminClient(tenant)
    client._token = actor.token
    environment_id = client.find_environment_id_by_dataverse_url(url)
    if not environment_id:
        raise RuntimeError("The administrator could not verify the selected environment's ID.")
    return environment_id


@asynccontextmanager
async def _session(actor: _Actor):
    env = {
        key: value for key, value in os.environ.items()
        if key not in {"AGENTCONFIG_ACCESS_TOKEN_FILE", "AGENTCONFIG_ACCESS_TOKEN"}
    }
    env["AGENTCONFIG_ACCESS_TOKEN"] = actor.token
    env["ESS_ADK_TELEMETRY"] = "off"
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_ROOT / "agentconfig_planner" / "server.py")],
        cwd=str(MCP_ROOT / "agentconfig_planner"),
        env=env,
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def _call(session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
    result = await session.call_tool(name, arguments)
    text = "\n".join(item.text for item in result.content if isinstance(item, TextContent))
    if result.isError:
        raise RuntimeError(f"{name}: {text}")
    return sync.extract_json_payload(text)


def _required(entity: dict[str, Any], *names: str) -> str:
    value = sync._scalar(entity, *names)
    if not isinstance(value, str) or not value:
        raise AssertionError(f"Live response is missing {names[0]}.")
    return value


async def _pull(session: ClientSession, ids: dict[str, str]) -> Plan:
    entity, tasks = await asyncio.gather(
        _call(session, "get_project_plan", ids),
        _call(session, "list_project_plan_tasks", ids),
    )
    return Plan(sync.hydrate_from_remote(entity, tasks))


async def _caller_ids(session: ClientSession, ids: dict[str, str]) -> set[str]:
    result = await _call(session, "list_project_plan_tasks_for_caller", ids)
    return {_required(task, "taskId", "id") for task in sync._as_entities(result)}


async def _assert_isolated(session: ClientSession, project_id: str, own_plan: str = "") -> None:
    project = await _call(session, "get_agent_configuration_project", {"projectId": project_id})
    if sync._scalar(project, "activePlanId"):
        raise RuntimeError("Existing active plan: refusing to replace or archive someone else's work.")
    plans = await _call(session, "list_project_plans", {"projectId": project_id})
    if any(_required(plan, "planId", "id") != own_plan for plan in sync._as_entities(plans)):
        raise RuntimeError("Existing plan: use a dedicated test project with no current plans.")


def _draft(maker: _Actor, admin: _Actor, run_id: str) -> Plan:
    plan = Plan.new(objective="Disposable Planner ER service validation; no deployment.")
    plan.set_configuring_agent_name("EmployeeSelfServiceHRDA")
    plan.set_context("validationRun", run_id, group="validation")
    plan.set_context("hr-profile-read", "Employee profile viewing", group="scenario")
    plan.set_system("hr-profile-read", "Not sure yet")
    plan.set_context(f"owner.{ADMIN_ROLE}", "Not known yet", group="pendingDecision")
    plan.add_task(new_task(
        "environment", "ER: record verified environment metadata",
        assigned_to=principal_pool(ADMIN_ROLE), produces=["primaryEnvironment"],
    ))
    plan.add_task(new_task(
        "followup", "ER: review shared environment metadata",
        assigned_to=principal_person(admin.oid, ADMIN_ROLE), consumes=["primaryEnvironment"],
    ))
    plan.add_task(new_task(
        "independent", "ER: review scenario scope",
        assigned_to=principal_person(maker.oid, "PowerPlatformEnvironmentMaker"),
    ))
    plan.add_task(new_task(
        "system", "ER: confirm profile system choice",
        assigned_to=principal_person(maker.oid, "PowerPlatformEnvironmentMaker"),
        consumes=["system.hr-profile-read"],
    ))
    return plan


async def _exercise(
    maker_session: ClientSession, admin_session: ClientSession,
    maker: _Actor, admin: _Actor, ids: dict[str, str], path: Path,
    environment_id: str, environment_url: str,
) -> None:
    shared = await _pull(maker_session, ids)
    assert shared.data["status"] == "Draft"
    assert len(shared.pending_decisions()) == 2
    tasks = {task["title"]: task["id"] for task in shared.tasks}
    environment = tasks["ER: record verified environment metadata"]
    followup = tasks["ER: review shared environment metadata"]
    independent = tasks["ER: review scenario scope"]
    system = tasks["ER: confirm profile system choice"]
    shared.save(path)
    assert len(Plan.load(path).pending_decisions()) == 2

    refused = await maker_session.call_tool("set_project_plan_task_state", {
        **ids, "taskId": independent, "state": "InProgress",
        "etag": shared.task(independent)["etag"],
    })
    error_text = " ".join(item.text for item in refused.content if isinstance(item, TextContent))
    assert refused.isError and "active" in error_text.casefold(), "Shared draft must be read-only."

    await _assert_isolated(maker_session, ids["projectId"], ids["planId"])
    shared = await _pull(maker_session, ids)
    await _call(maker_session, "update_project_plan", {
        **ids, "patch": {"status": "Active"}, "etag": shared.data["etag"],
    })
    shared = await _pull(maker_session, ids)
    assert shared.data["status"] == "Active"
    assert len(shared.pending_decisions()) == 2
    assert independent in await _caller_ids(maker_session, ids)
    assert followup in await _caller_ids(admin_session, ids)
    with pytest.raises(ValueError, match="Confirm the system"):
        shared.set_task_state(system, "InProgress")
    with pytest.raises(ValueError, match="ER: record verified environment metadata"):
        shared.set_task_state(followup, "InProgress")

    await _call(maker_session, "set_project_plan_task_state", {
        **ids, "taskId": independent, "state": "Completed",
        "etag": shared.task(independent)["etag"],
    })
    assert independent not in await _caller_ids(maker_session, ids)
    print("PASS: unknown owner/system survive sharing and activation; unrelated work continues.", flush=True)

    shared = await _pull(maker_session, ids)
    await _call(maker_session, "update_project_plan_task", {
        **ids, "taskId": environment, "etag": shared.task(environment)["etag"],
        "patch": {
            "assignedToId": admin.oid, "assignedToType": "User",
            "assignedToRoleId": "Power Platform Administrator",
        },
    })
    shared = await _pull(maker_session, ids)
    shared.remove_context(f"owner.{ADMIN_ROLE}")
    await _call(maker_session, "update_project_plan", {
        **ids, "patch": {"context": sync.to_remote_plan_body(shared)["context"]},
        "etag": shared.data["etag"],
    })
    assert environment in await _caller_ids(admin_session, ids)
    assert environment not in await _caller_ids(maker_session, ids)
    local = await _pull(admin_session, ids)
    await _call(admin_session, "set_project_plan_task_state", {
        **ids, "taskId": environment, "state": "InProgress",
        "etag": local.task(environment)["etag"],
    })
    local = await _pull(admin_session, ids)
    artifact = capture.detect_environment({}, {
        "environmentId": environment_id, "dataverseEndpoint": environment_url,
    }, task_id=environment)
    assert artifact is not None
    local.add_output(artifact)
    local.set_task_state(environment, "Completed")
    local.save(path)
    local = Plan.load(path)
    stale = await _pull(admin_session, ids)
    local = Plan(sync.preserve_local_pending(stale.data, local.data))
    assert local.task(environment)["pendingSync"]
    with pytest.raises(ValueError, match="shared confirmation"):
        local.set_task_state(followup, "InProgress")

    operation = next(
        task for task in sync.pending_sync_payload(local)["tasks"] if task["taskId"] == environment
    )
    await _call(admin_session, "complete_project_plan_task", {
        **ids, "taskId": environment, "outputs": operation["outputs"], "etag": operation["etag"],
    })
    readback = await _pull(maker_session, ids)
    confirmed = Plan(sync.preserve_local_pending(readback.data, local.data))
    assert not confirmed.task(environment).get("pendingSync")
    metadata = confirmed.output("primaryEnvironment")["attributes"]
    assert metadata["environmentId"] == environment_id
    assert metadata["environmentUrl"] == environment_url
    assert confirmed.blocking_inputs(followup) == {}
    next_tasks = await _caller_ids(admin_session, ids)
    assert environment not in next_tasks and followup in next_tasks
    assert confirmed.task_brief(followup)["consumes"]["primaryEnvironment"] == metadata
    print("PASS: two-identity assignment, pending sync, metadata readback, and dependency release.", flush=True)

    readback.set_system("hr-profile-read", "Workday")
    await _call(maker_session, "update_project_plan", {
        **ids, "patch": {"context": sync.to_remote_plan_body(readback)["context"]},
        "etag": readback.data["etag"],
    })
    resolved = await _pull(maker_session, ids)
    assert resolved.pending_decisions() == []
    assert resolved.blocking_inputs(system) == {}
    resolved.set_task_state(system, "InProgress")
    await _call(maker_session, "set_project_plan_task_state", {
        **ids, "taskId": system, "state": "InProgress", "etag": resolved.task(system)["etag"],
    })
    assert (await _pull(maker_session, ids)).task(system)["state"] == "InProgress"
    print("PASS: resolving the deferred system releases only its dependent task.", flush=True)


async def _run_live(settings: dict[str, str], path: Path, maker: _Actor) -> None:
    tenant = settings["TENANT_ID"]
    async with _session(maker) as maker_session:
        projects = sync._as_entities(await _call(maker_session, "list_agent_configuration_projects", {}))
        existing = [
            project for project in projects
            if sync._scalar(project, "name").strip().casefold() == "employee self-service"
        ]
        assert len(existing) <= 1, "Multiple ESS projects need manual review before live validation."
        project_id = _required(existing[0], "projectId", "id") if existing else ""
        if project_id:
            await _assert_isolated(maker_session, project_id)

        admin = await asyncio.to_thread(_sign_in, tenant, settings["ADMIN_UPN"])
        assert maker.oid != admin.oid, "Live validation requires two different identities."
        environment_id = await asyncio.to_thread(
            _resolve_environment, tenant, settings["ADMIN_UPN"], admin, settings["ENVIRONMENT_URL"],
        )
        async with _session(admin) as admin_session:
            if not project_id:
                project = await _call(maker_session, "create_agent_configuration_project", {
                    "project": {"name": "Employee Self-Service"},
                })
                project_id = _required(project, "projectId", "id")
            await _assert_isolated(maker_session, project_id)
            run_id = str(uuid4())
            created = await _call(maker_session, "create_project_plan", {
                "projectId": project_id, "idempotencyKey": run_id,
                "plan": sync.to_remote_plan_body(_draft(maker, admin, run_id)),
            })
            ids = {"projectId": project_id, "planId": _required(created, "planId", "id")}
            print(f"Disposable ER plan created: {ids['planId']}", flush=True)
            try:
                await _exercise(
                    maker_session, admin_session, maker, admin, ids, path,
                    environment_id, settings["ENVIRONMENT_URL"],
                )
            finally:
                own = await _pull(maker_session, ids)
                assert any(
                    item["key"] == "validationRun" and item["value"] == run_id for item in own.context
                ), "Cleanup refused: test-plan provenance does not match."
                await _call(maker_session, "archive_project_plan", {**ids, "etag": own.data["etag"]})
                archived = await _call(maker_session, "get_project_plan", ids)
                assert sync.remote_plan_status(sync._scalar(archived, "status")) == "Archived"
                print("Disposable ER plan archived; unrelated plans were not changed.", flush=True)


@pytest.mark.live
def test_two_account_planner_service_flow(tmp_path, monkeypatch, request):
    if request.config.option.showlocals:
        pytest.fail("Live authentication requires --no-showlocals to protect credentials.")
    names = ("TENANT_ID", "MAKER_UPN", "ADMIN_UPN", "ENVIRONMENT_URL", "ALLOW_WRITES")
    settings = {name: os.environ.get(f"ESS_PLANNER_LIVE_{name}", "").strip() for name in names}
    if not all(settings.values()):
        pytest.skip("Set all ESS_PLANNER_LIVE_* test settings and explicit tenant-scoped write consent.")
    tenant = str(UUID(settings["TENANT_ID"]))
    assert settings["ALLOW_WRITES"].casefold() == tenant, "Write consent must name this exact test tenant."
    settings["TENANT_ID"] = tenant
    url = urlparse(settings["ENVIRONMENT_URL"])
    assert url.scheme == "https" and url.hostname and url.hostname.endswith(".dynamics.com")
    assert not (url.username or url.password or url.query or url.fragment) and url.path in ("", "/")
    settings["ENVIRONMENT_URL"] = settings["ENVIRONMENT_URL"].rstrip("/")
    monkeypatch.syspath_prepend(str(MCP_ROOT / "agentconfig_core"))
    maker = _sign_in(tenant, settings["MAKER_UPN"])
    asyncio.run(_run_live(settings, tmp_path / "plan.json", maker))


@pytest.mark.parametrize(("changed", "error"), [
    ({}, None),
    ({"tid": "another-tenant"}, "tenant differs"),
    ({"tid": None}, "tenant differs"),
    ({"oid": None}, "no object ID"),
    ({"upn": "other@example.test"}, "Use another account"),
])
def test_live_actor_guard_rejects_wrong_identity(monkeypatch, changed, error):
    """Pure guard test; synthetic claims never authorize a service request."""
    monkeypatch.syspath_prepend(str(MCP_ROOT / "agentconfig_core"))
    claims = {"tid": "test-tenant", "oid": "test-maker", "upn": "maker@example.test", **changed}
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    result = {"access_token": f"header.{encoded}.signature"}
    if error:
        with pytest.raises(RuntimeError, match=error):
            _checked_actor(result, "test-tenant", "maker@example.test")
    else:
        assert _checked_actor(result, "test-tenant", "MAKER@example.test").oid == "test-maker"
