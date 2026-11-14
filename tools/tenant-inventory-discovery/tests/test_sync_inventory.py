"""§10: retire-on-absence -- the whole-inventory ``syncInventory`` contract.

The service no longer takes instructions about what to delete. It takes the tenant's
entire inventory and retires whatever the payload does not mention. That single change
inverts the failure direction of every bug in this file's subject area:

* Under the old reconcile design, a crawl that under-reported retired **too little** --
  drift lingered until the next pass.
* Under sync, a crawl that under-reports retires **too much** -- it deletes live
  resources it simply failed to mention.

There is no server-side guardrail (the service was asked for one and declined), so
every safety property is a client property, and these tests are where those properties
are pinned. The companion file ``test_carry_forward.py`` covers how a deliberately
narrow crawl stays safe; this file covers the sync primitive itself.
"""

from __future__ import annotations

import pytest

from conftest import ENV_A, ENV_B, build_platform
from spies import SpyInventoryClient
from tenant_inventory_discovery.discovery_skill import DiscoverySkill
from tenant_inventory_discovery.errors import InventoryApiError
from tenant_inventory_discovery.in_memory_inventory import StoredItem
from tenant_inventory_discovery.mapping import SyncPayloadError
from tenant_inventory_discovery.models import InventoryItem, Kind


def _store(inventory: SpyInventoryClient, item: StoredItem) -> None:
    inventory.items[item.item_id] = item


def _item(kind: Kind, natural_key: str, env: str = "") -> InventoryItem:
    return InventoryItem(
        kind=kind,
        natural_key=natural_key,
        attributes={},
        environment_id=env or None,
        display_name=natural_key,
    )


# -- absence is the delete verb ------------------------------------------------------


