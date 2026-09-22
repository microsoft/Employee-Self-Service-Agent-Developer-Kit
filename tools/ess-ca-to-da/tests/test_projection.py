from __future__ import annotations

from typing import Any

import pytest

from conftest import ca_component
from essmig.projection import (
    ProjectionError,
    _normalize_copilot_yaml,
    as_new_component,
    parse_ca_data,
    project,
    rewrite_prefixes,
)

TOPIC = """kind: AdaptiveDialog
beginDialog:
  kind: OnRedirect
  id: main
  actions:
    - kind: BeginDialog
      id: a1
      dialog: msdyn_copilotforemployeeselfservicecore.topic.Shared
"""


def test_topic_projects_into_a_dialog_component() -> None:
    projected = project(ca_component("topic.Foo", TOPIC), "hr")
    assert projected["kind"] == "DialogComponent"
    assert projected["schemaName"] == "gptagent_copilotforemployeeselfservicehr.topic.Foo"
    assert "kind" not in projected["dialog"]
    assert projected["dialog"]["beginDialog"]["kind"] == "OnRedirect"


def test_cross_agent_references_are_repointed_at_their_own_da_agent() -> None:
    # An HR topic that references a Core (hub) topic must repoint at the Core DA
    # agent, not be folded into HR — Core is its own first-class agent.
    projected = project(ca_component("topic.Foo", TOPIC), "hr")
    action = projected["dialog"]["beginDialog"]["actions"][0]
    assert action["dialog"] == "gptagent_copilotforemployeeselfservicecore.topic.Shared"


def test_each_agent_prefix_maps_to_its_own_da_agent_without_mangling() -> None:
    # The three agent prefixes share a long common stem; longest-first ordering must
    # rewrite each to its own DA agent rather than mangling one into another.
    text = (
        "msdyn_copilotforemployeeselfservicehr.topic.A "
        "msdyn_copilotforemployeeselfservicecore.topic.B "
        "msdyn_copilotforemployeeselfserviceit.topic.C"
    )
    assert rewrite_prefixes(text, "hr") == (
        "gptagent_copilotforemployeeselfservicehr.topic.A "
        "gptagent_copilotforemployeeselfservicecore.topic.B "
        "gptagent_copilotforemployeeselfserviceit.topic.C"
    )


def test_a_variable_projects_into_a_global_variable_component() -> None:
    data = "kind: Variable\nname: MyVar\nscope: User\n"
    projected = project(ca_component("component.MyVar", data, component_type=12), "hr")
    assert projected["kind"] == "GlobalVariableComponent"
    assert projected["variable"] == {"name": "MyVar", "scope": "User"}


def test_gpt_metadata_projects_into_a_gpt_component() -> None:
    data = "kind: GptComponentMetadata\ninstructions: be helpful\n"
    projected = project(ca_component("gpt.default", data, component_type=15), "hr")
    assert projected["kind"] == "GptComponent"
    assert projected["metadata"]["instructions"] == "be helpful"


def test_a_kind_that_contradicts_the_component_type_is_refused() -> None:
    with pytest.raises(ProjectionError, match="declares kind"):
        project(ca_component("topic.Foo", "kind: Variable\nname: X\n"), "hr")


CONNECTOR_TOPIC = """kind: AdaptiveDialog
beginDialog:
  kind: OnRedirect
  id: main
  actions:
    - kind: InvokeConnectorAction
      id: act1
      inputs:
        body:
          @odata.type: String
          value: =Topic.Foo
"""


def test_connector_data_with_at_odata_keys_is_parsed_not_crashed() -> None:
    # Copilot Studio emits '@odata.type' unquoted, which strict YAML rejects. It must
    # be quoted and parsed, not blow up the run.
    projected = project(ca_component("topic.Connector", CONNECTOR_TOPIC), "hr")
    body = projected["dialog"]["beginDialog"]["actions"][0]["inputs"]["body"]
    assert body["@odata.type"] == "String"
    assert body["value"] == "=Topic.Foo"


def test_reserved_indicator_values_and_keys_are_quoted() -> None:
    # A value that *starts* with a reserved indicator ('@' here) is quoted and read
    # back as the literal string, key untouched.
    tree = parse_ca_data("kind: X\nfield:\n  type: @EdmType\n", "hr")
    assert tree["field"]["type"] == "@EdmType"


def test_prose_in_a_block_scalar_is_never_rewritten() -> None:
    # An '@' inside instruction prose must survive untouched — only structural
    # scalars that *start* with a reserved indicator are quoted.
    text = "kind: GptComponentMetadata\ninstructions: |\n  Ping @oncall and note x: @y\n"
    quoted = _normalize_copilot_yaml(text)
    assert "Ping @oncall and note x: @y" in quoted
    tree = parse_ca_data(text, "hr")
    assert tree["instructions"].strip() == "Ping @oncall and note x: @y"


