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

# The AgentConfiguration MCP family lives at the ``src/mcp`` root as three sibling
# folders: the shared ``agentconfig_core`` client core plus the two MCP servers
# ``agentconfig_planner`` and ``agentconfig_landing_page``. There is no package
# __init__.py, and each server launches with cwd set to its own folder on a flat
# sys.path, so make the sibling ``agentconfig_core`` folder importable.
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agentconfig_core")
)

from _odata import (  # noqa: E402
    _require_odata_id,
    _validate_https_base_url,
    _validate_odata_string,
)
from base_client import AgentConfigApiError, AgentConfigBaseClient  # noqa: E402


DEFAULT_AGENTCONFIG_BASE_URL = "https://substrate.office.com/weveb2/api/v1.1"
_MAX_TITLE_ID_LENGTH = 256
_MAX_SEARCH_LENGTH = 256


def _validate_title_id(title_id: str) -> str:
    _validate_odata_string(title_id, "titleId")
    if len(title_id) > _MAX_TITLE_ID_LENGTH:
        raise ValueError(
            f"titleId must not exceed {_MAX_TITLE_ID_LENGTH} characters"
        )
    return title_id


def _convert_key_case(value: Any, *, upper: bool) -> Any:
    """Recursively convert the first character of JSON object keys."""
    if isinstance(value, list):
        return [_convert_key_case(item, upper=upper) for item in value]
    if not isinstance(value, dict):
        return value

    converted: dict[str, Any] = {}
    for key, item in value.items():
        if key and key[0].isalpha():
            first = key[0].upper() if upper else key[0].lower()
            converted_key = first + key[1:]
        else:
            converted_key = key
        converted[converted_key] = _convert_key_case(item, upper=upper)
    return converted


def _to_api_payload(value: Any) -> Any:
    return _convert_key_case(value, upper=True)


def _to_tool_payload(value: Any) -> Any:
    return _convert_key_case(value, upper=False)


class AgentConfigClient(AgentConfigBaseClient):
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
        return f"tenants('{self.tenant_id}')/EmployeeAgents"

    def _agent_path(self, title_id: str) -> str:
        encoded = _require_odata_id(_validate_title_id(title_id), "titleId")
        return f"{self._collection_path()}('{encoded}')"

    @staticmethod
    def _unwrap_collection(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict) and isinstance(payload.get("value"), list):
            return payload["value"]
        raise AgentConfigApiError(
            "AgentConfiguration API returned an invalid collection response"
        )

    async def list_agent_configs(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", self._collection_path())
        return self._unwrap_collection(payload)

    async def search_agents(self, search_string: str) -> list[dict[str, Any]]:
        if not isinstance(search_string, str) or not search_string.strip():
            raise ValueError("searchString must be a non-empty string")
        normalized = search_string.strip()
        if len(normalized) > _MAX_SEARCH_LENGTH:
            raise ValueError(
                f"searchString must not exceed {_MAX_SEARCH_LENGTH} characters"
            )
        payload = await self._request(
            "POST",
            f"{self._collection_path()}/SearchAgents",
            json={"SearchString": normalized},
        )
        return self._unwrap_collection(payload)

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
        return await self.get_agent_config(
            title_id,
            select_fields=("titleId", "pivots"),
        )
