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


def test_resolve_target_rejects_url_that_differs_from_setup(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path, dataverse_url=ENV_URL)

    with pytest.raises(
        preflight.WorkdayConnectPreflightError,
        match="does not match",
    ):
        preflight.resolve_target(
            tmp_path,
            dataverse_url="https://other.crm.dynamics.com",
            state=model.default_state(),
        )


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
        pac_resolver=lambda: Path("pac.exe"),
        pac_runner=lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                {
                    "EnvironmentId": "agent-environment",
                    "OrgUrl": ENV_URL,
                }
            ),
            stderr="",
        ),
    )

    assert target.dataverse_url == ENV_URL


def test_resolve_target_accepts_case_insensitive_https_scheme(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    uppercase_scheme_url = "HTTPS://target.crm.dynamics.com"
    _write_foundation(tmp_path, dataverse_url=uppercase_scheme_url)

    target = preflight.resolve_target(
        tmp_path,
        dataverse_url=uppercase_scheme_url,
        state=model.default_state(),
    )

    assert target.dataverse_url == uppercase_scheme_url


def test_resolve_target_ignores_stale_url_from_different_environment(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path)
    state = model.default_state()
    state["scope"].update(
        {
            "environmentId": "old-environment",
            "dataverseUrl": "https://old.crm.dynamics.com",
        }
    )
    inventory = (
        tmp_path / ".local" / "setup" / "environment-list-prod.json"
    )
    inventory.write_text(
        json.dumps(
            {
                "environments": [
                    {
                        "id": "agent-environment",
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
        state=state,
    )

    assert target.environment_id == "agent-environment"
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


def test_resolve_target_rejects_conflicting_setup_urls(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
    inventory = (
        tmp_path / ".local" / "setup" / "environment-list-prod.json"
    )
    inventory.write_text(
        json.dumps(
            {
                "environments": [
                    {
                        "id": "agent-environment",
                        "url": "https://different.crm.dynamics.com",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        preflight.WorkdayConnectPreflightError,
        match="disagree",
    ):
        preflight.resolve_target(
            tmp_path,
            dataverse_url=None,
            state=model.default_state(),
        )


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

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
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
    assert result["scope"]["entraTenantId"] == "tenant-id"


def test_preflight_carries_verified_tenant_into_entra_handoff(
    tmp_path: Path,
) -> None:
    import workday_connect_contracts as contracts
    import workday_connect_preflight as preflight
    import workday_connect_store as store_module

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
    store = store_module.WorkdayConnectStore(tmp_path)
    preflight.run_preflight(
        tmp_path,
        dataverse_url=ENV_URL,
        maker_username="maker@example.com",
        store=store,
        token_provider=lambda *_args, **_kwargs: "token",
        identity_provider=lambda *_args, **_kwargs: {
            "username": "maker@example.com",
            "tenantId": "tenant-id",
        },
        query=lambda *_args, **_kwargs: [
            {"uniquename": "msdyn_EssWorkdayRuntime"}
        ],
    )
    state = store.merge_section(
        "scope",
        {"workdayTenant": "contoso_impl"},
    )

    handoff = contracts.build_entra_handoff(
        state,
        {
            "applications": [
                {
                    "displayName": "Workday exact",
                    "appId": "44444444-4444-4444-4444-444444444444",
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": (
                        "66666666-6666-6666-6666-666666666666"
                    ),
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl"
                    ],
                }
            ]
        },
    )

    assert handoff["scope"]["entraTenantId"] == "tenant-id"


def test_preflight_installs_and_reverifies_with_same_account(
    tmp_path: Path,
) -> None:
    import workday_connect_preflight as preflight
    import workday_connect_store as store_module

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
    store = store_module.WorkdayConnectStore(tmp_path)
    installed = False

    def query(*_args, **_kwargs):
        return (
            [{"uniquename": "msdyn_EssWorkdayRuntime"}]
            if installed
            else []
        )

    plan_result = preflight.run_preflight(
        tmp_path,
        dataverse_url=ENV_URL,
        maker_username="maker@example.com",
        store=store,
        token_provider=lambda *_args, **_kwargs: "token",
        identity_provider=lambda *_args, **_kwargs: {
            "username": "maker@example.com",
            "tenantId": "tenant-id",
        },
        query=query,
    )
    assert plan_result["requiresApproval"] is True
    assert plan_result["plan"]["scope"]["agent"] == {
        "slug": "ess-hr",
        "botId": BOT_ID,
        "schemaName": "gptagent_copilotforemployeeselfservicehr",
    }
    assert store.status()["nextPhaseId"] == "preflight"
    _state, approved_hash = store.approve_plan(
        "preflight",
        plan_result["plan"],
    )

    def installer(*_args, **kwargs):
        nonlocal installed
        installed = True
        return {
            "schemaName": "msdyn_EssWorkdayRuntime",
            "authenticatedAccount": kwargs["preferred_username"],
        }

    result = preflight.run_preflight(
        tmp_path,
        dataverse_url=ENV_URL,
        maker_username="maker@example.com",
        store=store,
        token_provider=lambda *_args, **_kwargs: "token",
        identity_provider=lambda *_args, **_kwargs: {
            "username": "maker@example.com",
            "tenantId": "tenant-id",
        },
        query=query,
        installer=installer,
        approved_install_hash=approved_hash,
        plan_verifier=lambda plan, value: store.verify_plan(
            "preflight",
            plan,
            value,
        ),
    )

    assert result["package"]["action"] == "installed"
    assert result["operator"]["username"] == "maker@example.com"
    assert result["operator"]["credentialStores"]["pac"] == "verified"


def test_preflight_reuses_persisted_maker_identity(tmp_path: Path) -> None:
    import workday_connect_preflight as preflight
    import workday_connect_store as store_module

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
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


def test_preflight_apply_reuses_approved_plan_maker_identity(
    tmp_path: Path,
) -> None:
    import workday_connect_preflight as preflight
    import workday_connect_store as store_module

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
    store = store_module.WorkdayConnectStore(tmp_path)
    installed = False

    def query(*_args, **_kwargs):
        return (
            [{"uniquename": "msdyn_EssWorkdayRuntime"}]
            if installed
            else []
        )

    plan_result = preflight.run_preflight(
        tmp_path,
        dataverse_url=ENV_URL,
        maker_username="maker@example.com",
        store=store,
        token_provider=lambda *_args, **_kwargs: "token",
        identity_provider=lambda *_args, **_kwargs: {
            "username": "maker@example.com",
            "tenantId": "tenant-id",
        },
        query=query,
    )
    _state, approved_hash = store.approve_plan(
        "preflight",
        plan_result["plan"],
    )
    observed = {}

    def token_provider(_url, *, preferred_username):
        observed["preferred"] = preferred_username
        return "token"

    def installer(*_args, **kwargs):
        nonlocal installed
        installed = True
        return {
            "schemaName": "msdyn_EssWorkdayRuntime",
            "authenticatedAccount": kwargs["preferred_username"],
        }

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
        query=query,
        installer=installer,
        approved_install_hash=approved_hash,
        plan_verifier=lambda plan, value: store.verify_plan(
            "preflight",
            plan,
            value,
        ),
    )

    assert observed["preferred"] == "maker@example.com"


def test_preflight_identity_mismatch_is_structured(tmp_path: Path) -> None:
    import workday_connect_auth as auth
    import workday_connect_preflight as preflight
    import workday_connect_store as store_module

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
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

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    plan_result = preflight.run_preflight(
        tmp_path,
        dataverse_url=ENV_URL,
        maker_username="maker@example.com",
        store=store,
        token_provider=lambda *_args, **_kwargs: "token",
        identity_provider=lambda *_args, **_kwargs: {
            "username": "maker@example.com",
            "tenantId": "tenant-id",
        },
        query=lambda *_args, **_kwargs: [],
    )
    _state, approved_hash = store.approve_plan(
        "preflight",
        plan_result["plan"],
    )

    with pytest.raises(
        preflight.WorkdayConnectPreflightError,
        match="did not prove",
    ):
        preflight.run_preflight(
            tmp_path,
            dataverse_url=ENV_URL,
            maker_username="maker@example.com",
            store=store,
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
            approved_install_hash=approved_hash,
            plan_verifier=lambda plan, value: store.verify_plan(
                "preflight",
                plan,
                value,
            ),
        )


def test_preflight_rejects_supplied_url_not_proven_for_environment(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight

    _write_foundation(tmp_path)

    with pytest.raises(
        preflight.WorkdayConnectPreflightError,
        match="does not match",
    ):
        preflight.resolve_target(
            tmp_path,
            dataverse_url="https://wrong.crm.dynamics.com",
            state=model.default_state(),
            pac_resolver=lambda: Path("pac.exe"),
            pac_runner=lambda command, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "EnvironmentId": "agent-environment",
                        "OrgUrl": ENV_URL,
                    }
                ),
                stderr="",
            ),
        )


def test_repeated_preflight_preserves_verified_pac_evidence(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_preflight as preflight
    import workday_connect_store as store_module

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
    store = store_module.WorkdayConnectStore(tmp_path)
    installed = False

    def query(*_args, **_kwargs):
        return (
            [{"uniquename": "msdyn_EssWorkdayRuntime"}]
            if installed
            else []
        )

    common_kwargs = {
        "dataverse_url": ENV_URL,
        "maker_username": "maker@example.com",
        "store": store,
        "token_provider": lambda *_args, **_kwargs: "token",
        "identity_provider": lambda *_args, **_kwargs: {
            "username": "maker@example.com",
            "tenantId": "tenant-id",
        },
        "query": query,
    }
    plan_result = preflight.run_preflight(tmp_path, **common_kwargs)
    _state, approved_hash = store.approve_plan(
        "preflight",
        plan_result["plan"],
    )

    def installer(*_args, **kwargs):
        nonlocal installed
        installed = True
        return {
            "schemaName": "msdyn_EssWorkdayRuntime",
            "authenticatedAccount": kwargs["preferred_username"],
        }

    preflight.run_preflight(
        tmp_path,
        **common_kwargs,
        installer=installer,
        approved_install_hash=approved_hash,
        plan_verifier=lambda plan, value: store.verify_plan(
            "preflight",
            plan,
            value,
        ),
    )
    for phase_id in ("entra", "workday-admin"):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")

    result = preflight.run_preflight(
        tmp_path,
        **common_kwargs,
    )

    assert result["operator"]["credentialStores"]["pac"] == "verified"
    assert store.load()["phases"]["entra"]["status"] == "complete"
