# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Strict bot/environment binding, registration parsing, and resource-token identity."""

from __future__ import annotations

import base64
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
import requests

import agent_title_resolution as resolution


BOT = "aaaaaaaa-0000-4000-8000-000000004444"
OTHER_BOT = "bbbbbbbb-0000-4000-8000-000000005555"
TENANT = "00000000-0000-0000-0000-000000001111"
OTHER_TENANT = "00000000-0000-0000-0000-000000002222"
OBJECT_ID = "00000000-0000-0000-0000-000000003333"
ENDPOINT = "https://orgmocktenant.crm.dynamics.com"
REGULAR = "regular-registration"
LOB = "lob-registration"
PRIVATE = "PRIVATE_DISCOVERY_DETAIL"


def _agent(bot_id=BOT, slug="selected"):
    return {"botId": bot_id, "slug": slug, "name": "Same display name"}


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(resolution, "CONFIG_PATH", path)
    return path


def _write(path, *, agents=None, agent=None, active="selected", **extra):
    config = {
        "setup": "complete",
        "agents": [_agent()] if agents is None else agents,
        "dataverseEndpoint": ENDPOINT,
        **extra,
    }
    if agent is not None:
        config["agent"] = agent
    if active is not None:
        config["activeAgent"] = active
    path.write_text(json.dumps(config), encoding="utf-8")


def _metadata(metadata, *, bot_id=BOT):
    return {
        "botid": bot_id,
        "applicationmanifestinformation": json.dumps({"microsoft365": metadata}),
    }


def _token(**claims):
    payload = json.dumps({"tid": TENANT, "oid": OBJECT_ID, "private": PRIVATE, **claims})
    encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


@pytest.mark.parametrize("bot_id", [BOT, BOT.upper(), "{" + BOT.upper() + "}", BOT.replace("-", "")])
def test_target_binding_normalizes_guids_in_configuration_and_request(config_path, bot_id):
    _write(config_path, agents=[{**_agent(bot_id), "dataverseEndpoint": ENDPOINT}])
    target = resolution.load_configured_target(bot_id)
    assert (target.bot_id, target.dataverse_endpoint) == (BOT, ENDPOINT)


@pytest.mark.parametrize("bot_id", [None, 42, "", "Same display name", "selected", "0" * 32])
def test_display_names_slugs_and_empty_guids_cannot_select_a_bot(config_path, bot_id):
    _write(config_path)
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.load_configured_target(bot_id)
    assert caught.value.code == "InvalidRequest"


@pytest.mark.parametrize("content", [None, "{", "[]", "null", "{}", '{"setup": "pending"}'])
def test_missing_or_incomplete_configuration_fails_before_discovery(config_path, content):
    if content is not None:
        config_path.write_text(content, encoding="utf-8")
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.load_configured_target(BOT)
    assert caught.value.code == "InvalidRequest"


@pytest.mark.parametrize("agents", [{}, [None], [_agent(), _agent()], [_agent(OTHER_BOT)]])
def test_agent_binding_requires_exactly_one_valid_bot_match(config_path, agents):
    _write(config_path, agents=agents)
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.load_configured_target(BOT)
    assert caught.value.code == "InvalidRequest"


@pytest.mark.parametrize(
    ("agent", "active", "agents", "accepted"),
    [
        (_agent(), "selected", [_agent()], True),
        (_agent(), None, [_agent()], True),
        (None, "selected", [_agent()], True),
        (None, None, [_agent()], True),
        (_agent(), "other", [_agent()], False),
        (_agent(OTHER_BOT, "other"), "selected", [_agent()], False),
        (None, None, [_agent(), _agent(OTHER_BOT, "other")], False),
        (None, "selected", [_agent(), _agent(OTHER_BOT)], False),
        (_agent(), None, [], True),
        (_agent(), "other", [], False),
    ],
)
def test_workspace_endpoint_is_only_a_consistent_unambiguous_active_fallback(
    config_path, agent, active, agents, accepted
):
    _write(config_path, agent=agent, active=active, agents=agents)
    if accepted:
        assert resolution.load_configured_target(BOT).dataverse_endpoint == ENDPOINT
    else:
        with pytest.raises(resolution.AgentTitleResolutionError) as caught:
            resolution.load_configured_target(BOT)
        assert caught.value.code == "InvalidRequest"


