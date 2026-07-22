"""Unit tests for the input pipeline vertical slice."""

from __future__ import annotations

import base64
import json
from typing import Any, cast

import httpx
import pytest

from core.logging import Logger
from modules.preprocessing.input_pipeline import build_input_pipeline
from modules.preprocessing.steps.agent_selection_step import AgentSelectionStep
from modules.preprocessing.steps.gather_alm_customer_input_step import (
    GatherALMCustomerInputStep,
)
from modules.preprocessing.steps.gather_input_with_auth_step import (
    GatherInputWithAuthStep,
    _discover_tenant,
)
from modules.preprocessing.steps.retrieve_agent_configuration_step import (
    RetrieveAgentConfigurationStep,
)
from modules.preprocessing.steps.retrieve_customizations_step import RetrieveCustomizationsStep
from modules.transformation.models import MigrationContext


def _make_token(claims: dict[str, str]) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode("ascii")
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8"))
        .rstrip(b"=")
        .decode(
            "ascii",
        )
    )
    return f"{header}.{payload}.signature"


class FakeLogger:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def LogInfo(self, message: str, **_: object) -> None:
        self.messages.append(("INFO", message))

    def LogDebug(self, message: str, **_: object) -> None:
        self.messages.append(("DEBUG", message))

    def LogWarning(self, message: str, **_: object) -> None:
        self.messages.append(("WARNING", message))


class StubMsalTokenProvider:
    token = _make_token({"tid": "tenant-123", "oid": "user-456", "upn": "maker@contoso.com"})
    instances: list[StubMsalTokenProvider] = []

    def __init__(self, config: Any, *args: Any, **kwargs: Any) -> None:
        self.config = config
        self.instances.append(self)

    def get_token(self) -> str:
        return self.token


class FakeDataverseClient:
    def __init__(self, agents: list[dict[str, Any]]) -> None:
        self._agents = agents
        self.calls: list[tuple[str, str | None, str | None]] = []
        self.function_calls: list[tuple[str, dict[str, str]]] = []
        self.function_response: dict[str, Any] = {"value": []}
        self.layers_response: list[dict[str, Any]] = []
        self.botcomponents_response: list[dict[str, Any]] = []
        self.get_calls: list[str] = []
        self.get_response: dict[str, Any] = {}

    def query_all(
        self, entity_set: str, *, select: str | None = None, filter: str | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((entity_set, select, filter))
        if entity_set == "msdyn_componentlayers":
            return list(self.layers_response)
        if entity_set == "botcomponents":
            return list(self.botcomponents_response)
        return list(self._agents)

    def get(self, path: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        self.get_calls.append(path)
        return self.get_response

    def call_function(self, function_name: str, **params: str) -> dict[str, Any]:
        self.function_calls.append((function_name, dict(params)))
        return self.function_response


def test_gather_input_with_auth_step_populates_identity_and_bootstraps_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = cast(Logger, FakeLogger())
    step = GatherInputWithAuthStep(logger, ("READONLY", "WRITEBACK"))
    StubMsalTokenProvider.instances.clear()
    discovered_authority = "https://login.microsoftonline.com/tenant-123"
    monkeypatch.setattr(
        "modules.preprocessing.steps.gather_input_with_auth_step._discover_tenant",
        lambda env_url: "tenant-123",
    )
    monkeypatch.setattr(
        "modules.preprocessing.steps.gather_input_with_auth_step.MsalTokenProvider",
        StubMsalTokenProvider,
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda _: "https://fabrikam.crm.dynamics.com/",
    )

    context = step.execute(MigrationContext())

    assert context.tid == "tenant-123"
    assert context.oid == "user-456"
    assert context.upn == "maker@contoso.com"
    assert context.environment_url == "https://fabrikam.crm.dynamics.com"
    assert context.dataverse_client is not None
    assert context.dataverse_client.environment_url == "https://fabrikam.crm.dynamics.com"
    assert len(StubMsalTokenProvider.instances) == 1
    provider = StubMsalTokenProvider.instances[0]
    assert provider.config.client_id == "51f81489-12ee-4a9e-aaae-a2591f45987d"
    assert provider.config.authority == discovered_authority
    assert provider.config.scopes == ("https://fabrikam.crm.dynamics.com/user_impersonation",)


def test_discover_tenant_reads_tenant_from_www_authenticate_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "modules.preprocessing.steps.gather_input_with_auth_step.httpx.get",
        lambda *args, **kwargs: httpx.Response(
            401,
            headers={
                "WWW-Authenticate": (
                    'Bearer authorization_uri="https://login.microsoftonline.com/'
                    'tenant-789/oauth2/authorize"'
                ),
            },
        ),
    )

    assert _discover_tenant("https://fabrikam.crm.dynamics.com") == "tenant-789"


def test_discover_tenant_defaults_to_organizations_when_header_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "modules.preprocessing.steps.gather_input_with_auth_step.httpx.get",
        lambda *args, **kwargs: httpx.Response(401),
    )

    assert _discover_tenant("https://fabrikam.crm.dynamics.com") == "organizations"


