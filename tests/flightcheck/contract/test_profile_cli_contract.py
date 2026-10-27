# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""CLI contracts that keep FlightCheck profile execution deterministic."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import auth
from flightcheck import cli, registry
from flightcheck.agent_scope import is_declarative_agent
from flightcheck.runner import (
    CheckResult,
    FlightCheckRunner,
    Priority,
    Role,
    Status,
)


def _args(**overrides):
    values = {
        "profile": "workday-da:test",
        "connect_config": None,
        "environment_url": None,
        "environment_id": None,
        "quiet_auth": True,
        "preferred_username": "maker@example.com",
        "validation_realm": "dev",
        "agent_slug": "ess-hr",
        "agent_schema_name": "gptagent_test",
        "tenant_id": None,
        "runtime_reachability": False,
        "alm_import_probe": False,
        "output": "out",
        "no_telemetry": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _config() -> dict:
    return {
        "realm": "dev",
        "tenantId": "00000000-0000-0000-0000-000000001111",
        "environmentId": "00000000-0000-0000-0000-000000002222",
        "dataverseEndpoint": "https://org.crm.dynamics.com",
        "activeAgent": "ess-hr",
        "agents": [{
            "slug": "ess-hr",
            "schemaName": "gptagent_test",
            "botId": "00000000-0000-0000-0000-000000003333",
        }],
    }


def _passed() -> CheckResult:
    return CheckResult(
        checkpoint_id="TEST-001",
        category="Test",
        priority=Priority.HIGH.value,
        status=Status.PASSED.value,
        description="Profile test",
        result="Profile mode remained read-only.",
        roles=[Role.ESS_MAKER.value],
    )


@pytest.mark.parametrize("realm", ["test", "prod"])
@pytest.mark.parametrize("different_environment", [False, True])
def test_connect_profile_uses_promoted_snapshot_without_retargeting_workspace(
    tmp_path, monkeypatch, realm, different_environment,
) -> None:
    from flightcheck import maker_diagnostics
    from flightcheck.runner import RunResult
    from workday_connect_flightcheck import (
        _command, _config_projection, effective_validation_state,
    )
    from workday_connect_model import default_state

    local = tmp_path / ".local"
    local.mkdir()
    foundation = local / "config.json"
    foundation.write_text(json.dumps(_config()), encoding="utf-8")
    original = foundation.read_bytes()
    state = default_state()
    state["activeTargetRealm"] = realm
    config = _config()
    target_agent = {
        **config["agents"][0],
        "schemaName": f"gptagent_test_{realm}",
        "botId": "00000000-0000-0000-0000-000000004444",
    }
    state["scope"].update({
        "environmentId": (
            "00000000-0000-0000-0000-000000005555"
            if different_environment else config["environmentId"]
        ),
        "dataverseUrl": (
            "https://target.crm.dynamics.com"
            if different_environment else config["dataverseEndpoint"]
        ),
        "entraTenantId": config["tenantId"],
        "agent": target_agent,
        "ring": "prod",
    })
    state["operators"]["powerPlatformMaker"] = {"username": "maker@example.com"}
    effective = effective_validation_state(tmp_path, state)
    snapshot = tmp_path / "target.json"
    snapshot.write_text(json.dumps(_config_projection(effective)), encoding="utf-8")
    command = _command(
        tmp_path, effective, "workday-da:package-ready", tmp_path, snapshot,
    )
    assert "--connect-config" not in command
    args = _args(
        profile="workday-da:package-ready",
        profile_config=command[command.index("--profile-config") + 1],
        validation_realm=command[command.index("--validation-realm") + 1],
        environment_id=state["scope"]["environmentId"],
        environment_url=state["scope"]["dataverseUrl"],
        tenant_id=config["tenantId"],
        agent_schema_name=target_agent["schemaName"],
        no_open=True,
    )
    captured = {}

    def run_diagnostics(actual_args, actual_config):
        context = cli._validation_context_from_args(
            actual_args, actual_config, actual_args.environment_url,
            actual_args.environment_id,
        ).to_dict()
        captured["context"] = context
        captured["config"] = actual_config
        return RunResult(
            scope="profile", started="", profile=actual_args.profile,
            validation_context=context,
        )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(maker_diagnostics, "run_maker_diagnostics", run_diagnostics)
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a: None)
    monkeypatch.setattr(cli, "save_results", lambda *_a: None)
    with pytest.raises(SystemExit) as exc:
        cli._run_profile(args)

    assert exc.value.code == 0
    assert captured["context"] == {
        "realm": realm,
        "environmentId": state["scope"]["environmentId"],
        "environmentUrl": state["scope"]["dataverseUrl"],
        "tenantId": config["tenantId"],
        "agentSlug": target_agent["slug"],
        "agentSchemaName": target_agent["schemaName"],
        "agentId": target_agent["botId"],
    }
    assert captured["config"]["releaseLine"] == "da"
    assert "powerPlatformApiEndpoint" not in captured["config"]
    assert foundation.read_bytes() == original


