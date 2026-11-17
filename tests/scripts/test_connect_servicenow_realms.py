# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for ServiceNow Test/Prod realm discovery, foundation reuse, and gating."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

import servicenow_connect_realms as realms
from agentbuilder import AgentBuilderHTTPError

DEV_ENV = "00000000-0000-4000-8000-000000001111"
TEST_ENV = "00000000-0000-4000-8000-000000002222"
OTHER_ENV = "00000000-0000-4000-8000-000000002223"
DEV_AGENT = "00000000-0000-4000-8000-000000003333"
TEST_AGENT = "00000000-0000-4000-8000-000000004444"
PROD_AGENT = "00000000-0000-4000-8000-000000004445"
TENANT = "00000000-0000-4000-8000-000000006666"
OTHER_TENANT = "00000000-0000-4000-8000-000000007777"
FAMILY = "00000000-0000-4000-8000-000000008888"
OTHER_FAMILY = "00000000-0000-4000-8000-000000009999"
SCHEMA = "gptagent_copilotforemployeeselfservicehr"
TEST_URL = "https://contoso-test.crm.dynamics.com"
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
CONNECTION_ID = "99999999-aaaa-4bbb-8ccc-dddddddddddd"
PROMPT = "workday-style-prompt"

FOUNDATION = {
    "instanceName": "contoso",
    "clientId": CLIENT_ID,
    "tenantId": TENANT,
}


class FakeClient:
    def __init__(
        self,
        *,
        tenant_id: str = TENANT,
        route_realm: int = 0,
        siblings: list[dict[str, Any]] | None = None,
        family: str = FAMILY,
        schema: str = SCHEMA,
        commit: str = "abc123",
        agent_id: str = TEST_AGENT,
        realm: int = 1,
        missing: bool = False,
    ) -> None:
        self.tenant_id = tenant_id
        self.route_realm = route_realm
        self.siblings = (
            siblings if siblings is not None else [{"realm": 1, "botId": TEST_AGENT}]
        )
        self.family = family
        self.schema = schema
        self.commit = commit
        self.agent_id = agent_id
        self.realm = realm
        self.missing = missing
        self.writes: list[str] = []

    def get_realms(self, _agent_id: str) -> dict[str, Any]:
        return {"routeRealm": self.route_realm, "siblingRealms": self.siblings}

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        if self.missing:
            raise AgentBuilderHTTPError("missing", status_code=404)
        return {"botId": agent_id, "schemaName": self.schema}

    def get_realm_configuration(self, agent_id: str, realm: int) -> dict[str, Any]:
        return {
            "realm": realm,
            "cdsBotId": agent_id,
            "grsRepositoryId": self.family,
            "schemaName": self.schema,
            "commitSha": self.commit,
        }


def _discover(source: FakeClient, target: FakeClient, **overrides: Any):
    arguments: dict[str, Any] = {
        "source_agent_id": DEV_AGENT,
        "expected_schema_name": SCHEMA,
        "realm": "test",
        "environment_id": TEST_ENV,
        "environment_url": TEST_URL,
    }
    arguments.update(overrides)
    return realms.discover_realm_target(source, target, **arguments)


def test_discovers_exact_promoted_sibling() -> None:
    identity = _discover(FakeClient(), FakeClient())
    assert identity["agentId"] == TEST_AGENT
    assert identity["environmentId"] == TEST_ENV
    assert identity["almFamilyId"] == FAMILY
    assert identity["sourceAgentId"] == DEV_AGENT


@pytest.mark.parametrize(
    ("target", "message"),
    [
        (FakeClient(family=OTHER_FAMILY), "different ALM family"),
        (FakeClient(tenant_id=OTHER_TENANT), "different Microsoft Entra"),
        (FakeClient(schema="other_agent"), "supported ESS agent"),
        (FakeClient(commit=""), "deployed package evidence"),
    ],
)
def test_rejects_unproven_sibling(target: FakeClient, message: str) -> None:
    with pytest.raises(realms.ServiceNowRealmError, match=message):
        _discover(FakeClient(), target)


