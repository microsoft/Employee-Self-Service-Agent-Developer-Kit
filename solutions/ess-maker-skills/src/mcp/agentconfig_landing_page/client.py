# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Landing-page EmployeeAgents client (AgentConfiguration v1.1 surface).

The shared client core — bearer-token acquisition, the JWT claim decode, the
httpx session, and the retrying ``_request`` — lives in the neutral ``agentconfig_core``
core (``base_client.AgentConfigBaseClient``). This module keeps only what is specific to
the landing-page surface: the v1.1 base URL, the PascalCase/camelCase key
transform, the titleId helpers, and the tenant-scoped EmployeeAgents routes.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

# AgentConfiguration MCP surfaces and the shared ``agentconfig_core`` client live
# in sibling folders under ``src/mcp``. Each server launches with its own folder
# on a flat sys.path, so make the shared core importable.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agentconfig_core")
)

from _odata import (  # noqa: E402
    _require_odata_id,
    _validate_https_base_url,
    _validate_title_id,
)
from agent_discovery import (  # noqa: E402
    AgentDiscoveryClient,
    _to_api_payload,
    _to_tool_payload,
)
from base_client import AgentConfigApiError as AgentConfigApiError  # noqa: E402


DEFAULT_AGENTCONFIG_BASE_URL = "https://substrate.office.com/weveb2/api/v1.1"


class AgentConfigClient(AgentDiscoveryClient):
    """Async client for production EmployeeAgents list/search/create/get/PATCH.

    Inherits auth, token decode, the httpx session, and the retrying
    ``_request`` from ``AgentConfigBaseClient``; adds only the landing-page v1.1 base URL,
    the PascalCase response transform, and the EmployeeAgents routes.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        base_url = _validate_https_base_url(
            os.environ.get("AGENTCONFIG_BASE_URL", DEFAULT_AGENTCONFIG_BASE_URL),
            "AGENTCONFIG_BASE_URL",
        )
        super().__init__(
            base_url=base_url,
            logger_name="ess-landing-page-config",
            transport=transport,
        )

    def _transform_response(self, payload: Any) -> Any:
        """Rewrite PascalCase response keys to the camelCase the tools emit."""
        return _to_tool_payload(payload)

    def _collection_path(self) -> str:
        return self._agent_collection_path()

    def _agent_path(self, title_id: str) -> str:
        encoded = _require_odata_id(_validate_title_id(title_id), "titleId")
        return f"{self._collection_path()}('{encoded}')"

    async def create_agent_config(self, title_id: str) -> dict[str, Any]:
        title_id = _validate_title_id(title_id)
        return await self._request(
            "POST",
            self._collection_path(),
            json={"TitleId": title_id},
        )

    async def get_agent_config(
        self,
        title_id: str,
        *,
        select_fields: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        params = {"$select": ",".join(select_fields)} if select_fields else None
        return await self._request(
            "GET",
            self._agent_path(title_id),
            params=params,
        )

    async def update_agent_config(
        self,
        title_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise ValueError("config must be a JSON object")
        return await self._request(
            "PATCH",
            self._agent_path(title_id),
            json=_to_api_payload(config),
        )

    async def delete_agent_config(self, title_id: str) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            self._agent_path(title_id),
        )

    async def view_agent_icon(self, title_id: str) -> dict[str, Any]:
        return await self.get_agent_config(
            title_id,
            select_fields=("titleId", "name", "icon"),
        )

    async def open_accent_color(self, title_id: str) -> dict[str, Any]:
        return await self.get_agent_config(
            title_id,
            select_fields=("titleId", "branding"),
        )

    async def open_quick_links(self, title_id: str) -> dict[str, Any]:
        return await self.get_agent_config(
            title_id,
            select_fields=("titleId", "quickLinksConfig"),
        )

    async def open_starter_prompts(self, title_id: str) -> dict[str, Any]:
        # schemaName identifies the ESS vertical; the widget uses it to pick the
        # localized default categories it shows when pivots is empty.
        return await self.get_agent_config(
            title_id,
            select_fields=("titleId", "schemaName", "pivots"),
        )
