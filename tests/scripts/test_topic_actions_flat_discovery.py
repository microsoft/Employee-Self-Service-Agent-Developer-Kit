# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure flat-catalog logic and read orchestration; no invented network responses."""

from dataclasses import asdict, replace
import json
from types import SimpleNamespace

import pytest
import requests

from agentbuilder import AgentBuilderHTTPError, derive_environment_host
from topic_actions_discovery import DiscoveryError, DiscoveryTarget, discover_topic_sets
from topic_actions_flat_discovery import (
    FlatCatalog,
    FlatMember,
    FlatSet,
    InventoryTopic,
    NativeInventory,
    compare_flat_catalog,
    discover_flat_topic_sets,
    inventory_from_response,
    load_flat_catalog,
)


TARGET = DiscoveryTarget(
    "00000000-0000-0000-0000-000000001111",
    "00000000-0000-0000-0000-000000002222",
    "00000000-0000-0000-0000-000000003333",
)
FIRST = "00000000-0000-0000-0000-000000004444"
SECOND = "00000000-0000-0000-0000-000000005555"
OTHER = "00000000-0000-0000-0000-000000006666"


@pytest.fixture
def catalog():
    return FlatCatalog((
        FlatSet("isv-a", "exact.hr", (
            FlatMember("exact.hr.topic.GetReferenceData"),
            FlatMember("exact.hr.topic.Helper"),
        ), "source-r1", "/inventory/hr", "1"),
        FlatSet("isv-b", "exact.hr", (
            FlatMember("exact.hr.topic.Helper"),
        ), "source-r1", "/inventory/hr", "1"),
        FlatSet("isv-c", "exact.it", (
            FlatMember("exact.it.topic.GetTickets"),
        ), "source-r1", "/inventory/it", "1"),
    ), "catalog-r1")


@pytest.fixture
def inventory():
    return NativeInventory(TARGET, "exact.hr", (
        InventoryTopic(FIRST, "exact.hr.topic.GetReferenceData", "On"),
        InventoryTopic(SECOND, "exact.hr.topic.Helper", "Off"),
    ), "read-r1")


def catalog_document():
    return {
        "format": "adk-local-repository-topic-set-draft",
        "formatVersion": 1,
        "source": {"commit": "source-r1"},
        "sets": [{
            "key": "future:any-key",
            "agentSchemaName": "exact.hr",
            "sourcePath": "/inventory/hr",
            "templatePackageVersion": "1",
            "membershipCompleteWithinReviewedTemplate": True,
            "members": [{
                "schemaName": "exact.hr.topic.GetReferenceData",
                "sourceComponentId": "not-an-installed-id",
                "displayName": "A misleading display name",
                "observedState": "On",
                "required": None,
            }],
        }],
    }


def load_document(tmp_path, document):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return load_flat_catalog(path)


def test_load_versioned_catalog_ignores_template_ids_names_and_states(tmp_path):
    result = load_document(tmp_path, catalog_document())
    assert result.sets[0].key == "future:any-key"
    assert result.sets[0].members == (FlatMember("exact.hr.topic.GetReferenceData"),)
    assert result.sets[0].source_revision == "source-r1"
    assert "not-an-installed-id" not in repr(result)
    changed = catalog_document()
    changed["sets"][0]["members"].append({"schemaName": "another.exact.schema"})
    assert load_document(tmp_path, changed).revision != result.revision


@pytest.mark.parametrize(("mutation", "reason"), [
    (lambda d: d.update(formatVersion=3), "unsupported_catalog_format"),
    (lambda d: d.update(formatVersion=True), "unsupported_catalog_format"),
    (lambda d: d["sets"].append(d["sets"][0]), "ambiguous_set"),
    (lambda d: d["sets"][0]["members"].append(d["sets"][0]["members"][0]), "ambiguous_membership"),
    (lambda d: d["sets"][0].update(members=[]), "empty_membership"),
    (lambda d: d["sets"][0].update(membershipCompleteWithinReviewedTemplate=False), "incomplete_catalog_membership"),
    (lambda d: d["sets"][0]["members"][0].update(required="false"), "invalid_evidence"),
    (lambda d: d["sets"][0]["members"][0].update(schemaName="unsafe\n"), "invalid_identity"),
])
def test_catalog_errors_fail_closed_without_source_contents(tmp_path, mutation, reason):
    document = catalog_document()
    mutation(document)
    with pytest.raises(DiscoveryError) as error:
        load_document(tmp_path, document)
    assert error.value.reason == reason
    assert "misleading" not in str(error.value)


