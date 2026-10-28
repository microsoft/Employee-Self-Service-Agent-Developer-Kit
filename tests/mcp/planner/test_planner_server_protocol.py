# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Protocol-level tests for the AgentConfiguration planner MCP server.

Imports the FastMCP server and inspects the *resolved* tool surface exactly as
a client would see it over MCP: the tool list, each tool's description, its
input schema (what to pass and what is required), and its read/mutate/delete
annotations. It then invokes a representative tool from each category through
``call_tool`` against a recording fake client to prove the server wires each
call - and only token-derived identity - through to the client layer.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import warnings
from pathlib import Path
from typing import Any

import pytest
from pydantic_settings.exceptions import IncompleteFieldDefinitionWarning


REPO_ROOT = Path(__file__).parents[3]
PLANNER_DIR = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_planner"
)
sys.path.insert(0, str(PLANNER_DIR))

# Both this server and the landing-page server are the file ``server.py`` in
# their own folder; each runs as its own process in production, but under
# pytest they share one interpreter, so a plain ``import server`` would collide
# in ``sys.modules`` with whichever server.py was imported first. Load this one
# from its path under a unique module name to keep the two servers isolated.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", IncompleteFieldDefinitionWarning)
    _spec = importlib.util.spec_from_file_location(
        "planner_server", str(PLANNER_DIR / "server.py")
    )
    planner_server = importlib.util.module_from_spec(_spec)
    sys.modules["planner_server"] = planner_server
    _spec.loader.exec_module(planner_server)  # noqa: E402


# tool -> (all properties, required subset). Identity/tenant are never present.
_TOOLS: dict[str, tuple[list[str], list[str]]] = {
    "list_agent_configuration_projects": (["query"], []),
    "get_agent_configuration_project": (["projectId", "query"], ["projectId"]),
    "create_agent_configuration_project": (
        ["project", "idempotencyKey"],
        ["project"],
    ),
    "archive_agent_configuration_project": (
        ["projectId", "etag"],
        ["projectId", "etag"],
    ),
    "list_project_plans": (["projectId", "query"], ["projectId"]),
    "get_project_plan": (["projectId", "planId", "query"], ["projectId", "planId"]),
    "create_project_plan": (
        ["projectId", "plan", "idempotencyKey"],
        ["projectId", "plan"],
    ),
    "update_project_plan": (
        ["projectId", "planId", "patch", "etag"],
        ["projectId", "planId", "patch", "etag"],
    ),
    "archive_project_plan": (
        ["projectId", "planId", "etag"],
        ["projectId", "planId", "etag"],
    ),
    "list_project_plan_tasks": (
        ["projectId", "planId", "query"],
        ["projectId", "planId"],
    ),
    "list_project_plan_tasks_for_caller": (
        ["projectId", "planId", "query"],
        ["projectId", "planId"],
    ),
    "get_project_plan_task": (
        ["projectId", "planId", "taskId", "query"],
        ["projectId", "planId", "taskId"],
    ),
    "create_project_plan_task": (
        ["projectId", "planId", "task", "idempotencyKey"],
        ["projectId", "planId", "task"],
    ),
    "create_role_assigned_project_plan_task": (
        [
            "projectId",
            "planId",
            "role",
            "title",
            "description",
            "produces",
            "consumes",
            "idempotencyKey",
        ],
        ["projectId", "planId", "role", "title"],
    ),
    "update_project_plan_task": (
        ["projectId", "planId", "taskId", "patch", "etag"],
        ["projectId", "planId", "taskId", "patch", "etag"],
    ),
    "set_project_plan_task_state": (
        ["projectId", "planId", "taskId", "state", "etag"],
        ["projectId", "planId", "taskId", "state", "etag"],
    ),
    "complete_project_plan_task": (
        ["projectId", "planId", "taskId", "outputs", "etag"],
        ["projectId", "planId", "taskId", "outputs", "etag"],
    ),
    "delete_project_plan_task": (
        ["projectId", "planId", "taskId", "etag"],
        ["projectId", "planId", "taskId", "etag"],
    ),
    "list_attestable_roles": ([], []),
    "list_plan_role_assignments": (
        ["planId", "subjectId", "role", "status", "top", "orderby", "skiptoken"],
        ["planId"],
    ),
    "get_role_assignment": (["assignmentId"], ["assignmentId"]),
    "attest_plan_role": (
        ["planId", "subjectId", "role", "etag", "idempotencyKey"],
        ["planId", "subjectId", "role"],
    ),
    "revoke_role_assignment": (["assignmentId", "etag"], ["assignmentId"]),
    # WeveNova tenant-inventory write path, folded into this same server (one MCP, one
    # identity) so a discovery crawl persists through it. Crawler-driven, so these
    # follow the crawler's snake_case wire contract; the ``tenant_id`` argument is
    # accepted but ignored in favour of the token's ``tid`` (see server.py), which is
    # why it is not among _FORBIDDEN_IDENTITY_ARGS.
    "server_info": ([], []),
    "probe": (["tenant_id"], ["tenant_id"]),
    "list_items": (["tenant_id", "kind", "environment_id"], ["tenant_id"]),
    "sync_inventory": (["tenant_id", "items", "run_id"], ["tenant_id", "items"]),
}