@pytest.mark.parametrize("defect", [
    "missing", "malformed", "array", "schema", "environment", "tenant", "realm",
])
def test_explicit_profile_config_fails_closed(
    tmp_path, monkeypatch, capsys, defect,
) -> None:
    snapshot = tmp_path / "target.json"
    config = _config()
    args = _args(profile_config=str(snapshot))
    if defect == "schema":
        args.agent_schema_name = "wrong_schema"
    elif defect == "environment":
        args.environment_id = "00000000-0000-0000-0000-000000009999"
    elif defect == "tenant":
        args.tenant_id = "00000000-0000-0000-0000-000000008888"
    elif defect == "realm":
        args.validation_realm = "test"
    if defect != "missing":
        snapshot.write_text(
            "{bad" if defect == "malformed" else json.dumps(
                [] if defect == "array" else config
            ),
            encoding="utf-8",
        )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(registry, "resolve_profile", lambda _: object())
    monkeypatch.setattr(registry, "profile_requirements", lambda _: SimpleNamespace(
        clients=frozenset(), requires_config=False,
        requires_dataverse_endpoint=False,
    ))
    with pytest.raises(SystemExit) as exc:
        cli._run_profile(args)
    assert exc.value.code == 1
    assert "ERROR:" in capsys.readouterr().out


@pytest.mark.parametrize("mode", [[], ["--scope", "local"], ["--checkpoint", "WD-DA-PKG-001"]])
def test_profile_config_is_not_a_standalone_or_checkpoint_override(
    monkeypatch, capsys, mode,
) -> None:
    monkeypatch.setattr("sys.argv", [
        "flightcheck", "--profile-config", "target.json", *mode,
    ])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 2
    assert "--profile-config requires --profile" in capsys.readouterr().err


