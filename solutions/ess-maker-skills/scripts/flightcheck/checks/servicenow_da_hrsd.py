# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lifecycle checkpoints for the DA HR ServiceNow HRSD provider."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from typing import Any

from connect_servicenow_da import (
    AUTH_MODE,
    CONNECTOR_NAME,
    HR_SCHEMA_NAME,
    PROVIDER_KEY,
    SERVICENOW_CONNECTOR_APP_ID,
    _connection_binding_hash,
    _draft_semantic_hash,
    _identity_candidate_set_hash,
    _identity_mapping_relationship_hash,
    _portal_literal_value,
    _portal_topic_component,
    _servicenow_topic_changes,
    normalize_client_id,
    normalize_instance_name,
    normalize_portal_url,
    portal_confirmation_url,
    portal_configuration_summary,
    required_servicenow_prerequisites,
    summarize_components,
)

from ..agent_scope import validate_agent_slug
from ..runner import CheckResult, Priority, Role, Status


_CATEGORY = "ServiceNow DA HRSD"
_ROLES = [Role.ESS_MAKER.value, Role.SERVICENOW_ADMIN.value]
_ENTRA_PREFIX = "SN-DA-HRSD-ENTRA"
_TEST_PROMPT_CATEGORY = "list-my-open-hr-cases"
_RECOVERY_STATUSES = {
    Status.BLOCKED.value,
    Status.ERROR.value,
    Status.FAILED.value,
    Status.NOT_CONFIGURED.value,
    Status.WARNING.value,
}
_RECOVERY_GUIDANCE = {
    "PKG": {
        "step": "ServiceNow extension readiness",
        "owner": "Power Platform Maker/Admin",
        "where": (
            "Copilot Studio -> the exact selected agent -> Topics and "
            "installed solution components"
        ),
        "values": (
            "Use the selected agent named in the current result. Install or "
            "repair only the matching ServiceNow extension/profile."
        ),
        "success": (
            "The exact selected agent exposes the expected ServiceNow topics."
        ),
    },
    "ADMIN-PREFLIGHT": {
        "step": "target confirmation",
        "owner": "ESS Maker / Agent Developer",
        "where": (
            "Copilot Studio -> the exact selected agent and environment; "
            "ServiceNow public instance URL supplied by the ServiceNow admin"
        ),
        "values": (
            "Confirm the current agent, environment, Dev realm, and one public "
            "`https://<instance>.service-now.com` URL. If the URL is unknown, "
            "the ServiceNow admin must provide it; do not infer it from an old "
            "connection."
        ),
        "success": (
            "The exact agent/environment/realm and normalized public instance "
            "name are confirmed."
        ),
    },
    "PLUGIN": {
        "step": "HR Service Delivery Core prerequisite",
        "owner": "ServiceNow Admin",
        "where": (
            "ServiceNow -> All -> System Applications -> All Available "
            "Applications -> All"
        ),
        "values": (
            "Application: Human Resources Scoped App: Core; Plugin ID: "
            "`com.sn_hr_core`; Version Details: `Installed`; confirm the "
            "installed-and-ready message."
        ),
        "success": (
            "The Application Manager record shows the required plugin ID, "
            "Installed status, and ready message."
        ),
    },
    "ENTRA": {
        "step": "Microsoft Entra application setup",
        "owner": "Microsoft Entra Application Administrator or higher",
        "where": (
            "Microsoft Entra admin center -> App registrations -> the App A "
            "application identified by the recorded Application (client) ID"
        ),
        "values": (
            "Use the non-secret Application client ID recorded for this "
            "lifecycle. If it is absent or invalid, the Entra admin must return "
            "the correct App A client ID through the protected handoff. Never "
            "return a client secret, token, certificate, or PFX."
        ),
        "success": (
            "The single-tenant app, emitted claim candidates, "
            "`api://<client-id>` plus enabled `user_impersonation`, and "
            "ServiceNow connector pre-authorization all match the verified "
            "App A client ID."
        ),
    },
    "OIDC": {
        "step": "ServiceNow OIDC and active-user mapping",
        "owner": "ServiceNow Admin / security_admin",
        "where": (
            "ServiceNow -> All -> System OAuth -> Application Registry, then "
            "the protected ServiceNow identity-mapping handoff"
        ),
        "values": (
            "Use one Entra-confirmed emitted claim name and the exact "
            "ServiceNow user field selected by the ServiceNow admin. If either "
            "name is unknown, obtain it through the protected workbook; never "
            "return an employee identifier or token value."
        ),
        "success": (
            "The OIDC provider is ready and the bounded receipt proves one "
            "current claim-name/user-field pair plus a matching Active user."
        ),
    },
    "TOPICS": {
        "step": "ServiceNow topic readiness",
        "owner": "ESS Maker / Agent Developer",
        "where": "Copilot Studio -> the exact selected agent -> Topics",
        "values": (
            "Use the current ServiceNow topic inventory and states reported "
            "for this exact agent. Change only the required ServiceNow topics; "
            "leave unrelated and customer-authored topics unchanged."
        ),
        "success": (
            "Every required ServiceNow topic is Active, or the maker records "
            "the explicit keep-current decision for the current component hash."
        ),
    },
    "PORTAL": {
        "step": "ServiceNow portal Base URI",
        "owner": "ESS Maker / Agent Developer with ServiceNow Admin input",
        "where": (
            "Copilot Studio -> Topics -> ServiceNow Setup Configurations -> "
            "Set ServiceNow Portal BaseURI"
        ),
        "values": (
            "Use the exact administrator-confirmed HTTPS employee portal URL "
            "on the confirmed ServiceNow instance. A root URL is allowed only "
            "when explicitly confirmed; never infer `/sp` or `/esc`."
        ),
        "success": (
            "The saved literal is a plain HTTPS URL on the confirmed instance "
            "and matches the current administrator-confirmed portal URL."
        ),
    },
    "CREDENTIAL": {
        "step": "ServiceNow physical connection",
        "owner": "Power Platform Maker/Admin",
        "where": (
            "Power Automate or Power Apps -> exact environment -> Connections "
            "-> Microsoft-published ServiceNow connector"
        ),
        "values": (
            "Authentication Type: Microsoft Entra ID User Login "
            "(`entraIDUserLogin`). Instance Name: the confirmed preflight "
            "instance. Resource URI: the verified App A Application client ID. "
            "If either value is missing, resume its owning phase; never use an "
            "old failed connection value. The current maker signs in with "
            "their own Microsoft account."
        ),
        "success": (
            "A freshly discovered exact connection is Connected and matches "
            "the current environment, auth mode, Instance Name, and verified "
            "App A client ID."
        ),
    },
    "AGENT-CONNECTION": {
        "step": "agent connection binding",
        "owner": "ESS Maker / Agent Developer",
        "where": (
            "Copilot Studio -> the exact selected agent -> Settings -> "
            "Connection settings -> ServiceNow"
        ),
        "values": (
            "Bind the current maker's freshly verified exact ServiceNow "
            "connection. Do not copy or return a connection ID, and do not "
            "impersonate another connection owner."
        ),
        "success": (
            "The ServiceNow row shows Connected for the selected connection "
            "and the attestation is bound to the current saved draft."
        ),
    },
    "TEST": {
        "step": "Dev Test pane validation",
        "owner": "ESS Maker / Agent Developer",
        "where": "Copilot Studio -> the exact selected agent -> Test pane",
        "values": (
            "Save the current draft and use the profile's bounded low-side-"
            "effect test category. Record only Pass/Not pass plus the allowed "
            "failure category; never return prompt text, employee values, "
            "ticket/case content, tokens, or secrets."
        ),
        "success": (
            "A current passing Test result is bound to the current saved draft "
            "and selected connection."
        ),
    },
    "PUBLISH": {
        "step": "publish evidence",
        "owner": "ESS Maker / Agent Developer",
        "where": "Copilot Studio -> the exact selected agent -> Publish details",
        "values": (
            "Use only the current tested draft identity and explicit maker "
            "confirmation. Publishing remains outside ServiceNow Connect."
        ),
        "success": "A definitive receipt exists for the exact tested draft.",
    },
}


