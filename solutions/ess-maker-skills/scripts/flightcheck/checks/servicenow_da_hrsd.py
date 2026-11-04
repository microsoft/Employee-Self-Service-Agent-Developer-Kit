# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lifecycle checkpoints for the DA HR ServiceNow HRSD provider."""

from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from connect_servicenow_da import (
    AUTH_MODE,
    CONNECTOR_NAME,
    HRSD_PROFILE,
    ITSM_PROFILE,
    ServiceNowProductProfile,
    _agent_binding_identity_hash,
    _connection_binding_hash,
    _draft_semantic_hash,
    _identity_candidate_set_hash,
    _identity_mapping_relationship_hash,
    _portal_literal_value,
    _portal_topic_component,
    _servicenow_topic_changes,
    _safe_identity_name,
    normalize_client_id,
    normalize_instance_name,
    normalize_portal_url,
    portal_confirmation_url,
    portal_configuration_summary,
    product_profile_context,
    required_servicenow_prerequisites,
)

from ..agent_scope import validate_agent_slug
from ..runner import CheckResult, Priority, Role, Status


_ROLES = [Role.ESS_MAKER.value, Role.SERVICENOW_ADMIN.value]


@dataclass(frozen=True)
class CheckProfile:
    """Per-product identity and wording for the shared ServiceNow DA checks."""

    service: ServiceNowProductProfile
    id_prefix: str
    category: str
    family: str
    agent_short: str
    package_remediation: str | None = None
    has_plugin: bool = True

    @property
    def product(self) -> str:
        return self.service.product_name

    @property
    def provider_key(self) -> str:
        return self.service.provider_key

    @property
    def schema_name(self) -> str:
        return self.service.schema_name

    @property
    def test_prompt_category(self) -> str:
        return self.service.test_prompt_category

    @property
    def install_action(self) -> str:
        return (
            f"Install the {self.product} extension for this exact "
            f"{self.agent_short} agent."
        )

    @property
    def package_action(self) -> str:
        return self.package_remediation or self.install_action

    def cid(self, suffix: str) -> str:
        return f"{self.id_prefix}-{suffix}-001"


HR_CHECK_PROFILE = CheckProfile(
    service=HRSD_PROFILE,
    id_prefix="SN-DA-HRSD",
    category="ServiceNow DA HRSD",
    family="HRSD",
    agent_short="HR",
)
IT_CHECK_PROFILE = CheckProfile(
    service=ITSM_PROFILE,
    id_prefix="SN-DA-ITSM",
    category="ServiceNow DA ITSM",
    family="ITSM",
    agent_short="IT",
    package_remediation=(
        "Verify the exact Employee Self-Service (IT) agent contains the "
        "built-in ServiceNow ITSM topics."
    ),
    has_plugin=False,
)
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
        "step": "Microsoft Entra identity handoff",
        "owner": "Microsoft Entra Application Administrator or higher",
        "where": (
            "Microsoft Entra admin center -> App registrations -> the App A "
            "application identified by the recorded Application (client) ID"
        ),
        "values": (
            "Use the non-secret Application client ID recorded for this "
            "lifecycle. If it is absent or invalid, the Entra admin must return "
            "the correct App A client ID through the protected handoff. Also "
            "return exactly one explicit safe User Claim name; never return "
            "`aud`, a personal claim value, client secret, token, certificate, "
            "or PFX."
        ),
        "success": (
            "The current target-bound handoff contains one valid Application "
            "client ID GUID and one explicit safe User Claim name, with "
            "matching binding, provenance, and hashes."
        ),
    },
    "OIDC": {
        "step": "ServiceNow OIDC and claim-to-field mapping",
        "owner": "ServiceNow Admin / security_admin",
        "where": (
            "ServiceNow -> All -> System OAuth -> Application Registry, then "
            "the ServiceNow administrator identity handoff"
        ),
        "values": (
            "Record the locked Entra-confirmed claim name and the exact "
            "internal ServiceNow sys_user field selected by the ServiceNow "
            "admin. If the field is unknown, obtain it through the protected "
            "handoff; never return an employee identifier or token value."
        ),
        "success": (
            "The bounded receipt proves one current claim-name/user-field "
            "pair with matching target binding, provenance, candidate hash, "
            "and relationship hash."
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


def _recovery_key(checkpoint_id: str, profile: CheckProfile) -> str:
    suffix = checkpoint_id.removeprefix(f"{profile.id_prefix}-").removesuffix(
        "-001"
    )
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
    *,
    profile: CheckProfile,
    category_override: str | None = None,
) -> str:
    if status not in _RECOVERY_STATUSES:
        return action
    guidance = _RECOVERY_GUIDANCE.get(_recovery_key(checkpoint_id, profile))
    if guidance is None:
        return action
    category = category_override or _recovery_category(status, result)
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
    profile: CheckProfile,
    format_recovery: bool = True,
    recovery_category: str | None = None,
    roles: list[str] | None = None,
    evidence: dict[str, Any] | None = None,
) -> CheckResult:
    if format_recovery:
        remediation = _actionable_remediation(
            checkpoint_id,
            status,
            result,
            remediation,
            category_override=recovery_category,
            profile=profile,
        )
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category=profile.category,
        priority=Priority.HIGH.value,
        status=status,
        description=description,
        result=result,
        remediation=remediation,
        evidence=evidence or {},
        roles=list(roles or _ROLES),
    )


