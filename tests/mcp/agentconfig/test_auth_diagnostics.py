# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline auth diagnostics through the registered plain and widget MCP handlers."""

from __future__ import annotations

import asyncio
import base64
import errno
import json
import logging
import sys
from pathlib import Path
from unittest.mock import Mock, mock_open

import httpx
import pytest
import requests
from mcp.types import CallToolRequest, CallToolRequestParams
from portalocker.exceptions import LockException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _mcp_modules import load_landing_page_modules  # noqa: E402

_MODULES = load_landing_page_modules()
server = _MODULES["server"]
import base_client  # noqa: E402


TENANT = "00000000-0000-0000-0000-000000001111"
OTHER_TENANT = "00000000-0000-0000-0000-000000002222"
OID = "00000000-0000-0000-0000-000000003333"
PRIVATE = "PRIVATE-AUTH-DIAGNOSTIC"
GENERIC = "Could not renew credentials for the original account."
INVALID = "malformed or has no valid tenant id"


def _payload_token(payload: bytes) -> str:
    return f"header.{base64.urlsafe_b64encode(payload).decode().rstrip('=')}.signature"


def _token(**claims) -> str:
    return _payload_token(json.dumps({"tid": TENANT, "oid": OID, "private": PRIVATE, **claims}).encode())


async def _call_tool(tool):
    request = CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=tool, arguments={"titleId": "synthetic-agent"}),
    )
    return (await server.mcp._mcp_server.request_handlers[CallToolRequest](request)).root


@pytest.mark.parametrize("tool", ["get_agent_config", "open_accent_color"])
@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("file-missing", "AGENTCONFIG_ACCESS_TOKEN_FILE does not exist. Restore"),
        ("file-open", "AGENTCONFIG_ACCESS_TOKEN_FILE could not be read. Check"),
        ("file-read", "AGENTCONFIG_ACCESS_TOKEN_FILE could not be read. Check"),
        ("file-encoding", "AGENTCONFIG_ACCESS_TOKEN_FILE could not be read. Check"),
        ("file-empty", "AGENTCONFIG_ACCESS_TOKEN_FILE is empty. Provide"),
        ("bad-segments", INVALID),
        ("bad-base64", INVALID),
        ("non-ascii", INVALID),
        ("bad-utf8", INVALID),
        ("bad-json", INVALID),
        ("non-object", INVALID),
        ("missing-tenant", INVALID),
        ("invalid-tenant", INVALID),
        ("tenant-mismatch", "does not match the original tenant"),
        ("account-mismatch", "does not identify the original account"),
        ("missing-oid", "does not identify the original account"),
        ("cache-lock", "credential cache could not be locked. Retry"),
        ("access-denied", "Local credential access failed. Check"),
        ("missing-resource", "Local credential access failed. Check"),
        ("unknown-value", GENERIC),
        ("unknown-os", GENERIC),
        ("network-os", GENERIC),
        ("unchanged", "No replacement access token is available."),
        ("missing-original-oid", "original account cannot be identified"),
        ("success", None),
    ],
)
def test_refresh_diagnostics_survive_mcp_serialization(
    monkeypatch, tmp_path, caplog, capsys, tool, failure, message
):
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: TENANT)
    interactive = Mock(side_effect=AssertionError("No interactive fallback"))
    monkeypatch.setattr(base_client, "acquire_token_msal_interactive", interactive)
    caplog.set_level(logging.DEBUG)
    initial = _token(version="initial", oid=None if failure == "missing-original-oid" else OID)
    replacement = _token(version="replacement")
    path = tmp_path / PRIVATE
    underlying = {
        "cache-lock": LockException(PRIVATE),
        "access-denied": PermissionError(errno.EACCES, PRIVATE, str(path)),
        "missing-resource": FileNotFoundError(errno.ENOENT, PRIVATE, str(path)),
        "unknown-value": ValueError(f"AGENTCONFIG_ACCESS_TOKEN_FILE does not exist. {PRIVATE}"),
        "unknown-os": OSError(errno.EIO, PRIVATE, str(path)),
        "network-os": requests.RequestException(PRIVATE),
    }.get(failure)
    refresh_msal = Mock(side_effect=underlying or AssertionError("No MSAL fallback"))
    monkeypatch.setattr(base_client, "_refresh_msal_token", refresh_msal)
    if underlying is not None:
        monkeypatch.setattr(base_client, "_resolve_token", lambda: initial)
    elif failure.startswith("file-"):
        path.write_text(initial, encoding="utf-8")
        monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN_FILE", str(path))
    else:
        monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", initial)

    sent = []

    def transport(request):
        sent.append(request.headers["Authorization"])
        return httpx.Response(401 if len(sent) == 1 else 200, json={"ok": True})

    client = _MODULES["client"].AgentConfigClient(transport=httpx.MockTransport(transport))
    monkeypatch.setattr(server, "get_client", lambda: client)
    if failure == "file-missing":
        path.unlink()
    elif failure in ("file-open", "file-read"):
        underlying = PermissionError(errno.EACCES, PRIVATE, str(path))
        handle = mock_open(read_data=initial)
        if failure == "file-open":
            handle.side_effect = underlying
        else:
            handle.return_value.read.side_effect = underlying
        monkeypatch.setattr(base_client, "open", handle, raising=False)
    elif failure == "file-empty":
        path.write_text("", encoding="utf-8")
    elif failure == "file-encoding":
        path.write_bytes(b"\xff" + PRIVATE.encode())
    else:
        replacement = {
            "bad-segments": PRIVATE,
            "bad-base64": "header.a.signature",
            "non-ascii": f"header.{PRIVATE}\N{LATIN SMALL LETTER E WITH ACUTE}.signature",
            "bad-utf8": _payload_token(b"\xff"),
            "bad-json": _payload_token(f'{{"private":"{PRIVATE}",'.encode()),
            "non-object": _payload_token(b"[]"),
            "missing-tenant": _token(tid=None),
            "invalid-tenant": _token(tid=PRIVATE),
            "tenant-mismatch": _token(tid=OTHER_TENANT),
            "account-mismatch": _token(oid=PRIVATE),
            "missing-oid": _token(oid=None),
            "unchanged": initial,
        }.get(failure, replacement)
    # File-based renewal must not fall back to this valid environment token.
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", replacement)
    errors = []
    refresh = client._refresh_token

    async def capture_refresh(rejected_token):
        try:
            await refresh(rejected_token)
        except base_client.AgentConfigApiError as error:
            errors.append(error)
            raise

    monkeypatch.setattr(client, "_refresh_token", capture_refresh)

    async def run():
        try:
            return await _call_tool(tool)
        finally:
            await client.aclose()

    result = asyncio.run(run())
    interactive.assert_not_called()
    if failure in {"cache-lock", "access-denied", "missing-resource", "unknown-value", "unknown-os", "network-os"}:
        refresh_msal.assert_called_once_with(TENANT, OID)
    else:
        refresh_msal.assert_not_called()
    assert client.tenant_id == TENANT
    assert client.object_id == (None if failure == "missing-original-oid" else OID)
    if message is None:
        assert not result.isError and not errors
        assert sent == [f"Bearer {initial}", f"Bearer {replacement}"]
        assert client._token == replacement
    else:
        assert result.isError
        assert message in result.content[0].text
        assert sent == [f"Bearer {initial}"]
        assert client._token == initial
        assert errors[0].http_status == 401
        if underlying is not None:
            cause = errors[0].__cause__
            assert cause is underlying or cause.__cause__ is underlying
        elif failure not in {"unchanged", "missing-original-oid"}:
            assert isinstance(errors[0].__cause__, ValueError)
            if failure in {"bad-base64", "non-ascii", "bad-utf8", "bad-json", "invalid-tenant", "file-encoding"}:
                assert isinstance(errors[0].__cause__.__cause__, ValueError)
        if tool == "open_accent_color":
            assert result.structuredContent == {"error": {
                "code": "AgentConfigurationError",
                "message": str(errors[0]),
                "retryable": False,
                "httpStatus": 401,
            }}
        else:
            assert result.structuredContent is None
    output = result.model_dump_json() + caplog.text + "".join(capsys.readouterr())
    for private in (PRIVATE, str(path), initial, replacement):
        assert private not in output


