# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS planner MCP server.

Exposes the AgentConfiguration beta surface — projects, plans, tasks,
and plan role attestation — as MCP tools for the planner skill. Identity and
tenant come from the access token (never tool arguments); the shared client
core (auth, token decode, httpx session, retrying ``_request``) is the neutral
``AgentConfigBaseClient``, which ``PlannerClient`` composes with the planner and role
mixins.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from planner_client import PlannerClient
from roles_surface import ATTESTABLE_ROLES


_READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_UPDATE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_DELETE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)
_CREATE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
# Get-or-create / upsert tools converge on the same resource, so a replay is
# safe: create_agent_configuration_project returns the existing project when one
# already matches, and attest_plan_role upserts a deterministic grant row. They
# are creates in name only — non-destructive and idempotent — so clients may
# safely retry them after an ambiguous failure.
_CREATE_IDEMPOTENT_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


mcp = FastMCP(
    "ess-planner",
    instructions=(
        "Drive AgentConfiguration projects, plans, tasks, and plan "
        "role attestation. Identity and tenant come from the access token and "
        "are never tool arguments. For any PATCH/DELETE, read the exact entity "
        "first and pass its current ETag as ``etag`` (sent as If-Match). The "
        "server turns the two conflicts this surface produces into actionable "
        "errors: on a stale ETag (412) it tells you the entity changed since "
        "you read it and to re-read and reapply — it never silently replays "
        "your write over another edit — and when a task mutation is blocked "
        "because its parent plan is not Active it returns an actionable message "
        "telling you to activate the plan first. Projects and plans have no "
        "DELETE route — archive them instead; only tasks can be deleted."
    ),
)

_client: Optional[PlannerClient] = None


def get_client() -> PlannerClient:
    global _client
    if _client is None:
        _client = PlannerClient()
    return _client


def _format(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


# ----------------------------------------------------------------------
# AgentConfiguration project / plan / task tools (AgentConfiguration beta surface).
# Identity and tenant come from the access token; they are never tool args.
# For any PATCH/DELETE, read the exact entity first and pass its current
# ETag as ``etag`` (sent as If-Match). On a stale-ETag (412) conflict the
# client surfaces an actionable "the entity changed, re-read and reapply"
# error instead of replaying the write, and turns the "parent plan not
# Active" task conflict (409) into an actionable message.
# ----------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def list_agent_configuration_projects(
    query: Optional[dict[str, Any]] = None,
) -> str:
    """List the caller's AgentConfiguration projects (optional OData query)."""
    return _format(await get_client().list_agent_configuration_projects(query))


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def get_agent_configuration_project(
    projectId: str,
    query: Optional[dict[str, Any]] = None,
) -> str:
    """Get one project and its current ETag before archiving or updating it."""
    return _format(
        await get_client().get_agent_configuration_project(projectId, query)
    )


@mcp.tool(annotations=_CREATE_IDEMPOTENT_ANNOTATIONS)
async def create_agent_configuration_project(
    project: dict[str, Any],
    idempotencyKey: Optional[str] = None,
) -> str:
    """Get-or-create a project by name (case/whitespace-insensitive). Supported
    names: {"name": "Employee Self-Service"} or {"name": "Workforce Insights"};
    optional ownedById? and metadata?. An unsupported name is rejected (400
    ValidationError "name must be one of the supported configuration
    experiences: Employee Self-Service, Workforce Insights")."""
    return _format(
        await get_client().create_agent_configuration_project(project, idempotencyKey)
    )


@mcp.tool(annotations=_DELETE_ANNOTATIONS)
async def archive_agent_configuration_project(projectId: str, etag: str) -> str:
    """Archive a project (projects have no DELETE route). Cascades to the active
    plan and cancels in-flight tasks. Pass the project's current ETag."""
    return _format(
        await get_client().archive_agent_configuration_project(projectId, etag)
    )


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def list_project_plans(
    projectId: str,
    query: Optional[dict[str, Any]] = None,
) -> str:
    """List the plans in a project."""
    return _format(await get_client().list_project_plans(projectId, query))


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def get_project_plan(
    projectId: str,
    planId: str,
    query: Optional[dict[str, Any]] = None,
) -> str:
    """Get a plan and its current ETag before archiving or updating it."""
    return _format(await get_client().get_project_plan(projectId, planId, query))


@mcp.tool(annotations=_CREATE_ANNOTATIONS)
async def create_project_plan(
    projectId: str,
    plan: dict[str, Any],
    idempotencyKey: Optional[str] = None,
) -> str:
    """Create a plan in a project. Body: configuringAgentName is REQUIRED — the
    ESS agent this plan configures, one of EmployeeSelfServiceHRCEA,
    EmployeeSelfServiceHRDA, EmployeeSelfServiceITCEA, EmployeeSelfServiceITDA;
    then optional ownedById?, acceptanceCriteria?, context?, and tasks? (inline
    tasks are created atomically with the plan, max 50). Unknown fields are
    rejected (400). New plans start in Draft."""
    return _format(
        await get_client().create_project_plan(projectId, plan, idempotencyKey)
    )


