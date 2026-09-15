# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Inspect or export one known native Prod agent."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from agentbuilder import (
    DEFAULT_API_VERSION,
    DEV_REALM,
    PROD_REALM,
    REALM_NAMES,
    AgentBuilderClient,
    AgentBuilderError,
)
from setup_existing_da import (
    ExistingDASetupError,
    _client_from_args,
    _normalize_environment_id,
    _normalize_guid,
    resolve_da_target,
)


class AlmExportSetupError(RuntimeError):
    """Raised when a Prod source cannot be inspected or exported safely."""


def _matches_realm(value: Any, realm: int) -> bool:
    if type(value) is int:
        return value == realm
    return (
        isinstance(value, str)
        and value.casefold() == REALM_NAMES[realm].casefold()
    )


def _related_dev_agent_id(realms: dict[str, Any]) -> str | None:
    siblings = realms.get("siblingRealms")
    if siblings is None:
        return None
    if not isinstance(siblings, list):
        raise AlmExportSetupError(
            "Native realm discovery returned invalid sibling realms."
        )
    related: set[str] = set()
    for sibling in siblings:
        if not isinstance(sibling, dict):
            raise AlmExportSetupError(
                "Native realm discovery returned an invalid sibling."
            )
        if not _matches_realm(sibling.get("realm"), DEV_REALM):
            continue
        related.add(
            _normalize_guid(
                str(sibling.get("botId") or ""),
                "Related Dev agent ID",
            )
        )
    if len(related) > 1:
        raise AlmExportSetupError(
            "Native realm discovery returned multiple related Dev agents."
        )
    return next(iter(related), None)


def inspect_prod_source(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
) -> dict[str, Any]:
    """Return safe handoff facts after exact native Prod validation."""
    normalized_environment_id = _normalize_environment_id(environment_id)
    normalized_agent_id = _normalize_guid(agent_id, "Source agent ID")
    realms = client.get_realms(normalized_agent_id)
    if not _matches_realm(realms.get("routeRealm"), PROD_REALM):
        raise AlmExportSetupError(
            "The supplied source agent is not the native Prod realm."
        )
    configuration = client.get_realm_configuration(
        normalized_agent_id,
        PROD_REALM,
    )
    if not _matches_realm(configuration.get("realm"), PROD_REALM):
        raise AlmExportSetupError(
            "Native Prod configuration did not identify the Prod realm."
        )
    configured_agent_id = _normalize_guid(
        str(configuration.get("cdsBotId") or ""),
        "Configured Prod agent ID",
    )
    if configured_agent_id.casefold() != normalized_agent_id.casefold():
        raise AlmExportSetupError(
            "Native Prod configuration returned a different agent identity."
        )
    family_id = str(configuration.get("grsRepositoryId") or "").strip()
    if not family_id:
        raise AlmExportSetupError(
            "Native Prod configuration did not return an ALM-family identity."
        )
    return {
        "environmentId": normalized_environment_id,
        "tenantId": client.tenant_id,
        "host": client.host,
        "ring": client.ring,
        "apiVersion": client.api_version,
        "sourceAgentId": normalized_agent_id,
        "almFamilyId": family_id,
        "relatedDevAgentId": _related_dev_agent_id(realms),
    }


def export_prod_source(
    client: AgentBuilderClient,
    *,
    environment_id: str,
    agent_id: str,
    kit_root: Path,
) -> dict[str, Any]:
    """Validate and export once to a disposable package outside the kit."""
    source = inspect_prod_source(
        client,
        environment_id=environment_id,
        agent_id=agent_id,
    )
    handle, temporary = tempfile.mkstemp(
        prefix="ess-adk-prod-to-dev-",
        suffix=".zip",
    )
    os.close(handle)
    package_path = Path(temporary).resolve()
    exported = False
    try:
        resolved_kit_root = kit_root.resolve()
        if (
            package_path == resolved_kit_root
            or resolved_kit_root in package_path.parents
        ):
            raise AlmExportSetupError(
                "The operating system temporary package path is inside the kit."
            )
        client.export_package(source["sourceAgentId"], package_path)
        if package_path.stat().st_size == 0:
            raise AlmExportSetupError(
                "Native ALM export returned an empty package."
            )
        exported = True
    finally:
        if not exported:
            package_path.unlink(missing_ok=True)
    return {
        **source,
        "packagePath": str(package_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--source-url", required=True)
    common.add_argument("--tenant-id")
    common.add_argument("--select-account", action="store_true")
    common.add_argument("--api-version", default=DEFAULT_API_VERSION)
    common.add_argument("--kit-root", type=Path, default=Path.cwd())
    common.set_defaults(host=None)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect", parents=[common])
    commands.add_parser("export", parents=[common])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = resolve_da_target(
            target_url=args.source_url,
            environment_id=None,
            agent_id=None,
            ring=None,
            require_agent=True,
        )
        if source.get("source") != "copilot-studio-url":
            raise AlmExportSetupError(
                "The source must be a recognized Copilot Studio agent URL."
            )
        client = _client_from_args(
            args,
            source["environmentId"],
            source["ring"],
        )
        if args.command == "inspect":
            result = inspect_prod_source(
                client,
                environment_id=source["environmentId"],
                agent_id=source["agentId"],
            )
            marker = "DA_ALM_EXPORT_INSPECTION_JSON:"
        else:
            result = export_prod_source(
                client,
                environment_id=source["environmentId"],
                agent_id=source["agentId"],
                kit_root=args.kit_root,
            )
            marker = "DA_ALM_EXPORT_JSON:"
    except (
        AgentBuilderError,
        AlmExportSetupError,
        ExistingDASetupError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"{marker}{json.dumps(result, ensure_ascii=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