def test_duplicate_json_keys_and_missing_catalog_do_not_fallback(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text('{"formatVersion":1,"formatVersion":2}', encoding="utf-8")
    with pytest.raises(DiscoveryError, match="No changes attempted") as error:
        load_flat_catalog(path)
    assert error.value.reason == "ambiguous_catalog"
    with pytest.raises(DiscoveryError) as error:
        load_flat_catalog(tmp_path / "missing")
    assert error.value.reason == "catalog_unreadable"


def variant_document():
    original = catalog_document()["sets"][0]
    return {
        "format": "adk-local-repository-topic-set-draft",
        "formatVersion": 2,
        "source": {"commit": "source-r1"},
        "sets": [
            {"key": "workday-da-hr", "sourceVariants": [
                original,
                {
                    **original, "agentSchemaName": "package.hr",
                    "sourcePath": "/package/hr",
                    "members": [{"schemaName": "package.hr.topic.GetReferenceData"}],
                },
            ]},
            {"key": "workday-da-it", "sourceVariants": [{
                **original, "agentSchemaName": "package.it",
                "sourcePath": "/package/it",
                "members": [{"schemaName": "package.it.topic.GetReferenceData"}],
            }]},
        ],
    }


@pytest.mark.parametrize(("schema", "hr_status", "it_status", "selected"), [
    ("exact.hr", "present", "not_applicable", "workday-da-hr"),
    ("package.hr", "present", "not_applicable", "workday-da-hr"),
    ("package.it", "not_applicable", "present", "workday-da-it"),
])
def test_workday_verticals_and_source_variants_never_alias_or_union(
    tmp_path, schema, hr_status, it_status, selected,
):
    catalog = load_document(tmp_path, variant_document())
    inventory = NativeInventory(TARGET, schema, (
        InventoryTopic(FIRST, f"{schema}.topic.GetReferenceData", "On"),
        InventoryTopic(SECOND, "unrelated.hr.topic.GetReferenceData", "On"),
    ), "read-r1")
    result = compare_flat_catalog(catalog, inventory, (selected,))
    assert [item.status for item in result.sets] == [hr_status, it_status]
    assert result.selected_member_ids == (FIRST,)
    active = next(item for item in result.sets if item.status == "present")
    assert active.definition.agent_schema_name == schema
    assert len(active.members) == 1
    assert result.live_actions_available is False
    old_selection = compare_flat_catalog(catalog, inventory, ("workday",))
    assert old_selection.selected_member_ids == ()
    assert "missing_set:workday" in old_selection.blockers


def test_wrong_family_schema_is_not_rewritten_to_claim_presence(tmp_path):
    catalog = load_document(tmp_path, variant_document())
    inventory = NativeInventory(TARGET, "package.hr", (
        InventoryTopic(FIRST, "exact.hr.topic.GetReferenceData", "On"),
    ), "read-r1")
    result = compare_flat_catalog(catalog, inventory, ("workday-da-hr",))
    assert result.sets[0].status == "absent"
    assert result.selected_member_ids == ()


def test_duplicate_variant_and_malformed_versioned_forms_fail_closed(tmp_path):
    document = variant_document()
    document["sets"][0]["sourceVariants"].append(document["sets"][0]["sourceVariants"][0])
    with pytest.raises(DiscoveryError) as error:
        load_document(tmp_path, document)
    assert error.value.reason == "ambiguous_set"
    document = variant_document()
    document["sets"][0]["members"] = []
    with pytest.raises(DiscoveryError) as error:
        load_document(tmp_path, document)
    assert error.value.reason == "invalid_catalog"
    document = catalog_document()
    document["sets"][0]["sourceVariants"] = []
    with pytest.raises(DiscoveryError) as error:
        load_document(tmp_path, document)
    assert error.value.reason == "unsupported_catalog_format"


def test_listing_does_not_select_all_and_presence_is_not_authority(catalog, inventory):
    result = compare_flat_catalog(catalog, inventory)
    assert [item.status for item in result.sets] == ["present", "present", "not_applicable"]
    assert result.selected_keys == result.selected_member_ids == ()
    assert result.evidence_kind == "provided_inventory"
    assert "deployed_package_binding_unverified" in result.blockers
    assert "protection_coverage_unverified" in result.blockers
    assert result.live_actions_available is False


def test_selected_union_maps_installed_ids_and_deduplicates_overlap(catalog, inventory):
    result = compare_flat_catalog(catalog, inventory, ("isv-a", "isv-b"))
    assert result.selected_member_ids == (FIRST, SECOND)
    assert result.sets[0].members[0].state == "On"
    assert result.sets[0].members[1].state == "Off"
    assert result.sets[0].members[0].required is None
    assert f"unknown_protection:{FIRST}" in result.blockers
    assert result.live_actions_available is False


@pytest.mark.parametrize(("topics", "expected"), [
    ((), "absent"),
    ((InventoryTopic(FIRST, "exact.hr.topic.GetReferenceData", "On"),), "partial"),
    ((InventoryTopic(FIRST, "exact.hr.topic.GetReferenceDataExtra", "On"),), "absent"),
    ((
        InventoryTopic(FIRST, "exact.hr.topic.GetReferenceData", "On"),
        InventoryTopic(OTHER, "exact.hr.topic.GetReferenceData", "On"),
    ), "ambiguous"),
])
def test_absent_partial_ambiguous_and_prefixes_never_claim_present(catalog, inventory, topics, expected):
    result = compare_flat_catalog(catalog, replace(inventory, topics=topics), ("isv-a",))
    assert result.sets[0].status == expected
    assert f"set_{expected}:isv-a" in result.blockers
    assert result.selected_keys == ("isv-a",)
    assert result.live_actions_available is False


def test_invalid_combined_selection_stays_selected(catalog, inventory):
    result = compare_flat_catalog(catalog, inventory, ("isv-a", "isv-c", "unknown"))
    assert result.selected_keys == ("isv-a", "isv-c", "unknown")
    assert "set_not_applicable:isv-c" in result.blockers
    assert "missing_set:unknown" in result.blockers
    assert result.selected_member_ids == (FIRST, SECOND)
    assert result.live_actions_available is False


def test_unknown_state_and_missing_freshness_remain_explicit(catalog, inventory):
    changed = replace(inventory, revision=None, topics=(
        replace(inventory.topics[0], state="Unknown"), inventory.topics[1],
    ))
    result = compare_flat_catalog(catalog, changed, ("isv-a",))
    assert result.sets[0].status == "present"
    assert f"unknown_state:{FIRST}" in result.blockers
    assert "inventory_freshness_unverified" in result.blockers


def native_payload():
    """Pure parser fixture using the existing setup/M2 native fetch field contract.

    Confirmed consumers: topic_actions_flat_discovery.inventory_from_response and
    PR481 topic_actions_components._snapshot. Not a network mock or cassette.
    """
    return {
        "bot": {"cdsBotId": TARGET.agent_id, "schemaName": "exact.hr"},
        "changeToken": "private-change-token",
        "botComponentChanges": [{
            "$kind": "BotComponentInsert",
            "component": {
                "$kind": "DialogComponent", "id": FIRST,
                "parentBotId": TARGET.agent_id,
                "schemaName": "exact.hr.topic.GetReferenceData",
                "state": "Active", "status": "Active",
                "displayName": "not a membership key",
                "dialog": {"sensitiveContent": "must not escape"},
            },
        }],
    }


def test_native_projection_drops_token_and_dialog_body_and_normalizes_states():
    body = native_payload()
    result = inventory_from_response(TARGET, body)
    assert result.topics == (InventoryTopic(FIRST, "exact.hr.topic.GetReferenceData", "On"),)
    assert result.revision is not None
    assert "private-change-token" not in json.dumps(asdict(result))
    assert "must not escape" not in repr(result)
    body["botComponentChanges"][0]["component"].update(state="Inactive", status="Inactive")
    assert inventory_from_response(TARGET, body).topics[0].state == "Off"
    body["botComponentChanges"][0]["component"].update(state="mc", status="Active")
    assert inventory_from_response(TARGET, body).topics[0].state == "Unknown"


@pytest.mark.parametrize(("mutation", "reason"), [
    (lambda b: b["bot"].update(cdsBotId=OTHER), "target_mismatch"),
    (lambda b: b["botComponentChanges"][0]["component"].update(parentBotId=OTHER), "target_mismatch"),
    (lambda b: b["botComponentChanges"].append(b["botComponentChanges"][0]), "ambiguous_inventory"),
    (lambda b: b["botComponentChanges"][0].update({"$kind": "BotComponentDelete"}), "invalid_inventory"),
    (lambda b: b["botComponentChanges"][0]["component"].update(schemaName=None), "invalid_identity"),
])
def test_bad_inventory_never_becomes_absent_sets(mutation, reason):
    body = native_payload()
    mutation(body)
    with pytest.raises(DiscoveryError) as error:
        inventory_from_response(TARGET, body)
    assert error.value.reason == reason


def test_foreign_unselected_component_and_empty_token_fail_closed():
    body = native_payload()
    body["botComponentChanges"].append({
        "$kind": "BotComponentInsert",
        "component": {
            "$kind": "GlobalVariableComponent", "id": SECOND,
            "parentBotId": OTHER,
        },
    })
    with pytest.raises(DiscoveryError) as error:
        inventory_from_response(TARGET, body)
    assert error.value.reason == "target_mismatch"
    body = native_payload()
    body["changeToken"] = " "
    with pytest.raises(DiscoveryError) as error:
        inventory_from_response(TARGET, body)
    assert error.value.reason == "invalid_inventory"


def test_missing_token_is_freshness_unknown_not_missing_members(catalog):
    body = native_payload()
    del body["changeToken"]
    result = compare_flat_catalog(catalog, inventory_from_response(TARGET, body))
    assert result.sets[0].status == "partial"
    assert "inventory_freshness_unverified" in result.blockers
    assert result.live_actions_available is False


def test_duplicate_provided_ids_and_invalid_catalog_are_rejected(catalog, inventory):
    with pytest.raises(DiscoveryError) as error:
        compare_flat_catalog(catalog, replace(inventory, topics=(
            inventory.topics[0], replace(inventory.topics[1], component_id=FIRST),
        )))
    assert error.value.reason == "ambiguous_inventory"
    with pytest.raises(DiscoveryError) as error:
        compare_flat_catalog(replace(catalog, sets=(*catalog.sets, catalog.sets[0])), inventory)
    assert error.value.reason == "ambiguous_set"


def read_client():
    host = derive_environment_host(TARGET.environment_id, "prod", resolver=lambda *_: [])
    return SimpleNamespace(host=host, tenant_id=TARGET.tenant_id, ring="prod")


def test_live_entry_orders_verified_target_then_fresh_read_and_never_mutates(
    monkeypatch, catalog, inventory,
):
    events = []
    client = read_client()
    client.fetch_components = lambda identity: events.append(("fetch", identity)) or object()
    client.update_components = lambda *_: pytest.fail("Discovery must never update components.")
    monkeypatch.setattr(
        "topic_actions_flat_discovery.verify_native_target",
        lambda _, target: events.append(("verify", target.agent_id)),
    )
    monkeypatch.setattr("topic_actions_flat_discovery.inventory_from_response", lambda *_: inventory)
    result = discover_topic_sets(TARGET, ("isv-a",), client=client, catalog=catalog)
    assert events == [("verify", TARGET.agent_id), ("fetch", TARGET.agent_id)]
    assert result.evidence_kind == "native_read"
    assert result.live_actions_available is False


@pytest.mark.parametrize("keys", [(), ("isv-a", "isv-a"), (" unsafe",), ["isv-a"]])
def test_bad_selection_fails_before_reads(monkeypatch, catalog, keys):
    monkeypatch.setattr(
        "topic_actions_flat_discovery.verify_native_target",
        lambda *_args, **_kwargs: pytest.fail("Invalid selection must not read."),
    )
    with pytest.raises(DiscoveryError):
        discover_flat_topic_sets(read_client(), TARGET, catalog, keys)


def test_bad_catalog_fails_before_reads(monkeypatch, catalog):
    monkeypatch.setattr(
        "topic_actions_flat_discovery.verify_native_target",
        lambda *_args, **_kwargs: pytest.fail("Invalid catalog must not read."),
    )
    with pytest.raises(DiscoveryError) as error:
        discover_flat_topic_sets(read_client(), TARGET, replace(catalog, sets=()))
    assert error.value.reason == "invalid_catalog"


@pytest.mark.parametrize("change", [
    {"tenant_id": OTHER}, {"host": "https://unrelated.example"},
    {"host": "http://unrelated.example"}, {"ring": "unknown"},
])
def test_client_binding_rejects_mismatched_tenant_or_environment(monkeypatch, catalog, change):
    client = read_client()
    for key, value in change.items():
        setattr(client, key, value)
    monkeypatch.setattr(
        "topic_actions_flat_discovery.verify_native_target",
        lambda *_args, **_kwargs: pytest.fail("Unbound client must not read."),
    )
    with pytest.raises(DiscoveryError):
        discover_flat_topic_sets(client, TARGET, catalog)


@pytest.mark.parametrize(("failure", "reason"), [
    (AgentBuilderHTTPError("private-operation", 403), "access_denied"),
    (requests.Timeout("private service text"), "read_timeout"),
])
def test_failed_read_has_no_cached_or_synthetic_fallback(monkeypatch, catalog, failure, reason):
    def fail(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr("topic_actions_flat_discovery.verify_native_target", fail)
    with pytest.raises(DiscoveryError) as error:
        discover_flat_topic_sets(read_client(), TARGET, catalog)
    assert error.value.reason == reason
    assert "private" not in str(error.value)
