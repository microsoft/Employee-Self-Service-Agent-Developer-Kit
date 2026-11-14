"""Client decorator that records what a run applied.

The durable local mirror is built from the items a run submitted. The in-memory fake
happens to expose them (it *is* the store), but the live client does not -- it POSTs
and forgets. Rather than re-listing the whole tenant afterwards (an extra round trip
that would also pick up rows this run never touched), this wrapper captures the payload
as it goes out.

The mirror is written from the *response*, not the request: a sync reports which items
it retired, and a payload item can come back in ``failedItems`` having not been stored
at all. Recording the request alone would mirror a tenant state that never existed.

A run whose payload already matched the service skips the sync and sends nothing, so
there is no response to read. The caller records that payload through
:meth:`RecordingInventoryClient.record_unchanged` instead: the service provably holds it.

It delegates every call, so it satisfies the same
:class:`~tenant_inventory_discovery.inventory_client.InventoryClient` Protocol and can
wrap either implementation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from .in_memory_inventory import StoredItem
from .models import InventoryItem, Kind, SyncResult


class RecordingInventoryClient:
    """Wrap an :class:`InventoryClient` and remember every item it applied."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.items: dict[str, StoredItem] = {}

    def list_items(
        self, *, kind: Kind | None = None, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        return self._inner.list_items(kind=kind, environment_id=environment_id)

    def sync_inventory(
        self, items: Sequence[InventoryItem], *, run_id: str = ""
    ) -> SyncResult:
        result = self._inner.sync_inventory(items, run_id=run_id)
        failed = set(result.failed_item_ids)
        now = datetime.now(UTC)
        for item in items:
            if item.item_id in failed:
                continue
            self.items[item.item_id] = _stored(item, now)
        for item_id in result.retired_item_ids:
            stored = self.items.get(item_id)
            if stored is not None:
                stored.state = "Retired"
        return result

    def record_unchanged(self, items: Sequence[InventoryItem]) -> None:
        """Record a payload the service already holds, though no sync was sent.

        Call this when a run reports
        :attr:`~tenant_inventory_discovery.models.RunSummary.sync_unchanged`. The sync
        is skipped only when the payload matches the service's Active rows exactly --
        same keys, same wire form -- so every item is Active server-side and nothing
        else is. Without this the recorder stays empty, which reads as an empty tenant:
        the results list nothing and the local mirror retires every row.
        """
        now = datetime.now(UTC)
        for item in items:
            self.items[item.item_id] = _stored(item, now)


def _stored(item: InventoryItem, now: datetime) -> StoredItem:
    return StoredItem(
        kind=item.kind,
        natural_key=item.natural_key,
        attributes=dict(item.attributes),
        environment_id=item.environment_id or "",
        display_name=item.display_name,
        description=item.description,
        updated_at=now,
    )
