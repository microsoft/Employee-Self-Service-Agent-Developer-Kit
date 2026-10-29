# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Local capability probes and resumable prerequisite recovery."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
import responses

import workday_connect_prerequisites as prerequisites
from workday_connect_model import default_state, PHASE_REQUIRED_ACTIONS
from workday_connect_store import WorkdayConnectStore


@pytest.fixture
def probes(monkeypatch):
    commands = []
    api_calls = []
    monkeypatch.setattr(prerequisites.shutil, "which", lambda _name: "pwsh")
    monkeypatch.setattr(prerequisites, "validate_object_model_runtime", lambda: None)
    monkeypatch.setattr(
        prerequisites, "verify_local_runtime_workspace", lambda *_args: {},
    )
    monkeypatch.setattr(
        prerequisites, "_api_connections", lambda context: api_calls.append(context) or [],
    )

    def runner(command, **kwargs):
        commands.append((command, kwargs))
        if command[0] == "pac.exe":
            assert command[-1] == "help"
            output = (
                "Version: 2.13.1\n--environment --application-name "
                "--cloud --deviceCode --index --json"
            )
        elif "ParseFile" in command[-1]:
            output = ""
        elif "Get-Command python" in command[-1]:
            output = json.dumps({
                "executable": sys.executable,
                "version": list(sys.version_info[:2]),
            })
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    return {
        "runner": runner,
        "commands": commands,
        "api_calls": api_calls,
        "pac_resolver": lambda: Path("pac.exe"),
    }


def _state():
    state = default_state()
    state["scope"].update({
        "environmentId": "environment-id",
        "entraTenantId": "tenant-id",
        "ring": "test",
    })
    state["operators"]["powerPlatformMaker"] = {"username": "maker@example.com"}
    return state


def _check(tmp_path, probes, *, package_installed=False, runner=None, resolver=None):
    checks = prerequisites.check_prerequisites(
        tmp_path, _state(), package_installed=package_installed,
        pac_resolver=resolver or probes["pac_resolver"],
        runner=runner or probes["runner"],
    )
    return {check["id"]: check for check in checks}


def test_healthy_probes_are_read_only_and_use_selected_identity(tmp_path, probes):
    checks = _check(tmp_path, probes)

    assert all(check["status"] == "verified" for check in checks.values())
    assert probes["api_calls"] == [{
        "environmentId": "environment-id",
        "tenantId": "tenant-id",
        "ring": "test",
        "maker": "maker@example.com",
        "agentBuilderApiVersion": prerequisites.configured_connection_api_version(tmp_path),
    }]
    assert all(kwargs["timeout"] == 60 for _, kwargs in probes["commands"])
    assert all(kwargs["cwd"] == tmp_path for _, kwargs in probes["commands"])
    assert all(
        command[-1] == "help" if command[0] == "pac.exe" else "-WhatIf" not in command
        for command, _ in probes["commands"]
    )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("configured_version", [None, "2022-03-01-preview"])
@responses.activate
def test_prerequisite_discovery_preserves_configured_api_version(
    tmp_path, probes, monkeypatch, configured_version,
):
    from copy import deepcopy
    from urllib.parse import parse_qs, urlsplit

    import workday_connect_runtime as runtime
    from tests.conftest import require_validated_mock
    from tests.mocks import agentbuilder_connectivity as native
    from tests.scripts.test_workday_connect_runtime import _api_token, TENANT_ID

    require_validated_mock(native)
    config = {} if configured_version is None else {
        "agentBuilderApiVersion": configured_version,
    }
    foundation = tmp_path / ".local" / "config.json"
    foundation.parent.mkdir()
    foundation.write_text(json.dumps(config), encoding="utf-8")
    original_config = foundation.read_bytes()
    state = _state()
    state["scope"].update({
        "environmentId": native.MOCK_ENV_ID, "entraTenantId": TENANT_ID,
    })
    original_state = deepcopy(state)
    monkeypatch.setattr(prerequisites, "_api_connections", runtime._api_connections)
    monkeypatch.setattr(
        runtime, "authenticate_connections",
        lambda *_a, **_k: _api_token(username="maker@example.com"),
    )
    expected_version = configured_version or runtime.DEFAULT_API_VERSION
    response = native.list_connections(items=[])
    response["url"] = response["url"].split("?")[0]
    responses.add(**response)

    checks = prerequisites.check_prerequisites(
        tmp_path, state, package_installed=True,
        pac_resolver=probes["pac_resolver"], runner=probes["runner"],
    )

    assert next(row for row in checks if row["id"] == "connection-api")["status"] == "verified"
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert request.method == "GET"
    assert parse_qs(urlsplit(request.url).query)["api-version"] == [expected_version]
    assert foundation.read_bytes() == original_config
    assert state == original_state


