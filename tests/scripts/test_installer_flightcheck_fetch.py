# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Execute the installer's real snapshot-fetch block without network or installs."""

from __future__ import annotations

import base64
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import fetch_and_setup


INSTALLER = Path(__file__).resolve().parents[2] / "setup" / "Install-EssAdk.ps1"


def _ps_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@pytest.fixture(params=["powershell", "pwsh"])
def powershell(request: pytest.FixtureRequest) -> str:
    executable = shutil.which(request.param)
    if executable is None:
        pytest.skip(f"{request.param} is not installed")
    return executable


def _run_fetch(
    powershell: str,
    tmp_path: Path,
    *,
    exit_code: int = 0,
    stderr: bool = False,
    agent_selected: bool = True,
    script_exists: bool = True,
    python_exists: bool = True,
    da_target: bool = False,
) -> tuple[str, dict]:
    workspace = tmp_path / "maker's workspace"
    scripts = workspace / "scripts"
    scripts.mkdir(parents=True)
    if script_exists:
        (scripts / "fetch_and_setup.py").write_text(
            "import sys, json\n"
            "from pathlib import Path\n"
            "Path('fetch-args.json').write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
            "print('synthetic fetch stdout')\n"
            + (
                "sys.stderr.write('synthetic fetch diagnostic\\n"
                "synthetic diagnostic detail\\n')\n"
                if stderr
                else ""
            )
            + f"sys.exit({exit_code})\n",
            encoding="utf-8",
        )
    source = INSTALLER.read_text(encoding="utf-8")
    section = source.split("# --- Fetch solution snapshot for local file checks ---", 1)[1]
    section = section.split("# End saved-target configuration.", 1)[0]
    python = sys.executable if python_exists else workspace / "missing-python.exe"
    harness = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    {_ps_string(INSTALLER)}, [ref]$null, [ref]$null)
foreach ($name in @('Invoke-Native', 'Start-Spinner', 'Stop-Spinner',
                     'Write-Step', 'Write-Ok', 'Write-Warn2')) {{
    $definition = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }}, $true)
    if (-not $definition) {{ throw "Missing installer helper: $name" }}
    . ([scriptblock]::Create($definition.Extent.Text))
}}
$workspace = {_ps_string(workspace)}
$pyCmd = {_ps_string(python)}
$pyBaseArgs = @()
$botId = {_ps_string('mock-agent' if agent_selected else '')}
$envUrl = 'https://orgmocktenant.crm.dynamics.com'
$agentName = 'Mock ESS Agent'
$schemaName = 'mock_agent'
$isManaged = $true
$isDaTarget = ${str(da_target).lower()}
$originalLocation = (Get-Location).Path
$caught = $null
$reachedFlightCheck = $false
try {{
    . ([scriptblock]::Create({_ps_string(section)}))
    $reachedFlightCheck = $true
}} catch {{
    $caught = $_.FullyQualifiedErrorId
}}
$state = @{{
    reachedFlightCheck = $reachedFlightCheck
    caught = $caught
    fetchExit = $fetchExit
    preference = "$ErrorActionPreference"
    spinnerStopped = $null -eq $script:spinnerSW
    locationRestored = (Get-Location).Path -eq $originalLocation
    powershellMajor = $PSVersionTable.PSVersion.Major
}}
Write-Output ("`nSTATE:" + ($state | ConvertTo-Json -Compress))
"""
    encoded = base64.b64encode(harness.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    state_line = next(line for line in result.stdout.splitlines() if line.startswith("STATE:"))
    state = json.loads(state_line.removeprefix("STATE:"))
    args_path = workspace / "fetch-args.json"
    state["fetchArgs"] = json.loads(args_path.read_text(encoding="utf-8")) if args_path.exists() else []
    return result.stdout, state


@pytest.mark.parametrize("exit_code", [0, 7], ids=["success", "failure"])
@pytest.mark.parametrize("stderr", [False, True], ids=["stdout-only", "stderr"])
def test_fetch_uses_exit_status_and_continues_to_flightcheck(
    powershell: str, tmp_path: Path, exit_code: int, stderr: bool
) -> None:
    output, state = _run_fetch(powershell, tmp_path, exit_code=exit_code, stderr=stderr)

    assert state["caught"] is None
    assert state["reachedFlightCheck"] is True
    assert state["fetchExit"] == exit_code
    assert state["preference"] == "Stop"
    assert state["spinnerStopped"] is True
    assert state["locationRestored"] is True
    assert "--refresh" in state["fetchArgs"]
    assert state["fetchArgs"][state["fetchArgs"].index("--bot-id") + 1] == "mock-agent"
    assert "--url" not in state["fetchArgs"]
    if exit_code == 0:
        assert "Agent solution fetched and extracted" in output
        assert "Local file checks may be skipped" not in output
    else:
        assert "Agent solution fetched and extracted" not in output
        assert "Local file checks may be skipped" in output
        assert "synthetic fetch stdout" in output
        if stderr:
            assert "synthetic fetch diagnostic" in output
            assert "synthetic diagnostic detail" in output


@pytest.mark.parametrize(
    ("agent_selected", "script_exists", "message"),
    [
        (False, True, "No agent selected - skipping solution fetch"),
        (True, False, "fetch_and_setup.py not found"),
    ],
)
def test_unavailable_snapshot_is_explicit_and_does_not_block_flightcheck(
    powershell: str, tmp_path: Path, agent_selected: bool, script_exists: bool, message: str
) -> None:
    output, state = _run_fetch(
        powershell, tmp_path, agent_selected=agent_selected, script_exists=script_exists
    )

    assert message in output
    assert "Agent solution fetched and extracted" not in output
    assert state["reachedFlightCheck"] is True
    assert state["preference"] == "Stop"
    assert state["locationRestored"] is True


def test_python_launch_error_restores_state_without_claiming_success(
    powershell: str, tmp_path: Path
) -> None:
    output, state = _run_fetch(powershell, tmp_path, python_exists=False)

    assert "CommandNotFoundException" in state["caught"]
    assert state["reachedFlightCheck"] is False
    assert "Agent solution fetched and extracted" not in output
    assert state["preference"] == "Stop"
    assert state["spinnerStopped"] is True
    assert state["locationRestored"] is True


def test_saved_da_target_never_fetches_a_dataverse_snapshot(powershell, tmp_path):
    output, state = _run_fetch(powershell, tmp_path, da_target=True)
    assert state["caught"] is None
    assert state["fetchArgs"] == []
    assert state["reachedFlightCheck"] is True
    assert "DA target: skipping the Dataverse snapshot fetch" in output


def test_installer_fetch_arguments_resolve_saved_environment(
    powershell: str, tmp_path: Path,
) -> None:
    _, state = _run_fetch(powershell, tmp_path)
    parser = argparse.ArgumentParser()
    for flag in ("url", "environment-id", "bot-id", "name", "schema"):
        parser.add_argument("--" + flag)
    parser.add_argument("--managed", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(state["fetchArgs"])
    config = {
        "dataverseEndpoint": "https://selected.crm.dynamics.com",
        "environmentId": "selected-environment",
        "agent": {
            "botId": "mock-agent",
            "name": "Mock ESS Agent",
            "schemaName": "mock_agent",
            "isManaged": True,
        },
    }

    target = fetch_and_setup._resolve_refresh_target(args, config)

    assert target == (
        "https://selected.crm.dynamics.com", "selected-environment",
        "mock-agent", "Mock ESS Agent", "mock_agent", True,
    )
