# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Selected-agent setup diagnostics, not deployment approval or employee tests."""

from dataclasses import asdict
from functools import partial
from pathlib import Path
from types import SimpleNamespace
import subprocess
import uuid

import requests

from agentbuilder import (
    AgentBuilderClient, AgentBuilderError, ConnectivityClient, DEFAULT_API_VERSION,
    DEFAULT_TOKEN_CACHE, authenticate_flightcheck, authenticate_flightcheck_dependency,
    derive_environment_host, environment_id_from_host, ring_from_environment_host,
    validate_environment_host,
)

from .agent_scope import active_agent, validate_agent_slug
from .checks._connection_dependencies import _Access, _sap_only_topic, audit_connections
from .checks.environment import _env004_workday_configured
from .checks.local_files import run_da_local_file_checks
from .checks.maker_integrations import run_optional_integration_checks
from .checks.native_agent import run_native_agent_checks
from .checks.workday_da import _check_agent_flow_attachment, run_workday_da_checks
from .checks.workday_extension import _check_dv_connection, _check_user_context_redirect
from .runner import (
    BLOCK_REASON_CHECKPOINT_CONTRACT, CheckResult, FlightCheckRunner, Priority,
    Role, RunResult, Status, maker_diagnostic_outcome,
)


def _result(key, status, description, finding, remediation="", *, evidence=None):
    return CheckResult(
        key, "Agent setup", Priority.HIGH.value, status, description, finding, remediation,
        roles=[Role.ESS_MAKER.value, Role.POWER_PLATFORM_ADMIN.value],
        evidence=evidence or {},
        block_reason=BLOCK_REASON_CHECKPOINT_CONTRACT if status == Status.BLOCKED.value else "",
    )


def _configure(runner, args):
    selected = active_agent(runner.config, runner.agent_slug)
    validate_agent_slug(selected.get("slug"))
    agent_id = str(uuid.UUID(str(selected.get("botId") or "")))
    env_id = str(uuid.UUID(str(args.environment_id or runner.config.get("environmentId") or "")))
    configured_id = runner.config.get("environmentId")
    if configured_id and str(uuid.UUID(str(configured_id))) != env_id:
        raise ValueError("The requested environment differs from the selected agent's configured environment.")
    configured_tenant = runner.config.get("tenantId")
    if configured_tenant and args.tenant_id and (
        str(uuid.UUID(str(configured_tenant))) != str(uuid.UUID(str(args.tenant_id)))
    ):
        raise ValueError("The requested tenant differs from the configured environment.")
    host = runner.config.get("powerPlatformApiEndpoint")
    ring = ring_from_environment_host(host) if host else args.ring or runner.config.get("ring") or "prod"
    if args.ring and args.ring != ring:
        raise ValueError("The requested service ring conflicts with the configured endpoint.")
    host = validate_environment_host(host or derive_environment_host(env_id, ring), ring)
    if environment_id_from_host(host, ring).casefold() != env_id.casefold():
        raise ValueError("The native endpoint belongs to a different environment.")
    cache = Path(getattr(args, "token_cache", None) or DEFAULT_TOKEN_CACHE)
    token, tenant_id, account = authenticate_flightcheck(
        ring, account_hint=args.preferred_username, cache_path=cache,
        include_connectivity=True, allow_write=False, emit_account_identity=False,
        return_account_identity=True,
    )
    if not account or (args.preferred_username and account.casefold() != args.preferred_username.casefold()):
        raise ValueError("Native authentication selected a different or unverifiable account.")
    expected_tenant = args.tenant_id or runner.config.get("tenantId")
    if expected_tenant and str(uuid.UUID(str(expected_tenant))).casefold() != tenant_id.casefold():
        raise ValueError("Native authentication selected a different tenant.")
    version = runner.config.get("agentBuilderApiVersion", DEFAULT_API_VERSION)
    runner.env_id, runner.tenant_id, runner.ring = env_id, tenant_id, ring
    runner.authenticated_account = account
    runner.agentbuilder = AgentBuilderClient(host, token, ring=ring, tenant_id=tenant_id, api_version=version)
    runner.connectivity = ConnectivityClient(token, ring=ring, api_version=version)
    runner.connection_agent_ids = (agent_id,)
    runner.connection_dependency_token = partial(
        authenticate_flightcheck_dependency, tenant_id=tenant_id, ring=ring,
        account_hint=account, cache_path=cache,
    )
    if args.environment_url or (getattr(args, "profile", None) and runner.env_url):
        _Access(runner).dataverse()


