# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Native DA contracts from confirmed read-only Studio probes; no tenant calls."""

from __future__ import annotations

import ast
import asyncio
import base64
import copy
import json
from pathlib import Path

import pytest
import requests

import agent_title_resolution as resolution
import _tenant_context
import base_client


BOT_ID = "aaaaaaaa-0000-4000-8000-000000004444"
OTHER_BOT_ID = "bbbbbbbb-0000-4000-8000-000000005555"
ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
TENANT_ID = "11111111-2222-3333-4444-555555555555"
OBJECT_ID = "00000000-0000-0000-0000-000000003333"
REGULAR_ID = "T_00000000-0000-0000-0000-000000006666"
LOB_ID = "T_00000000-0000-0000-0000-000000007777"
HOST = (
    "https://0000000000004000800000000000111."
    "1.environment.api.test.powerplatform.com"
)


@pytest.fixture
def configured(tmp_path, monkeypatch):
    agent = {
        "botId": BOT_ID, "slug": "selected", "environmentId": ENVIRONMENT_ID,
        "powerPlatformApiEndpoint": HOST, "releaseLine": "da",
    }
    config = {
        "setup": "complete", "releaseLine": "da", "ring": "test",
        "environmentId": ENVIRONMENT_ID, "powerPlatformApiEndpoint": HOST,
        "activeAgent": "selected", "agent": copy.deepcopy(agent), "agents": [agent],
        "unrelated": {"preserve": [1, 2]},
    }
    canonical = {
        "schema_version": 4,
        "environment": {
            "id": ENVIRONMENT_ID, "tenant_id": TENANT_ID,
            "power_platform_api_endpoint": HOST, "ring": "test",
        },
        "agents": {BOT_ID: {"agent": {"id": BOT_ID}}},
    }
    path = tmp_path / "config.json"
    setup = tmp_path / "setup" / "config.json"
    setup.parent.mkdir()
    path.write_text(json.dumps(config), encoding="utf-8")
    setup.write_text(json.dumps(canonical), encoding="utf-8")
    monkeypatch.setattr(resolution, "CONFIG_PATH", path)
    monkeypatch.setattr(_tenant_context, "_CONFIG_PATH", path)
    return path, setup


def _response(body, status=200):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.headers["request-id"] = "PRIVATE_REQUEST_DETAIL"
    return response


class _Session:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.closed = False

    def mount(self, *args):
        pass

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


def _install_session(monkeypatch, *, regular=REGULAR_ID, lob=LOB_ID, replies=None):
    # Components bot.cdsBotId/teamsAppInformation are also cassette-backed in
    # agentbuilder_readiness.yaml. The separate publish-status GET/titleId
    # mapping was verified from Studio fetchM365PublishStatus and DA/CEA reads.
    session = _Session(replies if replies is not None else [
        _response({"botId": BOT_ID}),
        _response({"bot": {
            "cdsBotId": BOT_ID,
            "teamsAppInformation": {"microsoft365": {
                "titleId": regular, "lobTitleId": "not-the-native-lob-source",
            }},
        }}),
        _response({"titleId": lob}),
    ])
    monkeypatch.setattr(resolution.requests, "Session", lambda: session)
    monkeypatch.setattr(
        resolution, "acquire_power_platform_token",
        lambda ring, tenant, account: "test-resource-token",
    )
    return session


def _lookup():
    return resolution.resolve_configured_agent_title(
        resolution.load_configured_target(BOT_ID), TENANT_ID, OBJECT_ID
    )


def test_shared_resolver_has_no_feature_or_mcp_dependency():
    path = Path(resolution.__file__).resolve()
    assert path.parent.name == "agentconfig_core"
    imports = {
        node.module for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
    }
    assert not imports.intersection({"client", "validation", "drafts", "server"})
    assert not any(name and name.startswith("mcp") for name in imports)


