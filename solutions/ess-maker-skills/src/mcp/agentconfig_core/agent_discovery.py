# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only deployed-agent discovery shared by feature-owned MCP providers."""

from __future__ import annotations

from typing import Any

from base_client import AgentConfigApiError, AgentConfigBaseClient


_MAX_SEARCH_LENGTH = 256


def _convert_key_case(value: Any, *, upper: bool) -> Any:
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


def _unwrap_agent_collection(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("value"), list):
        return payload["value"]
    raise AgentConfigApiError(
        "AgentConfiguration API returned an invalid collection response"
    )


class AgentDiscoveryClient(AgentConfigBaseClient):
    """Discover deployed titleIds without initializing any feature configuration.

    Feature clients retain their own base URL, transport, and authentication.
    Explicit response conversion keeps discovery independent of each feature's
    canonical payload casing and collection routes.
    """

    def _agent_collection_path(self) -> str:
        return f"tenants('{self.tenant_id}')/EmployeeAgents"

    async def list_agent_configs(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET", self._agent_collection_path(), transform_payload=False
        )
        return _unwrap_agent_collection(_to_tool_payload(payload))

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
            f"{self._agent_collection_path()}/SearchAgents",
            json={"SearchString": normalized},
            transform_payload=False,
        )
        return _unwrap_agent_collection(_to_tool_payload(payload))
