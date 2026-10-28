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

from inventory_surface import InventorySurface
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
# can create records; idempotence permits safe replay after an ambiguous failure,
# not invocation without a requested workflow.
_CREATE_IDEMPOTENT_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
# syncInventory is whole-inventory replace: the payload IS the desired end state, so
# anything Active it omits is retired — destructive. It is still safe to replay (the
# idempotency key makes a resend converge rather than re-run), so it is marked
# idempotent.
_SYNC_INVENTORY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)


mcp = FastMCP(
    "ess-planner",
    instructions=(
        "Use tools only for a user-requested workflow or a genuine continuation, "
        "including requested planning or inventory/setup discovery. A greeting-only "
        "message such as Hi, general help, or passive open/attached plan.json context "
        "does not request work. Tool availability or prior approval is not permission "
        "to start a workflow. "
        "ESS Planner reads and updates shared implementation plans, tasks, and "
        "role assignments. Explain this purpose before a host trust prompt; "
        "tool approval does not grant environment-admin permissions. "
        "Identity and tenant come from the access token and "
        "are never tool arguments. For any PATCH/DELETE, read the exact entity "
        "first and pass its current ETag as ``etag`` (sent as If-Match). The "
        "server turns the two conflicts this surface produces into actionable "
        "errors: on a stale ETag (412) it tells you the entity changed since "
        "you read it and to re-read and reapply — it never silently replays "
        "your write over another edit — and when a task mutation is blocked "
        "because its parent plan is not Active it returns an actionable message "
        "telling you to activate the plan first. Activation requires explicit "
        "user consent; never activate just to bypass an error. Before starting "
        "or completing work, verify its prerequisites and pending decisions. "
        "A local completion is not shared until readback confirms state and outputs. "
        "Projects and plans have no "
        "DELETE route — archive them instead; only tasks can be deleted."
    ),
)

_client: Optional[PlannerClient] = None
_inventory: Optional[InventorySurface] = None


def get_client() -> PlannerClient:
    global _client
    if _client is None:
        _client = PlannerClient()
    return _client


def get_inventory_surface() -> InventorySurface:
    """Lazily build the inventory write path, reusing the planner's resolved token.

    The WeveNova Inventory API accepts the same ``weve/.default`` scope the planner
    core already holds, so a crawl persists through this one MCP under the signed-in
    principal without a second sign-in. The token is read per request so a refresh is
    picked up; ``WEVENOVA_ACCESS_TOKEN`` still overrides it for CI.
    """
    global _inventory
    if _inventory is None:
        client = get_client()
        _inventory = InventorySurface(
            token_provider=lambda: get_client()._token,
            tenant_id=client.tenant_id,
        )
    return _inventory


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
    """Get one project and its current ETag before archiving or updating it. The
    project names its single plan in ``activePlanId`` (null when no plan is
    active): a project has at most one active plan — activating a plan archives
    whatever was active before — so resolve the plan from ``activePlanId`` rather
    than listing and choosing."""
    return _format(
        await get_client().get_agent_configuration_project(projectId, query)
    )