def _active_agent(runner) -> tuple[str, dict[str, Any]] | None:
    target_context = getattr(runner, "servicenow_target_context", None)
    if isinstance(target_context, dict):
        target = target_context.get("target")
        target = target if isinstance(target, dict) else {}
        source_slug = str(
            target_context.get("sourceAgentSlug")
            or getattr(runner, "agent_slug", "")
            or ""
        )
        try:
            source_slug = validate_agent_slug(source_slug)
        except ValueError:
            return None
        if all(
            isinstance(target.get(key), str) and target[key]
            for key in ("agentId", "schemaName")
        ):
            return source_slug, {
                "slug": source_slug,
                "botId": target["agentId"],
                "schemaName": target["schemaName"],
                "realm": target_context.get("realm"),
            }
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


def _load_state(slug: str, *, profile: CheckProfile) -> dict[str, Any]:
    path = (
        Path(".local/connect")
        / profile.provider_key
        / "agents"
        / slug
        / "lifecycle.json"
    )
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _target_context(runner) -> dict[str, Any]:
    value = getattr(runner, "servicenow_target_context", None)
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
    profile: CheckProfile,
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
    key = (profile.provider_key, agent_id.casefold(), environment_id.casefold())
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


def run_servicenow_da_hrsd_checks(
    runner, profile: CheckProfile = HR_CHECK_PROFILE
) -> list[CheckResult]:
    # The snow helpers read the active product profile; scope it to this run.
    with product_profile_context(profile.service.key):
        return _run_checks(runner, profile)


