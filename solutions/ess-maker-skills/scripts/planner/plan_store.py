# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Planner: the Plan persistence seam (local file vs WeveNova MCP).

The planner reads and writes the Plan through a **store**. Two implementations:

  * :class:`LocalPlanStore` — the default. ``plan.json`` on disk plus the
    rendered ``ESS-scenario-plan.md`` beside it (the original behaviour).
  * :class:`McpPlanStore` — persists to a **WeveNova project plan** over the
    ``weve-plan`` MCP server instead of ``plan.json``: it reads the plan +
    project + tasks from WeveNova and reconciles task changes back to it. The
    human ``ESS-scenario-plan.md`` view is still rendered locally.

Both stores validate the Plan before persisting and always (re)render the
Markdown view, so the ``.md`` file is present regardless of backend.

WeveNova today exposes **task** CRUD plus a read of the plan (context, outputs,
status, acceptance criteria). Plan-level context/outputs are therefore read from
WeveNova and reflected in the ``.md``; task create/update/delete are persisted.
When a plan-level edit can't be pushed (no upstream plan-update operation), the
store says so rather than silently dropping it.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from planner import weve_mapping as wm
from planner.mcp_client import McpClient, McpError, client_from_config
from planner.plan_model import SUMMARY_FILENAME, Plan


class PlanStoreError(RuntimeError):
    """A store could not load or persist the plan."""


class PlanStore(Protocol):
    def load(self) -> Plan: ...
    def save(self, plan: Plan) -> list[str]: ...
    @property
    def summary_path(self) -> str: ...


def _summary_beside(plan_path: str) -> str:
    return os.path.join(os.path.dirname(plan_path) or ".", SUMMARY_FILENAME)


class LocalPlanStore:
    """The default file-backed store: ``plan.json`` + ``ESS-scenario-plan.md``."""

    def __init__(self, plan_path: str) -> None:
        self.plan_path = plan_path

    @property
    def summary_path(self) -> str:
        return _summary_beside(self.plan_path)

    def load(self) -> Plan:
        return Plan.load_or_new(self.plan_path)

    def save(self, plan: Plan) -> list[str]:
        """Validate then atomically write ``plan.json`` and re-render the ``.md``.
        Returns any non-fatal notices (none for the local store)."""
        plan.save_all(self.plan_path)
        return []