@mcp.tool(annotations=_UPDATE_ANNOTATIONS)
async def update_project_plan(
    projectId: str,
    planId: str,
    patch: dict[str, Any],
    etag: str,
) -> str:
    """Patch plan fields or dispatch a lifecycle change. Activate a Draft plan
    with patch {"status": "Active"}; also supports {"status": "Completed"} (use
    archive_project_plan for Archived), {"ownedById": ...},
    {"acceptanceCriteria": [...]}, or {"context": [...]}. Send a lifecycle field
    (status or ownedById) on its own — it cannot be combined with the other
    lifecycle field or with an acceptanceCriteria/context edit in one PATCH.
    Only the plan owner may change status. Requires the plan's current ETag; if
    it is stale the call fails with an actionable 412 telling you to re-read the
    plan and reapply your change (the write is never silently replayed)."""
    return _format(
        await get_client().update_project_plan(projectId, planId, patch, etag)
    )


@mcp.tool(annotations=_DELETE_ANNOTATIONS)
async def archive_project_plan(projectId: str, planId: str, etag: str) -> str:
    """Archive a plan (plans have no DELETE route). Cancels its in-flight tasks.
    Pass the plan's current ETag."""
    return _format(await get_client().archive_project_plan(projectId, planId, etag))


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def list_project_plan_tasks(
    projectId: str,
    planId: str,
    query: Optional[dict[str, Any]] = None,
) -> str:
    """List the tasks in a plan."""
    return _format(
        await get_client().list_project_plan_tasks(projectId, planId, query)
    )


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def list_project_plan_tasks_for_caller(
    projectId: str,
    planId: str,
    query: Optional[dict[str, Any]] = None,
) -> str:
    """List the plan's tasks for the authenticated caller — both tasks assigned
    directly to them AND tasks pooled to any attestable role the caller holds an
    active role assignment for (role-expanded). Attesting a caller into a role
    (attest_plan_role) is what makes that role's pooled tasks appear here. The
    caller Entra id is taken from the access token, not an argument."""
    return _format(
        await get_client().list_project_plan_tasks_for_caller(
            projectId, planId, query
        )
    )


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def get_project_plan_task(
    projectId: str,
    planId: str,
    taskId: str,
    query: Optional[dict[str, Any]] = None,
) -> str:
    """Get a task and its current ETag before updating, completing, or
    deleting it."""
    return _format(
        await get_client().get_project_plan_task(projectId, planId, taskId, query)
    )


@mcp.tool(annotations=_CREATE_ANNOTATIONS)
async def create_project_plan_task(
    projectId: str,
    planId: str,
    task: dict[str, Any],
    idempotencyKey: Optional[str] = None,
) -> str:
    """Create a task (body: title required; description?, assignedToId?,
    assignedToType? User|Role, assignedToRoleId?, produces?, consumes?)."""
    return _format(
        await get_client().create_project_plan_task(
            projectId, planId, task, idempotencyKey
        )
    )


@mcp.tool(annotations=_CREATE_ANNOTATIONS)
async def create_role_assigned_project_plan_task(
    projectId: str,
    planId: str,
    role: str,
    title: str,
    description: Optional[str] = None,
    produces: Optional[list[str]] = None,
    consumes: Optional[list[str]] = None,
    idempotencyKey: Optional[str] = None,
) -> str:
    """Create a pooled task assigned to whoever holds an attestable role
    (WorkdayAdmin, ServiceNowAdmin, ServiceNowKnowledgeManager)."""
    return _format(
        await get_client().create_role_assigned_project_plan_task(
            projectId,
            planId,
            role,
            title,
            description,
            produces,
            consumes,
            idempotencyKey,
        )
    )


@mcp.tool(annotations=_UPDATE_ANNOTATIONS)
async def update_project_plan_task(
    projectId: str,
    planId: str,
    taskId: str,
    patch: dict[str, Any],
    etag: str,
) -> str:
    """Patch task content or claim/reassign a pooled task. Accepts only title,
    description, assignedToId, produces, consumes. Reassignment is a lifecycle
    edit: send assignedToId on its own (a non-empty AAD id claims/reassigns, ""
    unassigns) — it cannot be combined with a title/description/produces/consumes
    edit in one PATCH. Use set_project_plan_task_state or
    complete_project_plan_task for state and outputs. Requires the task's current
    ETag; a stale ETag fails with an actionable 412 to re-read and reapply (never
    silently replayed), and a non-Active parent plan yields an actionable
    "activate the plan first" message."""
    return _format(
        await get_client().update_project_plan_task(
            projectId, planId, taskId, patch, etag
        )
    )