@pytest.mark.parametrize(
    ("regular", "lob"),
    [(REGULAR_ID, LOB_ID), (REGULAR_ID, None), (None, LOB_ID), (" ", LOB_ID),
     (REGULAR_ID, REGULAR_ID)],
)
def test_native_lookup_keeps_separate_registrations_and_never_writes(
    configured, monkeypatch, regular, lob
):
    before = [path.read_bytes() for path in configured]
    session = _install_session(monkeypatch, regular=regular, lob=lob)
    assert _lookup() == {
        "botId": BOT_ID, "titleId": regular if regular and regular.strip() else None,
        "lobTitleId": lob,
    }
    assert [path.read_bytes() for path in configured] == before
    assert session.closed
    assert [(method, url.removeprefix(HOST)) for method, url, _ in session.calls] == [
        ("GET", f"/copilotstudio/minimalBots/api/{BOT_ID}"),
        ("POST", f"/copilotstudio/minimalBots/api/{BOT_ID}/components"),
        ("GET", f"/copilotstudio/agents/{BOT_ID}/channels/m365/publish"),
    ]
    assert [call[2]["params"] for call in session.calls] == [
        {"api-version": "2024-10-01"},
        {"api-version": "2022-03-01-preview"},
        {"api-version": "2024-10-01"},
    ]
    assert session.calls[1][2]["json"] == {}
    headers = session.calls[2][2]["headers"]
    assert headers["X-CCI-CdsBotId"] == BOT_ID
    assert headers["x-ms-client-name"] == "CopilotStudio"
    assert headers["Accept"] == "application/json"
    assert headers["Authorization"].endswith("test-resource-token")
    assert session.calls[2][2]["allow_redirects"] is False
    assert all(0 < call[2]["timeout"] <= 180 for call in session.calls)


def test_da_only_tenant_binding_never_discovers_dataverse(configured):
    assert _tenant_context.configured_tenant_id() == TENANT_ID
    target = resolution.load_configured_target(BOT_ID.upper())
    assert (target.bot_id, target.environment_id, target.host, target.ring) == (
        BOT_ID, ENVIRONMENT_ID, HOST, "test",
    )


@pytest.mark.parametrize("bot_id", ["", "not-a-guid", "0" * 32, None, 42])
def test_invalid_bot_never_reaches_metadata(bot_id):
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.load_configured_target(bot_id)
    assert caught.value.code == "InvalidRequest"


@pytest.mark.parametrize("change", ["duplicate", "absent", "malformed", "incomplete", "ca"])
def test_target_binding_requires_exactly_one_completed_da_agent(configured, change):
    path, _ = configured
    config = json.loads(path.read_text())
    if change == "duplicate":
        config["agents"].append({**config["agents"][0], "botId": BOT_ID.upper()})
    elif change == "absent":
        config["agents"] = []
        config.pop("agent")
    elif change == "malformed":
        config["agents"] = {}
    elif change == "incomplete":
        config["setup"] = "in-progress"
    else:
        config["releaseLine"] = "ca"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.load_configured_target(BOT_ID)
    assert caught.value.code == "InvalidRequest"


def test_legacy_active_object_is_supported_only_in_canonical_da_environment(configured):
    path, _ = configured
    config = json.loads(path.read_text())
    config.pop("agents")
    path.write_text(json.dumps(config), encoding="utf-8")
    assert resolution.load_configured_target(BOT_ID).tenant_id == TENANT_ID


@pytest.mark.parametrize(
    ("surface", "field", "value"),
    [
        ("agent", "environmentId", OTHER_BOT_ID),
        ("agent", "powerPlatformApiEndpoint", "https://private.example"),
        ("agent", "ring", "prod"),
        ("agent", "releaseLine", "ca"),
        ("root", "environmentId", OTHER_BOT_ID),
        ("root", "ring", "prod"),
        ("root", "powerPlatformApiEndpoint", HOST.replace("0111.", "0222.")),
        ("canonical", "id", OTHER_BOT_ID),
        ("canonical", "tenant_id", "not-a-guid"),
        ("canonical", "power_platform_api_endpoint", "https://private.example"),
    ],
)
def test_conflicting_environment_mirrors_fail_closed(
    configured, surface, field, value
):
    path, setup = configured
    config, canonical = json.loads(path.read_text()), json.loads(setup.read_text())
    target = (
        config["agents"][0] if surface == "agent"
        else canonical["environment"] if surface == "canonical"
        else config
    )
    target[field] = value
    path.write_text(json.dumps(config), encoding="utf-8")
    setup.write_text(json.dumps(canonical), encoding="utf-8")
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.load_configured_target(BOT_ID)
    assert caught.value.code == "InvalidRequest"
    assert "private.example" not in str(caught.value)