class McpPlanStore:
    """A WeveNova-backed store over the ``weve-plan`` MCP server — the **source
    of truth** for the plan of the project/agent being configured.

    WeveNova is authoritative: ``load`` always **fetches** the plan (context,
    outputs, status, acceptance criteria) and its tasks from WeveNova; ``save``
    reconciles task changes back to WeveNova and then renders the human
    ``ESS-scenario-plan.md`` **from the re-fetched WeveNova state**. A local
    ``plan.json`` is written only as an optional cache/mirror (``cache_path``) —
    never read as truth.
    """

    def __init__(
        self,
        client: McpClient,
        summary_path: str,
        *,
        project_id: str,
        plan_id: str,
        tenant_id: str | None = None,
        cache_path: str | None = None,
    ) -> None:
        if not project_id or not plan_id:
            raise PlanStoreError(
                "the WeveNova store is multi-plan: both project_id and plan_id are "
                "required (resolve via make_store / resolve_plan_binding)."
            )
        self.client = client
        self._summary_path = summary_path
        self.project_id = project_id
        self.plan_id = plan_id
        self.tenant_id = tenant_id
        self.cache_path = cache_path
        self.warnings: list[str] = []
        try:
            self.lifecycle_rules = client.lifecycle_rules()
        except McpError as exc:
            raise PlanStoreError(
                f"cannot load the live WeveNova lifecycle rules: {exc}"
            ) from exc

    @property
    def summary_path(self) -> str:
        return self._summary_path

    def _ids(self) -> dict[str, str]:
        """The ``projectId``/``planId`` pair every 3.x plan/task tool now requires."""
        return {"projectId": self.project_id, "planId": self.plan_id}

    def _cache(self, plan: Plan) -> None:
        """Mirror the authoritative WeveNova plan to a local ``plan.json`` cache
        (best-effort; the cache is never the source of truth)."""
        if self.cache_path:
            try:
                plan.save(self.cache_path)
            except OSError:
                pass

    # -- read ------------------------------------------------------------- #

    def _list_tasks(self) -> list[dict[str, Any]]:
        raw = self.client.call_tool("list_project_plan_tasks", self._ids())
        # OData collections come back as {"value": [...]}, but tolerate a bare list.
        if isinstance(raw, dict):
            items = raw.get("value", raw.get("Value", []))
        elif isinstance(raw, list):
            items = raw
        else:
            items = []
        return [wm.task_from_weve(t) for t in items if isinstance(t, dict)]

    def load(self) -> Plan:
        """Fetch the authoritative plan (+ tasks) from WeveNova and mirror it to
        the local cache. WeveNova is always the source read here — never the
        local cache."""
        self.warnings = []
        try:
            doc = self.client.call_tool("get_project_plan", self._ids())
        except McpError as exc:
            raise PlanStoreError(f"cannot read the WeveNova project plan: {exc}") from exc
        if not isinstance(doc, dict):
            raise PlanStoreError(f"unexpected project-plan payload: {doc!r:.120}")
        try:
            tasks = self._list_tasks()
        except McpError as exc:
            # The plan itself read fine — degrade to a plan-level view with no
            # tasks and warn, rather than making MCP mode unusable while the
            # tasks collection is unavailable. ``save`` re-lists independently and
            # refuses to reconcile (never deletes) if it still can't read tasks.
            self.warnings.append(
                f"WeveNova tasks unavailable ({exc}); showing plan context/outputs only. "
                "Task changes will not persist until the tasks endpoint is reachable."
            )
            tasks = []
        plan = Plan(wm.plan_from_weve(doc, tasks=tasks))
        self._cache(plan)
        return plan

    # -- write ------------------------------------------------------------ #

    def _list_tasks_raw(self) -> dict[str, dict[str, Any]]:
        """Server tasks as ``{TaskId: raw WeveNova task}`` for change detection."""
        raw = self.client.call_tool("list_project_plan_tasks", self._ids())
        if isinstance(raw, dict):
            items = raw.get("value", raw.get("Value", []))
        elif isinstance(raw, list):
            items = raw
        else:
            items = []
        out: dict[str, dict[str, Any]] = {}
        for t in items:
            if isinstance(t, dict):
                tid = t.get("TaskId") or t.get("Id")
                if tid:
                    out[tid] = t
        return out

    def _get_plan_raw(self) -> dict[str, Any]:
        try:
            raw = self.client.call_tool("get_project_plan", self._ids())
        except McpError as exc:
            raise PlanStoreError(f"cannot read the current WeveNova plan: {exc}") from exc
        if not isinstance(raw, dict):
            raise PlanStoreError(f"unexpected project-plan payload: {raw!r:.120}")
        return raw

    def _get_task_raw(self, tid: str) -> dict[str, Any]:
        try:
            raw = self.client.call_tool(
                "get_project_plan_task", {**self._ids(), "taskId": tid}
            )
        except McpError as exc:
            raise PlanStoreError(
                f"cannot read current task {tid} before mutation: {exc}"
            ) from exc
        if not isinstance(raw, dict):
            raise PlanStoreError(f"unexpected task payload for {tid}: {raw!r:.120}")
        return raw

    @staticmethod
    def _etag(raw: dict[str, Any] | None) -> str | None:
        """The current entity ETag the mutating tools require as If-Match."""
        if not isinstance(raw, dict):
            return None
        return raw.get("ETag") or raw.get("etag") or raw.get("@odata.etag")

    @classmethod
    def _required_etag(cls, raw: dict[str, Any], entity: str) -> str:
        etag = cls._etag(raw)
        if not etag:
            raise PlanStoreError(
                f"the direct WeveNova read for {entity} returned no ETag; refusing "
                "an unsafe mutation."
            )
        return etag

    @staticmethod
    def _is_etag_conflict(exc: McpError) -> bool:
        text = str(exc).casefold()
        return (
            "preconditionfailed" in text
            or "precondition failed" in text
            or ("etag" in text and ("conflict" in text or "if-match" in text))
        )

    def _mutate_task(
        self, tool: str, tid: str, arguments: dict[str, Any]
    ) -> Any:
        """Mutate a task with its direct-read ETag; retry once only for ETag conflict."""
        for attempt in range(2):
            current = self._get_task_raw(tid)
            etag = self._required_etag(current, f"task {tid}")
            try:
                return self.client.call_tool(
                    tool, {**self._ids(), "taskId": tid, **arguments, "etag": etag}
                )
            except McpError as exc:
                if attempt == 0 and self._is_etag_conflict(exc):
                    continue
                raise
        raise AssertionError("unreachable")

    def _mutate_plan(self, patch: dict[str, Any]) -> Any:
        """Patch the plan with a direct-read ETag; retry once only for ETag conflict."""
        for attempt in range(2):
            current = self._get_plan_raw()
            etag = self._required_etag(current, f"plan {self.plan_id}")
            try:
                return self.client.call_tool(
                    "update_project_plan",
                    {**self._ids(), "patch": patch, "etag": etag},
                )
            except McpError as exc:
                if attempt == 0 and self._is_etag_conflict(exc):
                    continue
                raise
        raise AssertionError("unreachable")

    def _require_active_plan(self) -> None:
        plan = self._get_plan_raw()
        status = plan.get("Status") or plan.get("status")
        if status != "Active":
            owner = plan.get("OwnedById") or plan.get("ownedById") or "the plan owner"
            rule = self.lifecycle_rules.get("planActivationRule", "")
            suffix = f" {rule}" if rule else ""
            raise PlanStoreError(
                f"cannot change task state while plan {self.plan_id} is {status!r}. "
                f"It must be activated by {owner} before task execution.{suffix}"
            )

    def activate(self) -> dict[str, Any]:
        """Activate this plan as its resource owner and return the verified plan."""
        current = self._get_plan_raw()
        status = current.get("Status") or current.get("status")
        if status == "Active":
            return current
        try:
            self._mutate_plan({"Status": "Active"})
        except McpError as exc:
            raise PlanStoreError(f"cannot activate the WeveNova plan: {exc}") from exc
        verified = self._get_plan_raw()
        verified_status = verified.get("Status") or verified.get("status")
        if verified_status != "Active":
            raise PlanStoreError(
                f"activation returned without error, but plan status is "
                f"{verified_status!r}; do not start tasks."
            )
        return verified

    def _create_task(self, body: dict[str, Any]) -> None:
        """Create a task on the plan. A **pooled role** task (``AssignedToType ==
        'Role'``) is created through the dedicated
        ``create_role_assigned_project_plan_task`` tool so the server grounds it on
        the role; everything else goes through the generic ``create_project_plan_task``.
        Creates are POSTs — no ETag/If-Match is required."""
        if body.get("AssignedToType") == "Role" and body.get("AssignedToRoleId"):
            self.client.call_tool(
                "create_role_assigned_project_plan_task",
                {
                    **self._ids(),
                    "role": body["AssignedToRoleId"],
                    "title": body.get("Title", ""),
                    "description": body.get("Description", ""),
                    "produces": list(body.get("Produces") or []),
                    "consumes": list(body.get("Consumes") or []),
                },
            )
        else:
            self.client.call_tool("create_project_plan_task", {**self._ids(), "task": body})

    # The only task fields ``update_project_plan_task`` accepts as a PATCH
    # (its schema is additionalProperties:false). Assignment is carried **only**
    # by ``AssignedToId`` — claiming a role pool is "set AssignedToId to the user";
    # ``AssignedToType``/``AssignedToRoleId`` are server-derived and must not be
    # sent. ``State`` is never patched here (the state/complete tools own it).
    _PATCHABLE_TASK_FIELDS = ("Title", "Description", "AssignedToId", "Produces", "Consumes")

    def _update_task(
        self,
        tid: str,
        body: dict[str, Any],
        current: dict[str, Any],
        *,
        completion_outputs: list[dict[str, Any]] | None = None,
    ) -> None:
        """Reconcile a changed task. The mutating tools require the current ETag
        as If-Match, so a single task is mutated **at most once per call where
        possible**: a content change is a single ``update_project_plan_task``
        PATCH (restricted to the schema-allowed fields); a lifecycle change goes
        through ``set_project_plan_task_state`` — **except** a transition to
        ``Completed`` for a task that produced outputs, which goes through
        ``complete_project_plan_task`` so the outputs are persisted with the same
        call (WeveNova only records outputs at completion). When *both* a content
        field and the state changed we PATCH first, then the state/complete helper
        directly re-reads the task before the second mutation. Every mutation uses
        a direct entity GET; list-response ETags are used only for change
        detection, never If-Match."""
        state_changed = body.get("State") != current.get("State")
        # Only the schema-allowed writable fields participate in the content PATCH;
        # send just the ones that actually changed (an empty diff -> no PATCH).
        patch = {
            k: body[k]
            for k in self._PATCHABLE_TASK_FIELDS
            if k in body and body.get(k) != current.get(k)
        }

        desired_state = body.get("State", "NotStarted")
        if state_changed:
            if desired_state not in {"NotStarted", "InProgress", "Completed", "Cancelled"}:
                raise PlanStoreError(
                    f"WeveNova does not support task state {desired_state!r}; use "
                    "NotStarted, InProgress, Completed, or Cancelled."
                )
            # Check before any content PATCH so a Draft plan cannot leave a
            # half-applied content+state update.
            self._require_active_plan()

        if patch:
            self._mutate_task("update_project_plan_task", tid, {"patch": patch})
        if state_changed:
            if desired_state == "Completed" and completion_outputs:
                self._complete_task_with_outputs(tid, completion_outputs)
            else:
                self._mutate_task(
                    "set_project_plan_task_state", tid, {"state": desired_state}
                )

    def _complete_task_with_outputs(
        self, tid: str, outputs: list[dict[str, Any]]
    ) -> None:
        """Complete a task **and persist its produced outputs in one bulk call**
        (``complete_project_plan_task`` carries the full outputs array — one call,
        not one per output, mirroring how plan context is pushed in a single
        ``update_project_plan``). WeveNova completes only from ``InProgress``, so a
        ``NotStarted`` task is moved to ``InProgress`` first (state-only). Each
        mutation reads the task's fresh direct ETag; an ETag conflict is retried
        once (via :meth:`_mutate_task`)."""
        current = self._get_task_raw(tid)
        state = current.get("State") or current.get("state") or "NotStarted"
        if state == "NotStarted":
            self._mutate_task("set_project_plan_task_state", tid, {"state": "InProgress"})
        self._mutate_task("complete_project_plan_task", tid, {"outputs": outputs})

    def _reconcile_plan_fields(self, plan: Plan) -> list[str]:
        """Push the plan-level **Context + AcceptanceCriteria** to WeveNova when
        they differ from the server, via ``update_project_plan`` carrying the
        plan's current ETag as If-Match. This makes the MCP store read-*write* for
        plan-level intent, not just tasks. Outputs are excluded (WeveNova pins
        those on task completion). It is a no-op when the projections already match
        — an unchanged save issues no write — and returns a soft notice (not an
        error) when the current plan can't be read to diff against."""
        try:
            server_doc = self.client.call_tool("get_project_plan", self._ids())
        except McpError as exc:
            return [f"plan context not synced (could not read the plan to diff: {exc})."]
        if not isinstance(server_doc, dict):
            return ["plan context not synced (unexpected project-plan payload)."]
        desired = wm.plan_fields_to_weve(plan.data)
        current = wm.plan_fields_to_weve(wm.plan_from_weve(server_doc))
        if desired == current:
            return []
        try:
            self._mutate_plan(desired)
        except McpError as exc:
            raise PlanStoreError(f"cannot persist plan context to WeveNova: {exc}") from exc
        return []

    def save(self, plan: Plan) -> list[str]:
        """Reconcile the plan's tasks to WeveNova, then render the ``.md``.

        Diff by task id against the live server set: a local task not on the
        server is **created** (pooled-role tasks through the role-assigned create
        tool); a local task whose writable fields differ from the server is
        **patched** (a pure state change via the dedicated state tool); unchanged
        tasks are left alone (no no-op writes); a server task no longer in the plan
        is **deleted**. The mutating tools require the current entity ETag as
        If-Match, which is read from the task's direct GET immediately before each
        mutation. A genuine ETag conflict is re-read and retried once; lifecycle
        conflicts are never retried. Plan-level
        **context + acceptance criteria are also reconciled** to WeveNova (via
        :meth:`_reconcile_plan_fields`); only Outputs remain upstream-owned (pinned
        on task completion) — a notice is returned when the local plan holds them.
        """
        notices: list[str] = []
        try:
            server = self._list_tasks_raw()
        except McpError as exc:
            raise PlanStoreError(f"cannot reconcile tasks (list failed): {exc}") from exc

        local_ids: set[str] = set()
        try:
            for task in plan.tasks:
                tid = task.get("id") or ""
                local_ids.add(tid)
                body = wm.task_to_weve(task, include_id=False)
                if tid in server:
                    # Only patch when the writable projection actually changed.
                    current = wm.task_to_weve(wm.task_from_weve(server[tid]), include_id=False)
                    if body != current:
                        direct = self._get_task_raw(tid)
                        current = wm.task_to_weve(
                            wm.task_from_weve(direct), include_id=False
                        )
                        if body != current:
                            # A task going Completed carries its produced outputs
                            # (Active only) so completion persists them upstream in
                            # one bulk call; WeveNova records outputs only here.
                            completion_outputs = (
                                [wm.output_to_completion(a)
                                 for a in plan.completion_outputs(tid)]
                                if body.get("State") == "Completed"
                                else None
                            )
                            self._update_task(
                                tid, body, current,
                                completion_outputs=completion_outputs,
                            )
                else:
                    self._create_task(body)
            for stale in set(server) - local_ids:
                self._mutate_task("delete_project_plan_task", stale, {})
        except (McpError, PlanStoreError) as exc:
            raise PlanStoreError(f"cannot persist tasks to WeveNova: {exc}") from exc

        # Plan-level context + acceptance criteria are read-write over MCP too:
        # push them when they differ from the server (a no-op when unchanged).
        notices.extend(self._reconcile_plan_fields(plan))

        # Outputs reach WeveNova only when their producing task completes (carried
        # by the completion call above), so surface any Active output still held
        # locally because its producer isn't Completed yet.
        pending = 0
        for art in plan.outputs:
            if art.get("state") != "Active":
                continue
            producer = plan.task(art.get("producedByTaskId", ""))
            if producer is None or producer.get("state") != "Completed":
                pending += 1
        if pending:
            notices.append(
                f"{pending} pinned output(s) are held locally and will be pushed to "
                "WeveNova when their producing task is marked Completed."
            )

        # WeveNova is the source of truth: render the human view (and refresh the
        # local cache) from the **re-fetched** authoritative plan — so the .md
        # reflects WeveNova (including any server-assigned task ids), not just the
        # in-memory copy. Fall back to the in-memory plan if the re-fetch fails.
        authoritative = plan
        try:
            authoritative = self.load()
            notices.extend(
                w for w in self.warnings if "unavailable" in w
            )
        except PlanStoreError:
            pass
        authoritative.write_summary(self._summary_path)
        self._cache(authoritative)
        return notices