def _run_checks(runner, profile: CheckProfile) -> list[CheckResult]:
    target = getattr(runner, "checkpoint_target", None)
    target_context = _target_context(runner)
    target_mode = bool(target_context)
    selected = _active_agent(runner)
    if selected is None:
        return _all_unavailable(
            Status.FAILED.value,
            "The selected agent could not be resolved.",
            f"Select the exact editable ESS {profile.agent_short} agent and rerun the checkpoint.",
            target=target,
            profile=profile,
        )
    slug, agent = selected
    schema = str(
        agent.get("schemaName") or agent.get("schema_name") or ""
    ).casefold()
    accepted_schemas = {profile.schema_name.casefold()}
    if target_mode:
        realm = str(target_context.get("realm") or "").casefold()
        if realm:
            accepted_schemas.add(f"{profile.schema_name}_{realm}".casefold())
    if schema not in accepted_schemas:
        return _all_unavailable(
            Status.NOT_CONFIGURED.value,
            f"The selected agent '{slug}' is not the ESS DA {profile.agent_short} agent.",
            f"Select the Employee Self-Service {profile.agent_short} agent.",
            target=target,
            profile=profile,
        )
    agent_id = str(agent.get("botId") or agent.get("id") or "")
    if not agent_id:
        return _all_unavailable(
            Status.FAILED.value,
            f"The selected {profile.agent_short} agent has no AgentBuilder ID.",
            "Refresh the local setup handoff for this agent.",
            target=target,
            profile=profile,
        )
    needs_inventory = target in {
        profile.cid("CREDENTIAL"),
        profile.cid("AGENT-CONNECTION"),
        profile.cid("TEST"),
        None,
    }
    target_identity = target_context.get("target")
    target_identity = (
        target_identity if isinstance(target_identity, dict) else {}
    )
    environment_id = str(
        target_identity.get("environmentId")
        if target_mode
        else getattr(runner, "env_id", None)
        or ""
    )
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
        profile=profile,
    )
    if component_error is not None or components is None:
        error = component_error or RuntimeError("Component state is unavailable.")
        return _all_unavailable(
            Status.ERROR.value,
            f"Unable to inspect the {profile.agent_short} agent: "
            f"{type(error).__name__}: {error}",
            "Verify AgentBuilder access to the selected environment and retry.",
            target=target,
            profile=profile,
        )
    try:
        topic_changes = _servicenow_topic_changes(components)
        if not topic_changes:
            return _all_unavailable(
                Status.NOT_CONFIGURED.value,
                f"The selected {profile.agent_short} agent '{slug}' has no "
                f"{profile.product} topics.",
                profile.install_action,
                target=target,
                profile=profile,
                package_remediation=profile.package_action,
            )
        summary = {
            "serviceNowTopicCount": len(topic_changes),
            "activeServiceNowTopicCount": sum(
                1
                for change in topic_changes
                if isinstance(change.get("component"), dict)
                and change["component"].get("state") == "Active"
                and change["component"].get("status") == "Active"
            ),
        }
    except Exception as exc:
        return _all_unavailable(
            Status.ERROR.value,
            f"Unable to inspect the {profile.agent_short} agent: {type(exc).__name__}: {exc}",
            "Verify AgentBuilder access to the selected environment and retry.",
            target=target,
            profile=profile,
        )

    state = _load_state(
        str(target_context.get("sourceAgentSlug") or slug),
        profile=profile,
    )
    evidence = state.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    admin_setup = state.get("adminSetup")
    admin_setup = admin_setup if isinstance(admin_setup, dict) else {}
    if target_mode:
        admin_setup = copy.deepcopy(admin_setup)
        expected_instance = str(
            target_context.get("expectedInstanceName") or ""
        )
        expected_client_id = str(
            target_context.get("expectedApplicationClientId") or ""
        )
        if expected_instance:
            admin_setup.setdefault("preflight", {})[
                "instanceName"
            ] = expected_instance
        if expected_client_id:
            handoffs = admin_setup.setdefault("phaseHandoffs", {})
            entra = handoffs.setdefault("entra-registration", {})
            entra_evidence = entra.setdefault("evidence", {})
            entra_evidence["clientId"] = expected_client_id
    if target == profile.cid("PKG"):
        return [_package_result(slug, summary, profile=profile)]
    if target == profile.cid("ADMIN-PREFLIGHT"):
        return [_preflight_result(admin_setup, profile=profile)]
    if target == profile.cid("PLUGIN"):
        return (
            [_plugin_result(admin_setup, profile=profile)]
            if profile.has_plugin
            else []
        )
    if target == profile.cid("ENTRA-SETUP"):
        return [_entra_setup_result(admin_setup, state, profile=profile)]
    if target == profile.cid("OIDC"):
        return [_oidc_result(admin_setup, state, profile=profile)]
    if target == profile.cid("PORTAL"):
        return [_portal_result(components, admin_setup, state, profile=profile)]

    component_hash = (
        _hash(components)
        if target
        in {
            profile.cid("TOPICS"),
            profile.cid("TEST"),
            profile.cid("PUBLISH"),
            None,
        }
        else ""
    )
    if target == profile.cid("TOPICS"):
        return [_topics_result(summary, evidence, component_hash, profile=profile)]
    if target == profile.cid("PUBLISH"):
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
                f"Unable to inspect the {profile.agent_short} agent draft identity: "
                f"{type(exc).__name__}: {exc}",
                f"Verify the selected {profile.agent_short} agent component state and retry.",
                target=target,
                profile=profile,
            )
        return [
            _publish_result(
                evidence,
                component_hash,
                draft_semantic_hash,
                current_connection_binding_hash,
                profile=profile,
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
        require_handoff=not target_mode,
        profile=profile,
    )
    if target == profile.cid("CREDENTIAL"):
        return [credential_result]

    needs_draft_identity = (
        target in {
            profile.cid("AGENT-CONNECTION"),
            profile.cid("TEST"),
            None,
        }
        and not target_mode
    )
    draft_semantic_hash = ""
    binding_identity_sha256 = ""
    current_connection_binding_hash = None
    identity_inspection_error: str | None = None
    if needs_draft_identity:
        try:
            draft_semantic_hash = _draft_semantic_hash(components)
            binding_identity_sha256 = _agent_binding_identity_hash(
                {
                    "agent": {
                        "id": agent.get("botId"),
                        "workspace_slug": slug,
                    },
                    "environment": {
                        "id": str(getattr(runner, "env_id", None) or "")
                    },
                },
                state,
                components,
            )
            if target in {profile.cid("TEST"), None}:
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
            identity_inspection_error = (
                f"Unable to inspect the {profile.agent_short} agent binding/final-configuration "
                f"identity: {type(exc).__name__}: {exc}"
            )
            if target is not None:
                return _all_unavailable(
                    Status.ERROR.value,
                    identity_inspection_error,
                    (
                        f"Verify the selected {profile.agent_short} agent connection-reference "
                        "and component state, then retry this checkpoint."
                    ),
                    target=target,
                    profile=profile,
                )

    agent_connection_result = (
        _target_agent_connection_result(
            target_context,
            credential_result,
            profile=profile,
        )
        if target_mode
        else
        _result(
            profile.cid("AGENT-CONNECTION"),
            Status.ERROR.value,
            "ServiceNow credential connected to the selected agent",
            identity_inspection_error,
            (
                f"Verify the selected {profile.agent_short} agent connection-reference and "
                "binding metadata, then retry."
            ),
            profile=profile,
        )
        if identity_inspection_error
        else _agent_connection_result(
            evidence,
            credential_result,
            binding_identity_sha256,
            profile=profile,
        )
    )
    if target == profile.cid("AGENT-CONNECTION"):
        return [agent_connection_result]

    topics_result = _topics_result(summary, evidence, component_hash, profile=profile)
    portal_result = _portal_result(components, admin_setup, state, profile=profile)
    if target == profile.cid("TEST"):
        if target_mode:
            return [
                _target_test_result(
                    target_context,
                    topics_result,
                    portal_result,
                    credential_result,
                    agent_connection_result,
                    profile=profile,
                )
            ]
        return [
            _test_result(
                evidence,
                draft_semantic_hash,
                current_connection_binding_hash,
                topics_result,
                portal_result,
                credential_result,
                agent_connection_result,
                profile=profile,
            )
        ]
    test_result = (
        _result(
            profile.cid("TEST"),
            Status.ERROR.value,
            f"{profile.product} Test pane result",
            identity_inspection_error,
            (
                f"Verify the selected {profile.agent_short} agent connection-reference and "
                "final component identity, then retry."
            ),
            profile=profile,
        )
        if identity_inspection_error
        else _test_result(
            evidence,
            draft_semantic_hash,
            current_connection_binding_hash,
            topics_result,
            portal_result,
            credential_result,
            agent_connection_result,
            profile=profile,
        )
    )
    return [
        _package_result(slug, summary, profile=profile),
        _preflight_result(admin_setup, profile=profile),
        *(
            [_plugin_result(admin_setup, profile=profile)]
            if profile.has_plugin
            else []
        ),
        _entra_setup_result(admin_setup, state, profile=profile),
        _oidc_result(admin_setup, state, profile=profile),
        credential_result,
        agent_connection_result,
        topics_result,
        portal_result,
        test_result,
        (
            _result(
                profile.cid("PUBLISH"),
                Status.ERROR.value,
                f"{profile.product} publish evidence",
                identity_inspection_error,
                (
                    f"Verify the selected {profile.agent_short} agent connection-reference and "
                    "final component identity, then retry."
                ),
                profile=profile,
            )
            if identity_inspection_error
            else _publish_result(
                evidence,
                component_hash,
                draft_semantic_hash,
                current_connection_binding_hash,
                profile=profile,
            )
        ),
    ]


def _all_unavailable(
    status: str,
    result: str,
    remediation: str,
    *,
    profile: CheckProfile,
    package_remediation: str | None = None,
    target: str | None = None,
) -> list[CheckResult]:
    ids = (
        "PKG",
        "ADMIN-PREFLIGHT",
        "PLUGIN",
        "ENTRA-SETUP",
        "OIDC",
        "CREDENTIAL",
        "AGENT-CONNECTION",
        "TOPICS",
        "PORTAL",
        "TEST",
        "PUBLISH",
    )
    return _target_rows(
        target,
        [
            _result(
                profile.cid(suffix),
                status,
                f"{profile.product} {suffix.lower()} readiness",
                result,
                package_remediation
                if suffix == "PKG" and package_remediation
                else remediation,
                profile=profile,
            )
            for suffix in ids
            if suffix != "PLUGIN" or profile.has_plugin
        ],
    )


def _package_result(
    slug: str, summary: dict[str, Any], *, profile: CheckProfile
) -> CheckResult:
    count = summary["serviceNowTopicCount"]
    passed = bool(count)
    return _result(
        profile.cid("PKG"),
        Status.PASSED.value if passed else Status.NOT_CONFIGURED.value,
        f"{profile.product} package installed for the selected DA "
        f"{profile.agent_short} agent",
        (
            f"Selected {profile.agent_short} agent '{slug}' contains {count} "
            f"{profile.product} topic(s)."
        ),
        profile.package_action if not count else "",
        profile=profile,
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


def _preflight_result(admin_setup: dict[str, Any], *, profile: CheckProfile) -> CheckResult:
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
        profile.cid("ADMIN-PREFLIGHT"),
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
        profile=profile,
    )


def _plugin_result(admin_setup: dict[str, Any], *, profile: CheckProfile) -> CheckResult:
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
        profile.cid("PLUGIN"),
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
            else (
                "Owner: ServiceNow Admin. Where/how: ServiceNow Application "
                "Manager -> Human Resources Scoped App: Core. Expected "
                "runbook: src/skills/connect/servicenow-da-hrsd/actions/"
                "verify-plugin-prerequisites.md. Expected "
                "evidence: one current non-secret admin confirmation with "
                "plugin ID com.sn_hr_core, Version Details Installed, the "
                "installed-and-ready message, source, and timestamp. "
                "Completion: every value matches the current HR target; this "
                "result remains Manual."
            )
        ),
        roles=[Role.SERVICENOW_ADMIN.value],
        profile=profile,
    )


