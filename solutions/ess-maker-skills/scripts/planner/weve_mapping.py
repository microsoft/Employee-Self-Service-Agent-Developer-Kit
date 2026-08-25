# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: mapping between the local Plan model and the WeveNova
project-plan entities exposed over the ``weve-plan`` MCP server.

The local model (``plan_model``) is intentionally shaped like the WeveNova
entities, but the two differ in two concrete ways that this module reconciles:

  * **Casing.** WeveNova serialises PascalCase (``PlanId``, ``Context``, ``Key``,
    ``Value``, ``Provenance``…); the local model uses camelCase (``planId``,
    ``context``, ``key``, ``value``, ``provenance``…).
  * **Artifact attributes.** A WeveNova ``Output`` carries ``Attributes`` as a
    **list** of ``{Key, Value, Description, Provenance}`` records; the local
    ``PlanArtifact`` carries ``attributes`` as a **flat dict** ``{key: value}``.

The field names here are grounded in a live ``get_project_plan`` response (see
``tests/planner/fixtures/weve_project_plan.json``). The WeveNova *task* entity's
navigation collection was not reachable at authoring time (the upstream
``…/agentPlans('…')/tasks`` path returned 404), so the task mapping mirrors the
same PascalCase + ``AssignedTo`` Principal conventions as the local model and is
covered by round-trip tests; adjust the task field names here if the live task
schema differs.