def test_profile_passes_preferred_account_and_forces_read_only(
    tmp_path,
    monkeypatch,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[],
    )
    observed = {}

    def check(runner):
        observed["runtime_reachability"] = runner.runtime_reachability
        observed["runtime_reachability_declined"] = (
            runner.runtime_reachability_declined
        )
        observed["preserve_manual"] = runner.preserve_workday_manual_rows
        return [_passed()]

    plan.ordered_fns = [("Test", check)]
    monkeypatch.setattr(
        registry,
        "resolve_profile",
        lambda _name: profile,
    )
    monkeypatch.setattr(
        registry,
        "profile_requirements",
        lambda _name: plan,
    )
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(
        registry,
        "profile_family_contract",
        lambda _name: {},
    )
    monkeypatch.setattr(auth, "discover_tenant", lambda _url: _config()["tenantId"])

    authenticated = {}

    def authenticate(
        env_url,
        preferred_username=None,
        *,
        return_account_identity=False,
    ):
        authenticated["env_url"] = env_url
        authenticated["preferred_username"] = preferred_username
        assert return_account_identity is True
        return "token", preferred_username

    monkeypatch.setattr(auth, "authenticate", authenticate)
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 0
    assert authenticated == {
        "env_url": "https://org.crm.dynamics.com",
        "preferred_username": "maker@example.com",
    }
    assert observed == {
        "runtime_reachability": False,
        "runtime_reachability_declined": False,
        "preserve_manual": True,
    }
    result = captured["result"]
    assert result.client_availability["dataverse"]["available"] is True
    assert result.requested_validation_context["agentSlug"] == "ess-hr"
    assert result.requested_validation_context["environmentId"] == ""
    assert result.validation_context["agentId"].endswith("3333")


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("profile_name", [
    "workday-da:post-connection",
    "workday-legacy:diagnostic",
])
@pytest.mark.parametrize("selection,expected", [
    ("none", False),
    ("explicit_da", True),
    ("explicit_legacy", False),
    ("configured_da", True),
    ("compatibility_da", True),
])
def test_profile_preserves_explicit_context_without_promoting_first_record(
    selection, expected, profile_name, reverse, tmp_path, monkeypatch,
) -> None:
    # Arrange: keep the real profile and CLI runner, but replace API checks.
    config = _config()
    config.pop("activeAgent")
    config["agents"] = [
        {"slug": "hr", "releaseLine": "da"},
        {"slug": "legacy", "releaseLine": "cea"},
    ]
    if reverse:
        config["agents"].reverse()
    if selection == "configured_da":
        config["activeAgent"] = "hr"
    if selection == "compatibility_da":
        config["agent"] = {"slug": "hr", "releaseLine": "da"}
    explicit_slug = {
        "explicit_da": "hr",
        "explicit_legacy": "legacy",
    }.get(selection)
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    observed = []

    def check(runner):
        observed.append((
            runner.agent_slug,
            runner.workday_da_profile,
            is_declarative_agent(runner),
        ))
        return []

    monkeypatch.setattr(registry, "profile_requirements", lambda _name: SimpleNamespace(
        clients=frozenset(),
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[("Applicability", check)],
    ))
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "save_results", lambda *_a, **_k: None)

    # Act.
    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args(
            profile=profile_name,
            agent_slug=explicit_slug,
            agent_schema_name=None,
        ))

    # Assert: missing evidence remains blocked, but list order never supplies DA identity.
    assert exc.value.code == 1
    da_profile = profile_name.startswith("workday-da:")
    selected_slug = (
        explicit_slug
        or config.get("activeAgent")
        or config.get("agent", {}).get("slug")
        or ""
    )
    assert observed == [(
        selected_slug,
        da_profile,
        expected or (selection == "none" and da_profile),
    )]


def test_profile_rejects_mixed_authenticated_accounts_without_hint(
    tmp_path,
    monkeypatch,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.DATAVERSE, registry.GRAPH}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )
    monkeypatch.setattr(
        registry,
        "resolve_profile",
        lambda _name: profile,
    )
    monkeypatch.setattr(
        registry,
        "profile_requirements",
        lambda _name: plan,
    )
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(
        registry,
        "profile_family_contract",
        lambda _name: {},
    )
    monkeypatch.setattr(
        auth,
        "discover_tenant",
        lambda _url: _config()["tenantId"],
    )
    monkeypatch.setattr(
        auth,
        "authenticate",
        lambda *_args, **_kwargs: (
            "dv-token",
            "dataverse@example.test",
        ),
    )

    observed = {}

    class _Graph:
        signed_in_username = "graph@example.test"

        def __init__(self, _tenant_id):
            pass

        def authenticate(self, preferred_username=None):
            observed["preferred_username"] = preferred_username

    monkeypatch.setattr(cli, "GraphClient", _Graph)
    monkeypatch.setattr(
        cli,
        "_print_prioritized_summary",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        cli,
        "_emit_run_telemetry",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(cli, "save_results", lambda *_a, **_k: None)

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args(preferred_username=None))

    assert exc.value.code == 1
    assert observed["preferred_username"] == "dataverse@example.test"


