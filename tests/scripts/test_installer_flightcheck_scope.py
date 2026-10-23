# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Execute installer preflight and launch snippets without installing anything.

The startup prefixes end before any I/O. The actual resolver functions are also
executed with controlled terminal status/input, so CI can cover prompts without
a desktop. Launch tests replace only Python/the downloaded installer, not the
argument construction. PowerShell prefixes receive a test-only InstallRoot so
Linux CI does not evaluate the Windows-only USERPROFILE default.
No network, credentials, or live installation is used.
"""

from __future__ import annotations

import ast
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "setup"
PS_INSTALLER = "Install-EssAdk.ps1"
PS_BOOTSTRAP = "bootstrap-flightcheck.ps1"
SH_INSTALLER = "install-ess-adk.sh"
SH_BOOTSTRAP = "bootstrap-flightcheck-mac.sh"
TEXT = {name: (SETUP / name).read_text(encoding="utf-8") for name in (
    PS_INSTALLER, PS_BOOTSTRAP, SH_INSTALLER, SH_BOOTSTRAP,
)}
CLI = ROOT / "solutions" / "ess-maker-skills" / "scripts" / "flightcheck" / "cli.py"
SCOPE_MAP = next(
    node.value for node in ast.parse(CLI.read_text(encoding="utf-8")).body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "SCOPE_MAP" for target in node.targets)
)
SCOPES = ["full", *(ast.literal_eval(key) for key in SCOPE_MAP.keys)]


@pytest.fixture(params=["powershell", "pwsh", "bash"])
def shell(request: pytest.FixtureRequest) -> tuple[str, str]:
    kind = request.param
    if kind == "bash" and os.name == "nt":
        executable = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        path = str(executable) if executable.is_file() else None
    else:
        path = shutil.which(kind)
    if path is None:
        pytest.skip(f"{kind} is not installed")
    return kind, path


def run(shell, script, *, env=None, input_text="", script_path=None):
    kind, executable = shell
    process_env = dict(os.environ)
    for name in ("CI", "TF_BUILD", "GITHUB_ACTIONS", "FLIGHTCHECK_SCOPE", "FLIGHTCHECK_ONLY"):
        process_env.pop(name, None)
    process_env.update({"ESS_ADK_TELEMETRY": "off", **(env or {})})
    if script_path is not None:
        script_path.write_text(script, encoding="utf-8" if kind == "bash" else "utf-8-sig")
        command = (
            [executable, str(script_path)] if kind == "bash" else
            [executable, "-NoProfile", "-NonInteractive", "-File", str(script_path)]
        )
    elif kind == "bash":
        command = [executable, "-c", script]
    else:
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        command = [executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    return subprocess.run(
        command, input=input_text, text=True, capture_output=True,
        env=process_env, cwd=ROOT, timeout=30,
    )


def names(shell):
    return (SH_INSTALLER, SH_BOOTSTRAP) if shell[0] == "bash" else (PS_INSTALLER, PS_BOOTSTRAP)


def resolver(name):
    pattern = r"(?ms)^resolve_flightcheck_scope\(\) \{.*?^\}" if name.endswith(".sh") else r"(?ms)^function Resolve-FlightCheckScope \{.*?^\}"
    match = re.search(pattern, TEXT[name])
    assert match
    return match.group()


def preflight(name):
    marker = {
        PS_INSTALLER: "# Back-compat: -SkipMakerProfile",
        PS_BOOTSTRAP: "# Derive SourceBaseUrl",
        SH_INSTALLER: 'RING="${RING:-prod}"',
        SH_BOOTSTRAP: 'TEMP_DIR="$(mktemp -d)"',
    }[name]
    assert marker in TEXT[name]
    return TEXT[name].split(marker, 1)[0]


def invoke_preflight(shell, name, *, argument=False, bootstrap_tail=False, extra_args="", da_target=False):
    prefix = preflight(name)
    if shell[0] == "bash":
        args = 'set -- --scope "$TEST_SCOPE" ' if argument else "set -- "
        args += extra_args + "\n"
        if bootstrap_tail:
            # Replace the downloaded script, preserving its real invocation.
            tail = TEXT[name][TEXT[name].index('export ESS_ADK_BRANCH="$BRANCH"'):]
            return args + prefix + '\nbash() { printf "FORWARDED:%s|%s|%s|%s\\n" "$FLIGHTCHECK_SCOPE" "$ESS_ADK_BRANCH" "$RING" "$*"; }\n' + 'TEMP_DIR=unused\n' + tail
        return args + prefix + '\nprintf "SELECTED:%s\\n" "${FLIGHTCHECK_SCOPE:-}"'
    args = "-InstallRoot $PWD "
    if name == PS_INSTALLER:
        args += "-FlightCheckOnly "
    if argument:
        args += "-FlightCheckScope $env:TEST_SCOPE "
    args += extra_args
    if bootstrap_tail:
        tail = TEXT[name][TEXT[name].index("$installerArgs ="):]
        if da_target:
            prefix += "\n$scriptBlock = { param($Branch, $FlightCheckOnly, $Ring='prod', $FlightCheckScope, $InstallRoot, $DaTargetUrl, $AgentSchemaName, $ValidationRealm) Write-Output ('DA:' + (@($DaTargetUrl,$AgentSchemaName,$ValidationRealm) | ConvertTo-Json -Compress)) }\n" + tail
        else:
            prefix += "\n$scriptBlock = { param($Branch, $FlightCheckOnly, $Ring='prod', $FlightCheckScope, $InstallRoot) Write-Output ('FORWARDED:' + (@{Branch=$Branch; Ring=$Ring; Scope=$FlightCheckScope; Only=$FlightCheckOnly} | ConvertTo-Json -Compress)) }\n" + tail
    else:
        prefix += "\nWrite-Output ('SELECTED:' + $FlightCheckScope)"
    return "$ErrorActionPreference='Stop'\n& {\n" + prefix + "\n} " + args


def test_allowlists_match_cli_and_bootstraps_match_installers():
    assert resolver(PS_INSTALLER) == resolver(PS_BOOTSTRAP)
    assert resolver(SH_INSTALLER) == resolver(SH_BOOTSTRAP)
    assert re.findall(r"(?m)^        (\w+) = '", resolver(PS_INSTALLER)) == SCOPES
    assert re.findall(r"(?m)^        '(\w+)\|", resolver(SH_INSTALLER)) == SCOPES
    for scope in SCOPES:
        assert f"| `{scope}` |" in (SETUP / "README.md").read_text(encoding="utf-8")


def test_every_existing_scope_is_executable(shell):
    for name in names(shell):
        if shell[0] == "bash":
            code = "set -eu\n" + resolver(name) + "\nfor scope in " + " ".join(SCOPES) + '; do FLIGHTCHECK_SCOPE="$scope"; resolve_flightcheck_scope false; echo "SELECTED:$FLIGHTCHECK_SCOPE"; done'
        else:
            values = ",".join(f"'{scope}'" for scope in SCOPES)
            code = "$ErrorActionPreference='Stop'\n" + resolver(name) + f"\nforeach ($scope in @({values})) {{ Write-Output ('SELECTED:' + (Resolve-FlightCheckScope -Scope $scope -Interactive $false)) }}"
        result = run(shell, code)
        assert result.returncode == 0, result.stderr
        assert re.findall(r"SELECTED:(\w+)", result.stdout) == SCOPES


@pytest.mark.parametrize("scope", ["workday", "Full", " workdayda "])
@pytest.mark.parametrize("argument", [False, True])
def test_startup_selects_argument_or_environment(shell, scope, argument):
    for name in names(shell):
        env = {"FLIGHTCHECK_ONLY": "true", "CI": "true"}
        env.update({"TEST_SCOPE": scope, "FLIGHTCHECK_SCOPE": "servicenow"} if argument else {"FLIGHTCHECK_SCOPE": scope})
        result = run(shell, invoke_preflight(shell, name, argument=argument), env=env)
        assert result.returncode == 0, result.stderr
        assert "SELECTED:" + scope.strip().lower() in result.stdout
        assert "Choose a FlightCheck scope" not in result.stdout


@pytest.mark.parametrize("scope", ["typo", "workday-da", "workday; echo injected", "0", ""])
def test_invalid_or_empty_scope_fails_before_installation(shell, scope):
    for name in names(shell):
        result = run(shell, invoke_preflight(shell, name, argument=True), env={
            "TEST_SCOPE": scope, "CI": "true", "FLIGHTCHECK_ONLY": "true",
        })
        assert result.returncode != 0
        assert "scope" in (result.stdout + result.stderr).lower()
        assert "SELECTED:" not in result.stdout


@pytest.mark.parametrize("ci", ["", "CI", "TF_BUILD", "GITHUB_ACTIONS"])
def test_unattended_missing_scope_exits_with_instructions(shell, ci):
    for name in names(shell):
        result = run(shell, invoke_preflight(shell, name), env={
            "FLIGHTCHECK_ONLY": "true", **({ci: "true"} if ci else {}),
        })
        assert result.returncode != 0
        assert "FLIGHTCHECK_SCOPE" in result.stdout + result.stderr
        assert "SELECTED:" not in result.stdout


@pytest.mark.parametrize("answer", ["workday", "full", "", None, "wrong", "   "])
def test_interactive_selection_empty_and_eof(shell, answer):
    for name in names(shell):
        if shell[0] == "bash":
            code = "set -eu\n" + resolver(name) + '\nresolve_flightcheck_scope true\necho "SELECTED:$FLIGHTCHECK_SCOPE"'
        else:
            read_host = "function Read-Host { return $env:TEST_ANSWER }"
            if answer is None:
                read_host = "function Read-Host { return $null }"
            code = "$ErrorActionPreference='Stop'\n" + resolver(name) + "\n" + read_host + "\nWrite-Output ('SELECTED:' + (Resolve-FlightCheckScope -Interactive $true))"
        result = run(shell, code, env={"TEST_ANSWER": answer or ""}, input_text="" if answer is None else answer + "\n")
        assert "Choose a FlightCheck scope (no default)" in result.stdout
        for scope in SCOPES:
            assert f"  {scope} - " in result.stdout
        if answer in ("workday", "full"):
            assert result.returncode == 0, result.stderr
            assert f"SELECTED:{answer}" in result.stdout
        else:
            assert result.returncode != 0
            assert "FLIGHTCHECK_SCOPE" in result.stdout + result.stderr
            assert "SELECTED:" not in result.stdout


@pytest.mark.parametrize("argument", [False, True])
def test_bootstrap_forwards_scope_and_preserves_mode_branch_ring(shell, argument):
    name = names(shell)[1]
    code = invoke_preflight(shell, name, argument=argument, bootstrap_tail=True)
    result = run(shell, code, env={
        "FLIGHTCHECK_SCOPE": "workday", "TEST_SCOPE": "full", "RING": "test",
    })
    assert result.returncode == 0, result.stderr
    scope = "full" if argument else "workday"
    if shell[0] == "bash":
        assert f"FORWARDED:{scope}|main|test|unused/install-ess-adk.sh --scope {scope}" in result.stdout
    else:
        forwarded = json.loads(re.search(r"FORWARDED:(\{.*\})", result.stdout).group(1))
        assert forwarded == {"Branch": "main", "Ring": "prod", "Scope": scope, "Only": True}


def test_bootstrap_explicit_branch_ring_and_scope_override_environment(shell):
    name = names(shell)[1]
    extra_args = "--branch pinned-ref --ring preprod" if shell[0] == "bash" else "-Branch pinned-ref -Ring preprod"
    result = run(shell, invoke_preflight(
        shell, name, argument=True, bootstrap_tail=True, extra_args=extra_args,
    ), env={"FLIGHTCHECK_SCOPE": "servicenow", "TEST_SCOPE": "workdayda", "RING": "test"})
    assert result.returncode == 0, result.stderr
    if shell[0] == "bash":
        assert "FORWARDED:workdayda|pinned-ref|preprod|unused/install-ess-adk.sh --scope workdayda" in result.stdout
    else:
        forwarded = json.loads(re.search(r"FORWARDED:(\{.*\})", result.stdout).group(1))
        assert forwarded == {"Branch": "pinned-ref", "Ring": "preprod", "Scope": "workdayda", "Only": True}


def test_scope_argument_requires_a_value(shell):
    option = "--scope" if shell[0] == "bash" else "-FlightCheckScope"
    for name in names(shell):
        result = run(shell, invoke_preflight(shell, name, extra_args=option),
                     env={"FLIGHTCHECK_ONLY": "true"})
        assert result.returncode != 0
        assert "scope" in (result.stdout + result.stderr).lower()
        assert "SELECTED:" not in result.stdout


def test_powershell_unavailable_prompt_fails_with_instructions(shell):
    if shell[0] == "bash":
        pytest.skip("Bash EOF is covered by the interactive input tests")
    for name in names(shell):
        code = (
            "$ErrorActionPreference='Stop'\n" + resolver(name)
            + "\nfunction Read-Host { throw 'Input unavailable' }"
            + "\nResolve-FlightCheckScope -Interactive $true"
        )
        result = run(shell, code)
        assert result.returncode != 0
        assert "FLIGHTCHECK_SCOPE" in result.stdout + result.stderr


@pytest.mark.parametrize("da_target", [False, True])
def test_launch_commands_preserve_scope_telemetry_ring_and_targeting(shell, da_target):
    name = names(shell)[0]
    native_args = ["--da-target-url", "https://copilotstudio.microsoft.com/target",
                   "--agent-schema-name", "gptagent_hr", "--validation-realm", "dev"] if da_target else []
    if shell[0] == "bash":
        line = next(line.strip() for line in TEXT[name].splitlines() if '"$FLIGHTCHECK_PYTHON" scripts/flightcheck/cli.py --scope' in line)
        array = "DA_TARGET_ARGS=(" + " ".join(native_args) + ")\n"
        code = 'set -eu\ncapture() { printf "<%s>" "$@"; }\nFLIGHTCHECK_PYTHON=capture\nFLIGHTCHECK_SCOPE=workday\nRING=preprod\n' + array + line
        result = run(shell, code)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "<scripts/flightcheck/cli.py><--scope><workday><--invocation-source><installer><--select-targets><always><--ring><preprod>" + "".join(f"<{value}>" for value in native_args)
    else:
        lines = [line.strip() for line in TEXT[name].splitlines() if re.match(r"\s*& (?:py|\$pythonExe).* scripts/flightcheck/cli.py --scope", line)]
        assert len(lines) == 3
        for line in lines:
            array = "$daTargetArgs=@(" + ",".join(f"'{value}'" for value in native_args) + ")\n"
            code = "function py { $args | ConvertTo-Json -Compress }\nfunction capture { $args | ConvertTo-Json -Compress }\n$pythonExe='capture'; $FlightCheckScope='workday'; $Ring='test'\n" + array + line
            result = run(shell, code)
            assert result.returncode == 0, result.stderr
            args = json.loads(result.stdout)
            assert args[args.index("scripts/flightcheck/cli.py"):] == [
                "scripts/flightcheck/cli.py", "--scope", "workday", "--invocation-source", "installer",
                "--select-targets", "always", "--ring", "test",
            ] + native_args
        assert "--scope $FlightCheckScope --select-targets always --ring $Ring" in TEXT[name]


def test_explicit_da_bootstrap_forwards_native_target_without_legacy_discovery(shell):
    url = "https://copilotstudio.microsoft.com/environments/00000000-0000-0000-0000-000000002222/copilots/00000000-0000-0000-0000-000000003333"
    extra = (
        f'--da-target-url "{url}" --agent-schema-name gptagent_hr --validation-realm dev'
        if shell[0] == "bash" else
        f'-DaTargetUrl "{url}" -AgentSchemaName gptagent_hr -ValidationRealm dev'
    )
    result = run(shell, invoke_preflight(
        shell, names(shell)[1], bootstrap_tail=True, extra_args=extra, da_target=True,
    ), env={"FLIGHTCHECK_SCOPE": "full", "RING": "prod"})
    assert result.returncode == 0, result.stdout + result.stderr
    if shell[0] == "bash":
        assert f"--da-target-url {url} --agent-schema-name gptagent_hr --validation-realm dev" in result.stdout
    else:
        assert json.loads(re.search(r"DA:(\[.*\])", result.stdout).group(1)) == [url, "gptagent_hr", "dev"]


def test_partial_da_onboarding_fails_before_installation(shell):
    extra = "--da-target-url https://copilotstudio.microsoft.com" if shell[0] == "bash" else "-DaTargetUrl https://copilotstudio.microsoft.com"
    for name in names(shell):
        result = run(shell, invoke_preflight(shell, name, extra_args=extra),
                     env={"FLIGHTCHECK_SCOPE": "full", "FLIGHTCHECK_ONLY": "true"})
        assert result.returncode != 0
        assert "onboarding requires" in result.stdout + result.stderr


def test_explicit_da_installer_branch_skips_config_and_snapshot_writes(shell, tmp_path):
    name = names(shell)[0]
    url = "https://copilotstudio.microsoft.com/environments/00000000-0000-0000-0000-000000002222/copilots/00000000-0000-0000-0000-000000003333"
    if shell[0] == "bash":
        branch = TEXT[name].split("    DA_TARGET_ARGS=()", 1)[1].split("    # --- Run FlightCheck ---", 1)[0]
        code = (
            f'set -eu\nDA_TARGET_URL="{url}"\nAGENT_SCHEMA_NAME=gptagent_hr\nVALIDATION_REALM=dev\n'
            'ok() { :; }\nDA_TARGET_ARGS=()\n' + branch
            + '\nprintf "<%s>" "${DA_TARGET_ARGS[@]}"'
        )
    else:
        branch = TEXT[name].split("    $daTargetArgs = @()", 1)[1].split("    # --- Run FlightCheck ---", 1)[0]
        code = (
            f"$ErrorActionPreference='Stop'\n$DaTargetUrl='{url}'; $AgentSchemaName='gptagent_hr'; $ValidationRealm='dev'\n"
            "function Write-Ok { }\n$daTargetArgs=@()\n" + branch
            + "\n$daTargetArgs | ConvertTo-Json -Compress"
        )
    result = run(shell, code, script_path=tmp_path / "native-branch.ps1")
    assert result.returncode == 0, result.stdout + result.stderr
    expected = ["--da-target-url", url, "--agent-schema-name", "gptagent_hr", "--validation-realm", "dev"]
    if shell[0] == "bash":
        assert result.stdout == "".join(f"<{value}>" for value in expected)
    else:
        assert json.loads(result.stdout) == expected


@pytest.mark.parametrize("da_target", [False, True])
def test_installers_reuse_selected_agent_da_routing_for_saved_config(tmp_path, da_target):
    config = {
        "activeAgent": "hr", "dataverseEndpoint": "https://example.crm.dynamics.com",
        "agents": [{"slug": "hr", "releaseLine": "da" if da_target else "ca"}],
        "agent": {"slug": "other", "releaseLine": "ca" if da_target else "da"},
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    for name in (PS_INSTALLER, SH_INSTALLER):
        snippet = re.search(r"import json,sys; sys.path.insert\(0,'scripts'\); from flightcheck.da_execution .*?'legacy'\)", TEXT[name]).group()
        result = subprocess.run(
            [sys.executable, "-c", snippet, str(path)], capture_output=True,
            text=True, cwd=ROOT / "solutions" / "ess-maker-skills", timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == ("da" if da_target else "legacy")


@pytest.mark.parametrize("exit_code", [0, 1, 2])
def test_windows_installer_cannot_hide_non_ready_da_full_exit(shell, exit_code):
    if shell[0] == "bash":
        pytest.skip("Bash directly propagates the CLI process exit")
    gate = re.search(
        r'(?ms)^    if \(\$isDaTarget -and \$FlightCheckScope.*?^    \}',
        TEXT[PS_INSTALLER],
    ).group()
    result = run(shell, f"$ErrorActionPreference='Stop'\n$isDaTarget=$true; $FlightCheckScope='full'; $flightCheckExit={exit_code}\n" + gate)
    assert (result.returncode == 0) is (exit_code == 0)
    if exit_code:
        assert "did not establish READY" in result.stdout + result.stderr


def test_non_flightcheck_mode_does_not_require_scope(shell):
    name = names(shell)[0]
    if shell[0] == "bash":
        code = preflight(name) + "\necho CONTINUED"
    else:
        code = "& {\n" + preflight(name) + "\nWrite-Output CONTINUED\n} -InstallRoot $PWD"
    result = run(shell, code, env={"FLIGHTCHECK_SCOPE": "not-a-scope"})
    assert result.returncode == 0, result.stderr
    assert "CONTINUED" in result.stdout
    assert "Choose a FlightCheck scope" not in result.stdout


@pytest.mark.parametrize("bootstrap_tail", [False, True])
def test_powershell_preflight_does_not_require_windows_userprofile(
    shell, monkeypatch, bootstrap_tail,
):
    if shell[0] == "bash":
        pytest.skip("Windows installer parameter defaults are PowerShell-specific")
    monkeypatch.delenv("USERPROFILE", raising=False)
    for name in (names(shell)[1:] if bootstrap_tail else names(shell)):
        result = run(
            shell, invoke_preflight(shell, name, bootstrap_tail=bootstrap_tail),
            env={"FLIGHTCHECK_SCOPE": "workday", "CI": "true"},
        )

        assert result.returncode == 0, result.stderr
        assert ("FORWARDED:" if bootstrap_tail else "SELECTED:workday") in result.stdout
