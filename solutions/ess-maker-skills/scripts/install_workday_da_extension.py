# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Install the Workday package required by the active ESS HR agent."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from flightcheck.checks.workday_da import (
    _DA_HR_WORKDAY_CHILD_SCHEMA,
    _MOS_WORKDAY_RUNTIME_SCHEMA,
)


WORKDAY_PACKAGES = {
    "runtime": {
        "applicationName": _MOS_WORKDAY_RUNTIME_SCHEMA,
        "schemaName": _MOS_WORKDAY_RUNTIME_SCHEMA,
    },
    "legacy-da": {
        "applicationName": "msdyn_EssDAHRWorkdayHCM",
        "schemaName": _DA_HR_WORKDAY_CHILD_SCHEMA,
    },
}
CLOUD_FOR_RING = {
    "preprod": "Preprod",
    "prod": "Public",
}
_PROFILE_RE = re.compile(r"^\s*\[(\d+)\]\s*(\*)?\s*(.*)$")


class PacCliError(RuntimeError):
    """Raised when PAC is unavailable or cannot complete an operation."""


def resolve_pac_executable(environ=os.environ) -> Path:
    """Prefer the shared managed PAC installation, then PAC on PATH."""
    local_app_data = environ.get("LOCALAPPDATA")
    if local_app_data:
        managed = Path(local_app_data) / "InternalTools" / "pac" / "pac.exe"
        if managed.is_file():
            return managed
    for candidate in ("pac", "pac.cmd", "pac.exe"):
        resolved = shutil.which(candidate)
        if resolved:
            return Path(resolved)
    raise PacCliError(
        "PAC CLI is not installed. Install Microsoft Power Platform CLI, "
        "then retry /connect workday."
    )


def _run(command, *, capture_output: bool, timeout: int):
    """Run one PAC command without invoking a shell."""
    try:
        return subprocess.run(
            [str(part) for part in command],
            capture_output=capture_output,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PacCliError(
            f"PAC command did not finish within {timeout // 60} minutes."
        ) from exc


def _parse_profiles(output: str) -> list[dict]:
    """Parse the profile index, active marker, and cloud from PAC output."""
    profiles = []
    for line in output.splitlines():
        match = _PROFILE_RE.match(line)
        if not match:
            continue
        remainder = match.group(3)
        cloud = next(
            (
                token
                for token in re.split(r"\s+", remainder)
                if token.casefold() in {"public", "preprod"}
            ),
            None,
        )
        if cloud:
            profiles.append(
                {
                    "index": match.group(1),
                    "active": bool(match.group(2)),
                    "cloud": cloud,
                }
            )
    return profiles


def ensure_pac_auth(
    pac_executable: Path,
    *,
    ring: str,
    environment_url: str,
    runner=_run,
) -> None:
    """Select or create a PAC profile for the requested Power Platform ring."""
    cloud = CLOUD_FOR_RING[ring]
    listed = runner(
        [pac_executable, "auth", "list"],
        capture_output=True,
        timeout=60,
    )
    profiles = (
        _parse_profiles(listed.stdout or "")
        if listed.returncode == 0
        else []
    )
    matching = [
        profile
        for profile in profiles
        if profile["cloud"].casefold() == cloud.casefold()
    ]
    active = [profile for profile in matching if profile["active"]]
    if len(active) == 1:
        return
    if len(matching) == 1:
        selected = runner(
            [
                pac_executable,
                "auth",
                "select",
                "--index",
                matching[0]["index"],
            ],
            capture_output=True,
            timeout=60,
        )
        if selected.returncode != 0:
            raise PacCliError("PAC could not select the required auth profile.")
        return
    if len(matching) > 1:
        raise PacCliError(
            f"Multiple PAC profiles exist for {cloud}. Select the correct "
            "profile with 'pac auth select', then retry /connect workday."
        )

    command = [
        pac_executable,
        "auth",
        "create",
        "--cloud",
        cloud,
    ]
    if ring == "preprod":
        command.extend(["--environment", environment_url])
    command.append("--deviceCode")
    authenticated = runner(
        command,
        capture_output=False,
        timeout=15 * 60,
    )
    if authenticated.returncode != 0:
        raise PacCliError(
            f"PAC authentication for {cloud} did not complete successfully."
        )


def install_workday_package(
    environment_url: str,
    package_flavor: str,
    *,
    ring: str,
    pac_resolver=resolve_pac_executable,
    runner=_run,
) -> str:
    """Install one Workday AppSource package through the supported PAC flow."""
    if package_flavor not in WORKDAY_PACKAGES:
        raise ValueError(f"Unsupported Workday package flavor: {package_flavor}")
    environment_url = environment_url.rstrip("/")
    if not environment_url.startswith("https://"):
        raise ValueError("The Power Platform environment URL must use HTTPS.")

    package = WORKDAY_PACKAGES[package_flavor]
    pac_executable = pac_resolver()
    ensure_pac_auth(
        pac_executable,
        ring=ring,
        environment_url=environment_url,
        runner=runner,
    )
    installed = runner(
        [
            pac_executable,
            "application",
            "install",
            "--environment",
            environment_url,
            "--application-name",
            package["applicationName"],
        ],
        capture_output=False,
        timeout=20 * 60,
    )
    if installed.returncode != 0:
        raise PacCliError(
            "PAC could not install the Workday package. Review the PAC output "
            "above, confirm environment access, and retry /connect workday."
        )
    return package["schemaName"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install the Workday package required by an ESS HR agent."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Dataverse environment URL",
    )
    parser.add_argument(
        "--vertical",
        required=True,
        choices=["hr"],
        help="ESS vertical (this release supports hr only)",
    )
    parser.add_argument(
        "--package-flavor",
        choices=sorted(WORKDAY_PACKAGES),
        default="runtime",
        help="Package required by the active ESS agent architecture.",
    )
    parser.add_argument(
        "--ring",
        choices=sorted(CLOUD_FOR_RING),
        default="prod",
        help="Power Platform ring captured during setup.",
    )
    args = parser.parse_args()

    package = WORKDAY_PACKAGES[args.package_flavor]
    base_result = {
        "environmentUrl": args.url.rstrip("/"),
        "vertical": args.vertical,
        "ring": args.ring,
        "packageFlavor": args.package_flavor,
        "schemaName": package["schemaName"],
        "applicationName": package["applicationName"],
    }
    try:
        schema_name = install_workday_package(
            args.url,
            args.package_flavor,
            ring=args.ring,
        )
    except (OSError, PacCliError, RuntimeError, ValueError) as error:
        print(
            "WORKDAY_PACKAGE_INSTALL_FAILED_JSON:"
            f"{json.dumps({**base_result, 'error': str(error)})}",
            flush=True,
        )
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)

    print(
        "INSTALLED_WORKDAY_DA_EXTENSION_JSON:"
        f"{json.dumps({**base_result, 'schemaName': schema_name})}"
    )


if __name__ == "__main__":
    main()
