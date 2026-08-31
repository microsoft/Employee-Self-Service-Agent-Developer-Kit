# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Planner client: the neutral AgentConfiguration core plus the planner and
role-attestation endpoint mixins.

``PlannerClient`` inherits the shared ``AgentConfigBaseClient`` core — MSAL/bearer token
acquisition, the ``tid`` tenant decode, the shared httpx session, and the
retrying ``_request`` — and layers the beta project/plan/task and
role-attestation surfaces on top through mixins. It adds only the two pieces
those surfaces need beyond the core: the beta projects base URL and the
caller's ``oid`` (decoded from the same token). It logs under its own
``ess-planner`` name and carries none of the landing-page EmployeeAgents routes.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

# The AgentConfiguration MCP family lives at the ``src/mcp`` root as three sibling
# folders: the shared ``agentconfig_core`` client core plus the two MCP servers
# ``agentconfig_planner`` and ``agentconfig_landing_page``. There is no package
# __init__.py, and each server launches with cwd set to its own folder on a flat
# sys.path, so make the sibling ``agentconfig_core`` folder importable.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agentconfig_core")
)

from _odata import (  # noqa: E402
    _DEFAULT_AGENTCONFIG_PROJECTS_BASE_URL,
    _validate_https_base_url,
)
from base_client import AgentConfigBaseClient, _decode_object_id_from_jwt  # noqa: E402

from planner import PlannerMixin  # noqa: E402
from roles import RolesMixin  # noqa: E402


class PlannerClient(PlannerMixin, RolesMixin, AgentConfigBaseClient):
    """Async client for the AgentConfiguration project / plan / task and role
    attestation routes, composed onto the neutral AgentConfiguration client core."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        projects_base_url = _validate_https_base_url(
            os.environ.get(
                "AGENTCONFIG_PROJECTS_BASE_URL",
                _DEFAULT_AGENTCONFIG_PROJECTS_BASE_URL,
            ),
            "AGENTCONFIG_PROJECTS_BASE_URL",
        )
        super().__init__(
            base_url=projects_base_url,
            logger_name="ess-planner",
            transport=transport,
        )
        self.projects_base_url = projects_base_url
        self._caller_object_id = _decode_object_id_from_jwt(self._token)

    def __repr__(self) -> str:
        return (
            f"<PlannerClient projects_base_url={self.projects_base_url!r} "
            f"tenant_id={self.tenant_id!r}>"
        )

    def _format_api_error(self, body: Any, status_code: int) -> str:
        """Surface the AgentConfiguration error envelope's actionable detail.

        The neutral core message is just ``Code: Message`` — often opaque, e.g.
        ``BadRequest: The calling client sent a bad request to the service.``.
        The planner and role routes carry the field-level reason in ``Target``
        and the nested ``Details[]`` validation entries (for example the exact
        allowed values for an attest ``role``). The planner appends them so the
        agent reads the real cause and self-corrects instead of only seeing the
        generic top-level message.
        """
        message = super()._format_api_error(body, status_code)
        if not isinstance(body, dict):
            return message
        target = body.get("Target")
        if isinstance(target, str) and target.strip():
            message = f"{message} (target: {target})"
        details = body.get("Details")
        if isinstance(details, list):
            rendered: list[str] = []
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                detail_code = detail.get("Code")
                detail_message = detail.get("Message")
                if isinstance(detail_message, str) and detail_message.strip():
                    if isinstance(detail_code, str) and detail_code.strip():
                        rendered.append(f"{detail_code}: {detail_message}")
                    else:
                        rendered.append(detail_message)
            if rendered:
                message = f"{message} Details: {'; '.join(rendered)}"
        return message