class TestAbsenceRetires:
    """The core semantic: what the payload omits, the service removes."""

    def test_a_resource_that_disappeared_is_retired_on_the_next_run(
        self, platform, inventory
    ):
        DiscoverySkill(platform, inventory).discover("t1")
        assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Active"

        # Second pass over a tenant where the connector is genuinely gone. It is simply
        # missing from the payload -- no delete call is made or needed.
        gone = build_platform()
        gone.connectors = []
        DiscoverySkill(gone, inventory).discover("t1")

        assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Retired"

    def test_retirement_is_reported_back_by_id(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        gone = build_platform()
        gone.connectors = []
        summary = DiscoverySkill(gone, inventory).discover("t1")

        assert summary.synced is not None
        assert summary.synced.retired_item_ids == ["Connector:conn-catalog-1"]
        assert summary.synced.retired_count == 1

    def test_an_unchanged_tenant_retires_nothing(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        summary = DiscoverySkill(build_platform(), inventory).discover("t1")

        # Asserts the outcome, not the mechanism: an unchanged tenant loses nothing
        # whether that is because the sync retired nothing or because it was skipped as
        # provably redundant.
        assert sum(summary.retired_counts.values()) == 0
        assert all(s.state == "Active" for s in inventory.items.values())

    def test_a_rerun_is_idempotent(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        first = dict(inventory.items)
        DiscoverySkill(build_platform(), inventory).discover("t1")

        assert set(inventory.items) == set(first)
        assert all(s.state == "Active" for s in inventory.items.values())

    def test_a_retired_row_revives_when_the_resource_comes_back(
        self, platform, inventory
    ):
        DiscoverySkill(platform, inventory).discover("t1")
        gone = build_platform()
        gone.connectors = []
        DiscoverySkill(gone, inventory).discover("t1")
        assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Retired"

        DiscoverySkill(build_platform(), inventory).discover("t1")
        assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Active"


class TestOneCallDoesEverything:
    """Upsert, retire and revive are one request now, not a loop plus a sweep."""

    def test_the_whole_run_costs_exactly_one_write(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        assert inventory.sync_calls == 1

    def test_every_kind_travels_in_the_same_payload(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        kinds = {i.kind for i in inventory.last_payload}
        assert kinds == set(Kind)

    def test_order_is_not_the_clients_problem(self, inventory):
        """A child may precede its environment; the service sorts internally."""
        payload = [
            _item(Kind.CONNECTION, f"{ENV_A}:c-1", ENV_A),
            _item(Kind.ENVIRONMENT, ENV_A),
        ]
        result = inventory.sync_inventory(payload)

        assert result.failed_items == []
        assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c-1").state == "Active"


# -- the guardrails that replaced the server's ------------------------------------


class TestAnEmptyPayloadIsRefused:
    """``{"items": []}`` is legal to the service and would wipe the tenant."""

    def test_a_crawl_that_found_nothing_is_never_submitted(self, inventory):
        empty = build_platform()
        empty.environments = []
        empty.entra_apps = []
        empty.connectors = []
        empty.sharepoint_sites = []
        empty.connections = {}
        empty.knowledge_sources = {}
        empty.extension_packs = {}
        empty.scenario_templates = {}

        summary = DiscoverySkill(empty, inventory).discover("t1")

        assert inventory.sync_calls == 0
        assert "empty payload" in summary.sync_blocked_reason
        assert summary.synced is None

    def test_nothing_already_recorded_is_touched(self, inventory):
        _store(
            inventory,
            StoredItem(
                kind=Kind.CONNECTOR,
                natural_key="keep-me",
                attributes={},
                environment_id="",
            ),
        )
        empty = build_platform()
        empty.environments = []
        empty.entra_apps = []
        empty.connectors = []
        empty.sharepoint_sites = []
        empty.connections = {}
        empty.knowledge_sources = {}
        empty.extension_packs = {}
        empty.scenario_templates = {}

        DiscoverySkill(empty, inventory).discover("t1")
        assert inventory.get(Kind.CONNECTOR, "keep-me").state == "Active"


class TestPayloadLimits:
    """Rejected client-side, before a doomed request reaches the wire."""

    def test_more_than_fifty_of_one_kind_is_refused(self, inventory):
        payload = [_item(Kind.ENVIRONMENT, f"env-{n:03d}") for n in range(51)]
        with pytest.raises(SyncPayloadError):
            inventory.sync_inventory(payload)

    def test_a_duplicate_natural_key_is_a_hard_reject(self, inventory):
        """The service does not take last-one-wins; it rejects the call."""
        payload = [_item(Kind.ENVIRONMENT, ENV_A), _item(Kind.ENVIRONMENT, ENV_A)]
        with pytest.raises(SyncPayloadError):
            inventory.sync_inventory(payload)

    def test_the_same_key_under_different_kinds_is_fine(self, inventory):
        """Identity is ``kind:naturalKey``, not the key alone."""
        payload = [_item(Kind.ENVIRONMENT, "shared"), _item(Kind.CONNECTOR, "shared")]
        assert inventory.sync_inventory(payload).failed_items == []

    def test_a_rejected_payload_writes_nothing(self, inventory):
        _store(
            inventory,
            StoredItem(
                kind=Kind.CONNECTOR,
                natural_key="survivor",
                attributes={},
                environment_id="",
            ),
        )
        with pytest.raises(SyncPayloadError):
            inventory.sync_inventory(
                [_item(Kind.ENVIRONMENT, ENV_A), _item(Kind.ENVIRONMENT, ENV_A)]
            )
        assert inventory.get(Kind.CONNECTOR, "survivor").state == "Active"


class TestPartialSuccess:
    """A 200 carrying ``failedItems`` means the rest applied."""

    def test_a_child_without_its_environment_is_reported_not_fatal(self, inventory):
        payload = [
            _item(Kind.ENVIRONMENT, ENV_A),
            _item(Kind.CONNECTION, f"{ENV_A}:c-1", ENV_A),
            _item(Kind.CONNECTION, f"{ENV_B}:c-9", ENV_B),  # ENV_B is absent
        ]
        result = inventory.sync_inventory(payload)

        assert result.failed_item_ids == ["Connection:env-bbbb%3Ac-9"]
        assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c-1").state == "Active"

    def test_a_failed_item_is_not_counted_as_upserted(self, inventory):
        payload = [
            _item(Kind.ENVIRONMENT, ENV_A),
            _item(Kind.CONNECTION, f"{ENV_B}:c-9", ENV_B),
        ]
        result = inventory.sync_inventory(payload)

        assert result.submitted_count == 2
        assert result.upserted_count == 1


class TestManualRowsAreLeftAlone:
    """A hand-authored row is a deliberate act, not drift the crawler may sweep."""

    def test_absence_does_not_retire_a_manual_row(self, platform, inventory):
        _store(
            inventory,
            StoredItem(
                kind=Kind.CONNECTOR,
                natural_key="manual-1",
                attributes={"connectorId": "manual-1"},
                environment_id="",
                source="Manual",
            ),
        )
        DiscoverySkill(platform, inventory).discover("t1")
        assert inventory.get(Kind.CONNECTOR, "manual-1").state == "Active"


class TestIdempotencyKey:
    """A timed-out retry must not re-run ~400 writes."""

    def test_replaying_a_run_returns_the_original_response(self, inventory):
        payload = [_item(Kind.ENVIRONMENT, ENV_A)]
        first = inventory.sync_inventory(payload, run_id="run-1")
        again = inventory.sync_inventory(payload, run_id="run-1")

        assert again is first  # the cached response, retiredItemIds and all

    def test_a_different_run_is_not_a_replay(self, inventory):
        """The key covers the payload *and* the run: absences differ between passes."""
        payload = [_item(Kind.ENVIRONMENT, ENV_A)]
        first = inventory.sync_inventory(payload, run_id="run-1")
        other = inventory.sync_inventory(payload, run_id="run-2")

        assert other is not first


# -- skipping a provably redundant sync ----------------------------------------------


class TestTheRedundantSyncIsSkipped:
    """The sync is the run's expensive call. Not making it needs to be safe.

    The dangerous direction is asymmetric. Sending a redundant payload wastes minutes;
    skipping a *needed* one silently leaves the tenant wrong, and the next run compares
    against that same wrong state and skips again. So every test here is about the
    second kind of mistake.
    """

    def test_nothing_changed_means_nothing_is_sent(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        summary = DiscoverySkill(build_platform(), inventory).discover("t1")

        assert summary.sync_unchanged
        assert inventory.sync_calls == 1

    def test_a_new_resource_is_never_skipped(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        grown = build_platform()
        grown.connectors = [
            *grown.connectors,
            {"connectorId": "conn-new", "displayName": "New", "tier": "Standard"},
        ]
        summary = DiscoverySkill(grown, inventory).discover("t1")

        assert not summary.sync_unchanged
        assert inventory.get(Kind.CONNECTOR, "conn-new").state == "Active"

    def test_a_removed_resource_is_never_skipped(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        shrunk = build_platform()
        shrunk.connectors = []
        summary = DiscoverySkill(shrunk, inventory).discover("t1")

        assert not summary.sync_unchanged
        assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Retired"

    def test_an_edited_field_is_never_skipped(self, platform, inventory):
        """Same keys, different content: the set matching is not enough."""
        DiscoverySkill(platform, inventory).discover("t1")
        renamed = build_platform()
        renamed.connectors[0] = {
            **renamed.connectors[0],
            "displayName": "Renamed In Place",
        }
        summary = DiscoverySkill(renamed, inventory).discover("t1")

        assert not summary.sync_unchanged
        assert inventory.sync_calls == 2

    def test_a_retired_row_coming_back_is_never_skipped(self, platform, inventory):
        """A revival looks like "unchanged" only if Retired rows are miscounted."""
        DiscoverySkill(platform, inventory).discover("t1")
        gone = build_platform()
        gone.connectors = []
        DiscoverySkill(gone, inventory).discover("t1")
        summary = DiscoverySkill(build_platform(), inventory).discover("t1")

        assert not summary.sync_unchanged
        assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Active"

    def test_an_unreadable_inventory_never_skips(self, platform, inventory):
        """No "before" picture means no basis to call the write redundant."""
        DiscoverySkill(platform, inventory).discover("t1")

        def _boom(**_kw):
            raise InventoryApiError("GET failed")

        inventory.list_items = _boom
        summary = DiscoverySkill(build_platform(), inventory).discover("t1")

        # Withheld, not skipped -- and the two must not be confused: one is a safety
        # stop, the other is an optimization.
        assert not summary.sync_unchanged
        assert summary.sync_blocked_reason

    def test_a_skipped_run_still_counts_as_synced(self, platform, inventory):
        """The mirror refreshes off synced_ok, and refreshing is correct here.

        The server's state *is* the payload -- which is the exact guarantee a real
        sync provides -- so treating the run as unsynced would strand the local mirror
        on a stale picture for no reason.
        """
        DiscoverySkill(platform, inventory).discover("t1")
        summary = DiscoverySkill(build_platform(), inventory).discover("t1")

        assert summary.synced_ok
        assert summary.synced is None