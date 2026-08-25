"""§10: per-kind mapping, natural-key composition, and the upsert wire body.

These tests pin the contract against the *server's* schema
(``AgentConfigurationInventoryAttributeSchema``) and natural-key recipe
(``AgentConfigurationInventoryNaturalKey``). A change here should mean the server
changed.
"""

from __future__ import annotations

import pytest

from tenant_inventory_discovery.mapping import map_resource, to_request_body
from tenant_inventory_discovery.models import Kind, encode_item_id
from tenant_inventory_discovery.schemas import AttributeValidationError, schema_for

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


def test_every_kind_maps_required_keys_only_allowed_camelcase():
    for kind, attrs in SAMPLES.items():
        item = map_resource(kind, attrs)
        schema = schema_for(kind)
        assert schema.required <= item.attributes.keys()
        assert item.attributes.keys() <= schema.allowed


def test_missing_required_key_fails_item():
    with pytest.raises(AttributeValidationError):
        # KnowledgeSource requires botId as well as environmentId/sourceId.
        map_resource(Kind.KNOWLEDGE_SOURCE, {"environmentId": "e1", "sourceId": "k1"})


def test_unlisted_key_is_dropped_not_rejected():
    """The server 400s on an unknown key, so the client drops it first.

    Failing the whole item because a platform surface returned one extra field would
    make a scope incomplete and block reconcile -- a much worse outcome than losing
    an attribute the schema does not model.
    """
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
    # Same connectionId in two environments must not collide (spec §4).
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
    """Single-segment kinds keep the raw value; only the item id percent-encodes it."""
    url = "https://contoso.sharepoint.com/sites/hr"
    item = map_resource(Kind.SHAREPOINT_SITE, {"siteUrl": url})
    assert item.natural_key == url
    assert item.item_id == encode_item_id(Kind.SHAREPOINT_SITE, url)
    assert item.item_id.startswith("SharePointSite:https%3A%2F%2F")


def test_extension_pack_is_keyed_on_environment():
    """The schema carries no pack identity, so an environment holds exactly one row."""
    item = map_resource(
        Kind.EXTENSION_PACK, {"environmentId": "e1", "installed": True, "hrsd": False}
    )
    assert item.natural_key == "e1"
    assert item.environment_id == "e1"


def test_connection_carries_connector_edge_as_attribute():
    """The reference edge lives in `attributes`; there is no top-level connectorId."""
    item = map_resource(
        Kind.CONNECTION,
        {"environmentId": "e1", "connectionId": "c-1", "connectorId": "cat-9"},
    )
    assert item.attributes["connectorId"] == "cat-9"  # reference edge (§5.5)
    assert item.environment_id == "e1"  # containment edge (§5.5)
    assert "connectorId" not in to_request_body(item)


def test_tenant_root_has_no_environment_id():
    item = map_resource(Kind.CONNECTOR, {"connectorId": "c1", "displayName": "SN"})
    assert item.environment_id is None
    assert "environmentId" not in to_request_body(item)


def test_request_body_serializes_attributes_as_entry_array():
    item = map_resource(Kind.ENVIRONMENT, {"environmentId": "e1", "region": "us"})
    body = to_request_body(item)
    assert body["kind"] == "Environment"
    assert body["naturalKey"] == "e1"
    assert "runId" not in body  # no per-run watermark on the wire

    # attributes is an array of {key, value} entries, not an object or a string: an
    # OData entity type binds a dictionary to a list of empty objects.
    assert body["attributes"] == [
        {"key": "environmentId", "value": "e1"},
        {"key": "region", "value": "us"},
    ]

    # Skill never stamps provenance/audit/concurrency (spec §4.1).
    for forbidden in ("source", "submittedById", "state", "createdAt", "version"):
        assert forbidden not in body


def test_typed_attribute_values_travel_as_strings():
    """Boolean/Integer keys are coerce-validated from their string wire form."""
    item = map_resource(
        Kind.EXTENSION_PACK,
        {"environmentId": "e1", "installed": True, "hrsd": False, "flowCount": 12},
    )
    entries = {e["key"]: e["value"] for e in to_request_body(item)["attributes"]}
    assert entries["installed"] == "true"
    assert entries["hrsd"] == "false"
    assert entries["flowCount"] == "12"
    assert all(isinstance(v, str) for v in entries.values())


def test_non_coercible_typed_value_fails_item():
    with pytest.raises(AttributeValidationError):
        map_resource(
            Kind.EXTENSION_PACK, {"environmentId": "e1", "installed": "maybe"}
        )
    with pytest.raises(AttributeValidationError):
        map_resource(
            Kind.EXTENSION_PACK,
            {"environmentId": "e1", "installed": True, "flowCount": "many"},
        )


def test_caps_enforced():
    from tenant_inventory_discovery.schemas import AttributeCaps

    caps = AttributeCaps(max_value_length=3)
    with pytest.raises(AttributeValidationError):
        map_resource(
            Kind.ENVIRONMENT,
            {"environmentId": "e1", "region": "way-too-long"},
            caps=caps,
        )