def test_bap_only_profile_does_not_request_flow_audience(
    tmp_path,
    monkeypatch,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:setup-readiness",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.PP_ADMIN}),
        pp_admin_flow_required=False,
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )
    observed = {}

    class BapOnlyAdmin:
        signed_in_username = "maker@example.com"

        def __init__(self, _tenant_id):
            pass

        def authenticate(
            self,
            *,
            include_flow=True,
            preferred_username=None,
        ):
            observed["include_flow"] = include_flow
            observed["preferred_username"] = preferred_username
            return "token"

        def find_environment_id_by_dataverse_url(self, _url):
            return _config()["environmentId"]

    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(registry, "profile_family_contract", lambda _name: {})
    monkeypatch.setattr(auth, "discover_tenant", lambda _url: _config()["tenantId"])
    monkeypatch.setattr(cli, "PPAdminClient", BapOnlyAdmin)
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "save_results", lambda *_a, **_k: None)

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args(profile=profile.name))

    assert exc.value.code == 0
    assert observed == {
        "include_flow": False,
        "preferred_username": "maker@example.com",
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"environment_url": "https://other.crm.dynamics.com"},
            "--environment-url",
        ),
        (
            {
                "environment_id":
                    "00000000-0000-0000-0000-000000009999",
            },
            "--environment-id",
        ),
        (
            {"tenant_id": "00000000-0000-0000-0000-000000008888"},
            "--tenant-id",
        ),
    ],
)
def test_profile_rejects_target_mismatch(
    tmp_path,
    monkeypatch,
    capsys,
    overrides,
    message,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(
        registry,
        "profile_requirements",
        lambda _name: SimpleNamespace(
            clients=frozenset(),
            requires_config=True,
            requires_dataverse_endpoint=False,
        ),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args(**overrides))

    assert exc.value.code == 1
    assert message in capsys.readouterr().out


def test_profile_auth_failure_is_a_blocking_result(
    tmp_path,
    monkeypatch,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(
        registry,
        "profile_family_contract",
        lambda _name: {},
    )
    monkeypatch.setattr(
        auth,
        "discover_tenant",
        lambda _url: _config()["tenantId"],
    )
    def fail_authentication(*_args, **_kwargs):
        raise SystemExit(1)

    monkeypatch.setattr(auth, "authenticate", fail_authentication)
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1
    result = captured["result"]
    blocker = next(
        row for row in result.results
        if row.checkpoint_id == "PROFILE-CLIENT-DATAVERSE"
    )
    assert blocker.status == Status.BLOCKED.value
    assert "SystemExit" in blocker.result
    assert result.overall == "NOT_READY"


def test_explicit_unknown_agent_does_not_fall_back_to_legacy_agent() -> None:
    config = _config()
    config["agent"] = {
        "slug": "legacy-agent",
        "schemaName": "gptagent_legacy",
        "botId": "00000000-0000-0000-0000-000000004444",
    }

    with pytest.raises(ValueError, match="does not resolve"):
        cli._validation_context_from_args(
            _args(agent_slug="missing-agent"),
            config,
            config["dataverseEndpoint"],
            config["environmentId"],
        )


def test_configured_unknown_active_agent_does_not_fall_back_to_legacy() -> None:
    config = _config()
    config["activeAgent"] = "missing-agent"
    config["agent"] = {
        "slug": "legacy-agent",
        "schemaName": "gptagent_legacy",
        "botId": "00000000-0000-0000-0000-000000004444",
    }

    with pytest.raises(ValueError, match="missing-agent.*does not resolve"):
        cli._validation_context_from_args(
            _args(agent_slug=None),
            config,
            config["dataverseEndpoint"],
            config["environmentId"],
        )


def test_validation_context_rejects_requested_tenant_mismatch() -> None:
    config = _config()

    with pytest.raises(ValueError, match="authenticated profile target"):
        cli._validation_context_from_args(
            _args(tenant_id="00000000-0000-0000-0000-000000009999"),
            config,
            config["dataverseEndpoint"],
            config["environmentId"],
        )


@pytest.mark.parametrize(
    ("endpoint", "expected_reason"),
    [
        (None, "powerPlatformApiEndpoint is missing"),
        (
            "https://wrong.example",
            "must be a supported HTTPS environment host",
        ),
    ],
)
def test_agentbuilder_configuration_failure_creates_blocking_result(
    tmp_path,
    monkeypatch,
    endpoint,
    expected_reason,
) -> None:
    config = _config()
    if endpoint is not None:
        config["powerPlatformApiEndpoint"] = endpoint
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(config),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.AGENTBUILDER}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(registry, "profile_family_contract", lambda _name: {})
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1
    result = captured["result"]
    blocker = next(
        row for row in result.results
        if row.checkpoint_id == "PROFILE-CLIENT-AGENTBUILDER"
    )
    assert blocker.status == Status.BLOCKED.value
    assert expected_reason in blocker.result
    assert result.validation_context["agentSlug"] == "ess-hr"


def test_native_tenant_mismatch_creates_blocking_result(
    tmp_path,
    monkeypatch,
) -> None:
    config = _config()
    config["powerPlatformApiEndpoint"] = (
        "https://0000000000000000000000000000222."
        "2.environment.api.powerplatform.com"
    )
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(config),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.AGENTBUILDER}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(registry, "profile_family_contract", lambda _name: {})
    monkeypatch.setattr(
        cli,
        "authenticate_flightcheck",
        lambda *_a, **_k: (
            "token",
            "00000000-0000-0000-0000-000000009999",
            "maker@example.com",
        ),
    )
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1
    result = captured["result"]
    blocker = next(
        row for row in result.results
        if row.checkpoint_id == "PROFILE-CLIENT-AGENTBUILDER"
    )
    assert blocker.status == Status.BLOCKED.value
    assert "ValueError" in blocker.result


