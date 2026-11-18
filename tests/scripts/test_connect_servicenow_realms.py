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

IDENTITY = {
    "environmentId": TEST_ENV,
    "environmentUrl": TEST_URL,
    "tenantId": TENANT,
    "agentId": TEST_AGENT,
    "agentSchemaName": SCHEMA,
    "almFamilyId": FAMILY,
    "commitSha": "abc123",
    "sourceAgentId": DEV_AGENT,
}
DEV_RECORD = {"instanceName": "contoso", "clientId": CLIENT_ID, "tenantId": TENANT}


def _expected(
    *,
    dev_reference: dict[str, str] | None = None,
    previous: dict[str, Any] | None = None,
    provided: dict[str, str] | None = None,
    admin_confirmed: bool = False,
) -> dict[str, Any]:
    return realms.resolve_expected(
        IDENTITY,
        dev_reference=dev_reference,
        previous=previous,
        provided=provided,
        admin_confirmed=admin_confirmed,
    )


FOUNDATION = _expected(dev_reference=DEV_RECORD)


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


def _registry(*, test_ready: bool = False, expected: dict[str, Any] | None = None):
    registry = realms.new_registry("servicenow", "ess-hr")
    target = realms.record_target(registry, "test", IDENTITY, expected or FOUNDATION)
    if test_ready:
        for stage_id in realms.STAGE_IDS:
            target["stages"][stage_id] = {"status": "done"}
    return registry


def test_prod_and_test_are_independent_of_dev_and_each_other() -> None:
    registry = _registry()
    prod_identity = {**IDENTITY, "agentId": PROD_AGENT, "environmentId": OTHER_ENV}
    realms.record_target(registry, "prod", prod_identity, FOUNDATION)
    assert realms.target_status(registry, "test") == "in-progress"
    assert realms.target_status(registry, "prod") == "in-progress"
    realms.select_realm(registry, "prod")
    assert registry["activeTargetRealm"] == "prod"
    status = realms.realm_status(registry)
    assert "dev" not in status["targets"]
    assert status["targets"]["test"]["deploymentStatus"] == "in-progress"


def test_dev_record_is_an_optional_reference_for_expected_values() -> None:
    from_dev = _expected(dev_reference=DEV_RECORD)
    assert from_dev["values"] == {"instanceName": "contoso", "clientId": CLIENT_ID}
    assert realms.expected_blocker(from_dev) is None
    assert realms.foundation_reused(from_dev) is True

    none = _expected()
    blocker = realms.expected_blocker(none)
    assert blocker["reason"] == "expected-values-missing"
    assert blocker["missing"] == [
        "ServiceNow instance",
        "Entra application (client) ID",
    ]
    assert realms.foundation_reused(none) is False


def test_only_missing_values_are_asked_for() -> None:
    partial = _expected(dev_reference={"instanceName": "contoso", "tenantId": TENANT})
    assert realms.expected_blocker(partial)["missing"] == [
        "Entra application (client) ID"
    ]


def test_maker_values_need_admin_confirmation() -> None:
    provided = {"instanceName": "Contoso.service-now.com", "clientId": CLIENT_ID}
    unconfirmed = _expected(provided=provided)
    assert unconfirmed["values"]["instanceName"] == "contoso"
    assert (
        realms.expected_blocker(unconfirmed)["reason"] == "expected-values-unconfirmed"
    )
    confirmed = _expected(provided=provided, admin_confirmed=True)
    assert realms.expected_blocker(confirmed) is None
    again = _expected(previous=confirmed)
    assert realms.expected_blocker(again) is None
    changed = _expected(
        previous=confirmed, provided={"instanceName": "other"}
    )
    assert realms.expected_blocker(changed)["reason"] == "expected-values-unconfirmed"


def test_invalid_maker_values_are_rejected() -> None:
    with pytest.raises(realms.ServiceNowRealmError, match="GUID"):
        _expected(provided={"clientId": "not-a-guid"})
    with pytest.raises(realms.ServiceNowRealmError, match="instance name"):
        _expected(provided={"instanceName": "bad host!"})


