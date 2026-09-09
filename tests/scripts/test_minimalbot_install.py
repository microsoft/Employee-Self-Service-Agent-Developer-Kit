# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the Dataverse-free (TEST-ring) agent install transport."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class FakeResponse:
    def __init__(self, status_code, payload=None, *, content=b"{}"):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected raise_for_status {self.status_code}")


def _client():
    import minimalbot_install

    client = minimalbot_install.MinimalBotInstallClient("env-guid-123", "tenant-abc")
    client._token = "fake-token"  # bypass interactive auth for unit tests
    return client


def test_requires_environment_id():
    import minimalbot_install

    with pytest.raises(minimalbot_install.MinimalBotInstallError, match="environmentId"):
        minimalbot_install.MinimalBotInstallClient("", "tenant-abc")


def test_from_config_reads_environment_and_tenant():
    import minimalbot_install

    client = minimalbot_install.MinimalBotInstallClient.from_config({
        "environmentId": "env-guid-123",
        "tenantId": "tenant-abc",
    })

    assert client.environment_id == "env-guid-123"
    assert client.tenant_id == "tenant-abc"


def test_calls_before_authenticate_raise():
    import minimalbot_install

    client = minimalbot_install.MinimalBotInstallClient("env-guid-123", "tenant-abc")
    with pytest.raises(minimalbot_install.MinimalBotInstallError, match="authenticate"):
        client.list_environment_application_packages("env-guid-123")


def test_list_packages_unwraps_value_envelope_and_targets_test_ring():
    import minimalbot_install

    client = _client()
    captured = {}

    def fake_get(url, headers=None, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse(200, {"value": [{"uniqueName": "pkg", "state": "None"}]})

    with patch.object(minimalbot_install.requests, "get", fake_get):
        packages = client.list_environment_application_packages("env-guid-123")

    assert packages == [{"uniqueName": "pkg", "state": "None"}]
    assert captured["url"] == (
        "https://api.test.powerplatform.com/appmanagement/environments/"
        "env-guid-123/applicationPackages"
    )
    assert captured["params"] == {"api-version": minimalbot_install.APP_API_VERSION}


def test_list_packages_reports_permission_error():
    import minimalbot_install

    client = _client()
    with patch.object(
        minimalbot_install.requests,
        "get",
        lambda *a, **k: FakeResponse(403, {}),
    ):
        result = client.list_environment_application_packages("env-guid-123")

    assert result == {"_error": "insufficient_permissions", "_status": 403}


def test_install_marks_async_and_extracts_operation_id():
    import minimalbot_install

    client = _client()
    captured = {}

    def fake_post(url, headers=None, params=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse(
            202,
            {"lastOperation": {"operationId": "op-1", "state": "InstallRequested"}},
        )

    with patch.object(minimalbot_install.requests, "post", fake_post):
        result = client.install_application_package("env-guid-123", "pkg")

    assert result["_async"] is True
    assert result["_operationId"] == "op-1"
    assert captured["json"] == {"payloadValue": ""}
    assert captured["url"] == (
        "https://api.test.powerplatform.com/appmanagement/environments/"
        "env-guid-123/applicationPackages/pkg/install"
    )


def test_install_reports_permission_error():
    import minimalbot_install

    client = _client()
    with patch.object(
        minimalbot_install.requests,
        "post",
        lambda *a, **k: FakeResponse(401, {}),
    ):
        result = client.install_application_package("env-guid-123", "pkg")

    assert result == {"_error": "insufficient_permissions", "_status": 401}
