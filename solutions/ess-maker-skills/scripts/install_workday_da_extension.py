# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Attempt an automated install of the DA Workday extension package.

Used by ``src/skills/setup/workday-da/install-extension.md`` (step DA1.1).
The DA Workday extension package has no entry in
``src/reference/ess-agent-installation/config.json`` — there is no confirmed
Marketplace catalog record for it. This script therefore does not assume the
package is installable through the Marketplace application API; it only
*tries* through
``PowerPlatformClient.list_environment_application_packages`` /
``install_application_package``), and reports a distinct, honest outcome —
``not-listed`` — when the tenant's Marketplace catalog does not return the
package at all. The calling skill step must treat ``not-listed`` as "hand off
to the manual AppSource install", never as a failure.

This mirrors the principle already stated for the CEA extension pack install
(``src/skills/setup/workday/install-workday-extension-pack.md``): never infer
success from an unsupported or incomplete API response.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from auth import discover_tenant
from flightcheck.checks.workday_da import (
    _DA_HR_WORKDAY_CHILD_SCHEMA,
)
from flightcheck.powerplatform_client import PowerPlatformClient
from flightcheck.pp_admin_client import PPAdminClient

WORKDAY_DA_CHILD_SCHEMAS = {"hr": _DA_HR_WORKDAY_CHILD_SCHEMA}
INSTALLED_STATES = {"Installed", "TemplateInstalled"}
IN_PROGRESS_STATES = {
    "InstallRequested",
    "Installing",
    "InstallScheduled",
    "InstallRetrying",
}
FAILED_STATES = {"InstallFailed"}
DEFAULT_TIMEOUT_SECONDS = 10 * 60


class InstallationTimeoutError(RuntimeError):
    """Raised when Power Platform does not finish installation in time."""

    def __init__(self, unique_name: str, timeout_seconds: int):
        self.unique_name = unique_name
        self.timeout_seconds = timeout_seconds
        super().__init__(
            "Application installation did not finish within "
            f"{timeout_seconds // 60} minutes."
        )


def _find_package(packages: list[dict], schema_name: str) -> dict | None:
    """Find the entitled application whose unique name matches the schema."""
    target = schema_name.casefold()
    for package in packages:
        names = (package.get("uniqueName"), package.get("applicationName"))
        if any(
            isinstance(name, str) and name.casefold() == target
            for name in names
        ):
            return package
    return None


def _error_message(response: dict, default: str) -> str:
    """Return a concise API error without dumping the full response."""
    error = (
        response.get("error")
        or response.get("errorDetails")
        or response.get("lastError")
        or {}
    )
    if isinstance(error, dict):
        message = error.get("message") or error.get("errorName")
        if message:
            return str(message)
    message = response.get("statusMessage")
    return str(message) if message else default


def _list_packages(
    client: PowerPlatformClient, environment_id: str
) -> list[dict]:
    packages = client.list_environment_application_packages(environment_id)
    if isinstance(packages, dict) and packages.get("_error"):
        raise RuntimeError(
            "Your account cannot read Marketplace applications for this "
            "environment. Use a Power Platform or Dynamics 365 administrator "
            "account."
        )
    return packages


def _wait_for_install(
    client: PowerPlatformClient,
    environment_id: str,
    unique_name: str,
    *,
    timeout_seconds: int,
    poll_interval_seconds: int,
    sleep,
    clock,
    status_callback,
) -> None:
    """Poll the application-package collection until installation completes."""
    started_at = clock()
    deadline = started_at + timeout_seconds
    poll_number = 0

    while True:
        now = clock()
        if now >= deadline:
            break
        poll_number += 1
        observed_status = "Unknown"
        package = _find_package(
            _list_packages(client, environment_id),
            unique_name,
        )
        if package:
            state = package.get("state")
            observed_status = state or "Unknown"
            if state in INSTALLED_STATES:
                return
            if state in FAILED_STATES:
                raise RuntimeError(
                    _error_message(
                        package,
                        f"Application installation ended with state {state}.",
                    )
                )
        status_callback(
            "Installation status "
            f"(poll {poll_number}, {int(now - started_at)}s elapsed): "
            f"{observed_status}"
        )
        sleep(poll_interval_seconds)

    raise InstallationTimeoutError(unique_name, timeout_seconds)