def test_native_environment_mismatch_creates_blocking_result(
    tmp_path,
    monkeypatch,
) -> None:
    config = _config()
    config["powerPlatformApiEndpoint"] = (
        "https://0000000000000000000000000000999."
        "9.environment.api.powerplatform.com"
    )
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(config),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.AGENTBUILDER}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(registry, "profile_family_contract", lambda _name: {})
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1
    blocker = next(
        row for row in captured["result"].results
        if row.checkpoint_id == "PROFILE-CLIENT-AGENTBUILDER"
    )
    assert "different environment" in blocker.result


def test_native_valid_split_host_is_accepted_without_emitting_identity(
    tmp_path,
    monkeypatch,
) -> None:
    config = _config()
    config.pop("environmentId")
    config["powerPlatformApiEndpoint"] = (
        "https://0000000000000000000000000000222."
        "2.environment.api.powerplatform.com"
    )
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(config),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.AGENTBUILDER}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(registry, "profile_family_contract", lambda _name: {})
    observed = {}

    def authenticate_native(*_args, **kwargs):
        observed.update(kwargs)
        return "token", config["tenantId"], "maker@example.com"

    monkeypatch.setattr(cli, "authenticate_flightcheck", authenticate_native)
    monkeypatch.setattr(
        cli,
        "AgentBuilderClient",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 0
    assert observed["account_hint"] == "maker@example.com"
    assert observed["emit_account_identity"] is False
    assert observed["return_account_identity"] is True
    assert (
        captured["result"].validation_context["environmentId"]
        == "00000000-0000-0000-0000-000000002222"
    )


def test_native_preferred_account_mismatch_blocks_profile(
    tmp_path,
    monkeypatch,
) -> None:
    config = _config()
    config["powerPlatformApiEndpoint"] = (
        "https://0000000000000000000000000000222."
        "2.environment.api.powerplatform.com"
    )
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.AGENTBUILDER}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(registry, "profile_family_contract", lambda _name: {})
    monkeypatch.setattr(
        cli,
        "authenticate_flightcheck",
        lambda *_a, **_k: (
            "token",
            config["tenantId"],
            "other@example.com",
        ),
    )
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1
    state = captured["result"].client_availability["agentbuilder"]
    assert state["available"] is False
    assert state["authenticatedAccountVerified"] is False
    assert state["reason"] == "ValueError"


