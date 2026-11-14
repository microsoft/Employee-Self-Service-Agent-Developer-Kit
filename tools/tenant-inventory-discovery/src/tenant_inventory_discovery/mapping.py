"""Resource -> :class:`InventoryItem` -> ``syncInventory`` payload mapping.

A discovered resource is a raw ``dict`` already projected into the server's camelCase
attribute key space by its per-kind crawler. This module turns it into a validated
:class:`~tenant_inventory_discovery.models.InventoryItem` and then into one entry of
the whole-inventory sync payload.

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
- ``source`` / ``submittedById`` / ``state`` / audit / ``etag`` / the item id are
  accepted but **ignored inbound** -- the server stamps them. They are omitted here
  rather than sent-and-ignored, so a request body never implies authority the caller
  does not have.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .models import InventoryItem, Kind
from .schemas import (
    AttributeCaps,
    drop_unlisted,
    encode_attribute_value,
    validate_attributes,
)

#: What a crawler-authored row asserts about validation: nothing. Discovery observes
#: resources, it does not assess them, and the service's own captures show a
#: ``Discovered`` row carrying exactly this.
UNVALIDATED = "Unvalidated"


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

    Raises on invalid attributes. The caller records the item as ``skipped_invalid``,
    which withholds the whole sync: a resource that exists but cannot be described is
    a resource the payload would omit, and an omission retires.
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


def sync_idempotency_key(items: Sequence[InventoryItem], run_id: str = "") -> str:
    """Stable per-payload, **per-pass** ``Idempotency-Key`` for one sync call.

    A ``syncInventory`` call can carry up to 400 items and rewrites the tenant's whole
    inventory, so a client timeout is exactly the case worth deduplicating: without a
    key, the resend re-runs every write. The service replays the original response for
    24h, including its ``retiredItemIds``, so the caller still learns what the first
    attempt removed.

    Including ``run_id`` is load-bearing. A key derived from payload content alone
    would collide across passes whenever a tenant is unchanged -- and because the
    payload's *absences* are what retire rows, replaying a cached response would leave
    drift that appeared since the earlier pass in place until the cache aged out.
    Scoping the key to the pass makes every run genuinely apply.
    """
    canonical = json.dumps(
        sorted(
            f"{item.kind.discriminator}\x1f{item.natural_key}\x1f"
            + json.dumps(
                {k: encode_attribute_value(v) for k, v in item.attributes.items()},
                separators=(",", ":"),
                sort_keys=True,
            )
            for item in items
        ),
        separators=(",", ":"),
    )
    return hashlib.sha256(f"{run_id}\x1f{canonical}".encode()).hexdigest()


def to_attribute_entries(attributes: Mapping[str, object]) -> list[dict[str, str]]:
    """Render the attribute bag as the server's ``{key, value}`` entry array.

    Sorted by key so the payload is byte-stable across runs, which keeps the
    idempotency key meaningful and makes request diffs readable.
    """
    return [
        {"key": key, "value": encode_attribute_value(attributes[key])}
        for key in sorted(attributes)
    ]


def to_sync_entry(item: InventoryItem, tenant_id: str) -> dict[str, Any]:
    """Build one entry of the ``syncInventory`` payload.

    ``tenantId`` is carried per item rather than only in the route because the payload
    is a list of full rows in the same shape ``GET`` returns, which lets a fetched body
    be edited and posted straight back.
    """
    body: dict[str, Any] = {
        "tenantId": tenant_id,
        "kind": item.kind.discriminator,
        "naturalKey": item.natural_key,
        "validationStatus": UNVALIDATED,
        "attributes": to_attribute_entries(item.attributes),
    }
    if item.environment_id is not None:
        body["environmentId"] = item.environment_id
    if item.display_name is not None:
        body["displayName"] = item.display_name
    if item.description is not None:
        body["description"] = item.description
    return body


class SyncPayloadError(ValueError):
    """A payload the service is certain to reject, caught before it is sent."""


def validate_sync_payload(
    items: Sequence[InventoryItem],
    *,
    caps: AttributeCaps | None = None,
    max_items: int | None = None,
) -> None:
    """Reject a payload the service would refuse -- before spending the round trip.

    Each check mirrors a documented server-side rejection:

    - **Empty** -- legal on the wire, and it retires the tenant's entire inventory.
      That is never something this crawler means, so it is refused here rather than
      trusted to a caller's guard.
    - **Duplicate ``kind:naturalKey``** -- a hard ``ValidationError``, not last-one-
      wins, so a duplicate loses the whole payload rather than one row.
    - **Per-kind and total caps** -- ``InvariantViolation`` and a 400 respectively.

    Raises :class:`SyncPayloadError`; the caller withholds the sync rather than
    submitting a payload it knows to be bad.
    """
    caps = caps or AttributeCaps()
    if not items:
        raise SyncPayloadError(
            "refusing to sync an empty payload: the service treats absence as a "
            "retirement, so an empty item list would retire the tenant's entire "
            "inventory"
        )

    seen: dict[str, int] = {}
    per_kind: dict[str, int] = {}
    for index, item in enumerate(items):
        composed = f"{item.kind.discriminator}:{item.natural_key}"
        if composed in seen:
            raise SyncPayloadError(
                f"duplicate item {composed!r} at positions {seen[composed]} and "
                f"{index}; the service rejects the whole payload on a duplicate key"
            )
        seen[composed] = index
        per_kind[item.kind.discriminator] = per_kind.get(item.kind.discriminator, 0) + 1

    cap = caps.max_items_per_tenant_and_kind
    for discriminator, count in sorted(per_kind.items()):
        if count > cap:
            raise SyncPayloadError(
                f"{discriminator}: {count} items exceeds the per-kind cap of {cap}"
            )

    ceiling = max_items if max_items is not None else cap * len(Kind)
    if len(items) > ceiling:
        raise SyncPayloadError(
            f"{len(items)} items exceeds the per-call cap of {ceiling}"
        )
