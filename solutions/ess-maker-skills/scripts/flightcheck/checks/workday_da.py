# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Independent Workday readiness checks for the selected ESS HR DA.

Shared Workday checks remain reusable diagnostics. This module owns the
DA-specific package, runtime-flow, delegated-authorization, topic, wiring, and
employee-test evidence contracts used by the Workday DA profiles.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote
import uuid

import requests

from agentbuilder import AgentBuilderError
from auth import (
    AuthExpiredError,
    dataverse_get,
    query_all,
)
from http_errors import APIError
from minimalbot_evaluation import (
    blocking_diagnostics,
    reviewed_workday_topic_schemas,
)
from workday_connect_model import (
    WorkdayConnectModelError,
    load_catalog,
)

from ..agent_scope import active_agent, validate_agent_slug
from ..runner import CheckResult, Priority, Role, Status


_DA_IT_PARENT_SCHEMA = "msdyn_copilotforemployeeselfservicedait"
_WORKDAY_CATALOG_PATH = (
    Path(__file__).resolve().parents[2] / "workday_connect_catalog.json"
)
_DA_IT_AGENT_SCHEMAS = {
    _DA_IT_PARENT_SCHEMA,
    "gptagent_copilotforemployeeselfserviceit",
}

_SOLN_SELECT = "solutionid,uniquename,friendlyname,ismanaged,version"

_DOC_LINK = (
    "https://learn.microsoft.com/en-us/microsoft-365/copilot/"
    "employee-self-service/install"
)
_DESCRIPTION = "Workday extension package installed for the DA ESS HR agent"


def _safe_error_summary(exc: Exception) -> str:
    """Return a stable error summary without backend response text."""
    if isinstance(exc, ValueError):
        return str(exc)
    status_code = getattr(
        getattr(exc, "response", None),
        "status_code",
        None,
    )
    status_hint = (
        f" (HTTP {status_code})" if status_code is not None else ""
    )
    return f"{type(exc).__name__}{status_hint}"


def run_workday_da_checks(runner) -> list[CheckResult]:
    """Emit every independent DA-specific Workday validation row."""
    checks = (
        ("WD-DA-PKG-001", _check_workday_da_package_installed),
        ("WD-DA-FLOW-001", _check_runtime_flow_catalog),
        ("WD-DA-AUTH-001", _check_delegated_flow_authorization),
        ("WD-DA-TOPIC-001", _check_reviewed_workday_topics),
        ("WD-DA-WIRING-001", _check_runtime_template_wiring),
        ("WD-DA-ATTACH-001", _check_agent_flow_attachment),
        ("WD-DA-RUN-001", _check_correlated_runtime_evidence),
    )
    results: list[CheckResult] = []
    should_execute = getattr(runner, "should_execute", lambda _id: True)
    for checkpoint_id, check in checks:
        if should_execute(checkpoint_id):
            results.extend(check(runner))
    return results


def run_workday_da_package_check(runner) -> list[CheckResult]:
    """Preserve the legacy package-only ``workdayda`` scope contract."""
    return _check_workday_da_package_installed(runner)


