# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ESS-SOLN-001's Declarative Agent ALM configure read.

The check consumes the validated AgentBuilder Minimal Bot API
``GET /copilotstudio/minimalBots/alm/{agent_id}/configure`` shape captured in
``tests/fixtures/cassettes/agentbuilder_readiness.yaml``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
import responses
import yaml

from agentbuilder import (
    AgentBuilderClient, AgentBuilderHTTPError, DEV_REALM, PROD_REALM, TEST_REALM,
    derive_environment_host,
)
from flightcheck.checks.solution import _alm_realm, _check_ess_solution_installed, run_solution_checks
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


def test_passes_when_configure_returns_ess_schema_grs_and_commit() -> None:
    agentbuilder = _FakeAgentBuilder()
    runner = _Runner(agentbuilder=agentbuilder, config=_config())

    result = _check_ess_solution_installed(runner)[0]

    assert result.status == Status.PASSED.value
    assert "Agent runs the ESS base package" in result.result
    assert ab.MOCK_SCHEMA_NAME in result.result
    assert "exact package revision match pending US 7792604" in result.result
    assert ab.MOCK_ENV_ID in result.result
    assert ab.MOCK_COMMIT_SHA in result.result
    assert result.remediation == ""
    assert agentbuilder.calls == [(ab.MOCK_AGENT_ID, DEV_REALM)]


def test_fails_when_configure_schema_is_not_ess() -> None:
    payload = ab.configuration()
    payload["schemaName"] = "gptagent_contosowidgets"
    runner = _Runner(agentbuilder=_FakeAgentBuilder(payload), config=_config())

    result = _check_ess_solution_installed(runner)[0]

    assert result.status == Status.FAILED.value
    assert "gptagent_contosowidgets" in result.result
    assert "not the Employee Self Service base package" in result.result
    assert "committed GRS package is a different product" in result.result
    assert "Point this check's botId at the Employee Self Service agent" in (
        result.remediation
    )


def test_warns_when_schema_name_missing() -> None:
    payload = ab.configuration()
    payload["schemaName"] = ""
    runner = _Runner(agentbuilder=_FakeAgentBuilder(payload), config=_config())

    result = _check_ess_solution_installed(runner)[0]

    assert result.status == Status.WARNING.value
    assert "returned no schemaName" in result.result
    assert "identity could not be confirmed" in result.result
    assert "not provably ESS" in result.result
    assert ab.MOCK_ENV_ID in result.result
    assert ab.MOCK_COMMIT_SHA in result.result
    assert "returns a schemaName" in result.remediation


def _native_runner():
    path = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes" / "agentbuilder_readiness.yaml"
    interaction = next(
        item for item in yaml.safe_load(path.read_text(encoding="utf-8"))["interactions"]
        if "/components?" in item["request"]["uri"]
    )
    payload = json.loads(interaction["response"]["body"]["string"])
    bot = payload["bot"]
    config = _config()
    config["agents"][0].update(botId=bot["cdsBotId"], schemaName=bot["schemaName"])
    runner = _Runner(agentbuilder=_FakeAgentBuilder(error=AssertionError("DA must not read ALM")), config=config)
    runner.env_id = ab.MOCK_ENV_ID
    runner.da_full_assessment = True
    runner.validation_context = {"realm": "dev"}
    runner._da_native_snapshot = {
        "agentId": bot["cdsBotId"], "environmentId": ab.MOCK_ENV_ID,
        "changeset": payload,
    }
    return runner


def test_full_da_confirms_exact_native_ess_content_without_alm_provenance():
    runner = _native_runner()
    runner.config["almRealm"] = "prod"
    row = run_solution_checks(runner)[0]
    assert row.status == Status.PASSED.value
    assert "Confirmed native ESS schema" in row.result
    assert row.evidence["agentId"] == runner._da_native_snapshot["agentId"]
    assert "not_package_origin_revision" in row.evidence["evidenceBoundary"]
    assert row.remediation == ""
    assert runner.agentbuilder.calls == []


@pytest.mark.parametrize("mismatch", ["agent", "environment", "bot", "schema", "missing_content", "missing_snapshot"])
def test_full_da_native_installation_requires_exact_identity_and_content(mismatch):
    runner = _native_runner()
    snapshot = runner._da_native_snapshot
    if mismatch in {"agent", "environment"}:
        snapshot["agentId" if mismatch == "agent" else "environmentId"] = "different"
    elif mismatch in {"bot", "schema"}:
        snapshot["changeset"]["bot"]["cdsBotId" if mismatch == "bot" else "schemaName"] = "different"
    elif mismatch == "missing_content":
        snapshot["changeset"]["botComponentChanges"] = []
    else:
        del runner._da_native_snapshot
    row = run_solution_checks(runner)[0]
    assert row.status == Status.BLOCKED.value
    assert "could not be confirmed" in row.result
    assert "Resolve the native agent access/content findings" in row.remediation
    assert runner.agentbuilder.calls == []


def test_full_da_does_not_accept_a_non_ess_native_agent_as_ess():
    runner = _native_runner()
    runner.config["agents"][0]["schemaName"] = "gptagent_otherproduct"
    runner._da_native_snapshot["changeset"]["bot"]["schemaName"] = "gptagent_otherproduct"
    row = run_solution_checks(runner)[0]
    assert row.status == Status.FAILED.value
    assert "not an ESS schema" in row.result
    assert "Select the intended Employee Self-Service agent" in row.remediation


def test_legacy_package_replays_captured_configure_string_realm():
    path = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes" / "agentbuilder_readiness.yaml"
    interaction = next(
        item for item in yaml.safe_load(path.read_text(encoding="utf-8"))["interactions"]
        if item["request"]["method"] == "GET" and "/configure" in item["request"]["uri"]
    )
    payload = json.loads(interaction["response"]["body"]["string"])
    assert payload["realm"] == "Dev"
    parsed = urlsplit(interaction["request"]["uri"])
    host = derive_environment_host(ab.MOCK_ENV_ID, "prod")
    uri = parsed._replace(netloc=urlsplit(host).netloc).geturl()
    client = AgentBuilderClient(
        host, "test-token", ring="prod", tenant_id=ab.MOCK_ENV_ID,
        api_version=parse_qs(parsed.query)["api-version"][0],
    )
    config = _config(bot_id=payload["cdsBotId"])
    config["agents"][0]["schemaName"] = payload["schemaName"]
    runner = _Runner(agentbuilder=client, config=config)
    with responses.RequestsMock() as http:
        http.add(responses.GET, uri, json=payload, status=200)
        row = _check_ess_solution_installed(runner)[0]
        assert row.status == Status.PASSED.value
        assert "Agent runs the ESS base package" in row.result
        assert row.remediation == ""
        assert len(http.calls) == 1


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


def test_alm_realm_honors_explicit_dev_zero_over_later_fields() -> None:
    """Presence-based resolution: an explicit Dev realm 0 in an earlier field
    must win over a later field. The old `a or b` chain dropped 0 as falsy and
    resolved the wrong realm."""
    runner = _Runner(
        config={
            "minimalBotsAlmRealm": DEV_REALM,
            "grsRealm": TEST_REALM,
            "agent": {"realm": PROD_REALM},
        }
    )

    assert _alm_realm(runner) == DEV_REALM


def test_alm_realm_skips_blank_string_and_uses_next_present_field() -> None:
    """A blank/whitespace field is treated as unset so a later present
    candidate supplies the realm."""
    runner = _Runner(
        config={
            "minimalBotsAlmRealm": "   ",
            "grsRealm": TEST_REALM,
        }
    )

    assert _alm_realm(runner) == TEST_REALM


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
