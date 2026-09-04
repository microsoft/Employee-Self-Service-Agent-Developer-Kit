"""Pure mapping seam between the local ``plan.json`` document and the planner
service's wire shape (the "sync seam").

The planner CLI never talks to the network — it only ever reads and writes the
local plan document. The *skill* orchestrates the remote calls (through the
planner tools) and shuttles JSON in and out of this module:

* **export** — :func:`to_remote_plan_body` turns the local plan into the single
  create body the service expects (``configuringAgentName`` + inline tasks), so
  a freshly designed plan can be pushed "as one object".
* **import** — :func:`hydrate_from_remote` rebuilds the local cache from the
  entities the service returns, so the service stays the source of truth and the
  local file is just a durable mirror.

Everything here is pure: dict in, dict out. No I/O, no network, no clock reads
except the ``syncedAt`` stamp. That keeps the mapping exhaustively unit-testable
and keeps the two vocabularies (local vs. service) from leaking into each other.

Vocabulary bridges handled here:

* Task state — the local model has ``Blocked`` where the service has
  ``Cancelled``; every other state is shared verbatim. ``Cancelled`` is only ever
  set server-side by the plan-archive cascade, so export never emits it.
* Acceptance criteria — local plans keep them as ordinary Context entries under
  the ``acceptanceCriteria`` group (one open bag); the service models them as a
  first-class ``acceptanceCriteria`` list. This module promotes them on export
  and demotes them back into the group on import.
* Assignee — the local ``assignedTo`` Principal is flattened to the service's
  ``assignedToId`` / ``assignedToType`` / ``assignedToRoleId`` triple on export
  and reconstructed on import.
"""

from __future__ import annotations

from typing import Any

from planner.plan_model import (
    ACCEPTANCE_GROUP,
    CONFIGURING_AGENT_NAMES,
    PLAN_STATES,
    SCHEMA_VERSION,
    Plan,
    assignee_role_id,
    assignee_user_oid,
    context_entry,
    new_task,
    now_iso,
    plan_artifact,
    principal_person,
    principal_pool,
)

# The service's PlanTaskState enum, in declaration order (so an integer wire
# value can be resolved positionally). Only ``Cancelled`` differs from the local
# vocabulary — see the state-bridge helpers below.
_REMOTE_TASK_STATES = ("NotStarted", "InProgress", "Completed", "Cancelled")


# --------------------------------------------------------------------------- #
# Vocabulary bridges (state + status).
# --------------------------------------------------------------------------- #

def local_to_remote_state(state: str) -> str:
    """Map a local task state onto the service vocabulary (``Blocked`` →
    ``Cancelled``; everything else is shared).

    Export never actually sends state — new tasks always start ``NotStarted`` —
    but the bridge is exposed for completeness and symmetry with the importer.
    """
    return "Cancelled" if state == "Blocked" else state


def remote_task_state(raw: Any) -> str:
    """Map a service task state (name or ordinal) onto the local vocabulary.

    ``Cancelled`` becomes the local ``Blocked``; unknown values fall back to
    ``NotStarted`` so a partial/garbled read never corrupts the cache.
    """
    value: str | None = None
    if isinstance(raw, str) and raw:
        for state in _REMOTE_TASK_STATES:
            if state.lower() == raw.lower():
                value = state
                break
        else:
            value = raw
    elif isinstance(raw, bool):  # bool is an int subclass — guard before int.
        value = "NotStarted"
    elif isinstance(raw, int) and 0 <= raw < len(_REMOTE_TASK_STATES):
        value = _REMOTE_TASK_STATES[raw]
    if not value:
        value = "NotStarted"
    return "Blocked" if value == "Cancelled" else value


def remote_plan_status(raw: Any) -> str:
    """Map a service plan status (name or ordinal) onto the local vocabulary.

    The two vocabularies are identical (``Draft``/``Active``/``Completed``/
    ``Archived``); this only normalises case and resolves integers, defaulting to
    ``Draft`` for anything unrecognised.
    """
    if isinstance(raw, str) and raw:
        for status in PLAN_STATES:
            if status.lower() == raw.lower():
                return status
        return raw
    if isinstance(raw, bool):
        return "Draft"
    if isinstance(raw, int) and 0 <= raw < len(PLAN_STATES):
        return PLAN_STATES[raw]
    return "Draft"