@pytest.mark.parametrize("environment_field", ["environmentId", "powerPlatformApiEndpoint"])
def test_an_agent_with_its_own_environment_cannot_inherit_the_workspace_endpoint(
    config_path, environment_field
):
    _write(config_path, agents=[{**_agent(), environment_field: "other-environment"}])
    with pytest.raises(resolution.AgentTitleResolutionError, match="no configured Dataverse endpoint"):
        resolution.load_configured_target(BOT)


@pytest.mark.parametrize(
    "endpoint",
    [
        None, "", 42, "http://example.test", "https://user:password@example.test",
        "https://example.test/api", "https://example.test?environment=other",
        "https://example.test#other",
    ],
)
def test_agent_specific_endpoints_must_be_https_origins(config_path, endpoint):
    _write(config_path, agents=[{
        **_agent(), "environmentId": "selected-environment", "dataverseEndpoint": endpoint,
    }])
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.load_configured_target(BOT)
    assert caught.value.code == "InvalidRequest"


def test_identical_registration_ids_remain_a_canonical_pair():
    assert resolution._registered_titles(
        _metadata({"titleId": REGULAR, "lobTitleId": REGULAR}), BOT
    ) == {"titleId": REGULAR, "lobTitleId": REGULAR}


@pytest.mark.parametrize(
    "metadata",
    [
        None, {}, {"titleId": "", "lobTitleId": "  "},
        {"appId": REGULAR, "lobAppId": LOB},
        {"shareLink": "https://example.test/app", "lobShareLink": LOB},
    ],
)
def test_non_registration_ids_never_substitute_for_a_missing_registration(metadata):
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution._registered_titles(_metadata(metadata), BOT)
    assert caught.value.code == "RegistrationRequired"


@pytest.mark.parametrize("field", ["titleId", "lobTitleId"])
@pytest.mark.parametrize("value", [False, 42, {}, [], " padded ", "line\nbreak", "x" * 257])
def test_one_invalid_registration_rejects_the_entire_pair(field, value):
    metadata = {"titleId": REGULAR, "lobTitleId": LOB, field: value, "private": PRIVATE}
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution._registered_titles(_metadata(metadata), BOT)
    assert caught.value.code == "ServiceError"
    assert caught.value.source == "backend"
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("manifest", ["{", "[]", "null", {"microsoft365": {}}, '{"microsoft365": []}'])
def test_malformed_manifests_are_errors_not_empty_registration_successes(manifest):
    payload = {"botid": BOT, "applicationmanifestinformation": manifest, "private": PRIVATE}
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution._registered_titles(payload, BOT)
    assert caught.value.code == "ServiceError"
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("bot_id", [None, "", OTHER_BOT, "not-a-guid"])
def test_backend_bot_mismatch_never_accepts_any_registration(bot_id):
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution._registered_titles(_metadata({"titleId": REGULAR}, bot_id=bot_id), BOT)
    assert caught.value.code == "ServiceError"
    assert "selected configured bot" in str(caught.value)


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "AuthenticationRequired"), (403, "AuthorizationDenied"), (404, "NotFound"), (503, "ServiceError")],
)
def test_http_failures_are_explicit_sanitized_and_do_not_write_config(
    config_path, monkeypatch, status, code
):
    _write(config_path)
    before = config_path.read_bytes()
    monkeypatch.setattr(resolution, "acquire_dataverse_token", lambda *args: "test-resource-token")
    response = requests.Response()
    response.status_code = status

    def fail(*args, **kwargs):
        raise requests.HTTPError(PRIVATE, response=response)

    monkeypatch.setattr(resolution, "dataverse_get", fail)
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.resolve_configured_agent_title(
            resolution.load_configured_target(BOT), TENANT, OBJECT_ID
        )
    assert caught.value.code == code
    assert caught.value.source == "backend"
    assert f"HTTP {status}" in str(caught.value)
    assert PRIVATE not in str(caught.value)
    assert config_path.read_bytes() == before