def test_dataverse_preferred_account_mismatch_blocks_profile(
    tmp_path,
    monkeypatch,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(registry, "profile_family_contract", lambda _name: {})
    monkeypatch.setattr(auth, "discover_tenant", lambda _url: _config()["tenantId"])
    monkeypatch.setattr(
        auth,
        "authenticate",
        lambda *_a, **_k: ("token", "other@example.com"),
    )
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1
    state = captured["result"].client_availability["dataverse"]
    assert state["available"] is False
    assert state["reason"] == "ValueError"


def test_preferred_account_requires_observed_graph_identity(
    tmp_path,
    monkeypatch,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.GRAPH}),
        requires_config=True,
        requires_dataverse_endpoint=False,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )

    class GraphWithoutIdentity:
        signed_in_username = None

        def __init__(self, _tenant_id) -> None:
            pass

        def authenticate(self, preferred_username=None):
            return "token"

    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(registry, "profile_family_contract", lambda _name: {})
    monkeypatch.setattr(auth, "discover_tenant", lambda _url: _config()["tenantId"])
    monkeypatch.setattr(cli, "GraphClient", GraphWithoutIdentity)
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1
    state = captured["result"].client_availability["graph"]
    assert state["available"] is False
    assert state["reason"] == "ValueError"
    assert "authenticatedAccount" not in state


def test_profile_rejects_discovered_tenant_mismatch_before_authentication(
    tmp_path,
    monkeypatch,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[],
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        auth,
        "discover_tenant",
        lambda _url: "00000000-0000-0000-0000-000000009999",
    )
    monkeypatch.setattr(
        auth,
        "authenticate",
        lambda *_a, **_k: pytest.fail(
            "authentication must not run after target mismatch"
        ),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1


def test_profile_rejects_inconclusive_tenant_discovery_before_authentication(
    tmp_path,
    monkeypatch,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[],
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(auth, "discover_tenant", lambda _url: "organizations")
    monkeypatch.setattr(
        auth,
        "authenticate",
        lambda *_a, **_k: pytest.fail(
            "authentication must not run without a concrete tenant"
        ),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1


@pytest.mark.parametrize(
    ("lookup_error", "expected_reason"),
    [
        (False, "Dataverse environment binding could not be resolved"),
        (True, "RuntimeError"),
    ],
)
def test_profile_rejects_unproven_dataverse_environment_binding(
    tmp_path,
    monkeypatch,
    lookup_error,
    expected_reason,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.PP_ADMIN}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[],
    )

    class AdminWithoutEnvironmentMatch:
        signed_in_username = "maker@example.com"

        def __init__(self, _tenant_id):
            pass

        def authenticate(self, preferred_username=None):
            return "token"

        def find_environment_id_by_dataverse_url(self, _url):
            if lookup_error:
                raise RuntimeError("lookup failed")
            return None

    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(registry, "profile_family_contract", lambda _name: {})
    monkeypatch.setattr(auth, "discover_tenant", lambda _url: _config()["tenantId"])
    monkeypatch.setattr(cli, "PPAdminClient", AdminWithoutEnvironmentMatch)
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1
    state = captured["result"].client_availability["pp_admin"]
    assert state["available"] is False
    assert state["authenticatedAccountVerified"] is False
    assert state["reason"] == expected_reason


def test_connect_profile_accepts_controller_verified_environment_binding(
    tmp_path,
    monkeypatch,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(_config()),
        encoding="utf-8",
    )
    connect_config = tmp_path / "connect.json"
    connect_config.write_text(json.dumps(_config()), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.PP_ADMIN}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[("Test", lambda _runner: [_passed()])],
    )

    class AdminWithoutEnvironmentMatch:
        signed_in_username = "maker@example.com"

        def __init__(self, _tenant_id):
            pass

        def authenticate(self, preferred_username=None):
            return "token"

        def find_environment_id_by_dataverse_url(self, _url):
            return None

    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        registry,
        "profile_matches",
        lambda _name, emitted: emitted == "TEST-001",
    )
    monkeypatch.setattr(registry, "profile_family_contract", lambda _name: {})
    monkeypatch.setattr(auth, "discover_tenant", lambda _url: _config()["tenantId"])
    monkeypatch.setattr(cli, "PPAdminClient", AdminWithoutEnvironmentMatch)
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "_emit_run_telemetry", lambda *_a, **_k: None)
    captured = {}
    monkeypatch.setattr(
        cli,
        "save_results",
        lambda result, _output: captured.setdefault("result", result),
    )

    args = _args(
        invocation_source="connect",
        connect_config=str(connect_config),
        environment_id=_config()["environmentId"],
        environment_url=_config()["dataverseEndpoint"],
    )
    with pytest.raises(SystemExit) as exc:
        cli._run_profile(args)

    assert exc.value.code == 0
    state = captured["result"].client_availability["pp_admin"]
    assert state["available"] is True
    assert state["authenticatedAccountVerified"] is True


