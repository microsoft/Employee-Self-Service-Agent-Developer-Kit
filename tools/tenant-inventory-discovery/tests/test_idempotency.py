"""§10: idempotency-key replay + idempotent re-run."""

from __future__ import annotations

from tenant_inventory_discovery.mapping import idempotency_key, map_resource
from tenant_inventory_discovery.models import Kind


def test_idempotency_key_stable_for_same_item_within_a_run():
    item = map_resource(Kind.ENVIRONMENT, {"environmentId": "e1", "region": "us"})
    assert idempotency_key(item, "run-1") == idempotency_key(item, "run-1")


def test_idempotency_key_differs_across_items_and_attrs():
    a = map_resource(Kind.ENVIRONMENT, {"environmentId": "e1", "region": "us"})
    b = map_resource(Kind.ENVIRONMENT, {"environmentId": "e2", "region": "us"})
    # Different natural key -> different key.
    assert idempotency_key(a, "run-1") != idempotency_key(b, "run-1")
    # Same natural key, changed attributes -> different key (so a changed resource is
    # re-applied rather than deduped as a replay).
    a2 = map_resource(Kind.ENVIRONMENT, {"environmentId": "e1", "region": "eu"})
    assert idempotency_key(a, "run-1") != idempotency_key(a2, "run-1")


def test_idempotency_key_differs_across_runs():
    """An unchanged resource must still get a fresh key on the next pass.

    Reconcile retires rows whose UpdatedAt predates the pass watermark. If a later
    pass reused the key, the service would replay the cached response inside its 24h
    window, the row's UpdatedAt would stay put, and a live resource would be retired.
    """
    item = map_resource(Kind.ENVIRONMENT, {"environmentId": "e1", "region": "us"})
    assert idempotency_key(item, "run-1") != idempotency_key(item, "run-2")


def test_replay_does_not_duplicate(inventory):
    item = map_resource(Kind.CONNECTOR, {"connectorId": "c1", "displayName": "SN"})
    inventory.upsert(item, run_id="run-1")
    inventory.upsert(item, run_id="run-1")  # retried upsert, same idempotency key
    assert inventory.upsert_calls == 2
    stored = inventory.get(Kind.CONNECTOR, "c1")
    assert stored is not None
    assert stored.version == 1  # no version bump on replay -> no duplicate write


def test_next_run_reasserts_unchanged_item(inventory):
    """A new pass writes through, advancing UpdatedAt past the next watermark."""
    item = map_resource(Kind.CONNECTOR, {"connectorId": "c1", "displayName": "SN"})
    inventory.upsert(item, run_id="run-1")
    first = inventory.get(Kind.CONNECTOR, "c1").updated_at

    inventory.upsert(item, run_id="run-2")
    stored = inventory.get(Kind.CONNECTOR, "c1")
    assert stored.version == 2
    assert stored.updated_at >= first
