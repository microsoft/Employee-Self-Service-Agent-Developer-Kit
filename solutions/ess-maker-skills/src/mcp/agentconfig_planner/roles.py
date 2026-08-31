# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AgentConfiguration plan role-attestation endpoints (AgentConfiguration beta).

``RolesMixin`` is composed onto the neutral ``AgentConfigBaseClient`` core (see
``planner_client.py``) and reuses its bearer auth, tenant decode, httpx
session, and retrying ``_request``. Role assignments are tenant-sharded on the
token's ``tid`` claim, so the tenant is never a tool argument.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

# The AgentConfiguration MCP family lives at the ``src/mcp`` root as three sibling
# folders: the shared ``agentconfig_core`` client core plus the two MCP servers
# ``agentconfig_planner`` and ``agentconfig_landing_page``. There is no package
# __init__.py, and each server launches with cwd set to its own folder on a flat
# sys.path, so make the sibling ``agentconfig_core`` folder importable.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agentconfig_core")
)

from _odata import (  # noqa: E402
    _TENANTS_COLLECTION,
    _build_query_params,
    _escape_odata_literal,
    _mutation_headers,
    _require_odata_id,
)

_ROLE_ASSIGNMENTS_RESOURCE = "agentRoleAssignments"

# Only the provider-owned attestable roles are valid; legacy agent/task roles
# are retired.
ATTESTABLE_ROLES = ("WorkdayAdmin", "ServiceNowAdmin", "ServiceNowKnowledgeManager")
_ROLE_ASSIGNMENT_STATUSES = ("Active", "Revoked")
_ROLE_ASSIGNMENT_ORDERBY = ("createdAt asc", "createdAt desc")
_ATTESTATION_PROVIDER = "External"


class RolesMixin:
    """Plan role-attestation methods (tenant-sharded on the token's ``tid``)."""

    # Provided by the assembled client (PlannerClient).
    projects_base_url: str
    tenant_id: str

    def _role_assignments_collection_url(self) -> str:
        return (
            f"{self.projects_base_url}/{_TENANTS_COLLECTION}"
            f"('{self.tenant_id}')/{_ROLE_ASSIGNMENTS_RESOURCE}"
        )

    def _role_assignment_url(self, assignment_id: str) -> str:
        return (
            f"{self._role_assignments_collection_url()}"
            f"('{_require_odata_id(assignment_id, 'assignmentId')}')"
        )

    async def list_plan_role_assignments(
        self,
        plan_id: str,
        subject_id: Optional[str] = None,
        role: Optional[str] = None,
        status: Optional[str] = None,
        top: Optional[int] = None,
        orderby: Optional[str] = None,
        skiptoken: Optional[str] = None,
    ) -> Any:
        clauses = [f"targetPlanId eq '{_escape_odata_literal(plan_id, 'planId')}'"]
        if subject_id is not None:
            clauses.append(
                f"subjectObjectId eq '{_escape_odata_literal(subject_id, 'subjectId')}'"
            )
        if role is not None:
            clauses.append(f"roleId eq '{_escape_odata_literal(role, 'role')}'")
        if status is not None:
            if status not in _ROLE_ASSIGNMENT_STATUSES:
                raise ValueError("status must be Active or Revoked")
            clauses.append(f"status eq '{status}'")
        query: dict[str, Any] = {"filter": " and ".join(clauses)}
        if top is not None:
            query["top"] = top
        if orderby is not None:
            if orderby not in _ROLE_ASSIGNMENT_ORDERBY:
                raise ValueError(
                    "orderby must be 'createdAt asc' or 'createdAt desc'"
                )
            query["orderby"] = orderby
        if skiptoken is not None:
            query["skiptoken"] = skiptoken
        return await self._request(
            "GET",
            self._role_assignments_collection_url(),
            params=_build_query_params(query),
            transform_payload=False,
        )

    async def get_role_assignment(self, assignment_id: str) -> Any:
        return await self._request(
            "GET",
            self._role_assignment_url(assignment_id),
            transform_payload=False,
        )

    async def attest_plan_role(
        self,
        plan_id: str,
        subject_id: str,
        role: str,
        provider: str = _ATTESTATION_PROVIDER,
        etag: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        if not isinstance(subject_id, str) or not subject_id.strip():
            raise ValueError("subjectId is required")
        if role not in ATTESTABLE_ROLES:
            raise ValueError("role must be one of " + ", ".join(ATTESTABLE_ROLES))
        if provider != _ATTESTATION_PROVIDER:
            raise ValueError("provider must be External for plan attestation")
        if not isinstance(plan_id, str) or not plan_id.strip():
            raise ValueError("planId is required")
        body = {
            "subjectId": subject_id,
            "role": role,
            "target": {"type": "Plan", "id": plan_id},
            "provider": provider,
        }
        # Attest is a deterministic-row upsert on the backend: a given
        # (subject, role, target) resolves to one stable assignment row (an
        # opaque composite grant id), so replaying this POST converges on that
        # same row instead of creating duplicates. Verified against the
        # AgentConfiguration service. Passing an Idempotency-Key
        # (idempotency_key) additionally replays the cached result verbatim;
        # both make a retried attest safe with no client-side de-duplication.
        return await self._request(
            "POST",
            f"{self._role_assignments_collection_url()}/attest",
            json=body,
            headers=_mutation_headers(etag=etag, idempotency_key=idempotency_key),
            transform_payload=False,
        )

    async def revoke_role_assignment(
        self, assignment_id: str, etag: Optional[str] = None
    ) -> Any:
        return await self._request(
            "DELETE",
            self._role_assignment_url(assignment_id),
            headers=_mutation_headers(etag=etag),
            transform_payload=False,
        )
