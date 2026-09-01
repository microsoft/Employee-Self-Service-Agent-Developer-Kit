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

# Attestation providers accepted by the backend's attest action. The native
# ``AgentConfiguration`` provider is grant-only and is never valid for
# attestation, so it is deliberately absent here.
PROVIDER_EXTERNAL = "External"
PROVIDER_ENTRA = "Entra"
PROVIDER_POWER_PLATFORM = "PowerPlatform"
ATTESTATION_PROVIDERS = (PROVIDER_EXTERNAL, PROVIDER_ENTRA, PROVIDER_POWER_PLATFORM)

# Provider-owned attestable roles, mirroring the backend registry
# ``AttestableAuthorizationRoles`` (core/core/AgentConfiguration/Authorization/
# AttestableAuthorizationRoles.cs in o365exchange / "O365 Core" / WeveNova).
# There is no discovery endpoint for this set - it is a closed compile-time
# catalog on the service - so this table is a hand-maintained mirror and MUST
# stay in lockstep with the backend. The attest action validates ``role``
# against each provider's human-readable display names (NOT the compact ids used
# everywhere else), and additionally rejects any attest whose asserted provider
# doesn't own the role. So each role carries a fixed owning provider, and attest
# derives that provider from the role rather than trusting the caller. Verified
# against the live service: posting a compact id (e.g. "ServiceNowAdmin") returns
# 400 "role must be one of Workday administrator, ServiceNow Administrator,
# ServiceNow Knowledge Manager." while the display name under its owning provider
# is accepted (201).
_ROLES_BY_PROVIDER: dict[str, dict[str, str]] = {
    # External - upstream systems with no queryable Microsoft directory.
    PROVIDER_EXTERNAL: {
        "WorkdayAdmin": "Workday administrator",
        "ServiceNowAdmin": "ServiceNow Administrator",
        "ServiceNowKnowledgeManager": "ServiceNow Knowledge Manager",
    },
    # Entra - Microsoft Entra ID directory roles.
    PROVIDER_ENTRA: {
        "EntraGlobalAdministrator": "Global Administrator",
        "EntraNetworkAdministrator": "Network Administrator",
        "EntraUserAdministrator": "User Administrator",
        "EntraPowerPlatformAdministrator": "Power Platform Administrator",
        "EntraApplicationAdministrator": "Application Administrator",
        "EntraCloudApplicationAdministrator": "Cloud Application Administrator",
    },
    # Power Platform - Dataverse / environment roles.
    PROVIDER_POWER_PLATFORM: {
        "PowerPlatformEnvironmentMaker": "Environment Maker",
        "PowerPlatformEnvironmentAdministrator": "Environment Administrator",
        "PowerPlatformSystemAdministrator": "System Administrator",
    },
}

# Compact id -> (wire display name, owning provider). Flattened from the
# provider-grouped source above; External roles stay first so pre-existing
# ordering and behaviour are preserved.
ATTESTABLE_ROLE_DEFINITIONS: dict[str, tuple[str, str]] = {
    role_id: (wire, provider)
    for provider, roles in _ROLES_BY_PROVIDER.items()
    for role_id, wire in roles.items()
}

# The compact role ids, in registry order - what ``list_attestable_roles``
# returns and what ``create_role_assigned_project_plan_task`` validates against.
ATTESTABLE_ROLES = tuple(ATTESTABLE_ROLE_DEFINITIONS)

# Compact id -> wire display name. Retained as a public alias (callers and tests
# reference it), derived from the single source of truth above.
ATTESTABLE_ROLE_WIRE_NAMES = {
    role_id: wire for role_id, (wire, _provider) in ATTESTABLE_ROLE_DEFINITIONS.items()
}

# Wire display name -> owning provider, for callers that pass a display name.
_WIRE_NAME_TO_PROVIDER = {
    wire: provider for wire, provider in ATTESTABLE_ROLE_DEFINITIONS.values()
}


def resolve_attestable_role(role: str) -> tuple[str, str]:
    """Resolve a caller-supplied role - a compact id (``WorkdayAdmin``) or the
    backend wire display name (``Workday administrator``) - to its
    ``(wire display name, owning provider)``. Raise ``ValueError`` listing the
    accepted values when the role is not attestable."""
    if role in ATTESTABLE_ROLE_DEFINITIONS:
        return ATTESTABLE_ROLE_DEFINITIONS[role]
    if role in _WIRE_NAME_TO_PROVIDER:
        return role, _WIRE_NAME_TO_PROVIDER[role]
    raise ValueError(
        "role must be one of "
        + ", ".join(ATTESTABLE_ROLES)
        + " (compact ids) or their display names "
        + ", ".join(ATTESTABLE_ROLE_WIRE_NAMES.values())
    )


_ROLE_ASSIGNMENT_STATUSES = ("Active", "Revoked")
_ROLE_ASSIGNMENT_ORDERBY = ("createdAt asc", "createdAt desc")


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
        provider: Optional[str] = None,
        etag: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> Any:
        if not isinstance(subject_id, str) or not subject_id.strip():
            raise ValueError("subjectId is required")
        # A role's provider is fixed by the backend registry (the service rejects
        # any attest whose provider doesn't own the role), so resolve both the
        # wire display name and the owning provider from the role. ``provider``
        # stays accepted for explicit callers, but when supplied it must match
        # the role's owner rather than override it.
        wire_role, role_provider = resolve_attestable_role(role)
        if provider is not None and provider != role_provider:
            raise ValueError(
                f"role '{wire_role}' is owned by provider '{role_provider}', "
                f"not '{provider}'"
            )
        if not isinstance(plan_id, str) or not plan_id.strip():
            raise ValueError("planId is required")
        body = {
            "subjectId": subject_id,
            # The backend validates ``role`` against the provider display names,
            # so always send the mapped display string even though callers may
            # pass the compact id used elsewhere in the family.
            "role": wire_role,
            "target": {"type": "Plan", "id": plan_id},
            # Attestation is provider-scoped; send the role's owning provider.
            "provider": role_provider,
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
