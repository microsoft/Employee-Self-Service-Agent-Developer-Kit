# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Topic-action-owned native transport; no Connect or evaluation dependencies."""

from __future__ import annotations

from copy import deepcopy

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from agentbuilder import (
    AgentBuilderClient, AgentBuilderError, _response_error,
    environment_id_from_host, validate_environment_host,
)
from topic_actions_discovery import DiscoveryTarget, _identity, _target


COMPONENTS_API_VERSION = "2022-03-01-preview"


def verify_native_target(client: AgentBuilderClient, target: DiscoveryTarget) -> dict:
    """Verify direct identity without requiring ALM enrollment or a Dev realm."""
    target = _target(target)
    if (
        _identity(client.tenant_id) != target.tenant_id
        or environment_id_from_host(client.host, client.ring) != target.environment_id
    ):
        raise ValueError("Client identity is not bound to the selected target.")
    agent = client.get_agent(target.agent_id)
    if not isinstance(agent, dict) or _identity(agent.get("botId")) != target.agent_id:
        raise ValueError("Direct lookup did not return the selected agent.")
    return agent


class TopicActionsClient:
    single_attempt = True

    def __init__(
        self, environment_id: str, bot_id: str, tenant_id: str, *,
        host: str, ring: str, token: str, account: str, read_only: bool = False,
    ):
        target = _target(DiscoveryTarget(tenant_id, environment_id, bot_id))
        self.host = validate_environment_host(host, ring)
        if environment_id_from_host(self.host, ring) != target.environment_id:
            raise ValueError("Component host does not match the selected environment.")
        if not token or not isinstance(account, str) or not account.strip():
            raise ValueError("Verified authentication is required.")
        self.tenant_id = target.tenant_id
        self.environment_id = target.environment_id
        self.bot_id = target.agent_id
        self.ring = ring
        self.signed_in_username = account
        self.read_only = read_only
        self._token = token
        self._submitted = False

    @property
    def _components_url(self) -> str:
        return (
            f"{self.host}/copilotstudio/minimalBots/api/{self.bot_id}/components"
            f"?api-version={COMPONENTS_API_VERSION}"
        )

    def _request(self, method: str, url: str, *, body: dict) -> tuple[requests.Response, object]:
        with requests.Session() as session:
            session.mount("https://", HTTPAdapter(max_retries=Retry(total=0)))
            response = session.request(
                method, url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                json=deepcopy(body), timeout=120, allow_redirects=False,
            )
        if response.status_code != 200:
            _response_error(response, "Component submission" if method == "PUT" else "Component fetch")
        # A successful write still requires the controller's independent readback.
        if method == "PUT":
            return response, None
        try:
            return response, response.json()
        except ValueError:
            raise AgentBuilderError("Component fetch returned invalid JSON.") from None

    def read_components(self) -> dict:
        _, body = self._request("POST", self._components_url, body={})
        if not isinstance(body, dict):
            raise AgentBuilderError("Component fetch returned an unexpected payload.")
        return body

    def submit_state_payload(self, payload: dict) -> None:
        """Send the backend's exact validated payload, with no reread or replay."""
        if self.read_only or self._submitted:
            raise ValueError("Component submission is unavailable or already consumed.")
        self._submitted = True
        self._request("PUT", self._components_url, body=payload)