def test_a_block_mapping_entry_missing_the_key_space_is_repaired() -> None:
    # Copilot Studio emits 'connectionReference:esshr_Foo' with no space; a strict
    # reader needs 'connectionReference: esshr_Foo'.
    tree = parse_ca_data(
        "kind: X\naction:\n  connectionReference:esshr_HRSystemsConnectionConnRef\n", "hr"
    )
    assert tree["action"]["connectionReference"] == "esshr_HRSystemsConnectionConnRef"


def test_missing_key_space_repair_leaves_urls_and_spaced_values_alone() -> None:
    tree = parse_ca_data("kind: X\nendpoint: https://api.example.com/v1\n", "hr")
    assert tree["endpoint"] == "https://api.example.com/v1"


def test_unparseable_data_is_a_projection_error_not_a_raw_yaml_error() -> None:
    # A genuinely broken document is reported as one failed component, never a crash.
    with pytest.raises(ProjectionError, match="could not parse"):
        parse_ca_data("kind: X\nfoo: [unterminated\n", "hr")


def test_a_knowledge_source_projects_into_a_knowledge_source_component() -> None:
    data = (
        "kind: KnowledgeSourceConfiguration\n"
        "source:\n"
        "  kind: SharePointSearchSource\n"
        "  site: https://contoso.sharepoint.com/sites/HR\n"
    )
    projected = project(ca_component("knowledge.X", data, component_type=16), "hr")
    assert projected["kind"] == "KnowledgeSourceComponent"
    assert projected["configuration"]["source"]["kind"] == "SharePointSearchSource"


def test_a_new_knowledge_source_matches_the_export_shape() -> None:
    # A knowledge source is not a dialog: the import validator rejects the generic
    # net-new shape (state/status/shareContext, topic.* schema). It must be
    # namespaced under knowledge.<Name> and omit those lifecycle fields, matching a
    # real DA export, or it fails to bind.
    data = (
        "kind: KnowledgeSourceConfiguration\n"
        "source:\n"
        "  kind: SharePointSearchSource\n"
        "  site: https://contoso.sharepoint.com/sites/HR\n"
    )
    entry = as_new_component(
        ca_component("topic.Empty HR Web", data, component_type=16, name="Empty HR Web"),
        "hr",
    )
    assert entry["kind"] == "KnowledgeSourceComponent"
    assert entry["schemaName"].endswith(".knowledge.EmptyHRWeb")
    assert entry["displayName"] == "Empty HR Web"
    assert "SharePoint" in entry["description"]
    assert entry["configuration"]["source"]["cascadeShare"] is False
    for absent in ("state", "status", "shareContext"):
        assert absent not in entry


def test_component_types_with_no_da_equivalent_are_named_in_the_error() -> None:
    with pytest.raises(ProjectionError, match="No Declarative Agent shape"):
        project(ca_component("misc.X", "kind: X\n", component_type=99), "hr")


def test_a_new_component_is_marked_customer_owned() -> None:
    entry = as_new_component(ca_component("topic.Mine", TOPIC, name="Mine"), "hr")
    assert entry["managedProperties"] == {"isManaged": False, "isCustomizable": True}
    assert entry["displayName"] == "Mine"
    assert entry["state"] == entry["status"] == "Active"


def test_a_new_component_gets_a_unique_bindable_id() -> None:
    # A zero id fails the import binding ("could not be bound into a valid Dev
    # agent"); the ESS template gives every component a real GUID, so must we.
    first = as_new_component(ca_component("topic.Mine", TOPIC, name="Mine"), "hr")
    second = as_new_component(ca_component("topic.Mine", TOPIC, name="Mine"), "hr")
    assert first["id"] != "00000000-0000-0000-0000-000000000000"
    assert first["id"] != second["id"]
    assert first["parentBotId"] == "00000000-0000-0000-0000-000000000000"


def test_an_inactive_ca_topic_stays_inactive() -> None:
    entry = as_new_component(ca_component("topic.Mine", TOPIC, statecode=1), "hr")
    assert entry["state"] == "Inactive"


def test_a_variable_component_carries_no_display_name() -> None:
    data = "kind: Variable\nname: MyVar\nscope: User\n"
    entry: dict[str, Any] = as_new_component(
        ca_component("component.MyVar", data, component_type=12), "hr"
    )
    assert "displayName" not in entry
