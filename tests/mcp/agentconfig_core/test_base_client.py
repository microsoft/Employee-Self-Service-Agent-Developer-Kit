# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the neutral AgentConfiguration client core (auth + token cache).

The token-flow behaviour — the shared MSAL cache location and the interactive
form-post sign-in — lives on the neutral ``AgentConfigBaseClient`` core under ``agentconfig_core/`` and
is shared by every AgentConfiguration MCP (landing-page config and planner), so it is
pinned here against ``base_client`` directly rather than any one server's client.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[3]
CORE_DIR = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_core"
)
sys.path.insert(0, str(CORE_DIR))

import base_client  # noqa: E402


def test_token_cache_uses_shared_local_state() -> None:
    assert Path(base_client._TOKEN_CACHE_PATH) == (
        REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "mcp"
        / "agentconfig_core"
        / ".local"
        / "msal_token_cache.bin"
    )


def test_interactive_auth_always_prompts_for_account_selection(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        server_port = 12345

        def handle_request(self) -> None:
            base_client._FormPostCaptureHandler.captured = {
                "code": "authorization-code"
            }

        def server_close(self) -> None:
            pass

    class FakeApp:
        def initiate_auth_code_flow(self, **kwargs):
            captured.update(kwargs)
            return {"auth_uri": "https://login.example.test"}

        def acquire_token_by_auth_code_flow(self, flow, response):
            return {"access_token": "token"}

    monkeypatch.setattr(
        base_client.http.server,
        "HTTPServer",
        lambda *args: FakeServer(),
    )
    monkeypatch.setattr(base_client.webbrowser, "open", lambda url: True)

    result = base_client._acquire_token_interactive_form_post(FakeApp())

    assert result == {"access_token": "token"}
    assert captured["prompt"] == "select_account"