def _entra_client_id(admin_setup: dict[str, Any]) -> str:
    evidence = _phase_handoff(
        admin_setup,
        "entra-registration",
    ).get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    value = evidence.get("clientId")
    return str(value or "")


def _entra_error_result(message: str, *, profile: CheckProfile) -> CheckResult:
    return _result(
        profile.cid("ENTRA-SETUP"),
        Status.ERROR.value,
        "Entra User Login application setup",
        message,
        (
            "The Entra administrator verifies and returns the correct "
            "Application (client) ID GUID plus one explicit safe User Claim "
            "name for the current target. The Maker re-imports or updates the "
            "target-bound handoff, then retries only this Entra setup check."
        ),
        recovery_category="Invalid configuration input",
        roles=[Role.ENTRA_ADMIN.value, Role.ESS_MAKER.value],
        profile=profile,
    )


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
        or not isinstance(candidates, list)
        or len(candidates) != 1
    ):
        return None, (
            "The current Entra identity handoff must contain one explicit "
            "User Claim name."
        )
    try:
        candidate = _safe_identity_name(
            candidates[0],
            "user_claim",
        )
    except Exception as exc:
        return None, str(exc)
    if candidate.casefold() == "aud":
        return None, (
            "The aud audience claim cannot be selected as the user-matching "
            "User Claim."
        )
    if (
        receipt.get("kind") != "administrator-confirmed-claim-candidates"
        or receipt.get("entraAdministratorConfirmed") is not True
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
    provenance_sha256 = str(mapping.get("provenanceSha256") or "")
    imported_workbook_sha256 = str(
        mapping.get("importedWorkbookSha256") or ""
    )
    provenance_current = bool(
        len(provenance_sha256) == 64
        and all(
            character in "0123456789abcdefABCDEF"
            for character in provenance_sha256
        )
        and imported_workbook_sha256 == provenance_sha256
        and mapping.get("importedFileFormat") in {"direct", "xlsx", "csv"}
    )
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
        or not provenance_current
        or oidc.get("identityMappingReceiptConfirmed") is not True
        or oidc.get("mappingReceiptCurrent") is not True
        or oidc.get("mappingDetailsCollected") is not True
        or oidc.get("tokenClaimName") != mapping.get("tokenClaimName")
        or oidc.get("serviceNowUserField")
        != mapping.get("serviceNowUserField")
        or oidc.get("mappingRelationshipSha256")
        != mapping.get("relationshipSha256")
        or mapping.get("relationshipSha256")
        != _identity_mapping_relationship_hash(mapping)
    ):
        return None, (
            "The ServiceNow mapping receipt does not match one exact selected "
            "claim and user-field pair from the Entra-confirmed candidates, "
            "current target binding, provenance, and hashes."
        )
    return mapping, None


