# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Shared pytest fixtures for the ESS Maker Kit test suite.

Anything reusable across test modules — fake auth, fake config, fake
agent workspace, base URL constants — lives here so individual test files
can stay focused on the behavior they're verifying.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

import pytest


# Stable fake values used everywhere a test needs an "identity". These match
# the redaction substitution table documented in tests/captures/README.md so
# cassettes and hand-built mocks share a vocabulary.
FAKE_TENANT_ID = "00000000-0000-0000-0000-000000001111"
FAKE_USER_ID = "00000000-0000-0000-0000-000000002222"
FAKE_BOT_ID = "00000000-0000-0000-0000-000000003333"
FAKE_ENV_ID = "Default-00000000-0000-0000-0000-000000001111"
FAKE_ORG_FRAGMENT = "orgmocktenant"
FAKE_DATAVERSE_URL = f"https://{FAKE_ORG_FRAGMENT}.crm.dynamics.com"
FAKE_TOKEN = "REDACTED_TOKEN"  # noqa: S105 — test fixture, not a credential


@pytest.fixture
def fake_tenant_id() -> str:
    return FAKE_TENANT_ID


@pytest.fixture
def fake_dataverse_url() -> str:
    return FAKE_DATAVERSE_URL


@pytest.fixture
def fake_token() -> str:
    return FAKE_TOKEN


@pytest.fixture
def fake_config() -> dict[str, Any]:
    """A plausible .local/config.json payload for tests that load_config()."""
    return {
        "setup": "complete",
        "agent": {
            "name": "Mock ESS Agent",
            "botId": FAKE_BOT_ID,
            "schemaName": "msdyn_copilotforemployeeselfservice",
            "isManaged": True,
            "slug": "mock-ess-agent",
            "folder": "workspace/agents/mock-ess-agent",
        },
        "activeAgent": "mock-ess-agent",
        "agents": [
            {
                "name": "Mock ESS Agent",
                "botId": FAKE_BOT_ID,
                "schemaName": "msdyn_copilotforemployeeselfservice",
                "isManaged": True,
                "slug": "mock-ess-agent",
                "folder": "workspace/agents/mock-ess-agent",
            }
        ],
        "dataverseEndpoint": FAKE_DATAVERSE_URL,
        "templateConfigsDiscovered": True,
        "templateConfigCount": 0,
        "workflowCount": 0,
    }


@pytest.fixture
def tmp_kit_root(tmp_path: Path, fake_config: dict[str, Any]) -> Path:
    """
    Spin up a throwaway kit-root layout under tmp_path.

    Mirrors the on-disk shape the scripts expect:

        <tmp>/
        ├── .local/
        │   └── config.json
        └── workspace/
            └── agents/
                └── mock-ess-agent/
                    ├── agent.mcs.yml
                    └── ...
    """
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(json.dumps(fake_config, indent=2))

    agent_root = tmp_path / "workspace" / "agents" / "mock-ess-agent"
    agent_root.mkdir(parents=True)
    # Minimal placeholder so callers that os.scandir() the agent dir don't
    # crash. Tests that need real component files should write them inline.
    (agent_root / "agent.mcs.yml").write_text("kind: AgentDefinition\nname: Mock ESS Agent\n")

    return tmp_path


@pytest.fixture
def chdir_kit_root(tmp_kit_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Chdir into tmp_kit_root for the duration of one test.

    Most kit scripts read .local/config.json with a relative path, so they
    need the cwd set. Use this fixture for any test that calls into the
    scripts/ modules at top level.
    """
    monkeypatch.chdir(tmp_kit_root)
    return tmp_kit_root


@pytest.fixture
def fake_msal_token(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """
    Patch MSAL so any code path that calls acquire_token_* gets FAKE_TOKEN.

    Covers the silent path (cache hit), the interactive path (would normally
    pop a browser), and the device-flow path (would normally print a code).
    No real tokens, no real user prompts, no network.

    Yields the token value so a test can assert on it if needed.
    """
    silent_response = {"access_token": FAKE_TOKEN, "expires_in": 3600}
    interactive_response = {"access_token": FAKE_TOKEN, "expires_in": 3600}

    class _FakeApp:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_accounts(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            return [{"username": "mock.user@contoso.com", "home_account_id": FAKE_USER_ID}]

        def acquire_token_silent(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return silent_response

        def acquire_token_interactive(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return interactive_response

        def initiate_device_flow(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "user_code": "FAKE-CODE",
                "device_code": "FAKE-DEVICE",
                "verification_uri": "https://microsoft.com/devicelogin",
                "expires_in": 900,
                "interval": 5,
                "message": "(test) device-flow message",
            }

        def acquire_token_by_device_flow(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return interactive_response

    class _FakeCache:
        def __init__(self) -> None:
            self._serialized = ""

        def serialize(self) -> str:
            return self._serialized

        def deserialize(self, data: str) -> None:
            self._serialized = data

        @property
        def has_state_changed(self) -> bool:
            return False

    # msal is imported lazily by the kit's auth modules. Patch on both the
    # top-level msal namespace and on the per-module re-imports.
    import msal

    monkeypatch.setattr(msal, "PublicClientApplication", _FakeApp)
    monkeypatch.setattr(msal, "SerializableTokenCache", _FakeCache)

    # Some modules do `from msal import PublicClientApplication`. Patch the
    # symbol on every kit module that's already been imported by the time
    # this fixture runs. Modules imported after this still see the patched
    # msal namespace because of monkeypatch above.
    for mod_name in list(__import__("sys").modules):
        if mod_name.startswith(("auth", "flightcheck", "client", "server")):
            mod = __import__("sys").modules[mod_name]
            if hasattr(mod, "PublicClientApplication"):
                monkeypatch.setattr(mod, "PublicClientApplication", _FakeApp, raising=False)
            if hasattr(mod, "SerializableTokenCache"):
                monkeypatch.setattr(mod, "SerializableTokenCache", _FakeCache, raising=False)

    yield FAKE_TOKEN


@pytest.fixture
def isolate_token_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """
    Redirect HOME/USERPROFILE to a tmp dir so MSAL's on-disk token cache
    never touches the contributor's real cache.

    Belt-and-braces alongside fake_msal_token; covers paths that ignore
    the in-memory cache and hit disk directly.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("APPDATA", str(fake_home))
    return fake_home


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help=(
            "Run tests marked @pytest.mark.live (real network calls against a "
            "real tenant). Requires valid credentials. Off by default."
        ),
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip @pytest.mark.live tests unless --run-live was passed."""
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="live network test (pass --run-live to run)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