def test_rejects_link_to_a_different_agent() -> None:
    with pytest.raises(realms.ServiceNowRealmError, match="not the Test promotion"):
        _discover(
            FakeClient(),
            FakeClient(),
            expected_target_agent_id=OTHER_ENV,
        )


def _environments(*ids: str) -> list[dict[str, Any]]:
    return [
        {
            "id": environment_id,
            "displayName": f"Env {index}",
            "url": f"https://env{index}.crm.dynamics.com",
        }
        for index, environment_id in enumerate(ids)
    ]


@pytest.fixture
def no_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        realms,
        "derive_environment_host",
        lambda environment_id, ring: f"https://{environment_id}.{ring}",
    )


def _discover_realm(
    tmp_path: Path,
    clients: dict[str, FakeClient],
    environments: list[dict[str, Any]],
    **overrides: Any,
):
    def factory(host: str, *_args: Any, **_kwargs: Any) -> FakeClient:
        return clients[host]

    arguments: dict[str, Any] = {
        "root": tmp_path,
        "ring": "prod",
        "tenant_id": TENANT,
        "source_host": "dev-host",
        "api_version": "2024-10-01",
        "source_agent_id": DEV_AGENT,
        "expected_schema_name": SCHEMA,
        "realm": "test",
        "authenticator": lambda *_a, **_k: ("token", TENANT),
        "client_factory": factory,
        "environment_loader": lambda *_a, **_k: environments,
    }
    arguments.update(overrides)
    return realms.discover_realm(**arguments)


def test_automatic_discovery_skips_environments_without_the_agent(
    tmp_path: Path, no_dns: None
) -> None:
    clients = {
        "dev-host": FakeClient(),
        f"https://{OTHER_ENV}.prod": FakeClient(missing=True),
        f"https://{TEST_ENV}.prod": FakeClient(),
    }
    realm, identity = _discover_realm(
        tmp_path, clients, _environments(OTHER_ENV, TEST_ENV)
    )
    assert realm == "test"
    assert identity["environmentId"] == TEST_ENV


def test_automatic_discovery_failure_lists_safe_environment_names(
    tmp_path: Path, no_dns: None
) -> None:
    clients = {
        "dev-host": FakeClient(),
        f"https://{OTHER_ENV}.prod": FakeClient(missing=True),
    }
    with pytest.raises(realms.ServiceNowRealmError) as excinfo:
        _discover_realm(tmp_path, clients, _environments(OTHER_ENV))
    assert "Available environments: Env 0" in str(excinfo.value)
    assert "Select the environment by name or URL" in str(excinfo.value)


def test_signed_in_tenant_must_match_dev(tmp_path: Path, no_dns: None) -> None:
    with pytest.raises(realms.ServiceNowRealmError, match="tenant does not match"):
        _discover_realm(
            tmp_path,
            {"dev-host": FakeClient()},
            [],
            authenticator=lambda *_a, **_k: ("token", OTHER_TENANT),
        )


def _link(environment_id: str, agent_id: str) -> str:
    return (
        "https://copilotstudio.microsoft.com/environments/"
        f"{environment_id}/bots/{agent_id}/overview"
    )


def test_agent_link_activates_verified_realm(tmp_path: Path, no_dns: None) -> None:
    clients = {
        "dev-host": FakeClient(),
        f"https://{TEST_ENV}.prod": FakeClient(route_realm=1),
    }
    realm, identity = _discover_realm(
        tmp_path,
        clients,
        _environments(TEST_ENV),
        realm=None,
        agent_link=_link(TEST_ENV, TEST_AGENT),
    )
    assert realm == "test"
    assert identity["agentId"] == TEST_AGENT