@pytest.mark.parametrize("tool", ["get_agent_config", "open_accent_color"])
@pytest.mark.parametrize("failure", ["local-timeout", "timeout", "unknown", None, 408, {"code": "timeout"}])
def test_only_the_local_callback_timeout_gets_a_timeout_diagnostic(
    monkeypatch, caplog, capsys, tool, failure
):
    monkeypatch.setattr(base_client, "configured_tenant_id", lambda: TENANT)
    monkeypatch.setattr(server, "_client", None)
    caplog.set_level(logging.DEBUG)

    class FakeServer:
        server_port = 12345
        closed = False

        def handle_request(self):
            if failure != "local-timeout":
                base_client._FormPostCaptureHandler.captured = {"code": PRIVATE}

        def server_close(self):
            self.closed = True

    app = Mock()
    app.get_accounts.return_value = []
    app.initiate_auth_code_flow.return_value = {"auth_uri": "https://login.example.test"}
    app.acquire_token_by_auth_code_flow.return_value = {"error": failure, "error_description": PRIVATE}
    listener = FakeServer()
    monkeypatch.setattr(base_client, "_create_msal_app", lambda tenant: app)
    monkeypatch.setattr(base_client.http.server, "HTTPServer", lambda *args: listener)
    monkeypatch.setattr(base_client.webbrowser, "open", lambda url: True)
    result = asyncio.run(_call_tool(tool))
    assert result.isError and listener.closed
    message = result.content[0].text
    if failure == "local-timeout":
        assert "sign-in timed out waiting for the browser callback" in message
        app.acquire_token_by_auth_code_flow.assert_not_called()
    else:
        assert "sign-in failed. Sign in again and retry." in message
        assert "timed out" not in message
        app.acquire_token_by_auth_code_flow.assert_called_once()
    if tool == "open_accent_color":
        assert result.structuredContent["error"] == {
            "code": "InvalidRequest", "message": message, "retryable": False,
        }
    else:
        assert result.structuredContent is None
    assert PRIVATE not in result.model_dump_json() + caplog.text + "".join(capsys.readouterr())


@pytest.mark.parametrize("object_id", [None, ""])
def test_standalone_identity_validation_requires_an_expected_account(object_id):
    with pytest.raises(ValueError, match="authoring account cannot be identified"):
        base_client.validate_token_identity(_token(), TENANT, object_id)
