"""Unit tests for the input pipeline vertical slice."""

from __future__ import annotations

import base64
import json
import re
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
from modules.preprocessing.steps.retrieve_customizations_step import (
    RetrieveCustomizationsStep,
    _select_customizations,
)
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
        # Optional per-component layer responses, keyed by msdyn_componentid, so a
        # per-id query returns only that component's layers (matches live shape).
        self.layers_by_id: dict[str, list[dict[str, Any]]] = {}
        self.botcomponents_response: list[dict[str, Any]] = []
        self.solutions_response: list[dict[str, Any]] = [
            {"solutionid": "11111111-1111-1111-1111-111111111111"}
        ]
        self.get_calls: list[str] = []
        self.get_response: dict[str, Any] = {}

    def query_all(
        self, entity_set: str, *, select: str | None = None, filter: str | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((entity_set, select, filter))
        if entity_set == "msdyn_componentlayers":
            if self.layers_by_id:
                match = re.search(r"msdyn_componentid eq '([^']+)'", filter or "")
                component_id = match.group(1) if match else ""
                return list(self.layers_by_id.get(component_id, []))
            return list(self.layers_response)
        if entity_set == "botcomponents":
            return list(self.botcomponents_response)
        if entity_set == "solutions":
            return list(self.solutions_response)
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


def _component_json(
    component_type: int,
    schemaname: str = "msdyn_copilotforemployeeselfservicehr.topic.Foo",
    name: str | None = None,
    data: str | None = None,
) -> str:
    """Build a minimal msdyn_componentjson string carrying botcomponent attributes."""
    attributes: list[dict[str, Any]] = [
        {"Key": "componenttype", "Value": {"Value": component_type}},
        {"Key": "schemaname", "Value": schemaname},
    ]
    if name is not None:
        attributes.append({"Key": "name", "Value": name})
    if data is not None:
        attributes.append({"Key": "data", "Value": data})
    return json.dumps({"Attributes": attributes})


def test_retrieve_customizations_step_classifies_customized_and_net_new_layers() -> None:
    logger = cast(Logger, FakeLogger())
    step = RetrieveCustomizationsStep(logger, ("READONLY", "WRITEBACK"))
    fake_client = FakeDataverseClient([])
    fake_client.function_response = {
        "DependencyMetadataCollection": {
            "DependencyMetadataInfoCollection": [
                {
                    "dependentcomponentobjectid": "id-oob",
                    "dependentcomponententitylogicalname": "botcomponent",
                },
                {
                    "dependentcomponentobjectid": "id-netnew",
                    "dependentcomponententitylogicalname": "botcomponent",
                },
                {
                    "dependentcomponentobjectid": "id-customized",
                    "dependentcomponententitylogicalname": "botcomponent",
                },
                {
                    "dependentcomponentobjectid": "id-oob",
                    "dependentcomponententitylogicalname": "botcomponent",
                },  # duplicate ignored
                {
                    "dependentcomponentobjectid": "00000000-0000-0000-0000-000000000000",
                    "dependentcomponententitylogicalname": "botcomponent",
                },  # empty guid
            ]
        }
    }
    oob_layer = {
        "msdyn_componentid": "id-oob",
        "msdyn_solutionname": "msdyn_CopilotForEmployeeSelfServiceIT",  # managed base only
        "msdyn_overwritetime": "1900-01-01T00:00:00Z",
        "msdyn_componentjson": _component_json(9),
    }
    netnew_layer = {
        "msdyn_componentid": "id-netnew",
        "msdyn_solutionname": "Active",  # unmanaged net-new (overwritetime still ~1900!)
        "msdyn_overwritetime": "1900-01-01T00:00:00Z",
        "msdyn_componentjson": _component_json(9),
    }
    base_layer = {
        "msdyn_componentid": "id-customized",
        "msdyn_solutionname": "msdyn_CopilotForEmployeeSelfServiceIT",  # managed base
        "msdyn_overwritetime": "1900-01-01T00:00:00Z",
        "msdyn_componentjson": _component_json(9),
    }
    overlay_layer = {
        "msdyn_componentid": "id-customized",
        "msdyn_solutionname": "Active",  # unmanaged overlay
        "msdyn_overwritetime": "1900-01-01T00:00:00Z",
        "msdyn_componentjson": _component_json(9),
    }
    fake_client.layers_by_id = {
        "id-oob": [oob_layer],  # single ~1900 sentinel -> untouched OOB
        "id-netnew": [netnew_layer],  # single non-sentinel -> net-new
        "id-customized": [base_layer, overlay_layer],  # base + overlay -> customized
    }
    context = MigrationContext(
        dataverse_client=fake_client,
        selected_agent_schemaname="msdyn_copilotforemployeeselfserviceit",
    )

    result = step.execute(context)

    assert fake_client.function_calls == [
        (
            "RetrieveDependenciesForUninstallWithMetadata",
            {"SolutionId": "11111111-1111-1111-1111-111111111111"},
        )
    ]
    assert result.ess_solution_unique_name == "msdyn_CopilotForEmployeeSelfServiceIT"
    # solutionid resolved from the unique name first, then one layer query per
    # unique component id (all fields, select=None) — the virtual table resolves a
    # single id at a time — each carrying its own msdyn_solutioncomponentname.
    assert fake_client.calls == [
        (
            "solutions",
            "solutionid",
            "uniquename eq 'msdyn_CopilotForEmployeeSelfServiceIT'",
        ),
        (
            "msdyn_componentlayers",
            None,
            "msdyn_componentid eq 'id-oob' and msdyn_solutioncomponentname eq 'botcomponent'",
        ),
        (
            "msdyn_componentlayers",
            None,
            "msdyn_componentid eq 'id-netnew' and msdyn_solutioncomponentname eq 'botcomponent'",
        ),
        (
            "msdyn_componentlayers",
            None,
            "msdyn_componentid eq 'id-customized'"
            " and msdyn_solutioncomponentname eq 'botcomponent'",
        ),
    ]
    # component_layers keeps every component's raw layer set, keyed by id.
    assert result.component_layers == {
        "id-oob": [oob_layer],
        "id-netnew": [netnew_layer],
        "id-customized": [base_layer, overlay_layer],
    }
    # Untouched OOB dropped; net-new kept; customized kept (base + overlay), each
    # hydrated into a CustomizationComponent (type 9 / "Topic (V2)") keyed by id.
    assert set(result.customizations) == {"id-netnew", "id-customized"}
    netnew = result.customizations["id-netnew"]
    assert netnew.component_id == "id-netnew"
    assert netnew.component_type == 9
    assert netnew.component_type_label == "Topic (V2)"
    assert netnew.schemaname == "msdyn_copilotforemployeeselfservicehr.topic.Foo"
    assert netnew.layers == [netnew_layer]
    assert result.customizations["id-customized"].layers == [base_layer, overlay_layer]
    # raw_dependencies filtered to the customized components' metadata infos.
    assert result.customized_dependencies == [
        {
            "dependentcomponentobjectid": "id-netnew",
            "dependentcomponententitylogicalname": "botcomponent",
        },
        {
            "dependentcomponentobjectid": "id-customized",
            "dependentcomponententitylogicalname": "botcomponent",
        },
    ]


def test_select_customizations_uses_oob_solution_membership() -> None:
    def layer(solution_name: str) -> dict[str, Any]:
        return {"msdyn_solutionname": solution_name, "msdyn_componentjson": _component_json(9)}

    layers_by_component = {
        # Lone layer in an OOB solution (base or extension pack) -> untouched OOB.
        "base-oob": [layer("msdyn_CopilotForEmployeeSelfServiceHR")],
        "ext-oob": [layer("msdyn_EssHRServiceNowHRSD")],
        # Lone layer in a non-OOB solution -> customer change (net-new).
        "netnew-active": [layer("Active")],
        "netnew-custom-solution": [layer("acme_MyDevSolution")],
        # More than one layer -> customized regardless of the solutions involved.
        "multi-layer": [
            layer("msdyn_CopilotForEmployeeSelfServiceHR"),
            layer("Active"),
        ],
    }

    result = _select_customizations(layers_by_component)

    assert set(result) == {"netnew-active", "netnew-custom-solution", "multi-layer"}


def test_select_customizations_filters_to_allowed_component_types() -> None:
    def layer(component_type: int) -> dict[str, Any]:
        return {
            "msdyn_solutionname": "Active",
            "msdyn_componentjson": _component_json(component_type),
        }

    layers_by_component = {
        "topic-v2": [layer(9)],  # allow-listed -> kept
        "test-case": [layer(19)],  # not allow-listed -> dropped
        "knowledge-source": [layer(16)],  # not allow-listed -> dropped
        "untyped": [{"msdyn_solutionname": "Active"}],  # no componentjson -> dropped
    }

    result = _select_customizations(layers_by_component)

    assert set(result) == {"topic-v2"}


def test_select_customizations_filters_to_ess_agent_schemanames() -> None:
    def layer(schemaname: str) -> dict[str, Any]:
        return {
            "msdyn_solutionname": "Active",
            "msdyn_componentjson": _component_json(9, schemaname),
        }

    layers_by_component = {
        "hr-topic": [layer("msdyn_copilotforemployeeselfservicehr.topic.Foo")],
        "it-topic": [layer("msdyn_copilotforemployeeselfserviceit.topic.Bar")],
        # Owned by the shared "...core" agent, not HR/IT -> dropped.
        "core-topic": [layer("msdyn_copilotforemployeeselfservicecore.action.X")],
        # Missing schemaname -> dropped.
        "no-schema": [layer("")],
    }

    result = _select_customizations(layers_by_component)

    assert set(result) == {"hr-topic", "it-topic"}


def test_select_customizations_hydrates_top_level_fields() -> None:
    layers = [
        {
            "msdyn_componentid": "topic-1",
            "msdyn_solutionname": "Active",
            "msdyn_componentjson": _component_json(
                9,
                schemaname="msdyn_copilotforemployeeselfservicehr.topic.Telescope",
                name="telescope buy",
                data="kind: AdaptiveDialog\nmodelDescription: buy a telescope",
            ),
        }
    ]

    result = _select_customizations({"topic-1": layers})

    component = result["topic-1"]
    assert component.component_id == "topic-1"
    assert component.schemaname == "msdyn_copilotforemployeeselfservicehr.topic.Telescope"
    assert component.name == "telescope buy"
    assert component.component_type == 9
    assert component.component_type_label == "Topic (V2)"
    assert component.data == "kind: AdaptiveDialog\nmodelDescription: buy a telescope"
    assert component.layers == layers


def test_retrieve_customizations_step_uses_entity_logical_name_per_component() -> None:
    logger = cast(Logger, FakeLogger())
    step = RetrieveCustomizationsStep(logger, ("READONLY", "WRITEBACK"))
    fake_client = FakeDataverseClient([])
    fake_client.function_response = {
        "DependencyMetadataCollection": {
            "DependencyMetadataInfoCollection": [
                {
                    "dependentcomponentobjectid": "topic-1",
                    "dependentcomponententitylogicalname": "botcomponent",
                },
                {
                    "dependentcomponentobjectid": "bot-1",
                    "dependentcomponententitylogicalname": "bot",
                },
            ]
        }
    }
    context = MigrationContext(
        dataverse_client=fake_client,
        selected_agent_schemaname="msdyn_copilotforemployeeselfservicehr",
    )

    step.execute(context)

    # One single-id layer query per component, each carrying its own
    # solutioncomponentname taken from dependentcomponententitylogicalname.
    assert fake_client.calls == [
        ("solutions", "solutionid", "uniquename eq 'msdyn_CopilotForEmployeeSelfServiceHR'"),
        (
            "msdyn_componentlayers",
            None,
            "msdyn_componentid eq 'topic-1' and msdyn_solutioncomponentname eq 'botcomponent'",
        ),
        (
            "msdyn_componentlayers",
            None,
            "msdyn_componentid eq 'bot-1' and msdyn_solutioncomponentname eq 'bot'",
        ),
    ]


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
