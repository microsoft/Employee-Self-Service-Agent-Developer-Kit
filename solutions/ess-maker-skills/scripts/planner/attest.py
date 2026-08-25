# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: the role-attestation seam over the ``weve-plan`` MCP
server.

A *task* can be grounded on a **role** ("whoever holds the Workday
Administrator"); an **attestation** is the human-confirmed claim that binds a
named **person** to that role, scoped to a **plan**. This module is the thin
client the role skill drives to:

  * **attest** a person to a role on the plan (``attest_plan_role``),
  * **list** / **read** the plan's role assignments
    (``list_plan_role_assignments`` / ``get_role_assignment``),
  * **revoke** an assignment (``revoke_role_assignment``), and
  * list the tasks visible to a person once they log in — their directly
    assigned tasks **plus** the pooled tasks for the roles they hold
    (``list_project_plan_tasks_for_caller``).

Everything is validated **locally first** against the role registry
(:data:`planner.roles.DEFAULT_REGISTRY`) so a bad role/provider/oid is caught
with a friendly nudge before the server round-trip, mirroring WeveNova's own
``ValidateAttestationRequest`` rules:

  * ``subjectId`` — the *person's* Entra object id (an OID GUID). Required.
  * ``role`` — must be a registered **attestable** role (exact wire id).
  * ``provider`` — must be the role's owner (``External`` / ``Entra`` /
    ``PowerPlatform``); a right-role / wrong-provider pair is rejected.
  * attestations are **Plan-scoped** (the plan id is supplied here).

The attesting user's identity (tenant + who is attesting) comes from the request
context on the server, never the body — this client only says *who the role
belongs to* (``subjectId``) and *which role/plan*.