# --------------------------------------------------------------------------- #
# Export — local plan  ->  service create body.
# --------------------------------------------------------------------------- #

def to_remote_task_body(task: dict[str, Any]) -> dict[str, Any]:
    """Flatten one local task into the service's task-create shape.

    Only the fields the service accepts are emitted — ``title`` (required),
    optional ``description`` / ``produces`` / ``consumes``, and a flattened
    assignee. Local-only fields (``id``, ``state``, ``checklist``, ``remoteId``,
    ``etag``) are dropped: the service assigns its own ids and new tasks always
    start ``NotStarted``.
    """
    body: dict[str, Any] = {"title": task.get("title", "")}

    description = task.get("description")
    if description:
        body["description"] = description

    assigned_to = task.get("assignedTo") or {}
    ptype = assigned_to.get("type")
    role_id = assignee_role_id(assigned_to)
    oid = assignee_user_oid(assigned_to)
    if ptype == "Role":
        # Open pool: anyone holding the role may claim it.
        body["assignedToType"] = "Role"
        body["assignedToId"] = assigned_to.get("id") or role_id or ""
        if role_id:
            body["assignedToRoleId"] = role_id
    elif ptype == "User" and oid:
        # Owned by a person (default type User is left implicit). A retained role
        # rides along as the grounding ``assignedToRoleId``.
        body["assignedToId"] = oid
        if role_id:
            body["assignedToRoleId"] = role_id
    # Otherwise unassigned — emit no assignee fields.

    produces = task.get("produces")
    if produces:
        body["produces"] = list(produces)
    consumes = task.get("consumes")
    if consumes:
        body["consumes"] = list(consumes)
    return body


def to_remote_plan_body(
    plan: Plan,
    *,
    configuring_agent_name: str | None = None,
) -> dict[str, Any]:
    """Turn the local plan into the single service create body.

    The service requires ``configuringAgentName`` and rejects unknown fields, so
    this emits *exactly* the allowed keys and omits every empty optional:

    * ``configuringAgentName`` — from the ``configuring_agent_name`` argument, or
      the plan's stored value. Required: raises :class:`ValueError` if neither is
      set or the value is not a known agent.
    * ``acceptanceCriteria`` — promoted from Context entries in the
      ``acceptanceCriteria`` group (their scalar values, in order).
    * ``context`` — every *other* Context entry as ``{key, value, group?,
      description?}`` (provenance is server-stamped, never sent).
    * ``tasks`` — the plan's tasks, each via :func:`to_remote_task_body`.
    """
    name = configuring_agent_name or plan.configuring_agent_name
    if not name:
        raise ValueError(
            "configuringAgentName is required to push a plan — set it first "
            "(one of " + ", ".join(CONFIGURING_AGENT_NAMES) + ")"
        )
    if name not in CONFIGURING_AGENT_NAMES:
        raise ValueError(
            f"invalid configuringAgentName {name!r} — must be one of "
            + ", ".join(CONFIGURING_AGENT_NAMES)
        )

    acceptance: list[str] = []
    context: list[dict[str, Any]] = []
    for entry in plan.context:
        if entry.get("group") == ACCEPTANCE_GROUP:
            acceptance.append(entry.get("value"))
            continue
        item: dict[str, Any] = {"key": entry.get("key"), "value": entry.get("value")}
        group = entry.get("group")
        if group:
            item["group"] = group
        description = entry.get("description")
        if description:
            item["description"] = description
        context.append(item)

    body: dict[str, Any] = {"configuringAgentName": name}
    if acceptance:
        body["acceptanceCriteria"] = acceptance
    if context:
        body["context"] = context
    tasks = [to_remote_task_body(task) for task in plan.tasks]
    if tasks:
        body["tasks"] = tasks
    return body


# --------------------------------------------------------------------------- #
# Import — service entities  ->  local plan document.
# --------------------------------------------------------------------------- #