@pytest.mark.parametrize(
    ("link", "target", "overrides", "message"),
    [
        (_link(DEV_ENV, DEV_AGENT), FakeClient(route_realm=0), {}, "is the Dev agent"),
        (
            _link(TEST_ENV, TEST_AGENT),
            FakeClient(route_realm=0),
            {},
            "not a Test or Prod agent",
        ),
        (
            _link(TEST_ENV, TEST_AGENT),
            FakeClient(route_realm=1, family=OTHER_FAMILY),
            {},
            "different ALM family",
        ),
        (
            _link(TEST_ENV, TEST_AGENT),
            FakeClient(route_realm=1),
            {"realm": "prod"},
            "not Prod",
        ),
        (
            _link(TEST_ENV, PROD_AGENT),
            FakeClient(route_realm=1),
            {},
            "not the Test promotion",
        ),
        ("not a link", FakeClient(), {}, "full Copilot Studio link"),
    ],
)
def test_agent_link_is_rejected_unless_it_is_the_dev_sibling(
    tmp_path: Path,
    no_dns: None,
    link: str,
    target: FakeClient,
    overrides: dict[str, Any],
    message: str,
) -> None:
    clients = {
        "dev-host": FakeClient(),
        f"https://{TEST_ENV}.prod": target,
        f"https://{DEV_ENV}.prod": target,
    }
    options = {"realm": None, **overrides}
    with pytest.raises(realms.ServiceNowRealmError, match=message):
        _discover_realm(
            tmp_path,
            clients,
            _environments(DEV_ENV, TEST_ENV),
            agent_link=link,
            **options,
        )


def _registry(*, test_ready: bool = False) -> dict[str, Any]:
    registry = realms.new_registry("servicenow", "ess-hr")
    identity = {
        "environmentId": TEST_ENV,
        "environmentUrl": TEST_URL,
        "tenantId": TENANT,
        "agentId": TEST_AGENT,
        "agentSchemaName": SCHEMA,
        "almFamilyId": FAMILY,
        "commitSha": "abc123",
        "sourceAgentId": DEV_AGENT,
    }
    target = realms.record_target(registry, "test", identity, FOUNDATION)
    if test_ready:
        for stage_id in realms.STAGE_IDS:
            target["stages"][stage_id] = {"status": "done"}
    return registry


def test_prod_requires_dev_ready_and_ready_test() -> None:
    registry = _registry()
    with pytest.raises(realms.ServiceNowRealmError, match="Finish the Dev lifecycle"):
        realms.require_realm_prerequisite(registry, "test", dev_ready=False)
    with pytest.raises(realms.ServiceNowRealmError, match="Test must be Ready"):
        realms.require_realm_prerequisite(registry, "prod", dev_ready=True)
    realms.require_realm_prerequisite(
        _registry(test_ready=True), "prod", dev_ready=True
    )


def test_foundation_is_reused_and_tenant_difference_is_rejected() -> None:
    registry = _registry()
    assert registry["targets"]["test"]["foundationReused"] is True
    assert registry["activeTargetRealm"] == "test"
    with pytest.raises(realms.ServiceNowRealmError, match="tenant differs"):
        realms.record_target(
            registry,
            "test",
            {**registry["targets"]["test"]["identity"], "tenantId": OTHER_TENANT},
            FOUNDATION,
        )


def _connection(**overrides: Any) -> dict[str, Any]:
    connection = {
        "connectionId": CONNECTION_ID,
        "authMode": "entraIDUserLogin",
        "status": "Connected",
        "parameterValues": {
            "token:InstanceName": "contoso",
            "token:ResourceUri": CLIENT_ID,
        },
    }
    connection.update(overrides)
    return connection


def test_matching_connection_reuses_foundation() -> None:
    result = realms.evaluate_connections(
        FOUNDATION, {"connectionId": CONNECTION_ID}, [_connection()]
    )
    assert result["status"] == "done"


