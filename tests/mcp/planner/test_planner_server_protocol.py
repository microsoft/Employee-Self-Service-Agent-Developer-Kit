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
}

# Category -> (readOnlyHint, destructiveHint, idempotentHint).
_HINTS = {
    "read": (True, False, True),
    "create": (False, False, False),
    "create_idempotent": (False, False, True),
    "update": (False, False, True),
    "delete": (False, True, True),
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
    # Plan creation documents the required configuringAgentName enum.
    create_plan = tools["create_project_plan"].description
    assert "configuringAgentName" in create_plan
    assert "EmployeeSelfServiceHRCEA" in create_plan
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


# ---------------------------------------------------------------------------
# Invocation wiring
# ---------------------------------------------------------------------------
def test_list_attestable_roles_returns_provider_roles() -> None:
    result = _call("list_attestable_roles", {})
    assert json.loads(_result_text(result)) == [
        "WorkdayAdmin",
        "ServiceNowAdmin",
        "ServiceNowKnowledgeManager",
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