def _entra_confirmation(
    admin_setup: dict[str, Any],
    state: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    receipt, error = _identity_claim_candidates_contract(
        admin_setup,
        state,
    )
    if error or receipt is None:
        return None, error or (
            "The target-bound Entra handoff receipt is missing."
        )
    handoff = _phase_handoff(admin_setup, "entra-registration")
    evidence = handoff.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    if not _phase_attested(admin_setup, "entra-registration"):
        return None, (
            "The complete Entra administrator confirmation is missing."
        )
    binding = evidence.get("binding")
    receipt_binding = receipt.get("binding")
    if not isinstance(binding, dict) or binding != receipt_binding:
        return None, (
            "The Entra administrator confirmation does not match the "
            "target-bound handoff receipt."
        )
    try:
        evidence_client_id = normalize_client_id(
            str(evidence.get("clientId") or "")
        )
    except Exception:
        return None, (
            "The Entra administrator confirmation has an invalid client ID."
        )
    if (
        evidence_client_id != receipt.get("applicationClientId")
        or evidence.get("tokenClaimCandidates") != receipt.get("candidates")
        or evidence.get("candidateSetSha256")
        != receipt.get("candidateSetSha256")
        or evidence.get("mappingWorkbookSha256")
        != receipt.get("importedWorkbookSha256")
    ):
        return None, (
            "The Entra administrator confirmation does not match the "
            "locally validated handoff values and provenance."
        )
    selected_claim = str(evidence.get("selectedClaimName") or "")
    candidates = list(receipt.get("candidates") or [])
    if len(candidates) != 1 or selected_claim != candidates[0]:
        return None, (
            "The Entra identity handoff must identify the one selected User "
            "Claim name from the current receipt."
        )
    return evidence, None


def _entra_setup_result(
    admin_setup: dict[str, Any],
    state: dict[str, Any],
    *,
    profile: CheckProfile = HR_CHECK_PROFILE,
) -> CheckResult:
    client_id = _entra_client_id(admin_setup)
    if not client_id:
        return _result(
            profile.cid("ENTRA-SETUP"),
            Status.NOT_CONFIGURED.value,
            "Entra User Login application setup",
            "No Application client ID has been recorded.",
            (
                "Record one valid non-secret Application client ID GUID and "
                "one explicit safe User Claim name in the current target-bound "
                "handoff."
            ),
            roles=[Role.ENTRA_ADMIN.value, Role.ESS_MAKER.value],
            profile=profile,
        )
    try:
        normalize_client_id(client_id)
    except Exception as exc:
        return _entra_error_result(str(exc), profile=profile)
    confirmation, error = _entra_confirmation(admin_setup, state)
    if error or confirmation is None:
        return _result(
            profile.cid("ENTRA-SETUP"),
            Status.NOT_CONFIGURED.value,
            "Entra User Login application setup",
            error or "The Entra administrator confirmation is missing.",
            (
                "Record one valid Application client ID GUID and one explicit "
                "safe User Claim name in a current target-bound handoff."
            ),
            roles=[Role.ENTRA_ADMIN.value, Role.ESS_MAKER.value],
            profile=profile,
        )
    result = (
        "The current target-bound Entra identity handoff contains one valid "
        "Application client ID GUID and one explicit User Claim name. Binding, "
        "provenance, and hashes are current. This Manual result does not prove "
        "application configuration, claim emission, scope, pre-authorization, "
        "a real token, authentication, permission, or a business result."
    )
    handoff = _phase_handoff(admin_setup, "entra-registration")
    handoff_evidence = handoff.get("evidence")
    handoff_evidence = (
        handoff_evidence if isinstance(handoff_evidence, dict) else {}
    )
    binding = handoff_evidence.get("binding")
    binding = binding if isinstance(binding, dict) else {}
    runbook = (
        f"src/skills/connect/{state.get('provider')}/actions/"
        "guide-entra-registration.md"
    )
    evidence = {
        "kind": "target-bound-entra-admin-confirmation",
        "source": confirmation["currentSource"],
        "recordedAt": handoff_evidence.get("recordedAt"),
        "provider": state.get("provider"),
        "profile": state.get("profile"),
        "agentSlug": state.get("agentSlug"),
        "agentId": state.get("agentId"),
        "environmentId": state.get("environmentId"),
        "instanceName": binding.get("instanceName"),
        "applicationClientId": client_id,
        "selectedClaimName": handoff_evidence.get("selectedClaimName"),
        "candidateSetSha256": handoff_evidence.get(
            "candidateSetSha256"
        ),
        "bindingSha256": _hash(binding),
        "runbook": runbook,
        "requiredValues": [
            "application-client-id",
            "user-claim-name",
        ],
    }
    return _result(
        profile.cid("ENTRA-SETUP"),
        Status.MANUAL.value,
        "Entra User Login application setup",
        result,
        (
            "Owner: Microsoft Entra Application Administrator or higher; "
            "the Maker only transports/imports the protected handoff. "
            f"Where/how: follow `{runbook}` in the Microsoft Entra admin "
            "center for the exact target app. Expected "
            "evidence: one current target-bound non-secret handoff containing "
            "a valid Application client ID GUID and one explicit safe User "
            "Claim name. Completion: both values, binding, provenance, "
            "timestamp, and hashes are valid for the current target; the "
            "result remains Manual and is never cloud/API proof."
        ),
        roles=[Role.ENTRA_ADMIN.value, Role.ESS_MAKER.value],
        evidence=evidence,
        profile=profile,
    )


def _oidc_result(
    admin_setup: dict[str, Any],
    state: dict[str, Any],
    *,
    profile: CheckProfile = HR_CHECK_PROFILE,
) -> CheckResult:
    handoff = _phase_handoff(admin_setup, "servicenow-oidc")
    missing = not _phase_attested(admin_setup, "servicenow-oidc")
    mapping = handoff.get("evidence")
    mapping = mapping if isinstance(mapping, dict) else {}
    if missing:
        status = Status.NOT_CONFIGURED.value
        result = "The current ServiceNow identity mapping handoff is missing."
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
                "The current target-bound ServiceNow mapping receipt records "
                f"locked User Claim {receipt['tokenClaimName']!r} and actual "
                f"internal User Field {receipt['serviceNowUserField']!r}. "
                "Binding, provenance, candidate hash, and relationship hash "
                "are current. This Manual evidence does not prove that the "
                "OIDC provider is saved or configured, or prove a real token, "
                "authentication success, permission, employee match, or "
                "business result."
            )
    return _result(
        profile.cid("OIDC"),
        status,
        "ServiceNow identity mapping receipt",
        result,
        (
            "Record one current target-bound mapping receipt containing the "
            "locked Entra-confirmed claim name and one actual safe internal "
            "ServiceNow sys_user field. Recreate it when the target, binding, "
            "provenance, candidate hash, or relationship hash is stale."
            if status != Status.MANUAL.value
            else (
                "Owner: ServiceNow Admin / security_admin. Where/how: follow "
                f"`src/skills/connect/{state.get('provider')}/actions/"
                "guide-servicenow-oidc.md` in Application Registry and the "
                "administrator identity handoff. "
                "Expected evidence: one current target-bound non-secret "
                "receipt containing one locked Entra-confirmed claim name and "
                "one actual internal ServiceNow user field, with current "
                "source, timestamp, binding, provenance, candidate hash, and "
                "relationship hash. Completion: the receipt is current for "
                "the exact target; it does not prove the OIDC provider is "
                "saved or configured, or prove a token, authentication, "
                "permission, employee match, or business result."
            )
        ),
        roles=[Role.SERVICENOW_ADMIN.value],
        profile=profile,
    )