def _check_workday_da_package_installed(runner) -> list[CheckResult]:
    """WD-DA-PKG-001: the DA Workday extension package is installed.

    Always emits exactly one CheckResult (principle 7 — bucket multi-resource
    findings). API errors remain explicit errors rather than success-shaped
    manual guidance.
    """
    env_url = getattr(runner, "env_url", None)
    token = getattr(runner, "dv_token", None)

    if not env_url or not token:
        return [_result(
            Status.SKIPPED.value,
            "Dataverse URL or access token not available in this run.",
        )]

    selected = _selected_agent(runner)
    if selected is None:
        return [_result(
            Status.FAILED.value,
            "The selected agent identity could not be resolved from the "
            "workspace configuration.",
            remediation=(
                "Select the intended ESS DA HR agent, refresh the local "
                "workspace configuration, and rerun this checkpoint with its "
                "--agent-slug value."
            ),
        )]

    selected_slug, selected_agent = selected
    selected_schema = str(
        selected_agent.get("schemaName")
        or selected_agent.get("schema_name")
        or ""
    ).casefold()
    if selected_schema in _DA_IT_AGENT_SCHEMAS:
        return [_result(
            Status.FAILED.value,
            f"The selected agent '{selected_slug}' is the ESS DA IT agent.",
            remediation=(
                "Workday integration with the ESS IT Agent is not supported "
                "in this release. Select the ESS HR Agent first."
            ),
        )]
    try:
        catalog = load_catalog(_WORKDAY_CATALOG_PATH)
    except WorkdayConnectModelError as exc:
        return [_result(
            Status.ERROR.value,
            str(exc),
            remediation="Restore the reviewed Workday connect catalog.",
        )]
    supported_agents = catalog.get("supportedAgents")
    supported_agents = (
        supported_agents if isinstance(supported_agents, dict) else {}
    )
    agent_contract = supported_agents.get(selected_schema)
    if not isinstance(agent_contract, dict):
        return [_result(
            Status.FAILED.value,
            f"The selected agent '{selected_slug}' is not a supported ESS DA "
            "HR agent.",
            remediation=(
                "Select the installed ESS DA HR agent and rerun this "
                "checkpoint. Do not use environment-wide package presence as "
                "a substitute for selected-agent identity."
            ),
        )]
    package_flavor = str(
        agent_contract.get("packageFlavor") or ""
    ).strip()
    packages = catalog.get("packages")
    packages = packages if isinstance(packages, dict) else {}
    package_contract = packages.get(package_flavor)
    if not isinstance(package_contract, dict):
        return [_result(
            Status.ERROR.value,
            "The selected agent's Workday package flavor is missing from the "
            "reviewed catalog.",
            remediation="Restore the reviewed Workday connect catalog.",
        )]
    required_schema = str(
        package_contract.get("solutionSchemaName") or ""
    ).strip()
    if not required_schema:
        return [_result(
            Status.ERROR.value,
            "The reviewed Workday package contract has no solution schema.",
            remediation="Restore the reviewed Workday connect catalog.",
        )]

    try:
        solution_filter = f"uniquename eq '{required_schema}'"
        all_solutions = query_all(
            env_url, token,
            "solutions",
            _SOLN_SELECT,
            solution_filter,
        )
    except AuthExpiredError as e:
        return [_result(
            Status.ERROR.value,
            _safe_error_summary(e),
            remediation="Re-run FlightCheck to refresh the access token.",
        )]
    except (APIError, OSError, ValueError) as e:
        return [_result(
            Status.ERROR.value,
            f"Unable to verify the DA Workday package: "
            f"{_safe_error_summary(e)}",
            remediation=(
                "Inspect the error above; common causes are insufficient "
                "Dataverse privileges on the solutions table (typically "
                "surfaces as HTTP 403) or a transient platform error (HTTP 5xx)."
            ),
        )]

    installed_names = {
        s.get("uniquename", "").casefold(): s for s in all_solutions
    }

    child = installed_names.get(required_schema.casefold())
    if not child:
        return [_result(
            Status.FAILED.value,
            "The Workday package required by the ESS HR agent is not "
            "installed.",
            remediation=(
                "Run /connect workday to install the required Workday package "
                "in this environment, then re-run this check."
            ),
        )]

    return [_result(
        Status.PASSED.value,
        f"Selected ESS HR agent '{selected_slug}' detected. Workday package "
        "installed: "
        f"{_describe_solution(child)}.",
    )]


def _selected_agent(runner) -> tuple[str, dict] | None:
    """Resolve the exact selected agent without environment-wide inference."""
    config = getattr(runner, "config", {}) or {}
    if not isinstance(config, dict):
        return None

    legacy_agent = config.get("agent")
    legacy_agent = legacy_agent if isinstance(legacy_agent, dict) else {}
    slug = (
        getattr(runner, "agent_slug", None)
        or config.get("activeAgent")
        or legacy_agent.get("slug")
    )
    if not slug:
        return None
    try:
        selected_slug = validate_agent_slug(str(slug))
    except ValueError:
        return None

    selected = active_agent(config, selected_slug)
    return (selected_slug, selected) if selected else None