def _recovery_key(checkpoint_id: str) -> str:
    suffix = checkpoint_id.removeprefix("SN-DA-HRSD-").removesuffix("-001")
    return "ENTRA" if suffix.startswith("ENTRA-") else suffix


def _recovery_category(status: str, result: str) -> str:
    lowered = result.casefold()
    if status == Status.ERROR.value:
        if "429" in lowered or "throttl" in lowered:
            return "Read throttled"
        if any(
            token in lowered
            for token in (
                "401",
                "403",
                "permission",
                "denied",
                "authorization",
            )
        ):
            return "Read permission"
        return "Read or network error"
    if status == Status.FAILED.value:
        return "Verified mismatch or failed validation"
    if status == Status.BLOCKED.value:
        return "Ambiguous or blocked target"
    return "Missing or repairable configuration"


def _actionable_remediation(
    checkpoint_id: str,
    status: str,
    result: str,
    action: str,
) -> str:
    if status not in _RECOVERY_STATUSES:
        return action
    guidance = _RECOVERY_GUIDANCE.get(_recovery_key(checkpoint_id))
    if guidance is None:
        return action
    category = _recovery_category(status, result)
    if category == "Read throttled":
        retry = (
            "Honor the service's Retry-After value when present, then rerun "
            "only this read once. Do not replay configuration or later phases."
        )
    elif category == "Read permission":
        retry = (
            "Restore the minimum read permission for the current account, "
            "reauthenticate if required, then rerun only this read."
        )
    elif category == "Read or network error":
        retry = (
            "Restore the current read path or network access, then rerun only "
            "this step. Do not treat the error as missing configuration."
        )
    else:
        retry = action
    return (
        f"**Problem**\n{result}\n\n"
        f"**Category**\n{category}\n\n"
        f"**Owner**\n{guidance['owner']}\n\n"
        f"**Where**\n{guidance['where']}\n\n"
        f"**Values to use**\n{guidance['values']}\n\n"
        f"**Action**\n{retry}\n\n"
        f"**Success**\n{guidance['success']}\n\n"
        f"**Recheck and resume**\nRerun only the current "
        f"{guidance['step']} check. When it passes, resume at this step; "
        "dependent later steps remain pending and are rechecked in order."
    )


def _result(
    checkpoint_id: str,
    status: str,
    description: str,
    result: str,
    remediation: str = "",
    *,
    format_recovery: bool = True,
) -> CheckResult:
    if format_recovery:
        remediation = _actionable_remediation(
            checkpoint_id,
            status,
            result,
            remediation,
        )
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category=_CATEGORY,
        priority=Priority.HIGH.value,
        status=status,
        description=description,
        result=result,
        remediation=remediation,
        roles=_ROLES,
    )


def _active_agent(runner) -> tuple[str, dict[str, Any]] | None:
    config = getattr(runner, "config", {}) or {}
    if not isinstance(config, dict):
        return None
    slug = (
        getattr(runner, "agent_slug", None)
        or config.get("activeAgent")
        or (config.get("agent") or {}).get("slug")
    )
    try:
        slug = validate_agent_slug(str(slug))
    except ValueError:
        return None
    agents = config.get("agents")
    if isinstance(agents, list):
        for agent in agents:
            if isinstance(agent, dict) and agent.get("slug") == slug:
                return slug, agent
    legacy = config.get("agent")
    if isinstance(legacy, dict) and legacy.get("slug") == slug:
        return slug, legacy
    return None


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _load_state(slug: str) -> dict[str, Any]:
    path = (
        Path(".local/connect")
        / PROVIDER_KEY
        / "agents"
        / slug
        / "lifecycle.json"
    )
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _connection_status(record: dict[str, Any]) -> str:
    statuses = (record.get("properties") or {}).get("statuses")
    if not isinstance(statuses, list):
        return ""
    token = next(
        (
            value
            for value in statuses
            if isinstance(value, dict) and value.get("target") == "token"
        ),
        next((value for value in statuses if isinstance(value, dict)), {}),
    )
    return str(token.get("status") or "")


def _auth_mode(record: dict[str, Any]) -> str:
    parameters = (record.get("properties") or {}).get(
        "connectionParametersSet"
    )
    return str(
        parameters.get("name") if isinstance(parameters, dict) else ""
    )


def _servicenow_connections(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if str((record.get("properties") or {}).get("apiId") or "")
        .rstrip("/")
        .rsplit("/", 1)[-1]
        .casefold()
        == CONNECTOR_NAME.casefold()
    ]


def _target_matches(target: str | None, checkpoint_id: str) -> bool:
    if target is None:
        return True
    if target in {_ENTRA_PREFIX, f"{_ENTRA_PREFIX}-*"}:
        return checkpoint_id.startswith(f"{_ENTRA_PREFIX}-")
    return checkpoint_id == target


def _target_rows(
    target: str | None,
    results: list[CheckResult],
) -> list[CheckResult]:
    return [
        result
        for result in results
        if _target_matches(target, result.checkpoint_id)
    ]


def invalidate_servicenow_read_snapshot(runner) -> None:
    """Discard invocation-scoped read evidence after any external boundary."""
    runner._servicenow_read_snapshot = {}


def _read_snapshot(runner) -> dict[tuple[str, str, str], dict[str, Any]]:
    snapshot = getattr(runner, "_servicenow_read_snapshot", None)
    if not isinstance(snapshot, dict):
        snapshot = {}
        runner._servicenow_read_snapshot = snapshot
    return snapshot


def _is_throttled_error(exc: BaseException) -> bool:
    if getattr(exc, "status_code", None) == 429:
        return True
    details = getattr(exc, "details", None)
    return isinstance(details, dict) and (
        details.get("statusCode") == 429
        or details.get("category") == "throttled"
    )


def _acquire_servicenow_reads(
    runner,
    *,
    agent_id: str,
    environment_id: str,
    needs_inventory: bool,
) -> tuple[
    dict[str, Any] | None,
    BaseException | None,
    list[dict[str, Any]],
    BaseException | None,
]:
    """Acquire independent remote reads once; evaluation remains serial."""
    key = (PROVIDER_KEY, agent_id.casefold(), environment_id.casefold())
    snapshot = _read_snapshot(runner)
    entry = snapshot.setdefault(key, {})
    components = entry.get("components")
    connections = entry.get("connections")
    component_error = None
    connectivity_error = None
    tasks: dict[str, Any] = {}
    if components is None:
        if getattr(runner, "_servicenow_read_quiesced", False):
            component_error = getattr(
                runner,
                "_servicenow_throttle_error",
                RuntimeError(
                    "ServiceNow read acquisition is paused after throttling."
                ),
            )
        else:
            client = getattr(runner, "agentbuilder", None)
            if client is None:
                component_error = RuntimeError(
                    "AgentBuilder authentication is unavailable."
                )
            else:
                tasks["components"] = lambda: client.fetch_components(agent_id)
    if needs_inventory and connections is None:
        if getattr(runner, "_servicenow_read_quiesced", False):
            connectivity_error = getattr(
                runner,
                "_servicenow_throttle_error",
                RuntimeError(
                    "ServiceNow read acquisition is paused after throttling."
                ),
            )
        else:
            connectivity = getattr(runner, "connectivity", None)
            if connectivity is None:
                connectivity_error = RuntimeError(
                    "Connection inventory authentication is unavailable."
                )
            else:
                tasks["connections"] = lambda: _servicenow_connections(
                    connectivity.list_connector_connections(
                        environment_id,
                        CONNECTOR_NAME,
                    )
                )

    def capture(name: str, operation) -> None:
        nonlocal components, connections, component_error, connectivity_error
        try:
            value = operation()
            entry[name] = value
            if name == "components":
                components = value
            else:
                connections = value
        except Exception as exc:  # noqa: BLE001 - preserved for evaluation
            if _is_throttled_error(exc):
                runner._servicenow_read_quiesced = True
                runner._servicenow_throttle_error = exc
            if name == "components":
                component_error = exc
            else:
                connectivity_error = exc

    parallel = (
        getattr(runner, "servicenow_parallel_reads", True)
        and len(tasks) == 2
    )
    if parallel:
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="servicenow-read",
        ) as executor:
            futures = {
                name: executor.submit(operation)
                for name, operation in tasks.items()
            }
            for name, future in futures.items():
                capture(name, future.result)
    else:
        for name, operation in tasks.items():
            if getattr(runner, "_servicenow_read_quiesced", False):
                error = getattr(
                    runner,
                    "_servicenow_throttle_error",
                    RuntimeError(
                        "ServiceNow read acquisition is paused after "
                        "throttling."
                    ),
                )
                if name == "components":
                    component_error = error
                else:
                    connectivity_error = error
                continue
            capture(name, operation)
    return (
        components if isinstance(components, dict) else None,
        component_error,
        connections if isinstance(connections, list) else [],
        connectivity_error,
    )


