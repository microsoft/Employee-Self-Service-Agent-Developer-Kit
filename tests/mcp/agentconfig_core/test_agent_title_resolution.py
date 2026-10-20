# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Provider-independent contracts for the shared title resolver."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest

import agent_title_resolution as resolution


BOT_ID = "aaaaaaaa-0000-4000-8000-000000004444"
OTHER_BOT_ID = "bbbbbbbb-0000-4000-8000-000000005555"
REGULAR_ID = "T_00000000-0000-0000-0000-000000006666"
LOB_ID = "T_00000000-0000-0000-0000-000000007777"
ENDPOINT = "https://orgmocktenant.crm.dynamics.com"
OTHER_ENDPOINT = "https://orgother.crm.dynamics.com"
TENANT_ID = "11111111-2222-3333-4444-555555555555"
OBJECT_ID = "00000000-0000-0000-0000-000000003333"


def test_shared_resolver_has_no_feature_client_or_mcp_dependency():
    path = Path(resolution.__file__).resolve()
    assert path.parent.name == "agentconfig_core"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not imports.intersection({"client", "validation", "drafts", "server"})
    assert not any(name and name.startswith("mcp") for name in imports)


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"titleId": REGULAR_ID, "lobTitleId": LOB_ID},
         {"titleId": REGULAR_ID, "lobTitleId": LOB_ID}),
        ({"titleId": REGULAR_ID}, {"titleId": REGULAR_ID, "lobTitleId": None}),
        ({"lobTitleId": LOB_ID}, {"titleId": None, "lobTitleId": LOB_ID}),
        ({"titleId": None, "lobTitleId": LOB_ID},
         {"titleId": None, "lobTitleId": LOB_ID}),
    ],
)
def test_shared_lookup_reads_both_titles_without_writing_configuration(
    tmp_path, monkeypatch, metadata, expected
):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "setup": "complete",
        "activeAgent": "other",
        "agent": {"botId": OTHER_BOT_ID, "slug": "other"},
        "agents": [
            {"botId": BOT_ID, "slug": "selected", "dataverseEndpoint": ENDPOINT},
            {"botId": OTHER_BOT_ID, "slug": "other",
             "dataverseEndpoint": OTHER_ENDPOINT},
        ],
        "dataverseEndpoint": OTHER_ENDPOINT,
    }), encoding="utf-8")
    monkeypatch.setattr(resolution, "CONFIG_PATH", config_path)
    before = config_path.read_bytes()
    calls = []

    def token(endpoint, tenant_id, object_id):
        assert (endpoint, tenant_id, object_id) == (ENDPOINT, TENANT_ID, OBJECT_ID)
        return "test-resource-token"

    def read(endpoint, resource_token, path, *, params):
        calls.append((endpoint, path, params))
        assert resource_token == "test-resource-token"
        return {
            "botid": BOT_ID,
            "applicationmanifestinformation": json.dumps({"microsoft365": metadata}),
        }

    monkeypatch.setattr(resolution, "acquire_dataverse_token", token)
    monkeypatch.setattr(resolution, "dataverse_get", read)
    result = resolution.resolve_configured_agent_title(
        resolution.load_configured_target(BOT_ID), TENANT_ID, OBJECT_ID
    )

    assert result == {"botId": BOT_ID, **expected}
    assert calls == [(
        ENDPOINT, f"bots({BOT_ID})",
        {"$select": "botid,applicationmanifestinformation"},
    )]
    assert config_path.read_bytes() == before


def test_shared_browser_timeout_is_finite_and_sanitized(monkeypatch):
    class App:
        def acquire_token_silent(self, scopes, *, account):
            return None

        def acquire_token_interactive(self, scopes, *, prompt, timeout):
            assert scopes == [f"{ENDPOINT}/user_impersonation"]
            assert prompt == "select_account"
            assert timeout == 300
            raise RuntimeError("Timeout. PRIVATE_SDK_DIAGNOSTIC")

    monkeypatch.setattr(resolution, "_create_msal_app", lambda tenant_id: App())
    monkeypatch.setattr(resolution, "account_for_identity", lambda *args: object())

    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.acquire_dataverse_token(ENDPOINT, TENANT_ID, OBJECT_ID)

    assert caught.value.code == "AuthenticationRequired"
    assert "300 seconds" in str(caught.value)
    assert "PRIVATE_SDK_DIAGNOSTIC" not in str(caught.value)


def test_shared_coordinator_tracks_cancelled_work_and_isolates_provider_instances():
    async def run():
        coordinator = resolution.TitleResolutionCoordinator()
        other_provider = resolution.TitleResolutionCoordinator()
        started = asyncio.Event()
        finish = asyncio.Event()
        expected = {"botId": BOT_ID, "titleId": REGULAR_ID, "lobTitleId": LOB_ID}

        async def operation():
            started.set()
            await finish.wait()
            return expected

        async def immediate():
            return expected

        caller = asyncio.create_task(coordinator.run(operation))
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            pending = coordinator._task
            assert pending is not None and not pending.done()
            with pytest.raises(resolution.AgentTitleResolutionError, match="in progress"):
                await coordinator.run(immediate)
            assert await other_provider.run(immediate) == expected
            finish.set()
            assert await asyncio.wait_for(asyncio.shield(pending), timeout=2) == expected
            await asyncio.sleep(0)
            assert coordinator._task is None
            assert await coordinator.run(immediate) == expected
        finally:
            finish.set()

    asyncio.run(run())