def _topics_result(
    summary: dict[str, Any],
    evidence: dict[str, Any],
    component_hash: str,
    *,
    profile: CheckProfile,
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
        profile.cid("TOPICS"),
        status,
        f"{profile.product} topic readiness",
        f"{active}/{total} {profile.product} topics are Active.",
        f"Enable the inactive {profile.family} topics or explicitly attest that their "
        "current states should be retained."
        if status != Status.PASSED.value
        else "",
        profile=profile,
    )


def _portal_result(
    components: dict[str, Any],
    admin_setup: dict[str, Any],
    state: dict[str, Any],
    *,
    profile: CheckProfile,
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
            profile.cid("PORTAL"),
            Status.ERROR.value,
            f"{profile.product} employee portal Base URI",
            f"Unable to inspect the exact portal configuration: "
            f"{type(exc).__name__}: {exc}",
            (
                f"Open Copilot Studio Topics -> {profile.product} Setup "
                "Configurations and review the Set ServiceNow Portal BaseURI "
                "node without overwriting unrelated topic content."
            ),
            profile=profile,
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
            profile.cid("PORTAL"),
            Status.NOT_CONFIGURED.value,
            f"{profile.product} employee portal Base URI",
            "The Portal BaseURI is the ServiceNow instance root, but the "
            "lifecycle has no evidence that the administrator explicitly "
            "confirmed that exact root URL for the employee portal.",
            "Confirm the exact root URL through the portal phase before "
            "recording completion.",
            profile=profile,
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
                profile.cid("PORTAL"),
                Status.ERROR.value,
                f"{profile.product} employee portal Base URI",
                "Unable to verify the current portal URL against the URL "
                f"requested for this phase: {type(exc).__name__}: {exc}",
                "Review the latest portal transaction and the exact authored "
                "topic value before retrying.",
                profile=profile,
            )
        if actual_url != normalized_expected:
            return _result(
                profile.cid("PORTAL"),
                Status.NOT_CONFIGURED.value,
                f"{profile.product} employee portal Base URI",
                "The current Portal BaseURI is valid but does not match the "
                "administrator-confirmed URL requested for this phase.",
                "Set the exact requested employee portal URL, save the topic, "
                "and run a fresh read-only verification.",
                profile=profile,
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
        profile.cid("PORTAL"),
        status,
        f"{profile.product} employee portal Base URI",
        result,
        remediation,
        profile=profile,
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
    *,
    profile: CheckProfile,
    require_handoff: bool = True,
) -> CheckResult:
    match, credential = _selected_connection(evidence, connections)
    actual_instance = None
    actual_resource = None
    ambiguous_target = False
    if not require_handoff and not error:
        expected_instance = (
            (admin_setup.get("preflight") or {}).get("instanceName")
            if isinstance(admin_setup.get("preflight"), dict)
            else None
        )
        expected_client_id = _entra_client_id(admin_setup)
        exact_matches: list[tuple[dict[str, Any], str, str]] = []
        for candidate in connections:
            if (
                _connection_status(candidate) != "Connected"
                or _auth_mode(candidate) != AUTH_MODE
            ):
                continue
            properties = candidate.get("properties")
            properties = (
                properties if isinstance(properties, dict) else {}
            )
            parameter_set = properties.get("connectionParametersSet")
            parameter_set = (
                parameter_set if isinstance(parameter_set, dict) else {}
            )
            values = parameter_set.get("values")
            values = values if isinstance(values, dict) else {}

            def candidate_parameter(name: str) -> Any:
                value = values.get(name)
                return (
                    value.get("value")
                    if isinstance(value, dict)
                    else None
                )

            candidate_instance = candidate_parameter(
                "token:InstanceName"
            ) or candidate_parameter("instance")
            candidate_resource = candidate_parameter("token:ResourceUri")
            try:
                if (
                    expected_instance
                    and expected_client_id
                    and normalize_instance_name(str(candidate_instance))
                    == expected_instance
                    and normalize_client_id(str(candidate_resource))
                    == expected_client_id
                ):
                    exact_matches.append(
                        (
                            candidate,
                            str(candidate_instance),
                            str(candidate_resource),
                        )
                    )
            except Exception:
                continue
        if len(exact_matches) == 1:
            match, actual_instance, actual_resource = exact_matches[0]
            credential = {
                "connectionId": str(match.get("name") or ""),
            }
        elif len(exact_matches) > 1:
            ambiguous_target = True
            match = None
            credential = {}
        else:
            match = None
            credential = {}
    if error:
        status = Status.ERROR.value
        result = error
    elif ambiguous_target:
        status = Status.ERROR.value
        result = (
            "Fresh target inventory found multiple Connected ServiceNow "
            "connections with the exact auth mode, Instance Name, and "
            "Application client ID."
        )
    elif require_handoff and not _phase_attested(
        admin_setup,
        "credential",
    ):
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
    check = _result(
        profile.cid("CREDENTIAL"),
        status,
        f"{profile.product} credential health",
        result,
        (
            "Create or select a Connected Microsoft Entra ID User Login "
            "ServiceNow credential."
            if status != Status.PASSED.value
            else ""
        ),
        profile=profile,
    )
    if status == Status.PASSED.value:
        check.evidence = {
            "connectionId": str(
                credential.get("connectionId")
                or (match or {}).get("name")
                or ""
            ),
            "instanceName": (
                normalize_instance_name(str(actual_instance))
                if actual_instance
                else None
            ),
            "applicationClientId": (
                normalize_client_id(str(actual_resource))
                if actual_resource
                else None
            ),
        }
    return check


