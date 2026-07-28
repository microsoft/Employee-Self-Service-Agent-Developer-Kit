# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for flightcheck.graph_client.resolve_tenant_display_name_silent.

The helper resolves the tenant's org displayName via a SILENT-ONLY Graph
token so ADK telemetry can carry ``tenant_name`` even when the maker never
runs FlightCheck. It must NEVER trigger an interactive sign-in: if the shared
MSAL cache can't silently satisfy the read scope, it returns "" instead of
prompting. These tests pin the silent-only contract and the best-effort
degradation to "" on every failure mode.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from flightcheck import graph_client


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    # Run in a scratch cwd so the real repo ./.local/.token_cache.bin is never
    # read or written during the test.
    monkeypatch.chdir(tmp_path)


def _fake_app(*, accounts, silent_result):
    app = MagicMock()
    app.get_accounts.return_value = accounts
    app.acquire_token_silent.return_value = silent_result
    # Guardrail: interactive must never be reached in silent-only mode.
    app.acquire_token_interactive.side_effect = AssertionError(
        "silent-only resolver must not prompt interactively"
    )
    return app


def _resp(status_code, payload=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload or {}
    return r


def test_empty_tenant_id_returns_empty():
    assert graph_client.resolve_tenant_display_name_silent("") == ""


def test_no_cached_account_returns_empty_without_prompt():
    app = _fake_app(accounts=[], silent_result=None)
    with patch.object(graph_client.msal, "PublicClientApplication", return_value=app):
        assert graph_client.resolve_tenant_display_name_silent("tenant-Z") == ""
    app.acquire_token_silent.assert_not_called()
    app.acquire_token_interactive.assert_not_called()


def test_silent_token_unavailable_returns_empty_without_prompt():
    app = _fake_app(accounts=[SimpleNamespace()], silent_result=None)
    with patch.object(graph_client.msal, "PublicClientApplication", return_value=app):
        assert graph_client.resolve_tenant_display_name_silent("tenant-Z") == ""
    app.acquire_token_interactive.assert_not_called()


def test_success_returns_display_name():
    app = _fake_app(
        accounts=[SimpleNamespace()], silent_result={"access_token": "tok"}
    )
    resp = _resp(200, {"value": [{"displayName": "Contoso Ltd"}]})
    with patch.object(graph_client.msal, "PublicClientApplication", return_value=app), \
         patch.object(graph_client._SESSION, "get", return_value=resp) as mock_get:
        assert (
            graph_client.resolve_tenant_display_name_silent("tenant-Z") == "Contoso Ltd"
        )
    # Requested only the minimal Organization.Read.All scope.
    app.acquire_token_silent.assert_called_once_with(
        graph_client._ORG_READ_SCOPE, account=app.get_accounts.return_value[0]
    )
    mock_get.assert_called_once()
    app.acquire_token_interactive.assert_not_called()


def test_non_200_response_returns_empty():
    app = _fake_app(
        accounts=[SimpleNamespace()], silent_result={"access_token": "tok"}
    )
    with patch.object(graph_client.msal, "PublicClientApplication", return_value=app), \
         patch.object(graph_client._SESSION, "get", return_value=_resp(403)):
        assert graph_client.resolve_tenant_display_name_silent("tenant-Z") == ""


def test_empty_org_list_returns_empty():
    app = _fake_app(
        accounts=[SimpleNamespace()], silent_result={"access_token": "tok"}
    )
    with patch.object(graph_client.msal, "PublicClientApplication", return_value=app), \
         patch.object(graph_client._SESSION, "get", return_value=_resp(200, {"value": []})):
        assert graph_client.resolve_tenant_display_name_silent("tenant-Z") == ""


def test_exception_is_swallowed_returns_empty():
    with patch.object(
        graph_client.msal, "PublicClientApplication", side_effect=RuntimeError("boom")
    ):
        assert graph_client.resolve_tenant_display_name_silent("tenant-Z") == ""
