# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import base64
import json
import socket
from dataclasses import dataclass, field
from pathlib import Path
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
    content: bytes = b""
    closed: bool = False
    close_error: Exception | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [
            self.content[index : index + chunk_size]
            for index in range(0, len(self.content), chunk_size)
        ]

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error

    def json(self) -> Any:
        return self.value


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []
        self.mounts: dict[str, Any] = {}

    def mount(self, prefix: str, adapter: Any) -> None:
        self.mounts[prefix] = adapter

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
            FakeResponse({"routeRealm": 0}),
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
    client.get_realms(AGENT_ID)
    client.get_dev_configuration(AGENT_ID)
    client.fetch_components(AGENT_ID)

    assert all(call["url"].startswith(HOST) for call in session.calls)
    assert all("crm.dynamics.com" not in call["url"] for call in session.calls)
    assert session.calls[2]["url"].endswith(f"/alm/{AGENT_ID}/realms")
    assert session.calls[3]["params"]["realm"] == 0
    assert session.calls[4]["method"] == "POST"
    assert session.calls[4]["json"] == {}


def test_realm_configuration_rejects_unknown_realm() -> None:
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=FakeSession([]),
    )

    with pytest.raises(ValueError, match="numeric Dev, Test, or Prod"):
        client.get_realm_configuration(AGENT_ID, 9)


def test_import_package_sends_multipart_create_without_json_content_type(
    tmp_path: Path,
) -> None:
    package = tmp_path / "agent.zip"
    package.write_bytes(b"PK\x03\x04package")
    session = FakeSession(
        [
            FakeResponse(
                {
                    "cdsBotId": AGENT_ID,
                    "schemaName": "gptagent_esshr",
                }
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

    result = client.import_package(package)

    assert result == {
        "responseStatus": "valid",
        "result": {
            "cdsBotId": AGENT_ID,
            "schemaName": "gptagent_esshr",
        },
    }
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["params"] == {"api-version": "2024-10-01"}
    assert "Content-Type" not in call["headers"]
    assert call["data"] == {}
    filename, stream, content_type = call["files"]["package"]
    assert filename == "agent.zip"
    assert stream.closed
    assert content_type == "application/zip"
    assert "json" not in call
    assert call["allow_redirects"] is False


def test_realm_discovery_configuration_and_export_use_native_alm_requests(
    tmp_path: Path,
) -> None:
    package = tmp_path / "agent.zip"
    export_response = FakeResponse({}, content=b"PK\x03\x04package")
    session = FakeSession(
        [
            FakeResponse(
                {
                    "routeRealm": agentbuilder.PROD_REALM,
                    "siblingRealms": [],
                }
            ),
            FakeResponse(
                {
                    "realm": "Prod",
                    "cdsBotId": AGENT_ID,
                    "grsRepositoryId": "family-1",
                }
            ),
            export_response,
        ]
    )
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=session,
    )

    realms = client.get_realms(AGENT_ID)
    configuration = client.get_realm_configuration(
        AGENT_ID,
        agentbuilder.PROD_REALM,
    )
    client.export_package(AGENT_ID, package)

    assert realms["routeRealm"] == agentbuilder.PROD_REALM
    assert configuration["realm"] == "Prod"
    assert session.calls[0]["url"].endswith(
        f"/copilotstudio/minimalBots/alm/{AGENT_ID}/realms"
    )
    assert session.calls[1]["params"] == {
        "api-version": agentbuilder.DEFAULT_API_VERSION,
        "realm": agentbuilder.PROD_REALM,
    }
    export = session.calls[2]
    assert export["method"] == "POST"
    assert export["url"].endswith(
        f"/copilotstudio/minimalBots/alm/{AGENT_ID}/export"
    )
    assert export["params"] == {
        "api-version": agentbuilder.DEFAULT_API_VERSION
    }
    assert export["allow_redirects"] is False
    assert export["stream"] is True
    assert "Content-Type" not in export["headers"]
    assert "POST" not in session.mounts[
        "https://"
    ].max_retries.allowed_methods
    assert package.read_bytes() == b"PK\x03\x04package"
    assert export_response.closed is True


def test_export_preserves_request_error_when_response_close_fails(
    tmp_path: Path,
) -> None:
    response = FakeResponse(
        {"error": {"code": "ExportFailed", "message": "request failed"}},
        status_code=500,
        close_error=OSError("close failed"),
    )
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=FakeSession([response]),
    )

    with pytest.raises(
        agentbuilder.AgentBuilderHTTPError,
        match="Native ALM export failed",
    ) as raised:
        client.export_package(AGENT_ID, tmp_path / "agent.zip")

    assert raised.value.__notes__ == [
        "Native ALM export response cleanup also failed: "
        "OSError: close failed"
    ]


def test_import_package_sends_explicit_replacement_schema(
    tmp_path: Path,
) -> None:
    package = tmp_path / "agent.zip"
    package.write_bytes(b"PK\x03\x04package")
    session = FakeSession(
        [
            FakeResponse(
                {
                    "cdsBotId": AGENT_ID.upper(),
                    "schemaName": "gptagent_existing",
                }
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

    result = client.import_package(
        package,
        replacement_schema_name="gptagent_existing",
    )

    assert result["result"]["cdsBotId"] == AGENT_ID
    assert session.calls[0]["data"] == {
        "schemaName": "gptagent_existing"
    }


def test_import_package_does_not_follow_redirects(
    tmp_path: Path,
) -> None:
    package = tmp_path / "agent.zip"
    package.write_bytes(b"PK\x03\x04package")
    session = FakeSession(
        [
            FakeResponse(
                {},
                status_code=307,
                headers={"Location": "https://attacker.example/import"},
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
        match="HTTP 307",
    ):
        client.import_package(package)

    assert len(session.calls) == 1
    assert session.calls[0]["allow_redirects"] is False


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"cdsBotId": "not-a-guid", "schemaName": "gptagent_esshr"},
        {"cdsBotId": AGENT_ID, "schemaName": ""},
    ],
)
def test_import_package_classifies_invalid_success_shape(
    tmp_path: Path,
    response: dict[str, Any],
) -> None:
    package = tmp_path / "agent.zip"
    package.write_bytes(b"PK\x03\x04package")
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=FakeSession([FakeResponse(response)]),
    )

    outcome = client.import_package(package)

    assert outcome == {
        "responseStatus": "invalid",
        "reason": "invalid-agent-identity",
    }


def test_lists_ring_environments_with_agentbuilder_token() -> None:
    next_url = (
        "https://api.test.powerplatform.com/"
        "environmentmanagement/environments"
        "?api-version=2024-10-01&$skip=1"
    )
    session = FakeSession(
        [
            FakeResponse(
                {
                    "value": [
                        {
                            "id": ENVIRONMENT_ID,
                            "displayName": "First Environment",
                        }
                    ],
                    "@odata.nextlink": next_url,
                }
            ),
            FakeResponse(
                {
                    "value": [
                        {
                            "id": "00000000-0000-4000-8000-000000006666",
                            "displayName": "Second Environment",
                        }
                    ]
                }
            ),
        ]
    )

    environments = agentbuilder.list_environments(
        "fake-token",
        "test",
        session=session,
    )

    assert [environment["displayName"] for environment in environments] == [
        "First Environment",
        "Second Environment",
    ]
    assert [call["url"] for call in session.calls] == [
        (
            "https://api.test.powerplatform.com/"
            "environmentmanagement/environments"
        ),
        next_url,
    ]
    assert all(
        call["headers"]["Authorization"] == "Bearer fake-token"
        for call in session.calls
    )


def test_ring_environment_listing_rejects_unsafe_next_link() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "value": [],
                    "@odata.nextLink": (
                        "https://attacker.example/environmentmanagement/"
                        "environments"
                    ),
                }
            )
        ]
    )

    with pytest.raises(
        agentbuilder.AgentBuilderError,
        match="unsafe continuation URL",
    ):
        agentbuilder.list_environments(
            "fake-token",
            "test",
            session=session,
        )