def _check_native(runner, args):
    try:
        _configure(runner, args)
    except (ValueError, AgentBuilderError, requests.RequestException, SystemExit) as exc:
        return [_result(
            "DA-AGENT-001", Status.BLOCKED.value, "Access to the selected agent",
            f"Agent access could not be verified: {type(exc).__name__}: {exc}",
            "Check the selected agent, environment and signed-in account, then rerun. "
            "Administrator roles are not required merely to start this diagnostic.",
        )]
    rows = run_native_agent_checks(runner)
    snapshot = getattr(runner, "_da_native_snapshot", None)
    if snapshot and snapshot["changeset"]["botComponentChanges"]:
        schema = snapshot["changeset"]["bot"]["schemaName"]
        is_ess = "copilotforemployeeselfservice" in schema.casefold()
        rows.append(_result(
            "ESS-SOLN-001", Status.PASSED.value if is_ess else Status.FAILED.value,
            "Employee Self-Service agent identity",
            f"The selected agent has schema '{schema}' and readable authored content.",
            "" if is_ess else "Select the intended Employee Self-Service agent and rerun.",
            evidence={"evidenceBoundary": "native_identity_and_content_not_package_origin_or_employee_execution"},
        ))
    return rows


def _check_connections(runner):
    if not getattr(runner, "_da_native_snapshot", None):
        return []
    audit = audit_connections(runner)
    runner._da_connection_audit = audit
    status = (
        Status.FAILED.value if audit.failures else
        Status.ERROR.value if any(item["kind"] == "error" for item in audit.read_limitations) else
        Status.MANUAL.value if audit.read_limitations else
        Status.BLOCKED.value if audit.blocked or audit.warnings else Status.PASSED.value
    )
    finding = (
        f"Inspected {len(audit.references)} required connection reference(s) "
        f"from {audit.flow_count} active flow call(s)."
    )
    details = [audit.blocked, *audit.failures, *audit.warnings]
    finding += " " + " ".join(detail for detail in details if detail)
    return [_result(
        "ENV-004", status, "Connections used by this agent", finding.strip(),
        "" if status == Status.PASSED.value else
        "Review the listed references in Copilot Studio Connection Settings and Power Apps Solutions. "
        "Repair confirmed missing or unbound references. If access or topic activation is unknown, "
        "ask the resource owner to verify that specific item; do not replace unrelated connections.",
        evidence={
            "dependencyCoverageComplete": not audit.blocked and not audit.warnings,
            "requiredReferences": len(audit.references), "flowCount": audit.flow_count,
            "references": [asdict(reference) for reference in audit.references],
            "failures": audit.failures, "verificationLimitations": audit.warnings,
            "scopeExclusions": audit.excluded_topics,
            "readLimitations": audit.read_limitations,
            "evidenceBoundary": "inspected_bindings_not_employee_execution",
        },
    )]


