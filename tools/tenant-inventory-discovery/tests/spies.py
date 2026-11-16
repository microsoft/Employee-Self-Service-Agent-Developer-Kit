"""Test-only spies over the in-memory Inventory client.

Call counters are an *assertion* concern, not a behavioural one, so they live here
rather than in the shipped
:class:`~tenant_inventory_discovery.in_memory_inventory.InMemoryInventoryClient` --
which is real production code behind ``--local-only`` and should not carry
bookkeeping no caller reads.

Every counter increments *before* delegating, so a call that raises is still counted.
Tests that assert "this was never attempted" depend on that -- which is the whole
point under the whole-inventory contract, where the dangerous outcome is a sync that
happened when it should have been withheld.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from tenant_inventory_discovery.in_memory_inventory import InMemoryInventoryClient
from tenant_inventory_discovery.models import InventoryItem, Kind, SyncResult


@dataclass
class SpyInventoryClient(InMemoryInventoryClient):
    """:class:`InMemoryInventoryClient` plus per-method call counts.

    ``sync_payloads`` keeps every payload submitted, so a test can assert on what was
    *sent* independently of what the store did with it.
    """

    list_calls: int = field(default=0)
    sync_calls: int = field(default=0)
    sync_payloads: list[list[InventoryItem]] = field(default_factory=list)

    def list_items(
        self, *, kind: Kind | None = None, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        self.list_calls += 1
        return super().list_items(kind=kind, environment_id=environment_id)

    def sync_inventory(
        self, items: Sequence[InventoryItem], *, run_id: str = ""
    ) -> SyncResult:
        self.sync_calls += 1
        self.sync_payloads.append(list(items))
        return super().sync_inventory(items, run_id=run_id)

    # -- assertion helpers ------------------------------------------------------------

    @property
    def last_payload(self) -> list[InventoryItem]:
        """The most recent submitted payload (fails loudly if nothing was sent)."""
        assert self.sync_payloads, "no sync was submitted"
        return self.sync_payloads[-1]

    def submitted_keys(self) -> set[str]:
        """``kind:naturalKey`` for every item in the most recent payload."""
        return {f"{i.kind.discriminator}:{i.natural_key}" for i in self.last_payload}

    def active_keys(self) -> set[str]:
        """``kind:naturalKey`` for every row the store currently holds as Active."""
        return {
            f"{s.kind.discriminator}:{s.natural_key}"
            for s in self.items.values()
            if s.state == "Active"
        }
