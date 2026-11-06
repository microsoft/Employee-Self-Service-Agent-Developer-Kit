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
def shell(request, tmp_path_factory):
    if request.param == "bash":
        return _find_bash(tmp_path_factory.mktemp("bash probe's workspace"))
    executable = shutil.which(request.param)
    if not executable:
        pytest.skip(f"{request.param} is not installed")
    return executable


def _bash_candidates():
    if os.name == "nt":
        for root in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            directory = os.environ.get(root)
            if directory:
                suffix = ("Programs", "Git") if root == "LOCALAPPDATA" else ("Git",)
                candidate = Path(directory).joinpath(*suffix, "bin", "bash.exe")
                if candidate.is_file():
                    yield str(candidate)
    discovered = shutil.which("bash")
    if discovered:
        yield discovered


def _find_bash(probe_directory):
    # Probe the actual Windows-path/Python contract, not just `bash -c true`.
    probe = probe_directory / "probe.sh"
    python_command = shlex.quote(Path(sys.executable).as_posix())
    probe.write_text(
        f"{python_command} -c 'from pathlib import Path; "
        'print("BASH_PROBE_OK" if Path("probe.sh").is_file() else "WRONG_CWD")'
        "'\n",
        encoding="utf-8",
    )
    failures = []
    for executable in dict.fromkeys(_bash_candidates()):
        try:
            result = subprocess.run(
                [executable, str(probe)], cwd=probe_directory,
                capture_output=True, text=True, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            failures.append(f"{executable}: {type(exc).__name__}")
            continue
        if result.returncode == 0 and result.stdout.strip() == "BASH_PROBE_OK":
            return executable
        failures.append(f"{executable}: incompatible shell (exit {result.returncode})")
    pytest.skip(
        "No usable Bash for the installer tests. Install Git Bash on Windows "
        "or Bash on other platforms. " + "; ".join(failures)
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows shell discovery")
def test_bash_candidates_prefer_git_bash_over_wsl_launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("ProgramW6432", str(tmp_path))
    git_bash = tmp_path / "Git" / "bin" / "bash.exe"
    git_bash.parent.mkdir(parents=True)
    git_bash.touch()
    launcher = r"C:\Windows\System32\bash.exe"
    monkeypatch.setattr(shutil, "which", lambda name: launcher)

    candidates = list(_bash_candidates())

    assert candidates[0] == str(git_bash)
    assert candidates[-1] == launcher


@pytest.mark.parametrize("failure", ["exit", "timeout", "missing", "wrong-cwd"])
def test_bash_discovery_rejects_unusable_candidate(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(sys.modules[__name__], "_bash_candidates", lambda: iter([
        "unusable-bash", "usable-bash",
    ]))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["cwd"] == tmp_path
        assert kwargs["timeout"] == 10
        assert command[1] == str(tmp_path / "probe.sh")
        if command[0] == "unusable-bash":
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 10)
            if failure == "missing":
                raise FileNotFoundError("missing executable")
            return subprocess.CompletedProcess(
                command, 1 if failure == "exit" else 0, stdout="WRONG_CWD", stderr="",
            )
        return subprocess.CompletedProcess(command, 0, stdout="BASH_PROBE_OK\n", stderr="")

    monkeypatch.setattr(subprocess, "run", run)

    assert _find_bash(tmp_path) == "usable-bash"
    assert [command[0] for command in calls] == ["unusable-bash", "usable-bash"]


def test_bash_discovery_skips_with_actionable_prerequisite(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "_bash_candidates", lambda: iter([]))

    with pytest.raises(pytest.skip.Exception, match="Install Git Bash"):
        _find_bash(tmp_path)


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


@pytest.mark.parametrize("prompt", ["environment", "agent"])
@pytest.mark.parametrize("selection", [" 1 ", "\t1\t", "\r 1 \r"])
def test_numeric_selection_trims_surrounding_whitespace(shell, tmp_path, prompt, selection):
    answers = ["y", selection, "1"] if prompt == "environment" else ["y", "1", selection]

    state, config, calls, _ = _configure(
        shell, tmp_path, saved=_saved("test"), answers=answers,
    )

    assert state["caught"] is None
    assert config["ring"] == "test"
    assert config["environmentId"] == "env-test"
    assert config["agent"]["botId"] == "selected-bot"
    assert len(calls) == 2


@pytest.mark.parametrize("prompt", ["environment", "agent"])
@pytest.mark.parametrize("selection", ["1 0", "1\t0"])
def test_numeric_selection_rejects_internal_whitespace_without_replacing_target(
    shell, tmp_path, prompt, selection,
):
    answers = ["y", selection] if prompt == "environment" else ["y", "1", selection]

    state, _, calls, unchanged = _configure(
        shell, tmp_path, saved=_saved("test"), answers=answers,
    )

    assert state["caught"] is not None
    assert unchanged
    assert len(calls) == (1 if prompt == "environment" else 2)


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


@pytest.mark.parametrize("selection", ["", " \t ", "\r \t\r"])
def test_empty_agent_choice_explicitly_selects_environment_only(shell, tmp_path, selection):
    state, config, calls, _ = _configure(shell, tmp_path, answers=["1", selection])

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


@pytest.mark.parametrize(
    ("explicit", "confirmed"),
    [(None, "prod"), (None, "test"), ("prod", "prod"), ("test", "prod"), ("prod", " PREPROD ")],
)
def test_legacy_ring_confirmation_changes_only_ring(shell, tmp_path, explicit, confirmed):
    saved = _saved("prod")
    del saved["ring"]
    saved.update(
        environmentId="saved-environment",
        agents=[saved["agent"], {"botId": "another-bot", "name": "Another"}],
        activeAgent="saved",
        connections={"workday": {"enabled": False, "index": 0, "value": ""}},
        workdayTestEmployeeId="fixture-employee",
        referenceSource="local",
        environmentSku="Sandbox",
        customSetting={"nested": [False, 0, "", None]},
    )

    state, config, calls, _ = _configure(
        shell, tmp_path, saved=saved, ring=explicit, answers=["n", confirmed],
    )

    assert state["caught"] is None
    assert calls == []
    assert state["ring"] == confirmed.strip().lower()
    assert config == {**saved, "ring": confirmed.strip().lower()}


@pytest.mark.parametrize("answer", ["", "unknown", "y"])
def test_legacy_ring_invalid_confirmation_preserves_config(shell, tmp_path, answer):
    saved = _saved("prod")
    del saved["ring"]

    state, _, calls, unchanged = _configure(
        shell, tmp_path, saved=saved, answers=["n", answer],
    )

    assert "must be explicitly confirmed" in state["caught"]
    assert calls == []
    assert unchanged


@pytest.mark.parametrize(
    "invalid_settings",
    [
        {"powerPlatformApiEndpoint": "http://api.powerplatform.com"},
        {"powerPlatformApiEndpoint": "https://unrecognized.example"},
        {"powerPlatformApiEndpoint": "https://["},
        {"powerPlatformApiEndpoint": "https://api.test.powerplatform.com"},
        {"ring": "unsupported"},
    ],
)
@pytest.mark.parametrize("reconfigure", [True, False])
def test_invalid_saved_settings_allow_reconfiguration_but_not_retention(
    shell, tmp_path, invalid_settings, reconfigure,
):
    saved = {**_saved("prod"), **invalid_settings}
    state, config, calls, unchanged = _configure(
        shell, tmp_path, saved=saved,
        answers=["y", "2", "2"] if reconfigure else ["n"],
    )

    if reconfigure:
        assert state["caught"] is None
        assert config["ring"] == "prod"
        assert config["environmentId"] == "other-env"
        assert config["agent"]["botId"] == "other-bot"
        assert "powerPlatformApiEndpoint" not in config
        assert len(calls) == 2
    else:
        assert "Cannot keep a target" in state["caught"]
        assert calls == []
        assert unchanged


def test_invalid_saved_endpoint_and_failed_reconfiguration_preserve_config(shell, tmp_path):
    saved = {**_saved("prod"), "powerPlatformApiEndpoint": "https://["}

    state, _, _, unchanged = _configure(
        shell, tmp_path, saved=saved, answers=["y"], fail=True,
    )

    assert "Environment listing failed" in state["caught"]
    assert unchanged


@pytest.mark.parametrize("ring", [None, "test"])
def test_bootstrap_preserves_whether_ring_was_explicit(shell, tmp_path, ring):
    if Path(shell).stem == "bash":
        pytest.skip("PowerShell bootstrap contract")
    installer = (
        "param($Branch, [switch]$FlightCheckOnly, $Ring = 'prod', $InstallRoot, $FlightCheckScope)\n"
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
& ([scriptblock]::Create($bootstrap)) -FlightCheckScope workday {invocation}
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