def test_list_starter_packages_paginates_and_validates_shape() -> None:
    session = FakeSession(
        [
            FakeResponse(
                {
                    "packages": [{"packageId": "pkg-1", "name": "First"}],
                    "continuationToken": "page-2",
                }
            ),
            FakeResponse({"packages": [{"packageId": "pkg-2", "name": "Second"}]}),
        ]
    )
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=session,
    )

    packages = client.list_starter_packages()

    assert [package["packageId"] for package in packages] == ["pkg-1", "pkg-2"]
    assert session.calls[0]["url"].endswith(
        "/copilotstudio/minimalBots/agentStarterPackages"
    )
    assert session.calls[0]["params"] == {
        "api-version": agentbuilder.DEFAULT_API_VERSION,
        "pageSize": 200,
    }
    assert session.calls[1]["params"]["continuationToken"] == "page-2"


@pytest.mark.parametrize(
    "body",
    [
        {"packages": "not-a-list"},
        {"packages": [{"packageId": "ok"}, "not-a-dict"]},
        {"notPackages": []},
        ["not", "a", "dict"],
    ],
)
def test_list_starter_packages_rejects_malformed_shape(body: Any) -> None:
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=FakeSession([FakeResponse(body)]),
    )

    with pytest.raises(agentbuilder.AgentBuilderError, match="invalid shape"):
        client.list_starter_packages()


def test_list_starter_packages_rejects_non_string_continuation_token() -> None:
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=FakeSession(
            [FakeResponse({"packages": [], "continuationToken": 123})]
        ),
    )

    with pytest.raises(agentbuilder.AgentBuilderError, match="continuation token"):
        client.list_starter_packages()


