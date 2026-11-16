# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Standalone selection control flow; native lookup uses approved API fixtures."""

import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
import responses

import flightcheck_setup as setup
from agentbuilder import AgentBuilderClient, derive_environment_host
from flightcheck.agent_scope import is_declarative_agent
from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as native


ENV_ID = native.MOCK_ENV_ID
AGENT_ID = native.MOCK_AGENT_ID
TENANT_ID = "00000000-0000-0000-0000-000000004444"
URL = f"https://copilotstudio.microsoft.com/environments/{ENV_ID}/copilots/{AGENT_ID}"


@pytest.fixture
def selection(tmp_path, monkeypatch):
    require_validated_mock(native)
    auth_calls = []

    def authenticate(ring, **kwargs):
        auth_calls.append((ring, kwargs))
        return "mock-token", TENANT_ID, "maker@example.test"

    monkeypatch.setattr(setup, "authenticate_flightcheck", authenticate)
    return SimpleNamespace(
        root=tmp_path, config=tmp_path / ".local" / "config.json", auth=auth_calls,
    )


def _answer(monkeypatch, *answers):
    values = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _: next(values))


def _existing(selection, config):
    selection.config.parent.mkdir(exist_ok=True)
    selection.config.write_text(json.dumps(config), encoding="utf-8")
    return selection.config.read_bytes()


def _lookup(http, ring="prod", *, payload=None, status=200):
    http.add(
        responses.GET,
        f"{derive_environment_host(ENV_ID, ring)}/copilotstudio/minimalBots/api/{AGENT_ID}",
        json=payload if payload is not None else native.agent(),
        status=status,
    )


@pytest.mark.parametrize("ring", ["prod", "preprod", "test"])
def test_native_picker_supports_environments_without_dataverse(selection, monkeypatch, ring):
    _answer(monkeypatch, "", "1", "1")
    monkeypatch.setattr(setup, "list_environments", lambda *a, **k: [
        {"id": ENV_ID, "displayName": "Native environment"},
    ])
    monkeypatch.setattr(AgentBuilderClient, "list_minimal_bots", lambda _: [native.agent()])
    with responses.RequestsMock() as http:
        _lookup(http, ring)
        config = setup.configure_standalone(selection.root, ring)
    assert config["environmentId"] == ENV_ID
    assert config["tenantId"] == TENANT_ID
    assert config["ring"] == ring
    assert config["agent"]["botId"] == AGENT_ID
    assert "dataverseEndpoint" not in config
    assert config["setup"] == "flightcheck-only"
    assert is_declarative_agent(SimpleNamespace(config=config))
    assert json.loads(selection.config.read_text()) == config
    assert not (selection.root / ".local" / "setup").exists()
    _, kwargs = selection.auth[0]
    assert kwargs["force_account_selection"] is True
    assert kwargs["require_account_identity"] is True
    assert kwargs["allow_write"] is False
    assert kwargs["include_connectivity"] is False


def test_url_migrates_old_standalone_config_after_native_verification(selection, monkeypatch):
    _existing(selection, {
        "flightCheckOnly": True, "dataverseEndpoint": "https://old.example.test",
        "agent": {"botId": ""}, "agents": [], "activeAgent": "",
        "agentBuilderApiVersion": "2025-01-01",
    })
    _answer(monkeypatch, URL)
    with responses.RequestsMock() as http:
        _lookup(http)
        config = setup.configure_standalone(selection.root, "prod")
        assert "api-version=2025-01-01" in http.calls[0].request.url
    assert config["releaseLine"] == config["agent"]["releaseLine"] == "da"
    assert config["activeAgent"] == config["agents"][0]["slug"]
    assert "dataverseEndpoint" not in config
    assert "transport" not in config


@pytest.mark.parametrize("status,payload", [
    (403, {"error": {"message": "Access denied"}}),
    (404, {"error": {"message": "Not a native agent"}}),
    (200, {**native.agent(), "botId": ENV_ID}),
])
def test_unverified_or_legacy_agent_never_replaces_saved_target(
    selection, monkeypatch, capsys, status, payload,
):
    before = _existing(selection, {"flightCheckOnly": True, "agent": {"botId": ""}})
    _answer(monkeypatch, URL)
    with responses.RequestsMock() as http:
        _lookup(http, payload=payload, status=status)
        assert setup.main(["--kit-root", str(selection.root)]) == 1
    assert selection.config.read_bytes() == before
    assert "DA selection failed" in capsys.readouterr().err


@pytest.mark.parametrize("answers", [("", ""), ("", "2"), ("", "1", "")])
def test_picker_cannot_skip_into_legacy_checks(selection, monkeypatch, answers, capsys):
    _answer(monkeypatch, *answers)
    monkeypatch.setattr(setup, "list_environments", lambda *a, **k: [{"id": ENV_ID}])
    monkeypatch.setattr(AgentBuilderClient, "list_minimal_bots", lambda _: [native.agent()])
    assert setup.main(["--kit-root", str(selection.root)]) == 1
    assert not selection.config.exists()
    assert "selection cannot be skipped" in capsys.readouterr().err


