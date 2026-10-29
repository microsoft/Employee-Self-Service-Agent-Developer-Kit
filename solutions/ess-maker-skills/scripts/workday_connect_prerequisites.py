# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only local compatibility and connection-access probes for Connect."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping

import requests

from agentbuilder import AgentBuilderError
from agentbuilder_object_model import (
    ObjectModelConverterError,
    validate_object_model_runtime,
)
from install_workday_da_extension import PacCliError, resolve_pac_executable
from workday_connect_agent import (
    WorkdayConnectAgentError,
    verify_local_runtime_workspace,
)
from workday_connect_auth import WorkdayConnectIdentityError
from workday_connect_runtime import (
    AUTHORIZATION_SCRIPT,
    WorkdayConnectRuntimeError,
    configured_connection_api_version,
    _api_connections,
    _pac_upgrade_guidance,
    _powershell_literal,
)


class PrerequisiteProbeError(RuntimeError):
    """Raised when a bounded local compatibility probe fails."""


def _result(
    check_id: str,
    name: str,
    status: str,
    detail: str,
    impact: str,
    steps: list[str],
    *,
    kind: str = "local",
    commands: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "name": name,
        "status": status,
        "detail": detail,
        "impact": impact,
        "remediation": {
            "kind": kind,
            "steps": steps,
            "commands": commands or [],
            "requiresApproval": (
                kind in {"local", "workspace"} and status in {"blocked", "warning"}
            ),
        },
    }


