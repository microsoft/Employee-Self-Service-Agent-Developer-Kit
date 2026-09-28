from __future__ import annotations

from typing import Any

import pytest

from conftest import layer
from essmig.discovery import DiscoveryResult, discover

HR_SOLUTION = "msdyn_CopilotForEmployeeSelfServiceHR"
HR_PREFIX = "msdyn_copilotforemployeeselfservicehr"


class FakeClient:
    """A Dataverse stand-in that answers the three queries discovery makes."""

    def __init__(
        self,
        layers: dict[str, list[dict[str, Any]]],
        *,
        members: list[str] | None = None,
        dependents: list[str] | None = None,
        owned: list[str] | None = None,
        gpt: dict[str, Any] | None = None,
    ) -> None:
        self._layers = layers
        self._members = members or []
        # Which component ids the uninstall-dependency function reports, and which
        # the botcomponent table reports. Both default to every known component, so
        # existing tests see the pre-fix behaviour (the union collapses to one set).
        self._dependents = list(layers) if dependents is None else dependents
        self._owned = list(layers) if owned is None else owned
        # The gpt.default botcomponent row that carries the agent's name/description.
        self._gpt = gpt
        self.layer_queries: list[str] = []

    def query_all(
        self, entity_set: str, *, select: str | None = None, filter: str | None = None
    ) -> list[dict[str, Any]]:
        del select
        if entity_set == "solutions":
            return [{"solutionid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}]
        if entity_set == "botcomponents":
            # The agent-metadata lookup asks for one component by exact schema name;
            # the owned sweep asks for the whole family with startswith(...).
            if filter is not None and filter.startswith("schemaname eq"):
                return [self._gpt] if self._gpt is not None else []
            return [{"botcomponentid": component_id} for component_id in self._owned]
        if entity_set == "msdyn_componentlayers":
            assert filter is not None
            self.layer_queries.append(filter)
            component_id = filter.split("'")[1]
            return self._layers.get(component_id, [])
        if entity_set == "solutioncomponents":
            return [{"objectid": member} for member in self._members]
        raise AssertionError(f"unexpected entity set {entity_set}")

    def call_function(self, function_name: str, **params: str) -> dict[str, Any]:
        del function_name, params
        return {
            "DependencyMetadataCollection": {
                "DependencyMetadataInfoCollection": [
                    {
                        "dependentcomponentobjectid": component_id,
                        "dependentcomponententitylogicalname": "botcomponent",
                    }
                    for component_id in self._dependents
                ]
                + [
                    # A placeholder and a malformed entry: both must be ignored.
                    {
                        "dependentcomponentobjectid": "00000000-0000-0000-0000-000000000000",
                        "dependentcomponententitylogicalname": "botcomponent",
                    },
                    {"dependentcomponentobjectid": "no-entity-name"},
                ]
            }
        }


def topic_layer(solution: str, suffix: str, **overrides: Any) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "schemaname": f"{HR_PREFIX}.{suffix}",
        "name": suffix,
        "componenttype": {"Value": 9},
        "data": "kind: AdaptiveDialog\n",
    }
    attributes.update(overrides)
    return layer(solution, **attributes)


def run(layers: dict[str, list[dict[str, Any]]], **kwargs: Any) -> DiscoveryResult:
    return discover(FakeClient(layers, **kwargs), "hr")  # type: ignore[arg-type]


def test_an_untouched_oob_component_is_not_a_customization() -> None:
    result = run({"c1": [topic_layer(HR_SOLUTION, "topic.Foo")]})
    assert result.components == {}


def test_an_oob_component_with_an_unmanaged_overlay_is_a_customization() -> None:
    result = run(
        {"c1": [topic_layer(HR_SOLUTION, "topic.Foo"), topic_layer("Active", "topic.Foo")]}
    )
    assert list(result.components) == ["c1"]
    assert result.components["c1"].is_net_new is False


def test_a_lone_layer_outside_the_oob_solutions_is_a_net_new_component() -> None:
    result = run({"c1": [topic_layer("MyDevSolution", "topic.Mine")]})
    assert result.components["c1"].is_net_new is True


def test_the_topmost_layer_supplies_the_effective_attribute_values() -> None:
    result = run(
        {
            "c1": [
                topic_layer(HR_SOLUTION, "topic.Foo", data="kind: AdaptiveDialog\n# base\n"),
                topic_layer("Active", "topic.Foo", data="kind: AdaptiveDialog\n# mine\n"),
            ]
        }
    )
    assert "# mine" in (result.components["c1"].data or "")


def test_the_customer_overlay_wins_even_when_returned_before_the_managed_base() -> None:
    # msdyn_componentlayers row order is undocumented; the customer's unmanaged
    # "Active" overlay must win over the managed OOB base regardless of order.
    result = run(
        {
            "c1": [
                topic_layer("Active", "topic.Foo", data="kind: AdaptiveDialog\n# mine\n"),
                topic_layer(HR_SOLUTION, "topic.Foo", data="kind: AdaptiveDialog\n# base\n"),
            ]
        }
    )
    assert "# mine" in (result.components["c1"].data or "")


def test_a_component_owned_by_another_agent_is_skipped_with_a_reason() -> None:
    other = layer(
        "Active",
        schemaname="msdyn_someotheragent.topic.Foo",
        name="Foo",
        componenttype={"Value": 9},
    )
    result = run({"c1": [other]})
    assert result.components == {}
    assert "owned by another agent" in result.skipped[0]["reason"]


def test_a_non_carriable_component_type_is_detected_not_skipped() -> None:
    # Types the package cannot carry (e.g. Test Case / evaluations, type 19) are no
    # longer dropped at discovery — they are kept so the report can account for them.
    # Whether they migrate or must be re-created by hand is decided downstream.
    result = run({"c1": [topic_layer("Active", "testcase.X", componenttype={"Value": 19})]})
    assert list(result.components) == ["c1"]
    assert result.components["c1"].component_type == 19
    assert result.skipped == []


def test_each_component_gets_its_own_layer_query_paired_with_its_entity_name() -> None:
    # The virtual table returns almost nothing if ids are OR-ed into one query, and
    # nothing at all without msdyn_solutioncomponentname.
    client = FakeClient(
        {
            "c1": [topic_layer("Active", "topic.A")],
            "c2": [topic_layer("Active", "topic.B")],
        }
    )
    discover(client, "hr")  # type: ignore[arg-type]
    assert len(client.layer_queries) == 2
    assert all("msdyn_solutioncomponentname eq 'botcomponent'" in q for q in client.layer_queries)
    assert not any(" or " in q for q in client.layer_queries)


def test_the_preferred_solution_scopes_the_migration() -> None:
    layers = {
        "c1": [topic_layer("MyDevSolution", "topic.In")],
        "c2": [topic_layer("OtherSolution", "topic.Out")],
    }
    result = discover(
        FakeClient(layers, members=["{C1}"]),  # type: ignore[arg-type]
        "hr",
        preferred_solution="MyDevSolution",
    )
    assert list(result.components) == ["c1"]
    assert "preferred solution" in result.skipped[0]["reason"]


def test_an_in_place_edit_is_found_even_when_not_an_uninstall_dependency() -> None:
    # Editing the agent instructions adds an "Active" layer to the out-of-box
    # gpt.default (type 15) but creates no uninstall dependency. The botcomponent
    # table must still surface it so the edit reaches classification.
    layers = {
        "c1": [
            topic_layer(HR_SOLUTION, "gpt.default", componenttype={"Value": 15}),
            topic_layer("Active", "gpt.default", componenttype={"Value": 15}),
        ]
    }
    result = discover(
        FakeClient(layers, dependents=[], owned=["c1"]),  # type: ignore[arg-type]
        "hr",
    )
    assert list(result.components) == ["c1"]
    assert result.components["c1"].suffix == "gpt.default"


def test_a_component_in_both_sources_is_queried_only_once() -> None:
    layers = {"c1": [topic_layer("Active", "topic.A")]}
    client = FakeClient(layers, dependents=["c1"], owned=["c1"])
    discover(client, "hr")  # type: ignore[arg-type]
    assert len(client.layer_queries) == 1


def test_an_unknown_vertical_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown vertical"):
        discover(FakeClient({}), "finance")  # type: ignore[arg-type]


class SolutionsClient:
    """A Dataverse stand-in that only knows which base solutions are installed."""

    def __init__(self, installed_unique_names: set[str]) -> None:
        self._installed = installed_unique_names

    def query_all(
        self, entity_set: str, *, select: str | None = None, filter: str | None = None
    ) -> list[dict[str, Any]]:
        del select
        assert entity_set == "solutions"
        assert filter is not None
        unique_name = filter.split("'")[1]
        if unique_name in self._installed:
            return [{"solutionid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}]
        return []


def test_installed_targets_reports_every_ess_agent_present_in_canonical_order() -> None:
    from essmig.discovery import installed_targets

    client = SolutionsClient(
        {
            "msdyn_CopilotForEmployeeSelfServiceIT",
            "msdyn_CopilotForEmployeeSelfServiceCore",
            "msdyn_CopilotForEmployeeSelfServiceHR",
        }
    )
    assert installed_targets(client) == ["core", "hr", "it"]  # type: ignore[arg-type]


def test_installed_targets_returns_only_the_agents_that_are_installed() -> None:
    from essmig.discovery import installed_targets

    client = SolutionsClient({"msdyn_CopilotForEmployeeSelfServiceHR"})
    assert installed_targets(client) == ["hr"]  # type: ignore[arg-type]


def test_installed_targets_is_empty_when_no_ess_agent_is_installed() -> None:
    from essmig.discovery import installed_targets

    assert installed_targets(SolutionsClient(set())) == []  # type: ignore[arg-type]


# --- agent name & description ------------------------------------------------

_GPT_ID = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
_AGENT_SCHEMA = "msdyn_copilotforemployeeselfservicehr.gpt.default"


def _gpt_row(name: str, description: str) -> dict[str, Any]:
    return {
        "botcomponentid": _GPT_ID,
        "name": name,
        "description": description,
        "componenttype": {"Value": 15},
        "schemaname": _AGENT_SCHEMA,
    }


def test_the_agents_name_and_description_are_read_with_their_baseline() -> None:
    baseline_layer = layer(
        HR_SOLUTION,
        name="ESS HR (Preview)",
        description="Shipped ESS description.",
        schemaname=_AGENT_SCHEMA,
    )
    client = FakeClient(
        {_GPT_ID: [baseline_layer]},
        gpt=_gpt_row("Contoso People Helper", "Our tailored description."),
    )
    result = discover(client, "hr")  # type: ignore[arg-type]

    assert result.agent is not None
    assert result.agent.name == "Contoso People Helper"
    assert result.agent.baseline_name == "ESS HR (Preview)"
    assert result.agent.name_changed is True
    assert result.agent.description_changed is True


def test_an_agent_with_no_gpt_component_yields_no_metadata() -> None:
    result = run({})
    assert result.agent is None