@pytest.mark.parametrize("missing", ["file", "agent"])
def test_missing_canonical_state_never_cross_switches_backend(configured, missing):
    _, setup = configured
    if missing == "file":
        setup.unlink()
    else:
        value = json.loads(setup.read_text())
        value["agents"] = {}
        setup.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(resolution.AgentTitleResolutionError):
        resolution.load_configured_target(BOT_ID)


def test_invalid_da_setup_prevents_unrestricted_authoring_sign_in(
    configured, monkeypatch, caplog
):
    _, setup = configured
    setup.unlink()
    monkeypatch.setattr(
        base_client, "_create_msal_app",
        lambda *args: pytest.fail("invalid DA state reached unrestricted sign-in"),
    )
    with pytest.raises(base_client.LocalCredentialError, match="DA setup environment"):
        base_client._resolve_token()
    assert "unrestricted" not in caplog.text


@pytest.mark.parametrize(
    ("stage", "status", "code"),
    [
        (stage, status, code)
        for stage in range(3)
        for status, code in [
            (401, "AuthenticationRequired"), (403, "AuthorizationDenied"),
            (404, "NotFound"), (429, "ServiceError"), (500, "ServiceError"),
        ]
    ] + [(2, 302, "ServiceError")],
)
def test_native_http_errors_are_sanitized_without_fallback(
    configured, monkeypatch, caplog, stage, status, code
):
    session = _install_session(monkeypatch)
    session.replies[stage] = _response(
        {"error": {"code": "PRIVATE_BACKEND_DETAIL"}}, status
    )
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        _lookup()
    assert caught.value.code == code
    assert len(session.calls) == stage + 1
    assert session.closed
    assert "PRIVATE" not in str(caught.value) + caplog.text
    if status == 404:
        assert "does not establish that a registration is absent" in str(caught.value)


@pytest.mark.parametrize(
    ("stage", "body"),
    [
        (0, {"botId": OTHER_BOT_ID}),
        (0, {}),
        (1, {"bot": {"cdsBotId": OTHER_BOT_ID}}),
        (1, {"bot": {"id": BOT_ID}}),
        (1, {"bot": {"cdsBotId": BOT_ID, "teamsAppInformation": "invalid"}}),
        (1, {"bot": {"cdsBotId": BOT_ID, "teamsAppInformation": {"microsoft365": []}}}),
        (2, None),
        (2, []),
        (2, {}),
        (2, {"titleId": 123}),
        (2, {"titleId": "bad\nvalue"}),
        (2, {"titleId": LOB_ID, "botId": OTHER_BOT_ID}),
    ],
)
def test_wrong_identity_or_malformed_metadata_never_becomes_registration_success(
    configured, monkeypatch, stage, body
):
    session = _install_session(monkeypatch)
    session.replies[stage] = _response(body)
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        _lookup()
    assert caught.value.code == "ServiceError"
    assert session.closed
    if stage == 0 or stage == 1 and body.get("bot", {}).get("cdsBotId") != BOT_ID:
        assert len(session.calls) == stage + 1


def test_missing_both_registrations_is_explicit(configured, monkeypatch):
    _install_session(monkeypatch, regular=None, lob=None)
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        _lookup()
    assert caught.value.code == "RegistrationRequired"


def test_network_timeout_is_sanitized_and_closes_session(configured, monkeypatch, caplog):
    session = _install_session(monkeypatch, replies=[requests.Timeout("PRIVATE_URL")])
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        _lookup()
    assert caught.value.code == "NetworkError"
    assert session.closed
    assert "PRIVATE_URL" not in str(caught.value) + caplog.text


@pytest.mark.parametrize("stage", [0, 1, 2])
def test_non_json_metadata_is_sanitized(configured, monkeypatch, stage):
    session = _install_session(monkeypatch)
    session.replies[stage]._content = b"PRIVATE_NON_JSON_RESPONSE"
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        _lookup()
    assert caught.value.code == "ServiceError"
    assert "PRIVATE_NON_JSON_RESPONSE" not in str(caught.value)
    assert session.closed


