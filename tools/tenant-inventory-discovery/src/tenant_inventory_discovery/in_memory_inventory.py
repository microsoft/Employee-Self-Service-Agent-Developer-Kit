"""In-memory implementation of the Inventory API, for dry-runs, demos, and tests.

This is a **real implementation** of the
:class:`~tenant_inventory_discovery.inventory_client.InventoryClient` Protocol whose
storage happens to be a dict -- not a hollow test stub. It reproduces the *observable*
semantics of the live service, so a test that passes here is meaningful against the
real thing:

- ``syncInventory`` takes the tenant's **whole** inventory and treats the payload as
  the desired end state: rows are upserted, and every Active ``Discovered`` row the
  payload omits is **retired**. There is no per-row write and no delete call.
- Rows are keyed on ``(kind, naturalKey)``; re-asserting a Retired discovered row
  revives it.
- Ordering inside the call mirrors the service's, not the caller's: parents are
  written before children and retirement happens after every upsert, so a payload may
  arrive in any order.
- A child whose environment is carried by neither the payload nor the store lands in
  ``failedItems`` -- **partial success**, since everything else still applied.
- Manually-authored rows (``Source != Discovered``) are never retired by absence.
- ``list_items`` never returns Retired rows.
- The payload is rejected outright when it is empty, carries a duplicate
  ``kind:naturalKey``, or blows a cap -- see
  :func:`~tenant_inventory_discovery.mapping.validate_sync_payload`.
- An ``Idempotency-Key`` replays the original response, ``retiredItemIds`` included.

That fidelity is the point. It is what let the suite catch a cross-run idempotency
replay silently suppressing a write -- a laxer stub would have passed.

Two callers:

1. **``--local-only`` dry-runs** (kit bridge and ``__main__``): crawl, validate, and
   mirror locally without writing to the service.
2. **Tests**, via ``tests/spies.py``, which subclasses this to add call counters.
   Assertion-only bookkeeping lives there, not here.

The clock is injectable so a test can order writes deterministically without sleeping.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .mapping import sync_idempotency_key, validate_sync_payload
from .models import (
    FailedSyncItem,
    InventoryItem,
    Kind,
    SyncResult,
    encode_item_id,
)
from .schemas import AttributeCaps


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class StoredItem:
    kind: Kind
    natural_key: str
    attributes: dict[str, object]
    environment_id: str
    display_name: str | None = None
    description: str | None = None
    source: str = "Discovered"
    state: str = "Active"
    version: int = 1
    updated_at: datetime = field(default_factory=_utcnow)

    @property
    def item_id(self) -> str:
        return encode_item_id(self.kind, self.natural_key)

    def to_wire(self) -> dict[str, Any]:
        return {
            "agentConfigurationInventoryItemId": self.item_id,
            "kind": self.kind.discriminator,
            "naturalKey": self.natural_key,
            "environmentId": self.environment_id,
            "displayName": self.display_name,
            "description": self.description,
            "source": self.source,
            "state": self.state,
            "etag": str(self.version),
            "updatedAt": self.updated_at.isoformat(),
            "attributes": [
                {"key": k, "value": v} for k, v in sorted(self.attributes.items())
            ],
        }


@dataclass
class InMemoryInventoryClient:
    """In-memory store honoring the whole-inventory sync contract."""

    items: dict[str, StoredItem] = field(default_factory=dict)
    replayed_syncs: dict[str, SyncResult] = field(default_factory=dict)
    caps: AttributeCaps = field(default_factory=AttributeCaps)
    clock: Callable[[], datetime] = _utcnow

    # -- InventoryClient ------------------------------------------------------------

    def list_items(
        self, *, kind: Kind | None = None, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [s for s in self.items.values() if s.state != "Retired"]
        if kind is not None:
            rows = [s for s in rows if s.kind is kind]
        if environment_id is not None:
            rows = [s for s in rows if s.environment_id == environment_id]
        rows.sort(key=lambda s: s.natural_key)
        return [s.to_wire() for s in rows]

    def sync_inventory(
        self, items: Sequence[InventoryItem], *, run_id: str = ""
    ) -> SyncResult:
        """Replace the tenant's inventory with ``items``; absences retire.

        Mirrors the service's ordering guarantee rather than relying on the caller's:
        parents are written before children and retirement happens after every upsert,
        so a payload may arrive in any order.
        """
        payload = list(items)
        validate_sync_payload(payload, caps=self.caps)

        idem = sync_idempotency_key(payload, run_id)
        cached = self.replayed_syncs.get(idem)
        if cached is not None:
            # 24h replay of the original response, including its retiredItemIds.
            return cached

        # Parents first so a child never lands before the environment containing it.
        ordered = sorted(payload, key=lambda i: i.kind is not Kind.ENVIRONMENT)

        submitted_ids: set[str] = set()
        failed: list[FailedSyncItem] = []
        upserted = 0

        for item in ordered:
            item_id = item.item_id
            if item.kind.is_env_scoped and not self._environment_present(
                item, payload
            ):
                # The documented per-item failure: a child whose environment the
                # payload does not carry. Partial success -- everything else applies.
                failed.append(
                    FailedSyncItem(
                        item_id=item_id,
                        reason=(
                            f"environment {item.environment_id!r} is not present in "
                            "the payload or the store"
                        ),
                    )
                )
                continue
            submitted_ids.add(item_id)
            self._apply(item)
            upserted += 1

        # Absence retires. Children first so an Environment is never refused over rows
        # this same call is removing.
        retired_ids: list[str] = []
        stale = [
            s
            for s in self.items.values()
            if s.state == "Active"
            and s.source == "Discovered"
            and s.item_id not in submitted_ids
        ]
        for stored in sorted(stale, key=lambda s: s.kind is Kind.ENVIRONMENT):
            stored.state = "Retired"
            stored.version += 1
            stored.updated_at = self.clock()
            retired_ids.append(stored.item_id)

        result = SyncResult(
            submitted_count=len(payload),
            upserted_count=upserted,
            retired_count=len(retired_ids),
            retired_item_ids=retired_ids,
            failed_items=failed,
        )
        self.replayed_syncs[idem] = result
        return result

    def _environment_present(
        self, item: InventoryItem, payload: Sequence[InventoryItem]
    ) -> bool:
        """Is the environment this row hangs off available to contain it?"""
        env_id = item.environment_id or ""
        if not env_id:
            return False
        if any(
            other.kind is Kind.ENVIRONMENT and other.natural_key == env_id
            for other in payload
        ):
            return True
        existing = self.items.get(encode_item_id(Kind.ENVIRONMENT, env_id))
        return existing is not None and existing.state == "Active"

    def _apply(self, item: InventoryItem) -> None:
        """Create or overwrite one row, reviving it if it had been retired."""
        item_id = item.item_id
        env_id = item.environment_id or ""
        stored = self.items.get(item_id)
        if stored is None:
            self.items[item_id] = StoredItem(
                kind=item.kind,
                natural_key=item.natural_key,
                attributes=dict(item.attributes),
                environment_id=env_id,
                display_name=item.display_name,
                description=item.description,
                updated_at=self.clock(),
            )
            return
        stored.attributes = dict(item.attributes)
        stored.environment_id = env_id
        stored.display_name = item.display_name
        stored.description = item.description
        stored.version += 1
        stored.updated_at = self.clock()
        if stored.source == "Discovered":
            stored.state = "Active"  # re-asserting revives a retired row

    # -- test helpers ---------------------------------------------------------------

    def active_items(self) -> list[StoredItem]:
        return [s for s in self.items.values() if s.state == "Active"]

    def get(self, kind: Kind, natural_key: str) -> StoredItem | None:
        return self.items.get(encode_item_id(kind, natural_key))