The attestation tools key off ``tenantId`` + ``planId``; the caller-task tool
keys off ``projectId`` + ``planId`` (see :mod:`planner.plan_store`
``resolve_plan_binding`` for how the binding is discovered).
"""

from __future__ import annotations

import re
from typing import Any

from planner.mcp_client import McpClient, McpError
from planner.roles import DEFAULT_REGISTRY, RoleDef, RoleRegistry

# An Entra object id is a canonical GUID.
_OID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class AttestationError(RuntimeError):
    """A role attestation was rejected by local validation or the server."""


def is_oid(value: str | None) -> bool:
    """True iff ``value`` is a canonical Entra object-id GUID."""
    return bool(value) and bool(_OID_RE.match(value.strip()))


def validate_attestation(
    subject_id: str,
    role: str,
    provider: str | None = None,
    *,
    registry: RoleRegistry = DEFAULT_REGISTRY,
) -> tuple[str, str]:
    """Validate an attestation request locally and return the canonical
    ``(role_id, provider)`` to send.

    Mirrors the server's ``ValidateAttestationRequest``:

      * ``subject_id`` must be an OID GUID,
      * ``role`` must resolve (free text is accepted via
        :meth:`RoleRegistry.find`) to a **registered attestable** role,
      * ``provider`` (when supplied) must **own** that role; when omitted it is
        derived from the registry.

    Raises :class:`AttestationError` with a field-targeted, re-promptable message.
    """
    if not is_oid(subject_id):
        raise AttestationError(
            "subjectId must be the person's Entra object id (a GUID), e.g. "
            "'11111111-2222-3333-4444-555555555555'."
        )
    resolved: RoleDef | None = registry.find(role)
    if resolved is None or not resolved.attestable:
        allowed = ", ".join(registry.allowed_attestable_names())
        raise AttestationError(f"role must be one of {allowed}.")
    owner = resolved.provider
    if provider is None:
        provider = owner
    elif provider != owner:
        raise AttestationError(
            f"role is not owned by the supplied provider. '{resolved.role}' is owned "
            f"by '{owner}', not '{provider}'."
        )
    return resolved.role, provider


class AttestationClient:
    """Drives the plan role-assignment + caller-task tools for one plan.

    ``tenant_id`` is needed by the attestation tools (attest/list/get/revoke);
    ``project_id`` + ``plan_id`` are needed by the caller-task tool. Build the
    binding with :func:`planner.plan_store.resolve_plan_binding`.
    """

    def __init__(
        self,
        client: McpClient,
        *,
        plan_id: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
        registry: RoleRegistry = DEFAULT_REGISTRY,
    ) -> None:
        if not plan_id:
            raise AttestationError("plan_id is required for role attestations.")
        self.client = client
        self.plan_id = plan_id
        self.tenant_id = tenant_id
        self.project_id = project_id
        self.registry = registry

    def _require_tenant(self) -> str:
        if not self.tenant_id:
            raise AttestationError(
                "tenant_id is required for role attestations but could not be "
                "resolved — set PLANNER_MCP_TENANT_ID or pass it explicitly."
            )
        return self.tenant_id

    def _require_project(self) -> str:
        if not self.project_id:
            raise AttestationError(
                "project_id is required to list a caller's tasks but could not be "
                "resolved — set PLANNER_MCP_PROJECT_ID or pass it explicitly."
            )
        return self.project_id

    # -- attest / read / revoke ------------------------------------------ #

    def attest(
        self,
        subject_id: str,
        role: str,
        *,
        provider: str | None = None,
        idempotency_key: str | None = None,
        etag: str | None = None,
    ) -> dict[str, Any]:
        """Attest ``subject_id`` (a person's OID) to ``role`` on this plan.

        The role is validated (and resolved from free text) against the registry
        and the provider is derived/checked before the call. Idempotent — the
        server returns the existing assignment when the deterministic one already
        exists."""
        if etag and etag.strip().startswith("W/"):
            raise AttestationError(
                "attestation etag must be an existing role assignment's strong "
                "ETag. Omit it for a first attestation; never pass the plan ETag."
            )
        role_id, prov = validate_attestation(subject_id, role, provider, registry=self.registry)
        args: dict[str, Any] = {
            "tenantId": self._require_tenant(),
            "planId": self.plan_id,
            "subjectId": subject_id.strip(),
            "role": role_id,
            "provider": prov,
        }
        if etag:
            args["etag"] = etag
        if idempotency_key:
            args["idempotencyKey"] = idempotency_key
        try:
            result = self.client.call_tool("attest_plan_role", args)
        except McpError as exc:
            raise AttestationError(f"attest failed: {exc}") from exc
        record = result if isinstance(result, dict) else {"result": result}
        try:
            verified = self.list_assignments(
                subject_id=subject_id.strip(), role=role_id, status="Active"
            )
        except AttestationError as exc:
            raise AttestationError(
                "attestation response returned, but persistence could not be "
                f"verified; do not report success or retry blindly: {exc}"
            ) from exc
        if not verified:
            raise AttestationError(
                "attestation response returned, but no matching Active assignment "
                "was found. Do not report the role as assigned."
            )
        return {**verified[0], **record}

    def list_assignments(
        self,
        *,
        subject_id: str | None = None,
        role: str | None = None,
        status: str | None = None,
        top: int | None = None,
        orderby: str | None = None,
        skiptoken: str | None = None,
    ) -> list[dict[str, Any]]:
        """List this plan's role assignments (optionally filtered)."""
        args: dict[str, Any] = {"tenantId": self._require_tenant(), "planId": self.plan_id}
        if subject_id:
            args["subjectId"] = subject_id
        if role:
            resolved = self.registry.find(role)
            args["role"] = resolved.role if resolved else role
        if status:
            args["status"] = status
        if top is not None:
            args["top"] = top
        if orderby:
            args["orderby"] = orderby
        if skiptoken:
            args["skiptoken"] = skiptoken
        try:
            payload = self.client.call_tool("list_plan_role_assignments", args)
        except McpError as exc:
            raise AttestationError(f"list role assignments failed: {exc}") from exc
        return _odata_items(payload)

    def get_assignment(self, assignment_id: str) -> dict[str, Any]:
        try:
            result = self.client.call_tool(
                "get_role_assignment",
                {"tenantId": self._require_tenant(), "assignmentId": assignment_id},
            )
        except McpError as exc:
            raise AttestationError(f"get role assignment failed: {exc}") from exc
        return result if isinstance(result, dict) else {"result": result}

    def revoke(self, assignment_id: str, *, etag: str | None = None) -> dict[str, Any]:
        """Revoke (soft-revoke) a role assignment on this plan."""
        if not etag:
            current = self.get_assignment(assignment_id)
            etag = (
                current.get("ETag")
                or current.get("etag")
                or current.get("@odata.etag")
            )
        if not etag:
            raise AttestationError(
                "the current role assignment read returned no ETag; refusing an "
                "unsafe revoke."
            )
        args: dict[str, Any] = {"tenantId": self._require_tenant(), "assignmentId": assignment_id}
        args["etag"] = etag
        try:
            result = self.client.call_tool("revoke_role_assignment", args)
        except McpError as exc:
            raise AttestationError(f"revoke role assignment failed: {exc}") from exc
        return result if isinstance(result, dict) else {"result": result}

    # -- hand the role's pooled tasks to the newly-attested person ------- #

    def assign_role_pool_to_subject(
        self, subject_id: str, role_id: str
    ) -> list[dict[str, Any]]:
        """After attesting ``subject_id`` to ``role_id``, hand them the role's
        still-**open pooled** tasks on this plan (pool → claimed; the grounding
        role is retained so the task still groups under it in Flow 2).

        Only tasks that are an **open role pool** grounded on *exactly* this role
        are taken. A task already owned by a person (even one grounded on the same
        role) is left untouched, so an existing owner is never displaced and a
        second holder attested later simply finds an empty pool. Returns the tasks
        reassigned (``{TaskId, Title}``); an empty list means nothing was pooled
        for the role.

        Each mutation reads the task's current ETag from a direct GET immediately
        before the ``update_project_plan_task`` PATCH (WeveNova requires If-Match);
        an ETag conflict is re-read and retried once."""
        from planner import weve_mapping as wm
        from planner.plan_model import assignee_role_id

        args: dict[str, Any] = {"projectId": self._require_project(), "planId": self.plan_id}
        try:
            payload = self.client.call_tool("list_project_plan_tasks", args)
        except McpError as exc:
            raise AttestationError(
                f"attested, but could not list tasks to assign the role's pool: {exc}"
            ) from exc

        assigned: list[dict[str, Any]] = []
        for raw in _odata_items(payload):
            local = wm.task_from_weve(raw)
            who = local.get("assignedTo") or {}
            # Open pool for *this* role only — never touch a person-owned task.
            if who.get("type") != "Role" or assignee_role_id(who) != role_id:
                continue
            tid = local.get("id")
            if not tid:
                continue
            self._reassign_task_to_person(tid, subject_id, role_id)
            assigned.append({"TaskId": tid, "Title": local.get("title", "")})
        return assigned

    def _reassign_task_to_person(self, task_id: str, subject_id: str, role_id: str) -> None:
        """Claim one pooled task for ``subject_id`` by PATCHing **only**
        ``AssignedToId`` to their AAD id — the ``update_project_plan_task`` schema
        is additionalProperties:false and accepts assignment solely through
        ``AssignedToId``; the grounding ``AssignedToRoleId`` stays unchanged
        server-side (``role_id`` is kept only for the caller's reporting). Reads a
        fresh ETag before the write and retries once on an ETag conflict."""
        patch = {"AssignedToId": subject_id}
        ids = {"projectId": self._require_project(), "planId": self.plan_id, "taskId": task_id}
        for attempt in (1, 2):
            etag = self._task_etag(task_id)
            try:
                self.client.call_tool(
                    "update_project_plan_task", {**ids, "patch": patch, "etag": etag}
                )
                return
            except McpError as exc:
                if attempt == 1 and _is_etag_conflict(exc):
                    continue
                raise AttestationError(
                    f"attested, but could not assign task {task_id} to the person: {exc}"
                ) from exc

    def _task_etag(self, task_id: str) -> str:
        """The current strong ETag of a task, from its direct GET (used as
        If-Match on the very next mutation — never a list-response ETag)."""
        try:
            cur = self.client.call_tool(
                "get_project_plan_task",
                {"projectId": self._require_project(), "planId": self.plan_id, "taskId": task_id},
            )
        except McpError as exc:
            raise AttestationError(
                f"attested, but could not read task {task_id} to assign it: {exc}"
            ) from exc
        etag = None
        if isinstance(cur, dict):
            etag = cur.get("ETag") or cur.get("etag") or cur.get("@odata.etag")
        if not etag:
            raise AttestationError(
                f"attested, but task {task_id} returned no ETag; refusing an unsafe assign."
            )
        return etag

    # -- caller tasks (Flow 2) ------------------------------------------- #

    def tasks_for_caller(
        self, caller_id: str, *, odata_filter: str | None = None
    ) -> list[dict[str, Any]]:
        """The tasks a logged-in person sees: their directly-assigned tasks
        **plus** the pooled tasks for every role they are attested to on this
        plan (``list_project_plan_tasks_for_caller``).

        ``caller_id`` **must be the authenticated caller's own Entra object id**
        — the identity the ``weve-plan`` tunnel token signs in as. WeveNova reads
        ``callerId`` as a *self-scope sentinel* (equivalent to the OData
        ``$filter=assignedToId eq '<callerId>'`` marker the server intercepts):
        it strips that predicate and expands the caller's attested roles into
        their pooled tasks. This is **self-only** — passing a *different* person's
        OID (any OID other than the authenticated caller's own) is treated as an
        ordinary literal filter and returns **none** of the role-pooled work, so
        it must not be used to answer "what is *that* person assigned?".

        A plain ``list_project_plan_tasks`` (no ``callerId``) returns *all* tasks
        on the plan — role scoping is opt-in via this sentinel, never implicit.

        ``odata_filter`` is sent as an **additional** ``$filter`` (WeveNova's
        ``query.filter`` option). The caller scope is applied by the server from
        ``callerId`` — do **not** repeat the ``assignedToId`` predicate here (the
        parser rejects a duplicated caller term)."""
        args: dict[str, Any] = {
            "projectId": self._require_project(),
            "planId": self.plan_id,
            "callerId": caller_id,
        }
        if odata_filter:
            # ``query`` is an OData-options object per the tool schema, not a
            # bare string — the $filter goes under ``query.filter``.
            args["query"] = {"filter": odata_filter}
        try:
            payload = self.client.call_tool("list_project_plan_tasks_for_caller", args)
        except McpError as exc:
            raise AttestationError(f"list caller tasks failed: {exc}") from exc
        return _odata_items(payload)


def _odata_items(payload: Any) -> list[dict[str, Any]]:
    """Normalise an OData ``{value:[...]}`` collection (or a bare list) to a list
    of dict rows."""
    if isinstance(payload, dict):
        items = payload.get("value", payload.get("Value", []))
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    return [i for i in items if isinstance(i, dict)]


def _is_etag_conflict(exc: McpError) -> bool:
    """True when a mutation failed the If-Match precondition (a stale ETag),
    which is safe to re-read and retry once — as opposed to a lifecycle refusal."""
    text = str(exc).casefold()
    return (
        "preconditionfailed" in text
        or "precondition failed" in text
        or ("etag" in text and ("conflict" in text or "if-match" in text))
    )
