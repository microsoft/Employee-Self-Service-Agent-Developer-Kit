# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Consolidated preview, apply, and verification for Workday runtime wiring."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping

from auth import authenticate, query_all, update_record
from install_workday_da_extension import (
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
REALM_TEAM_NAMES = {
    realm: f"ESS DA HR Workday - {display_name}"
    for realm, display_name in REALM_DISPLAY_NAMES.items()
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
        raise WorkdayConnectRuntimeError(
            "PAC could not list the target environment's connections."
        )
    try:
        payload = json.loads(result.stdout or "")
    except json.JSONDecodeError as exc:
        raise WorkdayConnectRuntimeError(
            "PAC returned invalid connection inventory JSON."
        ) from exc
    values = payload.get("value")
    if not isinstance(values, list):
        raise WorkdayConnectRuntimeError(
            "PAC connection inventory did not contain a value array."
        )
    return [value for value in values if isinstance(value, dict)]


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


def _build_runtime_discovery(
    context: Mapping[str, Any],
    *,
    workday: Mapping[str, Any],
    dataverse: Mapping[str, Any],
    references: Mapping[str, Mapping[str, Any]],
    flows: Mapping[str, Mapping[str, Any]],
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
            "teamName": REALM_TEAM_NAMES[context["realm"]],
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
            "authorizationTeamName": REALM_TEAM_NAMES[context["realm"]],
        },
        "observed": observed,
    }


def discover_runtime_plan(
    state: Mapping[str, Any],
    *,
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
    context = _runtime_discovery_context(state, catalog)
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
    workday_connection_id: str | None = None,
    dataverse_connection_id: str | None = None,
    catalog: Mapping[str, Any] | None = None,
    pac_resolver: Callable[[], Path] = resolve_pac_executable,
    pac_auth: Callable[..., Any] = ensure_pac_auth,
    runner: Callable[..., subprocess.CompletedProcess] = _default_runner,
) -> dict[str, Any]:
    """Verify selected Workday and Dataverse connections from live state."""
    try:
        context = _runtime_discovery_context(state, catalog)
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
    if preview:
        return _classify_authorization_preview(
            plan,
            result.returncode,
            output,
            flow_names,
        )
    if (
        result.returncode != 0
        or "[FAIL]" in output
        or "Dataverse authorization is in place." not in output
    ):
        normalized = output.casefold()
        if "403" in normalized or "forbidden" in normalized:
            evidence = (
                "The authorization script received an explicit forbidden "
                "response from Dataverse."
            )
        elif "multiple" in normalized:
            evidence = (
                "The authorization script found ambiguous existing "
                "authorization records."
            )
        elif "[fail]" in normalized:
            evidence = "The authorization script emitted an explicit [FAIL] result."
        else:
            evidence = (
                f"The authorization script exited with code "
                f"{result.returncode} without its success marker."
            )
        print(
            f"[ERROR] {script} failed in {realm}: {evidence}",
            file=sys.stderr,
        )
        raise WorkdayConnectRuntimeError(
            f"Delegated flow authorization failed in {realm}. {evidence}"
        )
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
        "403",
        "forbidden",
        "unauthorized",
        "access denied",
        "permission denied",
    )
    if unexpected_failures or any(
        marker in normalized for marker in unsafe_markers
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