def test_gather_alm_customer_input_step_verifies_matching_preferred_solution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = cast(Logger, FakeLogger())
    step = GatherALMCustomerInputStep(logger, ("READONLY", "WRITEBACK"))
    fake_client = FakeDataverseClient([])
    fake_client.function_response = {"uniquename": "ess_customizations"}
    monkeypatch.setattr("builtins.input", lambda _: "ess_customizations")

    result = step.execute(MigrationContext(dataverse_client=fake_client))

    assert result.preferred_solution == "ess_customizations"
    assert fake_client.function_calls == [("GetPreferredSolution", {})]


def test_gather_alm_customer_input_step_raises_on_preferred_solution_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = cast(Logger, FakeLogger())
    step = GatherALMCustomerInputStep(logger, ("READONLY", "WRITEBACK"))
    fake_client = FakeDataverseClient([])
    fake_client.function_response = {"uniquename": "some_other_solution"}
    monkeypatch.setattr("builtins.input", lambda _: "ess_customizations")

    with pytest.raises(RuntimeError, match="Preferred solution mismatch"):
        step.execute(MigrationContext(dataverse_client=fake_client))


def test_gather_alm_customer_input_step_leaves_solution_empty_when_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = cast(Logger, FakeLogger())
    step = GatherALMCustomerInputStep(logger, ("READONLY", "WRITEBACK"))
    monkeypatch.setattr("builtins.input", lambda _: "   ")

    result = step.execute(MigrationContext())

    assert result.preferred_solution is None


def test_agent_selection_step_queries_agents_and_stores_selected_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = cast(Logger, FakeLogger())
    step = AgentSelectionStep(logger, ("READONLY", "WRITEBACK"))
    fake_client = FakeDataverseClient(
        [
            {"name": "Zebra Agent", "botid": "bot-z", "statecode": 1},
            {"name": "Alpha Agent", "botid": "bot-a", "statecode": 0},
        ],
    )
    context = MigrationContext(dataverse_client=fake_client)
    monkeypatch.setattr("builtins.input", lambda _: "1")

    result = step.execute(context)

    assert fake_client.calls == [
        (
            "bots",
            "name,botid,statecode,schemaname",
            (
                "schemaname eq 'msdyn_copilotforemployeeselfservicehr'"
                " or schemaname eq 'msdyn_copilotforemployeeselfserviceit'"
            ),
        )
    ]
    assert result.selected_agent_id == "bot-a"
    assert result.selected_agent_name == "Alpha Agent"
    assert ("INFO", "1. Alpha Agent [bot-a] state=0") in logger.messages  # type: ignore[attr-defined]
    assert ("INFO", "2. Zebra Agent [bot-z] state=1") in logger.messages  # type: ignore[attr-defined]


