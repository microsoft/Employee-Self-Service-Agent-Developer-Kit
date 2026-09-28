# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lifecycle checkpoints for the DA HR ServiceNow HRSD provider."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from connect_servicenow_da import (
    CONNECTOR_NAME,
    HR_SCHEMA_NAME,
    PROVIDER_KEY,
    summarize_components,
)
from agentbuilder import AgentBuilderHTTPError

from ..agent_scope import validate_agent_slug
from ..runner import CheckResult, Priority, Role, Status


_CATEGORY = "ServiceNow DA HRSD"
_ROLES = [Role.ESS_MAKER.value, Role.SERVICENOW_ADMIN.value]


def _result(
    checkpoint_id: str,
    status: str,
    description: str,
    result: str,
    remediation: str = "",
) -> CheckResult:
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


def _is_throttled_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, AgentBuilderHTTPError):
            if current.status_code == 429:
                return True
        response = getattr(current, "response", None)
        if getattr(response, "status_code", None) == 429:
            return True
        text = str(current).casefold()
        if "429" in text and (
            "too many" in text
            or "thrott" in text
            or "retry" in text
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def run_servicenow_da_hrsd_checks(runner) -> list[CheckResult]:
    selected = _active_agent(runner)
    if selected is None:
        return _all_unavailable(
            Status.FAILED.value,
            "The selected agent could not be resolved.",
            "Select the exact editable ESS HR agent and rerun the checkpoint.",
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
        )
    agent_id = str(agent.get("botId") or agent.get("id") or "")
    if not agent_id:
        return _all_unavailable(
            Status.FAILED.value,
            "The selected HR agent has no AgentBuilder ID.",
            "Refresh the local setup handoff for this agent.",
        )
    client = getattr(runner, "agentbuilder", None)
    if client is None:
        return _all_unavailable(
            Status.ERROR.value,
            "AgentBuilder authentication is unavailable.",
            "Sign in to the target environment and retry.",
        )
    try:
        components = client.fetch_components(agent_id)
        has_hrsd_topics = any(
            isinstance(change, dict)
            and "ServiceNowHRSD"
            in str((change.get("component") or {}).get("schemaName") or "")
            for change in components.get("botComponentChanges") or []
        )
        if not has_hrsd_topics:
            return _all_unavailable(
                Status.NOT_CONFIGURED.value,
                f"The selected HR agent '{slug}' has no ServiceNow HRSD topics.",
                "Install the ServiceNow HRSD extension for this exact HR agent.",
            )
        summary = summarize_components(components)
    except Exception as exc:
        return _all_unavailable(
            Status.ERROR.value,
            f"Unable to inspect the HR agent: {type(exc).__name__}: {exc}",
            "Verify AgentBuilder access to the selected environment and retry.",
        )

    state = _load_state(slug)
    evidence = state.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    component_hash = _hash(components)
    connections: list[dict[str, Any]] = []
    connectivity_error = ""
    inventory_source = "environment-wide"
    connectivity = getattr(runner, "connectivity", None)
    environment_id = str(getattr(runner, "env_id", None) or "")
    if connectivity is None:
        connectivity_error = "Connection inventory authentication is unavailable."
    else:
        try:
            connections = _servicenow_connections(
                connectivity.list_connections(environment_id)
            )
        except Exception as primary_exc:
            if not _is_throttled_error(primary_exc):
                connectivity_error = (
                    f"{type(primary_exc).__name__}: {primary_exc}"
                )
            else:
                try:
                    connections = _servicenow_connections(
                        connectivity.list_connector_connections(
                            environment_id,
                            CONNECTOR_NAME,
                            one_shot=True,
                        )
                    )
                    inventory_source = "connector-scoped-429-fallback"
                except Exception as fallback_exc:
                    connectivity_error = (
                        f"{type(primary_exc).__name__}: {primary_exc}; "
                        "connector-scoped 429 fallback failed: "
                        f"{type(fallback_exc).__name__}: {fallback_exc}"
                    )

    return [
        _package_result(slug, summary),
        _topics_result(summary, evidence, component_hash),
        _credential_result(
            evidence,
            connections,
            connectivity_error,
            inventory_source,
        ),
        _agent_connection_result(
            evidence,
            connections,
            connectivity_error,
            component_hash,
            inventory_source,
        ),
        _parameter_result(evidence, component_hash),
        _publish_result(evidence, component_hash),
        _test_result(evidence, component_hash),
    ]


def _all_unavailable(
    status: str,
    result: str,
    remediation: str,
) -> list[CheckResult]:
    ids = (
        "PKG",
        "TOPICS",
        "CREDENTIAL",
        "AGENT-CONNECTION",
        "PARAMETER-SHARING",
        "PUBLISH",
        "TEST",
    )
    return [
        _result(
            f"SN-DA-HRSD-{suffix}-001",
            status,
            f"ServiceNow HRSD {suffix.lower()} readiness",
            result,
            remediation,
        )
        for suffix in ids
    ]


def _package_result(slug: str, summary: dict[str, Any]) -> CheckResult:
    count = summary["serviceNowTopicCount"]
    return _result(
        "SN-DA-HRSD-PKG-001",
        Status.PASSED.value if count else Status.NOT_CONFIGURED.value,
        "ServiceNow HRSD package installed for the selected DA HR agent",
        (
            f"Selected HR agent '{slug}' contains {count} ServiceNow HRSD "
            "topic(s)."
        ),
        (
            "Install the ServiceNow HRSD extension for this exact HR agent."
            if not count
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
        (
            "Enable the inactive HRSD topics or explicitly attest that their "
            "current states should be retained."
            if status != Status.PASSED.value
            else ""
        ),
    )


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
    connections: list[dict[str, Any]],
    error: str,
    inventory_source: str = "environment-wide",
) -> CheckResult:
    match, credential = _selected_connection(evidence, connections)
    if error:
        status = Status.ERROR.value
        result = error
    elif not credential.get("connectionId"):
        status = Status.NOT_CONFIGURED.value
        result = "No ServiceNow credential has been selected."
    elif match is None:
        status = Status.FAILED.value
        result = "The selected ServiceNow credential is not visible."
    elif (
        _connection_status(match) != "Connected"
        or _auth_mode(match) != "entraIDUserLogin"
    ):
        status = Status.FAILED.value
        result = (
            "The selected ServiceNow credential is not a Connected Microsoft "
            "Entra ID User Login connection."
        )
    else:
        status = Status.PASSED.value
        result = (
            "The selected ServiceNow credential is Connected and uses Entra "
            f"(inventory source: {inventory_source})."
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
    component_hash: str,
    connection_id: str | None = None,
) -> str:
    binding = record.get("binding")
    if not isinstance(binding, dict):
        return "binding-missing"
    if binding.get("componentHash") != component_hash:
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


def _binding_current(
    record: dict[str, Any],
    component_hash: str,
    connection_id: str | None = None,
) -> bool:
    return (
        _binding_evaluation(record, component_hash, connection_id)
        == "valid"
    )


def _agent_connection_result(
    evidence: dict[str, Any],
    connections: list[dict[str, Any]],
    error: str,
    component_hash: str,
    inventory_source: str = "environment-wide",
) -> CheckResult:
    credential_check = _credential_result(
        evidence,
        connections,
        error,
        inventory_source,
    )
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
            component_hash,
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
                "component revision."
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


def _parameter_result(
    evidence: dict[str, Any],
    component_hash: str,
) -> CheckResult:
    record = evidence.get("parameterSharing")
    connection_id = str(
        (evidence.get("credential") or {}).get("connectionId") or ""
    )
    valid = (
        isinstance(record, dict)
        and record.get("status") in {"enabled", "not-exposed"}
        and record.get("makerAttested") is True
        and _binding_current(record, component_hash, connection_id)
    )
    return _result(
        "SN-DA-HRSD-PARAMETER-SHARING-001",
        Status.MANUAL.value if valid else Status.NOT_CONFIGURED.value,
        "ServiceNow parameter-sharing behavior",
        (
            f"Maker observed parameter sharing as {record.get('status')}."
            if valid
            else "Current parameter-sharing evidence is absent or stale."
        ),
        "Open Connection parameters and confirm the current control state.",
    )


def _publish_result(
    evidence: dict[str, Any],
    component_hash: str,
) -> CheckResult:
    record = evidence.get("publish")
    if not isinstance(record, dict) or record.get("componentHash") != component_hash:
        status = Status.NOT_CONFIGURED.value
        result = "The current component revision has no publish receipt."
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
    component_hash: str,
) -> CheckResult:
    record = evidence.get("test")
    publish = evidence.get("publish")
    valid_binding = (
        isinstance(record, dict)
        and isinstance(record.get("binding"), dict)
        and isinstance(publish, dict)
        and record["binding"].get("publishedComponentHash") == component_hash
        and publish.get("componentHash") == component_hash
    )
    if not valid_binding:
        status = Status.NOT_CONFIGURED.value
        result = "No current Test pane evidence is bound to this publish."
    elif record.get("result") == "pass":
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
