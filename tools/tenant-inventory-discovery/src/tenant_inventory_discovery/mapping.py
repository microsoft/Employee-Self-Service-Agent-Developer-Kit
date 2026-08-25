"""Resource -> :class:`InventoryItem` -> upsert-body mapping.

A discovered resource is a raw ``dict`` already projected into the server's camelCase
attribute key space by its per-kind crawler. This module turns it into a validated
:class:`~tenant_inventory_discovery.models.InventoryItem` and then into the JSON body
the upsert POST expects.

The wire shape is dictated by
``Sdk.AgentConfiguration.Inventory.Beta.AgentConfigurationInventoryItem``:

- ``attributes`` is an **array of ``{key, value}`` entries**, never a JSON object or
  an object-encoded string -- a plain dictionary serializes as an array of empty
  objects on an OData entity type.
- Every attribute ``value`` is a **string**; Boolean/Integer-typed keys travel as
  ``"true"`` / ``"42"`` and are coerce-validated server-side.
- There is **no top-level ``connectorId``**. A connector reference is carried as the
  ``connectorId`` *attribute* on the kinds whose schema allows it (Connection,
  ScenarioTemplate). Posting an unknown top-level field binds the body to null and
  yields a 400.
- ``source`` / ``submittedById`` / ``state`` / audit / ``version`` are omitted: the
  server stamps them and ignores any caller-supplied value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .models import InventoryItem, Kind
from .schemas import (
    AttributeCaps,
    drop_unlisted,
    encode_attribute_value,
    validate_attributes,
)


def map_resource(
    kind: Kind,
    attributes: Mapping[str, object],
    *,
    caps: AttributeCaps | None = None,
    display_name: str | None = None,
    description: str | None = None,
    dropped_out: list[str] | None = None,
) -> InventoryItem:
    """Map one discovered resource to a validated :class:`InventoryItem`.

    - Drops attribute keys the server schema does not model (they would be rejected
      outright), appending them to ``dropped_out`` when supplied.
    - Composes ``naturalKey`` from the kind's identity fields.
    - Sets ``environmentId`` (the containment edge) for env-scoped kinds.
    - Pre-validates the surviving attributes against the schema and caps.

    Raises on invalid attributes; the caller records the item as ``skipped_invalid``,
    which makes the scope incomplete if a required key was missing.
    """
    kept, dropped = drop_unlisted(kind, dict(attributes))
    if dropped and dropped_out is not None:
        dropped_out.extend(dropped)

    validate_attributes(kind, kept, caps)

    natural_key = kind.compose_natural_key(kept)
    environment_id = str(kept["environmentId"]) if kind.is_env_scoped else None

    # `displayName` is read from the *original* bag, not the filtered one: it is a
    # first-class column on the row, so a kind whose attribute schema happens not to
    # model it (ScenarioTemplate, ExtensionPack) should still get a label.
    resolved_display_name = display_name
    if resolved_display_name is None and attributes.get("displayName"):
        resolved_display_name = str(attributes["displayName"])

    caps = caps or AttributeCaps()
    if resolved_display_name is not None:
        resolved_display_name = resolved_display_name[: caps.max_display_name_length]
    if description is not None:
        description = description[: caps.max_description_length]

    return InventoryItem(
        kind=kind,
        natural_key=natural_key,
        attributes=kept,
        environment_id=environment_id,
        display_name=resolved_display_name,
        description=description,
    )


def idempotency_key(item: InventoryItem, run_id: str = "") -> str:
    """Stable per-item, **per-pass** ``Idempotency-Key``.

    Derived from ``run_id + kind + naturalKey + attributes``, which makes a network
    retry of the same upsert replay the server's cached response instead of
    re-applying.

    Including ``run_id`` is load-bearing, not cosmetic. The service caches an
    idempotency key for 24h, and reconcile decides drift by comparing each row's
    server-stamped ``UpdatedAt`` against the pass watermark. A run-independent key
    would let a second pass within that window *replay* the write for an unchanged
    resource -- leaving ``UpdatedAt`` behind the new watermark and getting a
    perfectly live row retired. Scoping the key to the pass guarantees every
    observed row's timestamp advances.
    """
    canonical_attrs = json.dumps(
        {k: encode_attribute_value(v) for k, v in item.attributes.items()},
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(
        f"{run_id}\x1f{item.kind.discriminator}\x1f{item.natural_key}"
        f"\x1f{canonical_attrs}".encode()
    )
    return digest.hexdigest()


def to_attribute_entries(attributes: Mapping[str, object]) -> list[dict[str, str]]:
    """Render the attribute bag as the server's ``{key, value}`` entry array.

    Sorted by key so the body is byte-stable across runs, which keeps the
    idempotency key meaningful and makes request diffs readable.
    """
    return [
        {"key": key, "value": encode_attribute_value(attributes[key])}
        for key in sorted(attributes)
    ]


def to_request_body(item: InventoryItem) -> dict[str, Any]:
    """Build the upsert POST body for one item."""
    body: dict[str, Any] = {
        "kind": item.kind.discriminator,
        "naturalKey": item.natural_key,
        "attributes": to_attribute_entries(item.attributes),
    }
    if item.environment_id is not None:
        body["environmentId"] = item.environment_id
    if item.display_name is not None:
        body["displayName"] = item.display_name
    if item.description is not None:
        body["description"] = item.description
    return body