@pytest.mark.parametrize(
    ("values", "item"),
    [
        ({"token:InstanceName": "other", "token:ResourceUri": CLIENT_ID}, "instance"),
        (
            {"token:InstanceName": "contoso", "token:ResourceUri": "another-client"},
            "client",
        ),
    ],
)
def test_foundation_mismatch_blocks_with_exact_difference(
    values: dict[str, str], item: str
) -> None:
    result = realms.evaluate_connections(
        FOUNDATION,
        {"connectionId": CONNECTION_ID},
        [_connection(parameterValues=values)],
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "foundation-mismatch"
    assert len(result["differences"]) == 1
    assert item in result["differences"][0]["item"].casefold()


def test_unbound_or_unhealthy_connection_needs_the_maker() -> None:
    assert realms.evaluate_connections(FOUNDATION, {}, [])["status"] == "needs-maker"
    unhealthy = realms.evaluate_connections(
        FOUNDATION,
        {"connectionId": CONNECTION_ID},
        [_connection(status="Error")],
    )
    assert unhealthy["status"] == "needs-maker"


def test_runtime_is_read_only_comparison_with_dev() -> None:
    dev = [{"schemaName": "a", "state": "Active", "status": "Active"}]
    portal = {"valid": True}
    assert (
        realms.evaluate_runtime(FOUNDATION, dev, list(dev), portal)["status"] == "done"
    )
    differs = realms.evaluate_runtime(
        FOUNDATION,
        dev,
        [{"schemaName": "a", "state": "Inactive", "status": "Inactive"}],
        {"valid": False, "reason": "portal-topic-missing"},
    )
    assert differs["status"] == "blocked"
    assert len(differs["observations"]) == 2


def test_stages_reach_ready_after_maker_validation() -> None:
    registry = _registry()
    target = registry["targets"]["test"]
    realms.apply_checks(
        target,
        connections={"status": "done", "connectionId": CONNECTION_ID},
        runtime={"status": "done"},
    )
    assert target["stages"]["maker-validation"]["status"] == "needs-maker"
    realms.record_validation(
        target,
        prompt_category=PROMPT,
        allowed_prompt_category=PROMPT,
        result="pass",
        failure_category=None,
    )
    assert realms.target_status(registry, "test") == "ready"
    status = realms.realm_status(registry, dev_ready=True)
    assert status["activeTargetRealm"] == "test"
    assert status["nextPhaseId"] is None
    assert status["targets"]["test"]["foundationReused"] is True


def test_validation_requires_earlier_stages_and_goes_stale() -> None:
    registry = _registry()
    target = registry["targets"]["test"]
    with pytest.raises(realms.ServiceNowRealmError, match="Complete Connections"):
        realms.record_validation(
            target,
            prompt_category=PROMPT,
            allowed_prompt_category=PROMPT,
            result="pass",
            failure_category=None,
        )
    realms.apply_checks(
        target,
        connections={"status": "done", "connectionId": CONNECTION_ID},
        runtime={"status": "done"},
    )
    realms.record_validation(
        target,
        prompt_category=PROMPT,
        allowed_prompt_category=PROMPT,
        result="pass",
        failure_category=None,
    )
    realms.apply_checks(
        target,
        connections={"status": "blocked", "reason": "foundation-mismatch"},
        runtime=None,
    )
    assert target["stages"]["maker-validation"]["status"] == "pending"


def test_registry_round_trips_and_detects_tampering(tmp_path: Path) -> None:
    registry = _registry()
    realms.save_registry(tmp_path, registry)
    loaded = realms.load_registry(tmp_path, "servicenow", "ess-hr")
    assert loaded["targets"]["test"]["identity"]["agentId"] == TEST_AGENT
    path = realms.registry_path(tmp_path, "servicenow", "ess-hr")
    path.write_text(
        path.read_text(encoding="utf-8").replace(TEST_AGENT, PROD_AGENT),
        encoding="utf-8",
    )
    with pytest.raises(realms.ServiceNowRealmError, match="modified outside"):
        realms.load_registry(tmp_path, "servicenow", "ess-hr")


def test_foundation_is_read_from_dev_state() -> None:
    state = {
        "tenantId": TENANT.upper(),
        "adminSetup": {
            "preflight": {"instanceName": "Contoso"},
            "phaseHandoffs": {
                "entra-registration": {"evidence": {"clientId": CLIENT_ID}}
            },
        },
    }
    assert realms.foundation_from_dev_state(state) == FOUNDATION
    with pytest.raises(realms.ServiceNowRealmError, match="incomplete"):
        realms.foundation_from_dev_state({"tenantId": TENANT})


def _controller_context(root: Path) -> dict[str, Any]:
    return {
        "root": str(root),
        "account": "maker@contoso.com",
        "environment": {
            "id": DEV_ENV,
            "ring": "prod",
            "tenant_id": TENANT,
            "power_platform_api_endpoint": "dev-host",
        },
        "agent": {
            "id": DEV_AGENT,
            "schema_name": SCHEMA,
            "workspace_slug": "ess-hr",
        },
    }


def _args(command: str, **values: Any) -> argparse.Namespace:
    defaults = {
        "realm": None,
        "environment": None,
        "agent_link": None,
    }
    return argparse.Namespace(command=command, **{**defaults, **values})


def _prepare_controller(monkeypatch: pytest.MonkeyPatch, *, dev_ready: bool) -> None:
    import connect_servicenow_da as snow

    monkeypatch.setattr(snow, "_realm_dev_ready", lambda _context: dev_ready)
    monkeypatch.setattr(
        snow,
        "_realm_dev_state",
        lambda _context: {
            "tenantId": TENANT,
            "adminSetup": {
                "preflight": {"instanceName": "contoso"},
                "phaseHandoffs": {
                    "entra-registration": {"evidence": {"clientId": CLIENT_ID}}
                },
            },
        },
    )

    def run_checks(_context: dict[str, Any], target: dict[str, Any]) -> None:
        realms.apply_checks(
            target,
            connections={"status": "done", "connectionId": CONNECTION_ID},
            runtime={"status": "done"},
        )

    monkeypatch.setattr(snow, "_realm_run_checks", run_checks)
    monkeypatch.setattr(
        realms,
        "discover_realm",
        lambda **kwargs: (
            kwargs["realm"] or "test",
            {
                "environmentId": TEST_ENV,
                "environmentUrl": TEST_URL,
                "tenantId": TENANT,
                "agentId": TEST_AGENT,
                "agentSchemaName": SCHEMA,
                "almFamilyId": FAMILY,
                "commitSha": "abc123",
                "sourceAgentId": DEV_AGENT,
            },
        ),
    )


def test_controller_discovers_test_and_blocks_prod_until_test_is_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    _prepare_controller(monkeypatch, dev_ready=True)
    context = _controller_context(tmp_path)
    result = snow.run_realm_command(
        context, _args("discover-realm-target", realm="test")
    )
    assert result["activeTargetRealm"] == "test"
    assert result["foundationReused"] is True
    assert result["nextPhaseId"] == "maker-validation"
    assert result["targets"]["test"]["deploymentStatus"] == "in-progress"
    with pytest.raises(
        snow.ServiceNowConnectError, match="Test must be Ready"
    ) as excinfo:
        snow.run_realm_command(context, _args("discover-realm-target", realm="prod"))
    assert excinfo.value.details["recoveryChoices"] == [
        "Check again",
        "Choose another environment",
        "Not now",
    ]


def test_controller_requires_ready_dev_and_a_realm_or_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    _prepare_controller(monkeypatch, dev_ready=False)
    context = _controller_context(tmp_path)
    with pytest.raises(snow.ServiceNowConnectError, match="Finish the Dev lifecycle"):
        snow.run_realm_command(context, _args("discover-realm-target", realm="test"))
    with pytest.raises(snow.ServiceNowConnectError, match="--realm test\\|prod"):
        snow.run_realm_command(context, _args("discover-realm-target"))
    status = snow.run_realm_command(context, _args("realm-status"))
    assert status["activeTargetRealm"] == "dev"
    assert status["targets"]["dev"]["deploymentStatus"] == "in-progress"