def _check_environment(runner):
    if not getattr(runner, "_da_native_snapshot", None):
        return []
    try:
        environment = getattr(runner, "_maker_environment_snapshot", None)
        if environment is None:
            environment = _Access(runner).admin().get_environment(runner.env_id)
        if not isinstance(environment, dict) or str(environment.get("name", "")).casefold() != runner.env_id.casefold():
            raise ValueError("Environment metadata did not identify the exact selected environment.")
        properties = environment.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("Environment properties were unavailable.")
        runner._maker_environment_snapshot = environment
    except (ValueError, RuntimeError, requests.RequestException) as exc:
        if getattr(runner, "da_strict_errors", False):
            raise
        row = _result(
            "ENV-001", "Blocked", "Selected environment metadata",
            f"Native agent access was verified, but environment metadata could not be read: {exc}",
            "Ask the environment owner to verify access to this specific environment; no tenant-wide administrator role is required to start FlightCheck.",
            evidence={"reviewOwner": "administrator"} if (
                isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code == 403
            ) else {},
        )
        row.category = "Environment"
        return [row]
    rows = [_result(
        "ENV-001", "Passed", "Selected environment identity",
        f"Environment {properties.get('displayName') or runner.env_id} matched the requested environment ID.",
        evidence={"environmentId": runner.env_id, "serviceRing": runner.ring},
    )]
    metadata = properties.get("linkedEnvironmentMetadata")
    linked_url = metadata.get("instanceUrl") if isinstance(metadata, dict) else None
    has_link = isinstance(linked_url, str) and bool(linked_url.strip())
    absent_link = "linkedEnvironmentMetadata" in properties and metadata is None
    rows.append(_result(
        "ENV-002", "Passed" if has_link else "NotConfigured" if absent_link else "Blocked",
        "Linked Dataverse environment",
        f"Environment metadata declares {linked_url}." if has_link else
        "No Dataverse link was declared. A native-only agent does not require Dataverse." if absent_link else
        "The environment response did not establish its Dataverse linkage.",
        "" if has_link or absent_link else
        "Inspect this environment's linked-resource metadata in the Power Platform admin center. Do not provision Dataverse merely to clear an unknown result.",
        evidence={"applicability": "not_applicable"} if absent_link else {},
    ))
    if properties.get("environmentSku"):
        rows.append(_result(
            "ENV-003", "Passed", "Environment type",
            f"Environment type: {properties['environmentSku']}. Service ring: {runner.ring}. These are separate settings.",
        ))
    for row in rows:
        row.category = "Environment"
    return rows


def _check_agent_configuration(runner):
    snapshot = getattr(runner, "_da_native_snapshot", None)
    if snapshot is None:
        return []
    payload = snapshot["changeset"]
    components = [change["component"] for change in payload["botComponentChanges"]]
    excluded = {
        component.get("schemaName") for component in components
        if component["$kind"] == "DialogComponent" and _sap_only_topic(component, payload)
    }
    topics = [c for c in components if c["$kind"] == "DialogComponent" and c.get("schemaName") not in excluded]
    unknown = [c.get("schemaName", c.get("id", "unnamed")) for c in topics if c.get("status") not in {"Active", "Inactive"}]
    rows = [_result(
        "DA-TOPIC-001", "Blocked" if unknown else "Passed", "Conversation inventory and activation",
        f"{len(topics)} in-scope conversation(s); "
        f"{sum(c.get('status') == 'Active' for c in topics)} active, "
        f"{sum(c.get('status') == 'Inactive' for c in topics)} inactive, {len(unknown)} unknown. "
        "Inactive conversations are not defects merely because they are disabled.",
        "Verify the listed conversations in Copilot Studio; do not infer activation from component state." if unknown else "",
        evidence={"unknownActivation": unknown, "sapExclusions": len(excluded)},
    )]
    rows[0].category = "Conversations"
    bot = payload["bot"]
    mode = bot.get("authenticationMode")
    rows.append(_result(
        "DA-AUTH-001", "Passed" if isinstance(mode, str) and mode.strip() else "Blocked", "Agent sign-in configuration",
        f"Authentication mode: {mode}; trigger: {bot.get('authenticationTrigger', 'not returned')}. "
        "This reads configuration, not an employee sign-in test.",
    ))
    rows[-1].category = "Agent configuration"
    gpts = [c for c in components if c["$kind"] == "GptComponent"]
    instructions = [
        c.get("metadata", {}).get("instructions")
        for c in gpts if isinstance(c.get("metadata"), dict)
    ]
    templates = [item for item in instructions if isinstance(item, dict) and item.get("$kind") == "TemplateLine"]
    segments = [
        segment for item in templates if isinstance(item.get("segments"), list)
        for segment in item["segments"] if isinstance(segment, dict)
    ]
    has_text = any(segment.get("$kind") == "TextSegment" and isinstance(segment.get("value"), str) and segment["value"].strip() for segment in segments)
    supported = len(templates) == len(instructions) and all(
        isinstance(item.get("segments"), list) and all(
            isinstance(segment, dict) and segment.get("$kind") in {"TextSegment", "ExpressionSegment"}
            for segment in item["segments"]
        )
        for item in templates
    )
    expressions = any(segment.get("$kind") == "ExpressionSegment" for segment in segments)
    instruction_status = "Passed" if supported and has_text else "Failed" if templates and supported and not expressions else "Blocked"
    rows.append(_result(
        "DA-INSTRUCTIONS-001", instruction_status,
        "Cloud-authored agent instructions",
        (f"{len(templates)} instruction definition(s) with nonempty text read from the exact agent's authoring snapshot. "
         if instruction_status == "Passed" else
         "The recorded instructions contain no nonempty text. " if instruction_status == "Failed" else
         "The instructions could not be verified in the supported authoring format. ")
        +
        "Published employee behavior was not assessed.",
        "" if instruction_status == "Passed" else "Refresh the selected agent and inspect its instructions in Copilot Studio.",
    ))
    rows[-1].category = "Agent configuration"
    return rows