def _result(status: str, result: str, remediation: str = "") -> CheckResult:
    return CheckResult(
        roles=[Role.ESS_MAKER.value],
        checkpoint_id="WD-DA-PKG-001",
        category="Workday DA",
        priority=Priority.CRITICAL.value,
        status=status,
        description=_DESCRIPTION,
        result=result,
        remediation=remediation,
        doc_link=_DOC_LINK,
    )


def _describe_solution(sol: dict) -> str:
    """Render one solution row as ``uniquename (vX.Y.Z)`` for the result text."""
    name = sol.get("uniquename", "<unknown>")
    version = sol.get("version")
    return f"{name} (v{version})" if version else name


def _load_runtime_contract() -> dict[str, Any]:
    try:
        catalog = load_catalog(_WORKDAY_CATALOG_PATH)
    except WorkdayConnectModelError as exc:
        raise ValueError(
            f"Workday runtime catalog could not be loaded: {exc}"
        ) from exc
    runtime = (catalog.get("packages") or {}).get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError(
            "Workday runtime catalog does not define packages.runtime."
        )
    for field_name in ("flowNames", "agentConnectionFlowNames"):
        values = runtime.get(field_name)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise ValueError(
                f"Workday runtime catalog field {field_name} is invalid."
            )
    return runtime


def _flow_name(flow: dict[str, Any]) -> str:
    return str(flow.get("name") or "")


def _flow_id(flow: dict[str, Any]) -> str:
    return str(flow.get("workflowid") or "").strip()


def _flow_is_active(flow: dict[str, Any]) -> bool:
    return flow.get("statecode") == 1 and flow.get("statuscode") == 2


def _runtime_flow_inventory(
    runner,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    runtime = _load_runtime_contract()
    env_url = str(getattr(runner, "env_url", "") or "")
    token = str(getattr(runner, "dv_token", "") or "")
    if not env_url or not token:
        raise ValueError(
            "Dataverse access is unavailable for runtime-flow verification."
        )
    expected = list(runtime["flowNames"])
    flow_filter = " or ".join(
        "name eq '" + name.replace("'", "''") + "'" for name in expected
    )
    flows = getattr(runner, "_workday_runtime_flows", None)
    if not isinstance(flows, list):
        flows = query_all(
            env_url,
            token,
            "workflows",
            "workflowid,name,statecode,statuscode,category",
            flow_filter,
        )
    by_name: dict[str, list[dict[str, Any]]] = {}
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        name = _flow_name(flow)
        if name:
            by_name.setdefault(name.casefold(), []).append(flow)
    return runtime, by_name


def _da_result(
    checkpoint_id: str,
    status: str,
    description: str,
    result: str,
    *,
    remediation: str = "",
    roles: list[str] | None = None,
    priority: str = Priority.CRITICAL.value,
    automation_type: str = "automated",
    evidence: dict[str, Any] | None = None,
) -> CheckResult:
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category="Workday DA",
        priority=priority,
        status=status,
        description=description,
        result=result,
        remediation=remediation,
        doc_link=_DOC_LINK,
        roles=roles or [Role.ESS_MAKER.value],
        automation_type=automation_type,
        evidence=evidence or {},
    )