def test_list_starter_packages_bounds_page_count() -> None:
    session = FakeSession(
        [
            FakeResponse({"packages": [], "continuationToken": "next"})
            for _ in range(3)
        ]
    )
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=session,
    )

    with pytest.raises(agentbuilder.AgentBuilderError, match="exceeded 3 pages"):
        client.list_starter_packages(max_pages=3)


def test_create_agent_from_starter_package_sends_one_empty_body_post() -> None:
    session = FakeSession(
        [FakeResponse({"cdsBotId": AGENT_ID, "schemaName": "gptagent_esshr"})]
    )
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=session,
    )

    response = client.create_agent_from_starter_package("pkg-1")

    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(
        "/copilotstudio/minimalBots/agentStarterPackages/pkg-1/create"
    )
    assert call["json"] == {}
    assert call["allow_redirects"] is False
    assert "POST" not in session.mounts["https://"].max_retries.allowed_methods
    # The client returns the raw response untouched -- no parsing, no
    # raising on a non-2xx status -- so the wrapper owns evidence
    # rendering and fuse disposition.
    assert response.json() == {
        "cdsBotId": AGENT_ID,
        "schemaName": "gptagent_esshr",
    }


def test_create_agent_from_starter_package_url_encodes_reserved_characters() -> None:
    session = FakeSession(
        [FakeResponse({"cdsBotId": AGENT_ID, "schemaName": "gptagent_esshr"})]
    )
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=session,
    )

    client.create_agent_from_starter_package("pkg/weird?id#1 two")

    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(
        "/copilotstudio/minimalBots/agentStarterPackages/"
        "pkg%2Fweird%3Fid%231%20two/create"
    )
    # Exactly one path segment for the encoded ID: no unescaped "/" split it.
    encoded_segment = call["url"].rsplit("agentStarterPackages/", 1)[1].split(
        "/create"
    )[0]
    assert "/" not in encoded_segment
    assert call["json"] == {}
    assert call["allow_redirects"] is False
    assert "POST" not in session.mounts["https://"].max_retries.allowed_methods


def test_create_agent_from_starter_package_does_not_raise_on_error_status() -> None:
    session = FakeSession(
        [FakeResponse({"error": {"code": "Conflict"}}, status_code=409)]
    )
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=session,
    )

    response = client.create_agent_from_starter_package("pkg-1")

    assert response.status_code == 409
    assert len(session.calls) == 1


def test_create_agent_from_starter_package_rejects_blank_package_id() -> None:
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=FakeSession([]),
    )

    with pytest.raises(ValueError, match="non-empty string"):
        client.create_agent_from_starter_package("   ")


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
    assert error.value.response is not None
    assert error.value.response.json()["error"]["message"] == (
        "sensitive platform detail"
    )


def test_http_error_carries_raw_response_without_leaking_it_into_str() -> None:
    raw_response = FakeResponse(
        {
            "error": {
                "code": "Forbidden",
                "message": "sensitive platform detail",
            }
        },
        status_code=403,
    )
    client = agentbuilder.AgentBuilderClient(
        HOST,
        "fake-token",
        ring="test",
        tenant_id="00000000-0000-4000-8000-000000009999",
        session=FakeSession([raw_response]),
    )

    with pytest.raises(agentbuilder.AgentBuilderHTTPError) as error:
        client.list_agents()

    assert error.value.response is raw_response
    assert "sensitive platform detail" not in str(error.value)


def test_http_error_response_defaults_to_none_for_existing_callers() -> None:
    error = agentbuilder.AgentBuilderHTTPError("Agent listing", 500)

    assert error.response is None


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


def test_targeted_authentication_can_force_account_selection(
    tmp_path,
    monkeypatch,
) -> None:
    observed: dict[str, Any] = {}

    class FakeApp:
        def __init__(self, client_id, *, authority, token_cache) -> None:
            observed["client_id"] = client_id
            observed["authority"] = authority
            observed["cache"] = token_cache

        def get_accounts(self):
            return [{"username": "cached@example.com"}]

        def acquire_token_silent(self, *_args, **_kwargs):
            raise AssertionError("forced selection must not use cached account")

        def acquire_token_interactive(self, *, scopes, prompt):
            observed["scopes"] = scopes
            observed["prompt"] = prompt
            return {"access_token": "selected-token"}

    monkeypatch.setattr(
        agentbuilder.msal,
        "PublicClientApplication",
        FakeApp,
    )

    result = agentbuilder.authenticate(
        "00000000-0000-4000-8000-000000009999",
        "prod",
        cache_path=tmp_path / "token-cache.bin",
        force_account_selection=True,
    )

    assert result == "selected-token"
    assert observed["authority"].endswith(
        "/00000000-0000-4000-8000-000000009999"
    )
    assert observed["prompt"] == "select_account"
