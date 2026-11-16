"""§10: syncInventory idempotency-key replay + idempotent re-run."""

from __future__ import annotations

from tenant_inventory_discovery.mapping import map_resource, sync_idempotency_key
from tenant_inventory_discovery.models import Kind


def _env(env_id: str):
    return map_resource(Kind.ENVIRONMENT, {"environmentId": env_id, "region": "us"})


def _connector(connector_id: str, *, tier: str = "standard"):
    return map_resource(
        Kind.CONNECTOR,
        {"connectorId": connector_id, "displayName": "SN", "tier": tier},
    )


def test_sync_idempotency_key_stable_for_same_payload_within_a_run():
    items = [_env("e1"), _connector("c1")]
    assert sync_idempotency_key(items, "run-1") == sync_idempotency_key(items, "run-1")


def test_sync_idempotency_key_ignores_payload_order():
    """The service treats the payload as a set, so harmless ordering cannot fork keys."""
    items = [_env("e1"), _connector("c1")]
    assert sync_idempotency_key(items, "run-1") == sync_idempotency_key(
        list(reversed(items)), "run-1"
    )


def test_sync_idempotency_key_differs_across_items_and_attrs():
    a = [_connector("c1", tier="standard")]
    b = [_connector("c2", tier="standard")]
    assert sync_idempotency_key(a, "run-1") != sync_idempotency_key(b, "run-1")

    changed = [_connector("c1", tier="premium")]
    assert sync_idempotency_key(a, "run-1") != sync_idempotency_key(changed, "run-1")


def test_sync_idempotency_key_differs_across_runs():
    """An unchanged tenant still needs a fresh write pass after the cache starts."""
    items = [_connector("c1")]
    assert sync_idempotency_key(items, "run-1") != sync_idempotency_key(items, "run-2")


def test_replayed_sync_returns_the_original_response(inventory):
    payload = [_connector("c1")]
    first = inventory.sync_inventory(payload, run_id="run-1")
    again = inventory.sync_inventory(payload, run_id="run-1")

    assert inventory.sync_calls == 2
    assert again is first
    assert len(inventory.replayed_syncs) == 1
    assert inventory.get(Kind.CONNECTOR, "c1").version == 1


def test_next_run_reasserts_unchanged_item(inventory):
    """A new pass writes through rather than replaying the previous pass."""
    payload = [_connector("c1")]
    inventory.sync_inventory(payload, run_id="run-1")
    first = inventory.get(Kind.CONNECTOR, "c1").updated_at

    inventory.sync_inventory(payload, run_id="run-2")
    stored = inventory.get(Kind.CONNECTOR, "c1")

    assert stored.version == 2
    assert stored.updated_at >= first
    assert len(inventory.replayed_syncs) == 2


def test_a_fresh_key_is_what_revives_a_retired_row(inventory):
    """Reusing a cached response would leave a legitimately reappeared row retired."""
    connector = _connector("c1")
    inventory.sync_inventory([connector], run_id="run-1")

    inventory.sync_inventory([_env("e1")], run_id="run-2")
    assert inventory.get(Kind.CONNECTOR, "c1").state == "Retired"

    inventory.sync_inventory([connector], run_id="run-1")
    assert inventory.get(Kind.CONNECTOR, "c1").state == "Retired"

    inventory.sync_inventory([connector], run_id="run-3")
    assert inventory.get(Kind.CONNECTOR, "c1").state == "Active"
