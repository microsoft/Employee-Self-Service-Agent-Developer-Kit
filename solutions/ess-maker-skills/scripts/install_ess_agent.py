# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Install an Employee Self-Service app with the Power Platform API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from auth import discover_tenant
from flightcheck.powerplatform_client import PowerPlatformClient
from flightcheck.pp_admin_client import PPAdminClient


CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "reference"
    / "solution-catalog.md"
)
CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "reference"
    / "ess-agent-installation" / "config.json"
)

EXPERIENCE_STATUS = {
    "da": "Active (DA bundle)",
    "cea": "Active (CEA bundle)",
}

VERTICAL_PACKAGE = {
    "hr": "Employee Self-Service HR",
    "it": "Employee Self-Service IT",
    "hub": "Employee Self-Service Hub",
}
VERTICAL_CONFIG_SECTION = {
    "hr": "esshr",
    "it": "essit",
    "hub": "esshub",
}


def load_parent_schemas(catalog_path: Path = CATALOG_PATH) -> dict[tuple[str, str], str]:
    """Read DA/CEA parent schema mappings from the solution catalog."""
    mappings: dict[tuple[str, str], str] = {}
    in_parents = False

    for line in catalog_path.read_text(encoding="utf-8").splitlines():
        if line == "## Parents":
            in_parents = True
            continue
        if in_parents and line.startswith("## "):
            break
        if not in_parents or not line.startswith("|"):
            continue

        columns = [column.strip() for column in line.strip("|").split("|")]
        if len(columns) != 5 or not columns[0].isdigit():
            continue

        package = columns[1]
        schema = columns[2].strip("`")
        status = columns[3]

        experience = next(
            (
                key for key, expected_status in EXPERIENCE_STATUS.items()
                if status == expected_status
            ),
            None,
        )
        vertical = next(
            (
                key for key, expected_package in VERTICAL_PACKAGE.items()
                if package == expected_package
            ),
            None,
        )
        if experience and vertical:
            mappings[(experience, vertical)] = schema

    expected = {
        (experience, vertical)
        for experience in EXPERIENCE_STATUS
        for vertical in VERTICAL_PACKAGE
    }
    missing = expected - mappings.keys()
    if missing:
        missing_labels = ", ".join(
            f"{experience.upper()}/{vertical.upper()}"
            for experience, vertical in sorted(missing)
        )
        raise ValueError(
            f"Solution catalog is missing parent schema mappings: {missing_labels}"
        )

    return mappings