def _scalar(entity: Any, *names: str, default: Any = "") -> Any:
    """Read the first present, non-null field from ``entity`` by any of ``names``.

    The SDK declares camelCase, but the live OData endpoint may render PascalCase,
    so callers pass every plausible spelling and this also falls back to a
    case-insensitive match.
    """
    if not isinstance(entity, dict):
        return default
    for name in names:
        if entity.get(name) is not None:
            return entity[name]
    lowered = {str(k).lower(): v for k, v in entity.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None:
            return value
    return default


def _obj(entity: Any, *names: str) -> dict[str, Any]:
    value = _scalar(entity, *names, default=None)
    return value if isinstance(value, dict) else {}


def _list(entity: Any, *names: str) -> list[Any]:
    value = _scalar(entity, *names, default=None)
    return value if isinstance(value, list) else []


def _as_entities(payload: Any) -> list[dict[str, Any]]:
    """Normalise a task payload into a plain list of entities.

    Tolerates ``None``, a bare list, or an OData collection wrapper
    (``{"value": [...]}``).
    """
    if payload is None:
        return []
    if isinstance(payload, dict):
        value = payload.get("value")
        return value if isinstance(value, list) else []
    if isinstance(payload, list):
        return payload
    return []


def _principal_from_remote(task: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct a local ``assignedTo`` Principal from a service task.

    Prefers the expanded ``assignedTo`` object, falling back to the flat
    ``assignedToId`` / ``assignedToRoleId`` fields. A role without a person is an
    open pool; a person (optionally carrying a grounding role) is an owner.
    """
    principal = _obj(task, "assignedTo", "AssignedTo")
    ptype = _scalar(principal, "type", "Type", default="") if principal else ""
    # Fall back to the flat assignedToType when the principal isn't expanded (e.g.
    # a create body echoed back before the service hydrates the reference).
    if not ptype:
        ptype = _scalar(task, "assignedToType", "AssignedToType", default="")

    role_id = _scalar(task, "assignedToRoleId", "AssignedToRoleId", default="")
    oid = _scalar(task, "assignedToId", "AssignedToId", default="")
    if principal:
        pid = _scalar(principal, "id", "Id", default="")
        if ptype == "Role" and not role_id:
            role_id = pid
        elif ptype == "User" and not oid:
            oid = pid

    if ptype == "Role":
        # Open pool — the role id may arrive as assignedToRoleId or (since a pool's
        # assignedToId *is* the role id) as assignedToId.
        pool_role = role_id or oid
        return principal_pool(pool_role) if pool_role else {}
    if role_id and not oid:
        return principal_pool(role_id)
    if oid:
        return principal_person(oid, role_id or None)
    return {}


def _task_from_remote(task: dict[str, Any]) -> dict[str, Any]:
    """Rebuild one local task dict from a service task entity."""
    remote_id = _scalar(task, "taskId", "TaskId", "id", "Id", default="")
    local = new_task(
        remote_id,
        _scalar(task, "title", "Title", default=""),
        description=_scalar(task, "description", "Description", default=""),
        assigned_to=_principal_from_remote(task),
        produces=_list(task, "produces", "Produces"),
        consumes=_list(task, "consumes", "Consumes"),
        state=remote_task_state(_scalar(task, "state", "State", default="NotStarted")),
    )
    local["remoteId"] = remote_id
    local["etag"] = _scalar(task, "etag", "ETag", "@odata.etag", default="")
    return local


def _output_from_remote(artifact: dict[str, Any]) -> dict[str, Any]:
    """Rebuild one local output artifact from a service ``PlanArtifact``.

    The service models attributes as a typed list; the local model stores them as
    a flat ``{key: value}`` dict, so the description on each entry is dropped.
    """
    attributes: dict[str, Any] = {}
    for attr in _list(artifact, "attributes", "Attributes"):
        if isinstance(attr, dict):
            key = _scalar(attr, "key", "Key", default="")
            if key:
                attributes[key] = _scalar(attr, "value", "Value", default="")

    kind = _scalar(artifact, "kind", "Kind", default="Custom")
    if not isinstance(kind, str):
        kind = "Custom"
    state = _scalar(artifact, "state", "State", default="Active")
    if not isinstance(state, str) or not state:
        state = "Active"
    return plan_artifact(
        _scalar(artifact, "key", "Key", default=""),
        kind,
        attributes,
        produced_by_task_id=_scalar(artifact, "producedByTaskId", "ProducedByTaskId", default=""),
        inventory_ref=_scalar(artifact, "inventoryRef", "InventoryRef", default="") or None,
        source="Agent",
        state=state,
    )


def hydrate_from_remote(
    plan_entity: dict[str, Any],
    task_entities: Any = None,
) -> dict[str, Any]:
    """Rebuild a local ``plan.json`` document from service entities.

    ``plan_entity`` is a single service ``Plan``; ``task_entities`` is the task
    collection (a list, an OData ``{"value": [...]}`` wrapper, or ``None`` to use
    the plan's embedded ``agentPlanTasks`` expansion). The result is a plain dict
    ready to hand to :meth:`Plan.load`/``save_all`` — the service stays the source
    of truth, so this never runs local validation.
    """
    if not isinstance(plan_entity, dict):
        raise ValueError("plan_entity must be a service Plan object")

    # ``None`` means "tasks weren't fetched — use the plan's embedded expansion";
    # an explicit collection (even an empty ``{"value": []}``) is the service
    # authoritatively stating the task set, so it must NOT fall back to the
    # embedded ``agentPlanTasks`` (that would resurrect tasks deleted upstream).
    if task_entities is None:
        tasks_raw = _as_entities(_scalar(plan_entity, "agentPlanTasks", "AgentPlanTasks", default=None))
    else:
        tasks_raw = _as_entities(task_entities)

    context: list[dict[str, Any]] = []
    for entry in _list(plan_entity, "context", "Context"):
        if not isinstance(entry, dict):
            continue
        context.append(
            context_entry(
                _scalar(entry, "key", "Key", default=""),
                _scalar(entry, "value", "Value", default=""),
                group=_scalar(entry, "group", "Group", default="") or None,
                description=_scalar(entry, "description", "Description", default="") or None,
                source="Agent",
            )
        )
    # Demote the service's first-class acceptance criteria back into the Context
    # bag under the acceptance group (stable, unique keys).
    for index, criterion in enumerate(_list(plan_entity, "acceptanceCriteria", "AcceptanceCriteria"), start=1):
        context.append(
            context_entry(
                f"acceptance.{index}",
                criterion,
                group=ACCEPTANCE_GROUP,
                description="Acceptance criterion",
                source="Agent",
            )
        )

    tasks = [_task_from_remote(t) for t in tasks_raw if isinstance(t, dict)]
    outputs = [_output_from_remote(a) for a in _list(plan_entity, "outputs", "Outputs") if isinstance(a, dict)]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "planId": _scalar(plan_entity, "planId", "PlanId", "id", "Id", default=""),
        "projectId": _scalar(plan_entity, "projectId", "ProjectId", default=""),
        "configuringAgentName": _scalar(plan_entity, "configuringAgentName", "ConfiguringAgentName", default=""),
        "status": remote_plan_status(_scalar(plan_entity, "status", "Status", default="Draft")),
        "context": context,
        "tasks": tasks,
        "outputs": outputs,
        "etag": _scalar(plan_entity, "etag", "ETag", "@odata.etag", default=""),
        "syncedAt": now_iso(),
    }


def stamp_remote_ids(
    plan: Plan,
    *,
    project_id: str,
    plan_id: str,
    plan_etag: str | None = None,
    synced_at: str | None = None,
) -> Plan:
    """Record the service ids/ETag a locally-authored plan now mirrors.

    Used after pushing a plan the maker designed offline, when re-hydrating from
    the service would be wasteful — only the identity needs to be stamped.
    """
    plan.set_remote_identity(
        project_id=project_id,
        plan_id=plan_id,
        etag=plan_etag,
        synced_at=synced_at,
    )
    return plan
