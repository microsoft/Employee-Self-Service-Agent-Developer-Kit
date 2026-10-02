# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import copy
import json

import pytest

from flightcheck.runner import (
    CheckResult,
    FlightCheckRunner,
    Priority,
    Status,
    compact_checkpoint_result_to_dict,
    parse_compact_checkpoint_result,
)


TARGET = "SN-DA-HRSD-TEST-001"
PROVIDER = "servicenow-da-hrsd"
PROFILE = "hrsd"
AGENT_SLUG = "employee-self-service-hr"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
INVOCATION_ID = "invocation-123"


def _run_result(status: str = Status.MANUAL.value):
    runner = FlightCheckRunner(
        scope=f"checkpoint:{TARGET}",
        target_matcher=lambda checkpoint_id: checkpoint_id == TARGET,
        checkpoint_target=TARGET,
    )
    runner.register(
        "ServiceNow DA HRSD",
        lambda _runner: [
            CheckResult(
                checkpoint_id=TARGET,
                category="ServiceNow DA HRSD",
                priority=Priority.HIGH.value,
                status=status,
                description="ServiceNow HRSD Test pane result",
                result="Maker recorded a passing HRSD Test pane result.",
                remediation=(
                    "Run a low-side-effect HRSD prompt in the Test pane and "
                    "record the current result."
                ),
                doc_link="https://learn.microsoft.com/example",
                doc_label="Docs",
                evidence={"kind": "bounded"},
                roles=["ESS Maker / Agent Developer"],
            )
        ],
    )
    return runner.run()


def _payload(status: str = Status.MANUAL.value) -> dict:
    result = _run_result(status)
    return compact_checkpoint_result_to_dict(
        result,
        target=TARGET,
        provider=PROVIDER,
        profile=PROFILE,
        agent_slug=AGENT_SLUG,
        agent_id=AGENT_ID,
        environment_id=ENVIRONMENT_ID,
        invocation_id=INVOCATION_ID,
        invocation_source="connect",
        exit_code=(
            1
            if status
            in {
                Status.FAILED.value,
                Status.BLOCKED.value,
                Status.ERROR.value,
            }
            else 0
        ),
    )


def _parse(payload: dict) -> dict:
    return parse_compact_checkpoint_result(
        json.dumps(payload, separators=(",", ":")),
        expected_target=TARGET,
        expected_provider=PROVIDER,
        expected_profile=PROFILE,
        expected_agent_slug=AGENT_SLUG,
        expected_agent_id=AGENT_ID,
        expected_environment_id=ENVIRONMENT_ID,
        expected_invocation_id=INVOCATION_ID,
    )


def test_compact_checkpoint_round_trip_preserves_actionable_fields() -> None:
    payload = _parse(_payload())
    row = payload["results"][0]

    assert payload["schemaVersion"] == "flightcheck.lifecycle-checkpoint.v1"
    assert payload["identity"] == {
        "provider": PROVIDER,
        "profile": PROFILE,
        "agentSlug": AGENT_SLUG,
        "agentId": AGENT_ID,
        "environmentId": ENVIRONMENT_ID,
    }
    assert payload["invocation"]["id"] == INVOCATION_ID
    assert row["checkpointId"] == TARGET
    assert row["status"] == Status.MANUAL.value
    assert row["description"] == "ServiceNow HRSD Test pane result"
    assert "passing HRSD Test pane" in row["result"]
    assert "low-side-effect" in row["remediation"]
    assert row["docLink"] == "https://learn.microsoft.com/example"
    assert row["roles"] == ["ESS Maker / Agent Developer"]
    assert row["evidence"] == {"kind": "bounded"}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.__setitem__("schemaVersion", "v2"), "schema"),
        (lambda payload: payload.__setitem__("kind", "checkpoint-error"), "result"),
        (lambda payload: payload.__setitem__("target", "OTHER-001"), "target"),
        (lambda payload: payload.__setitem__("targetKind", "family"), "target kind"),
        (
            lambda payload: payload["identity"].__setitem__(
                "agentId", "other-agent"
            ),
            "identity",
        ),
        (
            lambda payload: payload["invocation"].__setitem__(
                "id", "other-invocation"
            ),
            "invocation",
        ),
        (lambda payload: payload.__setitem__("results", []), "empty"),
        (
            lambda payload: payload["results"][0].__setitem__(
                "checkpointId", "OTHER-001"
            ),
            "target",
        ),
        (
            lambda payload: payload["results"][0].__setitem__(
                "status", "Unknown"
            ),
            "status",
        ),
        (lambda payload: payload.__setitem__("exitCode", 1), "exit"),
        (
            lambda payload: payload.__setitem__("overall", "NOT_READY"),
            "overall",
        ),
        (lambda payload: payload.__setitem__("extra", True), "fields"),
    ],
)
def test_compact_checkpoint_validation_fails_closed(
    mutate,
    message: str,
) -> None:
    payload = copy.deepcopy(_payload())
    mutate(payload)

    with pytest.raises(ValueError, match=message):
        _parse(payload)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        '{"schemaVersion":',
        "human output\n{}",
        "[]",
    ],
)
def test_compact_checkpoint_rejects_empty_truncated_or_mixed_stdout(
    raw: str,
) -> None:
    with pytest.raises(ValueError):
        parse_compact_checkpoint_result(
            raw,
            expected_target=TARGET,
            expected_provider=PROVIDER,
            expected_profile=PROFILE,
            expected_agent_slug=AGENT_SLUG,
            expected_agent_id=AGENT_ID,
            expected_environment_id=ENVIRONMENT_ID,
            expected_invocation_id=INVOCATION_ID,
        )


