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
    assert (
        _tenant_context._CONFIG_PATH == CORE_DIR.parents[2] / ".local" / "config.json"
    )


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
