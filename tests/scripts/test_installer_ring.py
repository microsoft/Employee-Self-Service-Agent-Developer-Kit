# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Execute installer configuration against local discovery subprocess fixtures."""

from __future__ import annotations

import base64
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "setup" / "Install-EssAdk.ps1"


def _quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@pytest.fixture(params=["powershell", "pwsh", "bash"])
def shell(request):
    executable = shutil.which(request.param)
    if not executable and request.param == "bash":
        git_bash = Path(os.environ.get("ProgramFiles", "")) / "Git" / "bin" / "bash.exe"
        if git_bash.is_file():
            executable = str(git_bash)
    if not executable:
        pytest.skip(f"{request.param} is not installed")
    return executable


def _configure(shell, tmp_path, *, saved=None, ring=None, answers=(), fail=False, fail_agent=False):
    workspace = tmp_path / "maker's workspace"
    scripts = workspace / "scripts"
    scripts.mkdir(parents=True)
    config_path = workspace / ".local" / "config.json"
    config_path.parent.mkdir()
    if saved is not None:
        config_path.write_text(json.dumps(saved), encoding="utf-8")
    original = config_path.read_bytes() if config_path.exists() else None
    calls_path = workspace / "calls.jsonl"
    (scripts / "discover.py").write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "with Path('calls.jsonl').open('a') as f:\n"
        "    f.write(json.dumps(args) + '\\n')\n"
        f"fail = {fail!r}\n"
        "if fail:\n"
        "    print('synthetic discovery failure', file=sys.stderr)\n"
        "    sys.exit(7)\n"
        f"if {fail_agent!r} and '--url' in args:\n"
        "    print('synthetic agent discovery failure', file=sys.stderr)\n"
        "    sys.exit(7)\n"
        "if '--list-environments' in args:\n"
        "    ring = args[args.index('--ring') + 1] if '--ring' in args else 'prod'\n"
        "    envs = [{'id': 'env-' + ring, 'displayName': ring + ' target',\n"
        "             'instanceUrl': 'https://' + ring + '.crm.dynamics.com'},\n"
        "            {'id': 'other-env', 'displayName': 'Other environment',\n"
        "             'instanceUrl': 'https://other.crm.dynamics.com'}]\n"
        "    print('ENVIRONMENT_LIST_JSON:' + json.dumps(envs))\n"
        "    if '--select' in args:\n"
        "        envs[0]['id'] = 'different-environment'\n"
        "        print('SELECTED_ENV_JSON:' + json.dumps(envs[0]))\n"
        "else:\n"
        "    agents = [{'botid': 'selected-bot', 'name': 'Selected agent',\n"
        "               'schemaname': 'selected', 'ismanaged': True},\n"
        "              {'botid': 'other-bot', 'name': 'Other agent',\n"
        "               'schemaname': 'other', 'ismanaged': False}]\n"
        "    print('AGENT_DISCOVERY_JSON:' + json.dumps(agents))\n"
        "    if '--select' in args:\n"
        "        agents[0]['botid'] = 'different-bot'\n"
        "        print('SELECTED_AGENT_JSON:' + json.dumps(agents[0]))\n",
        encoding="utf-8",
    )
    harness = f"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    {_quote(INSTALLER)}, [ref]$null, [ref]$null)