def test_retrieve_customizations_step_classifies_customized_and_net_new_layers() -> None:
    logger = cast(Logger, FakeLogger())
    step = RetrieveCustomizationsStep(logger, ("READONLY", "WRITEBACK"))
    fake_client = FakeDataverseClient([])
    fake_client.function_response = {
        "DependencyMetadataCollection": {
            "DependencyMetadataInfoCollection": [
                {"dependentcomponentobjectid": "id-oob"},
                {"dependentcomponentobjectid": "id-netnew"},
                {"dependentcomponentobjectid": "id-customized"},
                {"dependentcomponentobjectid": "id-oob"},  # duplicate ignored
                {"dependentcomponentobjectid": "00000000-0000-0000-0000-000000000000"},  # empty
            ]
        }
    }
    oob_layer = {"msdyn_componentid": "id-oob", "msdyn_overwritetime": "1900-01-01T00:00:00Z"}
    netnew_layer = {
        "msdyn_componentid": "id-netnew",
        "msdyn_overwritetime": "2026-06-11T19:05:31Z",
    }
    base_layer = {
        "msdyn_componentid": "id-customized",
        "msdyn_overwritetime": "1900-01-01T00:00:00Z",
    }
    overlay_layer = {
        "msdyn_componentid": "id-customized",
        "msdyn_overwritetime": "2026-06-11T20:00:00Z",
    }
    fake_client.layers_response = [oob_layer, netnew_layer, base_layer, overlay_layer]
    context = MigrationContext(
        dataverse_client=fake_client,
        selected_agent_schemaname="msdyn_copilotforemployeeselfserviceit",
    )

    result = step.execute(context)

    assert fake_client.function_calls == [
        (
            "RetrieveDependenciesForUninstallWithMetadata",
            {"SolutionUniqueName": "msdyn_CopilotForEmployeeSelfServiceIT"},
        )
    ]
    assert result.ess_solution_unique_name == "msdyn_CopilotForEmployeeSelfServiceIT"
    # All fields fetched (select=None), single chunk of the three unique ids.
    assert fake_client.calls == [
        (
            "msdyn_componentlayers",
            None,
            (
                "msdyn_componentid eq 'id-oob' or msdyn_componentid eq 'id-netnew'"
                " or msdyn_componentid eq 'id-customized'"
            ),
        )
    ]
    # Untouched OOB dropped; net-new kept; customized keeps the recent overlay.
    assert result.customizations == [netnew_layer, overlay_layer]


def test_retrieve_customizations_step_errors_on_unresolvable_vertical() -> None:
    logger = cast(Logger, FakeLogger())
    step = RetrieveCustomizationsStep(logger, ("READONLY", "WRITEBACK"))
    context = MigrationContext(
        dataverse_client=FakeDataverseClient([]),
        selected_agent_schemaname="msdyn_someotheragent",
    )

    with pytest.raises(RuntimeError, match="Could not resolve an ESS base solution"):
        step.execute(context)


def test_retrieve_agent_configuration_step_fetches_bot_record_and_gpt_component() -> None:
    logger = cast(Logger, FakeLogger())
    step = RetrieveAgentConfigurationStep(logger, ("READONLY", "WRITEBACK"))
    fake_client = FakeDataverseClient([])
    fake_client.get_response = {"botid": "bot-1", "template": "default-2.1.0"}
    fake_client.botcomponents_response = [{"schemaname": "sn.gpt.default", "data": "kind: x"}]
    context = MigrationContext(
        dataverse_client=fake_client,
        selected_agent_id="bot-1",
        selected_agent_schemaname="msdyn_copilotforemployeeselfservicehr",
    )

    result = step.execute(context)

    assert fake_client.get_calls == ["bots(bot-1)"]
    assert fake_client.calls == [
        (
            "botcomponents",
            None,
            "schemaname eq 'msdyn_copilotforemployeeselfservicehr.gpt.default'",
        )
    ]
    assert result.agent_bot_record == {"botid": "bot-1", "template": "default-2.1.0"}
    assert result.agent_gpt_component == {"schemaname": "sn.gpt.default", "data": "kind: x"}


def test_retrieve_agent_configuration_step_warns_when_gpt_component_missing() -> None:
    logger = cast(Logger, FakeLogger())
    step = RetrieveAgentConfigurationStep(logger, ("READONLY", "WRITEBACK"))
    fake_client = FakeDataverseClient([])
    fake_client.get_response = {"botid": "bot-1"}
    fake_client.botcomponents_response = []
    context = MigrationContext(
        dataverse_client=fake_client,
        selected_agent_id="bot-1",
        selected_agent_schemaname="msdyn_copilotforemployeeselfservicehr",
    )

    result = step.execute(context)

    assert result.agent_bot_record == {"botid": "bot-1"}
    assert result.agent_gpt_component is None


def test_build_input_pipeline_wires_steps_in_order() -> None:
    pipeline = build_input_pipeline(cast(Logger, FakeLogger()), ("READONLY", "WRITEBACK"))

    assert [step.name() for step in pipeline.steps] == [
        "GatherInputWithAuthStep",
        "AgentSelectionStep",
        "GatherALMCustomerInputStep",
        "RetrieveAgentConfigurationStep",
        "RetrieveCustomizationsStep",
    ]