def _check_integrations(runner):
    if getattr(runner, "da_executor", None) is not None and not hasattr(runner, "_da_connection_audit"):
        runner.da_executor.group("connections", _check_connections)
    selected = active_agent(runner.config, runner.agent_slug)
    intent_config = (
        {**runner.config, "agent": selected}
        if runner.agent_slug == runner.config.get("activeAgent", (runner.config.get("agent") or {}).get("slug"))
        else {"agent": selected}
    )
    return run_optional_integration_checks(
        runner, workday_configured=_env004_workday_configured(SimpleNamespace(config=intent_config)),
    )


def _check_workday(runner):
    states = getattr(runner, "maker_integrations", {})
    if not getattr(runner, "da_explicit_selection", False) and (
        states.get("Workday", {}).get("applicability") != "enabled"
        or not getattr(runner, "maker_workday_extension", False)
    ):
        return []
    if not getattr(runner, "_da_native_snapshot", None):
        return []
    try:
        cached = getattr(runner, "_da_dependency_dataverse", None)
        if cached:
            env_url, token, pp_admin = cached
        else:
            access = _Access(runner)
            env_url, token = access.dataverse()
            pp_admin = access.pp
        runner.env_url, runner.dv_token, runner.pp_admin = env_url, token, pp_admin
    except (ValueError, RuntimeError, requests.RequestException) as exc:
        if getattr(runner, "da_strict_errors", False):
            raise
        return [_result(
            "WD-DA-PKG-001", Status.BLOCKED.value, "Workday setup",
            f"The selected environment's Workday setup could not be inspected: {type(exc).__name__}: {exc}",
            "Ask the environment owner to confirm access to its linked Dataverse environment, then rerun. "
            "This result does not establish that the Workday package is missing.",
        )]
    rows = run_workday_da_checks(runner, include_manual=False)
    try:
        if runner.should_execute("DV-CONN-001"):
            rows.extend(_check_dv_connection(runner))
    except (ValueError, RuntimeError, PermissionError, requests.RequestException) as exc:
        response = getattr(exc, "response", None)
        code = 403 if isinstance(exc, PermissionError) else (
            response.status_code if response is not None else None
        )
        strict = getattr(runner, "da_strict_errors", False)
        rows.append(_result(
            "DV-CONN-001", ("Manual" if code == 403 else "Error") if strict else "Blocked",
            "Workday runtime Dataverse reference",
            f"The runtime reference could not be inspected: {type(exc).__name__}: {exc}",
            "Ask the environment owner to verify read access to connection references, then rerun.",
            evidence={"httpStatus": code, "readLimitation": type(exc).__name__},
        ))
    if not runner.should_execute("WD-REST-002"):
        return rows
    local = SimpleNamespace(
        config=runner.config, agent_slug=runner.agent_slug, env_id=runner.env_id,
        env_url=None, dv_token=None, pva=None,
    )
    if not (Path("workspace") / "agents" / runner.agent_slug / ".component-map.json").is_file():
        local_rows = [_result(
            "WD-REST-002", "Blocked", "Local Workday user-context redirect",
            "The selected agent's local component map is unavailable; its local redirect cannot be inspected.",
            "Refresh the selected agent's local extraction through setup, then rerun. This does not establish a cloud defect.",
        )]
    else:
        local_rows = _check_user_context_redirect(local)
    for row in local_rows:
        row.evidence.update({"evidenceBoundary": "local_authored_content", "deploymentFreshnessVerified": False})
        if row.status == "Skipped" and runner.config.get("installPath") == "legacy":
            row.status = "NotConfigured"
            row.evidence["applicability"] = "not_applicable"
    rows.extend(local_rows)
    return rows


