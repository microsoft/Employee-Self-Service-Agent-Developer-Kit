# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Static contract checks for the AgentConfiguration planner MCP server.

Parsed from source (no import) so the exposed tool surface - names, argument
lists, read/mutate/delete classification, and the presence of a description -
is pinned even in environments without the ``mcp`` runtime. Behavioural
wiring and the resolved input schema are covered by
``test_planner_server_protocol.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
SERVER_PATH = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_planner"
    / "server.py"
)


# Identity and tenant come from the access token; none of these may ever be
# exposed as a tool argument.
_FORBIDDEN_IDENTITY_ARGS = {
    "userName",
    "username",
    "aadId",
    "aadObjectId",
    "tenantId",
    "callerId",
    "objectId",
    "oid",
    "tid",
}

_EXPECTED_TOOLS: dict[str, list[str]] = {
    "list_agent_configuration_projects": ["query"],
    "get_agent_configuration_project": ["projectId", "query"],
    "create_agent_configuration_project": ["project", "idempotencyKey"],
    "archive_agent_configuration_project": ["projectId", "etag"],
    "list_project_plans": ["projectId", "query"],
    "get_project_plan": ["projectId", "planId", "query"],
    "create_project_plan": ["projectId", "plan", "idempotencyKey"],
    "update_project_plan": ["projectId", "planId", "patch", "etag"],
    "archive_project_plan": ["projectId", "planId", "etag"],
    "list_project_plan_tasks": ["projectId", "planId", "query"],
    "list_project_plan_tasks_for_caller": ["projectId", "planId", "query"],
    "get_project_plan_task": ["projectId", "planId", "taskId", "query"],
    "create_project_plan_task": ["projectId", "planId", "task", "idempotencyKey"],
    "create_role_assigned_project_plan_task": [
        "projectId",
        "planId",
        "role",
        "title",
        "description",
        "produces",
        "consumes",
        "idempotencyKey",
    ],
    "update_project_plan_task": ["projectId", "planId", "taskId", "patch", "etag"],
    "set_project_plan_task_state": ["projectId", "planId", "taskId", "state", "etag"],
    "complete_project_plan_task": ["projectId", "planId", "taskId", "outputs", "etag"],
    "delete_project_plan_task": ["projectId", "planId", "taskId", "etag"],
    "list_attestable_roles": [],
    "list_plan_role_assignments": [
        "planId",
        "subjectId",
        "role",
        "status",
        "top",
        "orderby",
        "skiptoken",
    ],
    "get_role_assignment": ["assignmentId"],
    "attest_plan_role": ["planId", "subjectId", "role", "etag", "idempotencyKey"],
    "revoke_role_assignment": ["assignmentId", "etag"],
}

# Each tool's ToolAnnotations constant encodes what the endpoint does to the
# resource: read-only, non-destructive mutation, create, or destructive.
_EXPECTED_ANNOTATIONS: dict[str, str] = {
    "list_agent_configuration_projects": "_READ_ONLY_ANNOTATIONS",
    "get_agent_configuration_project": "_READ_ONLY_ANNOTATIONS",
    "create_agent_configuration_project": "_CREATE_IDEMPOTENT_ANNOTATIONS",
    "archive_agent_configuration_project": "_DELETE_ANNOTATIONS",
    "list_project_plans": "_READ_ONLY_ANNOTATIONS",
    "get_project_plan": "_READ_ONLY_ANNOTATIONS",
    "create_project_plan": "_CREATE_ANNOTATIONS",
    "update_project_plan": "_UPDATE_ANNOTATIONS",
    "archive_project_plan": "_DELETE_ANNOTATIONS",
    "list_project_plan_tasks": "_READ_ONLY_ANNOTATIONS",
    "list_project_plan_tasks_for_caller": "_READ_ONLY_ANNOTATIONS",
    "get_project_plan_task": "_READ_ONLY_ANNOTATIONS",
    "create_project_plan_task": "_CREATE_ANNOTATIONS",
    "create_role_assigned_project_plan_task": "_CREATE_ANNOTATIONS",
    "update_project_plan_task": "_UPDATE_ANNOTATIONS",
    "set_project_plan_task_state": "_UPDATE_ANNOTATIONS",
    "complete_project_plan_task": "_UPDATE_ANNOTATIONS",
    "delete_project_plan_task": "_DELETE_ANNOTATIONS",
    "list_attestable_roles": "_READ_ONLY_ANNOTATIONS",
    "list_plan_role_assignments": "_READ_ONLY_ANNOTATIONS",
    "get_role_assignment": "_READ_ONLY_ANNOTATIONS",
    "attest_plan_role": "_CREATE_IDEMPOTENT_ANNOTATIONS",
    "revoke_role_assignment": "_DELETE_ANNOTATIONS",
}


def _tool_nodes() -> dict[str, ast.AsyncFunctionDef]:
    module = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    tools: dict[str, ast.AsyncFunctionDef] = {}
    for node in module.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "tool"
            ):
                tools[node.name] = node
    return tools


def test_server_exposes_exactly_the_planner_tool_contract() -> None:
    tools = _tool_nodes()
    actual = {
        name: [argument.arg for argument in node.args.args]
        for name, node in tools.items()
    }
    assert actual == _EXPECTED_TOOLS


def test_each_tool_classifies_its_effect_with_annotations() -> None:
    annotations: dict[str, str] = {}
    for name, node in _tool_nodes().items():
        decorator = next(
            d
            for d in node.decorator_list
            if isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and d.func.attr == "tool"
        )
        keyword = next(
            (kw for kw in decorator.keywords if kw.arg == "annotations"), None
        )
        assert keyword is not None, f"{name} is missing tool annotations"
        assert isinstance(keyword.value, ast.Name)
        annotations[name] = keyword.value.id
    assert annotations == _EXPECTED_ANNOTATIONS


def test_every_tool_has_a_description() -> None:
    for name, node in _tool_nodes().items():
        docstring = ast.get_docstring(node)
        assert docstring and docstring.strip(), f"{name} has no description"


def test_no_tool_exposes_identity_or_tenant_arguments() -> None:
    for name, node in _tool_nodes().items():
        arg_names = {argument.arg for argument in node.args.args}
        leaked = arg_names & _FORBIDDEN_IDENTITY_ARGS
        assert not leaked, f"{name} exposes identity/tenant args: {sorted(leaked)}"