def _check_runtime_flow_catalog(runner) -> list[CheckResult]:
    checkpoint_id = "WD-DA-FLOW-001"
    description = "Reviewed Workday runtime flow catalog and active state"
    try:
        runtime, by_name = _runtime_flow_inventory(runner)
    except (
        AuthExpiredError,
        APIError,
        requests.RequestException,
        OSError,
        ValueError,
    ) as exc:
        return [_da_result(
            checkpoint_id,
            Status.ERROR.value,
            description,
            "Runtime-flow verification failed: " + _safe_error_summary(exc),
            remediation=(
                "Restore the reviewed catalog and Dataverse access, "
                "then rerun this checkpoint."
            ),
            roles=[Role.ESS_MAKER.value],
        )]

    expected = list(runtime["flowNames"])
    missing = [
        name for name in expected
        if not by_name.get(name.casefold())
    ]
    duplicates = [
        name for name in expected
        if len(by_name.get(name.casefold()) or []) > 1
    ]
    inactive = [
        name for name in expected
        if len(by_name.get(name.casefold()) or []) == 1
        and not _flow_is_active(by_name[name.casefold()][0])
    ]
    if missing or duplicates or inactive:
        findings = []
        if missing:
            findings.append("missing: " + ", ".join(sorted(missing)))
        if duplicates:
            findings.append("duplicates: " + ", ".join(sorted(duplicates)))
        if inactive:
            findings.append("inactive: " + ", ".join(sorted(inactive)))
        return [_da_result(
            checkpoint_id,
            Status.FAILED.value,
            description,
            "The reviewed Workday runtime flow catalog is not ready ("
            + "; ".join(findings)
            + ").",
            remediation=(
                "Install exactly one copy of every reviewed Workday runtime "
                "flow and activate each flow before continuing."
            ),
            roles=[Role.ESS_MAKER.value],
            evidence={
                "expectedFlowNames": expected,
                "missingFlowNames": missing,
                "duplicateFlowNames": duplicates,
                "inactiveFlowNames": inactive,
            },
        )]

    resolved: dict[str, str] = {}
    try:
        for name in expected:
            flow_id = str(uuid.UUID(_flow_id(by_name[name.casefold()][0])))
            if flow_id in resolved.values():
                raise ValueError(
                    "The reviewed runtime flow inventory contains duplicate "
                    "flow IDs."
                )
            resolved[name] = flow_id
    except ValueError as exc:
        return [_da_result(
            checkpoint_id,
            Status.ERROR.value,
            description,
            str(exc),
            remediation=(
                "Refresh the Dataverse workflow inventory and rerun this "
                "checkpoint."
            ),
            roles=[Role.ESS_MAKER.value],
        )]
    return [_da_result(
        checkpoint_id,
        Status.PASSED.value,
        description,
        f"All {len(expected)} reviewed Workday runtime flows are present "
        "exactly once and active.",
        roles=[Role.ESS_MAKER.value],
        evidence={"flows": resolved},
    )]


def _selected_agent_identity(
    runner,
) -> tuple[str, str, str] | None:
    selected = _selected_agent(runner)
    if selected is None:
        return None
    slug, agent = selected
    schema = str(
        agent.get("schemaName")
        or agent.get("schema_name")
        or ""
    ).strip()
    bot_id = str(
        agent.get("botId")
        or agent.get("cdsBotId")
        or agent.get("id")
        or ""
    ).strip()
    if not schema or not bot_id:
        return None
    try:
        bot_id = str(uuid.UUID(bot_id))
    except ValueError:
        return None
    return slug, schema, bot_id