def _odata_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        items = payload.get("value", payload.get("Value", []))
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    return [i for i in items if isinstance(i, dict)]


def resolve_project_binding(
    client: McpClient,
    *,
    project_id: str | None = None,
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Resolve just the ``(project_id, project, tenant_id)`` for the WeveNova
    agent-configuration project — **without** requiring a plan to exist yet.
    Precedence: explicit arg → ``PLANNER_MCP_PROJECT_ID`` env → discovery
    (``list_agent_configuration_projects`` must return exactly one, else the
    caller must disambiguate). ``tenant_id`` (needed by the role/attest tools) is
    taken from the resolved project when known.

    This is the seam that lets ``init`` bind a project and then create its *first*
    plan (:func:`open_or_create_mcp_plan`): plan discovery is deliberately not
    done here, so a project with no plan is not an error at this step."""
    project_id = project_id or os.environ.get("PLANNER_MCP_PROJECT_ID")
    tenant_id: str | None = os.environ.get("PLANNER_MCP_TENANT_ID")

    project: dict[str, Any] | None = None
    try:
        if project_id:
            got = client.call_tool("get_agent_configuration_project", {"projectId": project_id})
            project = got if isinstance(got, dict) else None
        else:
            projects = _odata_items(client.call_tool("list_agent_configuration_projects", {}))
            if not projects:
                raise PlanStoreError(
                    "no WeveNova agent-configuration project found — create one first "
                    "or set PLANNER_MCP_PROJECT_ID."
                )
            if len(projects) > 1:
                names = ", ".join(
                    f"{p.get('Name', '?')} ({p.get('ProjectId')})" for p in projects
                )
                raise PlanStoreError(
                    "multiple WeveNova projects found — set PLANNER_MCP_PROJECT_ID to one "
                    f"of: {names}"
                )
            project = projects[0]
            project_id = project.get("ProjectId")
    except McpError as exc:
        raise PlanStoreError(f"cannot resolve the WeveNova project: {exc}") from exc

    if project and not tenant_id:
        tenant_id = project.get("TenantId")
    if not project_id:
        raise PlanStoreError("could not resolve a WeveNova project_id binding.")
    return project_id, project, tenant_id


def find_existing_plan_id(
    client: McpClient,
    *,
    project_id: str,
    project: dict[str, Any] | None = None,
) -> str | None:
    """Return the project's existing plan id — its ``ActivePlanId`` when set, else
    its single plan — or ``None`` when the project has **no** plan yet. Raises when
    the project has several plans and none is active (the caller must pick one via
    ``PLANNER_MCP_PLAN_ID``). Unlike :func:`resolve_plan_binding`, "no plan" is a
    normal result here (``None``) rather than an error — it is the signal that
    ``init`` should create the first plan."""
    active = project.get("ActivePlanId") if project else None
    if active:
        return active
    try:
        plans = _odata_items(client.call_tool("list_project_plans", {"projectId": project_id}))
    except McpError as exc:
        raise PlanStoreError(f"cannot list plans for project {project_id}: {exc}") from exc
    if not plans:
        return None
    if len(plans) > 1:
        ids = ", ".join(str(p.get("PlanId")) for p in plans)
        raise PlanStoreError(
            "project has multiple plans — set PLANNER_MCP_PLAN_ID to one of: " + ids
        )
    return plans[0].get("PlanId")


def _plan_id_of(created: Any) -> str | None:
    """Pull the ``PlanId`` out of a ``create_project_plan`` payload, tolerating a
    bare plan doc, an OData ``{"value": {...}}`` envelope, a bare id string, or the
    lowercase ``planId`` the local mapping uses."""
    if isinstance(created, str):
        return created or None
    if isinstance(created, dict):
        inner = created.get("value") if isinstance(created.get("value"), dict) else created
        return inner.get("PlanId") or inner.get("planId") or inner.get("Id") or None
    return None


def create_project_plan(
    client: McpClient,
    *,
    project_id: str,
    objective: str | None = None,
) -> str:
    """Create a new plan for an existing WeveNova project and return its
    ``PlanId``. The live ``create_project_plan`` tool requires a ``{"projectId",
    "plan"}`` body where ``plan`` is a **WeveNova plan entity** — the top level is
    ``additionalProperties:false``, so a bare ``objective`` scalar (the shape this
    sent before) is rejected. The objective is therefore seeded as an
    ``objective`` **Context** entry — the same shape the local model uses and
    :func:`weve_mapping.plan_from_weve` reads back — so ``--objective`` survives
    the create→load round-trip. Called only when the project has no plan yet
    (:func:`open_or_create_mcp_plan`); an existing plan is reused untouched, never
    recreated, because the WeveNova plan is owned upstream."""
    plan_body: dict[str, Any] = {}
    if objective:
        plan_body["Context"] = [
            wm.context_to_weve(
                {
                    "key": "objective",
                    "value": objective,
                    "group": "objective",
                    "description": "Primary objective for this ESS rollout.",
                    "provenance": {"source": "User"},
                }
            )
        ]
    try:
        created = client.call_tool(
            "create_project_plan", {"projectId": project_id, "plan": plan_body}
        )
    except McpError as exc:
        raise PlanStoreError(
            f"cannot create a WeveNova plan for project {project_id}: {exc}"
        ) from exc
    plan_id = _plan_id_of(created)
    if not plan_id:
        raise PlanStoreError(
            f"WeveNova create_project_plan returned no PlanId (got {created!r:.120})."
        )
    return plan_id


def resolve_plan_binding(
    client: McpClient,
    *,
    project_id: str | None = None,
    plan_id: str | None = None,
) -> tuple[str, str, str | None]:
    """Resolve the ``(project_id, plan_id, tenant_id)`` the multi-plan WeveNova
    surface needs. Precedence: explicit arg → ``PLANNER_MCP_PROJECT_ID`` /
    ``PLANNER_MCP_PLAN_ID`` env → **discovery** (:func:`resolve_project_binding`
    then the project's ``ActivePlanId`` or its single plan via
    :func:`find_existing_plan_id`). Raises when the project has no plan yet —
    callers that create the first plan use :func:`open_or_create_mcp_plan`."""
    plan_id = plan_id or os.environ.get("PLANNER_MCP_PLAN_ID")
    project_id, project, tenant_id = resolve_project_binding(client, project_id=project_id)
    if not plan_id:
        plan_id = find_existing_plan_id(client, project_id=project_id, project=project)
        if not plan_id:
            raise PlanStoreError(
                f"project {project_id} has no plans — create one first or set "
                "PLANNER_MCP_PLAN_ID."
            )
    return project_id, plan_id, tenant_id


def make_store(
    *,
    backend: str,
    plan_path: str,
    mcp_server: str = "weve-plan",
    mcp_config: str = os.path.join(".vscode", "mcp.json"),
    mcp_cache: bool = True,
    project_id: str | None = None,
    plan_id: str | None = None,
) -> PlanStore:
    """Build the requested store. ``backend`` is ``"local"`` (default) or
    ``"mcp"``. For MCP, the endpoint comes from ``.vscode/mcp.json`` (the
    ``weve-plan`` server) or the ``PLANNER_MCP_URL`` env override; the multi-plan
    binding (``project_id``/``plan_id``) is taken from the args, the
    ``PLANNER_MCP_PROJECT_ID``/``PLANNER_MCP_PLAN_ID`` env, or discovered from the
    server (:func:`resolve_plan_binding`). WeveNova is the source of truth and
    ``plan_path`` is written only as a local cache/mirror (disable with
    ``mcp_cache=False``)."""
    if backend == "local":
        return LocalPlanStore(plan_path)
    if backend == "mcp":
        try:
            client = client_from_config(mcp_server, mcp_config)
        except McpError as exc:
            raise PlanStoreError(str(exc)) from exc
        pid, plid, tid = resolve_plan_binding(client, project_id=project_id, plan_id=plan_id)
        cache_path = plan_path if mcp_cache else None
        return McpPlanStore(
            client,
            _summary_beside(plan_path),
            project_id=pid,
            plan_id=plid,
            tenant_id=tid,
            cache_path=cache_path,
        )
    raise PlanStoreError(f"unknown plan store backend: {backend!r}")


def open_or_create_mcp_plan(
    *,
    plan_path: str,
    mcp_server: str = "weve-plan",
    mcp_config: str = os.path.join(".vscode", "mcp.json"),
    mcp_cache: bool = True,
    project_id: str | None = None,
    plan_id: str | None = None,
    objective: str | None = None,
) -> tuple[McpPlanStore, bool]:
    """Open the project's WeveNova plan for ``init``, **creating it upstream when
    the project has none yet**. Returns ``(store, created)``.

    This fixes the ``init --store mcp`` catch‑22: binding a store through
    :func:`make_store` / :func:`resolve_plan_binding` requires a plan to already
    exist, but ``init`` is exactly the command that should create the first plan.
    So instead of binding the plan up front, this binds the **project** first
    (:func:`resolve_project_binding`), looks for an existing plan
    (:func:`find_existing_plan_id`), and only when the project has none — a fresh
    project, or one whose only plan is archived so discovery finds none — creates
    one via :func:`create_project_plan` and binds the store to the returned
    ``PlanId``. An existing plan is reused untouched (never recreated): the
    WeveNova plan is owned upstream and a blind recreate would drop its tasks."""
    try:
        client = client_from_config(mcp_server, mcp_config)
    except McpError as exc:
        raise PlanStoreError(str(exc)) from exc
    pid, project, tid = resolve_project_binding(client, project_id=project_id)
    plid = plan_id or os.environ.get("PLANNER_MCP_PLAN_ID")
    if not plid:
        plid = find_existing_plan_id(client, project_id=pid, project=project)
    created = False
    if not plid:
        plid = create_project_plan(client, project_id=pid, objective=objective)
        created = True
    store = McpPlanStore(
        client,
        _summary_beside(plan_path),
        project_id=pid,
        plan_id=plid,
        tenant_id=tid,
        cache_path=plan_path if mcp_cache else None,
    )
    return store, created
