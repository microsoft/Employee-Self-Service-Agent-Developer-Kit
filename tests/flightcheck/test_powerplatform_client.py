# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contract tests for documented Power Platform setup API surfaces."""

from __future__ import annotations

import json

import pytest
import responses

from flightcheck.powerplatform_client import PowerPlatformClient
from flightcheck import powerplatform_client
from tests.conftest import require_validated_mock
from tests.mocks import powerplatform as pp


require_validated_mock(pp)


def _client() -> PowerPlatformClient:
    client = PowerPlatformClient("tenant")
    client._token = "REDACTED_TOKEN"  # noqa: S105 - test fixture
    return client


@pytest.mark.parametrize(
    ("ring", "expected_base"),
    [
        ("prod", "https://api.powerplatform.com"),
        ("preprod", "https://api.preprod.powerplatform.com"),
        ("test", "https://api.test.powerplatform.com"),
    ],
)
def test_client_uses_ring_specific_base_and_scope(
    ring: str,
    expected_base: str,
) -> None:
    client = PowerPlatformClient("tenant", ring=ring)

    assert client.base_url == expected_base
    assert client.scope == f"{expected_base}/.default"


def test_client_rejects_unknown_ring() -> None:
    with pytest.raises(ValueError, match="Unsupported Power Platform ring"):
        PowerPlatformClient("tenant", ring="unknown")


def test_authenticate_uses_preferred_cached_account(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    selected_accounts = []
    requested_scopes = []

    class FakeCache:
        has_state_changed = False

    class FakeApp:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_accounts(self) -> list[dict]:
            return [
                {"username": "other@example.com"},
                {"username": "Maker@Example.com"},
            ]

        def acquire_token_silent(self, scopes, account):
            selected_accounts.append(account)
            requested_scopes.append(scopes)
            return {
                "access_token": "preferred-token",
                "id_token_claims": {
                    "preferred_username": "Maker@Example.com",
                },
            }

        def acquire_token_interactive(self, scopes, **kwargs):
            raise AssertionError("cached preferred account should be reused")

    monkeypatch.setattr(
        powerplatform_client.msal,
        "SerializableTokenCache",
        FakeCache,
    )
    monkeypatch.setattr(
        powerplatform_client.msal,
        "PublicClientApplication",
        FakeApp,
    )

    client = PowerPlatformClient("organizations", ring="test")
    token = client.authenticate(preferred_username="maker@example.com")

    assert token == "preferred-token"
    assert client.signed_in_username == "Maker@Example.com"
    assert selected_accounts == [{"username": "Maker@Example.com"}]
    assert requested_scopes == [
        ["https://api.test.powerplatform.com/.default"]
    ]


@responses.activate
def test_capacity_request_uses_ring_specific_base() -> None:
    environment_id = "00000000-0000-4000-8000-000000001111"
    expected_url = (
        "https://api.preprod.powerplatform.com/licensing/environments/"
        f"{environment_id}/entitlements"
    )
    entitlement = pp.environment_entitlement(allocated=0)
    responses.add(
        method="GET",
        url=expected_url,
        json=[entitlement],
        status=200,
    )
    client = PowerPlatformClient("tenant", ring="preprod")
    client._token = "REDACTED_TOKEN"  # noqa: S105 - test fixture

    assert client.get_environment_entitlements(environment_id)["items"] == [
        entitlement
    ]
    assert responses.calls[0].request.url.startswith(expected_url)


@responses.activate
def test_lists_user_environments_from_documented_contract() -> None:
    expected = pp.environment()
    responses.add(**pp.list_environments_for_user(environments=[expected]))

    result = _client().list_environments_for_user()

    assert result == [expected]


@responses.activate
def test_environment_listing_follows_documented_nextlink_casing() -> None:
    next_url = (
        f"{pp.PP_API_BASE}/environmentmanagement/environments"
        "?api-version=2024-10-01&$skip=1"
    )
    first = pp.environment(environment_id="environment-one")
    second = pp.environment(environment_id="environment-two")
    responses.add(
        **pp.list_environments_for_user(
            environments=[first],
            next_link=next_url,
        )
    )
    responses.add(
        method="GET",
        url=next_url,
        json={"value": [second]},
        status=200,
    )

    result = _client().list_environments_for_user()

    assert result == [first, second]


@responses.activate
def test_collection_permission_error_preserves_request_id() -> None:
    response = pp.list_environments_for_user(status=403)
    response["headers"] = {"x-ms-request-id": "environment-request-403"}
    responses.add(**response)

    result = _client().list_environments_for_user()

    assert result == {
        "_error": "insufficient_permissions",
        "_status": 403,
        "_request_id": "environment-request-403",
    }


@responses.activate
def test_lists_application_packages_from_documented_contract() -> None:
    expected = pp.application_package(state="Installed")
    responses.add(**pp.list_application_packages(packages=[expected]))

    result = _client().list_environment_application_packages(pp.MOCK_ENV_ID)

    assert result == [expected]


@responses.activate
def test_install_application_package_uses_documented_payload() -> None:
    operation = pp.instance_package_operation()
    responses.add(**pp.install_application_package(operation=operation))

    result = _client().install_application_package(
        pp.MOCK_ENV_ID,
        pp.MOCK_PACKAGE_UNIQUE_NAME,
    )

    assert result["lastOperation"] == operation
    assert result["_operationId"] == pp.MOCK_OPERATION_ID
    assert result["_async"] is False
    assert json.loads(responses.calls[0].request.body) == {
        "payloadValue": "",
    }


@responses.activate
def test_install_application_package_handles_documented_202() -> None:
    responses.add(**pp.install_application_package(status=202))

    result = _client().install_application_package(
        pp.MOCK_ENV_ID,
        pp.MOCK_PACKAGE_UNIQUE_NAME,
    )

    assert result == {
        "_async": True,
        "_operationId": None,
    }


@responses.activate
def test_app_management_permission_error_is_explicit() -> None:
    responses.add(**pp.list_application_packages(status=403))

    assert _client().list_environment_application_packages(pp.MOCK_ENV_ID) == {
        "_error": "insufficient_permissions",
        "_status": 403,
    }


@responses.activate
def test_environment_entitlements_preserve_response_evidence() -> None:
    entitlement = pp.environment_entitlement(allocated=500, available=500)
    responses.add(
        **pp.get_environment_entitlements(entitlements=[entitlement])
    )

    result = _client().get_environment_entitlements(pp.MOCK_ENV_ID)

    assert result == {
        "items": [entitlement],
        "_status": 200,
        "_request_id": "entitlement-request-200",
    }


@responses.activate
def test_environment_entitlements_preserve_denied_status() -> None:
    responses.add(**pp.get_environment_entitlements(status=403))

    result = _client().get_environment_entitlements(pp.MOCK_ENV_ID)

    assert result == {
        "_error": "insufficient_permissions",
        "_status": 403,
        "_request_id": "entitlement-request-403",
    }


@responses.activate
def test_environment_entitlements_preserve_not_found_status() -> None:
    responses.add(**pp.get_environment_entitlements(status=404))

    result = _client().get_environment_entitlements(pp.MOCK_ENV_ID)

    assert result == {
        "_error": "not_found",
        "_status": 404,
        "_request_id": "entitlement-request-404",
    }


@responses.activate
def test_environment_entitlements_preserve_no_content_status() -> None:
    responses.add(**pp.get_environment_entitlements(status=204))

    result = _client().get_environment_entitlements(pp.MOCK_ENV_ID)

    assert result == {
        "items": [],
        "_status": 204,
        "_request_id": "entitlement-request-204",
    }