# Category -> (readOnlyHint, destructiveHint, idempotentHint).
_HINTS = {
    "read": (True, False, True),
    "create": (False, False, False),
    "create_idempotent": (False, False, True),
    "update": (False, False, True),
    "delete": (False, True, True),
    # syncInventory is a whole-inventory replace: destructive (omission retires) but
    # safe to replay under its idempotency key.
    "sync": (False, True, True),
}
_TOOL_CATEGORY = {
    "list_agent_configuration_projects": "read",
    "get_agent_configuration_project": "read",
    "create_agent_configuration_project": "create_idempotent",
    "archive_agent_configuration_project": "delete",
    "list_project_plans": "read",
    "get_project_plan": "read",
    "create_project_plan": "create",
    "update_project_plan": "update",
    "archive_project_plan": "delete",
    "list_project_plan_tasks": "read",
    "list_project_plan_tasks_for_caller": "read",
    "get_project_plan_task": "read",
    "create_project_plan_task": "create",
    "create_role_assigned_project_plan_task": "create",
    "update_project_plan_task": "update",
    "set_project_plan_task_state": "update",
    "complete_project_plan_task": "update",
    "delete_project_plan_task": "delete",
    "list_attestable_roles": "read",
    "list_plan_role_assignments": "read",
    "get_role_assignment": "read",
    "attest_plan_role": "create_idempotent",
    "revoke_role_assignment": "delete",
    "server_info": "read",
    "probe": "read",
    "list_items": "read",
    "sync_inventory": "sync",
}

_FORBIDDEN_IDENTITY_ARGS = {
    "userName",
    "username",
    "aadId",
    "tenantId",
    "callerId",
    "objectId",
    "oid",
    "tid",
}


def _tools() -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(planner_server.mcp.list_tools())}