def _binding_evaluation(
    record: dict[str, Any],
    binding_identity_sha256: str,
    connection_id: str | None = None,
) -> str:
    binding = record.get("binding")
    if not isinstance(binding, dict):
        return "binding-missing"

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
    if binding.get("bindingIdentitySha256") != binding_identity_sha256:
        return "binding-identity-stale"
    return "valid"


def _agent_connection_result(
    evidence: dict[str, Any],
    credential_check: CheckResult,
    binding_identity_sha256: str,
    *,
    profile: CheckProfile,
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
            binding_identity_sha256,
            str((evidence.get("credential") or {}).get("connectionId") or ""),
        )
    if (
        credential_check.status == Status.PASSED.value
        and isinstance(record, dict)
        and record.get("makerAttested")
        and binding_evaluation != "valid"
    ):
        status = Status.NOT_CONFIGURED.value
        if binding_evaluation == "binding-identity-stale":
            result = (
                "The prior Agent Connect attestation is stale because the "
                "agent, environment, physical connection, or ServiceNow "
                "connection-reference binding identity changed."
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
        profile.cid("AGENT-CONNECTION"),
        status,
        "ServiceNow credential connected to the selected agent",
        result,
        "Confirm the ServiceNow row in Copilot Studio Connection settings.",
        profile=profile,
    )


def _target_agent_connection_result(
    target_context: dict[str, Any],
    credential_check: CheckResult,
    *,
    profile: CheckProfile,
) -> CheckResult:
    validation = target_context.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    runtime_plan = validation.get("runtimePlan")
    runtime_plan = runtime_plan if isinstance(runtime_plan, dict) else {}
    approval = validation.get("runtimeApproval")
    approval = approval if isinstance(approval, dict) else {}
    binding = validation.get("agentBinding")
    binding = binding if isinstance(binding, dict) else {}
    target = target_context.get("target")
    target = target if isinstance(target, dict) else {}
    target_sha = str(
        target_context.get("targetConfigurationSha256") or ""
    )
    expected_connection = str(
        target_context.get("connectionId")
        or runtime_plan.get("connectionId")
        or ""
    )
    current = bool(
        credential_check.status == Status.PASSED.value
        and binding.get("status") == "completed"
        and binding.get("targetConfigurationSha256") == target_sha
        and binding.get("targetAgentId") == target.get("agentId")
        and binding.get("targetEnvironmentId") == target.get("environmentId")
        and binding.get("planSha256") == runtime_plan.get("planSha256")
        and approval.get("decision") == "approved"
        and approval.get("planSha256") == runtime_plan.get("planSha256")
        and str(binding.get("connectionId") or "").casefold()
        == expected_connection.casefold()
    )
    status = (
        Status.MANUAL.value
        if current
        else credential_check.status
        if credential_check.status != Status.PASSED.value
        else Status.NOT_CONFIGURED.value
    )
    result = (
        "Current target-bound Manual evidence confirms the exact target "
        "agent shows the approved ServiceNow connection."
        if current
        else credential_check.result
        if credential_check.status != Status.PASSED.value
        else (
            "Current target-bound agent connection evidence is missing, "
            "stale, or belongs to another target, plan, or connection."
        )
    )
    check = _result(
        profile.cid("AGENT-CONNECTION"),
        status,
        "ServiceNow credential connected to the selected agent",
        result,
        (
            "Bind the exact approved connection in the target agent UI and "
            "record current target/hash-bound Manual evidence."
            if not current
            else ""
        ),
        profile=profile,
    )
    check.evidence = {
        "targetMode": True,
        "manualEvidenceCurrent": current,
        "targetConfigurationSha256": target_sha,
        "planSha256": runtime_plan.get("planSha256"),
        "connectionId": expected_connection or None,
    }
    check.automation_type = "manual"
    return check