@mcp.tool(annotations=_CREATE_IDEMPOTENT_ANNOTATIONS)
async def create_agent_configuration_project(
    project: dict[str, Any],
    idempotencyKey: Optional[str] = None,
) -> str:
    """Get-or-create a project by name (case/whitespace-insensitive). Only use
    this for a requested Planner action, not Hi alone, general help, or an open plan.json
    without an action. Passive file context is not permission; this operation can create a project.
    Supported names: {"name": "Employee Self-Service"} or {"name": "Workforce Insights"};
    optional ownedById? and metadata?. An unsupported name is rejected (400
    ValidationError "name must be one of the supported configuration
    experiences: Employee Self-Service, Workforce Insights"). The returned
    project carries ``activePlanId`` — the project's single active plan (null if
    none) — use it to resolve the plan instead of listing and choosing."""
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
    """List a project's plans (returns only non-archived plans). A project has at
    most one active plan, so prefer the project's ``activePlanId`` to resolve the
    plan directly; use this list only when ``activePlanId`` is null, to find an
    un-activated Draft."""
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
    ESS agent this plan configures. The ESS agent ships as a declarative agent
    (DA), which is what merges to main, so name one of EmployeeSelfServiceHRDA or
    EmployeeSelfServiceITDA. Infer the target from the requested scenarios and
    confirm it with the draft plan, preserving an explicit or saved target;
    this is not an up-front experience selector or a DA-vs-custom-engine choice.
    The target is required for this shared create, not for local drafting.
    Wait for explicit sharing consent and a resolved target before calling.
    Then optional ownedById?, acceptanceCriteria?, context?, and
    tasks? (inline tasks are created atomically with the plan, max 50). Unknown
    fields are rejected (400). New plans start in Draft. Aggregate plan metadata
    is checked against the 25,600-byte record budget with client headroom for
    server-added fields. Use the latest export-remote-plan body; it can compact
    generated workstream metadata without dropping intent. PlanPayloadTooLarge
    or OpenTypeTooLarge is not transient: do not retry unchanged or rotate keys
    to bypass it. Confirm the intended tenant if diagnostics report a mismatch."""
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
    Only the plan owner may change status. Activation requires an explicit
    activation request; a status question is not consent.
    Requires the plan's current ETag; if
    it is stale the call fails with an actionable 412 telling you to re-read the
    plan and reapply your change (the write is never silently replayed).
    Metadata edits are size-checked against the current record, not just the
    patch, while retaining the caller's ETag. PlanPayloadTooLarge/OpenTypeTooLarge
    requires reducing redundant metadata and re-exporting, not unchanged retries."""
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
    """List the tasks in a plan for a team overview, not the caller's assignments.
    For a personal execution next step, use list_project_plan_tasks_for_caller
    rather than treating any ready task in this list as the caller's work."""
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
    caller Entra id is taken from the access token, not an argument. This tool
    always sends that id as the top-level caller marker
    (assignedToId eq '<caller>') — the service needs it to run the role
    expansion — and always excludes Completed tasks (state ne 'Completed').
    Any query.filter you pass is ANDed on as a residual that narrows further;
    it cannot drop the marker or surface Completed work.
    Use this view for a personal next step in a status response. Returning tasks
    does not make them ready to execute: check the plan lifecycle, task state,
    and dependencies first; a shared draft is read-only. An empty result is not
    proof that the caller has no role, and never permits substituting another
    person's ready work. Query again after completion or reassignment before
    recommending the next task; do not reuse an earlier task list."""
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
    the caller to check task prerequisites before starting/completing work and
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
    actionable "activate the plan first" message. Do not fake completion to
    share partial outputs; confirm state and outputs by reading the plan back."""
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
    """List the provider-owned role identifiers accepted by plan attestation
    (across the External, Entra, and PowerPlatform providers)."""
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
    """Attest that a subject holds an attestable role for a plan. Pass a compact
    role id from list_attestable_roles; the backend's attestable set spans three
    providers - External (WorkdayAdmin, ServiceNowAdmin, ServiceNowKnowledgeManager),
    Entra directory roles (e.g. EntraPowerPlatformAdministrator,
    EntraGlobalAdministrator, EntraApplicationAdministrator), and PowerPlatform
    (e.g. PowerPlatformEnvironmentMaker, PowerPlatformSystemAdministrator). Each
    role's display name and owning provider are derived from the role, so the
    provider is never a free choice (the backend rejects a mismatched provider);
    a role's display name is also accepted in place of its compact id. Omit etag
    for a first attestation; pass an existing assignment's strong ETag to converge
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


# ----------------------------------------------------------------------
# WeveNova tenant-inventory tools. The discovery crawler
# (tenant_inventory_discovery.mcp_inventory.McpInventoryClient) drives these four
# over stdio to persist a crawl through this same ess-planner MCP, so the inventory
# write path shares the planner's identity and process instead of a separate server.
# Unlike the planner tools they return a {ok, data|error} envelope (not raw _format
# JSON): the crawler unwraps it and rebuilds the inventory error taxonomy from
# error.type. These are sync defs on purpose — the shared HttpInventoryClient is
# blocking, and FastMCP runs sync tools in a worker thread so they never stall the
# event loop. Tenant and token come from the access token; the tenant_id argument is
# part of the crawler's wire contract but the token's tid is authoritative.
# ----------------------------------------------------------------------


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
def server_info() -> str:
    """Report the inventory endpoint and token strategy the server is using (never the
    token itself). The crawler reads ``baseUrl`` to label the write path. Returns a
    ``{ok, data|error}`` envelope."""
    return _format(get_inventory_surface().server_info())


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
def probe(tenant_id: str) -> str:
    """Pre-flight the WeveNova Inventory API: one ``$top=1`` GET to confirm the
    endpoint is reachable and the token is accepted, so an unusable write path is
    reported before a long crawl rather than at sync time. Returns a
    ``{ok, data|error}`` envelope."""
    return _format(get_inventory_surface().probe())


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
def list_items(
    tenant_id: str,
    kind: Optional[str] = None,
    environment_id: Optional[str] = None,
) -> str:
    """List the tenant's non-retired inventory rows, optionally narrowed to one
    ``kind`` discriminator (e.g. Environment, Connection) and/or ``environment_id``.
    Returns a ``{ok, data|error}`` envelope whose ``data`` is the row list."""
    return _format(
        get_inventory_surface().list_items(kind=kind, environment_id=environment_id)
    )


@mcp.tool(annotations=_SYNC_INVENTORY_ANNOTATIONS)
def sync_inventory(
    tenant_id: str,
    items: list[dict[str, Any]],
    run_id: str = "",
) -> str:
    """Persist the tenant's whole inventory to WeveNova in one ``syncInventory`` call.
    The submitted ``items`` ARE the desired end state, so anything Active the payload
    omits is retired — never submit a partial crawl. Each item is domain-shaped
    ({kind, natural_key, attributes, environment_id, display_name, description}); the
    shared client encodes the wire body, so there is only one encoder. ``run_id``
    scopes the idempotency key so a timed-out resend replays rather than re-runs.
    Returns a ``{ok, data|error}`` envelope with submitted/upserted/retired counts,
    retiredItemIds, and any failedItems."""
    return _format(get_inventory_surface().sync_inventory(items=items, run_id=run_id))


if __name__ == "__main__":
    mcp.run()