def test_profile_rejects_runtime_reachability_before_auth(monkeypatch) -> None:
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("ENV-001",),
        description="test",
    )
    monkeypatch.setattr(
        registry,
        "resolve_profile",
        lambda _name: profile,
    )
    monkeypatch.setattr(
        registry,
        "profile_requirements",
        lambda _name: SimpleNamespace(clients=frozenset()),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args(runtime_reachability=True))

    assert exc.value.code == 2


@pytest.mark.parametrize("config_text", ["{", "[]"])
def test_profile_rejects_malformed_base_config(
    tmp_path,
    monkeypatch,
    config_text,
) -> None:
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(config_text, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(
        registry,
        "profile_requirements",
        lambda _name: SimpleNamespace(
            clients=frozenset(),
            requires_config=True,
            requires_dataverse_endpoint=False,
        ),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args())

    assert exc.value.code == 1


def test_profile_rejects_invalid_config_realm_before_authentication(
    tmp_path,
    monkeypatch,
) -> None:
    config = _config()
    config["realm"] = "production-ish"
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps(config),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-001",),
        description="test",
    )
    plan = SimpleNamespace(
        clients=frozenset({registry.DATAVERSE}),
        requires_config=True,
        requires_dataverse_endpoint=True,
        ordered_fns=[],
    )
    monkeypatch.setattr(registry, "resolve_profile", lambda _name: profile)
    monkeypatch.setattr(registry, "profile_requirements", lambda _name: plan)
    monkeypatch.setattr(
        auth,
        "discover_tenant",
        lambda _url: pytest.fail("tenant discovery must not run"),
    )
    monkeypatch.setattr(
        auth,
        "authenticate",
        lambda *_a, **_k: pytest.fail("authentication must not run"),
    )

    with pytest.raises(SystemExit) as exc:
        cli._run_profile(_args(validation_realm=None))

    assert exc.value.code == 1


def test_required_client_failure_creates_blocking_result() -> None:
    rows = cli._profile_client_blockers({
        "graph": {
            "required": True,
            "available": False,
            "reason": "consent missing",
        },
        "pp_admin": {
            "required": True,
            "available": True,
            "reason": "",
        },
    })

    assert len(rows) == 1
    row = rows[0]
    assert row.checkpoint_id == "PROFILE-CLIENT-GRAPH"
    assert row.status == "Blocked"
    assert "consent missing" in row.result
    assert "Restore access" in row.remediation


def test_client_error_reason_does_not_persist_exception_text() -> None:
    reason = cli._safe_client_error_reason(
        RuntimeError("token=secret backend response")
    )

    assert reason == "RuntimeError"
    assert "secret" not in reason


def test_profile_checkpoint_contract_blocks_missing_and_unresolved_rows() -> None:
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("WD-DA-PKG-001", "TEST-REQUIRED-001"),
        description="test",
    )
    runner = SimpleNamespace(results=[
        CheckResult(
            checkpoint_id="TEST-REQUIRED-001",
            category="Workday DA",
            priority=Priority.CRITICAL.value,
            status=Status.NOT_CONFIGURED.value,
            description="runtime",
            result="missing evidence",
        ),
    ])

    rows = cli._profile_checkpoint_contract_check(profile)(runner)

    assert {
        row.checkpoint_id: row.status for row in rows
    } == {
        "PROFILE-CHECKPOINT-MISSING": Status.BLOCKED.value,
        "PROFILE-CHECKPOINT-UNRESOLVED": Status.BLOCKED.value,
    }


