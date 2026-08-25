"""§10: retire-on-drift -- watermark reconcile, local sweep, and the exemptions.

The service splits drift handling in two, and these tests pin both halves:

- **Env-scoped kinds** go through the server's ``reconcile`` action, which retires
  rows whose ``UpdatedAt`` predates the pass watermark.
- **Tenant-rooted kinds** are rejected by that action, so the skill lists, diffs
  against the keys it observed, and DELETEs the remainder.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import ENV_A, build_platform
from spies import SpyInventoryClient
from tenant_inventory_discovery.discovery_skill import DiscoverySkill
from tenant_inventory_discovery.errors import InventoryApiError
from tenant_inventory_discovery.in_memory_inventory import StoredItem
from tenant_inventory_discovery.mapping import map_resource
from tenant_inventory_discovery.models import Kind, encode_item_id


def _store(inventory: SpyInventoryClient, item: StoredItem) -> None:
    inventory.items[item.item_id] = item


# -- tenant-rooted kinds: client-side list/diff/DELETE sweep ------------------------


def test_removed_tenant_root_resource_is_retired_after_next_run(platform, inventory):
    skill = DiscoverySkill(platform, inventory)
    skill.discover("t1")
    assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Active"

    # Second run over a tenant where the connector disappeared.
    platform2 = build_platform()
    platform2.connectors = []
    DiscoverySkill(platform2, inventory).discover("t1")

    stored = inventory.get(Kind.CONNECTOR, "conn-catalog-1")
    assert stored.state == "Retired"  # listed but not observed -> swept (spec §6.3)


def test_manual_item_never_retired(platform, inventory):
    """A hand-authored row is a deliberate act, not drift."""
    _store(
        inventory,
        StoredItem(
            kind=Kind.CONNECTOR,
            natural_key="manual-1",
            attributes={"connectorId": "manual-1", "displayName": "Hand-made"},
            environment_id="",
            source="Manual",
        ),
    )
    DiscoverySkill(platform, inventory).discover("t1")
    assert inventory.get(Kind.CONNECTOR, "manual-1").state == "Active"  # exempt (§6.3)


def test_partial_env_run_does_not_retire_tenant_root(inventory):
    # First: full crawl records everything.
    DiscoverySkill(build_platform(), inventory).discover("t1")

    # Then: a subset run touching only ENV_A. Tenant-root kinds must NOT be swept even
    # though they were enumerated (tenant-root exemption, spec §6.3).
    summary = DiscoverySkill(build_platform(), inventory).discover(
        "t1", environment_ids=[ENV_A]
    )

    completed_kinds = {s.kind for s in summary.completed_scopes}
    assert Kind.CONNECTOR not in completed_kinds
    assert Kind.ENVIRONMENT not in completed_kinds
    # The connector row stays Active (never swept by the subset run).
    assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Active"


def test_idempotent_rerun_leaves_everything_active(inventory):
    DiscoverySkill(build_platform(), inventory).discover("t1")
    keys = set(inventory.items)

    DiscoverySkill(build_platform(), inventory).discover("t1")
    assert set(inventory.items) == keys  # unchanged tenant -> no new rows
    assert all(v.state == "Active" for v in inventory.items.values())


# -- env-scoped kinds: server watermark reconcile -----------------------------------


def test_reconcile_retires_rows_older_than_the_watermark(inventory):
    """A row not re-asserted this pass keeps a stale UpdatedAt and is retired."""
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    _store(
        inventory,
        StoredItem(
            kind=Kind.CONNECTION,
            natural_key=f"{ENV_A}:gone",
            attributes={"environmentId": ENV_A, "connectionId": "gone"},
            environment_id=ENV_A,
            updated_at=old,
        ),
    )

    result = inventory.reconcile(
        Kind.CONNECTION, ENV_A, datetime.now(timezone.utc) - timedelta(minutes=5)
    )

    assert result.retired_count == 1
    assert result.retired_item_ids == [encode_item_id(Kind.CONNECTION, f"{ENV_A}:gone")]
    assert inventory.get(Kind.CONNECTION, f"{ENV_A}:gone").state == "Retired"


def test_reconcile_spares_rows_written_during_the_pass(inventory):
    watermark = datetime.now(timezone.utc) - timedelta(minutes=5)
    item = map_resource(
        Kind.CONNECTION, {"environmentId": ENV_A, "connectionId": "live"}
    )
    inventory.upsert(item, run_id="run-1")  # stamped now, i.e. after the watermark

    result = inventory.reconcile(Kind.CONNECTION, ENV_A, watermark)

    assert result.evaluated_count == 1
    assert result.retired_count == 0
    assert inventory.get(Kind.CONNECTION, f"{ENV_A}:live").state == "Active"


def test_reconcile_is_scoped_to_one_environment(inventory):
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    for env in (ENV_A, "env-other"):
        _store(
            inventory,
            StoredItem(
                kind=Kind.CONNECTION,
                natural_key=f"{env}:c",
                attributes={"environmentId": env, "connectionId": "c"},
                environment_id=env,
                updated_at=old,
            ),
        )

    inventory.reconcile(
        Kind.CONNECTION, ENV_A, datetime.now(timezone.utc) - timedelta(minutes=5)
    )

    assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c").state == "Retired"
    assert inventory.get(Kind.CONNECTION, "env-other:c").state == "Active"


def test_reconcile_rejects_tenant_root_kinds(inventory):
    """A tenant-wide crawl has no provable completeness boundary, so the API says no."""
    with pytest.raises(InventoryApiError):
        inventory.reconcile(
            Kind.CONNECTOR, "", datetime.now(timezone.utc) - timedelta(minutes=5)
        )


def test_reconcile_rejects_a_future_watermark(inventory):
    with pytest.raises(InventoryApiError):
        inventory.reconcile(
            Kind.CONNECTION, ENV_A, datetime.now(timezone.utc) + timedelta(hours=1)
        )


def test_full_run_retires_env_scoped_drift(inventory):
    """End-to-end: a connection that disappears is retired by the next pass."""
    platform = build_platform()
    platform.connections[ENV_A] = [
        {"environmentId": ENV_A, "connectionId": "c-1", "connectorId": "conn-catalog-1"},
        {"environmentId": ENV_A, "connectionId": "c-2", "connectorId": "conn-catalog-1"},
    ]
    DiscoverySkill(platform, inventory).discover("t1")
    assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c-2").state == "Active"

    # Rewind the surviving rows so the next pass's watermark is meaningful without
    # sleeping: only rows the second pass re-asserts will move forward again.
    for stored in inventory.items.values():
        stored.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)

    platform2 = build_platform()  # c-2 is gone
    DiscoverySkill(platform2, inventory).discover("t1")

    assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c-2").state == "Retired"
    assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c-1").state == "Active"


def test_capped_scope_is_never_reconciled(inventory):
    """A truncated view must not be treated as authoritative."""
    from tenant_inventory_discovery.config import DiscoveryConfig
    from tenant_inventory_discovery.schemas import AttributeCaps

    platform = build_platform()
    platform.connections[ENV_A] = [
        {"environmentId": ENV_A, "connectionId": f"c-{i}"} for i in range(5)
    ]
    config = DiscoveryConfig(caps=AttributeCaps(max_items_per_tenant_and_kind=2))

    summary = DiscoverySkill(platform, inventory, config=config).discover("t1")

    conn_report = next(s for s in summary.scopes if s.scope.kind is Kind.CONNECTION)
    assert conn_report.capped
    assert not conn_report.complete
    assert conn_report.scope not in summary.completed_scopes