@pytest.mark.parametrize("installed", [False, True])
def test_missing_pac_is_conditional_on_package_installation(tmp_path, probes, installed):
    def missing():
        raise prerequisites.PacCliError("PAC CLI is not installed.")

    checks = _check(tmp_path, probes, package_installed=installed, resolver=missing)

    assert checks["pac-install"]["status"] == ("warning" if installed else "blocked")
    assert checks["pac-discovery"]["status"] == "warning"
    assert "managed" in checks["pac-install"]["remediation"]["steps"][0]
    assert bool(probes["api_calls"]) == installed


def test_unsupported_discovery_is_warning_and_identifies_exact_pac(tmp_path, probes):
    def runner(command, **kwargs):
        if command[1:3] == ["connectivity", "list-connections"]:
            return subprocess.CompletedProcess(
                command, 1, stdout="Version: 1.44.0", stderr="Not a valid command.",
            )
        return probes["runner"](command, **kwargs)

    checks = _check(tmp_path, probes, runner=runner)

    assert checks["pac-discovery"]["status"] == "warning"
    guidance = checks["pac-discovery"]["remediation"]["steps"][0]
    assert "pac.exe" in guidance
    assert "connectivity list-connections help" in guidance
    assert checks["connection-api"]["status"] == "verified"


@pytest.mark.parametrize("installed", [False, True])
def test_missing_install_option_is_not_accepted_based_on_version(
    tmp_path, probes, installed,
):
    def runner(command, **kwargs):
        if command[1:3] == ["application", "install"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="Version: 99.0 --environment", stderr="",
            )
        return probes["runner"](command, **kwargs)

    checks = _check(tmp_path, probes, package_installed=installed, runner=runner)

    assert checks["pac-install"]["status"] == ("warning" if installed else "blocked")
    assert "required options" in checks["pac-install"]["detail"]
    assert "application install help" in checks["pac-install"]["remediation"]["steps"][0]


@pytest.mark.parametrize("failure", ["missing", "parse", "timeout"])
def test_powershell_failure_blocks_before_service_sign_in(
    tmp_path, probes, monkeypatch, failure,
):
    if failure == "missing":
        monkeypatch.setattr(prerequisites.shutil, "which", lambda _name: None)

    def runner(command, **kwargs):
        if command[0] == "pwsh" and "ParseFile" in command[-1]:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 60)
            if failure == "parse":
                return subprocess.CompletedProcess(
                    command, 1, stdout="", stderr="Unsupported script syntax.",
                )
        return probes["runner"](command, **kwargs)

    checks = _check(tmp_path, probes, runner=runner)

    assert checks["powershell"]["status"] == "blocked"
    assert "Runtime flow authorization" in checks["powershell"]["impact"]
    assert checks["connection-api"]["status"] == "pending"
    assert probes["api_calls"] == []
    assert checks["powershell"]["remediation"]["commands"] == []


@pytest.mark.parametrize("failure", ["different-python", "imports", "malformed"])
def test_python_mismatch_or_missing_dependencies_offer_scoped_repair(
    tmp_path, probes, failure,
):
    def runner(command, **kwargs):
        if command[0] == "pwsh" and "Get-Command python" in command[-1]:
            if failure == "imports":
                return subprocess.CompletedProcess(
                    command, 1, stdout="", stderr="ModuleNotFoundError: msal",
                )
            output = (
                "invalid-json" if failure == "malformed"
                else json.dumps({"executable": "other-python", "version": [3, 12]})
            )
            return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")
        return probes["runner"](command, **kwargs)

    checks = _check(tmp_path, probes, runner=runner)

    check = checks["python"]
    assert check["status"] == "blocked"
    assert "authentication environment" in check["impact"]
    assert "Activate the same Python environment" in check["remediation"]["steps"][0]
    assert check["remediation"]["requiresApproval"] is True
    assert "requirements.txt" in check["remediation"]["commands"][0]
    assert not probes["api_calls"]