def _run(
    command: list[str],
    root: Path,
    runner: Callable[..., subprocess.CompletedProcess],
) -> str:
    try:
        completed = runner(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrerequisiteProbeError(
            f"Could not complete the local compatibility check ({type(exc).__name__})."
        ) from exc
    if completed.returncode != 0:
        raise PrerequisiteProbeError(
            (completed.stderr or completed.stdout or "The local check failed.")[:2000]
        )
    return completed.stdout or ""


def check_prerequisites(
    root: Path,
    state: Mapping[str, Any],
    *,
    package_installed: bool,
    pac_resolver: Callable[[], Path] = resolve_pac_executable,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[dict[str, Any]]:
    """Inspect prerequisites without installing, changing profiles, or writing."""
    root = root.resolve()
    scripts = Path(__file__).parent
    checks = []
    pac = None
    pac_version = ""
    try:
        pac = pac_resolver()
        help_text = _run([str(pac), "help"], root, runner)
        version = re.search(r"Version:\s*([\w.+-]+)", help_text, re.IGNORECASE)
        pac_version = version.group(1) if version else "not reported"
        pac_detail = f"PAC: {pac}; version: {pac_version}."
    except (PacCliError, PrerequisiteProbeError) as exc:
        pac_detail = str(exc)

    for check_id, name, required, commands in (
        (
            "pac-install",
            "Workday package installation support",
            not package_installed,
            [
                (["application", "install"], ["--environment", "--application-name"]),
                (["auth", "create"], ["--cloud", "--environment", "--deviceCode"]),
                (["auth", "select"], ["--index"]),
                (["auth", "list"], []),
            ],
        ),
        (
            "pac-discovery",
            "PAC connection-discovery fallback",
            False,
            [
                (["connectivity", "list-connections"], ["--environment", "--json"]),
                (["auth", "create"], ["--cloud", "--environment", "--deviceCode"]),
                (["auth", "select"], ["--index"]),
                (["auth", "list"], []),
            ],
        ),
    ):
        try:
            if pac is None:
                raise PrerequisiteProbeError(pac_detail)
            for command, flags in commands:
                output = _run([str(pac), *command, "help"], root, runner)
                if any(flag not in output for flag in flags):
                    raise PrerequisiteProbeError(
                        f"PAC does not advertise required options for {' '.join(command)}."
                    )
        except PrerequisiteProbeError as exc:
            guidance = (
                _pac_upgrade_guidance(
                    pac, f"Version: {pac_version}",
                    command=" ".join(command), options=" ".join(flags),
                )
                if pac is not None
                else (
                    "Install or update the exact PAC installation shown using "
                    "https://learn.microsoft.com/power-platform/developer/cli/introduction. "
                    "The managed %LOCALAPPDATA%\\InternalTools\\pac\\pac.exe "
                    "takes precedence over other PAC copies on PATH."
                )
            )
            checks.append(_result(
                check_id, name, "blocked" if required else "warning",
                f"{pac_detail} {exc}",
                (
                    "The required Workday package cannot be installed."
                    if required
                    else "This optional PAC capability is unavailable."
                ),
                [guidance, "Recheck prerequisites after repairing this installation."],
            ))
        else:
            checks.append(_result(
                check_id, name, "verified", pac_detail,
                "Required command options are available.", [],
            ))

    shell = shutil.which("pwsh") or shutil.which("powershell")
    script = scripts / AUTHORIZATION_SCRIPT
    try:
        if not shell or not script.is_file():
            raise PrerequisiteProbeError(
                "PowerShell or the kit's flow-authorization script is missing."
            )
        invocation = (
            "$tokens=$null; $parseErrors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"{_powershell_literal(script)},[ref]$tokens,[ref]$parseErrors) | Out-Null; "
            "if ($parseErrors.Count) { $parseErrors | Out-String | Write-Error; exit 1 }"
        )
        _run([shell, "-NoProfile", "-NonInteractive", "-Command", invocation], root, runner)
    except PrerequisiteProbeError as exc:
        checks.append(_result(
            "powershell", "PowerShell authorization support", "blocked", str(exc),
            "Runtime flow authorization cannot run.",
            [
                "Install or repair PowerShell using https://aka.ms/powershell-release?tag=stable.",
                "If the checked-in script is missing or damaged, repair the kit installation.",
            ],
        ))
    else:
        checks.append(_result(
            "powershell", "PowerShell authorization support", "verified",
            f"{shell} can parse the authorization script without executing it.",
            "The local authorization-script syntax is supported.", [],
        ))

    try:
        if not shell:
            raise PrerequisiteProbeError("PowerShell cannot resolve the runtime Python.")
        probe = (
            "import sys,json; "
            f"sys.path.insert(0,{str(scripts)!r}); "
            "import auth,workday_connect_auth; "
            "print(json.dumps({'executable':sys.executable,"
            "'version':list(sys.version_info[:2])}))"
        )
        invocation = (
            "$ErrorActionPreference='Stop'; "
            "$python=(Get-Command python -CommandType Application -ErrorAction Stop "
            "| Select-Object -First 1).Source; "
            f"& $python -c {_powershell_literal(probe)}; exit $LASTEXITCODE"
        )
        output = _run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", invocation], root, runner,
        )
        identity = json.loads(output)
        if (
            not isinstance(identity, dict)
            or not isinstance(identity.get("executable"), str)
            or identity.get("version") != list(sys.version_info[:2])
            or Path(identity["executable"]).resolve() != Path(sys.executable).resolve()
        ):
            raise PrerequisiteProbeError(
                "PowerShell's python does not match the Python running Connect."
            )
    except (PrerequisiteProbeError, ValueError) as exc:
        checks.append(_result(
            "python", "Runtime Python and authentication dependencies", "blocked", str(exc),
            "The authorization script cannot reuse Connect's authentication environment.",
            [
                "Activate the same Python environment in this terminal and VS Code, then recheck.",
                "If authentication dependencies are missing, install the kit requirements after approval.",
            ],
            commands=[
                f"& {_powershell_literal(sys.executable)} -m pip install -r "
                f"{_powershell_literal(scripts / 'requirements.txt')}"
            ],
        ))
    else:
        checks.append(_result(
            "python", "Runtime Python and authentication dependencies", "verified",
            f"PowerShell resolves {sys.executable} and can import the authentication helpers.",
            "Runtime uses the same Python environment as Connect.", [],
        ))

    try:
        validate_object_model_runtime()
    except ObjectModelConverterError as exc:
        checks.append(_result(
            "object-model", "Agent serialization runtime", "blocked", str(exc),
            "Local Workday topic conversion and agent wiring cannot run.",
            [
                "Follow setup/README.md to repair Python.NET and a .NET 10 runtime "
                "matching Python's architecture, then restore the pinned Object Model packages.",
                "Recheck after the repair; restart the Python process if a runtime was already loaded.",
            ],
            commands=[
                f"& {_powershell_literal(sys.executable)} "
                f"{_powershell_literal(scripts / 'install_agentbuilder_object_model.py')}"
            ],
        ))
    else:
        checks.append(_result(
            "object-model", "Agent serialization runtime", "verified",
            "Python.NET, the matching .NET runtime and Microsoft assemblies loaded.",
            "The local topic-conversion runtime is available.", [],
        ))

    try:
        verify_local_runtime_workspace(root, state)
    except (WorkdayConnectAgentError, OSError, ValueError) as exc:
        checks.append(_result(
            "workspace", "Selected agent's local runtime components", "blocked", str(exc),
            "Runtime wiring cannot safely identify the selected agent's required topics.",
            [
                "Return to /setup for the same selected agent and repair or refresh its local workspace.",
                "Preserve local edits; confirm before replacing any customized files, then recheck.",
            ],
            kind="workspace",
        ))
    else:
        checks.append(_result(
            "workspace", "Selected agent's local runtime components", "verified",
            "Required topic mappings and YAML match the selected agent and environment.",
            "The local runtime components can be inspected safely.", [],
        ))

    if any(check["status"] == "blocked" for check in checks):
        checks.append(_result(
            "connection-api", "Power Platform connection API access", "pending",
            "Deferred until local prerequisites are repaired.",
            "No extra service sign-in was started while local checks are blocked.",
            ["Repair the local prerequisites, then recheck."], kind="service",
        ))
        return checks
    scope = state["scope"]
    maker = state["operators"]["powerPlatformMaker"]["username"]
    api_version = configured_connection_api_version(root)
    try:
        _api_connections({
            "environmentId": scope["environmentId"],
            "tenantId": scope["entraTenantId"],
            "ring": scope["ring"],
            "maker": maker,
            "agentBuilderApiVersion": api_version,
        })
    except WorkdayConnectIdentityError as exc:
        checks.append(_result(
            "connection-api", "Power Platform connection API access", "blocked", str(exc),
            "Discovery cannot continue under a different or unverifiable identity.",
            [
                f"Retry Microsoft sign-in using the maker selected in Step 1: {maker}.",
                "Keep the same selected environment and tenant; do not create another connection.",
            ],
            kind="sign-in",
        ))
    except (AgentBuilderError, requests.RequestException, OSError, ValueError,
            WorkdayConnectRuntimeError) as exc:
        fallback_available = next(
            check["status"] == "verified" for check in checks
            if check["id"] == "pac-discovery"
        )
        checks.append(_result(
            "connection-api", "Power Platform connection API access",
            "warning" if fallback_available else "blocked", str(exc),
            (
                "API access is unavailable; PAC supports fallback discovery, "
                "whose live access will be verified during Connections."
                if fallback_available
                else "Neither API discovery nor a compatible PAC fallback is available."
            ),
            [
                "Review the reported service, consent or network error with the environment administrator.",
                "Repair API access or the reported PAC fallback, then recheck. "
                "Do not reinstall Python to fix a service-permission error.",
            ],
            kind="service",
        ))
    else:
        checks.append(_result(
            "connection-api", "Power Platform connection API access", "verified",
            "Read-only connection inventory succeeded for the selected maker, tenant and ring.",
            "This verifies discovery access, not that Workday connections already exist.", [],
        ))
    return checks