def run_servicenow_da_hrsd_checks(runner) -> list[CheckResult]:
    target = getattr(runner, "checkpoint_target", None)
    selected = _active_agent(runner)
    if selected is None:
        return _all_unavailable(
            Status.FAILED.value,
            "The selected agent could not be resolved.",
            "Select the exact editable ESS HR agent and rerun the checkpoint.",
            target=target,
        )
    slug, agent = selected
    schema = str(
        agent.get("schemaName") or agent.get("schema_name") or ""
    ).casefold()
    if schema != HR_SCHEMA_NAME.casefold():
        return _all_unavailable(
            Status.NOT_CONFIGURED.value,
            f"The selected agent '{slug}' is not the ESS DA HR agent.",
            "Select the Employee Self-Service HR agent.",
            target=target,
        )
    agent_id = str(agent.get("botId") or agent.get("id") or "")
    if not agent_id:
        return _all_unavailable(
            Status.FAILED.value,
            "The selected HR agent has no AgentBuilder ID.",
            "Refresh the local setup handoff for this agent.",
            target=target,
        )
    needs_inventory = target in {
        "SN-DA-HRSD-CREDENTIAL-001",
        "SN-DA-HRSD-AGENT-CONNECTION-001",
        "SN-DA-HRSD-TEST-001",
        None,
    }
    environment_id = str(getattr(runner, "env_id", None) or "")
    (
        components,
        component_error,
        connections,
        connectivity_exception,
    ) = _acquire_servicenow_reads(
        runner,
        agent_id=agent_id,
        environment_id=environment_id,
        needs_inventory=needs_inventory,
    )
    if component_error is not None or components is None:
        error = component_error or RuntimeError("Component state is unavailable.")
        return _all_unavailable(
            Status.ERROR.value,
            f"Unable to inspect the HR agent: "
            f"{type(error).__name__}: {error}",
            "Verify AgentBuilder access to the selected environment and retry.",
            target=target,
        )
    try:
        if not _servicenow_topic_changes(components):
            return _all_unavailable(
                Status.NOT_CONFIGURED.value,
                f"The selected HR agent '{slug}' has no ServiceNow HRSD topics.",
                "Install the ServiceNow HRSD extension for this exact HR agent.",
                target=target,
            )
        summary = summarize_components(components)
    except Exception as exc:
        return _all_unavailable(
            Status.ERROR.value,
            f"Unable to inspect the HR agent: {type(exc).__name__}: {exc}",
            "Verify AgentBuilder access to the selected environment and retry.",
            target=target,
        )

    state = _load_state(slug)
    evidence = state.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    admin_setup = state.get("adminSetup")
    admin_setup = admin_setup if isinstance(admin_setup, dict) else {}
    if target == "SN-DA-HRSD-PKG-001":
        return [_package_result(slug, summary)]
    if target == "SN-DA-HRSD-ADMIN-PREFLIGHT-001":
        return [_preflight_result(admin_setup)]
    if target == "SN-DA-HRSD-PLUGIN-001":
        return [_plugin_result(admin_setup)]
    if target is not None and target.startswith(f"{_ENTRA_PREFIX}-"):
        return _target_rows(
            target,
            _entra_results(
                getattr(runner, "graph", None),
                admin_setup,
                state,
            ),
        )
    if target in {_ENTRA_PREFIX, f"{_ENTRA_PREFIX}-*"}:
        return _entra_results(
            getattr(runner, "graph", None),
            admin_setup,
            state,
        )
    if target == "SN-DA-HRSD-OIDC-001":
        return [_oidc_result(admin_setup, state)]
    if target == "SN-DA-HRSD-PORTAL-001":
        return [_portal_result(components, admin_setup, state)]

    component_hash = (
        _hash(components)
        if target
        in {
            "SN-DA-HRSD-TOPICS-001",
            "SN-DA-HRSD-TEST-001",
            "SN-DA-HRSD-PUBLISH-001",
            None,
        }
        else ""
    )
    if target == "SN-DA-HRSD-TOPICS-001":
        return [_topics_result(summary, evidence, component_hash)]
    if target == "SN-DA-HRSD-PUBLISH-001":
        try:
            draft_semantic_hash = _draft_semantic_hash(components)
            current_connection_binding_hash = (
                _connection_binding_hash(
                    {
                        "agent": {
                            "id": agent.get("botId"),
                            "workspace_slug": slug,
                        },
                        "environment": {
                            "id": str(
                                getattr(runner, "env_id", None) or ""
                            )
                        },
                    },
                    state,
                    components,
                    require_agent_attestation=False,
                )
                if isinstance(evidence.get("credential"), dict)
                and evidence["credential"].get("connectionId")
                else None
            )
        except Exception as exc:
            return _all_unavailable(
                Status.ERROR.value,
                f"Unable to inspect the HR agent draft identity: "
                f"{type(exc).__name__}: {exc}",
                "Verify the selected HR agent component state and retry.",
                target=target,
            )
        return [
            _publish_result(
                evidence,
                component_hash,
                draft_semantic_hash,
                current_connection_binding_hash,
            )
        ]

    connectivity_error = ""
    if needs_inventory:
        if connectivity_exception is not None:
            connectivity_error = (
                f"{type(connectivity_exception).__name__}: "
                f"{connectivity_exception}"
            )

    credential_result = _credential_result(
        evidence,
        admin_setup,
        connections,
        connectivity_error,
    )
    if target == "SN-DA-HRSD-CREDENTIAL-001":
        return [credential_result]

    needs_draft_identity = target in {
        "SN-DA-HRSD-AGENT-CONNECTION-001",
        "SN-DA-HRSD-TEST-001",
        None,
    }
    draft_semantic_hash = ""
    current_connection_binding_hash = None
    if needs_draft_identity:
        try:
            draft_semantic_hash = _draft_semantic_hash(components)
            if target in {"SN-DA-HRSD-TEST-001", None}:
                current_connection_binding_hash = (
                    _connection_binding_hash(
                        {
                            "agent": {
                                "id": agent.get("botId"),
                                "workspace_slug": slug,
                            },
                            "environment": {
                                "id": str(
                                    getattr(runner, "env_id", None) or ""
                                )
                            },
                        },
                        state,
                        components,
                        require_agent_attestation=False,
                    )
                    if isinstance(evidence.get("credential"), dict)
                    and evidence["credential"].get("connectionId")
                    else None
                )
        except Exception as exc:
            return _all_unavailable(
                Status.ERROR.value,
                f"Unable to inspect the HR agent draft identity: "
                f"{type(exc).__name__}: {exc}",
                "Verify the selected HR agent component state and retry.",
                target=target,
            )

    agent_connection_result = _agent_connection_result(
        evidence,
        credential_result,
        draft_semantic_hash,
    )
    if target == "SN-DA-HRSD-AGENT-CONNECTION-001":
        return [agent_connection_result]

    topics_result = _topics_result(summary, evidence, component_hash)
    portal_result = _portal_result(components, admin_setup, state)
    if target == "SN-DA-HRSD-TEST-001":
        return [
            _test_result(
                evidence,
                draft_semantic_hash,
                current_connection_binding_hash,
                topics_result,
                portal_result,
                credential_result,
                agent_connection_result,
            )
        ]
    test_result = _test_result(
        evidence,
        draft_semantic_hash,
        current_connection_binding_hash,
        topics_result,
        portal_result,
        credential_result,
        agent_connection_result,
    )
    return [
        _package_result(slug, summary),
        _preflight_result(admin_setup),
        _plugin_result(admin_setup),
        *_entra_results(
            getattr(runner, "graph", None),
            admin_setup,
            state,
        ),
        _oidc_result(admin_setup, state),
        topics_result,
        portal_result,
        credential_result,
        agent_connection_result,
        test_result,
        _publish_result(
            evidence,
            component_hash,
            draft_semantic_hash,
            current_connection_binding_hash,
        ),
    ]