def test_compact_checkpoint_failure_exit_semantics_round_trip() -> None:
    payload = _parse(_payload(Status.FAILED.value))

    assert payload["overall"] == "NOT_READY"
    assert payload["exitCode"] == 1
    assert payload["results"][0]["status"] == Status.FAILED.value


def test_compact_checkpoint_warning_preserves_manual_content() -> None:
    payload = _parse(_payload(Status.WARNING.value))
    row = payload["results"][0]

    assert payload["overall"] == "READY_WITH_WARNINGS"
    assert payload["exitCode"] == 0
    assert row["description"] == "ServiceNow HRSD Test pane result"
    assert "passing HRSD Test pane" in row["result"]
    assert "low-side-effect" in row["remediation"]
    assert row["evidence"] == {"kind": "bounded"}


def test_compact_checkpoint_family_accepts_only_family_members() -> None:
    target = "SN-DA-HRSD-ENTRA"
    runner = FlightCheckRunner(
        scope=f"checkpoint:{target}",
        target_matcher=lambda checkpoint_id: checkpoint_id.startswith(
            f"{target}-"
        ),
        checkpoint_target=target,
    )
    runner.register(
        "ServiceNow DA HRSD",
        lambda _runner: [
            CheckResult(
                checkpoint_id=f"{target}-APP-001",
                category="ServiceNow DA HRSD",
                priority=Priority.HIGH.value,
                status=Status.PASSED.value,
                description="Entra application registration exists",
                result="Microsoft Graph read-only verification passed.",
            ),
            CheckResult(
                checkpoint_id=f"{target}-CLAIMS-001",
                category="ServiceNow DA HRSD",
                priority=Priority.HIGH.value,
                status=Status.PASSED.value,
                description="Entra access-token optional claims",
                result="Microsoft Graph read-only verification passed.",
            ),
        ],
    )
    result = runner.run()
    payload = compact_checkpoint_result_to_dict(
        result,
        target=target,
        target_is_family=True,
        provider=PROVIDER,
        profile=PROFILE,
        agent_slug=AGENT_SLUG,
        agent_id=AGENT_ID,
        environment_id=ENVIRONMENT_ID,
        invocation_id=INVOCATION_ID,
        invocation_source="connect",
        exit_code=0,
    )

    parsed = parse_compact_checkpoint_result(
        json.dumps(payload),
        expected_target=target,
        expected_target_is_family=True,
        expected_provider=PROVIDER,
        expected_profile=PROFILE,
        expected_agent_slug=AGENT_SLUG,
        expected_agent_id=AGENT_ID,
        expected_environment_id=ENVIRONMENT_ID,
        expected_invocation_id=INVOCATION_ID,
    )

    assert parsed["targetKind"] == "family"
    assert len(parsed["results"]) == 2