def test_maker_values_override_dev_record_and_report_the_difference() -> None:
    expected = _expected(
        dev_reference=DEV_RECORD,
        provided={"instanceName": "contoso-test"},
        admin_confirmed=True,
    )
    assert expected["values"]["instanceName"] == "contoso-test"
    assert expected["values"]["clientId"] == CLIENT_ID
    assert expected["sources"]["clientId"] == "dev-record"
    assert expected["devRecordDifferences"] == [
        {
            "item": "ServiceNow instance",
            "dev": "contoso",
            "expected": "contoso-test",
        }
    ]
    assert realms.foundation_reused(expected) is False


def test_dev_record_from_another_tenant_is_not_reused() -> None:
    other = {**DEV_RECORD, "tenantId": OTHER_TENANT}
    expected = _expected(dev_reference=other)
    assert expected["values"] == {}


def test_recorded_values_do_not_follow_later_dev_changes() -> None:
    registry = _registry()
    previous = registry["targets"]["test"]["expected"]
    changed_dev = {**DEV_RECORD, "instanceName": "new-dev"}
    kept = _expected(dev_reference=changed_dev, previous=previous)
    assert kept["values"]["instanceName"] == "contoso"
    realms.record_target(registry, "test", IDENTITY, kept)
    assert registry["targets"]["test"]["expected"]["values"]["instanceName"] == (
        "contoso"
    )