def test_profile_checkpoint_contract_flags_guided_rows() -> None:
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("WD-DA-ATTACH-001",),
        description="test",
    )
    runner = SimpleNamespace(results=[
        CheckResult(
            checkpoint_id="WD-DA-ATTACH-001",
            category="Workday DA",
            priority=Priority.HIGH.value,
            status=Status.MANUAL.value,
            description="attachment",
            result="guided",
        ),
    ])

    rows = cli._profile_checkpoint_contract_check(profile)(runner)

    assert len(rows) == 1
    assert rows[0].checkpoint_id == "PROFILE-CHECKPOINT-GUIDED"
    assert rows[0].status == Status.WARNING.value


def test_required_not_configured_row_makes_profile_not_ready() -> None:
    profile = registry.ProfileSpec(
        name="workday-da:test",
        checkpoint_ids=("TEST-REQUIRED-001",),
        description="test",
    )
    runner = FlightCheckRunner(
        scope="profile:workday-da:test",
        target_matcher=lambda checkpoint_id: (
            checkpoint_id == "TEST-REQUIRED-001"
            or checkpoint_id.startswith("PROFILE-CHECKPOINT-")
        ),
    )
    runner.register(
        "Workday DA",
        lambda _runner: [CheckResult(
            checkpoint_id="TEST-REQUIRED-001",
            category="Workday DA",
            priority=Priority.CRITICAL.value,
            status=Status.NOT_CONFIGURED.value,
            description="runtime",
            result="missing evidence",
        )],
    )
    runner.register(
        "FlightCheck Profile",
        cli._profile_checkpoint_contract_check(profile),
    )

    result = runner.run()

    assert result.blocked == 1
    assert result.overall == "NOT_READY"
    assert cli._run_exit_code(result) == 1


def test_profile_family_cardinality_blocks_zero_rows() -> None:
    runner = SimpleNamespace(results=[])
    check = cli._profile_family_cardinality_check({
        "WD-FLOW": {"minimum": 1}
    })

    row = check(runner)[0]

    assert row.status == "Blocked"
    assert "emitted 0 resolved validation row(s)" in row.result
    assert "WD-FLOW emits" in row.remediation


@pytest.mark.parametrize(
    "status",
    [
        Status.NOT_CONFIGURED.value,
        Status.SKIPPED.value,
        Status.WARNING.value,
        Status.MANUAL.value,
        Status.BLOCKED.value,
        Status.ERROR.value,
    ],
)
def test_profile_family_cardinality_rejects_unresolved_rows(status) -> None:
    runner = SimpleNamespace(results=[CheckResult(
        checkpoint_id="WD-FLOW-001",
        category="Workday",
        priority=Priority.HIGH.value,
        status=status,
        description="flow",
        result="unresolved",
    )])

    rows = cli._profile_family_cardinality_check({
        "WD-FLOW": {"minimum": 1}
    })(runner)

    assert len(rows) == 1
    assert rows[0].status == Status.BLOCKED.value


def test_family_cardinality_does_not_count_distinct_fixed_checkpoints() -> None:
    assert registry.matches("WD-CONN", "WD-CONN-002") is True
    assert registry.matches("WD-CONN", "WD-CONN-013") is False
    runner = SimpleNamespace(results=[CheckResult(
        checkpoint_id="WD-CONN-013",
        category="Workday",
        priority=Priority.HIGH.value,
        status=Status.PASSED.value,
        description="fixed checkpoint",
        result="passed",
    )])

    rows = cli._profile_family_cardinality_check({
        "WD-CONN": {"minimum": 1}
    })(runner)

    assert len(rows) == 1
    assert rows[0].status == Status.BLOCKED.value