@pytest.mark.parametrize(
    ("error", "code"),
    [(requests.Timeout(PRIVATE), "NetworkError"), (ValueError(PRIVATE), "ServiceError")],
)
def test_network_and_parse_failures_do_not_become_empty_discovery(monkeypatch, error, code):
    monkeypatch.setattr(resolution, "acquire_dataverse_token", lambda *args: "test-resource-token")

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(resolution, "dataverse_get", fail)
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.resolve_configured_agent_title(
            resolution.ConfiguredAgentTarget(BOT, ENDPOINT), TENANT, OBJECT_ID
        )
    assert caught.value.code == code
    assert PRIVATE not in str(caught.value)


def test_dataverse_silent_auth_uses_the_same_tenant_account_and_resource(monkeypatch):
    account = object()
    calls = []

    def silent(scopes, *, account):
        calls.append((scopes, account))
        return {"access_token": _token()}

    app = SimpleNamespace(acquire_token_silent=silent)

    def create_app(tenant):
        assert tenant == TENANT
        return app

    def match_identity(selected_app, tenant, object_id):
        assert (selected_app, tenant, object_id) == (app, TENANT, OBJECT_ID)
        return account

    monkeypatch.setattr(resolution, "_create_msal_app", create_app)
    monkeypatch.setattr(resolution, "account_for_identity", match_identity)
    assert resolution.acquire_dataverse_token(ENDPOINT, TENANT, OBJECT_ID) == _token()
    assert calls == [([f"{ENDPOINT}/user_impersonation"], account)]


@pytest.mark.parametrize("claims", [{"tid": OTHER_TENANT}, {"oid": OTHER_BOT}, {"oid": None}])
def test_a_mismatched_resource_token_cannot_switch_tenant_or_account(monkeypatch, claims):
    app = SimpleNamespace(acquire_token_silent=lambda *args, **kwargs: {"access_token": _token(**claims)})
    monkeypatch.setattr(resolution, "_create_msal_app", lambda tenant: app)
    monkeypatch.setattr(resolution, "account_for_identity", lambda *args: object())
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.acquire_dataverse_token(ENDPOINT, TENANT, OBJECT_ID)
    assert caught.value.code == "AuthenticationRequired"
    assert PRIVATE not in str(caught.value)


@pytest.mark.parametrize("object_id", [None, ""])
def test_missing_authoring_identity_never_opens_a_sign_in(monkeypatch, object_id):
    monkeypatch.setattr(
        resolution, "_create_msal_app", lambda tenant: pytest.fail("No account was identified")
    )
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.acquire_dataverse_token(ENDPOINT, TENANT, object_id)
    assert caught.value.code == "AuthenticationRequired"


@pytest.mark.parametrize("cached_account", [None, object()])
def test_interactive_auth_is_bounded_and_keeps_resource_identity(monkeypatch, cached_account):
    calls = []

    def interactive(scopes, *, prompt, timeout):
        calls.append((scopes, prompt, timeout))
        return {"access_token": _token()}

    app = SimpleNamespace(
        acquire_token_silent=lambda *args, **kwargs: None,
        acquire_token_interactive=interactive,
    )
    monkeypatch.setattr(resolution, "_create_msal_app", lambda tenant: app)
    monkeypatch.setattr(resolution, "account_for_identity", lambda *args: cached_account)
    assert resolution.acquire_dataverse_token(ENDPOINT, TENANT, OBJECT_ID) == _token()
    assert calls == [([f"{ENDPOINT}/user_impersonation"], "select_account", 300)]


def test_raw_sdk_errors_are_not_exposed_in_discovery(monkeypatch):
    result = {"error": PRIVATE, "error_description": PRIVATE}
    before = deepcopy(result)
    app = SimpleNamespace(acquire_token_interactive=lambda *args, **kwargs: result)
    monkeypatch.setattr(resolution, "_create_msal_app", lambda tenant: app)
    monkeypatch.setattr(resolution, "account_for_identity", lambda *args: None)
    with pytest.raises(resolution.AgentTitleResolutionError) as caught:
        resolution.acquire_dataverse_token(ENDPOINT, TENANT, OBJECT_ID)
    assert caught.value.code == "AuthenticationRequired"
    assert PRIVATE not in str(caught.value)
    assert result == before