def _check_delegated_flow_authorization(runner) -> list[CheckResult]:
    checkpoint_id = "WD-DA-AUTH-001"
    description = "Selected-agent delegated authorization for runtime flows"
    env_url = str(getattr(runner, "env_url", "") or "")
    token = str(getattr(runner, "dv_token", "") or "")
    if not env_url or not token:
        return [_da_result(
            checkpoint_id,
            Status.SKIPPED.value,
            description,
            "Dataverse access is unavailable, so delegated authorization "
            "could not be verified.",
            remediation="Authenticate to Dataverse and rerun.",
            roles=[Role.POWER_PLATFORM_ADMIN.value],
        )]
    identity = _selected_agent_identity(runner)
    if identity is None:
        return [_da_result(
            checkpoint_id,
            Status.FAILED.value,
            description,
            "The selected agent's schema and bot ID could not be resolved.",
            remediation=(
                "Refresh the selected ESS HR DA configuration and rerun with "
                "the intended --agent-slug."
            ),
            roles=[Role.ESS_MAKER.value],
        )]
    slug, _schema, bot_id = identity
    try:
        runtime, by_name = _runtime_flow_inventory(runner)
        flow_rows = []
        for name in runtime["agentConnectionFlowNames"]:
            matches = by_name.get(name.casefold()) or []
            if len(matches) != 1 or not _flow_id(matches[0]):
                raise ValueError(
                    f"Reviewed agent-facing flow {name!r} is missing or ambiguous."
                )
            try:
                workflow_id = str(uuid.UUID(_flow_id(matches[0])))
            except ValueError as exc:
                raise ValueError(
                    f"Reviewed agent-facing flow {name!r} has an invalid ID."
                ) from exc
            flow_rows.append((name, workflow_id))

        authorizations = query_all(
            env_url,
            token,
            "delegatedauthorizations",
            "delegatedauthorizationid,name,providertype,botid",
            f"botid eq '{bot_id}'",
        )
        authorization_id = ""
        if len(authorizations) == 1:
            try:
                authorization_id = str(uuid.UUID(str(
                    authorizations[0].get("delegatedauthorizationid") or ""
                )))
            except ValueError:
                authorization_id = ""
        teams = (
            query_all(
                env_url,
                token,
                "teams",
                "teamid,name,teamtype,_delegatedauthorizationid_value",
                f"_delegatedauthorizationid_value eq {authorization_id}",
            )
            if authorization_id
            else []
        )
    except (
        AuthExpiredError,
        APIError,
        requests.RequestException,
        OSError,
        ValueError,
    ) as exc:
        return [_da_result(
            checkpoint_id,
            Status.ERROR.value,
            description,
            "Delegated authorization verification failed: "
            f"{_safe_error_summary(exc)}",
            remediation=(
                "Restore Dataverse access and the reviewed runtime-flow "
                "inventory, then rerun this checkpoint."
            ),
            roles=[Role.POWER_PLATFORM_ADMIN.value],
        )]

    if (
        len(authorizations) != 1
        or authorizations[0].get("providertype") != 3
        or str(authorizations[0].get("botid") or "").casefold()
        != bot_id.casefold()
        or len(teams) != 1
        or teams[0].get("teamtype") != 1
    ):
        return [_da_result(
            checkpoint_id,
            Status.FAILED.value,
            description,
            "The selected agent does not resolve to exactly one MCSBot "
            "delegated authorization and one linked access team.",
            remediation=(
                "Run the reviewed delegated-authorization setup for this "
                "agent and remove duplicate or incorrectly typed records."
            ),
            roles=[Role.POWER_PLATFORM_ADMIN.value],
            evidence={
                "agentSlug": slug,
                "botId": bot_id,
                "delegatedAuthorizationCount": len(authorizations),
                "teamCount": len(teams),
            },
        )]

    try:
        team_id = str(uuid.UUID(str(teams[0].get("teamid") or "")))
    except ValueError:
        return [_da_result(
            checkpoint_id,
            Status.ERROR.value,
            description,
            "Dataverse returned an invalid delegated access-team ID.",
            remediation="Restore the delegated authorization and rerun.",
            roles=[Role.POWER_PLATFORM_ADMIN.value],
        )]
    missing_shares: list[str] = []
    try:
        for flow_name, workflow_id in flow_rows:
            target = quote(
                json.dumps({"@odata.id": f"workflows({workflow_id})"}),
                safe="",
            )
            payload = dataverse_get(
                env_url,
                token,
                "RetrieveSharedPrincipalsAndAccess"
                f"(Target=@t)?@t={target}",
            )
            accesses = payload.get("PrincipalAccesses")
            if not isinstance(accesses, list):
                raise ValueError(
                    "Dataverse returned an invalid shared-principals response."
                )
            authorized = False
            for access in accesses:
                if not isinstance(access, dict):
                    raise ValueError(
                        "Dataverse returned an invalid principal-access row."
                    )
                principal = access.get("Principal")
                if not isinstance(principal, dict):
                    raise ValueError(
                        "Dataverse returned an invalid principal record."
                    )
                if (
                    str(principal.get("ownerid") or "").casefold() == team_id
                    and "WriteAccess"
                    in str(access.get("AccessMask") or "")
                ):
                    authorized = True
                    break
            if not authorized:
                missing_shares.append(flow_name)
    except (
        AuthExpiredError,
        requests.RequestException,
        OSError,
        ValueError,
    ) as exc:
        return [_da_result(
            checkpoint_id,
            Status.ERROR.value,
            description,
            "Runtime-flow share verification failed: "
            f"{_safe_error_summary(exc)}",
            remediation=(
                "Restore Dataverse read access and rerun this checkpoint."
            ),
            roles=[Role.POWER_PLATFORM_ADMIN.value],
        )]

    if missing_shares:
        return [_da_result(
            checkpoint_id,
            Status.FAILED.value,
            description,
            "Delegated authorization is missing WriteAccess for: "
            + ", ".join(sorted(missing_shares))
            + ".",
            remediation=(
                "Run the reviewed delegated-authorization setup for each "
                "listed flow, then rerun."
            ),
            roles=[Role.POWER_PLATFORM_ADMIN.value],
            evidence={"missingFlowShares": missing_shares, "teamId": team_id},
        )]
    return [_da_result(
        checkpoint_id,
        Status.PASSED.value,
        description,
        f"The selected agent '{slug}' has one MCSBot access team with "
        f"WriteAccess on all {len(flow_rows)} reviewed agent-facing flows.",
        roles=[Role.POWER_PLATFORM_ADMIN.value],
        evidence={
            "agentSlug": slug,
            "botId": bot_id,
            "teamId": team_id,
            "flowIds": [flow_id for _name, flow_id in flow_rows],
        },
    )]