def test_object_model_failure_reuses_shared_validator_and_existing_installer(
    tmp_path, probes, monkeypatch,
):
    def broken():
        raise prerequisites.ObjectModelConverterError("No matching .NET 10 runtime found.")
    monkeypatch.setattr(prerequisites, "validate_object_model_runtime", broken)

    check = _check(tmp_path, probes)["object-model"]

    assert check["status"] == "blocked"
    assert ".NET 10" in check["detail"]
    assert "matching Python's architecture" in check["remediation"]["steps"][0]
    assert "install_agentbuilder_object_model.py" in check["remediation"]["commands"][0]


def test_invalid_workspace_offers_non_destructive_setup_recovery(
    tmp_path, probes, monkeypatch,
):
    def broken(*_args):
        raise prerequisites.WorkdayConnectAgentError("Mapped topic file is missing.")
    monkeypatch.setattr(prerequisites, "verify_local_runtime_workspace", broken)

    check = _check(tmp_path, probes)["workspace"]

    assert check["status"] == "blocked"
    assert check["remediation"]["kind"] == "workspace"
    assert "same selected agent" in check["remediation"]["steps"][0]
    assert "Preserve local edits" in check["remediation"]["steps"][1]
    assert check["remediation"]["commands"] == []


@pytest.mark.parametrize("fallback", [False, True])
def test_api_failure_warns_only_when_compatible_fallback_exists(
    tmp_path, probes, monkeypatch, fallback,
):
    def denied(*_args):
        raise prerequisites.AgentBuilderError("Connection listing failed with HTTP 403")
    monkeypatch.setattr(prerequisites, "_api_connections", denied)

    def runner(command, **kwargs):
        if not fallback and command[1:3] == ["connectivity", "list-connections"]:
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="Unknown command")
        return probes["runner"](command, **kwargs)

    check = _check(tmp_path, probes, runner=runner)["connection-api"]

    assert check["status"] == ("warning" if fallback else "blocked")
    assert "HTTP 403" in check["detail"]
    assert check["remediation"]["kind"] == "service"
    assert "administrator" in check["remediation"]["steps"][0]
    assert check["remediation"]["commands"] == []


def test_identity_mismatch_is_blocking_even_with_compatible_pac(
    tmp_path, probes, monkeypatch,
):
    def mismatch(*_args):
        raise prerequisites.WorkdayConnectIdentityError("A different account was returned.")
    monkeypatch.setattr(prerequisites, "_api_connections", mismatch)

    check = _check(tmp_path, probes)["connection-api"]

    assert check["status"] == "blocked"
    assert check["remediation"]["kind"] == "sign-in"
    assert "Step 1: maker@example.com" in check["remediation"]["steps"][0]


def test_preflight_persists_blocker_then_resumes_without_discarding_handoffs(
    tmp_path, probes, monkeypatch,
):
    import workday_connect_preflight as preflight
    from tests.scripts.test_workday_connect_preflight import _write_foundation, ENV_URL

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
    store = WorkdayConnectStore(tmp_path)
    kwargs = {
        "dataverse_url": ENV_URL,
        "maker_username": "maker@example.com",
        "store": store,
        "token_provider": lambda *_args, **_kwargs: "token",
        "identity_provider": lambda *_args, **_kwargs: {
            "username": "maker@example.com", "tenantId": "tenant-id",
        },
        "query": lambda *_args: [{"uniquename": "msdyn_EssWorkdayRuntime"}],
        "pac_resolver": probes["pac_resolver"],
        "pac_runner": probes["runner"],
    }
    first = preflight.run_preflight(tmp_path, **kwargs)
    assert len(first["verificationChecks"]) == 9
    for phase_id in ("entra", "workday-admin"):
        for action in PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(phase_id, action, evidence={"outcome": "verified"})
        store.set_phase_status(phase_id, "complete")
    before = store.load()["phases"]

    def broken():
        raise prerequisites.ObjectModelConverterError("Missing assemblies.")
    monkeypatch.setattr(prerequisites, "validate_object_model_runtime", broken)
    with pytest.raises(preflight.WorkdayConnectPreflightError) as raised:
        preflight.run_preflight(tmp_path, **kwargs)

    assert raised.value.details["verificationChecks"]
    blocked = store.load()["phases"]
    assert blocked["preflight"]["status"] == "complete"
    assert blocked["connections"]["status"] == "blocked"
    assert blocked["connections"]["blocker"]["details"]["verificationChecks"]
    for phase_id in ("entra", "workday-admin"):
        assert blocked[phase_id] == before[phase_id]

    monkeypatch.setattr(prerequisites, "validate_object_model_runtime", lambda: None)
    final = preflight.run_preflight(tmp_path, **kwargs)

    assert final["status"]["nextPhaseId"] == "connections"
    after = store.load()["phases"]
    assert after["preflight"]["blocker"] is None
    for phase_id in ("entra", "workday-admin"):
        assert after[phase_id] == before[phase_id]


