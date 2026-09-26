# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for identity-aware Workday connect preflight."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest


BOT_ID = "00000000-0000-4000-8000-000000000001"
ENV_URL = "https://target.crm.dynamics.com"


def _write_foundation(
    root: Path,
    *,
    dataverse_url: str | None = None,
    schema_name: str = "gptagent_copilotforemployeeselfservicehr",
) -> None:
    local = root / ".local"
    local.mkdir(parents=True, exist_ok=True)
    config = {
        "configVersion": 1,
        "setup": "complete",
        "releaseLine": "da",
        "environmentId": "agent-environment",
        "powerPlatformApiEndpoint": "https://api.powerplatform.com",
        "ring": "prod",
        "activeAgent": "ess-hr",
        "agent": {
            "slug": "ess-hr",
            "botId": BOT_ID,
            "schemaName": schema_name,
            "name": "Employee Self-Service HR",
        },
        "agents": [
            {
                "slug": "ess-hr",
                "botId": BOT_ID,
                "schemaName": schema_name,
                "name": "Employee Self-Service HR",
            }
        ],
    }
    if dataverse_url:
        config["dataverseEndpoint"] = dataverse_url
    (local / "config.json").write_text(json.dumps(config), encoding="utf-8")
    setup = local / "setup"
    setup.mkdir()
    (setup / "config.json").write_text(
        json.dumps(
            {
                "schema_version": 4,
                "agents": {
                    BOT_ID: {
                        "agent": {
                            "id": BOT_ID,
                            "workspace_slug": "ess-hr",
                        },
                        "steps": {"SETUP-07": {"state": "done"}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def test_resolve_target_prefers_canonical_dataverse_url(tmp_path: Path) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path, dataverse_url=ENV_URL)

    target = preflight.resolve_target(
        tmp_path,
        dataverse_url="https://other.crm.dynamics.com",
        state=model.default_state(),
    )

    assert target.dataverse_url == ENV_URL
    assert target.environment_id == "agent-environment"
    assert target.package_flavor == "runtime"


def test_resolve_target_accepts_exact_url_without_inventory_lookup(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path)

    target = preflight.resolve_target(
        tmp_path,
        dataverse_url=ENV_URL,
        state=model.default_state(),
    )

    assert target.dataverse_url == ENV_URL


def test_resolve_target_reuses_setup_environment_inventory(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path)
    inventory = (
        tmp_path / ".local" / "setup" / "environment-list-prod.json"
    )
    inventory.write_text(
        json.dumps(
            {
                "environments": [
                    {
                        "id": "agent-environment",
                        "displayName": "ESS HR",
                        "url": ENV_URL,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    target = preflight.resolve_target(
        tmp_path,
        dataverse_url=None,
        state=model.default_state(),
    )

    assert target.dataverse_url == ENV_URL


def test_resolve_target_reuses_exact_pac_environment(tmp_path: Path) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path)

    def runner(command, **_kwargs):
        assert command[-3:] == [
            "--environment",
            "agent-environment",
            "--json",
        ]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "EnvironmentId": "agent-environment",
                    "OrgUrl": f"{ENV_URL}/",
                }
            ),
            stderr="",
        )

    target = preflight.resolve_target(
        tmp_path,
        dataverse_url=None,
        state=model.default_state(),
        pac_resolver=lambda: Path("pac.exe"),
        pac_runner=runner,
    )

    assert target.dataverse_url == ENV_URL


def test_resolve_target_rejects_mismatched_pac_environment(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path)

    with pytest.raises(
        preflight.WorkdayConnectPreflightError,
        match="different environment",
    ):
        preflight.resolve_target(
            tmp_path,
            dataverse_url=None,
            state=model.default_state(),
            pac_resolver=lambda: Path("pac.exe"),
            pac_runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "EnvironmentId": "other-environment",
                        "OrgUrl": ENV_URL,
                    }
                ),
                stderr="",
            ),
        )


def test_resolve_target_rejects_classic_da(tmp_path: Path) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    _write_foundation(
        tmp_path,
        schema_name="msdyn_copilotforemployeeselfservicedahr",
    )

    with pytest.raises(
        preflight.WorkdayConnectPreflightError,
        match="native ESS HR agent only",
    ):
        preflight.resolve_target(
            tmp_path,
            dataverse_url=ENV_URL,
            state=model.default_state(),
        )


def test_preflight_skips_install_when_package_exists(tmp_path: Path) -> None:
    import workday_connect_preflight as preflight
    import workday_connect_store as store_module

    _write_foundation(tmp_path)
    installer_calls = []

    def query(_url, _token, entity_set, _select, _filter):
        assert entity_set == "solutions"
        return [{"uniquename": "msdyn_EssWorkdayRuntime"}]

    result = preflight.run_preflight(
        tmp_path,
        dataverse_url=ENV_URL,
        maker_username="maker@example.com",
        store=store_module.WorkdayConnectStore(tmp_path),
        token_provider=lambda *_args, **_kwargs: "token",
        identity_provider=lambda *_args, **_kwargs: {
            "username": "maker@example.com",
            "tenantId": "tenant-id",
        },
        query=query,
        installer=lambda *_args, **_kwargs: installer_calls.append(True),
    )

    assert installer_calls == []
    assert result["package"]["action"] == "unchanged"
    assert result["status"]["nextPhaseId"] == "entra"


def test_preflight_installs_and_reverifies_with_same_account(
    tmp_path: Path,
) -> None:
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path)
    query_results = iter(
        [[], [{"uniquename": "msdyn_EssWorkdayRuntime"}]]
    )

    result = preflight.run_preflight(
        tmp_path,
        dataverse_url=ENV_URL,
        maker_username="maker@example.com",
        token_provider=lambda *_args, **_kwargs: "token",
        identity_provider=lambda *_args, **_kwargs: {
            "username": "maker@example.com",
            "tenantId": "tenant-id",
        },
        query=lambda *_args, **_kwargs: next(query_results),
        installer=lambda *_args, **kwargs: {
            "schemaName": "msdyn_EssWorkdayRuntime",
            "authenticatedAccount": kwargs["preferred_username"],
        },
    )

    assert result["package"]["action"] == "installed"
    assert result["operator"]["username"] == "maker@example.com"
    assert result["operator"]["credentialStores"]["pac"] == "verified"


def test_preflight_reuses_persisted_maker_identity(tmp_path: Path) -> None:
    import workday_connect_preflight as preflight
    import workday_connect_store as store_module

    _write_foundation(tmp_path)
    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "operators",
        {
            "powerPlatformMaker": {
                "username": "maker@example.com",
                "tenantId": "tenant-id",
            }
        },
    )
    observed = {}

    def token_provider(_url, *, preferred_username):
        observed["preferred"] = preferred_username
        return "token"

    preflight.run_preflight(
        tmp_path,
        dataverse_url=ENV_URL,
        maker_username=None,
        store=store,
        token_provider=token_provider,
        identity_provider=lambda _token, *, preferred_username: {
            "username": preferred_username,
            "tenantId": "tenant-id",
        },
        query=lambda *_args, **_kwargs: [
            {"uniquename": "msdyn_EssWorkdayRuntime"}
        ],
    )

    assert observed["preferred"] == "maker@example.com"


def test_preflight_identity_mismatch_is_structured(tmp_path: Path) -> None:
    import workday_connect_auth as auth
    import workday_connect_preflight as preflight
    import workday_connect_store as store_module

    _write_foundation(tmp_path)
    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()

    def mismatch(_token, *, preferred_username):
        raise auth.WorkdayConnectIdentityError(
            "Dataverse authentication used a different account from the "
            "selected Environment Maker."
        )

    with pytest.raises(
        preflight.WorkdayConnectPreflightError,
        match="different account",
    ):
        preflight.run_preflight(
            tmp_path,
            dataverse_url=ENV_URL,
            maker_username="maker@example.com",
            store=store,
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=mismatch,
            query=lambda *_args, **_kwargs: [],
        )


def test_preflight_rejects_unproven_pac_account(tmp_path: Path) -> None:
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path)

    with pytest.raises(
        preflight.WorkdayConnectPreflightError,
        match="did not prove",
    ):
        preflight.run_preflight(
            tmp_path,
            dataverse_url=ENV_URL,
            maker_username="maker@example.com",
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=lambda *_args, **_kwargs: {
                "username": "maker@example.com",
                "tenantId": "tenant-id",
            },
            query=lambda *_args, **_kwargs: [],
            installer=lambda *_args, **_kwargs: {
                "schemaName": "msdyn_EssWorkdayRuntime",
                "authenticatedAccount": "other@example.com",
            },
        )
