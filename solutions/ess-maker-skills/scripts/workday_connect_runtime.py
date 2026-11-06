# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Consolidated preview, apply, and verification for Workday runtime wiring."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping
from uuid import UUID

import requests

from agentbuilder import (
    AgentBuilderError,
    ConnectivityClient,
    DEFAULT_API_VERSION,
    authenticate as authenticate_connections,
    connectivity_read_scopes,
)
from auth import authenticate, query_all, update_record
from install_workday_da_extension import (
    PacCliError,
    ensure_pac_auth,
    resolve_pac_executable,
)
from workday_connect_model import load_catalog, plan_hash
from workday_connect_auth import (
    WorkdayConnectIdentityError,
    require_identity,
)


ACTIVE_FLOW_STATE = 1
ACTIVE_FLOW_STATUS = 2
CLOUD_FLOW_CATEGORY = 5
AUTHORIZATION_SCRIPT = "alm/Enable-CosmosDAFlowAuthorization.ps1"
REALM_DISPLAY_NAMES = {
    "dev": "Development",
    "test": "Test",
    "prod": "Production",
}


class WorkdayConnectRuntimeError(RuntimeError):
    """Raised when runtime configuration cannot proceed safely."""

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = dict(details or {})
        self.customer_remediation = message if self.details.get("nextAction") else ""


def _required_text(
    document: Mapping[str, Any],
    key: str,
    label: str,
) -> str:
    value = str(document.get(key) or "").strip()
    if not value:
        raise WorkdayConnectRuntimeError(f"{label} is required.")
    return value


def _odata_literal(value: str) -> str:
    return value.replace("'", "''")


def _powershell_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _connector_name(connection: Mapping[str, Any]) -> str:
    api_id = str((connection.get("properties") or {}).get("apiId") or "")
    return api_id.rstrip("/").rsplit("/", 1)[-1].casefold()


def _connected(connection: Mapping[str, Any]) -> bool:
    statuses = (connection.get("properties") or {}).get("statuses") or []
    return any(
        isinstance(status, Mapping)
        and str(status.get("status") or "").casefold() == "connected"
        for status in statuses
    )


def _select_connection(
    connections: list[dict[str, Any]],
    connector_name: str,
    *,
    explicit_id: str | None,
) -> dict[str, Any]:
    connected_matches = [
        value
        for value in connections
        if _connector_name(value) == connector_name.casefold()
        and _connected(value)
    ]
    matches = [
        value
        for value in connected_matches
        if not explicit_id
        or str(value.get("name") or "").casefold() == explicit_id.casefold()
    ]
    if len(matches) != 1:
        candidates = sorted(
            (
                {
                    "connectionId": str(value.get("name") or ""),
                    "displayName": str(
                        (value.get("properties") or {}).get("displayName")
                        or connector_name
                    ),
                }
                for value in connected_matches
            ),
            key=lambda value: (
                value["displayName"].casefold(),
                value["connectionId"].casefold(),
            ),
        )
        safe = sorted({value["displayName"] for value in candidates})
        raise WorkdayConnectRuntimeError(
            f"Expected exactly one connected {connector_name} connection; "
            f"found {len(matches)}. Connected display names: "
            f"{json.dumps(safe, sort_keys=True)}",
            details={
                "connector": connector_name,
                "candidateConnections": candidates,
            },
        )
    return matches[0]


