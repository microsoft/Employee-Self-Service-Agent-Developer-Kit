# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ESS-SOLN-001's Declarative Agent ALM configure read.

The check consumes the validated AgentBuilder Minimal Bot API
``GET /copilotstudio/minimalBots/alm/{agent_id}/configure`` shape captured in
``tests/fixtures/cassettes/agentbuilder_readiness.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from agentbuilder import AgentBuilderHTTPError, DEV_REALM, PROD_REALM, TEST_REALM
from flightcheck.checks.solution import _alm_realm, _check_ess_solution_installed
from flightcheck.runner import Status
from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as ab

require_validated_mock(ab)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]):
        self.status_code = 400
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAgentBuilder:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._payload = payload or ab.configuration()
        self._error = error
        self.calls: list[tuple[str, int]] = []

    def get_realm_configuration(self, agent_id: str, realm: int) -> dict[str, Any]:
        self.calls.append((agent_id, realm))
        if self._error is not None:
            raise self._error
        return self._payload


@dataclass
class _Runner:
    agentbuilder: Any = None
    config: dict[str, Any] = field(default_factory=dict)


def _config(*, bot_id: str | None = ab.MOCK_AGENT_ID) -> dict[str, Any]:
    agent: dict[str, Any] = {"slug": "ess-dev"}
    if bot_id is not None:
        agent["botId"] = bot_id
    return {
        "activeAgent": "ess-dev",
        "agent": agent.copy(),
        "agents": [agent],
    }


def test_passes_when_configure_returns_grs_repository_and_commit() -> None:
    agentbuilder = _FakeAgentBuilder()
    runner = _Runner(agentbuilder=agentbuilder, config=_config())

    result = _check_ess_solution_installed(runner)[0]

    assert result.status == Status.PASSED.value
    assert "Agent has a committed GRS package" in result.result
    assert "ESS base-package identity match pending US 7792604" in result.result
    assert ab.MOCK_ENV_ID in result.result
    assert ab.MOCK_COMMIT_SHA in result.result
    assert result.remediation == ""
    assert agentbuilder.calls == [(ab.MOCK_AGENT_ID, DEV_REALM)]


@pytest.mark.parametrize(
    ("field", "result_phrase"),
    [
        ("grsRepositoryId", "grsRepositoryId"),
        ("commitSha", "commitSha"),
    ],
)
def test_fails_when_configure_omits_required_package_state(
    field: str,
    result_phrase: str,
) -> None:
    payload = ab.configuration()
    payload[field] = ""
    runner = _Runner(agentbuilder=_FakeAgentBuilder(payload), config=_config())

    result = _check_ess_solution_installed(runner)[0]

    assert result.status == Status.FAILED.value
    assert result_phrase in result.result
    assert "not present in the agent's GRS package state" in result.result
    assert "Install or import the Employee Self Service base package" in (
        result.remediation
    )
    assert "confirm the ALM configure response has a repository and commit" in (
        result.remediation
    )


def test_not_configured_when_agent_is_not_opted_into_alm() -> None:
    error = AgentBuilderHTTPError(
        "Dev realm configuration",
        400,
        response=_FakeResponse({"ErrorCode": 4003}),
    )
    runner = _Runner(
        agentbuilder=_FakeAgentBuilder(error=error),
        config=_config(),
    )

    result = _check_ess_solution_installed(runner)[0]

    assert result.status == Status.NOT_CONFIGURED.value
    assert "not opted into ALM" in result.result
    assert "error code 4003" in result.result
    assert "Opt the agent into Application Lifecycle Management" in (
        result.remediation
    )
    assert "Copilot Studio" in result.remediation


def test_skips_when_agentbuilder_client_is_missing() -> None:
    result = _check_ess_solution_installed(_Runner(config=_config()))[0]

    assert result.status == Status.SKIPPED.value
    assert "AgentBuilder client not available" in result.result
    assert "native AgentBuilder authentication" in result.remediation


def test_skips_when_bot_id_is_missing() -> None:
    runner = _Runner(
        agentbuilder=_FakeAgentBuilder(),
        config=_config(bot_id=None),
    )

    result = _check_ess_solution_installed(runner)[0]

    assert result.status == Status.SKIPPED.value
    assert "No agent botId" in result.result
    assert "Run setup" in result.remediation


def test_fails_when_configured_alm_realm_is_not_supported() -> None:
    config = _config()
    config["almRealm"] = "sandbox"
    agentbuilder = _FakeAgentBuilder()
    runner = _Runner(agentbuilder=agentbuilder, config=config)

    result = _check_ess_solution_installed(runner)[0]

    assert result.status == Status.FAILED.value
    assert "configured ALM realm is not Dev, Test, or Prod" in result.result
    assert "Set almRealm, grsRealm, or minimalBotsAlmRealm" in (
        result.remediation
    )
    assert "Dev, Test, or Prod" in result.remediation
    assert agentbuilder.calls == []


@pytest.mark.parametrize(
    ("raw_realm", "expected"),
    [
        (DEV_REALM, DEV_REALM),
        ("dev", DEV_REALM),
        ("DEV", DEV_REALM),
        ("test", TEST_REALM),
        ("TeSt", TEST_REALM),
        ("prod", PROD_REALM),
        ("PROD", PROD_REALM),
        (str(TEST_REALM), TEST_REALM),
        ("sandbox", None),
    ],
)
def test_alm_realm_maps_supported_config_values(
    raw_realm: Any,
    expected: int | None,
) -> None:
    runner = _Runner(config={"almRealm": raw_realm})

    assert _alm_realm(runner) == expected


def test_warning_when_configure_read_errors() -> None:
    error = AgentBuilderHTTPError("Dev realm configuration", 500)
    runner = _Runner(
        agentbuilder=_FakeAgentBuilder(error=error),
        config=_config(),
    )

    result = _check_ess_solution_installed(runner)[0]

    assert result.status == Status.WARNING.value
    assert "Unable to verify ESS package state" in result.result
    assert "Dev realm configuration failed with HTTP 500" in result.result
    assert "Retry the read-only ALM configure check" in result.remediation
    assert "AgentBuilder access" in result.remediation