def test_changing_expected_values_resets_stage_results() -> None:
    registry = _registry(test_ready=True)
    changed = _expected(
        previous=registry["targets"]["test"]["expected"],
        provided={"instanceName": "other"},
        admin_confirmed=True,
    )
    target = realms.update_expected(registry, "test", changed)
    assert all(
        target["stages"][stage_id]["status"] == "pending"
        for stage_id in realms.STAGE_IDS
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


def _bound() -> dict[str, str]:
    return {"connectionId": CONNECTION_ID}


def _statuses(result: dict[str, Any]) -> dict[str, str]:
    return {entry["item"]: entry["status"] for entry in result["items"]}


def test_matching_connection_is_verified_item_by_item() -> None:
    result = realms.evaluate_connections(FOUNDATION, _bound(), [_connection()])
    assert result["status"] == "done"
    assert set(_statuses(result).values()) == {"pass"}


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
def test_instance_or_client_id_mismatch_blocks_with_exact_difference(
    values: dict[str, str], item: str
) -> None:
    result = realms.evaluate_connections(
        FOUNDATION, _bound(), [_connection(parameterValues=values)]
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "connection-mismatch"
    assert len(result["differences"]) == 1
    assert item in result["differences"][0]["item"].casefold()
    assert "doesn't use the expected sign-in values" in result["message"]
    assert result["message"].startswith("**Validation is paused:**")


@pytest.mark.parametrize(
    ("reference", "connections", "reason", "named"),
    [
        ({}, [_connection()], "connection-not-bound", "isn't linked to this agent"),
        (
            {},
            [],
            "connection-not-found",
            "has no ServiceNow connection available",
        ),
        (
            {"connectionId": OTHER_ENV},
            [_connection()],
            "connection-not-found",
            "has no ServiceNow connection available",
        ),
        (
            _bound(),
            [_connection(status="Error")],
            "connection-unhealthy",
            "is disconnected",
        ),
    ],
)
def test_connection_problems_are_blocked_without_a_repair(
    reference: dict[str, str],
    connections: list[dict[str, Any]],
    reason: str,
    named: str,
) -> None:
    result = realms.evaluate_connections(FOUNDATION, reference, connections)
    message = result["message"]
    assert result["status"] == "blocked"
    assert result["reason"] == reason
    assert message.startswith("**Validation is paused:**")
    assert named in message
    assert "BLOCKED" not in message
    assert "recheck before you run the request" in message
    assert "administrator-confirmed sign-in setup stays in place" in message
    assert "connectionHandoff" not in result


def test_dev_on_but_test_off_is_detected_per_item() -> None:
    result = realms.evaluate_connections(FOUNDATION, {}, [])
    assert _statuses(result)["ServiceNow connection is bound to this agent"] == "fail"
    assert _statuses(result)["Connection exists in this environment"] == "fail"
    assert result["status"] != "done"


def test_missing_expected_values_stop_the_connection_check() -> None:
    result = realms.evaluate_connections(_expected(), _bound(), [_connection()])
    assert result["status"] == "needs-maker"
    assert result["reason"] == "expected-values-missing"
    unconfirmed = realms.evaluate_connections(
        _expected(provided={"instanceName": "contoso", "clientId": CLIENT_ID}),
        _bound(),
        [_connection()],
    )
    assert unconfirmed["reason"] == "expected-values-unconfirmed"


def _topic(name: str, state: str = "Active") -> dict[str, str]:
    return {"schemaName": name, "state": state, "status": state}


def test_runtime_checks_required_topics_and_portal_read_only() -> None:
    portal = {"valid": True}
    assert (
        realms.evaluate_runtime(FOUNDATION, [_topic("a"), _topic("b")], portal)[
            "status"
        ]
        == "done"
    )
    off = realms.evaluate_runtime(
        FOUNDATION,
        [_topic("a"), _topic("b", "Inactive")],
        {"valid": False, "reason": "portal-topic-missing"},
    )
    assert off["status"] == "blocked"
    assert len(off["observations"]) == 2
    assert "Fix them in Dev" in off["message"]
    assert "promote again" in off["message"]
    empty = realms.evaluate_runtime(FOUNDATION, [], portal)
    assert empty["status"] == "blocked"


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
    status = realms.realm_status(registry)
    assert status["activeTargetRealm"] == "test"
    assert status["nextPhaseId"] is None
    assert status["targets"]["test"]["expected"]["devRecordReused"] is True


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
        connections={"status": "blocked", "reason": "connection-unhealthy"},
        runtime={"status": "done"},
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


def _dev_state(**entra: Any) -> dict[str, Any]:
    return {
        "tenantId": TENANT.upper(),
        "adminSetup": {
            "preflight": {"instanceName": "Contoso"},
            "phaseHandoffs": {
                "entra-registration": {
                    "status": entra.get("status", "completed"),
                    "evidence": {"clientId": CLIENT_ID},
                }
            },
        },
    }


def test_dev_reference_is_read_from_confirmed_dev_state_only() -> None:
    assert realms.dev_reference_from_state(_dev_state()) == DEV_RECORD
    unconfirmed = realms.dev_reference_from_state(_dev_state(status="pending"))
    assert unconfirmed == {"instanceName": "contoso", "tenantId": TENANT}
    assert realms.dev_reference_from_state({}) == {}


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
        "expected_instance": None,
        "expected_client_id": None,
        "admin_confirmed": False,
    }
    return argparse.Namespace(command=command, **{**defaults, **values})


def _prepare_controller(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dev_reference: dict[str, str] | None,
    world: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fake the promoted realm; `world` is what the realm actually contains."""
    import connect_servicenow_da as snow

    realm_world: dict[str, Any] = world if world is not None else {}
    realm_world.setdefault("reference", _bound())
    realm_world.setdefault("connections", [_connection()])
    realm_world.setdefault("topics", [_topic("a")])
    realm_world.setdefault("portal", {"valid": True})
    monkeypatch.setattr(
        snow, "_realm_dev_reference", lambda _context: dict(dev_reference or {})
    )

    def run_checks(_context: dict[str, Any], target: dict[str, Any]) -> None:
        expected = target["expected"]
        realms.apply_checks(
            target,
            connections=realms.evaluate_connections(
                expected, realm_world["reference"], realm_world["connections"]
            ),
            runtime=realms.evaluate_runtime(
                expected, realm_world["topics"], realm_world["portal"]
            ),
        )

    monkeypatch.setattr(snow, "_realm_run_checks", run_checks)

    def discover(**kwargs: Any):
        realm = kwargs["realm"] or "test"
        agent = TEST_AGENT if realm == "test" else PROD_AGENT
        return realm, {**IDENTITY, "agentId": agent}

    monkeypatch.setattr(realms, "discover_realm", discover)
    return realm_world


def test_controller_checks_test_without_any_dev_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    _prepare_controller(monkeypatch, dev_reference=None)
    context = _controller_context(tmp_path)
    asked = snow.run_realm_command(context, _args("discover-realm-target", realm="test"))
    connections = asked["phases"][0]
    assert connections["reason"] == "expected-values-missing"
    assert connections["missing"] == [
        "ServiceNow instance",
        "Entra application (client) ID",
    ]
    provided = {"expected_instance": "contoso", "expected_client_id": CLIENT_ID}
    unconfirmed = snow.run_realm_command(
        context, _args("check-realm", realm="test", **provided)
    )
    assert unconfirmed["phases"][0]["reason"] == "expected-values-unconfirmed"
    confirmed = snow.run_realm_command(
        context, _args("check-realm", realm="test", admin_confirmed=True)
    )
    assert confirmed["phases"][0]["status"] == "complete"
    assert confirmed["nextPhaseId"] == "maker-validation"
    assert confirmed["targets"]["test"]["deploymentStatus"] == "in-progress"


def test_controller_detects_dev_on_but_test_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    world = _prepare_controller(monkeypatch, dev_reference=DEV_RECORD)
    world.update(
        reference={}, connections=[], topics=[_topic("a", "Inactive")], portal={}
    )
    result = snow.run_realm_command(
        _controller_context(tmp_path), _args("discover-realm-target", realm="test")
    )
    by_id = {phase["id"]: phase for phase in result["phases"]}
    assert by_id["connections"]["status"] == "blocked"
    assert by_id["connections"]["message"].startswith("**Validation is paused:**")
    assert "connectionHandoff" not in result
    assert by_id["runtime-configuration"]["status"] == "blocked"
    assert result["targets"]["test"]["deploymentStatus"] == "blocked"
    assert result["activeTargetRealm"] == "test"


def test_controller_prod_does_not_need_test_ready_or_dev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    _prepare_controller(monkeypatch, dev_reference=DEV_RECORD)
    context = _controller_context(tmp_path)
    prod = snow.run_realm_command(context, _args("discover-realm-target", realm="prod"))
    assert prod["activeTargetRealm"] == "prod"
    assert prod["nextPhaseId"] == "maker-validation"
    assert prod["targets"]["test"]["deploymentStatus"] == "not-discovered"


def test_controller_realm_states_are_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    world = _prepare_controller(monkeypatch, dev_reference=DEV_RECORD)
    context = _controller_context(tmp_path)
    snow.run_realm_command(context, _args("discover-realm-target", realm="test"))
    snow.run_realm_command(context, _args("discover-realm-target", realm="prod"))
    world["connections"] = [_connection(status="Error")]
    after_prod = snow.run_realm_command(context, _args("check-realm", realm="prod"))
    assert after_prod["phases"][0]["reason"] == "connection-unhealthy"
    status = snow.run_realm_command(context, _args("realm-status"))
    assert "dev" not in status["targets"]
    registry = realms.load_registry(
        tmp_path, snow.ACTIVE_PROFILE.provider_key, "ess-hr"
    )
    assert registry["targets"]["test"]["stages"]["connections"]["status"] == "done"
    assert registry["targets"]["prod"]["stages"]["connections"]["status"] == "blocked"


def test_controller_dev_changes_do_not_invalidate_a_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    _prepare_controller(monkeypatch, dev_reference=DEV_RECORD)
    context = _controller_context(tmp_path)
    snow.run_realm_command(context, _args("discover-realm-target", realm="test"))
    _prepare_controller(
        monkeypatch, dev_reference={**DEV_RECORD, "instanceName": "new-dev"}
    )
    result = snow.run_realm_command(context, _args("check-realm", realm="test"))
    assert result["targets"]["test"]["expected"]["values"]["instanceName"] == "contoso"
    assert result["phases"][0]["status"] == "complete"


def test_controller_requires_a_realm_or_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    _prepare_controller(monkeypatch, dev_reference=None)
    context = _controller_context(tmp_path)
    with pytest.raises(snow.ServiceNowConnectError, match="--realm test\\|prod"):
        snow.run_realm_command(context, _args("discover-realm-target"))
    status = snow.run_realm_command(context, _args("realm-status"))
    assert status["activeTargetRealm"] == "dev"


class _DeniedClient(FakeClient):
    def __init__(self, status_code: int) -> None:
        super().__init__()
        self.status_code = status_code

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        raise AgentBuilderHTTPError("access", status_code=self.status_code)


def test_denied_and_inconclusive_access_have_separate_messages(
    tmp_path: Path, no_dns: None
) -> None:
    def failure(status_code: int) -> realms.ServiceNowRealmError:
        clients = {
            "dev-host": FakeClient(),
            f"https://{TEST_ENV}.prod": _DeniedClient(status_code),
        }
        with pytest.raises(realms.ServiceNowRealmError) as excinfo:
            _discover_realm(tmp_path, clients, _environments(TEST_ENV))
        return excinfo.value

    denied = failure(403)
    assert "doesn't have the required access" in str(denied)
    assert "Environment Maker role" in denied.customer_remediation
    inconclusive = failure(500)
    assert "couldn't verify" in str(inconclusive)
    assert "doesn't mean your access was denied" in str(inconclusive)
    assert "Retry the access check to continue." in inconclusive.customer_remediation


@pytest.mark.parametrize(
    ("profile", "realm", "lookup", "not_covered", "limit"),
    [
        ("hrsd", "test", "HR case lookup", "case creation", "Prod behavior"),
        ("hrsd", "prod", "HR case lookup", "case creation", "release readiness"),
        ("itsm", "test", "IT ticket lookup", "ticket creation", "Prod behavior"),
        ("itsm", "prod", "IT ticket lookup", "ticket creation", "release readiness"),
    ],
)
def test_completion_says_what_was_and_was_not_verified(
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
    realm: str,
    lookup: str,
    not_covered: str,
    limit: str,
) -> None:
    import connect_servicenow_da as snow

    monkeypatch.setattr(snow, "ACTIVE_PROFILE", snow.PRODUCT_PROFILES[profile])
    message = snow._realm_completion_message(realm)
    label = realm.title()
    assert message.startswith(f"**Your {lookup} worked in {label}.**")
    assert f"not {not_covered}" in message
    assert "other employees' sign-in mapping" in message
    assert message.endswith(f"{limit}.")
    assert "publish" not in message.lower()
    assert "Ready" not in message


REALMS_GUIDE = (
    Path(__file__).resolve().parents[2]
    / "solutions/ess-maker-skills/src/skills/connect/servicenow/realms.md"
)


def test_realms_guide_carries_the_spec_questions() -> None:
    text = " ".join(
        line.removeprefix("> ").removeprefix(">").strip()
        for line in REALMS_GUIDE.read_text(encoding="utf-8").splitlines()
    )
    for phrase in (
        "Which destination should we check, Test or Prod?",
        "What did the request from **{Agent} in {Environment}** return, and was "
        "that what you expected?",
        "do not treat it as pass or fail and do not run `record-realm-test`",
        "Use the agent in {Environment}, not the Dev agent.",
        "Did the Test pane show an error or only an empty result?",
        "That's a {Dev|Test} result; we still need",
        "The HR service-area list is empty.",
        "doesn't switch this run to the Test environment",
    ):
        assert phrase in text, phrase
    assert "publishing and non-maker validation" not in text
    assert "finish without testing" not in text


def test_realms_guide_carries_the_s5_recovery_wording() -> None:
    text = " ".join(
        line.strip().removeprefix(">").strip()
        for line in REALMS_GUIDE.read_text(encoding="utf-8").splitlines()
    )
    for phrase in (
        "**Validation is paused:**",
        "Retry the access check to continue.",
        "A working Dev connection doesn't tell us whether a usable connection is "
        "available and linked to this agent in **{Environment}**.",
        "The Dev integration was left untested",
        "This run will establish the result for **{Agent} in {Environment}**.",
        "We'll switch to **{Agent} in {Environment}**, verify your permission "
        "there, and revalidate",
        "won't count as a {Prod|Test} result.",
        "That doesn't match the result you expected. We'll check the available "
        "setup information",
        "That matches what you expected, but an empty result alone doesn't show "
        "whether the agent can retrieve your HR data.",
        "That changes the shared-instance assumption behind this promotion path.",
        "your own deployment process",
    ):
        assert phrase in text, phrase
    for stale in ("BLOCKED.", "Connect does not offer", "ALM tool", "ALM process"):
        assert stale not in text, stale


def test_realms_guide_maker_text_has_no_technical_headers() -> None:
    text = REALMS_GUIDE.read_text(encoding="utf-8")
    quoted = [line for line in text.splitlines() if line.startswith(">")]
    form_text = [
        line
        for line in text.splitlines()
        if line.strip().startswith(('"title"', '"description"'))
    ]
    forbidden = (
        "activeTargetRealm",
        "connectionId",
        "BotId",
        "schemaName",
        "nextPhaseId",
        "python",
        "scripts/",
        "--",
    )
    assert quoted and form_text
    for line in quoted + form_text:
        for token in forbidden:
            assert token not in line, (token, line)
