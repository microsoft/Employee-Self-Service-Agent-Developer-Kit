# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Typed adapter for the v1.1 PromptCardDefinitions maker API."""

import json
import logging
import os
import sys
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentconfig_landing_page.client import (  # noqa: E402
    AgentConfigClient, AgentConfigApiError, _to_api_payload, _validate_title_id,
)
from _odata import _require_odata_id  # noqa: E402
from prompt_cards_models import (  # noqa: E402
    Guid, PromptCardCreate, PromptCardDefinition, PromptCardPatch, PromptCardReorder,
)


class PromptCardsClient(AgentConfigClient):
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        super().__init__(transport=transport)
        self._logger = logging.getLogger("ess-prompt-cards")

    async def _request(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return await super()._request(*args, **kwargs)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AgentConfigApiError("Invalid prompt-card API response") from None

    def validate_scope(self, tenant_id: str, title_id: str) -> None:
        if TypeAdapter(Guid).validate_python(tenant_id) != self.tenant_id:
            raise ValueError("tenantId does not match the authenticated tenant")
        _validate_title_id(title_id)

    def _definitions_path(self, title_id: str) -> str:
        return f"{self._agent_path(title_id)}/PromptCardDefinitions"

    def _definition_path(self, title_id: str, definition_id: str) -> str:
        key = TypeAdapter(Guid).validate_python(definition_id)
        return f"{self._definitions_path(title_id)}('{_require_odata_id(key, 'definitionId')}')"

    @staticmethod
    def _definition(payload: Any) -> PromptCardDefinition:
        try:
            return PromptCardDefinition.model_validate(payload)
        except ValidationError:
            raise AgentConfigApiError("Invalid prompt-card definition response") from None

    def _definitions(self, payload: Any) -> list[PromptCardDefinition]:
        definitions = [self._definition(item) for item in self._unwrap_collection(payload)]
        if len({item.definitionId for item in definitions}) != len(definitions):
            raise AgentConfigApiError("Duplicate prompt-card IDs in API response")
        return sorted(definitions, key=lambda item: (item.sortOrder, item.definitionId))

    async def list_definitions(self, title_id: str) -> list[PromptCardDefinition]:
        payload = await self._request(
            "GET", f"{self._definitions_path(title_id)}/GetAllDefinitions()",
        )
        return self._definitions(payload)

    async def create_definition(
        self, title_id: str, definition: PromptCardCreate,
    ) -> PromptCardDefinition:
        definition = PromptCardCreate.model_validate(definition)
        payload = await self._request(
            "POST", self._definitions_path(title_id),
            json=_to_api_payload(definition.model_dump()), idempotent=False,
        )
        return self._definition(payload)

    async def update_definition(
        self, title_id: str, definition_id: str, patch: PromptCardPatch,
    ) -> PromptCardDefinition:
        patch = PromptCardPatch.model_validate(patch)
        payload = await self._request(
            "PATCH", self._definition_path(title_id, definition_id),
            json=_to_api_payload(patch.model_dump(exclude_unset=True)),
        )
        stored = self._definition(payload)
        if stored.definitionId != TypeAdapter(Guid).validate_python(definition_id):
            raise AgentConfigApiError("Prompt-card response ID does not match the request")
        return stored

    async def reorder_definitions(
        self, title_id: str, request: PromptCardReorder,
    ) -> list[PromptCardDefinition]:
        request = PromptCardReorder.model_validate(request)
        payload = await self._request(
            "PATCH", self._definitions_path(title_id),
            json=_to_api_payload(request.model_dump()),
            # Batch writes are not atomic; let the caller reconcile before replay.
            idempotent=False,
        )
        stored = self._definitions(payload)
        expected = {item.definitionId: item.sortOrder for item in request.definitions}
        if {item.definitionId: item.sortOrder for item in stored} != expected:
            raise AgentConfigApiError("Prompt-card reorder response does not match the request")
        return stored

    async def delete_definition(self, title_id: str, definition_id: str) -> None:
        await self._request("DELETE", self._definition_path(title_id, definition_id))