class _RecordingClient:
    """Async client stand-in that records calls and echoes a marker payload."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        async def _method(*args: Any, **kwargs: Any) -> dict[str, Any]:
            self.calls.append((name, args, kwargs))
            return {"called": name, "args": list(args), "kwargs": kwargs}

        return _method


def _call(tool_name: str, arguments: dict[str, Any]):
    return asyncio.run(planner_server.mcp.call_tool(tool_name, arguments))


def _result_text(result: Any) -> str:
    # call_tool returns (content, structured) in this mcp version, or a
    # CallToolResult; support both by locating the first text content item.
    content = result[0] if isinstance(result, tuple) else result.content
    return content[0].text


# ---------------------------------------------------------------------------
# Server identity
# ---------------------------------------------------------------------------
def test_server_identity_and_instructions() -> None:
    assert planner_server.mcp.name == "ess-planner"
    instructions = planner_server.mcp.instructions or ""
    # The invocation contract callers rely on is stated up front.
    assert "ETag" in instructions
    assert "access token" in instructions


def test_discovery_exposes_intent_boundaries_without_shared_clients(monkeypatch) -> None:
    def unexpected_client():
        pytest.fail("MCP discovery must not initialize shared-service clients")

    monkeypatch.setattr(planner_server, "get_client", unexpected_client)
    monkeypatch.setattr(planner_server, "get_inventory_surface", unexpected_client)

    instructions = planner_server.mcp.instructions or ""
    for phrase in ("user-requested workflow", "greeting-only", "Hi", "plan.json", "inventory/setup"):
        assert phrase in instructions
    description = " ".join(_tools()["create_agent_configuration_project"].description.split())
    for phrase in ("requested Planner action", "not permission", "can create a project"):
        assert phrase in description


# ---------------------------------------------------------------------------
# Exposed surface
# ---------------------------------------------------------------------------
def test_exposes_exactly_the_expected_tools() -> None:
    assert set(_tools()) == set(_TOOLS)


def test_each_tool_input_schema_declares_params_and_required() -> None:
    tools = _tools()
    for name, (props, required) in _TOOLS.items():
        schema = tools[name].inputSchema
        assert set(schema.get("properties", {})) == set(props), name
        assert set(schema.get("required", [])) == set(required), name


def test_no_tool_input_schema_exposes_identity_or_tenant() -> None:
    for name, tool in _tools().items():
        properties = set(tool.inputSchema.get("properties", {}))
        assert not (properties & _FORBIDDEN_IDENTITY_ARGS), name


def test_every_tool_has_a_nonempty_description() -> None:
    for name, tool in _tools().items():
        assert tool.description and tool.description.strip(), name


def test_key_tool_descriptions_explain_how_to_invoke() -> None:
    tools = _tools()
    # Archive endpoints explain there is no DELETE and an ETag is required.
    assert "no DELETE" in tools["archive_agent_configuration_project"].description
    assert "ETag" in tools["archive_project_plan"].description
    # Completion documents the artifact shape and the Environment rule.
    complete = tools["complete_project_plan_task"].description
    assert "environmentId" in complete
    assert "Custom|Environment|Connection|" in complete
    # Attestation documents the attestable roles and the External provider.
    attest = tools["attest_plan_role"].description
    assert "External" in attest
    assert "WorkdayAdmin" in attest
    # Plan creation documents the required configuringAgentName enum (DA-only).
    create_plan = tools["create_project_plan"].description
    assert "configuringAgentName" in create_plan
    assert "EmployeeSelfServiceHRDA" in create_plan
    # The caller-scoped listing documents that identity comes from the token.
    caller = tools["list_project_plan_tasks_for_caller"].description
    assert "access token" in caller


def test_tool_annotations_reflect_read_mutate_delete_effect() -> None:
    tools = _tools()
    for name, category in _TOOL_CATEGORY.items():
        read_only, destructive, idempotent = _HINTS[category]
        annotations = tools[name].annotations
        assert annotations is not None, name
        assert annotations.readOnlyHint is read_only, name
        assert annotations.destructiveHint is destructive, name
        assert annotations.idempotentHint is idempotent, name


def test_plan_creation_guidance_infers_and_confirms_experience_from_scenarios() -> None:
    description = " ".join(_tools()["create_project_plan"].description.split())
    assert "Infer the target from the requested scenarios" in description
    assert "confirm it with the draft plan" in description
    assert "not an up-front experience selector" in description
    assert "HR vs IT is the only choice" not in description


def test_status_tool_guidance_distinguishes_team_overview_from_personal_next_step() -> None:
    tools = _tools()
    overview = " ".join(tools["list_project_plan_tasks"].description.split())
    personal = " ".join(tools["list_project_plan_tasks_for_caller"].description.split())
    assert "team overview, not the caller's assignments" in overview
    assert "list_project_plan_tasks_for_caller" in overview
    assert "personal next step in a status response" in personal
    assert "does not make them ready to execute" in personal
    assert "plan lifecycle" in personal
    assert "dependencies" in personal
    assert "shared draft is read-only" in personal


def test_status_requests_do_not_authorize_activation() -> None:
    description = " ".join(_tools()["update_project_plan"].description.split())
    assert "explicit activation request" in description
    assert "a status question is not consent" in description


def test_caller_task_guidance_requires_refresh_after_progress() -> None:
    description = " ".join(_tools()["list_project_plan_tasks_for_caller"].description.split())
    assert "Query again after completion or reassignment" in description
    assert "do not reuse an earlier task list" in description


# ---------------------------------------------------------------------------
# Invocation wiring
# ---------------------------------------------------------------------------
def test_list_attestable_roles_returns_provider_roles() -> None:
    result = _call("list_attestable_roles", {})
    assert json.loads(_result_text(result)) == [
        "WorkdayAdmin",
        "ServiceNowAdmin",
        "ServiceNowKnowledgeManager",
        "EntraGlobalAdministrator",
        "EntraNetworkAdministrator",
        "EntraUserAdministrator",
        "EntraPowerPlatformAdministrator",
        "EntraApplicationAdministrator",
        "EntraCloudApplicationAdministrator",
        "PowerPlatformEnvironmentMaker",
        "PowerPlatformEnvironmentAdministrator",
        "PowerPlatformSystemAdministrator",
    ]


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_call"),
    [
        (
            "get_project_plan",
            {"projectId": "p1", "planId": "pl1"},
            ("get_project_plan", ["p1", "pl1", None]),
        ),
        (
            "archive_project_plan",
            {"projectId": "p1", "planId": "pl1", "etag": "e1"},
            ("archive_project_plan", ["p1", "pl1", "e1"]),
        ),
        (
            "set_project_plan_task_state",
            {
                "projectId": "p1",
                "planId": "pl1",
                "taskId": "t1",
                "state": "InProgress",
                "etag": "e1",
            },
            ("set_project_plan_task_state", ["p1", "pl1", "t1", "InProgress", "e1"]),
        ),
        (
            "revoke_role_assignment",
            {"assignmentId": "a1"},
            ("revoke_role_assignment", ["a1", None]),
        ),
    ],
)
def test_call_tool_wires_through_to_client(
    monkeypatch, tool_name: str, arguments: dict, expected_call: tuple
) -> None:
    fake = _RecordingClient()
    monkeypatch.setattr(planner_server, "_client", fake)

    result = _call(tool_name, arguments)

    name, args, _ = fake.calls[0]
    assert (name, args) == (expected_call[0], tuple(expected_call[1]))
    assert json.loads(_result_text(result))["called"] == tool_name


def test_caller_scoped_tool_passes_no_identity_to_client(monkeypatch) -> None:
    fake = _RecordingClient()
    monkeypatch.setattr(planner_server, "_client", fake)

    _call("list_project_plan_tasks_for_caller", {"projectId": "p1", "planId": "pl1"})

    name, args, kwargs = fake.calls[0]
    assert name == "list_project_plan_tasks_for_caller"
    # Only project/plan/query are forwarded; the caller id is the client's job.
    assert args == ("p1", "pl1", None)
    assert kwargs == {}


def test_attest_tool_forwards_optional_headers_as_keywords(monkeypatch) -> None:
    fake = _RecordingClient()
    monkeypatch.setattr(planner_server, "_client", fake)

    _call(
        "attest_plan_role",
        {"planId": "pl1", "subjectId": "s1", "role": "WorkdayAdmin"},
    )

    name, args, kwargs = fake.calls[0]
    assert name == "attest_plan_role"
    assert args == ("pl1", "s1", "WorkdayAdmin")
    assert kwargs == {"etag": None, "idempotency_key": None}