@mcp.tool(annotations=_UPDATE_ANNOTATIONS)
async def set_project_plan_task_state(
    projectId: str,
    planId: str,
    taskId: str,
    state: str,
    etag: str,
) -> str:
    """Transition a task's lifecycle state without outputs (NotStarted,
    InProgress, Completed, Cancelled). A task must be InProgress before it can
    be Completed, and the parent plan must be Active. Use
    complete_project_plan_task when completion must capture outputs. Requires
    the task's current ETag; a stale ETag fails with an actionable 412 to
    re-read and reapply (never silently replayed), and a non-Active parent plan
    yields an actionable "activate the plan first" message."""
    return _format(
        await get_client().set_project_plan_task_state(
            projectId, planId, taskId, state, etag
        )
    )


@mcp.tool(annotations=_UPDATE_ANNOTATIONS)
async def complete_project_plan_task(
    projectId: str,
    planId: str,
    taskId: str,
    outputs: list[dict[str, Any]],
    etag: str,
) -> str:
    """Complete an InProgress task and persist its outputs into the parent plan
    ledger. Each output needs key, kind (Custom|Environment|Connection|
    KnowledgeSource), and attributes [{key, value, description?}]; Environment
    outputs require a non-empty environmentId attribute. Requires the task's
    current ETag; a stale ETag fails with an actionable 412 to re-read and
    reapply (never silently replayed), and a non-Active parent plan yields an
    actionable "activate the plan first" message."""
    return _format(
        await get_client().complete_project_plan_task(
            projectId, planId, taskId, outputs, etag
        )
    )


@mcp.tool(annotations=_DELETE_ANNOTATIONS)
async def delete_project_plan_task(
    projectId: str,
    planId: str,
    taskId: str,
    etag: str,
) -> str:
    """Permanently delete one task (the only project-plan resource with a DELETE
    route). Requires the task's current ETag; a stale ETag fails with an
    actionable 412 to re-read and reapply (never silently replayed), and a
    non-Active parent plan yields an actionable "activate the plan first"
    message."""
    return _format(
        await get_client().delete_project_plan_task(projectId, planId, taskId, etag)
    )


# ----------------------------------------------------------------------
# AgentConfiguration role attestation tools. The tenant is taken from the access
# token; only the provider-owned attestable roles are valid and the
# attestation provider is always External.
# ----------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def list_attestable_roles() -> str:
    """List the provider-owned role identifiers accepted by plan attestation."""
    return _format(list(ATTESTABLE_ROLES))


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def list_plan_role_assignments(
    planId: str,
    subjectId: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    top: Optional[int] = None,
    orderby: Optional[str] = None,
    skiptoken: Optional[str] = None,
) -> str:
    """List active or revoked role assignments for a plan (plan-scoped;
    optionally filter by subjectId, role, or status Active|Revoked)."""
    return _format(
        await get_client().list_plan_role_assignments(
            planId, subjectId, role, status, top, orderby, skiptoken
        )
    )


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def get_role_assignment(assignmentId: str) -> str:
    """Get one role assignment by its opaque assignment ID (returns its ETag)."""
    return _format(await get_client().get_role_assignment(assignmentId))


@mcp.tool(annotations=_CREATE_IDEMPOTENT_ANNOTATIONS)
async def attest_plan_role(
    planId: str,
    subjectId: str,
    role: str,
    etag: Optional[str] = None,
    idempotencyKey: Optional[str] = None,
) -> str:
    """Attest that a subject holds an attestable role for a plan; the provider is
    always External. Pass the compact role id — WorkdayAdmin, ServiceNowAdmin, or
    ServiceNowKnowledgeManager (their display names Workday administrator,
    ServiceNow Administrator, ServiceNow Knowledge Manager are also accepted); the
    tool sends the display name the backend validates against. Omit etag for a
    first attestation; pass an existing assignment's strong ETag to converge
    (never the plan's weak ETag)."""
    return _format(
        await get_client().attest_plan_role(
            planId, subjectId, role, etag=etag, idempotency_key=idempotencyKey
        )
    )


@mcp.tool(annotations=_DELETE_ANNOTATIONS)
async def revoke_role_assignment(
    assignmentId: str,
    etag: Optional[str] = None,
) -> str:
    """Revoke a plan role assignment by opaque assignment ID (soft-revoke to
    Status=Revoked)."""
    return _format(await get_client().revoke_role_assignment(assignmentId, etag))


if __name__ == "__main__":
    mcp.run()