def _check_local(runner):
    local = SimpleNamespace(
        config=runner.config, agent_slug=runner.agent_slug, maker_diagnostics=True,
        env_id=runner.env_id, env_url=None, dv_token=None, pva=None,
    )
    return run_da_local_file_checks(local)


def _check_manual_verification(runner):
    if not getattr(runner, "da_explicit_selection", False) and (
        getattr(runner, "maker_integrations", {}).get("Workday", {}).get("applicability") != "enabled"
        or not getattr(runner, "maker_workday_extension", False)
    ):
        return []
    rows = _check_agent_flow_attachment(runner)
    for row in rows:
        if row.status == Status.MANUAL.value:
            row.category = "Manual verification"
    return rows


def run_maker_diagnostics(args, config) -> RunResult:
    from .da_execution import DAExecutor, plan_da_checks

    checkpoint, profile = getattr(args, "checkpoint", None), getattr(args, "profile", None)
    scope = "checkpoint" if checkpoint else "profile" if profile else getattr(args, "scope", "full")
    if scope not in {"full", "local", "workday", "servicenow", "checkpoint", "profile"}:
        raise ValueError(f"Unsupported DA maker diagnostic scope: {scope!r}.")
    runner = FlightCheckRunner(scope=scope)
    runner.config = dict(config)
    workday_app_id = (getattr(args, "workday_app_id", None) or "").strip()
    if workday_app_id:
        runner.config["entraAppId"] = workday_app_id
        runner.config.pop("entraAppObjectId", None)
    runner.agent_slug = args.agent_slug or active_agent(config).get("slug")
    runner.maker_diagnostics = True
    runner.da_strict_errors = True
    runner.validation_context = {"realm": args.validation_realm or config.get("realm")}
    runner.env_id = args.environment_id or config.get("environmentId")
    runner.env_url = args.environment_url or config.get("dataverseEndpoint", "")
    runner.dv_token = runner.pp_admin = runner.agentbuilder = runner.connectivity = None
    runner.graph = runner.powerplatform = runner.azure_arm = None
    runner.da_observations = {}
    runner.rerun_command = ""
    if checkpoint:
        command = ["python", str(Path("scripts") / "flightcheck" / "cli.py"), "--checkpoint", checkpoint]
        if runner.agent_slug:
            command.extend(("--agent-slug", runner.agent_slug))
        for option, value in (
            ("--workday-app-id", workday_app_id),
            ("--environment-url", args.environment_url), ("--environment-id", args.environment_id),
            ("--tenant-id", args.tenant_id), ("--ring", args.ring),
            ("--validation-realm", args.validation_realm), ("--preferred-username", args.preferred_username),
            ("--token-cache", getattr(args, "token_cache", None)),
        ):
            if value:
                command.extend((option, str(value)))
        command.extend(("--output", str(args.output), "--invocation-source", "cli", "--select-targets", "never"))
        if getattr(args, "no_telemetry", False):
            command.append("--no-telemetry")
        runner.rerun_command = subprocess.list2cmdline(command)
    requested, specs, aliases = plan_da_checks(
        checkpoint=checkpoint, profile=profile, local=scope == "local", scope=scope,
    )
    runner.da_explicit_selection = bool(checkpoint or profile)
    wanted = frozenset(spec.key for spec in specs)
    runner._target_matcher = wanted.__contains__
    if runner.da_explicit_selection or scope in {"workday", "servicenow"}:
        from .registry import REGISTRY

        features = {REGISTRY[key].da.feature for key in requested if key in REGISTRY and REGISTRY[key].da} - {""}
        generic_dependencies = bool({"ENV-004", "DA-INTEGRATIONS-001"} & set(requested))
        if not generic_dependencies and features and features <= {"workday", "workday_oob", "workday_custom"}:
            runner.da_integration_names = frozenset({"Workday"})
            runner.da_connector_filter = frozenset({"shared_workdaysoap", "shared_commondataserviceforapps"})
        elif not generic_dependencies and features == {"servicenow"}:
            runner.da_integration_names = frozenset({"ServiceNow"})
            runner.da_connector_filter = frozenset({"shared_service-now"})
    executor = DAExecutor(runner, args, requested, specs, aliases)
    runner.da_executor = executor
    runner.register("Selected-agent checks", executor.run)
    result = runner.run()
    result.diagnostic_only = True
    result.rerun_command = runner.rerun_command
    result.coverage = executor.coverage()
    if profile:
        from .registry import profile_family_contract, profile_requirements

        result.profile = profile
        result.profile_checkpoints = list(requested)
        result.profile_families = profile_family_contract(profile)
        authenticated = bool(getattr(runner, "authenticated_account", ""))
        dataverse = getattr(runner, "_da_dependency_dataverse", None)
        available = {
            "agentbuilder": runner.agentbuilder is not None,
            "dataverse": bool(dataverse and dataverse[1]),
            "connectivity": runner.connectivity is not None,
            "graph": runner.graph is not None,
            "powerplatform": runner.powerplatform is not None,
            "azure_arm": runner.azure_arm is not None,
            "pp_admin": getattr(runner, "_da_pp_read_client", None) is not None,
            "pva": getattr(runner, "pva", None) is not None,
        }
        result.client_availability = {
            client: {
                "required": True,
                "available": available.get(client, False),
                "authenticatedAccountVerified": authenticated and available.get(client, False),
                "reason": "" if authenticated and available.get(client, False)
                else "The required client did not complete verified authentication.",
            }
            for client in sorted(profile_requirements(profile).clients)
        }
    else:
        result.overall = maker_diagnostic_outcome(result)
    selected = active_agent(config, runner.agent_slug)
    snapshot = getattr(runner, "_da_native_snapshot", None)
    bot = snapshot["changeset"]["bot"] if snapshot else {}
    environment = getattr(runner, "_maker_environment_snapshot", {})
    properties = environment.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    metadata = properties.get("linkedEnvironmentMetadata")
    result.validation_context = {
        "agentSlug": runner.agent_slug, "agentId": selected.get("botId", ""),
        "agentSchemaName": selected.get("schemaName", ""), "environmentId": runner.env_id or "",
        "agentName": bot.get("displayName") or selected.get("name") or selected.get("displayName") or runner.agent_slug,
        "accountEmail": getattr(runner, "authenticated_account", ""),
        "environmentName": properties.get("displayName", ""),
        "environmentUrl": metadata.get("instanceUrl", "") if isinstance(metadata, dict) else "",
        "environmentType": properties.get("environmentSku", ""),
        "serviceRing": getattr(runner, "ring", ""),
        "targetVerified": snapshot is not None,
        "tenantId": getattr(runner, "tenant_id", config.get("tenantId", "")),
        "realm": args.validation_realm or config.get("realm") or (
            next((row.evidence.get("realm") for row in result.results if row.checkpoint_id == "DA-AGENT-001"), None)
        ),
    }
    if checkpoint or profile:
        result.requested_validation_context = {
            "realm": args.validation_realm or config.get("realm") or "",
            "agentSlug": runner.agent_slug, "agentId": selected.get("botId", ""),
            "agentSchemaName": selected.get("schemaName", ""),
            "environmentId": runner.env_id or "",
            "environmentUrl": args.environment_url or config.get("dataverseEndpoint", ""),
            "tenantId": args.tenant_id or config.get("tenantId", ""),
        }
    return result