def _target_test_result(
    target_context: dict[str, Any],
    topics_check: CheckResult,
    portal_check: CheckResult,
    credential_check: CheckResult,
    agent_connection_check: CheckResult,
    *,
    profile: CheckProfile,
) -> CheckResult:
    prerequisite = _test_prerequisite_gate(
        topics_check,
        portal_check,
        credential_check,
        agent_connection_check,
        profile=profile,
    )
    if prerequisite is not None:
        return prerequisite
    validation = target_context.get("validation")
    validation = validation if isinstance(validation, dict) else {}
    record = validation.get("functionalTest")
    record = record if isinstance(record, dict) else {}
    binding = record.get("binding")
    binding = binding if isinstance(binding, dict) else {}
    target = target_context.get("target")
    target = target if isinstance(target, dict) else {}
    runtime_plan = validation.get("runtimePlan")
    runtime_plan = runtime_plan if isinstance(runtime_plan, dict) else {}
    expected = {
        "provider": profile.provider_key,
        "profile": target_context.get("profile"),
        "targetAgentId": target.get("agentId"),
        "targetEnvironmentId": target.get("environmentId"),
        "targetConfigurationSha256": target_context.get(
            "targetConfigurationSha256"
        ),
        "planSha256": runtime_plan.get("planSha256"),
        "connectionId": target_context.get("connectionId")
        or runtime_plan.get("connectionId"),
    }
    current = bool(
        record.get("status") == "completed"
        and all(
            str(binding.get(key) or "").casefold()
            == str(value or "").casefold()
            for key, value in expected.items()
        )
        and record.get("promptCategory") in {
            None,
            profile.test_prompt_category,
        }
    )
    if not current:
        status = Status.NOT_CONFIGURED.value
        result = (
            "No current target-bound Test pane evidence matches the exact "
            "target, configuration, approved plan, connection, and binding."
        )
    elif record.get("result") == "pass" and record.get(
        "failureCategory"
    ) is None:
        status = Status.MANUAL.value
        result = f"Maker recorded a current passing {profile.family} target Test result."
    elif record.get("result") == "fail":
        status = Status.FAILED.value
        result = f"Maker recorded a current failing {profile.family} target Test result."
    else:
        status = Status.NOT_CONFIGURED.value
        result = "Target Test evidence does not use the bounded result contract."
    check = _result(
        profile.cid("TEST"),
        status,
        f"{profile.product} Test pane result",
        result,
        (
            "Run the profile's bounded low-side-effect scenario in the exact "
            "target Test pane and record current target/hash-bound Manual "
            "evidence."
            if status != Status.MANUAL.value
            else ""
        ),
        profile=profile,
    )
    check.evidence = {
        "targetMode": True,
        "manualEvidenceCurrent": current,
        "targetConfigurationSha256": expected[
            "targetConfigurationSha256"
        ],
        "planSha256": expected["planSha256"],
        "connectionId": expected["connectionId"],
    }
    check.automation_type = "manual"
    return check


def _publish_result(
    evidence: dict[str, Any],
    component_hash: str,
    draft_semantic_hash: str,
    connection_binding_hash: str | None,
    *,
    profile: CheckProfile,
) -> CheckResult:
    record = evidence.get("publish")
    test_outcome = _test_evidence_outcome(
        evidence,
        draft_semantic_hash,
        connection_binding_hash,
        profile=profile,
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
        profile.cid("PUBLISH"),
        status,
        f"{profile.product} agent publish status",
        result,
        "Review Copilot Studio publish details and republish only after explicit confirmation.",
        profile=profile,
    )


def _test_result(
    evidence: dict[str, Any],
    draft_semantic_hash: str,
    connection_binding_hash: str | None,
    topics_check: CheckResult,
    portal_check: CheckResult,
    credential_check: CheckResult,
    agent_connection_check: CheckResult,
    *,
    profile: CheckProfile,
) -> CheckResult:
    prerequisite = _test_prerequisite_gate(
        topics_check,
        portal_check,
        credential_check,
        agent_connection_check,
        profile=profile,
    )
    if prerequisite is not None:
        return prerequisite
    outcome = _test_evidence_outcome(
        evidence,
        draft_semantic_hash,
        connection_binding_hash,
        profile=profile,
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
        result = f"Maker recorded a passing {profile.family} Test pane result."
    else:
        status = Status.FAILED.value
        result = f"Maker recorded a failing {profile.family} Test pane result."
    return _result(
        profile.cid("TEST"),
        status,
        f"{profile.product} Test pane result",
        result,
        f"Run a low-side-effect {profile.family} prompt in the Test pane and record the current result.",
        profile=profile,
    )


def _test_evidence_outcome(
    evidence: dict[str, Any],
    draft_semantic_hash: str,
    connection_binding_hash: str | None,
    *,
    profile: CheckProfile,
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
        record.get("promptCategory") != profile.test_prompt_category
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
    *,
    profile: CheckProfile,
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
            profile.cid("TEST"),
            status,
            f"{profile.product} Test pane result",
            (
                f"Current {label} prerequisite is {check.status}: "
                f"{check.result}"
            ),
            check.remediation,
            format_recovery=False,
            profile=profile,
        )
    return None
