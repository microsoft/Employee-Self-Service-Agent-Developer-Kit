# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Sanity tests for the conftest fixtures themselves.

Cheap to run, fails loudly if the scaffolding regresses, and gives new
contributors a known-good example of what each fixture provides.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_fake_tenant_id_is_stable(fake_tenant_id: str) -> None:
    assert fake_tenant_id == "00000000-0000-0000-0000-000000001111"


def test_fake_dataverse_url_is_https(fake_dataverse_url: str) -> None:
    assert fake_dataverse_url.startswith("https://")
    assert "orgmocktenant" in fake_dataverse_url


def test_fake_config_round_trips_as_json(fake_config: dict) -> None:
    blob = json.dumps(fake_config)
    assert json.loads(blob) == fake_config
    assert fake_config["setup"] == "complete"
    assert fake_config["agent"]["slug"] == "mock-ess-agent"


def test_tmp_kit_root_writes_config(tmp_kit_root: Path) -> None:
    config_path = tmp_kit_root / ".local" / "config.json"
    assert config_path.exists()
    loaded = json.loads(config_path.read_text())
    assert loaded["activeAgent"] == "mock-ess-agent"


def test_tmp_kit_root_writes_workspace(tmp_kit_root: Path) -> None:
    agent_yaml = tmp_kit_root / "workspace" / "agents" / "mock-ess-agent" / "agent.mcs.yml"
    assert agent_yaml.exists()


def test_chdir_kit_root_actually_chdirs(chdir_kit_root: Path) -> None:
    assert Path.cwd() == chdir_kit_root


def test_fake_msal_token_returns_canned(fake_msal_token: str) -> None:
    import msal

    app = msal.PublicClientApplication("any-client-id", authority="https://example/")
    accounts = app.get_accounts()
    assert accounts and accounts[0]["username"] == "mock.user@contoso.com"

    silent = app.acquire_token_silent(["scope"], account=accounts[0])
    assert silent["access_token"] == fake_msal_token


def test_isolate_token_cache_redirects_home(
    isolate_token_cache: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    assert os.environ["HOME"] == str(isolate_token_cache)
    assert os.environ["USERPROFILE"] == str(isolate_token_cache)