def _all_unavailable(
    status: str,
    result: str,
    remediation: str,
    *,
    target: str | None = None,
) -> list[CheckResult]:
    ids = (
        "PKG",
        "ADMIN-PREFLIGHT",
        "PLUGIN",
        "ENTRA-APP",
        "ENTRA-CLAIMS",
        "ENTRA-SCOPE",
        "ENTRA-PREAUTH",
        "OIDC",
        "TOPICS",
        "PORTAL",
        "CREDENTIAL",
        "AGENT-CONNECTION",
        "TEST",
        "PUBLISH",
    )
    return _target_rows(
        target,
        [
        _result(
            f"SN-DA-HRSD-{suffix}-001",
            status,
            f"ServiceNow HRSD {suffix.lower()} readiness",
            result,
            remediation,
        )
        for suffix in ids
        ],
    )


def _package_result(slug: str, summary: dict[str, Any]) -> CheckResult:
    count = summary["serviceNowTopicCount"]
    passed = bool(count)
    return _result(
        "SN-DA-HRSD-PKG-001",
        Status.PASSED.value if passed else Status.NOT_CONFIGURED.value,
        "ServiceNow HRSD package installed for the selected DA HR agent",
        (
            f"Selected HR agent '{slug}' contains {count} ServiceNow HRSD "
            "topic(s)."
        ),
        "Install the ServiceNow HRSD extension for this exact HR agent."
        if not count
        else "",
    )


def _phase_handoffs(admin_setup: dict[str, Any]) -> dict[str, Any]:
    value = admin_setup.get("phaseHandoffs")
    return value if isinstance(value, dict) else {}


def _phase_handoff(
    admin_setup: dict[str, Any],
    phase: str,
) -> dict[str, Any]:
    value = _phase_handoffs(admin_setup).get(phase)
    return value if isinstance(value, dict) else {}


def _phase_attested(
    admin_setup: dict[str, Any],
    phase: str,
) -> bool:
    return _phase_handoff(admin_setup, phase).get("status") in {
        "completed",
        "reused",
    }


def _preflight_result(admin_setup: dict[str, Any]) -> CheckResult:
    preflight = admin_setup.get("preflight")
    preflight = preflight if isinstance(preflight, dict) else {}
    if not _phase_attested(admin_setup, "preflight"):
        status = Status.NOT_CONFIGURED.value
        result = "The ServiceNow target confirmation is incomplete."
    elif not preflight.get("instanceName"):
        status = Status.NOT_CONFIGURED.value
        result = "The public ServiceNow instance URL is not known."
    else:
        status = Status.PASSED.value
        result = (
            "The exact supported agent target and public ServiceNow instance "
            "are confirmed. Later phases own plugin, identity, connection, "
            "binding, and functional readiness."
        )
    return _result(
        "SN-DA-HRSD-ADMIN-PREFLIGHT-001",
        status,
        "ServiceNow target confirmation",
        result,
        (
            "Confirm the selected live ESS agent, environment, realm, and one "
            "public ServiceNow instance URL. Do not treat connection inventory "
            "or later readiness as this checkpoint's pass condition."
            if status != Status.PASSED.value
            else ""
        ),
    )


def _plugin_result(admin_setup: dict[str, Any]) -> CheckResult:
    requirements = required_servicenow_prerequisites(
        str(admin_setup.get("scope") or "hrsd"),
        str(admin_setup.get("authMode") or AUTH_MODE),
    )
    handoff = _phase_handoff(admin_setup, "plugin-prerequisites")
    evidence = handoff.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    confirmed = bool(
        _phase_attested(admin_setup, "plugin-prerequisites")
        and evidence.get("pluginId") == "com.sn_hr_core"
        and evidence.get("versionDetails") == "Installed"
        and evidence.get("installedReadyMessageConfirmed") is True
    )
    missing = [] if confirmed else [
        requirement["id"] for requirement in requirements
    ]
    status = (
        Status.MANUAL.value if not missing else Status.NOT_CONFIGURED.value
    )
    return _result(
        "SN-DA-HRSD-PLUGIN-001",
        status,
        "Scope-derived ServiceNow plugin prerequisites",
        (
            "The ServiceNow admin confirmed Human Resources Scoped App: Core "
            "shows Plugin ID com.sn_hr_core, Version Details Installed, and "
            "the installed-and-ready message."
            if not missing
            else "Missing admin confirmation for: " + ", ".join(missing) + "."
        ),
        (
            "Ask a ServiceNow admin to confirm the Application Manager record "
            "shows com.sn_hr_core, Installed, and the installed-and-ready "
            "message."
            if missing
            else ""
        ),
    )


def _entra_client_id(admin_setup: dict[str, Any]) -> str:
    evidence = _phase_handoff(
        admin_setup,
        "entra-registration",
    ).get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    value = evidence.get("clientId")
    return str(value or "")


def _entra_manual_or_missing(
    admin_setup: dict[str, Any],
    checkpoint_id: str,
    description: str,
    reason: str,
) -> CheckResult:
    attested = _phase_attested(admin_setup, "entra-registration")
    return _result(
        checkpoint_id,
        Status.MANUAL.value if attested else Status.NOT_CONFIGURED.value,
        description,
        (
            f"{reason} Structured admin evidence is present."
            if attested
            else f"{reason} Structured admin evidence is also missing."
        ),
        (
            "Have the Entra admin complete or confirm the full registration, "
            "then rerun with Microsoft Graph read access when available."
        ),
    )


def _entra_error_results(message: str) -> list[CheckResult]:
    rows = (
        ("APP", "Entra application registration exists"),
        ("CLAIMS", "Entra access-token optional claims"),
        ("SCOPE", "Entra identifier URI and user_impersonation scope"),
        ("PREAUTH", "ServiceNow connector pre-authorization"),
    )
    return [
        _result(
            f"SN-DA-HRSD-ENTRA-{suffix}-001",
            Status.ERROR.value,
            description,
            message,
            "Restore read-only Microsoft Graph access and retry.",
        )
        for suffix, description in rows
    ]


