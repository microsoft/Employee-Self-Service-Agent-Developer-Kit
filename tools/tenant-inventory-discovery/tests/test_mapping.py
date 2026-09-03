"""§10: per-kind mapping, natural-key composition, and sync payload validation."""

from __future__ import annotations

import pytest

from tenant_inventory_discovery.mapping import (
    SyncPayloadError,
    map_resource,
    to_sync_entry,
    validate_sync_payload,
)
from tenant_inventory_discovery.models import InventoryItem, Kind, encode_item_id
from tenant_inventory_discovery.schemas import (
    AttributeCaps,
    AttributeValidationError,
    schema_for,
)

# One minimally-valid resource per kind: every required attribute, nothing unlisted.
SAMPLES: dict[Kind, dict[str, object]] = {
    Kind.ENVIRONMENT: {"environmentId": "e1", "region": "unitedstates"},
    Kind.ENTRA_APP: {"appId": "a1", "displayName": "App"},
    Kind.CONNECTOR: {"connectorId": "c1", "displayName": "SN"},
    Kind.CONNECTION: {"environmentId": "e1", "connectionId": "x1", "connectorId": "c1"},
    Kind.SHAREPOINT_SITE: {"siteUrl": "https://s", "siteId": "s1"},
    Kind.KNOWLEDGE_SOURCE: {"environmentId": "e1", "botId": "b1", "sourceId": "k1"},
    Kind.EXTENSION_PACK: {"environmentId": "e1", "installed": True},
    Kind.SCENARIO_TEMPLATE: {"environmentId": "e1", "uniqueName": "U"},
}


def _item(kind: Kind, natural_key: str) -> InventoryItem:
    return InventoryItem(
        kind=kind,
        natural_key=natural_key,
        attributes={kind.key_fields[-1]: natural_key},
        environment_id=natural_key if kind.is_env_scoped else None,
    )


def test_every_kind_maps_required_keys_only_allowed_camelcase():
    for kind, attrs in SAMPLES.items():
        item = map_resource(kind, attrs)
        schema = schema_for(kind)
        assert schema.required <= item.attributes.keys()
        assert item.attributes.keys() <= schema.allowed


def test_missing_required_key_fails_item():
    with pytest.raises(AttributeValidationError):
        map_resource(Kind.KNOWLEDGE_SOURCE, {"environmentId": "e1", "sourceId": "k1"})


def test_unlisted_key_is_dropped_not_rejected():
    """Unknown keys would 400 the whole sync, so the crawler drops them first."""
    dropped: list[str] = []
    item = map_resource(
        Kind.CONNECTOR,
        {"connectorId": "c1", "displayName": "SN", "bogus": "x"},
        dropped_out=dropped,
    )
    assert "bogus" not in item.attributes
    assert dropped == ["bogus"]
    assert item.attributes == {"connectorId": "c1", "displayName": "SN"}


def test_env_scoped_natural_key_composes_environment_id():
    a = map_resource(
        Kind.CONNECTION,
        {"environmentId": "envA", "connectionId": "c-1", "connectorId": "k"},
    )
    b = map_resource(
        Kind.CONNECTION,
        {"environmentId": "envB", "connectionId": "c-1", "connectorId": "k"},
    )
    assert a.natural_key != b.natural_key
    assert a.natural_key == "envA:c-1"
    assert b.natural_key == "envB:c-1"


def test_multipart_key_for_knowledge_source():
    item = map_resource(
        Kind.KNOWLEDGE_SOURCE,
        {"environmentId": "e1", "botId": "b1", "sourceId": "k1"},
    )
    assert item.natural_key == "e1:b1:k1"


def test_composite_segments_are_escaped_before_joining():
    """A separator inside a segment must not create a phantom extra segment."""
    item = map_resource(
        Kind.KNOWLEDGE_SOURCE,
        {"environmentId": "e1", "botId": "b:1", "sourceId": "k1"},
    )
    assert item.natural_key == "e1:b%3A1:k1"
    assert item.natural_key.count(":") == 2


def test_single_segment_natural_key_is_raw():
    """Single-segment kinds keep the raw value; only the item id encodes it."""
    url = "https://contoso.sharepoint.com/sites/hr"
    item = map_resource(Kind.SHAREPOINT_SITE, {"siteUrl": url})
    assert item.natural_key == url
    assert item.item_id == encode_item_id(Kind.SHAREPOINT_SITE, url)
    assert item.item_id.startswith("SharePointSite:https%3A%2F%2F")