Pure functions, no IO.
"""

from __future__ import annotations

from typing import Any

# --- small helpers ----------------------------------------------------------- #

def _prov_from_weve(p: dict[str, Any] | None) -> dict[str, Any]:
    """WeveNova Provenance -> local provenance (``source``/``addedBy``/``addedAt``)."""
    p = p or {}
    added_by: dict[str, Any] = {}
    oid = p.get("AddedById") or p.get("ProducedById")
    if oid:
        added_by = {"oid": oid}
    return {
        "source": p.get("Source", ""),
        "addedBy": added_by,
        "addedAt": p.get("AddedAt") or p.get("ProducedAt") or "",
    }


def _prov_to_weve(p: dict[str, Any] | None) -> dict[str, Any]:
    """Local provenance -> WeveNova Provenance (best-effort; server stamps its own)."""
    p = p or {}
    out: dict[str, Any] = {"Source": p.get("source", "")}
    oid = (p.get("addedBy") or {}).get("oid")
    if oid:
        out["AddedById"] = oid
    if p.get("addedAt"):
        out["AddedAt"] = p["addedAt"]
    return out


# --- context ----------------------------------------------------------------- #

def context_from_weve(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": entry.get("Key", ""),
        "value": entry.get("Value"),
        "group": entry.get("Group", "") or "",
        "description": entry.get("Description", "") or "",
        "provenance": _prov_from_weve(entry.get("Provenance")),
    }


def context_to_weve(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "Key": entry.get("key", ""),
        "Value": entry.get("value"),
        "Group": entry.get("group", "") or "",
        "Description": entry.get("description", "") or "",
        "Provenance": _prov_to_weve(entry.get("provenance")),
    }


# --- outputs (PlanArtifact) -------------------------------------------------- #

def output_from_weve(art: dict[str, Any]) -> dict[str, Any]:
    """WeveNova Output -> local PlanArtifact. ``Attributes`` (list of
    ``{Key,Value,…}``) collapses to the local flat ``attributes`` dict."""
    attributes: dict[str, Any] = {}
    for a in art.get("Attributes", []) or []:
        if isinstance(a, dict) and a.get("Key") is not None:
            attributes[a["Key"]] = a.get("Value")
    return {
        "key": art.get("Key", ""),
        "kind": art.get("Kind", ""),
        "attributes": attributes,
        "inventoryRef": art.get("InventoryRef", "") or "",
        "producedByTaskId": art.get("ProducedByTaskId", "") or "",
        "provenance": _prov_from_weve(art.get("Provenance")),
        "state": art.get("State", "Active") or "Active",
    }


def output_to_weve(art: dict[str, Any]) -> dict[str, Any]:
    """Local PlanArtifact -> WeveNova Output. The flat ``attributes`` dict
    expands to the ``Attributes`` list of ``{Key,Value}`` records."""
    attributes = [
        {"Key": k, "Value": v} for k, v in (art.get("attributes") or {}).items()
    ]
    return {
        "Key": art.get("key", ""),
        "Kind": art.get("kind", ""),
        "InventoryRef": art.get("inventoryRef", "") or "",
        "ProducedByTaskId": art.get("producedByTaskId", "") or "",
        "State": art.get("state", "Active") or "Active",
        "Attributes": attributes,
        "Provenance": _prov_to_weve(art.get("provenance")),
    }


# The kinds the ``complete_project_plan_task`` tool accepts for a produced output.
# The local ledger is richer (``ARTIFACT_KINDS``); kinds outside this enum
# (``EntraApp``, ``Agent``) fold to ``Custom`` on the wire — the local plan keeps
# the precise kind.
COMPLETION_KINDS = ("Custom", "Environment", "Connection", "KnowledgeSource")


def output_to_completion(art: dict[str, Any]) -> dict[str, Any]:
    """Local PlanArtifact -> the **completion-output** shape required by
    ``complete_project_plan_task`` (MCP 5.6.0). This is a *reduced, camelCase*
    projection distinct from :func:`output_to_weve`'s plan-level PascalCase
    ``Output``: only ``{key, kind, attributes[, inventoryRef]}`` where ``kind`` is
    clamped to :data:`COMPLETION_KINDS` and ``attributes`` is a list of
    ``{key, value}`` records (the tool requires a ``value`` key, so a ``None``
    value is preserved, not dropped). Outputs are only persisted to WeveNova at
    task completion, so this is the sole mapper that pushes them upstream."""
    kind = art.get("kind", "") or ""
    completion: dict[str, Any] = {
        "key": art.get("key", ""),
        "kind": kind if kind in COMPLETION_KINDS else "Custom",
        "attributes": [
            {"key": k, "value": v} for k, v in (art.get("attributes") or {}).items()
        ],
    }
    inventory_ref = art.get("inventoryRef") or ""
    if inventory_ref:
        completion["inventoryRef"] = inventory_ref
    return completion


# --- tasks ------------------------------------------------------------------- #
# WeveNova assignment is carried by two flat scalars — ``AssignedToId`` and
# ``AssignedToRoleId`` — plus a read-only expanded ``AssignedTo`` object that
# names the ``Type`` (``User`` | ``Role``). The **writable** shape adds
# ``AssignedToType`` (spec §3): a *pooled* role task is
# ``AssignedToType=Role, AssignedToId=<roleId>, AssignedToRoleId=<roleId>``; a
# task *claimed by a person but still grounded on a role* is
# ``AssignedToType=User, AssignedToId=<oid>, AssignedToRoleId=<roleId>``. There is
# no ``Checklist`` field on the task (the local read-back-only checklist is client
# display state and is dropped on sync).

def task_from_weve(t: dict[str, Any]) -> dict[str, Any]:
    """WeveNova Task -> local task. ``TaskId`` becomes the local ``id``. The
    assignee type is resolved from the expanded ``AssignedTo`` object, else the
    ``AssignedToType`` scalar, else inferred from the scalars (a pooled task's
    ``AssignedToId`` equals its ``AssignedToRoleId``)."""
    from planner.plan_model import principal_person, principal_pool

    role_id = t.get("AssignedToRoleId")
    user_oid = t.get("AssignedToId")
    atype: str | None = None

    at = t.get("AssignedTo")
    if isinstance(at, dict) and at.get("Type"):
        atype = at.get("Type")
        expanded_role = at.get("Role")
        if isinstance(expanded_role, dict):
            role_id = role_id or expanded_role.get("RoleId")
        if atype == "User":
            user_oid = user_oid or at.get("Id")
        elif atype == "Role":
            role_id = role_id or at.get("Id")
    if not atype:
        atype = t.get("AssignedToType")

    if atype == "Role":
        assigned = principal_pool(role_id) if role_id else {}
    elif atype == "User":
        assigned = principal_person(user_oid, role_id=role_id or None) if user_oid else {}
    elif user_oid and role_id and user_oid == role_id:  # type-less pooled
        assigned = principal_pool(role_id)
    elif user_oid:
        assigned = principal_person(user_oid, role_id=role_id or None)
    elif role_id:
        assigned = principal_pool(role_id)
    else:
        assigned = {}

    return {
        "id": t.get("TaskId") or t.get("Id") or "",
        "title": t.get("Title", "") or "",
        "description": t.get("Description", "") or "",
        "assignedTo": assigned,
        "state": t.get("State", "NotStarted") or "NotStarted",
        "produces": list(t.get("Produces") or []),
        "consumes": list(t.get("Consumes") or []),
    }


def task_to_weve(task: dict[str, Any], *, include_id: bool = True) -> dict[str, Any]:
    """Local task -> WeveNova Task body (the writable projection). Emits the
    spec-§3 assignment scalars: ``AssignedToType`` (``Role``/``User``/``None``),
    ``AssignedToId`` (the role id when pooled, the person oid when claimed), and
    the grounding ``AssignedToRoleId``. Omit the id for a create (the server
    assigns ``TaskId``)."""
    from planner.plan_model import assignee_role_id, assignee_user_oid

    assigned = task.get("assignedTo") or {}
    atype = assigned.get("type")  # "Role" | "User" | None
    role_id = assignee_role_id(assigned)
    user_oid = assignee_user_oid(assigned)
    if atype == "Role":
        assigned_id: str | None = role_id
    elif atype == "User":
        assigned_id = user_oid
    else:
        assigned_id = None

    body: dict[str, Any] = {
        "Title": task.get("title", "") or "",
        "Description": task.get("description", "") or "",
        "State": task.get("state", "NotStarted") or "NotStarted",
        "Produces": list(task.get("produces") or []),
        "Consumes": list(task.get("consumes") or []),
        "AssignedToType": atype,
        "AssignedToId": assigned_id,
        "AssignedToRoleId": role_id,
    }
    if include_id and task.get("id"):
        body["TaskId"] = task["id"]
    return body


# --- plan (top level) -------------------------------------------------------- #

# The local model keeps the plan's acceptance criteria as context entries in this
# group; WeveNova promotes them to a top-level ``AcceptanceCriteria`` string list.
ACCEPTANCE_GROUP = "acceptanceCriteria"


def plan_from_weve(doc: dict[str, Any], *, tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A WeveNova project-plan document (+ optional task list) -> the local
    ``Plan.data`` dict. ``AcceptanceCriteria`` folds into context entries so the
    local model round-trips it without a bespoke field."""
    context = [context_from_weve(c) for c in doc.get("Context", []) or []]
    for crit in doc.get("AcceptanceCriteria", []) or []:
        context.append(
            {
                "key": f"{ACCEPTANCE_GROUP}:{crit}",
                "value": crit,
                "group": ACCEPTANCE_GROUP,
                "description": "",
                "provenance": {"source": "User", "addedBy": {}, "addedAt": ""},
            }
        )
    return {
        "schemaVersion": 1,
        "planId": doc.get("PlanId", "") or "",
        "projectId": doc.get("ProjectId", "") or "",
        "status": doc.get("Status", "Draft") or "Draft",
        "etag": doc.get("ETag", "") or "",
        "context": context,
        "tasks": list(tasks or []),
        "outputs": [output_from_weve(o) for o in doc.get("Outputs", []) or []],
    }