def _identity_claim_candidates_contract(
    admin_setup: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    entra_handoff = _phase_handoff(admin_setup, "entra-registration")
    entra = entra_handoff.get("evidence")
    entra = entra if isinstance(entra, dict) else {}
    receipt = state.get("evidence", {}).get("identityClaimCandidates")
    receipt = receipt if isinstance(receipt, dict) else {}
    candidates = entra.get("tokenClaimCandidates")
    if (
        not _phase_attested(admin_setup, "entra-registration")
        or entra.get("tokenClaimEmissionConfirmed") is not True
        or not isinstance(candidates, list)
        or not candidates
    ):
        return None, (
            "The employee identity claim candidates or actual claim emission "
            "confirmation are missing."
        )
    if (
        receipt.get("kind") != "administrator-confirmed-claim-candidates"
        or receipt.get("entraAdministratorConfirmed") is not True
        or receipt.get("tokenClaimEmissionConfirmed") is not True
        or receipt.get("candidates") != candidates
        or receipt.get("candidateSetSha256")
        != entra.get("candidateSetSha256")
    ):
        return None, (
            "The scoped claim-candidate receipt does not match the Entra "
            "handoff."
        )
    for field, expected in (
        ("applicationClientId", _entra_client_id(admin_setup)),
    ):
        if str(receipt.get(field) or "") != str(expected or ""):
            return None, (
                "The Entra handoff does not match the scoped claim candidate "
                "receipt."
            )
    binding = receipt.get("binding")
    binding = binding if isinstance(binding, dict) else {}
    expected_binding = {
        "provider": state.get("provider"),
        "profile": state.get("profile"),
        "agentSlug": state.get("agentSlug"),
        "agentId": state.get("agentId"),
        "environmentId": state.get("environmentId"),
        "applicationClientId": _entra_client_id(admin_setup),
        "instanceName": (
            admin_setup.get("preflight", {}).get("instanceName")
            if isinstance(admin_setup.get("preflight"), dict)
            else None
        ),
    }
    if state.get("tenantId"):
        expected_binding["tenantId"] = state.get("tenantId")
    for field, expected in expected_binding.items():
        if not expected or str(binding.get(field) or "") != str(expected):
            return None, (
                "The scoped identity mapping receipt binding does not match "
                "the active lifecycle."
            )
    expected_hash = _identity_candidate_set_hash(
        application_client_id=receipt["applicationClientId"],
        candidates=list(receipt["candidates"]),
        binding=binding,
    )
    if receipt.get("candidateSetSha256") != expected_hash:
        return None, (
            "The scoped claim candidate hash does not match its bound values."
        )
    return receipt, None


def _identity_mapping_contract(
    admin_setup: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    candidates, error = _identity_claim_candidates_contract(
        admin_setup,
        state,
    )
    if error or candidates is None:
        return None, error
    mapping = state.get("evidence", {}).get("identityMapping")
    mapping = mapping if isinstance(mapping, dict) else {}
    oidc = _phase_handoff(
        admin_setup,
        "servicenow-oidc",
    ).get("evidence")
    oidc = oidc if isinstance(oidc, dict) else {}
    try:
        mapping_client_id = normalize_client_id(
            str(mapping.get("applicationClientId") or "")
        )
    except Exception:
        mapping_client_id = None
    if (
        mapping.get("kind") != "administrator-confirmed-identity-mapping"
        or mapping.get("status") != "servicenow-confirmed"
        or mapping.get("serviceNowAdministratorConfirmed") is not True
        or mapping_client_id != candidates.get("applicationClientId")
        or mapping.get("binding") != candidates.get("binding")
        or mapping.get("candidateSetSha256")
        != candidates.get("candidateSetSha256")
        or mapping.get("tokenClaimName") not in candidates["candidates"]
        or not mapping.get("serviceNowUserField")
        or oidc.get("claimMappingConfirmed") is not True
        or oidc.get("tokenClaimName") != mapping.get("tokenClaimName")
        or oidc.get("serviceNowUserField")
        != mapping.get("serviceNowUserField")
        or oidc.get("mappingRelationshipSha256")
        != mapping.get("relationshipSha256")
        or mapping.get("relationshipSha256")
        != _identity_mapping_relationship_hash(mapping)
    ):
        return None, (
            "The ServiceNow OIDC handoff does not match one exact selected "
            "claim and user-field pair from the Entra-confirmed candidates."
        )
    return mapping, None


def _entra_claim_result(
    admin_setup: dict[str, Any],
    state: dict[str, Any],
    *,
    claim_names: set[str] | None,
    graph_note: str = "",
) -> CheckResult:
    receipt, error = _identity_claim_candidates_contract(
        admin_setup,
        state,
    )
    description = "Entra employee identity claim candidates"
    if error or receipt is None:
        return _result(
            "SN-DA-HRSD-ENTRA-CLAIMS-001",
            Status.NOT_CONFIGURED.value,
            description,
            error or "The scoped claim candidate receipt is missing.",
            (
                "Have the Entra administrator confirm actual claim emission, "
                "then record the emitted employee identity claim candidates."
            ),
        )
    candidates = list(receipt["candidates"])
    observations = []
    for candidate in candidates:
        if claim_names is None:
            observation = graph_note or (
                "Microsoft Graph optionalClaims verification is unavailable."
            )
        elif candidate.casefold() in claim_names:
            observation = "listed in Microsoft Graph optionalClaims"
        else:
            observation = (
                "not listed in optionalClaims; a custom claims-mapping policy "
                "may emit it"
            )
        observations.append(f"{candidate}: {observation}")
    return _result(
        "SN-DA-HRSD-ENTRA-CLAIMS-001",
        Status.MANUAL.value,
        description,
        (
            "Confirmed employee identity claim candidates: "
            + "; ".join(observations)
            + ". The administrator confirmed actual claim emission. "
            "optionalClaims is configuration evidence and does not prove "
            "emitted token contents."
        ),
    )


def _entra_results(
    graph,
    admin_setup: dict[str, Any],
    state: dict[str, Any],
) -> list[CheckResult]:
    client_id = _entra_client_id(admin_setup)
    rows = (
        (
            "SN-DA-HRSD-ENTRA-APP-001",
            "Entra application registration exists",
        ),
        (
            "SN-DA-HRSD-ENTRA-CLAIMS-001",
            "Entra selected access-token claim",
        ),
        (
            "SN-DA-HRSD-ENTRA-SCOPE-001",
            "Entra identifier URI and user_impersonation scope",
        ),
        (
            "SN-DA-HRSD-ENTRA-PREAUTH-001",
            "ServiceNow connector pre-authorization",
        ),
    )
    if not client_id:
        return [
            _result(
                checkpoint_id,
                Status.NOT_CONFIGURED.value,
                description,
                "No Application client ID has been recorded.",
                "Record only the non-secret Application client ID.",
            )
            for checkpoint_id, description in rows
        ]
    try:
        normalized_client_id = normalize_client_id(client_id)
    except Exception as exc:
        return _entra_error_results(str(exc))
    if graph is None:
        return [
            (
                _entra_claim_result(
                    admin_setup,
                    state,
                    claim_names=None,
                    graph_note="Microsoft Graph verification is unavailable.",
                )
                if checkpoint_id == "SN-DA-HRSD-ENTRA-CLAIMS-001"
                else _entra_manual_or_missing(
                    admin_setup,
                    checkpoint_id,
                    description,
                    "Microsoft Graph verification is unavailable.",
                )
            )
            for checkpoint_id, description in rows
        ]

    try:
        applications = graph.get_all(
            "/applications",
            params={
                "$filter": f"appId eq '{normalized_client_id}'",
                "$select": (
                    "id,appId,displayName,signInAudience,identifierUris,"
                    "optionalClaims,api"
                ),
            },
            raise_on_permission_error=True,
        )
    except PermissionError:
        return [
            (
                _entra_claim_result(
                    admin_setup,
                    state,
                    claim_names=None,
                    graph_note=(
                        "Microsoft Graph denied read-only application access."
                    ),
                )
                if checkpoint_id == "SN-DA-HRSD-ENTRA-CLAIMS-001"
                else _entra_manual_or_missing(
                    admin_setup,
                    checkpoint_id,
                    description,
                    "Microsoft Graph denied read-only application access.",
                )
            )
            for checkpoint_id, description in rows
        ]
    except Exception as exc:
        return _entra_error_results(
            f"Unable to query Microsoft Graph: {type(exc).__name__}: {exc}"
        )

    if not applications:
        return [
            _result(
                checkpoint_id,
                Status.FAILED.value,
                description,
                (
                    "Microsoft Graph confirms that no application with the "
                    f"recorded client ID {normalized_client_id} exists."
                ),
                "Correct the client ID or have the Entra admin create the app.",
            )
            for checkpoint_id, description in rows
        ]
    application = applications[0]
    api = application.get("api")
    api = api if isinstance(api, dict) else {}
    scopes = api.get("oauth2PermissionScopes")
    scopes = scopes if isinstance(scopes, list) else []
    scope = next(
        (
            value
            for value in scopes
            if isinstance(value, dict)
            and value.get("value") == "user_impersonation"
            and value.get("isEnabled", True)
        ),
        None,
    )
    scope_id = str((scope or {}).get("id") or "")
    optional_claims = application.get("optionalClaims")
    optional_claims = (
        optional_claims if isinstance(optional_claims, dict) else {}
    )
    access_token_claims = optional_claims.get("accessToken")
    access_token_claims = (
        access_token_claims if isinstance(access_token_claims, list) else []
    )
    claim_names = {
        str(value.get("name") or "").casefold()
        for value in access_token_claims
        if isinstance(value, dict)
    }
    identifiers = {
        str(value).casefold()
        for value in application.get("identifierUris") or []
    }
    scope_ok = (
        f"api://{normalized_client_id}".casefold() in identifiers
        and bool(scope_id)
    )
    preauthorized = any(
        isinstance(value, dict)
        and str(value.get("appId") or "").casefold()
        == SERVICENOW_CONNECTOR_APP_ID.casefold()
        and scope_id
        in {
            str(permission_id)
            for permission_id in value.get("delegatedPermissionIds") or []
        }
        for value in api.get("preAuthorizedApplications") or []
    )
    def programmatic(
        checkpoint_id: str,
        description: str,
        passed: bool,
        failure: str,
    ) -> CheckResult:
        if not passed:
            return _result(
                checkpoint_id,
                Status.FAILED.value,
                description,
                failure,
                "Have the Entra admin correct this exact application setting.",
            )
        if not _phase_attested(admin_setup, "entra-registration"):
            return _result(
                checkpoint_id,
                Status.NOT_CONFIGURED.value,
                description,
                "Microsoft Graph verifies the setting, but explicit Maker reuse approval is not recorded.",
                "Confirm this exact existing setting with the admin and record it as reused.",
            )
        return _result(
            checkpoint_id,
            Status.PASSED.value,
            description,
            "Microsoft Graph read-only verification passed.",
        )

    results = [
        programmatic(
            rows[0][0],
            rows[0][1],
            (
                str(application.get("appId") or "").casefold()
                == normalized_client_id.casefold()
                and application.get("signInAudience") == "AzureADMyOrg"
            ),
            "The application is missing or is not single-tenant.",
        ),
        _entra_claim_result(
            admin_setup,
            state,
            claim_names=claim_names,
        ),
        programmatic(
            rows[2][0],
            rows[2][1],
            scope_ok,
            (
                "The application must expose api://<client-id> and an enabled "
                "user_impersonation scope."
            ),
        ),
        programmatic(
            rows[3][0],
            rows[3][1],
            preauthorized,
            (
                "The ServiceNow connector application is not pre-authorized "
                "for the user_impersonation scope."
            ),
        ),
    ]
    return results


def _oidc_result(
    admin_setup: dict[str, Any],
    state: dict[str, Any],
) -> CheckResult:
    handoff = _phase_handoff(admin_setup, "servicenow-oidc")
    missing = not _phase_attested(admin_setup, "servicenow-oidc")
    mapping = handoff.get("evidence")
    mapping = mapping if isinstance(mapping, dict) else {}
    if missing:
        status = Status.NOT_CONFIGURED.value
        result = "The complete ServiceNow OIDC admin handoff is missing."
    elif mapping.get("oidcCapabilityConfirmed") is not True:
        status = Status.NOT_CONFIGURED.value
        result = "The ServiceNow OIDC capability confirmation is missing."
    elif mapping.get("runbookCompleted") is not True:
        status = Status.NOT_CONFIGURED.value
        result = "The complete ServiceNow OIDC runbook attestation is missing."
    elif "claim" in mapping or "userField" in mapping:
        status = Status.NOT_CONFIGURED.value
        result = (
            "The OIDC handoff does not use the bounded privacy-minimized "
            "completion evidence contract."
        )
    elif mapping.get("mappingDetailsCollected") is not True:
        status = Status.NOT_CONFIGURED.value
        result = (
            "The legacy OIDC attestation does not contain the current "
            "two-name mapping confirmation."
        )
    elif mapping.get("claimMappingConfirmed") is not True:
        status = Status.NOT_CONFIGURED.value
        result = "The ServiceNow claim mapping confirmation is missing."
    else:
        receipt, error = _identity_mapping_contract(admin_setup, state)
        if error or receipt is None:
            status = Status.NOT_CONFIGURED.value
            result = error or (
                "The current two-name identity mapping receipt is missing."
            )
        else:
            status = Status.MANUAL.value
            result = (
                "The ServiceNow admin confirmed OIDC capability, "
                "security_admin elevation, provider metadata, User Claim "
                f"{receipt['tokenClaimName']!r} sourced from "
                f"the Entra-confirmed candidates, User Field "
                f"{receipt['serviceNowUserField']!r}, and a matching Active "
                "user. No employee value was returned."
            )
    return _result(
        "SN-DA-HRSD-OIDC-001",
        status,
        "ServiceNow OIDC provider and active-user mapping",
        result,
        (
            "Complete or re-verify the full guided ServiceNow OIDC runbook, "
            "then record the current two-name mapping handoff and bounded "
            "completion attestation."
            if status != Status.MANUAL.value
            else ""
        ),
    )


def _topics_result(
    summary: dict[str, Any],
    evidence: dict[str, Any],
    component_hash: str,
) -> CheckResult:
    total = summary["serviceNowTopicCount"]
    active = summary["activeServiceNowTopicCount"]
    topic_evidence = evidence.get("topics")
    keep_current = (
        isinstance(topic_evidence, dict)
        and topic_evidence.get("customerChoice") == "keep-current"
        and topic_evidence.get("boundComponentHash") == component_hash
    )
    if total and active == total:
        status = Status.PASSED.value
    elif total and keep_current:
        status = Status.MANUAL.value
    else:
        status = Status.NOT_CONFIGURED.value
    return _result(
        "SN-DA-HRSD-TOPICS-001",
        status,
        "ServiceNow HRSD topic readiness",
        f"{active}/{total} ServiceNow HRSD topics are Active.",
        "Enable the inactive HRSD topics or explicitly attest that their "
        "current states should be retained."
        if status != Status.PASSED.value
        else "",
    )


def _portal_result(
    components: dict[str, Any],
    admin_setup: dict[str, Any],
    state: dict[str, Any],
) -> CheckResult:
    preflight = admin_setup.get("preflight")
    preflight = preflight if isinstance(preflight, dict) else {}
    expected_instance = preflight.get("instanceName")
    try:
        portal = portal_configuration_summary(
            components,
            expected_instance_name=(
                expected_instance
                if isinstance(expected_instance, str)
                else None
            ),
        )
    except Exception as exc:
        return _result(
            "SN-DA-HRSD-PORTAL-001",
            Status.ERROR.value,
            "ServiceNow HRSD employee portal Base URI",
            f"Unable to inspect the exact portal configuration: "
            f"{type(exc).__name__}: {exc}",
            (
                "Open Copilot Studio Topics -> ServiceNow HRSD Setup "
                "Configurations and review the Set ServiceNow Portal BaseURI "
                "node without overwriting unrelated topic content."
            ),
        )
    confirmed_url = None
    if (
        portal["valid"]
        and isinstance(expected_instance, str)
        and expected_instance
    ):
        try:
            topic = _portal_topic_component(components)
            current_url = normalize_portal_url(
                _portal_literal_value(topic),
                expected_instance_name=expected_instance,
            )
            confirmed_url = portal_confirmation_url(
                state,
                topic=topic,
                current_portal_url=current_url,
                expected_instance_name=expected_instance,
            )
        except Exception:
            confirmed_url = None
    expected_url = confirmed_url or _latest_requested_portal_url(state)
    if portal["valid"] and portal["path"] == "/" and not confirmed_url:
        return _result(
            "SN-DA-HRSD-PORTAL-001",
            Status.NOT_CONFIGURED.value,
            "ServiceNow HRSD employee portal Base URI",
            "The Portal BaseURI is the ServiceNow instance root, but the "
            "lifecycle has no evidence that the administrator explicitly "
            "confirmed that exact root URL for the employee portal.",
            "Confirm the exact root URL through the portal phase before "
            "recording completion.",
        )
    if portal["valid"] and expected_url:
        try:
            actual_url = normalize_portal_url(
                str(portal["origin"]) + str(portal["path"]),
                expected_instance_name=str(expected_instance),
            )
            normalized_expected = normalize_portal_url(
                expected_url,
                expected_instance_name=str(expected_instance),
            )
        except Exception as exc:
            return _result(
                "SN-DA-HRSD-PORTAL-001",
                Status.ERROR.value,
                "ServiceNow HRSD employee portal Base URI",
                "Unable to verify the current portal URL against the URL "
                f"requested for this phase: {type(exc).__name__}: {exc}",
                "Review the latest portal transaction and the exact authored "
                "topic value before retrying.",
            )
        if actual_url != normalized_expected:
            return _result(
                "SN-DA-HRSD-PORTAL-001",
                Status.NOT_CONFIGURED.value,
                "ServiceNow HRSD employee portal Base URI",
                "The current Portal BaseURI is valid but does not match the "
                "administrator-confirmed URL requested for this phase.",
                "Set the exact requested employee portal URL, save the topic, "
                "and run a fresh read-only verification.",
            )
    if portal["valid"]:
        status = Status.PASSED.value
        result = (
            "The exact Setup Configurations topic has an HTTPS employee portal "
            f"path on the confirmed ServiceNow instance: {portal['path']}."
        )
        remediation = ""
    elif portal["reason"] == "wrong-instance":
        status = Status.FAILED.value
        result = (
            "The configured Portal BaseURI targets a different ServiceNow "
            "instance."
        )
        remediation = (
            "Set the exact administrator-confirmed employee portal URL on the "
            "confirmed ServiceNow instance."
        )
    elif portal["reason"] == "invalid-url":
        status = Status.FAILED.value
        result = "The configured Portal BaseURI is not a safe plain HTTPS URL."
        remediation = (
            "Set a plain HTTPS employee portal URL without credentials, query, "
            "or fragment."
        )
    else:
        status = Status.NOT_CONFIGURED.value
        result = (
            "The exact Setup Configurations topic does not contain an "
            "administrator-confirmed employee portal URL."
        )
        remediation = (
            "Provide the exact employee portal URL. A root instance URL is "
            "allowed only when the administrator explicitly supplies it; "
            "never infer /sp or /esc."
        )
    return _result(
        "SN-DA-HRSD-PORTAL-001",
        status,
        "ServiceNow HRSD employee portal Base URI",
        result,
        remediation,
    )


def _latest_requested_portal_url(state: dict[str, Any]) -> str | None:
    transactions = state.get("transactions")
    transactions = transactions if isinstance(transactions, dict) else {}
    portal_transactions = transactions.get("portal")
    portal_transactions = (
        portal_transactions if isinstance(portal_transactions, dict) else {}
    )
    candidates = [
        transaction
        for transaction in portal_transactions.values()
        if isinstance(transaction, dict)
        and transaction.get("status")
        in {"committed", "failed-unchanged", "reconciliation-required"}
        and isinstance(transaction.get("requestedPortalUrl"), str)
        and transaction["requestedPortalUrl"]
    ]
    if not candidates:
        return None
    latest = max(
        candidates,
        key=lambda transaction: str(transaction.get("preparedAt") or ""),
    )
    return str(latest["requestedPortalUrl"])


def _selected_connection(
    evidence: dict[str, Any],
    connections: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    credential = evidence.get("credential")
    credential = credential if isinstance(credential, dict) else {}
    selected_id = str(credential.get("connectionId") or "").casefold()
    match = next(
        (
            record
            for record in connections
            if str(record.get("name") or "").casefold() == selected_id
        ),
        None,
    )
    return match, credential


def _credential_result(
    evidence: dict[str, Any],
    admin_setup: dict[str, Any],
    connections: list[dict[str, Any]],
    error: str,
) -> CheckResult:
    match, credential = _selected_connection(evidence, connections)
    if error:
        status = Status.ERROR.value
        result = error
    elif not _phase_attested(admin_setup, "credential"):
        status = Status.NOT_CONFIGURED.value
        result = "The bundled physical-connection handoff is incomplete."
    elif not credential.get("connectionId"):
        status = Status.NOT_CONFIGURED.value
        result = "No ServiceNow credential has been selected."
    elif match is None:
        status = Status.NOT_CONFIGURED.value
        result = "The selected ServiceNow credential is not visible."
    elif (
        _connection_status(match) != "Connected"
        or _auth_mode(match) != AUTH_MODE
    ):
        status = Status.NOT_CONFIGURED.value
        result = (
            "The selected ServiceNow credential is not a Connected Microsoft "
            "Entra ID User Login connection."
        )
    else:
        properties = match.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        parameter_set = properties.get("connectionParametersSet")
        parameter_set = (
            parameter_set if isinstance(parameter_set, dict) else {}
        )
        values = parameter_set.get("values")
        values = values if isinstance(values, dict) else {}

        def parameter(name: str) -> Any:
            value = values.get(name)
            return value.get("value") if isinstance(value, dict) else None

        expected_instance = (
            (admin_setup.get("preflight") or {}).get("instanceName")
            if isinstance(admin_setup.get("preflight"), dict)
            else None
        )
        expected_client_id = _entra_client_id(admin_setup)
        actual_instance = parameter("token:InstanceName") or parameter(
            "instance"
        )
        actual_resource = parameter("token:ResourceUri")
        if not expected_instance or not expected_client_id:
            status = Status.NOT_CONFIGURED.value
            result = (
                "The lifecycle does not have a confirmed Instance Name and "
                "Application client ID for exact connection verification."
            )
        elif not actual_instance or not actual_resource:
            status = Status.NOT_CONFIGURED.value
            result = (
                "Direct connector inventory did not expose the connection's "
                "Instance Name and Resource URI."
            )
        else:
            try:
                values_match = (
                    normalize_instance_name(str(actual_instance))
                    == expected_instance
                    and normalize_client_id(str(actual_resource))
                    == expected_client_id
                )
            except Exception:
                values_match = False
            if not values_match:
                status = Status.NOT_CONFIGURED.value
                result = (
                    "The Connected credential targets a different Instance "
                    "Name or Resource URI. Resource URI must be the exact "
                    "Application client ID, not an api:// URI or object ID."
                )
            else:
                status = Status.PASSED.value
                result = (
                    "Direct connector inventory verifies Connected "
                    "entraIDUserLogin with the exact Instance Name and "
                    "Application client ID."
                )
    return _result(
        "SN-DA-HRSD-CREDENTIAL-001",
        status,
        "ServiceNow HRSD credential health",
        result,
        (
            "Create or select a Connected Microsoft Entra ID User Login "
            "ServiceNow credential."
            if status != Status.PASSED.value
            else ""
        ),
    )


def _binding_evaluation(
    record: dict[str, Any],
    draft_semantic_hash: str,
    connection_id: str | None = None,
) -> str:
    binding = record.get("binding")
    if not isinstance(binding, dict):
        return "binding-missing"
    if binding.get("draftSemanticHash") != draft_semantic_hash:
        return "revision-stale"

    nested_connection_id = str(binding.get("connectionId") or "")
    legacy_connection_id = str(record.get("connectionId") or "")
    if (
        nested_connection_id
        and legacy_connection_id
        and nested_connection_id.casefold() != legacy_connection_id.casefold()
    ):
        return "connection-conflict"

    recorded_connection_id = nested_connection_id or legacy_connection_id
    if connection_id is not None:
        if not recorded_connection_id:
            return "connection-missing"
        if recorded_connection_id.casefold() != connection_id.casefold():
            return "connection-mismatch"
    return "valid"


def _agent_connection_result(
    evidence: dict[str, Any],
    credential_check: CheckResult,
    draft_semantic_hash: str,
) -> CheckResult:
    record = evidence.get("agentConnection")
    if credential_check.status not in {
        Status.PASSED.value,
    }:
        status = credential_check.status
        result = credential_check.result
    elif not isinstance(record, dict) or not record.get("makerAttested"):
        status = Status.NOT_CONFIGURED.value
        result = "Current maker evidence for the agent's ServiceNow row is absent."
    else:
        binding_evaluation = _binding_evaluation(
            record,
            draft_semantic_hash,
            str((evidence.get("credential") or {}).get("connectionId") or ""),
        )
    if (
        credential_check.status == Status.PASSED.value
        and isinstance(record, dict)
        and record.get("makerAttested")
        and binding_evaluation != "valid"
    ):
        status = Status.NOT_CONFIGURED.value
        if binding_evaluation == "revision-stale":
            result = (
                "The prior Agent Connect attestation is stale for this "
                "saved draft."
            )
        elif binding_evaluation == "connection-conflict":
            result = (
                "The Agent Connect evidence contains conflicting connection "
                "identities."
            )
        elif binding_evaluation == "connection-mismatch":
            result = (
                "The Agent Connect evidence belongs to a different selected "
                "credential."
            )
        else:
            result = (
                "The Agent Connect evidence does not identify the selected "
                "credential."
            )
    elif credential_check.status == Status.PASSED.value and isinstance(
        record, dict
    ) and record.get("makerAttested"):
        status = Status.MANUAL.value
        result = "Maker attested that the ServiceNow row currently shows Connected."
    return _result(
        "SN-DA-HRSD-AGENT-CONNECTION-001",
        status,
        "ServiceNow credential connected to the selected agent",
        result,
        "Confirm the ServiceNow row in Copilot Studio Connection settings.",
    )


def _publish_result(
    evidence: dict[str, Any],
    component_hash: str,
    draft_semantic_hash: str,
    connection_binding_hash: str | None,
) -> CheckResult:
    record = evidence.get("publish")
    test_outcome = _test_evidence_outcome(
        evidence,
        draft_semantic_hash,
        connection_binding_hash,
    )
    published_hash = (
        record.get("publishedComponentHash") or record.get("componentHash")
        if isinstance(record, dict)
        else None
    )
    semantic_bridge_current = bool(
        isinstance(record, dict)
        and record.get("testedDraftSemanticHash") == draft_semantic_hash
        and record.get("publishedSemanticHash") == draft_semantic_hash
    )
    if test_outcome == "fail":
        status = Status.FAILED.value
        result = (
            "The maker recorded Not pass for the current saved draft and "
            "selected connection; publish is blocked."
        )
    elif test_outcome != "pass":
        status = Status.NOT_CONFIGURED.value
        result = (
            "A current passing Test pane result is required before publish."
        )
    elif not isinstance(record, dict) or published_hash != component_hash:
        status = Status.NOT_CONFIGURED.value
        result = (
            "The current tested draft identity has no matching publish "
            "receipt."
        )
    elif record.get("status") == "needs_remediation":
        status = Status.FAILED.value
        result = "Publish needs remediation; automatic unpublish is unavailable."
    elif not semantic_bridge_current:
        status = Status.NOT_CONFIGURED.value
        result = (
            "The current tested draft identity has no matching publish "
            "receipt."
        )
    elif record.get("status") == "completed":
        status = Status.PASSED.value
        result = "The current component revision has a definitive publish receipt."
    elif record.get("status") == "confirmation-required":
        status = Status.MANUAL.value
        result = "Publish was accepted but requires current maker confirmation."
    else:
        status = Status.FAILED.value
        result = "Publish needs remediation; automatic unpublish is unavailable."
    return _result(
        "SN-DA-HRSD-PUBLISH-001",
        status,
        "ServiceNow HRSD agent publish status",
        result,
        "Review Copilot Studio publish details and republish only after explicit confirmation.",
    )


def _test_result(
    evidence: dict[str, Any],
    draft_semantic_hash: str,
    connection_binding_hash: str | None,
    topics_check: CheckResult,
    portal_check: CheckResult,
    credential_check: CheckResult,
    agent_connection_check: CheckResult,
) -> CheckResult:
    prerequisite = _test_prerequisite_gate(
        topics_check,
        portal_check,
        credential_check,
        agent_connection_check,
    )
    if prerequisite is not None:
        return prerequisite
    outcome = _test_evidence_outcome(
        evidence,
        draft_semantic_hash,
        connection_binding_hash,
    )
    if outcome == "stale":
        status = Status.NOT_CONFIGURED.value
        result = (
            "No current Test pane evidence is bound to this saved draft and "
            "selected connection."
        )
    elif outcome == "invalid":
        status = Status.NOT_CONFIGURED.value
        result = (
            "Current Test pane evidence does not use the privacy-safe "
            "bounded evidence contract."
        )
    elif outcome == "pass":
        status = Status.MANUAL.value
        result = "Maker recorded a passing HRSD Test pane result."
    else:
        status = Status.FAILED.value
        result = "Maker recorded a failing HRSD Test pane result."
    return _result(
        "SN-DA-HRSD-TEST-001",
        status,
        "ServiceNow HRSD Test pane result",
        result,
        "Run a low-side-effect HRSD prompt in the Test pane and record the current result.",
    )


def _test_evidence_outcome(
    evidence: dict[str, Any],
    draft_semantic_hash: str,
    connection_binding_hash: str | None,
) -> str:
    """Return stale, invalid, pass, or fail for current bounded Test evidence."""
    record = evidence.get("test")
    binding = record.get("binding") if isinstance(record, dict) else None
    if (
        not isinstance(record, dict)
        or not isinstance(binding, dict)
        or binding.get("draftSemanticHash") != draft_semantic_hash
        or connection_binding_hash is None
        or binding.get("connectionBindingHash") != connection_binding_hash
    ):
        return "stale"
    if (
        record.get("promptCategory") != _TEST_PROMPT_CATEGORY
        or "prompt" in record
        or "details" in record
    ):
        return "invalid"
    failure_category = record.get("failureCategory")
    if record.get("result") == "pass":
        return "pass" if failure_category is None else "invalid"
    if record.get("result") == "fail":
        return (
            "fail"
            if failure_category is None
            or failure_category
            in {
                "authentication",
                "permission",
                "empty-result",
                "connector",
                "unexpected",
            }
            else "invalid"
        )
    return "invalid"


def _test_prerequisite_gate(
    topics_check: CheckResult,
    portal_check: CheckResult,
    credential_check: CheckResult,
    agent_connection_check: CheckResult,
) -> CheckResult | None:
    prerequisites = (
        ("credential", credential_check, {Status.PASSED.value}),
        (
            "topics",
            topics_check,
            {Status.PASSED.value, Status.MANUAL.value},
        ),
        ("portal Base URI", portal_check, {Status.PASSED.value}),
        (
            "Agent Connect",
            agent_connection_check,
            {Status.MANUAL.value},
        ),
    )
    passthrough = {
        Status.FAILED.value,
        Status.BLOCKED.value,
        Status.ERROR.value,
        Status.WARNING.value,
    }
    for label, check, accepted in prerequisites:
        if check.status in accepted:
            continue
        status = (
            check.status
            if check.status in passthrough
            else Status.NOT_CONFIGURED.value
        )
        return _result(
            "SN-DA-HRSD-TEST-001",
            status,
            "ServiceNow HRSD Test pane result",
            (
                f"Current {label} prerequisite is {check.status}: "
                f"{check.result}"
            ),
            check.remediation,
            format_recovery=False,
        )
    return None