def _token(tenant=TENANT_ID, account=OBJECT_ID):
    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": tenant, "oid": account}).encode()
    ).decode()
    return f"header.{payload}.signature"


@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize(
    ("tenant", "account", "success"),
    [(TENANT_ID, OBJECT_ID, True), (OTHER_BOT_ID, OBJECT_ID, False),
     (TENANT_ID, OTHER_BOT_ID, False)],
)
def test_metadata_token_uses_ring_global_scopes_and_exact_authoring_identity(
    monkeypatch, interactive, tenant, account, success
):
    calls = []
    selected = object()

    class App:
        def acquire_token_silent(self, scopes, *, account):
            assert account is selected
            calls.append(scopes)
            return None if interactive else {"access_token": _token(tenant, account_id)}

        def acquire_token_interactive(self, scopes, *, prompt, timeout):
            assert prompt == "select_account" and timeout == 300
            calls.append(scopes)
            return {"access_token": _token(tenant, account_id)}

    account_id = account
    monkeypatch.setattr(resolution, "_create_msal_app", lambda tid: App())
    monkeypatch.setattr(resolution, "account_for_identity", lambda *args: selected)
    if success:
        assert resolution.acquire_power_platform_token("test", TENANT_ID, OBJECT_ID) == _token()
    else:
        with pytest.raises(resolution.AgentTitleResolutionError) as caught:
            resolution.acquire_power_platform_token("test", TENANT_ID, OBJECT_ID)
        assert caught.value.code == "AuthenticationRequired"
    assert calls == [[
        "https://api.test.powerplatform.com/CopilotStudio.MakerOperations.Read",
        "https://api.test.powerplatform.com/CopilotStudio.MinimalBot.Read",
    ]] * (2 if interactive else 1)


def test_missing_account_and_cross_tenant_target_never_acquire_metadata_token(
    configured, monkeypatch
):
    with pytest.raises(resolution.AgentTitleResolutionError, match="cannot be identified"):
        resolution.acquire_power_platform_token("test", TENANT_ID, None)
    monkeypatch.setattr(
        resolution, "acquire_power_platform_token",
        lambda *args: pytest.fail("cross-tenant target reached resource sign-in"),
    )
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.resolve_configured_agent_title(
            resolution.load_configured_target(BOT_ID), OTHER_BOT_ID, OBJECT_ID
        )
    assert caught.value.code == "AuthenticationRequired"


def test_browser_timeout_is_bounded_and_sanitized(monkeypatch):
    class App:
        def acquire_token_interactive(self, scopes, *, prompt, timeout):
            assert timeout == 300
            raise RuntimeError("PRIVATE_SDK_TIMEOUT")

    monkeypatch.setattr(resolution, "_create_msal_app", lambda tid: App())
    monkeypatch.setattr(resolution, "account_for_identity", lambda *args: None)
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.acquire_power_platform_token("test", TENANT_ID, OBJECT_ID)
    assert caught.value.code == "AuthenticationRequired"
    assert "300 seconds" in str(caught.value)
    assert "PRIVATE_SDK_TIMEOUT" not in str(caught.value)


@pytest.mark.parametrize("failure", [OSError, RuntimeError, requests.RequestException])
def test_msal_factory_failure_is_sanitized(monkeypatch, failure):
    def fail(*args):
        raise failure("PRIVATE_AUTH_FACTORY_DETAIL")

    monkeypatch.setattr(resolution, "_create_msal_app", fail)
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.acquire_power_platform_token("test", TENANT_ID, OBJECT_ID)
    assert caught.value.code == "AuthenticationRequired"
    assert "PRIVATE_AUTH_FACTORY_DETAIL" not in str(caught.value)


def test_coordinator_tracks_cancelled_work_and_isolates_providers():
    async def run():
        coordinator = resolution.TitleResolutionCoordinator()
        other_provider = resolution.TitleResolutionCoordinator()
        started, finish = asyncio.Event(), asyncio.Event()
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
