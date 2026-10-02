# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Runtime and selected-agent evidence contracts for Workday Connect."""

from __future__ import annotations

from typing import Any, Mapping

from workday_connect_contract_common import (
    WorkdayConnectContractError,
    required_text,
)
from workday_connect_model import load_catalog


def validate_agent_binding_evidence(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise WorkdayConnectContractError(
            "Agent binding evidence must contain a JSON object."
        )
    allowed = {
        "environmentId",
        "botId",
        "makerUsername",
        "flowAttachment",
        "workdayTopics",
    }
    unexpected = sorted(set(evidence) - allowed)
    if unexpected:
        raise WorkdayConnectContractError(
            "Agent binding evidence contains unsupported fields: "
            + ", ".join(unexpected)
        )
    scope = state.get("scope") or {}
    agent = scope.get("agent") or {}
    expected_environment = required_text(
        scope,
        "environmentId",
        "Workday environment ID",
    )
    expected_bot = required_text(agent, "botId", "Workday agent bot ID")
    observed_environment = required_text(
        evidence,
        "environmentId",
        "Verified environment ID",
    )
    observed_bot = required_text(
        evidence,
        "botId",
        "Verified agent bot ID",
    )
    if observed_environment.casefold() != expected_environment.casefold():
        raise WorkdayConnectContractError(
            "Agent binding verification targeted a different environment."
        )
    if observed_bot.casefold() != expected_bot.casefold():
        raise WorkdayConnectContractError(
            "Agent binding verification targeted a different agent."
        )
    expected_maker = required_text(
        (state.get("operators") or {}).get("powerPlatformMaker") or {},
        "username",
        "Recorded Power Platform maker",
    )
    observed_maker = required_text(
        evidence,
        "makerUsername",
        "Verified Power Platform maker",
    )
    if observed_maker.casefold() != expected_maker.casefold():
        raise WorkdayConnectContractError(
            "Agent binding verification used a different Power Platform maker."
        )
    flow_attachment = evidence.get("flowAttachment")
    if not isinstance(flow_attachment, Mapping):
        raise WorkdayConnectContractError(
            "Agent binding evidence must contain the maker-confirmed Workday "
            "flow attachment."
        )
    attachment_allowed = {
        "outcome",
        "botId",
        "flowNames",
        "parameterSharingOutcome",
    }
    attachment_unexpected = sorted(
        set(flow_attachment) - attachment_allowed
    )
    if attachment_unexpected:
        raise WorkdayConnectContractError(
            "Workday flow attachment evidence contains unsupported fields: "
            + ", ".join(attachment_unexpected)
        )
    if flow_attachment.get("outcome") != "maker-confirmed":
        raise WorkdayConnectContractError(
            "Workday flow attachment must be explicitly confirmed by the maker."
        )
    attachment_bot = required_text(
        flow_attachment,
        "botId",
        "Workday flow attachment agent bot ID",
    )
    if attachment_bot.casefold() != expected_bot.casefold():
        raise WorkdayConnectContractError(
            "Workday flow attachment confirmation targeted a different agent."
        )
    if (
        flow_attachment.get("parameterSharingOutcome")
        != "enabled-for-exposed-connections"
    ):
        raise WorkdayConnectContractError(
            "Workday flow attachment must confirm parameter sharing for every "
            "connection exposed by the agent."
        )
    package_flavor = required_text(
        scope,
        "packageFlavor",
        "Workday package flavor",
    )
    package = (load_catalog().get("packages") or {}).get(package_flavor)
    if not isinstance(package, Mapping):
        raise WorkdayConnectContractError(
            f"Unsupported Workday package flavor: {package_flavor}."
        )
    expected_flow_names = {
        str(name)
        for name in package.get("agentConnectionFlowNames") or []
    }
    if not expected_flow_names:
        raise WorkdayConnectContractError(
            "The selected Workday package does not define agent-facing flows."
        )
    supplied_flow_names = flow_attachment.get("flowNames")
    if (
        not isinstance(supplied_flow_names, list)
        or any(
            not isinstance(name, str) or not name
            for name in supplied_flow_names
        )
        or len(supplied_flow_names) != len(expected_flow_names)
        or set(supplied_flow_names) != expected_flow_names
    ):
        raise WorkdayConnectContractError(
            "Workday flow attachment confirmation must name exactly the "
            "reviewed agent-facing Workday flows."
        )
    topics = evidence.get("workdayTopics")
    if not isinstance(topics, Mapping):
        raise WorkdayConnectContractError(
            "Agent binding evidence must contain Workday topic verification."
        )
    expected_count = topics.get("expected")
    verified_count = topics.get("verified")
    active_count = topics.get("active")
    diagnostics = topics.get("blockingDiagnostics")
    if (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count <= 0
        or not isinstance(verified_count, int)
        or isinstance(verified_count, bool)
        or not isinstance(active_count, int)
        or isinstance(active_count, bool)
        or verified_count != expected_count
        or active_count != expected_count
        or not isinstance(diagnostics, list)
        or any(not isinstance(diagnostic, Mapping) for diagnostic in diagnostics)
    ):
        raise WorkdayConnectContractError(
            "Every mapped Workday topic must be active and verified, and "
            "reported topic diagnostics must be structured."
        )
    return {
        "environmentId": observed_environment,
        "botId": observed_bot,
        "makerUsername": observed_maker,
        "flowAttachment": {
            "outcome": "maker-confirmed",
            "botId": attachment_bot,
            "flowNames": sorted(expected_flow_names),
            "parameterSharingOutcome": "enabled-for-exposed-connections",
        },
        "workdayTopics": {
            "expected": expected_count,
            "verified": verified_count,
            "active": active_count,
            "blockingDiagnostics": [
                dict(diagnostic) for diagnostic in diagnostics
            ],
        },
    }