class ExtensionNotListedError(RuntimeError):
    """The DA Workday extension is not in this tenant's Marketplace catalog.

    Not a failure — the calling skill step must treat this as "automation is
    not available here" and fall back to the manual AppSource install, the
    same guidance ``WD-DA-PKG-001`` (``checks/workday_da.py``) already gives.
    """

    def __init__(self, unique_name: str):
        self.unique_name = unique_name
        super().__init__(
            f"'{unique_name}' was not found in this tenant's Marketplace "
            "application catalog."
        )


def install_workday_da_extension(
    env_url: str,
    vertical: str,
    *,
    pp_admin_client_factory=PPAdminClient,
    powerplatform_client_factory=PowerPlatformClient,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    poll_interval_seconds: int = 20,
    sleep=time.sleep,
    clock=time.monotonic,
    status_callback=lambda message: print(message, flush=True),
    installation_state_callback=lambda _status: None,
) -> str:
    """Try to install the DA Workday extension package for one vertical.

    Returns the installed child solution's schema name on success. Raises
    ``ExtensionNotListedError`` when the Marketplace catalog does not return
    the package at all (automation genuinely unavailable — not an error to
    surface as a failure). Raises ``InstallationTimeoutError`` or
    ``RuntimeError`` for other automation problems.
    """
    env_url = env_url.rstrip("/")
    if vertical != "hr":
        raise ValueError(
            "Workday integration with the ESS DA IT Agent is not supported "
            "in this release."
        )
    schema_name = WORKDAY_DA_CHILD_SCHEMAS[vertical]
    tenant_id = discover_tenant(env_url)

    pp_admin = pp_admin_client_factory(tenant_id)
    pp_admin.authenticate(include_flow=False)
    environment_id = pp_admin.find_environment_id_by_dataverse_url(env_url)
    if not environment_id:
        raise RuntimeError(
            "Could not resolve the selected environment's Power Platform ID."
        )

    client = powerplatform_client_factory(tenant_id)
    client.authenticate()
    package = _find_package(_list_packages(client, environment_id), schema_name)
    if not package:
        raise ExtensionNotListedError(schema_name)

    unique_name = package.get("uniqueName") or schema_name
    state = package.get("state")
    if state in INSTALLED_STATES:
        installation_state_callback("automatic-complete")
        return schema_name

    if state in IN_PROGRESS_STATES:
        installation_state_callback("installing")
    else:
        result = client.install_application_package(environment_id, unique_name)
        if result.get("_error"):
            raise RuntimeError(
                "Your account cannot install Marketplace applications in this "
                "environment. Use a Power Platform or Dynamics 365 "
                "administrator account."
            )
        last_state = result.get("lastOperation", {}).get("state")
        if last_state in INSTALLED_STATES:
            installation_state_callback("automatic-complete")
            return schema_name
        if last_state in FAILED_STATES:
            raise RuntimeError(
                _error_message(result.get("lastOperation", {}), "Installation failed.")
            )
        installation_state_callback("installing")

    _wait_for_install(
        client,
        environment_id,
        unique_name,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        sleep=sleep,
        clock=clock,
        status_callback=status_callback,
    )
    installation_state_callback("automatic-complete")
    return schema_name


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Attempt an automated install of the DA Workday extension "
            "package for one ESS vertical."
        )
    )
    parser.add_argument("--url", required=True, help="Dataverse environment URL")
    parser.add_argument(
        "--vertical",
        required=True,
        choices=sorted(WORKDAY_DA_CHILD_SCHEMAS),
        help="DA vertical (this release supports hr only)",
    )
    args = parser.parse_args()

    base_result = {
        "environmentUrl": args.url.rstrip("/"),
        "vertical": args.vertical,
        "schemaName": WORKDAY_DA_CHILD_SCHEMAS[args.vertical],
    }

    try:
        schema_name = install_workday_da_extension(args.url, args.vertical)
    except ExtensionNotListedError as error:
        print(
            "WORKDAY_DA_EXTENSION_NOT_LISTED_JSON:"
            f"{json.dumps(base_result)}",
            flush=True,
        )
        print(f"INFO: {error}", file=sys.stderr)
        sys.exit(3)
    except InstallationTimeoutError as error:
        result = {**base_result, "timeoutMinutes": error.timeout_seconds // 60}
        print(
            "WORKDAY_DA_EXTENSION_INSTALL_TIMEOUT_JSON:"
            f"{json.dumps(result)}",
            flush=True,
        )
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)

    result = {**base_result, "schemaName": schema_name}
    print(f"INSTALLED_WORKDAY_DA_EXTENSION_JSON:{json.dumps(result)}")


if __name__ == "__main__":
    main()
