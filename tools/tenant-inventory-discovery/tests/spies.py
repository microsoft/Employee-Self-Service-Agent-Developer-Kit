"""Test-only spies over the in-memory Inventory client.

Call counters are an *assertion* concern, not a behavioural one, so they live here
rather than in the shipped
:class:`~tenant_inventory_discovery.in_memory_inventory.InMemoryInventoryClient` --
which is real production code behind ``--local-only`` and should not carry
bookkeeping no caller reads.

Every counter increments *before* delegating, so a call that raises is still counted.
Tests that assert "this was never attempted" depend on that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from tenant_inventory_discovery.in_memory_inventory import InMemoryInventoryClient
from tenant_inventory_discovery.models import Kind, ReconcileResult


@dataclass
class SpyInventoryClient(InMemoryInventoryClient):
    """:class:`InMemoryInventoryClient` plus per-method call counts."""

    upsert_calls: int = field(default=0)
    list_calls: int = field(default=0)
    retire_calls: int = field(default=0)
    reconcile_calls: int = field(default=0)

    def upsert(self, item, *, if_match: str | None = None, run_id: str = ""):
        self.upsert_calls += 1
        return super().upsert(item, if_match=if_match, run_id=run_id)

    def list_items(
        self, *, kind: Kind | None = None, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        self.list_calls += 1
        return super().list_items(kind=kind, environment_id=environment_id)

    def retire(self, item_id: str, *, if_match: str | None = None) -> None:
        self.retire_calls += 1
        super().retire(item_id, if_match=if_match)

    def reconcile(
        self, kind: Kind, environment_id: str, pass_started_at: datetime
    ) -> ReconcileResult:
        self.reconcile_calls += 1
        return super().reconcile(kind, environment_id, pass_started_at)