def test_extension_pack_is_keyed_on_environment():
    """The schema has no pack identity, so an environment holds exactly one row."""
    item = map_resource(
        Kind.EXTENSION_PACK, {"environmentId": "e1", "installed": True, "hrsd": False}
    )
    assert item.natural_key == "e1"
    assert item.environment_id == "e1"


def test_connection_carries_connector_edge_as_attribute():
    """The reference edge lives in attributes; there is no top-level connectorId."""
    item = map_resource(
        Kind.CONNECTION,
        {"environmentId": "e1", "connectionId": "c-1", "connectorId": "cat-9"},
    )
    body = to_sync_entry(item, "tenant-1")
    assert item.attributes["connectorId"] == "cat-9"
    assert item.environment_id == "e1"
    assert "connectorId" not in body


def test_tenant_root_has_no_environment_id():
    item = map_resource(Kind.CONNECTOR, {"connectorId": "c1", "displayName": "SN"})
    body = to_sync_entry(item, "tenant-1")
    assert item.environment_id is None
    assert "environmentId" not in body


def test_sync_entry_serializes_attributes_as_entry_array():
    item = map_resource(Kind.ENVIRONMENT, {"environmentId": "e1", "region": "us"})
    body = to_sync_entry(item, "tenant-1")
    assert body["tenantId"] == "tenant-1"
    assert body["kind"] == "Environment"
    assert body["naturalKey"] == "e1"
    assert body["validationStatus"] == "Unvalidated"

    assert body["attributes"] == [
        {"key": "environmentId", "value": "e1"},
        {"key": "region", "value": "us"},
    ]

    for forbidden in ("source", "submittedById", "state", "createdAt", "version", "etag"):
        assert forbidden not in body


def test_typed_attribute_values_travel_as_strings():
    """Boolean/Integer keys are coerce-validated from their string wire form."""
    item = map_resource(
        Kind.EXTENSION_PACK,
        {"environmentId": "e1", "installed": True, "hrsd": False, "flowCount": 12},
    )
    entries = {e["key"]: e["value"] for e in to_sync_entry(item, "tenant-1")["attributes"]}
    assert entries["installed"] == "true"
    assert entries["hrsd"] == "false"
    assert entries["flowCount"] == "12"
    assert all(isinstance(v, str) for v in entries.values())


def test_non_coercible_typed_value_fails_item():
    with pytest.raises(AttributeValidationError):
        map_resource(Kind.EXTENSION_PACK, {"environmentId": "e1", "installed": "maybe"})
    with pytest.raises(AttributeValidationError):
        map_resource(
            Kind.EXTENSION_PACK,
            {"environmentId": "e1", "installed": True, "flowCount": "many"},
        )


def test_caps_enforced_while_mapping_fields():
    caps = AttributeCaps(max_value_length=3)
    with pytest.raises(AttributeValidationError):
        map_resource(
            Kind.ENVIRONMENT,
            {"environmentId": "e1", "region": "way-too-long"},
            caps=caps,
        )

    with pytest.raises(AttributeValidationError):
        map_resource(
            Kind.ENVIRONMENT,
            {"environmentId": "e1"},
            caps=AttributeCaps(max_attribute_count=0),
        )


def test_validate_sync_payload_rejects_an_empty_payload():
    with pytest.raises(SyncPayloadError, match="empty payload"):
        validate_sync_payload([])


def test_validate_sync_payload_rejects_more_than_400_items():
    items = [_item(Kind.ENVIRONMENT, f"e{i}") for i in range(401)]
    caps = AttributeCaps(max_items_per_tenant_and_kind=500)
    with pytest.raises(SyncPayloadError, match="per-call cap"):
        validate_sync_payload(items, caps=caps, max_items=400)


def test_validate_sync_payload_rejects_more_than_50_in_one_kind():
    items = [_item(Kind.ENVIRONMENT, f"e{i}") for i in range(51)]
    with pytest.raises(SyncPayloadError, match="per-kind cap"):
        validate_sync_payload(items)


def test_validate_sync_payload_rejects_duplicate_kind_natural_key():
    items = [_item(Kind.CONNECTOR, "c1"), _item(Kind.CONNECTOR, "c1")]
    with pytest.raises(SyncPayloadError, match="duplicate item"):
        validate_sync_payload(items)
