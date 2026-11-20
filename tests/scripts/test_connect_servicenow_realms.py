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


@pytest.fixture(autouse=True)
def _checklist_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rendering tests exercise the restorable legacy rows; the default-view
    tests set the flags back inside the test."""
    monkeypatch.setattr(realms, "SHOW_REALM_CHECKLIST", True)
    monkeypatch.setattr(realms, "SHOW_LEGACY_REALM_ROWS", True)


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
    changed = _expected(previous=confirmed, provided={"instanceName": "other"})
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


def test_untested_finish_is_saved_but_never_a_pass() -> None:
    registry = _registry()
    target = registry["targets"]["test"]
    realms.apply_checks(
        target,
        connections={"status": "done", "connectionId": CONNECTION_ID},
        runtime={"status": "done"},
    )
    stage = realms.record_validation(
        target,
        prompt_category=PROMPT,
        allowed_prompt_category=PROMPT,
        result="untested",
        failure_category=None,
    )
    assert stage["status"] == "untested"
    assert stage["result"] == "untested"
    assert realms.target_status(registry, "test") == "untested"
    status = realms.realm_status(registry)
    assert status["targets"]["test"]["deploymentStatus"] == "untested"
    assert status["nextPhaseId"] == "maker-validation"
    phase = next(p for p in status["phases"] if p["id"] == "maker-validation")
    assert phase["status"] == "untested"
    assert phase["status"] != "complete"
    # A later check keeps it untested while setup is unchanged.
    realms.apply_checks(
        target,
        connections={"status": "done", "connectionId": CONNECTION_ID},
        runtime={"status": "done"},
    )
    assert target["stages"]["maker-validation"]["status"] == "untested"
    # A later pass replaces it.
    realms.record_validation(
        target,
        prompt_category=PROMPT,
        allowed_prompt_category=PROMPT,
        result="pass",
        failure_category=None,
    )
    assert realms.target_status(registry, "test") == "ready"
    # And a later fail replaces an untested result too.
    realms.record_validation(
        target,
        prompt_category=PROMPT,
        allowed_prompt_category=PROMPT,
        result="untested",
        failure_category=None,
    )
    realms.record_validation(
        target,
        prompt_category=PROMPT,
        allowed_prompt_category=PROMPT,
        result="fail",
        failure_category="unexpected",
    )
    assert realms.target_status(registry, "test") == "blocked"


def test_untested_requires_earlier_stages_and_goes_stale_when_setup_breaks() -> None:
    registry = _registry()
    target = registry["targets"]["test"]
    with pytest.raises(realms.ServiceNowRealmError, match="Complete Connections"):
        realms.record_validation(
            target,
            prompt_category=PROMPT,
            allowed_prompt_category=PROMPT,
            result="untested",
            failure_category=None,
        )
    realms.apply_checks(
        target,
        connections={"status": "done", "connectionId": CONNECTION_ID},
        runtime={"status": "done"},
    )
    with pytest.raises(realms.ServiceNowRealmError, match="failure category"):
        realms.record_validation(
            target,
            prompt_category=PROMPT,
            allowed_prompt_category=PROMPT,
            result="untested",
            failure_category="unexpected",
        )
    realms.record_validation(
        target,
        prompt_category=PROMPT,
        allowed_prompt_category=PROMPT,
        result="untested",
        failure_category=None,
    )
    realms.apply_checks(
        target,
        connections={"status": "blocked", "reason": "connection-unhealthy"},
        runtime={"status": "done"},
    )
    assert target["stages"]["maker-validation"]["status"] == "pending"
    assert realms.target_status(registry, "test") == "blocked"


def test_untested_message_is_plain_and_names_no_success() -> None:
    import connect_servicenow_da as snow

    message = snow._realm_untested_message("test")
    assert message.startswith(
        "**The applicable ServiceNow setup steps in Test are finished, but "
        "this destination integration remains untested.**"
    )
    assert "Test this agent before employees use it." in message
    assert "Your progress is saved at the destination Test-pane request." in message
    assert "worked" not in message


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


def _complete_dev_state() -> dict[str, Any]:
    state = _dev_state()
    state["adminSetup"]["preflight"].update(
        instanceSource="maker-confirmed", recordedAt="2026-01-01T00:00:00Z"
    )
    state["adminSetup"]["phaseHandoffs"]["entra-registration"]["evidence"][
        "selectedClaimName"
    ] = "email"
    state["adminSetup"]["phaseHandoffs"]["servicenow-oidc"] = {
        "status": "completed",
        "evidence": {"serviceNowUserField": "email"},
    }
    return state


def _prepare_controller(
    monkeypatch: pytest.MonkeyPatch,
    *,
    dev_reference: dict[str, str] | None,
    dev_state: dict[str, Any] | None = None,
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
    recorded_dev = (
        dev_state
        if dev_state is not None
        else (_complete_dev_state() if dev_reference else {})
    )
    monkeypatch.setattr(snow, "_realm_dev_state", lambda _context: recorded_dev)

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
    asked = snow.run_realm_command(
        context, _args("discover-realm-target", realm="test")
    )
    assert asked["phases"][0]["status"] == "pending"
    assert asked["renderBlock"]["case"] == "independent"
    with pytest.raises(snow.ServiceNowConnectError, match="never typed in"):
        snow.run_realm_command(
            context,
            _args("check-realm", realm="test", expected_client_id=CLIENT_ID),
        )
    with pytest.raises(snow.ServiceNowConnectError, match="never typed in"):
        snow.run_realm_command(
            context, _args("check-realm", realm="test", admin_confirmed=True)
        )


def _admin_args(stage: str, **values: Any) -> argparse.Namespace:
    defaults = {
        "client_id": None,
        "claim_name": None,
        "user_field": None,
        "directory_tenant_id": None,
        "confirm_saved_mapping": False,
    }
    return _args(
        "record-realm-admin", realm="test", stage=stage, **{**defaults, **values}
    )


def _block(result: dict[str, Any]) -> str:
    return result["renderBlock"]["text"]


def test_case_two_runs_the_full_administrator_flow_then_the_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    _prepare_controller(monkeypatch, dev_reference=None)
    context = _controller_context(tmp_path)
    first = snow.run_realm_command(
        context, _args("discover-realm-target", realm="test")
    )
    text = _block(first)
    assert first["renderBlock"]["case"] == "independent"
    assert (
        "We couldn't find a completed Dev setup for this agent, so we'll run "
        "the full ServiceNow setup for Test. We'll start with your "
        "administrators, then check the connection, topics, and portal."
    ) in text
    assert [
        line.split(" — ")[0][2:]
        for line in text.splitlines()
        if line and line[0] in "✅🔄⬜⏳❌"
    ] == [
        "Permission to configure this agent",
        "Microsoft Entra administrator (Client ID and claim)",
        "ServiceNow administrator (employee mapping / User Field)",
        "ServiceNow connection",
        "Topics",
        "Portal URL",
        "Real-data test in the Test pane",
    ]
    assert _icons(text) == ["✅", "⏳", "⬜", "⬜", "⬜", "⬜", "⬜"]
    assert "What is your ServiceNow instance name" in text
    assert "Instructions for the Entra administrator" not in text
    assert "Test pane" in text and "Waiting for you" not in text

    entra = snow.run_realm_command(
        context, _args("check-realm", realm="test", expected_instance="Contoso")
    )
    text = _block(entra)
    assert _icons(text) == ["✅", "⏳", "⬜", "⬜", "⬜", "⬜", "⬜"]
    assert "Instructions for the Entra administrator" in text
    assert "Instructions for the ServiceNow administrator" not in text
    assert "Tenant ID" not in text.split("Ready-to-send message")[1]

    with pytest.raises(snow.ServiceNowConnectError, match="aud"):
        snow.run_realm_command(
            context,
            _admin_args("entra", client_id=CLIENT_ID, claim_name="AUD"),
        )
    with pytest.raises(snow.ServiceNowConnectError, match="does not match"):
        snow.run_realm_command(
            context,
            _admin_args(
                "entra",
                client_id=CLIENT_ID,
                claim_name="email",
                directory_tenant_id=OTHER_ENV,
            ),
        )
    with pytest.raises(snow.ServiceNowConnectError, match="comes first"):
        snow.run_realm_command(
            context,
            _admin_args("servicenow", user_field="email", confirm_saved_mapping=True),
        )

    mapping = snow.run_realm_command(
        context,
        _admin_args("entra", client_id=CLIENT_ID.upper(), claim_name="email"),
    )
    text = _block(mapping)
    assert _icons(text) == ["✅", "✅", "⏳", "⬜", "⬜", "⬜", "⬜"]
    assert "Instructions for the ServiceNow administrator" in text
    assert f"`{CLIENT_ID}`" in text
    assert "https://contoso.service-now.com" in text
    assert f"login.microsoftonline.com/{TENANT}/.well-known" in text
    for placeholder in ("<client ID>", "<tenant ID>", "<instance>", "<claim>"):
        assert (
            placeholder not in text.split("Ready-to-send message")[1].split("Part 1")[0]
        )

    with pytest.raises(snow.ServiceNowConnectError, match="saved"):
        snow.run_realm_command(context, _admin_args("servicenow", user_field="email"))
    with pytest.raises(snow.ServiceNowConnectError, match="field name"):
        snow.run_realm_command(
            context,
            _admin_args(
                "servicenow", user_field="bad field!", confirm_saved_mapping=True
            ),
        )
    done = snow.run_realm_command(
        context,
        _admin_args("servicenow", user_field="email", confirm_saved_mapping=True),
    )
    text = _block(done)
    assert _icons(text) == ["✅"] * 6 + ["⏳"]
    assert "Instructions for the" not in text
    assert done["nextPhaseId"] == "maker-validation"
    registry = realms.load_registry(
        tmp_path, snow.ACTIVE_PROFILE.provider_key, "ess-hr"
    )
    assert registry["targets"]["test"]["expected"]["sources"] == {
        "instanceName": "maker",
        "clientId": "entra-administrator",
    }

    again = snow.run_realm_command(
        context, _args("discover-realm-target", realm="test")
    )
    assert again["renderBlock"]["case"] == "independent"
    assert _icons(_block(again)) == ["✅"] * 6 + ["⏳"]


def test_case_two_rechecks_only_the_failing_step_after_the_admin_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    world = _prepare_controller(monkeypatch, dev_reference=None)
    world["connections"] = []
    world["reference"] = {}
    context = _controller_context(tmp_path)
    snow.run_realm_command(context, _args("discover-realm-target", realm="test"))
    snow.run_realm_command(
        context, _args("check-realm", realm="test", expected_instance="contoso")
    )
    snow.run_realm_command(
        context, _admin_args("entra", client_id=CLIENT_ID, claim_name="email")
    )
    blocked = snow.run_realm_command(
        context,
        _admin_args("servicenow", user_field="email", confirm_saved_mapping=True),
    )
    assert _icons(_block(blocked)) == ["✅", "✅", "✅", "❌", "⬜", "⬜", "⬜"]
    world["connections"] = [_connection()]
    world["reference"] = _bound()
    fixed = snow.run_realm_command(context, _args("check-realm", realm="test"))
    assert _icons(_block(fixed)) == ["✅"] * 6 + ["⏳"]


def test_case_one_reuses_the_dev_setup_without_any_administrator_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    _prepare_controller(monkeypatch, dev_reference=DEV_RECORD)
    context = _controller_context(tmp_path)
    result = snow.run_realm_command(
        context, _args("discover-realm-target", realm="test")
    )
    text = _block(result)
    assert result["renderBlock"]["case"] == "dev-reuse"
    assert (
        "We'll retain the administrator-confirmed sign-in setup and employee "
        "mapping that still applies to this ServiceNow instance."
    ) in text
    assert "We won't repeat completed administrator work." in text
    assert _icons(text) == ["✅", "✅", "✅", "✅", "⏳"]
    assert "Microsoft Entra administrator" not in text
    assert "ServiceNow administrator" not in text
    assert "Instructions for the" not in text
    assert "adminInstruction" not in text
    with pytest.raises(snow.ServiceNowConnectError, match="reuses"):
        snow.run_realm_command(
            context,
            _admin_args("entra", client_id=CLIENT_ID, claim_name="email"),
        )


def _state_without(path: tuple[str, ...]) -> dict[str, Any]:
    state = _complete_dev_state()
    node = state
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    return state


@pytest.mark.parametrize(
    "state",
    [
        _state_without(("adminSetup", "phaseHandoffs", "servicenow-oidc")),
        _state_without(
            (
                "adminSetup",
                "phaseHandoffs",
                "entra-registration",
                "evidence",
                "selectedClaimName",
            )
        ),
        _state_without(("adminSetup", "phaseHandoffs", "entra-registration")),
        _state_without(("adminSetup", "preflight", "instanceSource")),
        {**_complete_dev_state(), "tenantId": OTHER_ENV},
        {},
    ],
    ids=[
        "no-employee-mapping",
        "no-claim",
        "no-entra",
        "instance-not-confirmed",
        "other-tenant",
        "no-record",
    ],
)
def test_any_missing_dev_value_means_the_full_administrator_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: dict[str, Any]
) -> None:
    import connect_servicenow_da as snow

    _prepare_controller(monkeypatch, dev_reference=DEV_RECORD, dev_state=state)
    result = snow.run_realm_command(
        _controller_context(tmp_path), _args("discover-realm-target", realm="test")
    )
    assert result["renderBlock"]["case"] == "independent"
    assert "Microsoft Entra administrator" in _block(result)
    assert _icons(_block(result))[1] == "⏳"


def test_complete_dev_state_is_case_one_for_the_same_tenant_only() -> None:
    assert realms.dev_admin_setup_complete(_complete_dev_state(), TENANT)
    assert not realms.dev_admin_setup_complete(_complete_dev_state(), OTHER_ENV)
    assert not realms.dev_admin_setup_complete({}, TENANT)


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


def test_controller_records_untested_persists_and_pass_replaces_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import connect_servicenow_da as snow

    _prepare_controller(monkeypatch, dev_reference=DEV_RECORD)
    context = _controller_context(tmp_path)
    snow.run_realm_command(context, _args("discover-realm-target", realm="test"))
    prompt = snow.ACTIVE_PROFILE.test_prompt_category
    untested = snow.run_realm_command(
        context,
        _args(
            "record-realm-test",
            realm="test",
            prompt_category=prompt,
            result="untested",
            failure_category=None,
        ),
    )
    assert untested["targets"]["test"]["deploymentStatus"] == "untested"
    assert untested["nextPhaseId"] == "maker-validation"
    assert untested["message"].startswith(
        "**The applicable ServiceNow setup steps in Test are finished, but "
        "this destination integration remains untested.**"
    )
    assert "worked" not in untested["message"]
    registry = realms.load_registry(
        tmp_path, snow.ACTIVE_PROFILE.provider_key, "ess-hr"
    )
    assert registry["targets"]["test"]["stages"]["maker-validation"]["result"] == (
        "untested"
    )
    on_return = snow.run_realm_command(context, _args("check-realm", realm="test"))
    assert on_return["targets"]["test"]["deploymentStatus"] == "untested"
    status = snow.run_realm_command(context, _args("realm-status"))
    assert status["targets"]["test"]["deploymentStatus"] == "untested"
    passed = snow.run_realm_command(
        context,
        _args(
            "record-realm-test",
            realm="test",
            prompt_category=prompt,
            result="pass",
            failure_category=None,
        ),
    )
    assert passed["targets"]["test"]["deploymentStatus"] == "ready"
    assert passed["message"].startswith("**Your ")


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
    assert (
        "Retry the permission check to continue." in inconclusive.customer_remediation
    )


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
        "You can also finish without testing; this integration in {Environment} "
        "will remain untested.",
        "You can also finish without testing; the Prod integration will remain "
        "untested. Test it before employees use it.",
        "**The applicable ServiceNow setup steps in {Environment} are finished, "
        "but this destination integration remains untested.** Test this agent "
        "before employees use it.",
        "Your progress is saved at the destination Test-pane request. When you "
        "return, we'll continue there.",
        "This destination remains untested; its setup isn't complete.",
        "--result untested",
    ):
        assert phrase in text, phrase
    assert "publishing and non-maker validation" not in text


def test_realms_guide_carries_the_s5_recovery_wording() -> None:
    text = " ".join(
        line.strip().removeprefix(">").strip()
        for line in REALMS_GUIDE.read_text(encoding="utf-8").splitlines()
    )
    for phrase in (
        'ends with "Validation is paused"',
        "Retry the permission check to continue.",
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
        "We'll retain the earlier result only for its original instance and "
        "identify which setup information needs review.",
        "Bring back their non-sensitive reply after any required access work is "
        "complete.",
        "We're continuing ServiceNow validation for **{Agent} in {Environment}**.",
        "verbatim when it is non-empty",
        'reply "Done" and we\'ll recheck this step only',
        "publish the agent in Dev",
    ):
        assert phrase in text, phrase
    assert "Show each item in" not in text
    for stale in ("BLOCKED.", "Connect does not offer", "ALM tool", "ALM process"):
        assert stale not in text, stale


def test_realms_guide_describes_both_administrator_cases() -> None:
    guide = " ".join(REALMS_GUIDE.read_text(encoding="utf-8").split())
    assert "Do not re-issue an administrator handoff automatically" not in guide
    for expected in (
        "`dev-reuse`",
        "`independent`",
        "Partial reuse is never offered",
        "record-realm-admin --realm {test|prod} --stage entra",
        "record-realm-admin --realm {test|prod} --stage servicenow",
        "Never pass `--expected-client-id` or `--admin-confirmed` in an independent run",
        "never ask the maker for a tenant ID",
        "do not paraphrase its\nexplanation or its instruction".replace("\n", " "),
    ):
        assert expected in guide, expected


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
    assert quoted
    for line in quoted + form_text:
        for token in forbidden:
            assert token not in line, (token, line)


def _render_context(**overrides: Any) -> dict[str, Any]:
    return {
        "agent": "Employee Self-Service (HR)",
        "kind": "HR",
        "record": "case",
        "example": "Show my open HR cases",
        "agentUrl": None,
        **overrides,
    }


def _rendered(
    realm: str = "test",
    *,
    connections: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    registry = _registry()
    if realm == "prod":
        prod_identity = {**IDENTITY, "agentId": PROD_AGENT, "environmentId": OTHER_ENV}
        realms.record_target(registry, "prod", prod_identity, FOUNDATION)
    realms.select_realm(registry, realm)
    target = registry["targets"][realm]
    realms.apply_checks(
        target,
        connections=connections
        or realms.evaluate_connections(FOUNDATION, _bound(), [_connection()]),
        runtime=runtime
        or realms.evaluate_runtime(FOUNDATION, [_topic("a")], {"valid": True}),
    )
    result = realms.realm_status(registry, render=context or _render_context())
    assert result["renderBlock"]["kind"] == "realm-checklist"
    return result["renderBlock"]["text"]


def _icons(block: str) -> list[str]:
    return [
        line.split(" ", 1)[0]
        for line in block.splitlines()
        if line and line[0] in "✅🔄⬜⏳❌"
    ]


def test_realm_block_all_pass_waits_for_the_test_pane_request() -> None:
    block = _rendered()
    assert block.startswith(
        "**ServiceNow validation: Employee Self-Service (HR) in Test**"
    )
    assert _icons(block) == ["✅", "✅", "✅", "✅", "⏳"]
    assert "Real-data test in the Test pane — Waiting for you" in block
    assert "run an HR request in that agent's **Test pane**" in block
    assert "Use the agent in Test, not the Dev agent." in block
    assert (
        "You can also finish without testing; this integration in Test will "
        "remain untested."
    ) in block


def test_realm_block_prod_request_matches_the_spec_variant() -> None:
    block = _rendered("prod")
    assert "in Prod**" in block
    assert "doesn't switch this run to the Test environment" in block
    assert (
        "You can also finish without testing; the Prod integration will remain "
        "untested. Test it before employees use it."
    ) in block


@pytest.mark.parametrize(
    ("reference", "connections", "named", "step"),
    [
        ({}, [], "has no ServiceNow connection available", "Create new connection"),
        (
            {},
            [_connection()],
            "isn't linked to",
            "Select the ServiceNow connection available in Test",
        ),
        (_bound(), [_connection(status="Error")], "is disconnected", "**Connected**"),
        (
            _bound(),
            [
                _connection(
                    parameterValues={
                        "token:InstanceName": "other",
                        "token:ResourceUri": CLIENT_ID,
                    }
                )
            ],
            "doesn't use the expected sign-in values",
            "expected `contoso`, found `other`",
        ),
    ],
)
def test_realm_block_connection_problems_carry_dev_style_steps(
    reference: dict[str, str],
    connections: list[dict[str, Any]],
    named: str,
    step: str,
) -> None:
    block = _rendered(
        connections=realms.evaluate_connections(FOUNDATION, reference, connections)
    )
    assert _icons(block) == ["✅", "❌", "⬜", "⬜", "⬜"]
    assert "**Validation is paused:**" in block
    assert named in block
    assert step in block
    assert 'reply "Done" and we\'ll recheck this step only.' in block
    assert "Dev connection" not in block
    assert "BLOCKED" not in block
    assert "Show my open HR cases" not in block


def test_realm_block_topics_disabled_points_back_to_dev_and_publish() -> None:
    block = _rendered(
        runtime=realms.evaluate_runtime(
            FOUNDATION,
            [_topic("a"), _topic("b", "Inactive")],
            {"valid": True},
        )
    )
    assert _icons(block) == ["✅", "✅", "❌", "⬜", "⬜"]
    assert "`b`" in block
    assert "Test is a managed environment" in block
    assert (
        "Go back to Dev and update the topics: run `/connect servicenow` again."
        in block
    )
    assert "Publish the agent in Dev." in block
    assert (
        "Deploy (promote) Employee Self-Service (HR) to Test again through your "
        "own deployment process."
    ) in block
    assert 'Reply "Done" and we\'ll recheck this step only.' in block
    assert "manually" not in block


def test_realm_block_portal_problem_keeps_topics_green() -> None:
    block = _rendered(
        "prod",
        runtime=realms.evaluate_runtime(
            FOUNDATION, [_topic("a")], {"valid": False, "reason": "missing"}
        ),
        context=_render_context(kind="IT", record="ticket"),
    )
    assert _icons(block) == ["✅", "✅", "✅", "❌", "⬜"]
    assert "ticket links" in block
    assert "Prod is a managed environment" in block
    assert "Go back to Dev and update the portal URL" in block
    assert "Publish the agent in Dev." in block
    assert "to Prod again" in block


def test_realm_block_untested_and_ready_footers() -> None:
    registry = _registry()
    target = registry["targets"]["test"]
    realms.apply_checks(
        target,
        connections={"status": "done", "connectionId": CONNECTION_ID},
        runtime={"status": "done"},
    )
    realms.record_validation(
        target,
        prompt_category=PROMPT,
        allowed_prompt_category=PROMPT,
        result="untested",
        failure_category=None,
    )
    context = _render_context(footer="Untested footer.")
    untested = realms.realm_status(registry, render=context)["renderBlock"]["text"]
    assert _icons(untested) == ["✅", "✅", "✅", "✅", "⏳"]
    assert "Untested; your progress is saved" in untested
    assert untested.endswith("Untested footer.")
    realms.record_validation(
        target,
        prompt_category=PROMPT,
        allowed_prompt_category=PROMPT,
        result="pass",
        failure_category=None,
    )
    ready = realms.realm_status(registry, render=_render_context(footer="Ready."))
    assert _icons(ready["renderBlock"]["text"]) == ["✅"] * 5
    assert ready["renderBlock"]["text"].endswith("Ready.")


def test_realm_status_without_render_context_has_no_block() -> None:
    assert "renderBlock" not in realms.realm_status(_registry())


def test_realm_checklist_defaults_to_a_snapshot_and_state_is_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(realms, "SHOW_REALM_CHECKLIST", True)
    monkeypatch.setattr(realms, "SHOW_LEGACY_REALM_ROWS", False)
    assert realms.PROGRESS_DELIVERY == "chat"
    registry = _registry()
    result = realms.realm_status(registry, render=_render_context(footer="Footer."))
    block = result["renderBlock"]
    assert block["kind"] == "realm-step"
    assert not _icons(block["text"])
    assert block["text"].endswith("Footer.")
    assert "✅" not in block["text"] and "⬜" not in block["text"]
    assert result["realmIntro"]
    assert block["progressTodos"] == []
    snapshot = block["progressSnapshot"]
    lines = snapshot.splitlines()
    assert lines[0].startswith("Here's your ") and lines[1] == ""
    assert lines[2:] and all(
        line.startswith("- ") and line[2] in "✅🔄⛔⬜" for line in lines[2:]
    )

    monkeypatch.setattr(realms, "PROGRESS_DELIVERY", "todo")
    todo = realms.realm_status(registry, render=_render_context(footer="Footer."))
    assert todo["renderBlock"]["progressSnapshot"] == ""
    todos = todo["renderBlock"]["progressTodos"]
    assert todos and [t["id"] for t in todos] == list(range(1, len(todos) + 1))
    assert all(
        t["status"] in {"completed", "in-progress", "not-started"} for t in todos
    )
    assert any(t["title"] == "Permission to configure this agent" for t in todos)
    assert all("—" not in t["title"] for t in todos)
    monkeypatch.setattr(realms, "PROGRESS_DELIVERY", "chat")

    monkeypatch.setattr(realms, "SHOW_REALM_CHECKLIST", False)
    hidden = realms.realm_status(registry, render=_render_context(footer="Footer."))
    assert hidden["renderBlock"]["progressSnapshot"] == ""
    assert hidden["renderBlock"]["progressTodos"] == []
    assert hidden["phases"] == result["phases"]

    monkeypatch.setattr(realms, "SHOW_LEGACY_REALM_ROWS", True)
    shown = realms.realm_status(registry, render=_render_context(footer="Footer."))
    assert shown["renderBlock"]["kind"] == "realm-checklist"
    assert _icons(shown["renderBlock"]["text"])


def test_realm_block_has_no_technical_headers() -> None:
    blocks = [
        _rendered(),
        _rendered(connections=realms.evaluate_connections(FOUNDATION, {}, [])),
        _rendered(runtime=realms.evaluate_runtime(FOUNDATION, [], {"valid": False})),
    ]
    for block in blocks:
        for token in ("connectionId", "BotId", "nextPhaseId", "scripts/", "python"):
            assert token not in block, token


@pytest.mark.parametrize("profile", ["hrsd", "itsm"])
def test_controller_returns_the_checklist_first_for_hr_and_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    import connect_servicenow_da as snow

    monkeypatch.setattr(snow, "ACTIVE_PROFILE", snow.PRODUCT_PROFILES[profile])
    world = _prepare_controller(monkeypatch, dev_reference=DEV_RECORD)
    context = _controller_context(tmp_path)
    kind = "HR" if profile == "hrsd" else "IT"
    record = "case" if profile == "hrsd" else "ticket"
    waiting = snow.run_realm_command(
        context, _args("discover-realm-target", realm="test")
    )
    text = waiting["renderBlock"]["text"]
    wrapped = snow._with_agent_rules(waiting, "discover-realm-target")
    assert list(wrapped)[:3] == ["chatMessage", "endTurn", "renderBlock"]
    assert wrapped["chatMessage"] == text
    assert (
        snow.ACTIVE_PROFILE.agent_display_name.replace("(", "").replace(")", "")
        in text
    )
    assert f"run an {kind} request" in text or f"run a {kind} request" in text
    assert f"open {'HR cases' if kind == 'HR' else 'IT tickets'}" in text
    assert f"paste {record} contents" in text
    world["topics"] = [_topic("a", "Inactive")]
    failed = snow.run_realm_command(context, _args("check-realm", realm="test"))
    assert _icons(failed["renderBlock"]["text"]) == ["✅", "✅", "❌", "⬜", "⬜"]
    assert "Publish the agent in Dev." in failed["renderBlock"]["text"]
    status = snow.run_realm_command(context, _args("realm-status"))
    assert status["renderBlock"]["text"] == failed["renderBlock"]["text"]
    world["topics"] = [_topic("a")]
    snow.run_realm_command(context, _args("check-realm", realm="test"))
    ready = snow.run_realm_command(
        context,
        _args(
            "record-realm-test",
            realm="test",
            prompt_category=snow.ACTIVE_PROFILE.test_prompt_category,
            result="pass",
            failure_category=None,
        ),
    )
    assert _icons(ready["renderBlock"]["text"]) == ["✅"] * 5
    assert ready["renderBlock"]["text"].endswith(ready["message"])
