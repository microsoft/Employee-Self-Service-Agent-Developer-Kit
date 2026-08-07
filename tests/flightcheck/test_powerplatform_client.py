# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contract tests for documented Power Platform setup API surfaces."""

from __future__ import annotations

import json

import responses

from flightcheck.powerplatform_client import PowerPlatformClient
from tests.conftest import require_validated_mock
from tests.mocks import powerplatform as pp


require_validated_mock(pp)


def _client() -> PowerPlatformClient:
    client = PowerPlatformClient("tenant")
    client._token = "REDACTED_TOKEN"  # noqa: S105 - test fixture
    return client


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
