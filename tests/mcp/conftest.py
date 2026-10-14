# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Keep MCP tests independent of real maker configuration and authentication."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import msal
import pytest
import requests


CORE_DIR = (
    Path(__file__).resolve().parents[2]
    / "solutions" / "ess-maker-skills" / "src" / "mcp" / "agentconfig_core"
)
sys.path.insert(0, str(CORE_DIR))

import _tenant_context  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_mcp_identity(monkeypatch, tmp_path) -> None:
    # Legacy consumer tests have no workspace config. Keep that fallback
    # deterministic without ever reading a developer's real config or token.
    monkeypatch.setattr(_tenant_context, "_CONFIG_PATH", tmp_path / "config.json")
    for name in (
        "AGENTCONFIG_ACCESS_TOKEN_FILE",
        "AGENTCONFIG_ACCESS_TOKEN",
        "GRAPH_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)

    def unmocked_auth_or_network(*args, **kwargs):
        pytest.fail("MCP tests must mock authentication, discovery, and network I/O")

    monkeypatch.setattr(_tenant_context, "discover_tenant", unmocked_auth_or_network)
    monkeypatch.setattr(msal, "PublicClientApplication", unmocked_auth_or_network)
    monkeypatch.setattr(requests.sessions.Session, "request", unmocked_auth_or_network)
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", unmocked_auth_or_network
    )
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", unmocked_auth_or_network
    )
