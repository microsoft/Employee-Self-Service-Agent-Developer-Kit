# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Standalone target and auth boundaries; API shapes come from the live cassette."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from flightcheck import cli
from flightcheck.checks import _connection_dependencies as dependencies
from tests.flightcheck.checks import test_env_004_workday_coverage as connection_tests


dependency_case = connection_tests.dependency_case


@pytest.mark.parametrize("existing_config", [False, True])
def test_env004_cli_needs_no_setup_state_and_ignores_other_local_target(
    dependency_case, tmp_path, monkeypatch, existing_config,
):
    case = dependency_case
    if existing_config:
        local = tmp_path / ".local"
        local.mkdir()
        # An explicit target must not even parse another workspace's setup state.
        (local / "config.json").write_text("unrelated malformed setup config", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    compact = case.runner.env_id.replace("-", "")
    host = f"https://{compact[:30]}.{compact[30:]}.environment.api.powerplatform.com"
    monkeypatch.setattr(cli, "derive_environment_host", lambda *_args: host)
    native_auth = Mock(return_value=(
        "REDACTED_TOKEN", case.runner.tenant_id, "maker@example.com",
    ))
    monkeypatch.setattr(cli, "authenticate_flightcheck", native_auth)
    monkeypatch.setattr(cli, "AgentBuilderClient", lambda *_args, **_kwargs: case.native)
    monkeypatch.setattr(cli, "ConnectivityClient", lambda *_args, **_kwargs: case.runner.connectivity)
    monkeypatch.setattr(cli, "authenticate_flightcheck_dependency", lambda *_args, **_kwargs: "REDACTED_TOKEN")
    pp = case.runner.pp_admin
    pp.has_flow_token = True
    pp.has_powerapps_token = True
    monkeypatch.setattr(dependencies, "PPAdminClient", lambda *_args: pp)
    monkeypatch.setattr(dependencies, "discover_tenant", lambda _url: case.runner.tenant_id)
    output = tmp_path / "results"
    cache = tmp_path / "original-cache.bin"
    monkeypatch.setattr(sys, "argv", [
        "flightcheck", "--checkpoint", "ENV-004",
        "--agent-id", case.agent_id, "--environment-id", case.runner.env_id,
        "--ring", "prod", "--preferred-username", "maker@example.com",
        "--token-cache", str(cache), "--output", str(output),
        "--no-open", "--no-telemetry",
    ])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 0
    report = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert report["overall"] == "READY"
    assert [(row["checkpoint_id"], row["status"]) for row in report["results"]] == [
        ("ENV-004", "Passed")
    ]
    assert (output / "report.html").exists()
    assert native_auth.call_args.kwargs["cache_path"] == cache
    case.native.get_agent.assert_called_once_with(case.agent_id)
    assert not (tmp_path / ".local" / "setup").exists()


@pytest.mark.parametrize("arguments", [
    ["--checkpoint", "ENV-004", "--agent-id", "not-a-guid"],
    ["--checkpoint", "ENV-004", "--agent-id", "00000000-0000-0000-0000-000000001111",
     "--environment-id", "not-an-environment-guid"],
    ["--scope", "full", "--agent-id", "00000000-0000-0000-0000-000000001111"],
    ["--scope", "workday", "--token-cache", "cache.bin"],
    ["--checkpoint", "ENV-004", "--agent-id", "00000000-0000-0000-0000-000000001111",
     "--environment-id", "00000000-0000-0000-0000-000000002222",
     "--connect-config", "other.json"],
])
def test_invalid_or_ambiguous_target_flags_are_rejected_before_auth(arguments, monkeypatch):
    authenticate = Mock()
    monkeypatch.setattr(cli, "authenticate_flightcheck", authenticate)
    monkeypatch.setattr(sys, "argv", ["flightcheck", *arguments])

    with pytest.raises(SystemExit) as exit_info:
        cli.main()

    assert exit_info.value.code == 2
    authenticate.assert_not_called()


def test_connection_setup_failure_does_not_disable_other_native_checks(dependency_case):
    dependency_case.runner.connection_validation_error = "Native target does not match the environment."

    audit = dependencies.audit_connections(dependency_case.runner)

    assert audit.blocked == "Native target does not match the environment."
    assert dependency_case.runner.agentbuilder is dependency_case.native
    dependency_case.native.get_agent.assert_not_called()


@pytest.mark.parametrize("mismatch", ["account", "tenant"])
def test_existing_native_identity_is_verified_before_dependency_access(
    dependency_case, monkeypatch, mismatch,
):
    case = dependency_case
    authenticate = Mock()
    monkeypatch.setattr(cli, "authenticate_flightcheck", authenticate)
    args = SimpleNamespace(
        agent_id=[case.agent_id], ring="prod",
        preferred_username="other@example.com" if mismatch == "account" else "maker@example.com",
        tenant_id="00000000-0000-0000-0000-000000009999" if mismatch == "tenant" else None,
    )

    with pytest.raises(ValueError, match="different"):
        cli._configure_connection_validation(
            case.runner, args, account="maker@example.com",
        )

    authenticate.assert_not_called()
    assert not hasattr(case.runner, "connection_dependency_token")
