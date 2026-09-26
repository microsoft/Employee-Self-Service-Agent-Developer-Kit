# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Bind ESS Workday Runtime solution references to physical connections."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

from auth import authenticate, query_all, update_record
from install_workday_da_extension import ensure_pac_auth, resolve_pac_executable


WORKDAY_LOGICAL_NAME = "msdyn_sharedworkdaysoap_workdayruntime"
DATAVERSE_LOGICAL_NAME = (
    "msdyn_sharedcommondataserviceforapps_workdayruntime"
)
WORKDAY_CONNECTOR = "shared_workdaysoap"
DATAVERSE_CONNECTOR = "shared_commondataserviceforapps"
PLAN_MARKER = "WORKDAY_DA_BINDING_PLAN_JSON:"
APPLIED_MARKER = "WORKDAY_DA_BINDING_APPLIED_JSON:"
FAILED_MARKER = "WORKDAY_DA_BINDING_FAILED_JSON:"


class WorkdayDABindingError(RuntimeError):
    """Raised when connection binding cannot be completed safely."""


def _run(command: list[str], *, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _connector_name(connection: dict[str, Any]) -> str:
    properties = connection.get("properties") or {}
    api_id = str(properties.get("apiId") or "")
    return api_id.rstrip("/").rsplit("/", 1)[-1].casefold()


def _is_connected(connection: dict[str, Any]) -> bool:
    properties = connection.get("properties") or {}
    statuses = properties.get("statuses") or []
    return any(
        str(status.get("status") or "").casefold() == "connected"
        for status in statuses
        if isinstance(status, dict)
    )


def _connection_summary(connection: dict[str, Any]) -> dict[str, str]:
    properties = connection.get("properties") or {}
    return {
        "id": str(connection.get("name") or ""),
        "displayName": str(properties.get("displayName") or ""),
        "connector": _connector_name(connection),
        "status": "Connected" if _is_connected(connection) else "NotConnected",
    }


def _select_connection(
    connections: list[dict[str, Any]],
    connector_name: str,
    *,
    explicit_id: str | None,
) -> dict[str, Any]:
    candidates = [
        connection
        for connection in connections
        if _connector_name(connection) == connector_name.casefold()
        and _is_connected(connection)
    ]
    if explicit_id:
        candidates = [
            connection
            for connection in candidates
            if str(connection.get("name") or "").casefold()
            == explicit_id.casefold()
        ]
    if len(candidates) != 1:
        safe_candidates = [
            _connection_summary(connection) for connection in candidates
        ]
        raise WorkdayDABindingError(
            f"Expected exactly one connected {connector_name} connection; "
            f"found {len(candidates)}. Candidates: "
            f"{json.dumps(safe_candidates, sort_keys=True)}"
        )
    return candidates[0]


def _parse_connection_inventory(output: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(output)
    except ValueError as exc:
        raise WorkdayDABindingError(
            "PAC returned invalid JSON while listing connections."
        ) from exc
    connections = payload.get("value")
    if not isinstance(connections, list):
        raise WorkdayDABindingError(
            "PAC connection inventory did not contain a value array."
        )
    return [item for item in connections if isinstance(item, dict)]


def _list_connections(
    pac_executable: Path,
    environment_url: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess],
) -> list[dict[str, Any]]:
    result = runner(
        [
            str(pac_executable),
            "connectivity",
            "list-connections",
            "--environment",
            environment_url,
            "--json",
        ],
        timeout=120,
    )
    if result.returncode != 0:
        raise WorkdayDABindingError(
            "PAC could not list the target environment's connections."
        )
    return _parse_connection_inventory(result.stdout or "")


def query_runtime_references(
    environment_url: str,
    token: str,
    *,
    query: Callable[..., list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    filter_expr = (
        f"connectionreferencelogicalname eq '{WORKDAY_LOGICAL_NAME}' or "
        f"connectionreferencelogicalname eq '{DATAVERSE_LOGICAL_NAME}'"
    )
    rows = query(
        environment_url,
        token,
        "connectionreferences",
        "connectionreferenceid,connectionreferencelogicalname,"
        "connectionreferencedisplayname,connectorid,connectionid,statuscode",
        filter_expr,
    )
    grouped: dict[str, list[dict[str, Any]]] = {
        WORKDAY_LOGICAL_NAME: [],
        DATAVERSE_LOGICAL_NAME: [],
    }
    for row in rows:
        logical_name = str(
            row.get("connectionreferencelogicalname") or ""
        ).casefold()
        for expected in grouped:
            if logical_name == expected.casefold():
                grouped[expected].append(row)
    invalid = {
        logical_name: len(matches)
        for logical_name, matches in grouped.items()
        if len(matches) != 1
    }
    if invalid:
        raise WorkdayDABindingError(
            "Expected exactly one installed runtime connection reference for "
            f"each logical name; observed {json.dumps(invalid, sort_keys=True)}."
        )
    return {
        logical_name: matches[0]
        for logical_name, matches in grouped.items()
    }


def bind_runtime_connections(
    environment_url: str,
    *,
    ring: str,
    apply: bool,
    preferred_username: str | None = None,
    workday_connection_id: str | None = None,
    dataverse_connection_id: str | None = None,
    pac_resolver: Callable[[], Path] = resolve_pac_executable,
    pac_auth: Callable[..., None] = ensure_pac_auth,
    runner: Callable[..., subprocess.CompletedProcess] = _run,
    token_provider: Callable[..., str] = authenticate,
    query: Callable[..., list[dict[str, Any]]] = query_all,
    updater: Callable[..., bool] = update_record,
) -> dict[str, Any]:
    """Preview or apply the two ESS Workday Runtime connection bindings."""
    environment_url = environment_url.rstrip("/")
    pac_executable = pac_resolver()
    pac_auth(
        pac_executable,
        ring=ring,
        environment_url=environment_url,
        preferred_username=preferred_username,
    )
    connections = _list_connections(
        pac_executable,
        environment_url,
        runner=runner,
    )
    workday = _select_connection(
        connections,
        WORKDAY_CONNECTOR,
        explicit_id=workday_connection_id,
    )
    dataverse = _select_connection(
        connections,
        DATAVERSE_CONNECTOR,
        explicit_id=dataverse_connection_id,
    )
    token = token_provider(
        environment_url,
        preferred_username=preferred_username,
    )
    references = query_runtime_references(
        environment_url,
        token,
        query=query,
    )
    targets = {
        WORKDAY_LOGICAL_NAME: str(workday.get("name") or ""),
        DATAVERSE_LOGICAL_NAME: str(dataverse.get("name") or ""),
    }
    changes = [
        {
            "logicalName": logical_name,
            "displayName": str(
                references[logical_name].get(
                    "connectionreferencedisplayname"
                )
                or logical_name
            ),
            "currentConnectionId": references[logical_name].get(
                "connectionid"
            ),
            "targetConnectionId": target_id,
            "action": (
                "unchanged"
                if str(
                    references[logical_name].get("connectionid") or ""
                ).casefold()
                == target_id.casefold()
                else "bind"
            ),
        }
        for logical_name, target_id in targets.items()
    ]
    result = {
        "environmentUrl": environment_url,
        "mode": "apply" if apply else "preview",
        "changes": changes,
    }
    if not apply:
        return result

    for change in changes:
        if change["action"] == "unchanged":
            continue
        reference = references[change["logicalName"]]
        record_id = reference.get("connectionreferenceid")
        if not record_id:
            raise WorkdayDABindingError(
                f"{change['logicalName']} has no connectionreferenceid."
            )
        updater(
            environment_url,
            token,
            "connectionreferences",
            record_id,
            {"connectionid": change["targetConnectionId"]},
        )

    verified = query_runtime_references(
        environment_url,
        token,
        query=query,
    )
    for logical_name, target_id in targets.items():
        observed = str(verified[logical_name].get("connectionid") or "")
        if observed.casefold() != target_id.casefold():
            raise WorkdayDABindingError(
                f"Post-write verification failed for {logical_name}; "
                "the expected connection binding did not persist."
            )
    result["verified"] = True
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Bind ESS Workday Runtime solution references to connected "
            "Workday and Dataverse physical connections."
        )
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--ring", choices=["preprod", "prod"], required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--preferred-username")
    parser.add_argument("--workday-connection-id")
    parser.add_argument("--dataverse-connection-id")
    args = parser.parse_args()

    marker = APPLIED_MARKER if args.apply else PLAN_MARKER
    try:
        result = bind_runtime_connections(
            args.url,
            ring=args.ring,
            apply=args.apply,
            preferred_username=args.preferred_username,
            workday_connection_id=args.workday_connection_id,
            dataverse_connection_id=args.dataverse_connection_id,
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"{FAILED_MARKER}{json.dumps({'error': str(error)})}")
        sys.exit(1)
    print(f"{marker}{json.dumps(result, sort_keys=True)}")


if __name__ == "__main__":
    main()
