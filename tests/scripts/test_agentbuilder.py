# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import base64
import json
import socket
from dataclasses import dataclass, field
from typing import Any

import pytest

import agentbuilder
import list_environments


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
HOST = (
    "https://0000000000004000800000000000111."
    "1.environment.api.test.powerplatform.com"
)


@dataclass
class FakeResponse:
    value: Any
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> Any:
        return self.value


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def mount(self, *_args: Any) -> None:
        pass

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)


def test_host_derivation_probes_primary_split_first() -> None:
    attempted: list[str] = []

    def resolver(hostname: str, _port: int) -> list[object]:
        attempted.append(hostname)
        if hostname.startswith("0000000000004000800000000000111.1."):
            return [object()]
        raise socket.gaierror

    host = agentbuilder.derive_environment_host(
        ENVIRONMENT_ID,
        "test",
        resolver=resolver,
    )

    assert host == HOST
    assert len(attempted) == 1


def test_explicit_host_rejects_cross_ring_and_paths() -> None:
    with pytest.raises(ValueError, match="environment host"):
        agentbuilder.validate_environment_host(
            "https://example.environment.api.powerplatform.com/path",
            "test",
        )


def test_client_uses_only_configured_environment_host() -> None:
    session = FakeSession(
        [
            FakeResponse([]),
            FakeResponse({"botId": AGENT_ID}),
            FakeResponse(
                {
                    "realm": "Dev",
                    "cdsBotId": AGENT_ID,
                    "schemaName": "gptagent_esshr",
                    "grsRepositoryId": "family-1",
                }
            ),
            FakeResponse(
                {
                    "bot": {"cdsBotId": AGENT_ID},
                    "botComponentChanges": [],
                }
            ),
        ]
    )
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=session,
    )

    client.list_agents()
    client.get_agent(AGENT_ID)
    client.get_dev_configuration(AGENT_ID)
    client.fetch_components(AGENT_ID)

    assert all(call["url"].startswith(HOST) for call in session.calls)
    assert all("crm.dynamics.com" not in call["url"] for call in session.calls)
    assert session.calls[2]["params"]["realm"] == 0
    assert session.calls[3]["method"] == "POST"
    assert session.calls[3]["json"] == {}


def test_http_403_is_explicit_without_echoing_response_body() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "error": {
                        "code": "Forbidden",
                        "message": "sensitive platform detail",
                    }
                },
                status_code=403,
            )
        ]
    )
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=session,
    )

    with pytest.raises(
        agentbuilder.AgentBuilderHTTPError,
        match="not authorized",
    ) as error:
        client.list_agents()

    assert "sensitive platform detail" not in str(error.value)


def test_extracts_guid_from_default_and_regular_environment_names() -> None:
    assert list_environments.extract_environment_guid(
        f"Default-{ENVIRONMENT_ID}"
    ) == ENVIRONMENT_ID
    assert list_environments.extract_environment_guid(
        ENVIRONMENT_ID
    ) == ENVIRONMENT_ID
    assert list_environments.extract_environment_guid("legacy-name") is None


def test_reads_tenant_id_from_authenticated_access_token() -> None:
    tenant_id = "00000000-0000-4000-8000-000000009999"
    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": tenant_id}).encode("utf-8")
    ).decode("ascii").rstrip("=")

    assert list_environments.tenant_id_from_access_token(
        f"header.{payload}.signature"
    ) == tenant_id


def test_agentbuilder_reads_tenant_id_from_authenticated_access_token() -> None:
    tenant_id = "00000000-0000-4000-8000-000000009999"
    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": tenant_id}).encode("utf-8")
    ).decode("ascii").rstrip("=")

    assert agentbuilder.tenant_id_from_access_token(
        f"header.{payload}.signature"
    ) == tenant_id


def test_agentbuilder_rejects_unreadable_token_tenant() -> None:
    with pytest.raises(agentbuilder.AgentBuilderError, match="tenant identity"):
        agentbuilder.tenant_id_from_access_token("opaque-token")


def test_first_run_authentication_returns_selected_token_tenant(
    tmp_path,
    monkeypatch,
) -> None:
    tenant_id = "00000000-0000-4000-8000-000000009999"
    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": tenant_id}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    token = f"header.{payload}.signature"
    observed: dict[str, Any] = {}

    class FakeApp:
        def __init__(self, client_id, *, authority, token_cache) -> None:
            observed["client_id"] = client_id
            observed["authority"] = authority
            observed["cache"] = token_cache

        def acquire_token_interactive(self, *, scopes, prompt):
            observed["scopes"] = scopes
            observed["prompt"] = prompt
            return {"access_token": token}

    monkeypatch.setattr(
        agentbuilder.msal,
        "PublicClientApplication",
        FakeApp,
    )

    result = agentbuilder.authenticate_selected_tenant(
        "prod",
        cache_path=tmp_path / "token-cache.bin",
    )

    assert result == (token, tenant_id)
    assert observed["authority"].endswith("/organizations")
    assert observed["prompt"] == "select_account"
    assert observed["scopes"] == [
        "https://api.powerplatform.com/"
        "CopilotStudio.MinimalBot.ReadWrite"
    ]