def _list_connections(
    pac_executable: Path,
    environment_url: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess],
) -> list[dict[str, Any]]:
    try:
        result = runner(
            [
                str(pac_executable),
                "connectivity",
                "list-connections",
                "--environment",
                environment_url,
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkdayConnectRuntimeError(
            "PAC did not finish listing environment connections within 2 minutes."
        ) from exc
    if result.returncode != 0:
        output = f"{result.stdout or ''}\n{result.stderr or ''}"
        if any(
            marker in output.casefold()
            for marker in (
                "not a valid command",
                "unknown command",
                "unrecognized command",
                "unknown argument",
                "unrecognized argument",
                "unneeded argument",
                "not recognized as",
            )
        ):
            raise WorkdayConnectRuntimeError(
                _pac_upgrade_guidance(pac_executable, output)
            )
        raise WorkdayConnectRuntimeError(
            "PAC could not list the target environment's connections. "
            "Check the selected maker's access and PAC sign-in, then retry "
            "/connect workday."
        )
    try:
        payload = json.loads(result.stdout or "")
    except json.JSONDecodeError as exc:
        raise WorkdayConnectRuntimeError(
            "PAC returned invalid connection inventory JSON."
        ) from exc
    values = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(values, list) or not all(
        isinstance(value, dict) for value in values
    ):
        raise WorkdayConnectRuntimeError(
            "PAC connection inventory did not contain a valid value array."
        )
    return values


def _pac_upgrade_guidance(
    pac_executable: Path,
    output: str,
    *,
    command: str = "connectivity list-connections",
    options: str = "--json",
) -> str:
    version = re.search(r"Version:\s*([\w.+-]+)", output, re.IGNORECASE)
    version_label = f" (version {version.group(1)})" if version else ""
    executable = _powershell_literal(pac_executable)
    location = str(pac_executable).replace("\\", "/").casefold()
    if "/.dotnet/tools/" in location:
        upgrade = (
            "Run 'dotnet tool update --global Microsoft.PowerApps.CLI.Tool', "
            "then reopen the terminal."
        )
    elif "/.vscode/extensions/" in location:
        upgrade = (
            "Update the Microsoft Power Platform Tools extension in VS Code, "
            "then restart VS Code."
        )
    else:
        upgrade = (
            "Update this exact PAC installation using its original installer "
            "or provisioning tool. For a Windows MSI installation, run "
            "'pac install latest' in its terminal; for a managed/custom copy, "
            f"update the PAC files in {_powershell_literal(pac_executable.parent)} "
            "using that copy's provisioning tool. Installation instructions: "
            "https://learn.microsoft.com/power-platform/developer/cli/introduction."
        )
    return (
        f"PAC at {executable}{version_label} does not support "
        f"'{command} {options}'. "
        f"{upgrade} The kit prefers the managed "
        "'%LOCALAPPDATA%\\InternalTools\\pac\\pac.exe' when present; "
        "updating a different PAC on PATH will not update that copy. "
        f"Verify support with: & {executable} {command} help. "
        "Then rerun /connect workday."
        + (
            " Do not use 'pac connection list' as a substitute: it does not "
            "provide the required maker-connection inventory."
            if command == "connectivity list-connections"
            else ""
        )
    )


def configured_connection_api_version(root: Path) -> str:
    config_path = root / ".local" / "config.json"
    if not config_path.exists():
        return DEFAULT_API_VERSION
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkdayConnectRuntimeError(
            "The foundation configuration could not be read for connection discovery."
        ) from exc
    if not isinstance(config, Mapping):
        raise WorkdayConnectRuntimeError(
            "The foundation configuration must be an object."
        )
    version = config.get("agentBuilderApiVersion", DEFAULT_API_VERSION)
    if not isinstance(version, str) or not version.strip():
        raise WorkdayConnectRuntimeError(
            "The configured agentBuilderApiVersion must be a non-empty string."
        )
    return version


def _api_connections(context: Mapping[str, Any]) -> list[dict[str, Any]]:
    environment_id = _required_text(context, "environmentId", "Environment ID")
    tenant_id = _required_text(context, "tenantId", "Microsoft Entra tenant ID")
    ring = str(context["ring"])
    token = authenticate_connections(
        tenant_id,
        ring,
        account_hint=context["maker"],
        scopes=connectivity_read_scopes(ring),
    )
    identity = require_identity(token, preferred_username=context["maker"])
    if identity["tenantId"].casefold() != tenant_id.casefold():
        raise WorkdayConnectIdentityError(
            "Power Platform connection discovery authenticated to a different "
            "Microsoft Entra tenant from the selected Workday target."
        )
    return ConnectivityClient(
        token, ring=ring,
        api_version=context.get("agentBuilderApiVersion", DEFAULT_API_VERSION),
    ).list_connections(environment_id)


def _single_rows(
    rows: list[dict[str, Any]],
    names: list[str],
    key: str,
    label: str,
) -> dict[str, dict[str, Any]]:
    grouped = {name: [] for name in names}
    for row in rows:
        observed = str(row.get(key) or "").casefold()
        for name in names:
            if observed == name.casefold():
                grouped[name].append(row)
    invalid = {
        name: len(matches) for name, matches in grouped.items() if len(matches) != 1
    }
    if invalid:
        raise WorkdayConnectRuntimeError(
            f"Expected exactly one installed {label} for each reviewed name; "
            f"observed {json.dumps(invalid, sort_keys=True)}."
        )
    return {name: grouped[name][0] for name in names}


def _runtime_references(
    environment_url: str,
    token: str,
    logical_names: list[str],
    *,
    query: Callable[..., list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    filters = " or ".join(
        f"connectionreferencelogicalname eq '{_odata_literal(name)}'"
        for name in logical_names
    )
    rows = query(
        environment_url,
        token,
        "connectionreferences",
        "connectionreferenceid,connectionreferencelogicalname,"
        "connectionreferencedisplayname,connectionid",
        filters,
    )
    return _single_rows(
        rows,
        logical_names,
        "connectionreferencelogicalname",
        "connection reference",
    )


def _runtime_flows(
    environment_url: str,
    token: str,
    flow_names: list[str],
    allowed_workflow_ids: set[str],
    *,
    query: Callable[..., list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    filters = " or ".join(f"name eq '{_odata_literal(name)}'" for name in flow_names)
    rows = query(
        environment_url,
        token,
        "workflows",
        "workflowid,name,statecode,statuscode,category",
        filters,
    )
    flows = _single_rows(rows, flow_names, "name", "Workday flow")
    outside_package = [
        name
        for name, row in flows.items()
        if str(row.get("workflowid") or "").casefold() not in allowed_workflow_ids
    ]
    if outside_package:
        raise WorkdayConnectRuntimeError(
            "A reviewed Workday flow name resolved outside the selected "
            "installed package: " + ", ".join(sorted(outside_package))
        )
    non_cloud = [
        name
        for name, row in flows.items()
        if row.get("category") != CLOUD_FLOW_CATEGORY
    ]
    if non_cloud:
        raise WorkdayConnectRuntimeError(
            "Refusing to configure non-cloud workflow records: "
            + ", ".join(sorted(non_cloud))
        )
    return flows


def _solution_component_ids(
    environment_url: str,
    token: str,
    solution_schema: str,
    *,
    query: Callable[..., list[dict[str, Any]]],
) -> set[str]:
    solutions = query(
        environment_url,
        token,
        "solutions",
        "solutionid,uniquename",
        f"uniquename eq '{_odata_literal(solution_schema)}'",
    )
    if len(solutions) != 1:
        raise WorkdayConnectRuntimeError(
            "Expected exactly one installed Workday package solution "
            f"'{solution_schema}'; found {len(solutions)}."
        )
    solution_id = _required_text(
        solutions[0],
        "solutionid",
        f"Solution ID for {solution_schema}",
    )
    components = query(
        environment_url,
        token,
        "solutioncomponents",
        "objectid,componenttype",
        f"_solutionid_value eq {solution_id} and componenttype eq 29",
    )
    component_ids = {
        str(value.get("objectid") or "").casefold()
        for value in components
        if str(value.get("objectid") or "").strip()
    }
    if not component_ids:
        raise WorkdayConnectRuntimeError(
            "The installed Workday package did not expose solution-component "
            "membership for its reviewed flows."
        )
    return component_ids


def _default_runner(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("text", True)
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(command, **kwargs)


def _runtime_discovery_context(
    state: Mapping[str, Any],
    catalog: Mapping[str, Any] | None,
    *,
    api_version: str = DEFAULT_API_VERSION,
) -> dict[str, Any]:
    scope = state.get("scope") or {}
    operators = state.get("operators") or {}
    agent = scope.get("agent") or {}
    realm = str(state.get("activeTargetRealm") or "dev").casefold()
    if realm not in REALM_DISPLAY_NAMES:
        raise WorkdayConnectRuntimeError(
            "The active Workday target realm is invalid."
        )
    targets = state.get("targets") or {}
    target = targets.get(realm)
    target_identity = (
        target.get("identity")
        if isinstance(target, Mapping)
        and isinstance(target.get("identity"), Mapping)
        else {}
    )
    environment_id = str(
        target_identity.get("environmentId")
        or scope.get("environmentId")
        or ""
    ).strip()
    tenant_id = str(
        target_identity.get("tenantId")
        or scope.get("entraTenantId")
        or ""
    ).strip()
    bot_id = _required_text(
        {"botId": target_identity.get("agentId") or agent.get("botId")},
        "botId",
        "Workday agent bot ID",
    )
    if realm != "dev":
        required_target_identity = {
            "environmentId": environment_id,
            "tenantId": tenant_id,
            "almFamilyId": str(
                target_identity.get("almFamilyId") or ""
            ).strip(),
            "commitSha": str(
                target_identity.get("commitSha") or ""
            ).strip(),
        }
        missing = [
            key for key, value in required_target_identity.items() if not value
        ]
        if missing:
            raise WorkdayConnectRuntimeError(
                f"The {REALM_DISPLAY_NAMES[realm]} target identity is "
                "incomplete: "
                + ", ".join(sorted(missing))
            )
        if (
            str(scope.get("environmentId") or "").casefold()
            != environment_id.casefold()
            or str(agent.get("botId") or "").casefold()
            != bot_id.casefold()
            or str(scope.get("entraTenantId") or "").casefold()
            != tenant_id.casefold()
        ):
            raise WorkdayConnectRuntimeError(
                f"The active {REALM_DISPLAY_NAMES[realm]} target projection "
                "does not match its verified identity."
            )
    package_flavor = _required_text(scope, "packageFlavor", "Workday package flavor")
    active_catalog = catalog or load_catalog()
    package = (active_catalog.get("packages") or {}).get(package_flavor)
    if not isinstance(package, Mapping):
        raise WorkdayConnectRuntimeError(
            f"Unknown Workday package flavor: {package_flavor}."
        )
    flow_names = package.get("flowNames")
    if not isinstance(flow_names, list) or not flow_names:
        raise WorkdayConnectRuntimeError(
            "This Workday architecture requires a manual runtime handoff; "
            "no reviewed flow catalog is available."
        )
    ring = str(scope.get("ring") or "prod").casefold()
    if ring not in {"prod", "preprod", "test"}:
        raise WorkdayConnectRuntimeError(
            f"Unsupported Power Platform ring: {ring!r}."
        )
    return {
        "realm": realm,
        "realmDisplayName": REALM_DISPLAY_NAMES[realm],
        "agent": agent,
        "environmentUrl": _required_text(
            scope, "dataverseUrl", "Dataverse environment URL"
        ).rstrip("/"),
        "environmentId": environment_id,
        "tenantId": tenant_id,
        "packageFlavor": package_flavor,
        "botId": bot_id,
        "almFamilyId": str(
            target_identity.get("almFamilyId") or ""
        ).strip(),
        "commitSha": str(target_identity.get("commitSha") or "").strip(),
        "maker": _required_text(
            operators.get("powerPlatformMaker") or {},
            "username",
            "Power Platform maker account",
        ),
        "ring": ring,
        "agentBuilderApiVersion": api_version,
        "pacRing": "preprod" if ring in {"test", "preprod"} else "prod",
        "package": package,
        "flowNames": [str(name) for name in flow_names],
        "referencesCatalog": active_catalog["connectionReferences"],
        "selectedConnectionIds": _selected_connection_ids(state),
    }


def _selected_connection_ids(
    state: Mapping[str, Any],
) -> dict[str, str]:
    phase = (state.get("phases") or {}).get("connections") or {}
    for record in reversed(phase.get("evidence") or []):
        if (
            isinstance(record, Mapping)
            and record.get("action") == "physical-connections-verified"
            and isinstance(record.get("connectionIds"), Mapping)
        ):
            values = record["connectionIds"]
            return {
                "workday": str(values.get("workday") or "").strip(),
                "dataverse": str(values.get("dataverse") or "").strip(),
            }
    return {"workday": "", "dataverse": ""}


def _effective_connection_id(
    connector: str,
    requested: str | None,
    recorded: str,
) -> str | None:
    requested_value = str(requested or "").strip()
    recorded_value = str(recorded or "").strip()
    if (
        requested_value
        and recorded_value
        and requested_value.casefold() != recorded_value.casefold()
    ):
        raise WorkdayConnectRuntimeError(
            f"The requested {connector} connection ID differs from the "
            "connection verified during the Connections phase."
        )
    return requested_value or recorded_value or None


def _require_shared_connection_selection(
    state: Mapping[str, Any],
    context: Mapping[str, Any],
    workday: Mapping[str, Any],
    dataverse: Mapping[str, Any],
) -> None:
    selected = {"workday": workday, "dataverse": dataverse}
    for realm, target in (state.get("targets") or {}).items():
        if realm == context["realm"] or not isinstance(target, Mapping):
            continue
        identity = target.get("identity") or {}
        scope = target.get("scope") or {}
        environment_id = str(
            identity.get("environmentId") or scope.get("environmentId") or ""
        ).strip()
        environment_url = str(
            identity.get("environmentUrl") or scope.get("dataverseUrl") or ""
        ).strip().rstrip("/")
        same_environment = (
            environment_id
            and context["environmentId"]
            and environment_id.casefold() == context["environmentId"].casefold()
        ) or environment_url.casefold() == context["environmentUrl"].casefold()
        if not same_environment:
            continue
        phase = (target.get("phases") or {}).get("runtime") or {}
        if not (
            target.get("status") == "ready"
            or phase.get("status") == "complete"
            or "connection-references-bound" in (phase.get("completedActions") or [])
        ):
            continue
        bindings = (phase.get("approvedPlan") or {}).get("connectionBindings") or {}
        recorded = _selected_connection_ids(target)
        conflicts = []
        required_ids = {}
        for connector, connection in selected.items():
            logical_name = context["referencesCatalog"][connector]["logicalName"]
            binding = bindings.get(logical_name) or {}
            expected = str(
                binding.get("connectionId")
                or (recorded[connector] if not bindings else "")
            ).strip()
            if expected:
                required_ids[connector] = expected
            if not expected or expected.casefold() != str(connection.get("name") or "").casefold():
                conflicts.append(connector)
        if conflicts:
            target_name = REALM_DISPLAY_NAMES[realm]
            next_action = (
                f"Reuse the verified Workday and Microsoft Dataverse connections "
                f"of the {target_name} target, with the required access, or use "
                "a separate Power Platform environment for different bindings. "
                "Do not rebind the shared runtime references independently."
            )
            raise WorkdayConnectRuntimeError(
                f"The selected connections conflict with, or cannot be verified "
                f"against, the shared runtime bindings already established for "
                f"{target_name} in this environment. {next_action}",
                details={
                    "cause": "shared-runtime-binding-conflict",
                    "targetRealm": realm,
                    "conflictingConnectors": conflicts,
                    "requiredConnectionIds": required_ids,
                    "nextAction": next_action,
                },
            )


def _authorization_preflight_failure(
    evidence: str,
    next_action: str,
    *,
    cause: str = "invalid-records",
) -> WorkdayConnectRuntimeError:
    return WorkdayConnectRuntimeError(
        f"{evidence} No runtime changes were made. {next_action}",
        details={
            "stage": "authorization-preflight",
            "cause": cause,
            "nextAction": next_action,
        },
    )


def _authorization_target(
    environment_url: str,
    token: str,
    realm: str,
    bot_id: str,
    *,
    query: Callable[..., list[dict[str, Any]]],
) -> dict[str, Any]:
    """Resolve exact-agent ownership before any runtime writes."""
    try:
        canonical_bot_id = str(UUID(bot_id))
    except ValueError as exc:
        raise _authorization_preflight_failure(
            "The selected agent needs a valid BotId before runtime authorization.",
            "Verify the selected agent and environment through supported target "
            "recovery, then check Runtime again. Do not substitute another agent.",
        ) from exc

    def record_id(row: Mapping[str, Any], key: str, label: str) -> str:
        try:
            return str(UUID(str(row.get(key) or "")))
        except ValueError as exc:
            raise _authorization_preflight_failure(
                f"Authorization preflight could not validate the {label}.",
                "Ask the Dataverse administrator to inspect the selected "
                "agent's records before retrying."
            ) from exc

    def read(entity_set: str, select: str, filter_expr: str) -> list[dict[str, Any]]:
        try:
            rows = query(
                environment_url, token, entity_set, select,
                filter_expr=filter_expr,
            )
        except requests.RequestException as exc:
            raise _authorization_preflight_failure(
                "Authorization preflight could not read the selected agent's "
                "Dataverse records.",
                "Ask the Dataverse administrator to verify read access, "
                "then check again.",
                cause="read-failed",
            ) from exc
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows
        ):
            raise _authorization_preflight_failure(
                "Authorization preflight received unreadable Dataverse records.",
                "Ask the Dataverse administrator to investigate, then check again."
            )
        return rows

    authorizations = read(
        "delegatedauthorizations",
        "delegatedauthorizationid,botid,providertype",
        f"botid eq '{canonical_bot_id}'",
    )
    teams = read(
        "teams",
        "teamid,name,teamtype,_delegatedauthorizationid_value,_businessunitid_value",
        f"delegatedauthorizationid/botid eq '{canonical_bot_id}'",
    )
    if len(authorizations) > 1 or len(teams) > 1:
        raise _authorization_preflight_failure(
            "Multiple authorization records or linked teams exist for the selected agent.",
            "Ask the Dataverse administrator to resolve these duplicates, "
            "then check again. Do not delete another agent's records."
        )
    authorization = authorizations[0] if authorizations else None
    if authorization is not None and (
        str(authorization.get("botid") or "").casefold() != canonical_bot_id
        or authorization.get("providertype") != 3
    ):
        raise _authorization_preflight_failure(
            "The selected agent's authorization has an unexpected owner or provider "
            "type.",
            "Ask the Dataverse administrator to inspect it before retrying.",
        )
    authorization_id = (
        record_id(authorization, "delegatedauthorizationid", "authorization ID")
        if authorization is not None else None
    )
    if teams:
        team = teams[0]
        if (
            not authorization_id
            or team.get("teamtype") != 1
            or str(team.get("_delegatedauthorizationid_value") or "").casefold()
            != authorization_id.casefold()
        ):
            raise _authorization_preflight_failure(
                "The linked team does not prove access-team ownership by the "
                "selected agent.",
                "Ask the Dataverse administrator to inspect the "
                "relationship before retrying. Do not adopt or relink another team."
            )
        team_name = str(team.get("name") or "").strip()
        if not team_name:
            raise _authorization_preflight_failure(
                "The selected agent's access team has no readable name.",
                "Ask the Dataverse administrator to inspect the linked access team, "
                "then check again.",
            )
        return {
            "authorizationId": authorization_id,
            "teamId": record_id(team, "teamid", "access team ID"),
            "teamName": team_name,
            "businessUnitId": record_id(
                team, "_businessunitid_value", "access team business unit"
            ),
        }
    units = read(
        "businessunits", "businessunitid",
        "parentbusinessunitid eq null",
    )
    if len(units) != 1:
        raise _authorization_preflight_failure(
            "Authorization preflight could not resolve exactly one root business "
            "unit.",
            "Ask the Dataverse administrator to inspect it, then check again.",
        )
    unit_id = record_id(units[0], "businessunitid", "root business unit")
    team_name = f"ESS DA HR Workday - {REALM_DISPLAY_NAMES[realm]} - {canonical_bot_id}"
    conflicts = read(
        "teams", "teamid",
        f"_businessunitid_value eq {unit_id} and name eq '{_odata_literal(team_name)}'",
    )
    if conflicts:
        raise _authorization_failure("ndx_TeamName_BusinessUnitId", preflight=True)
    return {
        "authorizationId": authorization_id,
        "teamId": None,
        "teamName": team_name,
        "businessUnitId": unit_id,
    }


def _build_runtime_discovery(
    context: Mapping[str, Any],
    *,
    workday: Mapping[str, Any],
    dataverse: Mapping[str, Any],
    references: Mapping[str, Mapping[str, Any]],
    flows: Mapping[str, Mapping[str, Any]],
    authorization_target: Mapping[str, Any],
) -> dict[str, Any]:
    references_catalog = context["referencesCatalog"]
    logical_names = [
        references_catalog["workday"]["logicalName"],
        references_catalog["dataverse"]["logicalName"],
    ]
    target_connections = {
        logical_names[0]: {
            "connectionId": str(workday.get("name") or ""),
            "displayName": str(
                (workday.get("properties") or {}).get("displayName") or "Workday"
            ),
            "connector": references_catalog["workday"]["connectorName"],
        },
        logical_names[1]: {
            "connectionId": str(dataverse.get("name") or ""),
            "displayName": str(
                (dataverse.get("properties") or {}).get("displayName")
                or "Microsoft Dataverse"
            ),
            "connector": references_catalog["dataverse"]["connectorName"],
        },
    }
    flow_targets = [
        {
            "name": name,
            "workflowId": _required_text(
                flows[name], "workflowid", f"Workflow ID for {name}"
            ),
        }
        for name in context["flowNames"]
    ]
    plan = {
        "phase": "runtime",
        "scope": {
            "realm": context["realm"],
            "realmDisplayName": context["realmDisplayName"],
            "dataverseUrl": context["environmentUrl"],
            "environmentId": context["environmentId"],
            "tenantId": context["tenantId"],
            "botId": context["botId"],
            "almFamilyId": context["almFamilyId"],
            "commitSha": context["commitSha"],
            "packageFlavor": context["packageFlavor"],
            "makerUsername": context["maker"],
        },
        "connectionBindings": target_connections,
        "flows": flow_targets,
        "delegatedAuthorization": {
            "botId": context["botId"],
            "workflowIds": [target["workflowId"] for target in flow_targets],
            "script": AUTHORIZATION_SCRIPT,
            **authorization_target,
        },
        "actions": [
            "Bind the reviewed Workday and Dataverse connection references",
            "Activate the reviewed Workday runtime cloud flows",
            "Authorize the selected agent to invoke each reviewed flow",
            "Reread and verify every changed Dataverse record",
        ],
    }
    observed = {
        "connectionBindings": {
            name: {
                "selectedDisplayName": target_connections[name]["displayName"],
                "alreadyBoundToSelection": str(
                    references[name].get("connectionid") or ""
                ).casefold()
                == target_connections[name]["connectionId"].casefold(),
            }
            for name in logical_names
        },
        "flowStates": {
            name: {
                "statecode": flows[name].get("statecode"),
                "statuscode": flows[name].get("statuscode"),
            }
            for name in context["flowNames"]
        },
    }
    return {
        "plan": {**plan, "planHash": plan_hash(plan)},
        "approvalSummary": {
            "targetRealm": context["realmDisplayName"],
            "environmentUrl": context["environmentUrl"],
            "agentName": str(context["agent"].get("name") or "ESS HR agent"),
            "connections": [
                value["displayName"] for value in target_connections.values()
            ],
            "flows": [target["name"] for target in flow_targets],
            "authorizationTeam": (
                "Reuse the existing internal Dataverse access team linked to this agent."
                if authorization_target["teamId"]
                else "Create a new internal Dataverse access team for this agent."
            ),
        },
        "observed": observed,
    }


def discover_runtime_plan(
    state: Mapping[str, Any],
    *,
    api_version: str = DEFAULT_API_VERSION,
    workday_connection_id: str | None = None,
    dataverse_connection_id: str | None = None,
    catalog: Mapping[str, Any] | None = None,
    token: str | None = None,
    token_provider: Callable[..., str] = authenticate,
    query: Callable[..., list[dict[str, Any]]] = query_all,
    pac_resolver: Callable[[], Path] = resolve_pac_executable,
    pac_auth: Callable[..., Any] = ensure_pac_auth,
    runner: Callable[..., subprocess.CompletedProcess] = _default_runner,
) -> dict[str, Any]:
    """Discover exact runtime targets and return a stable approval plan."""
    context = _runtime_discovery_context(state, catalog, api_version=api_version)
    selected_ids = context["selectedConnectionIds"]
    workday, dataverse = _discover_physical_connections(
        context,
        workday_connection_id=_effective_connection_id(
            "Workday",
            workday_connection_id,
            selected_ids["workday"],
        ),
        dataverse_connection_id=_effective_connection_id(
            "Dataverse",
            dataverse_connection_id,
            selected_ids["dataverse"],
        ),
        pac_resolver=pac_resolver,
        pac_auth=pac_auth,
        runner=runner,
    )
    _require_shared_connection_selection(state, context, workday, dataverse)

    active_token = token or token_provider(
        context["environmentUrl"],
        preferred_username=context["maker"],
    )
    references_catalog = context["referencesCatalog"]
    logical_names = [
        references_catalog["workday"]["logicalName"],
        references_catalog["dataverse"]["logicalName"],
    ]
    references = _runtime_references(
        context["environmentUrl"],
        active_token,
        logical_names,
        query=query,
    )
    solution_component_ids = _solution_component_ids(
        context["environmentUrl"],
        active_token,
        _required_text(
            context["package"],
            "solutionSchemaName",
            "Workday package solution schema",
        ),
        query=query,
    )
    flows = _runtime_flows(
        context["environmentUrl"],
        active_token,
        context["flowNames"],
        solution_component_ids,
        query=query,
    )
    return _build_runtime_discovery(
        context,
        workday=workday,
        dataverse=dataverse,
        references=references,
        flows=flows,
        authorization_target=_authorization_target(
            context["environmentUrl"], active_token,
            context["realm"], context["botId"], query=query,
        ),
    )


def _discover_physical_connections(
    context: Mapping[str, Any],
    *,
    workday_connection_id: str | None,
    dataverse_connection_id: str | None,
    pac_resolver: Callable[[], Path],
    pac_auth: Callable[..., Any],
    runner: Callable[..., subprocess.CompletedProcess],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        connections = _api_connections(context)
    except WorkdayConnectIdentityError as exc:
        raise WorkdayConnectRuntimeError(str(exc)) from exc
    except (
        AgentBuilderError,
        requests.RequestException,
        OSError,
        ValueError,
        WorkdayConnectRuntimeError,
    ) as exc:
        api_error = str(exc)
        print(
            f"[WARNING] Power Platform connection API discovery failed: "
            f"{api_error} Falling back to PAC for the same environment "
            "and maker account.",
            file=sys.stderr,
        )
        try:
            pac = pac_resolver()
            pac_auth(
                pac,
                ring=context["pacRing"],
                environment_url=context["environmentUrl"],
                preferred_username=context["maker"],
                runner=runner,
            )
            connections = _list_connections(
                pac,
                context["environmentUrl"],
                runner=runner,
            )
        except (
            PacCliError,
            WorkdayConnectRuntimeError,
            OSError,
            subprocess.TimeoutExpired,
        ) as pac_exc:
            pac_error = (
                "PAC authentication timed out. Complete sign-in with the "
                "selected maker account, then retry /connect workday."
                if isinstance(pac_exc, subprocess.TimeoutExpired)
                else str(pac_exc)
            )
            raise WorkdayConnectRuntimeError(
                f"Power Platform connection API discovery failed: {api_error} "
                f"PAC fallback failed: {pac_error}",
                details={"apiDiscoveryError": api_error},
            ) from pac_exc
    references_catalog = context["referencesCatalog"]
    dataverse = _select_connection(
        connections,
        references_catalog["dataverse"]["connectorName"],
        explicit_id=dataverse_connection_id,
    )
    workday = _select_connection(
        connections,
        references_catalog["workday"]["connectorName"],
        explicit_id=workday_connection_id,
    )
    return workday, dataverse


def verify_physical_connections(
    state: Mapping[str, Any],
    *,
    api_version: str = DEFAULT_API_VERSION,
    workday_connection_id: str | None = None,
    dataverse_connection_id: str | None = None,
    catalog: Mapping[str, Any] | None = None,
    pac_resolver: Callable[[], Path] = resolve_pac_executable,
    pac_auth: Callable[..., Any] = ensure_pac_auth,
    runner: Callable[..., subprocess.CompletedProcess] = _default_runner,
) -> dict[str, Any]:
    """Verify selected Workday and Dataverse connections from live state."""
    try:
        context = _runtime_discovery_context(state, catalog, api_version=api_version)
        selected_ids = context["selectedConnectionIds"]
        workday, dataverse = _discover_physical_connections(
            context,
            workday_connection_id=_effective_connection_id(
                "Workday",
                workday_connection_id,
                selected_ids["workday"],
            ),
            dataverse_connection_id=_effective_connection_id(
                "Dataverse",
                dataverse_connection_id,
                selected_ids["dataverse"],
            ),
            pac_resolver=pac_resolver,
            pac_auth=pac_auth,
            runner=runner,
        )
        _require_shared_connection_selection(state, context, workday, dataverse)
    except WorkdayConnectRuntimeError:
        raise
    except (OSError, RuntimeError, ValueError, SystemExit) as exc:
        raise WorkdayConnectRuntimeError(
            f"Power Platform connection discovery failed: {exc}"
        ) from exc
    return {
        "makerUsername": context["maker"],
        "connectionIds": {
            "workday": str(workday.get("name") or ""),
            "dataverse": str(dataverse.get("name") or ""),
        },
        "connections": [
            {
                "connector": context["referencesCatalog"]["workday"]["connectorName"],
                "displayName": str(
                    (workday.get("properties") or {}).get("displayName") or "Workday"
                ),
            },
            {
                "connector": context["referencesCatalog"]["dataverse"]["connectorName"],
                "displayName": str(
                    (dataverse.get("properties") or {}).get("displayName")
                    or "Microsoft Dataverse"
                ),
            },
        ],
    }


def run_runtime_operation(
    state: Mapping[str, Any],
    *,
    apply: bool,
    approved_hash: str | None = None,
    verifier: Callable[[Mapping[str, Any], str], Any] | None = None,
    workday_connection_id: str | None = None,
    dataverse_connection_id: str | None = None,
    token_provider: Callable[..., str] = authenticate,
    identity_provider: Callable[..., dict[str, str]] = require_identity,
    query: Callable[..., list[dict[str, Any]]] = query_all,
    updater: Callable[..., bool] = update_record,
    authorization_runner: Callable[..., subprocess.CompletedProcess] = _default_runner,
    stage_recorder: Callable[[str, Mapping[str, Any]], Any] | None = None,
    **discovery_dependencies: Any,
) -> dict[str, Any]:
    """Run runtime preview or apply while reusing one Dataverse token."""
    phases = state.get("phases") or {}
    if (phases.get("connections") or {}).get("status") != "complete":
        raise WorkdayConnectRuntimeError(
            "Complete the Workday connection sign-ins before runtime wiring."
        )
    scope = state.get("scope") or {}
    operators = state.get("operators") or {}
    environment_url = _required_text(
        scope, "dataverseUrl", "Dataverse environment URL"
    ).rstrip("/")
    maker = _required_text(
        operators.get("powerPlatformMaker") or {},
        "username",
        "Power Platform maker account",
    )
    try:
        token = token_provider(
            environment_url,
            preferred_username=maker,
        )
    except SystemExit as exc:
        raise WorkdayConnectRuntimeError(
            "Dataverse authentication did not complete."
        ) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkdayConnectRuntimeError(
            f"Dataverse authentication failed: {exc}"
        ) from exc
    try:
        identity = identity_provider(
            token,
            preferred_username=maker,
        )
    except WorkdayConnectIdentityError as exc:
        raise WorkdayConnectRuntimeError(str(exc)) from exc
    try:
        discovery = discover_runtime_plan(
            state,
            workday_connection_id=workday_connection_id,
            dataverse_connection_id=dataverse_connection_id,
            token=token,
            token_provider=token_provider,
            query=query,
            **discovery_dependencies,
        )
    except WorkdayConnectRuntimeError:
        raise
    except (OSError, RuntimeError, ValueError, SystemExit) as exc:
        raise WorkdayConnectRuntimeError(
            f"Runtime target discovery failed: {exc}"
        ) from exc
    if not apply:
        authorization_preview = _run_authorization(
            discovery["plan"],
            runner=authorization_runner,
            preview=True,
        )
        return {
            **discovery,
            "authorizationPreview": authorization_preview,
            "authenticatedAccount": identity["username"],
        }
    if not approved_hash or verifier is None:
        raise WorkdayConnectRuntimeError(
            "Runtime apply requires an approved plan hash."
        )
    verifier(discovery["plan"], approved_hash)
    try:
        applied = apply_runtime_plan(
            discovery["plan"],
            token=token,
            query=query,
            updater=updater,
            authorization_runner=authorization_runner,
            stage_recorder=stage_recorder,
        )
    except WorkdayConnectRuntimeError:
        raise
    except (OSError, RuntimeError, ValueError, SystemExit) as exc:
        raise WorkdayConnectRuntimeError(
            f"Runtime apply failed: {exc}"
        ) from exc
    return {
        "observedBeforeApply": discovery["observed"],
        "applied": applied,
        "authenticatedAccount": identity["username"],
    }


def _authorization_diagnostics(output: str) -> str:
    return "\n".join(
        line for line in output.casefold().splitlines()
        if not re.match(r"^\s*\[(?:reuse|create|ok)\]", line)
    )


def _authorization_forbidden(output: str) -> bool:
    return bool(re.search(
        r"(?<![\w-])403(?![\w-])|\bforbidden\b",
        _authorization_diagnostics(output),
    ))


def _authorization_failure(
    output: str,
    *,
    preflight: bool = False,
) -> WorkdayConnectRuntimeError:
    normalized = _authorization_diagnostics(output)
    if (
        "ndx_teamname_businessunitid" in normalized
        or "wd-auth-team-name-conflict" in normalized
    ):
        cause = "team-name-conflict"
        evidence = "The authorization access-team name is already in use."
        next_action = (
            "Refresh the runtime plan. If the conflict remains, ask the Dataverse "
            "administrator to inspect ownership; do not delete, rename, or adopt "
            "another agent's records."
        )
    elif _authorization_forbidden(output):
        cause = "forbidden"
        evidence = "Dataverse explicitly denied authorization access."
        next_action = (
            "Ask the Dataverse administrator to verify the selected maker's "
            "authorization and flow-sharing privileges, then check again."
        )
    elif "multiple" in normalized or "wd-auth-invalid-records" in normalized:
        cause = "invalid-records"
        evidence = "Existing authorization records are ambiguous or incorrectly linked."
        next_action = (
            "Ask the Dataverse administrator to inspect the selected agent's "
            "authorization and linked access team, then check again."
        )
    else:
        cause = "script-failed"
        evidence = (
            "The authorization script emitted an explicit [FAIL] result."
            if "[fail]" in normalized
            else "The authorization script did not complete verification."
        )
        next_action = (
            "Ask the Dataverse administrator to investigate authorization for the "
            "selected agent, then retry Runtime. Do not reset healthy connections "
            "or repeat Workday administrator setup."
        )
    progress = (
        "No runtime changes were made."
        if preflight
        else "Earlier verified runtime stages remain saved; Runtime is not complete."
    )
    return WorkdayConnectRuntimeError(
        f"Delegated flow authorization failed. {evidence} {progress} {next_action}",
        details={
            "stage": "authorization-preflight" if preflight else "delegated-authorization",
            "cause": cause,
            "nextAction": next_action,
        },
    )


def _run_authorization(
    plan: Mapping[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess],
    preview: bool = False,
) -> dict[str, Any]:
    authorization = plan["delegatedAuthorization"]
    script = str(authorization["script"])
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        print(
            f"[ERROR] Cannot run {script}: PowerShell was not found.",
            file=sys.stderr,
        )
        raise WorkdayConnectRuntimeError(
            "PowerShell is required for delegated flow authorization."
        )
    workflow_ids = [
        str(value) for value in authorization.get("workflowIds") or []
    ]
    if not workflow_ids or len(set(workflow_ids)) != len(workflow_ids):
        raise WorkdayConnectRuntimeError(
            "Delegated authorization requires unique reviewed Workday flows."
        )
    flow_names = [
        str(flow.get("name") or "")
        for flow in plan.get("flows", [])
        if isinstance(flow, Mapping)
    ]
    if len(flow_names) != len(workflow_ids):
        raise WorkdayConnectRuntimeError(
            "Delegated authorization flow metadata is incomplete."
        )
    realm = str(plan["scope"].get("realmDisplayName") or "selected target")
    operation = "Previewing" if preview else "Running"
    print(
        f"[INFO] {operation} {script} once for {len(workflow_ids)} reviewed "
        f"Workday flows in {realm}.",
        file=sys.stderr,
    )
    workflow_array = "@(" + ",".join(
        _powershell_literal(workflow_id) for workflow_id in workflow_ids
    ) + ")"
    invocation = " ".join(
        [
            "&",
            _powershell_literal(Path(__file__).parent / script),
            "-OrgUrl",
            _powershell_literal(plan["scope"]["dataverseUrl"]),
            "-BotId",
            _powershell_literal(authorization["botId"]),
            "-PreferredUsername",
            _powershell_literal(plan["scope"]["makerUsername"]),
            "-WorkflowId",
            workflow_array,
            "-TeamName",
            _powershell_literal(authorization["teamName"]),
        ]
    )
    if authorization.get("businessUnitId"):
        invocation += " -BusinessUnitId " + _powershell_literal(
            authorization["businessUnitId"]
        )
    for key, parameter in (
        ("authorizationId", "-ExpectedAuthorizationId"),
        ("teamId", "-ExpectedTeamId"),
    ):
        if authorization.get(key):
            invocation += f" {parameter} " + _powershell_literal(authorization[key])
    if preview:
        invocation += " -WhatIf"
    command = [shell, "-NoProfile", "-Command", invocation]
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        print(
            f"[ERROR] {script} failed in {realm}: "
            "execution did not finish within 10 minutes.",
            file=sys.stderr,
        )
        raise WorkdayConnectRuntimeError(
            "Delegated flow authorization did not finish within 10 minutes."
        ) from exc
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    failed = (
        result.returncode != 0
        or "[FAIL]" in output
        or "Dataverse authorization is in place." not in output
    )
    if failed and (
        _authorization_forbidden(output)
        or any(marker in _authorization_diagnostics(output) for marker in (
            "ndx_teamname_businessunitid", "wd-auth-team-name-conflict",
            "wd-auth-invalid-records",
        ))
    ):
        failure = _authorization_failure(output, preflight=preview)
        print(f"[ERROR] {script} failed in {realm}: {failure}", file=sys.stderr)
        raise failure
    if preview:
        try:
            return _classify_authorization_preview(
                plan,
                result.returncode,
                output,
                flow_names,
            )
        except WorkdayConnectRuntimeError as exc:
            next_action = (
                "Ask the Dataverse administrator to investigate the selected "
                "agent's authorization, then check Runtime again."
            )
            raise WorkdayConnectRuntimeError(
                f"{exc} No runtime changes were made. {next_action}",
                details={
                    "stage": "authorization-preflight",
                    "cause": "preview-unverified",
                    "nextAction": next_action,
                },
            ) from exc
    if failed:
        failure = _authorization_failure(output)
        print(
            f"[ERROR] {script} failed in {realm}: {failure}",
            file=sys.stderr,
        )
        raise failure
    print(
        f"[INFO] {script} completed in {realm}; Dataverse authorization "
        "was verified.",
        file=sys.stderr,
    )
    return {
        "outcome": "verified",
        "realm": plan["scope"]["realm"],
        "teamName": authorization["teamName"],
        "workflowCount": len(workflow_ids),
    }


def _classify_authorization_preview(
    plan: Mapping[str, Any],
    returncode: int,
    output: str,
    flow_names: list[str],
) -> dict[str, Any]:
    normalized = output.casefold()
    normalized_lines = [
        " ".join(line.casefold().split()) for line in output.splitlines()
    ]
    authorization = plan["delegatedAuthorization"]
    workflow_ids = [
        str(value).casefold()
        for value in authorization.get("workflowIds") or []
    ]
    authorization_create = "would create delegatedauthorization" in normalized
    authorization_reuse = any(
        line.startswith("[reuse] delegatedauthorization ")
        for line in normalized_lines
    )
    team_create = "would create access team" in normalized
    team_reuse = any(
        line.startswith("[reuse] team ") for line in normalized_lines
    )
    if not (authorization_create or authorization_reuse):
        raise WorkdayConnectRuntimeError(
            "Delegated authorization preview could not prove the exact "
            "authorization record."
        )
    if not (team_create or team_reuse):
        raise WorkdayConnectRuntimeError(
            "Delegated authorization preview could not prove the exact access "
            "team."
        )

    planned_workflow_ids: set[str] = set()
    for workflow_id, flow_name in zip(workflow_ids, flow_names, strict=True):
        share_create = f"would share '{flow_name.casefold()}' with the team"
        share_reuse = f"'{flow_name.casefold()}' already shared with the team"
        if share_create in normalized:
            planned_workflow_ids.add(workflow_id)
        elif share_reuse not in normalized:
            raise WorkdayConnectRuntimeError(
                "Delegated authorization preview did not account for every "
                "reviewed Workday flow."
            )

    unexpected_failures = []
    expected_failure_count = 0
    for line in output.splitlines():
        lowered = line.casefold()
        if "[fail]" not in lowered:
            continue
        if (
            "getteamsforbotid returned 0 teams" in lowered
            and (authorization_create or team_create)
        ):
            expected_failure_count += 1
            continue
        if "verification failed - see [fail] lines above" in lowered:
            continue
        if any(
            workflow_id in lowered
            and "is not shared with the team with writeaccess" in lowered
            and workflow_id in planned_workflow_ids
            for workflow_id in workflow_ids
        ):
            expected_failure_count += 1
            continue
        unexpected_failures.append(line.strip())
    unsafe_markers = (
        "unauthorized",
        "access denied",
        "permission denied",
    )
    if unexpected_failures or _authorization_forbidden(output) or any(
        marker in _authorization_diagnostics(output) for marker in unsafe_markers
    ):
        raise WorkdayConnectRuntimeError(
            "Delegated authorization preview reported an unsafe or "
            "ambiguous target state."
        )

    changes_required = bool(
        authorization_create or team_create or planned_workflow_ids
    )
    success_marker = "dataverse authorization is in place." in normalized
    if changes_required:
        recognized_whatif_failure = (
            returncode == 1
            and expected_failure_count > 0
            and "verification failed - see [fail] lines above" in normalized
        )
        if not (
            returncode == 0 and success_marker
            or recognized_whatif_failure
        ):
            raise WorkdayConnectRuntimeError(
                "Delegated authorization preview did not return a recognized "
                "safe WhatIf result."
            )
        outcome = "changes-required"
    elif returncode == 0 and success_marker:
        outcome = "already-configured"
    else:
        raise WorkdayConnectRuntimeError(
            "Delegated authorization preview did not return a recognized "
            "safe result."
        )
    return {
        "outcome": outcome,
        "realm": plan["scope"]["realm"],
        "teamName": authorization["teamName"],
        "workflowCount": len(workflow_ids),
        "changesRequired": changes_required,
    }


def _require_approved_flow_targets(
    flows: Mapping[str, Mapping[str, Any]],
    targets: list[Mapping[str, Any]],
) -> None:
    changed = [
        str(target["name"])
        for target in targets
        if str(flows[str(target["name"])].get("workflowid") or "").casefold()
        != str(target["workflowId"]).casefold()
    ]
    if changed:
        raise WorkdayConnectRuntimeError(
            "Reviewed Workday flow identity changed after approval: "
            + ", ".join(sorted(changed))
        )


def _record_runtime_stage(
    stages: list[str],
    action: str,
    evidence: Mapping[str, Any],
    recorder: Callable[[str, Mapping[str, Any]], Any] | None,
) -> None:
    if recorder is not None:
        recorder(action, evidence)
    stages.append(action)


def _apply_connection_binding_stage(
    plan: Mapping[str, Any],
    *,
    token: str,
    query: Callable[..., list[dict[str, Any]]],
    updater: Callable[..., bool],
) -> dict[str, str]:
    environment_url = plan["scope"]["dataverseUrl"]
    targets = plan["connectionBindings"]
    bindings = {
        logical_name: target["connectionId"] for logical_name, target in targets.items()
    }
    references = _runtime_references(
        environment_url,
        token,
        list(bindings),
        query=query,
    )
    for logical_name, target_id in bindings.items():
        if (
            str(references[logical_name].get("connectionid") or "").casefold()
            == str(target_id).casefold()
        ):
            continue
        updater(
            environment_url,
            token,
            "connectionreferences",
            _required_text(
                references[logical_name],
                "connectionreferenceid",
                f"Connection reference ID for {logical_name}",
            ),
            {"connectionid": target_id},
        )
    verified = _runtime_references(
        environment_url,
        token,
        list(bindings),
        query=query,
    )
    wrong = [
        name
        for name, target_id in bindings.items()
        if str(verified[name].get("connectionid") or "").casefold()
        != str(target_id).casefold()
    ]
    if wrong:
        raise WorkdayConnectRuntimeError(
            "Connection-reference verification failed: " + ", ".join(sorted(wrong))
        )
    return {
        logical_name: target["displayName"] for logical_name, target in targets.items()
    }


def _apply_flow_activation_stage(
    plan: Mapping[str, Any],
    *,
    token: str,
    query: Callable[..., list[dict[str, Any]]],
    updater: Callable[..., bool],
) -> list[str]:
    environment_url = plan["scope"]["dataverseUrl"]
    targets = plan["flows"]
    flow_names = [value["name"] for value in targets]
    approved_ids = {value["workflowId"].casefold() for value in targets}
    flows = _runtime_flows(
        environment_url,
        token,
        flow_names,
        approved_ids,
        query=query,
    )
    _require_approved_flow_targets(flows, targets)
    for target in targets:
        flow = flows[target["name"]]
        if (
            flow.get("statecode") == ACTIVE_FLOW_STATE
            and flow.get("statuscode") == ACTIVE_FLOW_STATUS
        ):
            continue
        updater(
            environment_url,
            token,
            "workflows",
            target["workflowId"],
            {
                "statecode": ACTIVE_FLOW_STATE,
                "statuscode": ACTIVE_FLOW_STATUS,
            },
        )
    verified = _runtime_flows(
        environment_url,
        token,
        flow_names,
        approved_ids,
        query=query,
    )
    _require_approved_flow_targets(verified, targets)
    inactive = [
        name
        for name, row in verified.items()
        if row.get("statecode") != ACTIVE_FLOW_STATE
        or row.get("statuscode") != ACTIVE_FLOW_STATUS
    ]
    if inactive:
        raise WorkdayConnectRuntimeError(
            "Runtime flow verification failed: " + ", ".join(sorted(inactive))
        )
    return flow_names


def apply_runtime_plan(
    plan: Mapping[str, Any],
    *,
    token: str,
    query: Callable[..., list[dict[str, Any]]] = query_all,
    updater: Callable[..., bool] = update_record,
    authorization_runner: Callable[..., subprocess.CompletedProcess] = _default_runner,
    stage_recorder: Callable[[str, Mapping[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Apply and verify ordered idempotent stages with one Dataverse token."""
    authorization = plan["delegatedAuthorization"]
    current = _authorization_target(
        plan["scope"]["dataverseUrl"], token,
        plan["scope"]["realm"], authorization["botId"], query=query,
    )
    if any(
        current[key] != authorization[key]
        for key in ("teamName", "businessUnitId")
    ) or any(
        authorization[key] is not None and current[key] != authorization[key]
        for key in ("authorizationId", "teamId")
    ):
        raise _authorization_preflight_failure(
            "Authorization ownership changed after approval.",
            "Refresh the runtime plan and approve the verified target before "
            "applying any changes.",
        )
    verified_stages: list[str] = []
    connection_bindings = _apply_connection_binding_stage(
        plan,
        token=token,
        query=query,
        updater=updater,
    )
    _record_runtime_stage(
        verified_stages,
        "connection-references-bound",
        {"outcome": "verified", "provenance": "Dataverse reread"},
        stage_recorder,
    )

    flow_names = _apply_flow_activation_stage(
        plan,
        token=token,
        query=query,
        updater=updater,
    )
    _record_runtime_stage(
        verified_stages,
        "runtime-flows-active",
        {"outcome": "verified", "provenance": "Dataverse reread"},
        stage_recorder,
    )

    authorization = _run_authorization(plan, runner=authorization_runner)
    _record_runtime_stage(
        verified_stages,
        "delegated-authorization-configured",
        {"outcome": "verified", "provenance": "authorization script"},
        stage_recorder,
    )

    return {
        "verified": True,
        "verifiedStages": verified_stages,
        "connectionBindings": connection_bindings,
        "flows": flow_names,
        "delegatedAuthorization": authorization,
    }
