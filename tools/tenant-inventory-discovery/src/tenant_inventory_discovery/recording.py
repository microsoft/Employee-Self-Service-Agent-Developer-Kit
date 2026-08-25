"""Client decorator that records what a run applied.

The durable local mirror is built from the items a run wrote. The in-memory fake
happens to expose them (it *is* the store), but the live client does not -- it POSTs
and forgets. Rather than re-listing the whole tenant afterwards (an extra round trip
that would also pick up rows this run never touched), this wrapper captures each
applied item as it goes.

It delegates every call, so it satisfies the same
:class:`~tenant_inventory_discovery.inventory_client.InventoryClient` Protocol and can
wrap either implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .in_memory_inventory import StoredItem
from .models import InventoryItem, Kind, ReconcileResult, UpsertResult


class RecordingInventoryClient:
    """Wrap an :class:`InventoryClient` and remember every item it applied."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.items: dict[str, StoredItem] = {}

    def upsert(
        self, item: InventoryItem, *, if_match: str | None = None, run_id: str = ""
    ) -> UpsertResult:
        result = self._inner.upsert(item, if_match=if_match, run_id=run_id)
        self.items[item.item_id] = StoredItem(
            kind=item.kind,
            natural_key=item.natural_key,
            attributes=dict(item.attributes),
            environment_id=item.environment_id or "",
            display_name=item.display_name,
            description=item.description,
            updated_at=datetime.now(timezone.utc),
        )
        return result

    def list_items(
        self, *, kind: Kind | None = None, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        return self._inner.list_items(kind=kind, environment_id=environment_id)

    def retire(self, item_id: str, *, if_match: str | None = None) -> None:
        self._inner.retire(item_id, if_match=if_match)
        stored = self.items.get(item_id)
        if stored is not None:
            stored.state = "Retired"

    def reconcile(
        self, kind: Kind, environment_id: str, pass_started_at: datetime
    ) -> ReconcileResult:
        result = self._inner.reconcile(kind, environment_id, pass_started_at)
        for item_id in result.retired_item_ids:
            stored = self.items.get(item_id)
            if stored is not None:
                stored.state = "Retired"
        return result
