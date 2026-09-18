# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for configured-tenant discovery and the unrestricted login fallback."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import requests


CORE_DIR = (
    Path(__file__).parents[3]
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_core"
)
sys.path.insert(0, str(CORE_DIR))

import _tenant_context  # noqa: E402
import auth  # noqa: E402


TENANT_ID = "00000000-0000-0000-0000-000000001111"
ENDPOINT = "https://orgmocktenant.crm.dynamics.com"


@pytest.fixture
def config_path(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "config.json"
    monkeypatch.setattr(_tenant_context, "_CONFIG_PATH", path)

    def unexpected_discovery(endpoint):
        pytest.fail(f"Unexpected tenant discovery for {endpoint}")

    monkeypatch.setattr(_tenant_context, "discover_tenant", unexpected_discovery)
    return path


def test_config_path_is_anchored_to_the_maker_workspace() -> None:
    # The MCP isolation fixture redirects _CONFIG_PATH; the root and imported
    # auth module must still be anchored to this checkout, not a sibling one.
    assert _tenant_context._SOLUTION_ROOT == CORE_DIR.parents[2]
    assert Path(auth.__file__).resolve() == CORE_DIR.parents[2] / "scripts" / "auth.py"


def test_discovers_the_configured_environment_from_any_working_directory(
    config_path, tmp_path, monkeypatch
) -> None:
    config_path.write_text(
        json.dumps({"dataverseEndpoint": f" {ENDPOINT}/ "}), encoding="utf-8"
    )
    endpoints = []
    monkeypatch.setattr(
        _tenant_context,
        "discover_tenant",
        lambda endpoint: endpoints.append(endpoint) or TENANT_ID,
    )
    monkeypatch.chdir(tmp_path)

    assert _tenant_context.configured_tenant_id() == TENANT_ID
    assert endpoints == [ENDPOINT]


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        "{",
        "[]",
        "null",
        "{}",
        '{"dataverseEndpoint": null}',
        '{"dataverseEndpoint": 42}',
        '{"dataverseEndpoint": "  "}',
    ],
)
def test_missing_or_unusable_configuration_warns_and_falls_back(
    config_path, content, caplog, capsys
) -> None:
    if content is not None:
        config_path.write_text(content, encoding="utf-8")

    assert _tenant_context.configured_tenant_id() is None
    assert "unrestricted AgentConfiguration sign-in (organizations)" in caplog.text
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://example.test",
        "https:///missing-host",
        "https://user:password@example.test",
        "https://example.test?tenant=other",
    ],
)
def test_invalid_endpoint_warns_without_discovery(
    config_path, endpoint, caplog
) -> None:
    config_path.write_text(
        json.dumps({"dataverseEndpoint": endpoint}), encoding="utf-8"
    )

    assert _tenant_context.configured_tenant_id() is None
    assert "configured Dataverse endpoint is invalid" in caplog.text
    assert endpoint not in caplog.text


def test_discovery_transport_failure_warns_and_falls_back(
    config_path, monkeypatch, caplog
) -> None:
    config_path.write_text(
        json.dumps({"dataverseEndpoint": ENDPOINT}), encoding="utf-8"
    )

    def timeout(endpoint):
        raise requests.Timeout("sensitive transport details")

    monkeypatch.setattr(_tenant_context, "discover_tenant", timeout)

    assert _tenant_context.configured_tenant_id() is None
    assert "Dataverse tenant discovery failed" in caplog.text
    assert "sensitive transport details" not in caplog.text


@pytest.mark.parametrize("tenant", ["organizations", "common", "", "invalid-tenant"])
def test_unresolved_tenant_warns_and_falls_back(
    config_path, monkeypatch, tenant, caplog
) -> None:
    config_path.write_text(
        json.dumps({"dataverseEndpoint": ENDPOINT}), encoding="utf-8"
    )
    monkeypatch.setattr(_tenant_context, "discover_tenant", lambda endpoint: tenant)

    assert _tenant_context.configured_tenant_id() is None
    assert "Dataverse did not identify a concrete tenant" in caplog.text


def test_invalid_config_encoding_warns_and_falls_back(config_path, caplog) -> None:
    config_path.write_bytes(b"\xff")

    assert _tenant_context.configured_tenant_id() is None
    assert "configuration could not be read" in caplog.text


@pytest.mark.parametrize("launch_folder", ["agentconfig_landing_page"])
def test_discovers_configured_environment_from_feature_launch_directory(
    config_path, monkeypatch, launch_folder
) -> None:
    config_path.write_text(
        json.dumps({"dataverseEndpoint": f" {ENDPOINT}/ "}), encoding="utf-8"
    )
    endpoints = []
    monkeypatch.setattr(
        _tenant_context, "discover_tenant",
        lambda endpoint: endpoints.append(endpoint) or TENANT_ID,
    )
    monkeypatch.chdir(CORE_DIR.parent / launch_folder)
    assert _tenant_context.configured_tenant_id() == TENANT_ID
    assert endpoints == [ENDPOINT]


@pytest.mark.parametrize(
    "challenge",
    [
        f'Bearer authorization_uri="https://login.microsoftonline.com/{TENANT_ID}"',
        f'Bearer authorization_uri="https://LOGIN.MICROSOFTONLINE.COM/{TENANT_ID}/oauth2/authorize"',
        f"Bearer authorization_uri=https://login.microsoftonline.com/{TENANT_ID}, resource_id=example",
        f"https://login.microsoftonline.com/{TENANT_ID}?resource=example",
    ],
)
def test_auth_challenge_discovery_produces_a_concrete_tenant(
    config_path, monkeypatch, challenge
) -> None:
    config_path.write_text(json.dumps({"dataverseEndpoint": ENDPOINT}), encoding="utf-8")
    requests_seen = []

    def get(url, **kwargs):
        requests_seen.append((url, kwargs))
        response = requests.Response()
        response.status_code = 401
        response.headers["WWW-Authenticate"] = challenge
        return response

    monkeypatch.setattr(auth._SESSION, "get", get)
    monkeypatch.setattr(_tenant_context, "discover_tenant", auth.discover_tenant)
    assert _tenant_context.configured_tenant_id() == TENANT_ID
    assert requests_seen == [(
        f"{ENDPOINT}/api/data/v9.2/",
        {
            "headers": {"Accept": "application/json"},
            "allow_redirects": False,
            "timeout": 10,
            "verify": True,
        },
    )]


def test_runtime_install_paths_include_the_shared_foundation() -> None:
    solution = CORE_DIR.parents[2]
    assert "-r ../src/mcp/agentconfig_core/requirements.txt" in (
        solution / "scripts" / "requirements.txt"
    ).read_text()
    for feature in ("agentconfig_landing_page",):
        assert "-r ../agentconfig_core/requirements.txt" in (
            CORE_DIR.parent / feature / "requirements.txt"
        ).read_text()
    requirements = (CORE_DIR / "requirements.txt").read_text()
    assert "msal-extensions[portalocker]>=1.3.1,<2.0" in requirements
    assert "requests>=2.32.0,<3.0" in requirements
    assert "urllib3>=2.2.0,<3.0" in requirements
