# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
import responses

from flightcheck import azure_arm_client


def test_authentication_accepts_an_explicit_cache_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache = Mock()
    cache.has_state_changed = False
    app = Mock()
    app.get_accounts.return_value = []
    app.acquire_token_interactive.return_value = {
        "access_token": "arm-token",
    }
    observed: dict[str, object] = {}

    def public_client(client_id, *, authority, token_cache):
        observed.update(
            client_id=client_id,
            authority=authority,
            token_cache=token_cache,
        )
        return app

    monkeypatch.setattr(
        azure_arm_client.msal,
        "SerializableTokenCache",
        lambda: cache,
    )
    monkeypatch.setattr(
        azure_arm_client.msal,
        "PublicClientApplication",
        public_client,
    )
    cache_path = tmp_path / "organization-token-cache.bin"

    client = azure_arm_client.AzureArmClient(
        "organizations",
        cache_path=cache_path,
    )

    assert client.authenticate() == "arm-token"
    assert observed["authority"] == (
        "https://login.microsoftonline.com/organizations"
    )
    app.acquire_token_interactive.assert_called_once_with(
        [azure_arm_client.ARM_SCOPE],
        prompt="select_account",
    )


@responses.activate
def test_list_tenants_follows_documented_arm_pagination() -> None:
    first_url = (
        f"{azure_arm_client.ARM_BASE}/tenants"
        f"?api-version={azure_arm_client.API_VERSION}"
    )
    next_url = (
        f"{azure_arm_client.ARM_BASE}/tenants"
        f"?api-version={azure_arm_client.API_VERSION}&$skiptoken=next"
    )
    first_tenant = {
        "tenantId": "00000000-0000-4000-8000-000000001111",
        "displayName": "Contoso",
        "defaultDomain": "contoso.onmicrosoft.com",
    }
    second_tenant = {
        "tenantId": "00000000-0000-4000-8000-000000002222",
        "displayName": "Fabrikam",
        "defaultDomain": "fabrikam.onmicrosoft.com",
    }
    responses.get(
        first_url,
        json={"value": [first_tenant], "nextLink": next_url},
        status=200,
    )
    responses.get(
        next_url,
        json={"value": [second_tenant]},
        status=200,
    )
    client = azure_arm_client.AzureArmClient("organizations")
    client._token = "arm-token"

    assert client.list_tenants() == [first_tenant, second_tenant]


@responses.activate
def test_list_tenants_rejects_cross_host_next_link() -> None:
    first_url = (
        f"{azure_arm_client.ARM_BASE}/tenants"
        f"?api-version={azure_arm_client.API_VERSION}"
    )
    responses.get(
        first_url,
        json={
            "value": [],
            "nextLink": "https://example.com/tenants?skiptoken=unsafe",
        },
        status=200,
    )
    client = azure_arm_client.AzureArmClient("organizations")
    client._token = "arm-token"

    with pytest.raises(RuntimeError, match="unsafe continuation"):
        client.list_tenants()