def test_controller_emits_repair_details_and_does_not_run_readiness_when_blocked(
    tmp_path, probes, monkeypatch, capsys,
):
    import workday_connect
    import workday_connect_preflight as preflight
    from tests.scripts.test_workday_connect_preflight import _write_foundation, ENV_URL

    _write_foundation(tmp_path, dataverse_url=ENV_URL)
    monkeypatch.setenv("ESS_ADK_TELEMETRY", "off")
    monkeypatch.setattr(workday_connect, "_ensure_migration_baseline", lambda _store: None)
    monkeypatch.setattr(
        workday_connect, "_run_profile_gate",
        lambda *_args: pytest.fail("Live readiness must wait for local repair."),
    )
    real_preflight = preflight.run_preflight
    def run(root, **kwargs):
        return real_preflight(
            root, **kwargs,
            token_provider=lambda *_args, **_kwargs: "token",
            identity_provider=lambda *_args, **_kwargs: {
                "username": "maker@example.com", "tenantId": "tenant-id",
            },
            query=lambda *_args: [{"uniquename": "msdyn_EssWorkdayRuntime"}],
            pac_resolver=probes["pac_resolver"], pac_runner=probes["runner"],
        )
    monkeypatch.setattr(workday_connect, "run_preflight", run)
    def broken():
        raise prerequisites.ObjectModelConverterError("Missing assemblies.")
    monkeypatch.setattr(prerequisites, "validate_object_model_runtime", broken)
    monkeypatch.setattr(
        sys, "argv", ["workday_connect.py", "--root", str(tmp_path), "preflight"],
    )

    with pytest.raises(SystemExit) as raised:
        workday_connect.main()

    assert raised.value.code == 1
    error_line = next(
        line for line in capsys.readouterr().err.splitlines()
        if line.startswith(workday_connect.ERROR_MARKER)
    )
    payload = json.loads(error_line[len(workday_connect.ERROR_MARKER):])
    assert any(
        check["id"] == "object-model" and check["status"] == "blocked"
        for check in payload["details"]["verificationChecks"]
    )
    assert WorkdayConnectStore(tmp_path).load()["phases"]["preflight"]["blocker"][
        "errorType"
    ] == "WorkdayConnectPrerequisiteError"


def test_repeated_prerequisite_failure_preserves_an_existing_operation_blocker(tmp_path):
    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    original = {
        "operation": "preflight",
        "errorType": "ExistingAccessError",
        "message": "The selected account cannot access this environment.",
    }
    store.set_phase_status("preflight", "blocked", blocker=original)
    check = {
        "id": "powershell", "name": "PowerShell", "status": "blocked",
        "detail": "PowerShell is missing.",
    }

    store.record_preflight_checks([check])
    store.record_preflight_checks([check])
    saved = store.load()["phases"]["preflight"]["blocker"]
    assert saved["previousBlocker"] == original

    store.record_preflight_checks([{**check, "status": "verified"}])
    phase = store.load()["phases"]["preflight"]
    assert phase["status"] == "blocked"
    assert phase["blocker"] == original