def test_existing_maker_workspace_is_not_overwritten(selection, capsys):
    before = _existing(selection, {"releaseLine": "da", "setup": "complete"})
    assert setup.main(["--kit-root", str(selection.root)]) == 1
    assert selection.config.read_bytes() == before
    assert not selection.auth
    assert "existing maker workspace" in capsys.readouterr().err


def test_unverifiable_account_cannot_replace_saved_target(selection, monkeypatch, capsys):
    before = _existing(selection, {"flightCheckOnly": True})
    _answer(monkeypatch, URL)
    monkeypatch.setattr(
        setup, "authenticate_flightcheck", lambda *a, **k: ("token", TENANT_ID, None),
    )
    assert setup.main(["--kit-root", str(selection.root)]) == 1
    assert selection.config.read_bytes() == before
    assert "did not verify the selected Microsoft account" in capsys.readouterr().err


def test_ring_mismatch_is_rejected_before_sign_in(selection, monkeypatch, capsys):
    _answer(monkeypatch, URL)
    assert setup.main(["--kit-root", str(selection.root), "--ring", "test"]) == 1
    assert not selection.auth
    assert not selection.config.exists()
    assert "ring" in capsys.readouterr().err


def test_cancelled_selection_does_not_replace_configuration(selection, monkeypatch, capsys):
    before = _existing(selection, {"flightCheckOnly": True})

    def cancel(_):
        raise EOFError

    monkeypatch.setattr("builtins.input", cancel)
    assert setup.main(["--kit-root", str(selection.root)]) == 130
    assert selection.config.read_bytes() == before
    assert "FlightCheck was not started" in capsys.readouterr().err


@pytest.mark.parametrize("setup_exit", [0, 1, 130])
def test_windows_entrypoint_only_runs_cli_after_successful_da_selection(tmp_path, setup_exit):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        pytest.skip("PowerShell is required to exercise the Windows entrypoint.")
    root = Path(__file__).resolve().parents[2]
    installer = (root / "setup" / "Install-EssAdk.ps1").read_text(encoding="utf-8")
    section = installer.split("# 6. FlightCheck config generation", 1)[1]
    section = section[section.index("if ($FlightCheckOnly) {"):]
    section = section.split("# VS Code can retain", 1)[0]
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "flightcheck_setup.py").touch()
    (tmp_path / ".local").mkdir()
    (tmp_path / ".local" / "config.json").write_text(json.dumps({
        "releaseLine": "da", "agent": {"botId": AGENT_ID}, "activeAgent": "selected-da",
        "tenantId": TENANT_ID, "account": "maker@example.test", "ring": "test",
    }), encoding="utf-8")
    workspace = str(tmp_path).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
$workspace = '{workspace}'
$FlightCheckOnly = $true
$Ring = 'test'
$script:calls = [System.Collections.Generic.List[object]]::new()
$script:outcome = ''
$initialPath = (Get-Location).Path
function Write-Step {{ param($Message) }}
function Resolve-Python {{ return 'Invoke-TestPython' }}
function Complete-EssInstallTelemetry {{ param($Outcome) $script:outcome = $Outcome }}
function Invoke-TestPython {{
    $script:calls.Add(@($args))
    if ($args[0] -like '*flightcheck_setup.py') {{
        $global:LASTEXITCODE = {setup_exit}
    }} else {{
        $global:LASTEXITCODE = 1
    }}
}}
$failure = ''
try {{ & {{
{section}
}} }} catch {{ $failure = $_.Exception.Message }}
@{{
    calls = @($script:calls.ToArray())
    failure = $failure
    outcome = $script:outcome
    exitCode = $global:LASTEXITCODE
    restoredPath = ((Get-Location).Path -eq $initialPath)
    restoredPreference = ($ErrorActionPreference -eq 'Stop')
}} | ConvertTo-Json -Depth 6 -Compress
"""
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["restoredPath"] and payload["restoredPreference"]
    assert len(payload["calls"]) == (2 if setup_exit == 0 else 1)
    if setup_exit:
        assert "FlightCheck was not started" in payload["failure"]
        assert payload["outcome"] == ""
    else:
        assert payload["failure"] == ""
        assert payload["outcome"] == "success"
        assert payload["exitCode"] == 1
        args = payload["calls"][1]
        assert args[args.index("--agent-slug") + 1] == "selected-da"
        assert args[args.index("--preferred-username") + 1] == "maker@example.test"
        assert args[args.index("--tenant-id") + 1] == TENANT_ID
        assert args[args.index("--ring") + 1] == "test"
        assert args[args.index("--select-targets") + 1] == "never"