def _dialog_components(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    changes = payload.get("botComponentChanges")
    if not isinstance(changes, list):
        raise ValueError(
            "AgentBuilder component response has no botComponentChanges list."
        )
    components: dict[str, list[dict[str, Any]]] = {}
    for change in changes:
        if not isinstance(change, dict):
            continue
        component = change.get("component")
        if (
            not isinstance(component, dict)
            or component.get("$kind") != "DialogComponent"
        ):
            continue
        schema = str(component.get("schemaName") or "").strip()
        if schema:
            components.setdefault(schema.casefold(), []).append(component)
    return components


def _fetch_selected_components(
    runner,
) -> tuple[str, str, str, dict[str, list[dict[str, Any]]]]:
    identity = _selected_agent_identity(runner)
    if identity is None:
        raise ValueError(
            "The selected agent's schema and bot ID could not be resolved."
        )
    client = getattr(runner, "agentbuilder", None)
    if client is None:
        raise RuntimeError("AgentBuilder client is unavailable.")
    slug, schema, bot_id = identity
    cache = getattr(runner, "_workday_da_component_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        runner._workday_da_component_cache = cache
    components = cache.get(bot_id)
    if components is None:
        payload = client.fetch_components(bot_id)
        components = _dialog_components(payload)
        cache[bot_id] = components
    return slug, schema, bot_id, components


def _check_reviewed_workday_topics(runner) -> list[CheckResult]:
    checkpoint_id = "WD-DA-TOPIC-001"
    description = "Reviewed OOB Workday topic inventory and active state"
    if getattr(runner, "agentbuilder", None) is None:
        return [_da_result(
            checkpoint_id,
            Status.SKIPPED.value,
            description,
            "AgentBuilder access is unavailable, so live Workday topics "
            "could not be verified.",
            remediation="Authenticate to AgentBuilder and rerun.",
        )]
    try:
        slug, schema, _bot_id, components = _fetch_selected_components(runner)
        expected = reviewed_workday_topic_schemas(schema)
        if not expected:
            raise ValueError(
                f"No reviewed Workday topic inventory exists for {schema!r}."
            )
    except (
        AgentBuilderError,
        requests.RequestException,
        RuntimeError,
        ValueError,
    ) as exc:
        return [_da_result(
            checkpoint_id,
            Status.ERROR.value,
            description,
            _safe_error_summary(exc),
            remediation=(
                "Select the supported ESS HR DA and restore live component "
                "access, then rerun."
            ),
        )]

    missing: list[str] = []
    duplicates: list[str] = []
    inactive: list[str] = []
    diagnostics: list[str] = []
    for expected_schema in sorted(expected):
        matches = components.get(expected_schema.casefold()) or []
        if not matches:
            missing.append(expected_schema)
            continue
        if len(matches) != 1:
            duplicates.append(expected_schema)
            continue
        component = matches[0]
        if str(component.get("status") or "").casefold() != "active":
            inactive.append(expected_schema)
        if blocking_diagnostics(component):
            diagnostics.append(expected_schema)
    if missing or duplicates or inactive:
        findings = []
        for label, values in (
            ("missing", missing),
            ("duplicates", duplicates),
            ("inactive", inactive),
        ):
            if values:
                findings.append(f"{label}: {', '.join(values)}")
        return [_da_result(
            checkpoint_id,
            Status.FAILED.value,
            description,
            "The reviewed OOB Workday topic inventory is not ready ("
            + "; ".join(findings)
            + ").",
            remediation=(
                "Restore the Microsoft-shipped Workday topics, activate each "
                "topic, resolve blocking diagnostics, and rerun."
            ),
            evidence={
                "expected": len(expected),
                "missing": missing,
                "duplicates": duplicates,
                "inactive": inactive,
                "blockingDiagnostics": diagnostics,
            },
        )]
    return [_da_result(
        checkpoint_id,
        Status.PASSED.value,
        description,
        f"All {len(expected)} reviewed OOB Workday topics are present exactly "
        f"once and active for '{slug}'. Dependency diagnostics are retained "
        "as evidence but do not determine topic activation state.",
        evidence={
            "expected": len(expected),
            "verified": len(expected),
            "diagnosticTopics": diagnostics,
        },
    )]


def _begin_dialog_target(action: dict[str, Any]) -> str:
    target = action.get("dialog")
    if isinstance(target, str):
        return target.strip()
    if isinstance(target, dict):
        return str(
            target.get("literalValue")
            or target.get("expressionText")
            or target.get("value")
            or ""
        ).strip()
    return ""


def _begin_dialog_targets(value: Any) -> list[str]:
    targets: list[str] = []
    if isinstance(value, dict):
        kind = str(value.get("$kind") or value.get("kind") or "")
        if kind == "BeginDialog":
            target = _begin_dialog_target(value)
            if target:
                targets.append(target)
        for child in value.values():
            targets.extend(_begin_dialog_targets(child))
    elif isinstance(value, list):
        for child in value:
            targets.extend(_begin_dialog_targets(child))
    return targets


def _single_component(
    components: dict[str, list[dict[str, Any]]],
    schema: str,
) -> dict[str, Any]:
    matches = components.get(schema.casefold()) or []
    if len(matches) != 1:
        raise ValueError(
            f"Live component {schema!r} is missing or duplicated."
        )
    return matches[0]


def _check_runtime_template_wiring(runner) -> list[CheckResult]:
    checkpoint_id = "WD-DA-WIRING-001"
    description = "Conversation Start to Workday runtime-template wiring"
    if getattr(runner, "agentbuilder", None) is None:
        return [_da_result(
            checkpoint_id,
            Status.SKIPPED.value,
            description,
            "AgentBuilder access is unavailable, so live topic wiring could "
            "not be verified.",
            remediation="Authenticate to AgentBuilder and rerun.",
        )]
    try:
        _slug, schema, _bot_id, components = _fetch_selected_components(runner)
        conversation_schema = f"{schema}.topic.ConversationStart"
        runtime_schema = (
            f"{schema}.topic."
            "WorkdaySystemSetRuntimeTemplateConfigurations"
        )
        user_context_schema = (
            f"{schema}.topic.WorkdaySystemGetUserContextV2"
        )
        validation_schema = (
            f"{schema}.topic.System-UserContext-Validate"
        )
        conversation = _single_component(components, conversation_schema)
        runtime = _single_component(components, runtime_schema)
        user_context = _single_component(components, user_context_schema)
        begin_dialog = (conversation.get("dialog") or {}).get("beginDialog")
        actions = (
            begin_dialog.get("actions")
            if isinstance(begin_dialog, dict)
            else None
        )
        all_targets = _begin_dialog_targets(conversation.get("dialog"))
        top_level_targets = [
            _begin_dialog_target(action)
            if (
                isinstance(action, dict)
                and str(action.get("$kind") or action.get("kind"))
                == "BeginDialog"
            )
            else ""
            for action in actions or []
        ]
        validation_positions = [
            index
            for index, target in enumerate(top_level_targets)
            if target == validation_schema
        ]
        runtime_precedes_validation = (
            len(validation_positions) == 1
            and validation_positions[0] > 0
            and top_level_targets[validation_positions[0] - 1]
            == runtime_schema
        )
        user_context_targets = _begin_dialog_targets(
            user_context.get("dialog")
        )
        diagnostics = (
            blocking_diagnostics(conversation)
            + blocking_diagnostics(runtime)
            + blocking_diagnostics(user_context)
        )
        inactive_components = [
            component_schema
            for component_schema, component in (
                (conversation_schema, conversation),
                (runtime_schema, runtime),
                (user_context_schema, user_context),
            )
            if str(component.get("status") or "").casefold() != "active"
        ]
    except (
        AgentBuilderError,
        requests.RequestException,
        RuntimeError,
        ValueError,
    ) as exc:
        return [_da_result(
            checkpoint_id,
            Status.ERROR.value,
            description,
            _safe_error_summary(exc),
            remediation=(
                "Restore the reviewed live topic components and rerun."
            ),
        )]

    if (
        all_targets.count(runtime_schema) != 1
        or not runtime_precedes_validation
        or runtime_schema in user_context_targets
        or inactive_components
    ):
        return [_da_result(
            checkpoint_id,
            Status.FAILED.value,
            description,
            "Conversation Start must call the Workday runtime-template topic "
            "exactly once immediately before User Context Validate; User "
            "Context V2 must not call it, and all three topics must be active.",
            remediation=(
                "Restore the reviewed Conversation Start initialization chain "
                "and remove the obsolete User Context V2 nested call."
            ),
            evidence={
                "runtimeTargetCount": all_targets.count(runtime_schema),
                "runtimePrecedesValidation": runtime_precedes_validation,
                "validationTargetCount": len(validation_positions),
                "userContextContainsTarget": (
                    runtime_schema in user_context_targets
                ),
                "blockingDiagnostics": diagnostics,
                "inactiveComponents": inactive_components,
            },
        )]
    return [_da_result(
        checkpoint_id,
        Status.PASSED.value,
        description,
        "Conversation Start initializes Workday runtime templates exactly "
        "once immediately before User Context Validate, and User Context V2 "
        "has no obsolete nested initialization. All three topics are active; "
        "dependency diagnostics are retained for runtime validation.",
        evidence={
            "conversationStart": conversation_schema,
            "runtimeTemplate": runtime_schema,
            "userContext": user_context_schema,
            "blockingDiagnostics": diagnostics,
        },
    )]


def _check_agent_flow_attachment(runner) -> list[CheckResult]:
    try:
        runtime = _load_runtime_contract()
    except ValueError as exc:
        return [_da_result(
            "WD-DA-ATTACH-001",
            Status.ERROR.value,
            "Reviewed Workday flows exposed to the selected agent",
            str(exc),
            remediation="Restore the reviewed Workday runtime catalog.",
        )]
    flow_names = list(runtime["agentConnectionFlowNames"])
    return [_da_result(
        "WD-DA-ATTACH-001",
        Status.MANUAL.value,
        "Reviewed Workday flows exposed to the selected agent",
        "The reviewed agent-facing flow contract contains exactly: "
        + ", ".join(flow_names)
        + ". FlightCheck has no validated read-only API that proves the "
        "maker UI attachment and parameter-sharing toggle.",
        remediation=(
            "In Copilot Studio, open the selected ESS HR agent's Workday "
            "connection settings. Confirm exactly the listed flows are "
            "attached and 'Allow permission to share parameters' is enabled "
            "for every exposed connection."
        ),
        priority=Priority.HIGH.value,
        automation_type="manual",
        evidence={"expectedFlowNames": flow_names},
    )]


def _check_correlated_runtime_evidence(_runner) -> list[CheckResult]:
    return [_da_result(
        "WD-DA-RUN-001",
        Status.NOT_CONFIGURED.value,
        "Retired employee runtime-evidence correlation",
        "Bounded Power Automate run-history windows cannot prove which "
        "conversation initiated a run and are no longer accepted as Workday "
        "scenario evidence.",
        remediation=(
            "Complete the guided lifecycle with a successful maker scenario "
            "in the Copilot Studio Test pane. Publishing and non-maker "
            "validation are post-skill activities."
        ),
        automation_type="passive",
    )]
