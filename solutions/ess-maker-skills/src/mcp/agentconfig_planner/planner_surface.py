# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AgentConfiguration project / plan / task endpoints (AgentConfiguration beta).

``PlannerMixin`` is composed onto the neutral ``AgentConfigBaseClient`` core (see
``planner_client.py``) and reuses its bearer auth, tenant decode, httpx
session, and retrying ``_request``. These routes live on the beta base
(``.../api/beta/me/agentConfigurationProjects``) and are addressed with
absolute URLs; httpx uses an absolute URL verbatim while still applying the
shared bearer/Accept headers. Bodies are camelCase and responses are returned
untransformed (``transform_payload=False``).
"""

from __future__ import annotations

import os
import sys
from typing import Any, Awaitable, Callable, Optional

# The AgentConfiguration MCP family lives at the ``src/mcp`` root as three sibling
# folders: the shared ``agentconfig_core`` client core plus the two MCP servers
# ``agentconfig_planner`` and ``agentconfig_landing_page``. There is no package
# __init__.py, and each server launches with cwd set to its own folder on a flat
# sys.path, so make the sibling ``agentconfig_core`` folder importable.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agentconfig_core")
)

from _odata import (  # noqa: E402
    _build_query_params,
    _entity_scalar,
    _escape_odata_literal,
    _mutation_headers,
    _normalize_etag,
    _require_odata_id,
)
from base_client import AgentConfigApiError  # noqa: E402

from roles_surface import ATTESTABLE_ROLES  # noqa: E402

_AGENT_PROJECTS_COLLECTION = "me/agentConfigurationProjects"
_PLANS_RESOURCE = "agentPlans"
_TASKS_RESOURCE = "agentPlanTasks"

_PROJECT_ARCHIVE_STATE = "Archived"
_PLAN_ARCHIVE_STATUS = "Archived"
_TASK_STATES = ("NotStarted", "InProgress", "Completed", "Cancelled")
# Scalar-group fields accepted by update_project_plan_task; lifecycle fields
# (state, outputs) go through set_project_plan_task_state / complete.
_TASK_UPDATE_FIELDS = ("title", "description", "assignedToId", "produces", "consumes")
_OUTPUT_KINDS = ("Custom", "Environment", "Connection", "KnowledgeSource")


def _normalize_completion_outputs(outputs: Any) -> list[dict[str, Any]]:
    """Validate and normalize task-completion artifacts to the PlanArtifact shape."""
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("outputs must contain at least one completion artifact")
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, output in enumerate(outputs):
        if not isinstance(output, dict):
            raise ValueError(f"outputs[{index}] must be an object")
        key = str(output.get("key", "")).strip()
        if not key:
            raise ValueError(f"outputs[{index}].key is required")
        if key in seen:
            raise ValueError(f"outputs contains duplicate key {key}")
        seen.add(key)
        kind = str(output.get("kind", ""))
        if kind not in _OUTPUT_KINDS:
            raise ValueError(
                f"outputs[{index}].kind must be one of {', '.join(_OUTPUT_KINDS)}"
            )
        raw_attributes = output.get("attributes")
        if not isinstance(raw_attributes, list):
            raise ValueError(f"outputs[{index}].attributes must be an array")
        attributes: list[dict[str, Any]] = []
        for attr_index, attribute in enumerate(raw_attributes):
            if not isinstance(attribute, dict):
                raise ValueError(
                    f"outputs[{index}].attributes[{attr_index}] must be an object"
                )
            attribute_key = str(attribute.get("key", "")).strip()
            if not attribute_key:
                raise ValueError(
                    f"outputs[{index}].attributes[{attr_index}].key is required"
                )
            entry: dict[str, Any] = {
                "key": attribute_key,
                "value": attribute.get("value"),
            }
            if attribute.get("description") is not None:
                entry["description"] = attribute["description"]
            attributes.append(entry)
        if kind == "Environment" and not any(
            attribute["key"] == "environmentId"
            and str(attribute.get("value") or "").strip()
            for attribute in attributes
        ):
            raise ValueError(
                f"outputs[{index}] Environment requires a non-empty "
                "environmentId attribute"
            )
        artifact: dict[str, Any] = {"key": key, "kind": kind, "attributes": attributes}
        if output.get("inventoryRef"):
            artifact["inventoryRef"] = output["inventoryRef"]
        normalized.append(artifact)
    return normalized


class PlannerMixin:
    """Project / plan / task methods for the AgentConfiguration beta surface."""

    # Provided by the assembled client (PlannerClient).
    projects_base_url: str
    _caller_object_id: Optional[str]

    # ------------------------------------------------------------------
    # URL builders
    # ------------------------------------------------------------------
    def _projects_collection_url(self) -> str:
        return f"{self.projects_base_url}/{_AGENT_PROJECTS_COLLECTION}"

    def _project_url(self, project_id: str) -> str:
        return (
            f"{self._projects_collection_url()}"
            f"('{_require_odata_id(project_id, 'projectId')}')"
        )

    def _plans_collection_url(self, project_id: str) -> str:
        return f"{self._project_url(project_id)}/{_PLANS_RESOURCE}"

    def _plan_url(self, project_id: str, plan_id: str) -> str:
        return (
            f"{self._plans_collection_url(project_id)}"
            f"('{_require_odata_id(plan_id, 'planId')}')"
        )

    def _tasks_collection_url(self, project_id: str, plan_id: str) -> str:
        return f"{self._plan_url(project_id, plan_id)}/{_TASKS_RESOURCE}"

    def _task_url(self, project_id: str, plan_id: str, task_id: str) -> str:
        return (
            f"{self._tasks_collection_url(project_id, plan_id)}"
            f"('{_require_odata_id(task_id, 'taskId')}')"
        )

    # ------------------------------------------------------------------
    # ETag / plan-state conflict recovery
    # ------------------------------------------------------------------
    async def _mutate_with_etag_recovery(
        self,
        method: str,
        url: str,
        *,
        etag: str,
        refetch: Callable[[], Awaitable[Any]],
        json_body: Optional[dict[str, Any]] = None,
        plan_refetch: Optional[Callable[[], Awaitable[Any]]] = None,
    ) -> Any:
        """Run an If-Match mutation, recovering from the two conflicts this
        surface produces so a planner agent need not hand-roll the retry dance.

        * **412 Precondition Failed** (stale/mismatched ETag): re-read the
          entity via ``refetch`` to surface an actionable error. AgentConfiguration bumps
          a task's version as a side effect of ledger reconciliation (for
          example, completing a producer task reconciles an artifact a consumer
          task references), so an ETag a caller just read can go stale through
          no edit of its own — but that benign bump is indistinguishable from a
          concurrent edit to the very fields being written. Rather than blindly
          replay the mutation against the fresh ETag (which would defeat the
          ``If-Match`` lost-update guard and could silently clobber another
          writer's change), the precondition failure is preserved: the caller
          is told the ETag advanced and must re-read and reapply the change if
          it is still needed.
        * **409 Conflict** on a task mutation (``plan_refetch`` supplied): the
          dominant cause is the parent plan not being Active —
          ``EnsureParentPlanIsActive`` makes tasks read-only under a non-Active
          plan, and the backend returns a generic conflict message. Re-read the
          plan and, when it is not Active, surface an actionable message;
          otherwise re-raise the original error untouched.
        """

        async def _perform(active_etag: str) -> Any:
            return await self._request(
                method,
                url,
                json=json_body,
                headers=_mutation_headers(etag=active_etag),
                transform_payload=False,
            )

        try:
            return await _perform(etag)
        except AgentConfigApiError as error:
            if error.http_status == 412:
                try:
                    entity = await refetch()
                except AgentConfigApiError:
                    # The re-read that would let us explain the precondition
                    # failure itself failed; surface the original 412 so the
                    # caller still sees the actionable stale-ETag signal rather
                    # than a secondary error from the recovery read.
                    raise error
                fresh = _entity_scalar(entity, "ETag", "@odata.etag")
                if fresh and _normalize_etag(fresh) != _normalize_etag(etag):
                    # The entity was modified after the caller read it (its ETag
                    # advanced). A benign ledger-reconciliation version bump is
                    # indistinguishable here from a concurrent edit to the same
                    # fields, so replaying the mutation against the fresh ETag
                    # could silently overwrite another writer's work. Preserve
                    # the precondition failure and let the caller re-read and
                    # decide whether the change is still needed.
                    raise AgentConfigApiError(
                        "The entity changed since you read it (its ETag advanced "
                        f"from {etag} to {fresh}). Re-read it to get the current "
                        "ETag and state, then reapply your change if it is still "
                        "needed.",
                        http_status=412,
                    ) from error
                raise
            if error.http_status == 409 and plan_refetch is not None:
                try:
                    plan = await plan_refetch()
                except AgentConfigApiError:
                    # As above: keep the original 409 conflict if the recovery
                    # plan re-read fails, instead of masking it with a secondary
                    # error.
                    raise error
                status = _entity_scalar(plan, "Status")
                if status is not None and status.lower() != "active":
                    raise AgentConfigApiError(
                        f"The parent plan is '{status}', not Active, so its "
                        "tasks are read-only. Activate the plan with "
                        'update_project_plan patch {"status": "Active"} (plan '
                        "owner only) before updating, transitioning, "
                        "completing, or deleting its tasks.",
                        http_status=409,
                    ) from error
                raise
            raise

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    async def list_agent_configuration_projects(
        self, query: Optional[dict[str, Any]] = None
    ) -> Any:
        return await self._request(
            "GET",
            self._projects_collection_url(),
            params=_build_query_params(query),
            transform_payload=False,
        )

    async def get_agent_configuration_project(
        self, project_id: str, query: Optional[dict[str, Any]] = None
    ) -> Any:
        return await self._request(
            "GET",
            self._project_url(project_id),
            params=_build_query_params(query),
            transform_payload=False,
        )

    async def create_agent_configuration_project(
        self, project: dict[str, Any], idempotency_key: Optional[str] = None
    ) -> Any:
        if not isinstance(project, dict):
            raise ValueError("project must be an object")
        # Get-or-create by name is convergent: a replayed POST after an
        # ambiguous 5xx resolves to the same project, so (unlike the create_*
        # plan/task calls below) this stays retry-safe by default and does not
        # opt out.
        return await self._request(
            "POST",
            self._projects_collection_url(),
            json=project,
            headers=_mutation_headers(idempotency_key=idempotency_key),
            transform_payload=False,
        )

    async def archive_agent_configuration_project(
        self, project_id: str, etag: str
    ) -> Any:
        return await self._mutate_with_etag_recovery(
            "PATCH",
            self._project_url(project_id),
            etag=etag,
            json_body={"state": _PROJECT_ARCHIVE_STATE},
            refetch=lambda: self.get_agent_configuration_project(project_id),
        )

    # ------------------------------------------------------------------
    # Plans
    # ------------------------------------------------------------------
    async def list_project_plans(
        self, project_id: str, query: Optional[dict[str, Any]] = None
    ) -> Any:
        return await self._request(
            "GET",
            self._plans_collection_url(project_id),
            params=_build_query_params(query),
            transform_payload=False,
        )

    async def get_project_plan(
        self, project_id: str, plan_id: str, query: Optional[dict[str, Any]] = None
    ) -> Any:
        return await self._request(
            "GET",
            self._plan_url(project_id, plan_id),
            params=_build_query_params(query),
            transform_payload=False,
        )

    async def create_project_plan(
        self,
        project_id: str,
        plan: dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> Any:
        if not isinstance(plan, dict):
            raise ValueError("plan must be an object")
        return await self._request(
            "POST",
            self._plans_collection_url(project_id),
            json=plan,
            headers=_mutation_headers(idempotency_key=idempotency_key),
            idempotent=idempotency_key is not None,
            transform_payload=False,
        )

    async def update_project_plan(
        self, project_id: str, plan_id: str, patch: dict[str, Any], etag: str
    ) -> Any:
        if not isinstance(patch, dict) or not patch:
            raise ValueError("patch must be a non-empty object")
        for key, value in patch.items():
            if (
                key.strip().lower() == "status"
                and isinstance(value, str)
                and value.strip().lower() == _PLAN_ARCHIVE_STATUS.lower()
            ):
                raise ValueError(
                    "Refusing to archive a plan through update_project_plan; "
                    "archiving also cancels the plan's tasks. Use "
                    "archive_project_plan for that destructive operation."
                )
        return await self._mutate_with_etag_recovery(
            "PATCH",
            self._plan_url(project_id, plan_id),
            etag=etag,
            json_body=patch,
            refetch=lambda: self.get_project_plan(project_id, plan_id),
        )

    async def archive_project_plan(
        self, project_id: str, plan_id: str, etag: str
    ) -> Any:
        return await self._mutate_with_etag_recovery(
            "PATCH",
            self._plan_url(project_id, plan_id),
            etag=etag,
            json_body={"status": _PLAN_ARCHIVE_STATUS},
            refetch=lambda: self.get_project_plan(project_id, plan_id),
        )

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------
    async def list_project_plan_tasks(
        self, project_id: str, plan_id: str, query: Optional[dict[str, Any]] = None
    ) -> Any:
        return await self._request(
            "GET",
            self._tasks_collection_url(project_id, plan_id),
            params=_build_query_params(query),
            transform_payload=False,
        )

    async def _caller_active_role_ids(
        self, plan_id: str, caller_id: str
    ) -> list[str]:
        """Role ids the caller actively holds on this plan.

        Role-pooled tasks are addressed to a role (in ``assignedToRoleId``), not
        the caller's oid, so scoping "tasks for the caller" to direct
        assignments alone would hide them. Resolving the caller's Active role
        assignments for the plan lets the task query expand to those roles.
        """
        assignments = await self.list_plan_role_assignments(
            plan_id, subject_id=caller_id, status="Active"
        )
        entities = (
            assignments.get("value")
            if isinstance(assignments, dict)
            else assignments
        )
        if not isinstance(entities, list):
            return []
        role_ids: list[str] = []
        seen: set[str] = set()
        for entity in entities:
            # Field asymmetry: the $filter grammar keys role on ``roleId`` (see
            # list_plan_role_assignments), but the assignment response projects
            # the role name under ``role`` (``roleId`` appears only on older
            # shapes). Read ``role`` first, falling back to ``roleId``, so the
            # value matches a task's ``assignedToRoleId`` and role-pooled tasks
            # are not silently dropped. Verified against the AgentConfiguration
            # service response shape.
            role_id = _entity_scalar(entity, "role", "roleId")
            if role_id and role_id not in seen:
                seen.add(role_id)
                role_ids.append(role_id)
        return role_ids

    async def list_project_plan_tasks_for_caller(
        self, project_id: str, plan_id: str, query: Optional[dict[str, Any]] = None
    ) -> Any:
        caller_id = self._caller_object_id
        if not caller_id:
            raise AgentConfigApiError(
                "The access token has no 'oid' claim; cannot scope tasks to the caller."
            )
        # Direct assignment to the caller, plus every role the caller actively
        # holds on this plan. create_role_assigned_project_plan_task stores the
        # role in assignedToRoleId, so role-pooled tasks would otherwise be
        # invisible here despite the tool contract promising them.
        clauses = [
            f"assignedToId eq '{_escape_odata_literal(caller_id, 'callerId')}'"
        ]
        for role_id in await self._caller_active_role_ids(plan_id, caller_id):
            # Pool-only. A person-assigned task keeps its grounding
            # assignedToRoleId (see scripts/planner/sync.py), so matching the
            # role id alone would surface work owned by someone else to every
            # other holder of that role; require the open Role-typed pool too.
            clauses.append(
                f"(assignedToRoleId eq '{_escape_odata_literal(role_id, 'roleId')}' "
                "and assignedToType eq 'Role')"
            )
        caller_filter = " or ".join(clauses)
        # Completed work is history, not something the caller can pick up
        # (mirrors the local Flow-2 exclusion in plan_model), so scope it out.
        scoped_filter = f"({caller_filter}) and state ne 'Completed'"
        merged = dict(query or {})
        existing = merged.get("filter")
        merged["filter"] = (
            f"({scoped_filter}) and ({existing})" if existing else scoped_filter
        )
        return await self._request(
            "GET",
            self._tasks_collection_url(project_id, plan_id),
            params=_build_query_params(merged),
            transform_payload=False,
        )

    async def get_project_plan_task(
        self,
        project_id: str,
        plan_id: str,
        task_id: str,
        query: Optional[dict[str, Any]] = None,
    ) -> Any:
        return await self._request(
            "GET",
            self._task_url(project_id, plan_id, task_id),
            params=_build_query_params(query),
            transform_payload=False,
        )

    async def create_project_plan_task(
        self,
        project_id: str,
        plan_id: str,
        task: dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> Any:
        if not isinstance(task, dict):
            raise ValueError("task must be an object")
        return await self._request(
            "POST",
            self._tasks_collection_url(project_id, plan_id),
            json=task,
            headers=_mutation_headers(idempotency_key=idempotency_key),
            idempotent=idempotency_key is not None,
            transform_payload=False,
        )

    async def create_role_assigned_project_plan_task(
        self,
        project_id: str,
        plan_id: str,
        role: str,
        title: str,
        description: Optional[str] = None,
        produces: Optional[list[str]] = None,
        consumes: Optional[list[str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        if role not in ATTESTABLE_ROLES:
            raise ValueError("role must be one of " + ", ".join(ATTESTABLE_ROLES))
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be a non-empty string")
        body: dict[str, Any] = {
            "title": title,
            "assignedToId": role,
            "assignedToType": "Role",
            "assignedToRoleId": role,
        }
        if description is not None:
            body["description"] = description
        if produces is not None:
            body["produces"] = produces
        if consumes is not None:
            body["consumes"] = consumes
        return await self._request(
            "POST",
            self._tasks_collection_url(project_id, plan_id),
            json=body,
            headers=_mutation_headers(idempotency_key=idempotency_key),
            idempotent=idempotency_key is not None,
            transform_payload=False,
        )

    async def update_project_plan_task(
        self,
        project_id: str,
        plan_id: str,
        task_id: str,
        patch: dict[str, Any],
        etag: str,
    ) -> Any:
        if not isinstance(patch, dict) or not patch:
            raise ValueError("patch must be a non-empty object")
        canonical = {field.lower(): field for field in _TASK_UPDATE_FIELDS}
        normalized: dict[str, Any] = {}
        for key, value in patch.items():
            field = canonical.get(key.lower())
            if field is None:
                raise ValueError(
                    f"patch.{key} is not accepted here; use "
                    "set_project_plan_task_state or complete_project_plan_task "
                    "for lifecycle changes"
                )
            if field in normalized:
                raise ValueError(
                    f"patch.{key} duplicates field {field}"
                )
            # Emit the canonical camelCase key regardless of how the caller
            # cased it. The live surface deserializes these field names
            # case-insensitively (a PATCH sending "Title" lands identically to
            # "title"), so normalization is not required for the write to
            # apply; it keeps the emitted body a deterministic camelCase shape
            # consistent with the rest of this client and stays correct if the
            # backend ever tightens to case-sensitive parsing. Combined with the
            # duplicate check above it also rejects a patch that names one field
            # twice under different casing.
            normalized[field] = value
        return await self._mutate_with_etag_recovery(
            "PATCH",
            self._task_url(project_id, plan_id, task_id),
            etag=etag,
            json_body=normalized,
            refetch=lambda: self.get_project_plan_task(project_id, plan_id, task_id),
            plan_refetch=lambda: self.get_project_plan(project_id, plan_id),
        )

    async def set_project_plan_task_state(
        self,
        project_id: str,
        plan_id: str,
        task_id: str,
        state: str,
        etag: str,
    ) -> Any:
        if state not in _TASK_STATES:
            raise ValueError(f"state must be one of {', '.join(_TASK_STATES)}")
        return await self._mutate_with_etag_recovery(
            "PATCH",
            self._task_url(project_id, plan_id, task_id),
            etag=etag,
            json_body={"state": state},
            refetch=lambda: self.get_project_plan_task(project_id, plan_id, task_id),
            plan_refetch=lambda: self.get_project_plan(project_id, plan_id),
        )

    async def complete_project_plan_task(
        self,
        project_id: str,
        plan_id: str,
        task_id: str,
        outputs: list[dict[str, Any]],
        etag: str,
    ) -> Any:
        normalized = _normalize_completion_outputs(outputs)
        return await self._mutate_with_etag_recovery(
            "PATCH",
            self._task_url(project_id, plan_id, task_id),
            etag=etag,
            json_body={"state": "Completed", "outputs": normalized},
            refetch=lambda: self.get_project_plan_task(project_id, plan_id, task_id),
            plan_refetch=lambda: self.get_project_plan(project_id, plan_id),
        )

    async def delete_project_plan_task(
        self, project_id: str, plan_id: str, task_id: str, etag: str
    ) -> Any:
        return await self._mutate_with_etag_recovery(
            "DELETE",
            self._task_url(project_id, plan_id, task_id),
            etag=etag,
            refetch=lambda: self.get_project_plan_task(project_id, plan_id, task_id),
            plan_refetch=lambda: self.get_project_plan(project_id, plan_id),
        )
