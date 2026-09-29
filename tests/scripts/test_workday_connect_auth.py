# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Workday connect identity continuity."""

from __future__ import annotations

import base64
import json

import pytest


def _token(username: str, tenant_id: str = "tenant-id") -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {"preferred_username": username, "tid": tenant_id}
        ).encode()
    ).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_token_identity_returns_only_safe_provenance() -> None:
    import workday_connect_auth as auth

    assert auth.token_identity(_token("maker@example.com")) == {
        "username": "maker@example.com",
        "tenantId": "tenant-id",
    }


def test_require_identity_rejects_wrong_account() -> None:
    import workday_connect_auth as auth

    with pytest.raises(auth.WorkdayConnectIdentityError, match="different account"):
        auth.require_identity(
            _token("other@example.com"),
            preferred_username="maker@example.com",
        )


def test_authentication_plan_distinguishes_credential_stores() -> None:
    import workday_connect_auth as auth

    stores = {item["store"] for item in auth.authentication_plan()}

    assert stores == {
        "azure-cli-graph",
        "pac",
        "dataverse-msal",
        "workday-connector",
    }