def acceptance_criteria_from_plan(plan_data: dict[str, Any]) -> list[str]:
    """The acceptance-criteria strings a WeveNova plan would carry, read back out
    of the local context bag."""
    return [
        e.get("value")
        for e in plan_data.get("context", [])
        if e.get("group") == ACCEPTANCE_GROUP and e.get("value")
    ]


def plan_fields_to_weve(plan_data: dict[str, Any]) -> dict[str, Any]:
    """The **writable plan-level projection** pushed back to WeveNova via the
    ``update_project_plan`` tool: the ``Context`` bag (PascalCase) **minus** the
    acceptance-criteria entries, which travel in their own ``AcceptanceCriteria``
    string list (they are folded *into* context on read by :func:`plan_from_weve`,
    so they must be split back *out* on write to avoid duplicating them).

    Outputs are intentionally excluded — WeveNova records those when a task
    completes, not through a plan-level context write. The inverse of the
    ``Context``/``AcceptanceCriteria`` halves of :func:`plan_from_weve`, so a
    plan read then written unchanged round-trips to an equal projection (used to
    skip no-op ``update_project_plan`` calls)."""
    context = [
        context_to_weve(e)
        for e in plan_data.get("context", [])
        if e.get("group") != ACCEPTANCE_GROUP
    ]
    return {
        "Context": context,
        "AcceptanceCriteria": acceptance_criteria_from_plan(plan_data),
    }