foreach ($name in @('Invoke-Native', 'Write-Ok', 'Write-Warn2', 'Get-FlightCheckConfigRing')) {{
    $definition = $ast.Find({{
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq $name
    }}, $true)
    if ($definition) {{ . ([scriptblock]::Create($definition.Extent.Text)) }}
}}
function Resolve-Python {{ {_quote(sys.executable)} }}
$script:answers = New-Object 'System.Collections.Generic.Queue[string]'
foreach ($answer in (ConvertFrom-Json {_quote(json.dumps(list(answers)))})) {{
    $script:answers.Enqueue([string]$answer)
}}
function Read-Host {{
    param([string]$Prompt)
    Write-Host "PROMPT:$Prompt"
    if ($script:answers.Count -eq 0) {{ throw 'Unexpected prompt' }}
    $script:answers.Dequeue()
}}
$workspace = {_quote(workspace)}
$Ring = {_quote(ring if ring is not None else 'prod')}
$ringExplicit = ${str(ring is not None).lower()}
$caught = $null
$source = [IO.File]::ReadAllText({_quote(INSTALLER)})
$section = $source.Split(@("Write-Step 'Configuring FlightCheck environment'"), [StringSplitOptions]::None)[1]
$section = $section.Split(@('# --- Fetch solution snapshot for local file checks ---'), [StringSplitOptions]::None)[0]
try {{ . ([scriptblock]::Create($section)) }}
catch {{ $caught = $_.Exception.Message }}
Write-Output ('STATE:' + (@{{ring=$Ring; caught=$caught}} | ConvertTo-Json -Compress))
"""
    if Path(shell).stem == "bash":
        source = (ROOT / "setup" / "install-ess-adk.sh").read_text(encoding="utf-8")
        section = source.split('    LOCAL_DIR=".local"', 1)[1]
        section = section.split("# --- Fetch solution snapshot for local file checks ---", 1)[0]
        script_path = tmp_path / "configuration.sh"
        python_command = shlex.quote(Path(sys.executable).as_posix())
        if os.name == "nt":
            # Windows Python emits CRLF; macOS Python emits LF.
            python_setup = (
                f"fixture_python() {{ {python_command} \"$@\" | tr -d '\\r'; }}\n"
                "FLIGHTCHECK_PYTHON=fixture_python\n"
            )
        else:
            python_setup = f"FLIGHTCHECK_PYTHON={python_command}\n"
        script_path.write_text(
            "set -euo pipefail\n"
            "ok() { echo \"$*\"; }\nwarn() { echo \"$*\"; }\n"
            "err() { echo \"$*\" >&2; }\nstep() { echo \"$*\"; }\n"
            + python_setup +
            f"RING={shlex.quote(ring if ring is not None else 'prod')}\n"
            f"RING_EXPLICIT={'x' if ring is not None else ''}\n"
            'LOCAL_DIR=".local"\n' + section +
            "\nprintf 'STATE:{\"ring\":\"%s\",\"caught\":null}\\n' \"$RING\"\n",
            encoding="utf-8",
        )
        result = subprocess.run(
            [shell, str(script_path)], cwd=workspace,
            input="".join(answer + "\n" for answer in answers).encode("utf-8"),
            capture_output=True, timeout=30, check=False,
        )
        result.stdout = result.stdout.decode("utf-8")
        result.stderr = result.stderr.decode("utf-8")
        if result.returncode:
            state = {"caught": result.stderr + result.stdout}
        else:
            state = json.loads(next(
                line.removeprefix("STATE:")
                for line in result.stdout.splitlines() if line.startswith("STATE:")
            ))
    else:
        encoded = base64.b64encode(harness.encode("utf-16-le")).decode("ascii")
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        state = json.loads(next(
            line.removeprefix("STATE:")
            for line in result.stdout.splitlines() if line.startswith("STATE:")
        ))
    state["conflict_prompt"] = "differs from saved ring" in result.stdout
    config_bytes = config_path.read_bytes() if config_path.exists() else None
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
    return state, json.loads(config_bytes) if config_bytes else None, calls, original == config_bytes


def _saved(ring):
    return {
        "ring": ring,
        "dataverseEndpoint": f"https://saved-{ring}.crm.dynamics.com",
        "agent": {"botId": "saved-bot", "name": "Saved"},
    }


@pytest.mark.parametrize("ring", ["prod", "preprod", "test"])
def test_fresh_setup_uses_requested_ring_and_exact_displayed_subject(shell, tmp_path, ring):
    state, config, calls, _ = _configure(shell, tmp_path, ring=ring, answers=["1", "1"])

    assert state["caught"] is None
    assert config["ring"] == ring
    assert config["environmentId"] == f"env-{ring}"
    assert config["dataverseEndpoint"] == f"https://{ring}.crm.dynamics.com"
    assert config["agent"]["botId"] == "selected-bot"
    assert len(calls) == 2
    assert calls[0] == ["--list-environments", "--ring", ring]


@pytest.mark.parametrize("explicit", [None, "test"])
def test_retained_ring_is_used_without_discovery(shell, tmp_path, explicit):
    state, config, calls, _ = _configure(
        shell, tmp_path, saved=_saved("test"), ring=explicit, answers=["n"],
    )

    assert state["caught"] is None
    assert state["ring"] == config["ring"] == "test"
    assert config["agent"]["botId"] == "saved-bot"
    assert calls == []


@pytest.mark.parametrize("switch", [True, False])
def test_conflicting_ring_asks_to_switch_or_keep(shell, tmp_path, switch):
    state, config, calls, _ = _configure(
        shell, tmp_path, saved=_saved("prod"), ring="test",
        answers=["y", "1", "1"] if switch else ["n"],
    )

    assert state["caught"] is None
    assert state["conflict_prompt"]
    assert state["ring"] == config["ring"] == ("test" if switch else "prod")
    assert config["agent"]["botId"] == ("selected-bot" if switch else "saved-bot")
    assert len(calls) == (2 if switch else 0)


def test_failed_reconfiguration_preserves_previous_config(shell, tmp_path):
    state, _, _, unchanged = _configure(
        shell, tmp_path, saved=_saved("prod"), ring="test", answers=["y"], fail=True,
    )

    assert "Environment listing failed" in state["caught"]
    assert unchanged


@pytest.mark.parametrize("selection", ["abc", "0", "3", "999999999999999999999"])
def test_invalid_agent_selection_fails_without_replacing_target(shell, tmp_path, selection):
    state, _, _, unchanged = _configure(
        shell, tmp_path, saved=_saved("prod"), answers=["y", "1", selection],
    )

    assert state["caught"] is not None
    assert unchanged


def test_empty_agent_choice_explicitly_selects_environment_only(shell, tmp_path):
    state, config, calls, _ = _configure(shell, tmp_path, answers=["1", ""])

    assert state["caught"] is None
    assert config["agent"]["botId"] == ""
    assert config["agents"] == []
    assert len(calls) == 2


def test_selection_after_first_row_uses_exact_displayed_subject(shell, tmp_path):
    state, config, calls, _ = _configure(shell, tmp_path, answers=["2", "2"])

    assert state["caught"] is None
    assert config["environmentId"] == "other-env"
    assert config["dataverseEndpoint"] == "https://other.crm.dynamics.com"
    assert config["agent"]["botId"] == "other-bot"
    assert config["agent"]["isManaged"] is False
    assert len(calls) == 2


@pytest.mark.parametrize("continue_without_agent", [True, False])
def test_agent_discovery_failure_requires_explicit_environment_only_choice(
    shell, tmp_path, continue_without_agent,
):
    state, config, _, unchanged = _configure(
        shell, tmp_path, saved=_saved("prod"), fail_agent=True,
        answers=["y", "1", "y" if continue_without_agent else "n"],
    )

    if continue_without_agent:
        assert state["caught"] is None
        assert config["agent"]["botId"] == ""
    else:
        assert "Agent discovery failed" in state["caught"]
        assert unchanged


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        ({"powerPlatformApiEndpoint": "https://abc.api.test.powerplatform.com"}, "test"),
        ({"ring": " TEST "}, "test"),
        ({"ring": "unknown"}, None),
        ({"ring": "prod", "powerPlatformApiEndpoint": "https://abc.api.test.powerplatform.com"}, None),
        ({}, None),
    ],
)
def test_saved_ring_evidence_is_not_silently_relabelled(shell, tmp_path, saved, expected):
    saved.update(dataverseEndpoint="https://saved.crm.dynamics.com", agent={"botId": "saved"})
    state, config, calls, unchanged = _configure(shell, tmp_path, saved=saved, answers=["n"])

    assert calls == []
    if expected is None:
        assert state["caught"] is not None
        assert unchanged
    else:
        assert state["caught"] is None
        assert state["ring"] == config["ring"] == expected


@pytest.mark.parametrize("ring", [None, "test"])
def test_bootstrap_preserves_whether_ring_was_explicit(shell, tmp_path, ring):
    if Path(shell).stem == "bash":
        pytest.skip("PowerShell bootstrap contract")
    installer = (
        "param($Branch, [switch]$FlightCheckOnly, $Ring = 'prod', $InstallRoot)\n"
        "Write-Output ('ARGS:' + (@{explicit=$PSBoundParameters.ContainsKey('Ring'); "
        "ring=$Ring} | ConvertTo-Json -Compress))"
    )
    invocation = f"-Ring {_quote(ring)}" if ring is not None else ""
    harness = f"""
$ErrorActionPreference = 'Stop'
$env:TEMP = {_quote(tmp_path)}
function Invoke-WebRequest {{
    param($Uri, $OutFile, [switch]$UseBasicParsing, $TimeoutSec)
    [IO.File]::WriteAllText($OutFile, {_quote(installer)})
}}
$bootstrap = [IO.File]::ReadAllText({_quote(ROOT / 'setup' / 'bootstrap-flightcheck.ps1')})
& ([scriptblock]::Create($bootstrap)) {invocation}
"""
    encoded = base64.b64encode(harness.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    args = json.loads(next(
        line.removeprefix("ARGS:")
        for line in result.stdout.splitlines() if line.startswith("ARGS:")
    ))
    assert args == {"explicit": ring is not None, "ring": ring if ring is not None else "prod"}
