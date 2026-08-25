"""In-memory implementation of the Inventory API, for dry-runs, demos, and tests.

This is a **real implementation** of the
:class:`~tenant_inventory_discovery.inventory_client.InventoryClient` Protocol whose
storage happens to be a dict -- not a hollow test stub. It reproduces the *observable*
semantics of the live service, so a test that passes here is meaningful against the
real thing:

- Upsert is keyed on ``(kind, naturalKey)`` and replays a cached ``Idempotency-Key``.
- Re-asserting a Retired discovered row revives it.
- ``DELETE`` is a **soft** delete (``state = Retired``) and is idempotent.
- ``list_items`` never returns Retired rows.
- Creates are refused past :data:`AttributeCaps.max_items_per_tenant_and_kind`.
- **Reconcile is watermark-based and env-scoped only**: it retires Active,
  ``Source = Discovered`` rows in one ``(kind, environmentId)`` scope whose
  ``updatedAt`` predates ``passStartedAt``, and it *rejects* tenant-rooted kinds.
  Manually-authored rows (``Source != Discovered``) are never retired.

That fidelity is the point. It is what let the suite catch a cross-run idempotency
replay silently defeating watermark reconcile -- a laxer stub would have passed.

Two callers:

1. **``--local-only`` dry-runs** (kit bridge and ``__main__``): crawl, validate, and
   mirror locally without writing to the service.
2. **Tests**, via ``tests/spies.py``, which subclasses this to add call counters.
   Assertion-only bookkeeping lives there, not here.

The clock is injectable so a test can place writes on either side of a watermark
without sleeping.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .errors import InventoryApiError, PreconditionFailedError
from .mapping import idempotency_key
from .models import InventoryItem, Kind, ReconcileResult, encode_item_id
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
    """In-memory store honoring the idempotency + watermark-reconcile contract."""

    items: dict[str, StoredItem] = field(default_factory=dict)
    seen_idempotency_keys: dict[str, int] = field(default_factory=dict)
    caps: AttributeCaps = field(default_factory=AttributeCaps)
    clock: Callable[[], datetime] = _utcnow

    # -- InventoryClient ------------------------------------------------------------

    def upsert(
        self, item: InventoryItem, *, if_match: str | None = None, run_id: str = ""
    ):
        from .models import UpsertResult

        idem = idempotency_key(item, run_id)
        item_id = item.item_id

        if idem in self.seen_idempotency_keys:
            # Replay of the same upsert -> no duplicate, no version bump.
            stored = self.items[item_id]
            return UpsertResult(
                item.natural_key, item.kind, item_id=item_id, etag=str(stored.version)
            )

        created = item_id not in self.items
        env_id = item.environment_id or ""

        if created:
            active_in_kind = sum(
                1
                for s in self.items.values()
                if s.kind is item.kind and s.state == "Active"
            )
            if active_in_kind >= self.caps.max_items_per_tenant_and_kind:
                raise InventoryApiError(
                    f"{item.kind.discriminator}: tenant is at the per-kind row cap "
                    f"({self.caps.max_items_per_tenant_and_kind}); create refused"
                )
            stored = StoredItem(
                kind=item.kind,
                natural_key=item.natural_key,
                attributes=dict(item.attributes),
                environment_id=env_id,
                display_name=item.display_name,
                description=item.description,
                updated_at=self.clock(),
            )
        else:
            stored = self.items[item_id]
            if if_match is not None and if_match != str(stored.version):
                raise PreconditionFailedError(item.natural_key)
            stored.attributes = dict(item.attributes)  # overwrite in place (idempotent)
            stored.environment_id = env_id
            stored.display_name = item.display_name
            stored.description = item.description
            stored.version += 1
            stored.updated_at = self.clock()
            if stored.source == "Discovered":
                stored.state = "Active"  # re-asserting revives a retired row

        self.items[item_id] = stored
        self.seen_idempotency_keys[idem] = stored.version
        return UpsertResult(
            item.natural_key,
            item.kind,
            item_id=item_id,
            etag=str(stored.version),
            created=created,
        )

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

    def retire(self, item_id: str, *, if_match: str | None = None) -> None:
        stored = self.items.get(item_id)
        if stored is None:
            return  # idempotent: nothing to retire
        if if_match is not None and if_match != str(stored.version):
            raise PreconditionFailedError(stored.natural_key)
        if stored.state == "Retired":
            return
        stored.state = "Retired"
        stored.version += 1
        stored.updated_at = self.clock()

    def reconcile(
        self, kind: Kind, environment_id: str, pass_started_at: datetime
    ) -> ReconcileResult:
        if kind.is_tenant_root:
            raise InventoryApiError(
                f"{kind.discriminator} is tenant-rooted and cannot be reconciled; "
                "retire drift explicitly instead"
            )
        if not environment_id:
            raise InventoryApiError("environmentId is required to reconcile")
        if pass_started_at.tzinfo is None:
            pass_started_at = pass_started_at.replace(tzinfo=timezone.utc)
        if pass_started_at > self.clock():
            raise InventoryApiError("passStartedAt cannot be in the future")

        evaluated = 0
        retired_ids: list[str] = []
        for stored in self.items.values():
            if stored.kind is not kind or stored.environment_id != environment_id:
                continue
            if stored.source != "Discovered" or stored.state != "Active":
                continue
            evaluated += 1
            if stored.updated_at < pass_started_at:
                stored.state = "Retired"
                stored.version += 1
                stored.updated_at = self.clock()
                retired_ids.append(stored.item_id)

        return ReconcileResult(
            kind=kind,
            environment_id=environment_id,
            evaluated_count=evaluated,
            retired_count=len(retired_ids),
            retired_item_ids=retired_ids,
        )

    # -- test helpers ---------------------------------------------------------------

    def active_items(self) -> list[StoredItem]:
        return [s for s in self.items.values() if s.state == "Active"]

    def get(self, kind: Kind, natural_key: str) -> StoredItem | None:
        return self.items.get(encode_item_id(kind, natural_key))