def load_installation_config(
    config_path: Path = CONFIG_PATH,
    catalog_path: Path = CATALOG_PATH,
) -> dict:
    """Load installation metadata and reject ambiguous or stale mappings."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("schemaVersion") != 1:
        raise ValueError("Unsupported ESS installation config schemaVersion.")

    experiences = config.get("experiences")
    verticals = config.get("verticals")
    installations = config.get("installations")
    if not all(isinstance(value, dict) for value in (
        experiences,
        verticals,
        installations,
    )):
        raise ValueError(
            "ESS installation config must define experiences, verticals, "
            "and installations objects."
        )

    for dimension_name, dimension in (
        ("experiences", experiences),
        ("verticals", verticals),
    ):
        labels: set[str] = set()
        display_orders: set[int] = set()
        for key, metadata in dimension.items():
            label = metadata.get("label")
            display_order = metadata.get("displayOrder")
            if not isinstance(label, str) or not label.strip():
                raise ValueError(
                    f"{dimension_name}.{key} must define a non-empty label."
                )
            normalized_label = label.casefold()
            if normalized_label in labels:
                raise ValueError(
                    f"{dimension_name} contains duplicate label '{label}'."
                )
            labels.add(normalized_label)
            if not isinstance(display_order, int) or display_order in display_orders:
                raise ValueError(
                    f"{dimension_name}.{key} must define a unique integer "
                    "displayOrder."
                )
            display_orders.add(display_order)

    experience_short_labels: set[str] = set()
    for key, metadata in experiences.items():
        short_label = metadata.get("shortLabel")
        if not isinstance(short_label, str) or not short_label.strip():
            raise ValueError(
                f"experiences.{key} must define a non-empty shortLabel."
            )
        normalized_short_label = short_label.casefold()
        if normalized_short_label in experience_short_labels:
            raise ValueError(
                f"experiences contains duplicate shortLabel '{short_label}'."
            )
        experience_short_labels.add(normalized_short_label)

    expected_keys = {
        f"{experience_key}.{vertical_key}"
        for experience_key in experiences
        for vertical_key in verticals
    }
    if set(installations) != expected_keys:
        raise ValueError(
            "ESS installation config must define exactly one entry for every "
            "experience and vertical combination."
        )

    application_names: set[str] = set()
    config_keys: set[str] = set()
    catalog_schemas = load_parent_schemas(catalog_path)
    for installation_key, installation in installations.items():
        experience_key = installation.get("experienceKey")
        vertical_key = installation.get("verticalKey")
        config_key = installation.get("configKey")
        expected_key = f"{experience_key}.{vertical_key}"
        if installation_key != expected_key:
            raise ValueError(
                f"Installation key '{installation_key}' does not match its "
                f"experienceKey and verticalKey ('{expected_key}')."
            )
        expected_config_key = (
            f"{experience_key}.{VERTICAL_CONFIG_SECTION[vertical_key]}"
        )
        if config_key != expected_config_key:
            raise ValueError(
                f"Installation '{installation_key}' must use configKey "
                f"'{expected_config_key}'."
            )
        if config_key in config_keys:
            raise ValueError(
                f"Installation configKey '{config_key}' is assigned more "
                "than once."
            )
        config_keys.add(config_key)

        application = installation.get("marketplaceApplication") or {}
        solution = installation.get("solution") or {}
        catalog_match = installation.get("catalogMatch") or {}
        required_connection = installation.get("requiredConnection")
        unique_name = application.get("uniqueName")
        parent_unique_name = solution.get("parentUniqueName")
        if not unique_name or not parent_unique_name:
            raise ValueError(
                f"Installation '{installation_key}' is missing an application "
                "or parent solution unique name."
            )
        normalized_name = unique_name.casefold()
        if normalized_name in application_names:
            raise ValueError(
                f"Marketplace application unique name '{unique_name}' is "
                "assigned to more than one installation."
            )
        application_names.add(normalized_name)

        if catalog_match != {
            "parentPackage": VERTICAL_PACKAGE[vertical_key],
            "status": EXPERIENCE_STATUS[experience_key],
        }:
            raise ValueError(
                f"Installation '{installation_key}' has catalogMatch metadata "
                "that does not match its experience and vertical."
            )

        catalog_schema = catalog_schemas[(experience_key, vertical_key)]
        if unique_name != catalog_schema or parent_unique_name != catalog_schema:
            raise ValueError(
                f"Installation '{installation_key}' does not match the parent "
                f"schema '{catalog_schema}' in solution-catalog.md."
            )

        if vertical_key != "it":
            if required_connection is not None:
                raise ValueError(
                    f"Installation '{installation_key}' must not require a "
                    "parent connection."
                )
        else:
            required_fields = (
                "displayName",
                "connectorApiName",
                "referenceLogicalName",
                "runtimeSource",
                "creationGuidance",
            )
            if not isinstance(required_connection, dict) or any(
                not isinstance(required_connection.get(field), str)
                or not required_connection[field].strip()
                for field in required_fields
            ):
                raise ValueError(
                    f"Installation '{installation_key}' must define complete "
                    "requiredConnection metadata."
                )
            if required_connection["connectorApiName"] != "shared_alchemy":
                raise ValueError(
                    f"Installation '{installation_key}' must use the "
                    "shared_alchemy connector."
                )
            if required_connection["runtimeSource"] != "invoker":
                raise ValueError(
                    f"Installation '{installation_key}' must declare its "
                    "connection runtimeSource as 'invoker'."
                )
            expected_reference_prefix = parent_unique_name.casefold()
            if not required_connection["referenceLogicalName"].casefold().startswith(
                expected_reference_prefix
            ):
                raise ValueError(
                    f"Installation '{installation_key}' connection reference "
                    "does not match its parent solution."
                )

    return config


def build_installation_options(config: dict) -> list[dict]:
    """Build the single ordered ESS installation picker."""
    experiences = config["experiences"]
    verticals = config["verticals"]

    options = []
    for key, installation in config["installations"].items():
        experience_key = installation["experienceKey"]
        vertical_key = installation["verticalKey"]
        experience = experiences[experience_key]
        vertical = verticals[vertical_key]
        options.append({
            "key": key,
            "configKey": installation["configKey"],
            "experience": experience_key,
            "vertical": vertical_key,
            "label": (
                f"{experience['shortLabel']}: {vertical['label']}"
                f"{' (Recommended)' if experience.get('recommended') else ''}"
            ),
            "description": (
                f"{experience['description']} {vertical['description']}"
            ),
            "schemaName": installation["solution"]["parentUniqueName"],
            "requiredConnection": installation.get("requiredConnection"),
        })

    return sorted(
        options,
        key=lambda option: (
            experiences[option["experience"]]["displayOrder"],
            verticals[option["vertical"]]["displayOrder"],
        ),
    )


def find_installation_by_schema(config: dict, schema_name: str) -> dict | None:
    """Return the configured installation whose solution schema matches."""
    target = schema_name.casefold()
    for option in build_installation_options(config):
        if option["schemaName"].casefold() == target:
            return option
    return None


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


def _connector_api_name(value: str | None) -> str:
    return (value or "").rstrip("/").rsplit("/", 1)[-1].casefold()


def validate_required_connection(
    installation: dict,
    connections: list[dict],
    selected_connection_name: str | None = None,
) -> str | None:
    """Hard-gate installation on its required connected connector instance."""
    requirement = installation.get("requiredConnection")
    if requirement is None:
        return None

    matches = []
    expected_connector = requirement["connectorApiName"].casefold()
    for connection in connections:
        properties = connection.get("properties") or {}
        statuses = properties.get("statuses") or []
        status = (
            statuses[0].get("status")
            if statuses and isinstance(statuses[0], dict)
            else None
        )
        if (
            connection.get("name")
            and _connector_api_name(properties.get("apiId")) == expected_connector
            and str(status or "").casefold() == "connected"
        ):
            matches.append(connection["name"])

    if not matches:
        raise RuntimeError(
            f"This ESS agent requires an active {requirement['displayName']} "
            "connection. Create it in the selected environment before "
            "installation."
        )
    if selected_connection_name:
        if selected_connection_name not in matches:
            raise RuntimeError(
                "The selected required connection is not connected or does not "
                f"use {requirement['connectorApiName']}."
            )
        return selected_connection_name
    if len(matches) > 1:
        raise RuntimeError(
            "Multiple connected instances of the required connector exist. "
            "Select one during connection preflight before installation."
        )
    return matches[0]

def _find_package(packages: list[dict], schema_name: str) -> dict | None:
    """Find the entitled application whose unique name matches the catalog."""
    target = schema_name.casefold()
    for package in packages:
        names = (
            package.get("uniqueName"),
            package.get("applicationName"),
        )
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


def _list_packages(client: PowerPlatformClient, environment_id: str) -> list[dict]:
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
    """Poll the documented application-package collection until completion."""
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
            status_callback(
                "Installation status "
                f"(poll {poll_number}, {int(now - started_at)}s elapsed): "
                f"{observed_status}"
            )
            if state in INSTALLED_STATES:
                return
            if state in FAILED_STATES:
                raise RuntimeError(
                    _error_message(
                        package,
                        f"Application installation ended with state {state}.",
                    )
                )
        else:
            status_callback(
                "Installation status "
                f"(poll {poll_number}, {int(now - started_at)}s elapsed): "
                f"{observed_status}"
            )

        sleep(poll_interval_seconds)

    raise InstallationTimeoutError(unique_name, timeout_seconds)


def install_agent(
    env_url: str,
    experience: str,
    vertical: str,
    *,
    connection_name: str | None = None,
    config_path: Path = CONFIG_PATH,
    catalog_path: Path = CATALOG_PATH,
    pp_admin_client_factory=PPAdminClient,
    powerplatform_client_factory=PowerPlatformClient,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    poll_interval_seconds: int = 20,
    sleep=time.sleep,
    clock=time.monotonic,
    status_callback=lambda message: print(message, flush=True),
    installation_state_callback=lambda _status: None,
) -> str:
    """Authenticate and install the selected ESS application through REST APIs."""
    env_url = env_url.rstrip("/")
    config = load_installation_config(config_path, catalog_path)
    installation_key = f"{experience}.{vertical}"
    installation = config["installations"][installation_key]
    schema_name = installation["solution"]["parentUniqueName"]
    application_unique_name = installation["marketplaceApplication"]["uniqueName"]
    tenant_id = discover_tenant(env_url)

    pp_admin = pp_admin_client_factory(tenant_id)
    pp_admin.authenticate(include_flow=False)
    environment_id = pp_admin.find_environment_id_by_dataverse_url(env_url)
    if not environment_id:
        raise RuntimeError(
            "Could not resolve the selected environment's Power Platform ID."
        )

    if installation.get("requiredConnection") is not None:
        connections = pp_admin.get_connections(environment_id)
        if isinstance(connections, dict) and connections.get("_error"):
            raise RuntimeError(
                "Your account cannot read connections for this environment. "
                "Use a Power Platform administrator account, or ask an admin "
                "to confirm the required connection exists."
            )
        validate_required_connection(
            installation,
            connections,
            connection_name,
        )

    client = powerplatform_client_factory(tenant_id)
    client.authenticate()
    package = _find_package(
        _list_packages(client, environment_id),
        application_unique_name,
    )
    if not package:
        raise RuntimeError(
            f"The Marketplace application '{application_unique_name}' is not available "
            "for this tenant or environment."
        )

    unique_name = package.get("uniqueName") or application_unique_name
    state = package.get("state")
    if state in INSTALLED_STATES:
        installation_state_callback("automatic-complete")
        return schema_name

    if state in IN_PROGRESS_STATES:
        installation_state_callback("installing")
    else:
        result = client.install_application_package(
            environment_id,
            unique_name,
        )
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
        if last_state == "InstallFailed":
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
        description="Install an Employee Self-Service agent application"
    )
    parser.add_argument("--url", required=True, help="Dataverse environment URL")
    parser.add_argument(
        "--experience",
        required=True,
        choices=sorted(EXPERIENCE_STATUS),
        help="Agent experience: da or cea",
    )
    parser.add_argument(
        "--vertical",
        required=True,
        choices=sorted(VERTICAL_PACKAGE),
        help="Agent vertical: hr, it, or hub",
    )
    parser.add_argument(
        "--connection-name",
        help="Required connection selected by connection preflight",
    )
    parser.add_argument(
        "--state",
        default=".local/setup/config.json",
        help="Foundation setup state path",
    )
    args = parser.parse_args()

    from setup_state import persist_product_installation_status

    config = load_installation_config()
    product_id = config["installations"][
        f"{args.experience}.{args.vertical}"
    ]["configKey"]

    def persist_installation_state(status):
        mapped_status = {
            "installing": "installing",
            "automatic-complete": "installed",
        }[status]
        persist_product_installation_status(
            product_id,
            mapped_status,
            connection_name=args.connection_name,
            state_path=Path(args.state),
        )

    try:
        schema_name = install_agent(
            args.url,
            args.experience,
            args.vertical,
            connection_name=args.connection_name,
            installation_state_callback=persist_installation_state,
        )
    except InstallationTimeoutError as error:
        persist_product_installation_status(
            product_id,
            "manual-required",
            connection_name=args.connection_name,
            schema_name=error.unique_name,
            state_path=Path(args.state),
        )
        result = {
            "environmentUrl": args.url.rstrip("/"),
            "experience": args.experience,
            "vertical": args.vertical,
            "schemaName": error.unique_name,
            "timeoutMinutes": error.timeout_seconds // 60,
        }
        print(
            "ESS_AGENT_INSTALLATION_TIMEOUT_JSON:"
            f"{json.dumps(result)}",
            flush=True,
        )
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(2)
    except (OSError, RuntimeError, ValueError) as error:
        persist_product_installation_status(
            product_id,
            "failed",
            connection_name=args.connection_name,
            failure_cause=str(error),
            state_path=Path(args.state),
        )
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)

    result = {
        "environmentUrl": args.url.rstrip("/"),
        "experience": args.experience,
        "vertical": args.vertical,
        "productId": product_id,
        "schemaName": schema_name,
    }
    print(f"INSTALLED_ESS_AGENT_JSON:{json.dumps(result)}")


if __name__ == "__main__":
    main()
