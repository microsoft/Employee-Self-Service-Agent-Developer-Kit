"""§10: carry-forward -- how a deliberately narrow crawl stays safe under sync.

The ESS kit crawls **one** environment, the one bound during ``/setup``. Under the
whole-inventory contract that is a loaded gun: a payload describing one environment,
submitted as if it were the tenant, retires every other environment in the tenant.

The fix is not to refuse to sync -- that would mean the kit could never write at all.
It is to *complete the payload*: read the current inventory first and re-send, verbatim,
every Active row this run cannot vouch for. A scope the crawl did not cover contributes
its existing rows rather than an absence, so "I didn't look there" costs nothing.

Which scopes a run may vouch for is a per-kind question, and the answer is not
``Kind.is_tenant_root``. That flag says where a row is *filed*; it says nothing about
how much the crawler *looked at*. In the kit only ``EntraApp`` is genuinely
tenant-wide (a Graph ``/applications`` query); ``Environment``, ``Connector`` and
``SharePointSite`` are all derived from the single configured environment despite being
filed at the tenant root. Conflating the two is precisely the bug that would delete a
tenant's inventory, so it is pinned here.
"""

from __future__ import annotations

from conftest import ENV_A, ENV_B, build_platform
from spies import SpyInventoryClient
from tenant_inventory_discovery.discovery_skill import DiscoverySkill
from tenant_inventory_discovery.errors import InventoryApiError
from tenant_inventory_discovery.in_memory_inventory import StoredItem
from tenant_inventory_discovery.models import Kind


def _kit_shaped(platform):
    """A platform with the kit's real coverage: only EntraApp is tenant-wide."""
    platform.tenant_wide = {Kind.ENTRA_APP}
    return platform


def _seed_both_environments(inventory: SpyInventoryClient) -> None:
    """A tenant recorded by an earlier, wider pass over ENV_A and ENV_B."""
    DiscoverySkill(build_platform(), inventory).discover("t1")


def _narrow_run(inventory: SpyInventoryClient, **kw):
    """A kit-shaped crawl that only visits ENV_A."""
    platform = _kit_shaped(build_platform())
    for attr, value in kw.items():
        setattr(platform, attr, value)
    return DiscoverySkill(platform, inventory).discover("t1", environment_ids=[ENV_A])


# -- the headline property -----------------------------------------------------------


class TestAnUnvisitedEnvironmentSurvives:
    def test_rows_in_an_environment_the_run_never_opened_are_kept(self, inventory):
        _seed_both_environments(inventory)
        assert inventory.get(Kind.CONNECTION, f"{ENV_B}:c-1").state == "Active"

        _narrow_run(inventory)

        assert inventory.get(Kind.CONNECTION, f"{ENV_B}:c-1").state == "Active"

    def test_those_rows_are_in_the_payload_not_merely_spared(self, inventory):
        """Survival must come from being *mentioned*; there is no other mechanism."""
        _seed_both_environments(inventory)
        summary = _narrow_run(inventory)

        assert f"Connection:{ENV_B}:c-1" in inventory.submitted_keys()
        assert summary.carried_forward > 0

    def test_the_environment_row_itself_survives(self, inventory):
        _seed_both_environments(inventory)
        _narrow_run(inventory)
        assert inventory.get(Kind.ENVIRONMENT, ENV_B).state == "Active"

    def test_a_narrow_run_retires_nothing_it_did_not_look_at(self, inventory):
        _seed_both_environments(inventory)
        before = inventory.active_keys()

        summary = _narrow_run(inventory)

        assert sum(summary.retired_counts.values()) == 0
        assert inventory.active_keys() == before


# -- the other half: coverage must still buy deletion --------------------------------


class TestCoveredScopesStillRetire:
    """Carry-forward must not become "never delete anything"."""

    def test_the_crawled_environment_still_self_maintains(self, inventory):
        _seed_both_environments(inventory)
        _narrow_run(inventory, connections={ENV_B: build_platform().connections[ENV_B]})

        # ENV_A's connection is gone from the platform and ENV_A *was* crawled.
        assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c-1").state == "Retired"
        assert inventory.get(Kind.CONNECTION, f"{ENV_B}:c-1").state == "Active"

    def test_a_genuinely_tenant_wide_kind_still_retires(self, inventory):
        """EntraApp is read from Graph across the whole tenant, so absence is real."""
        _seed_both_environments(inventory)
        _narrow_run(inventory, entra_apps=[])

        assert inventory.get(Kind.ENTRA_APP, "app-1").state == "Retired"

    def test_a_tenant_root_kind_that_is_not_tenant_wide_does_not_retire(
        self, inventory
    ):
        """Connector is filed at the tenant root but derived from one environment.

        Its absence means "this environment stopped using it", never "the tenant
        stopped having it" -- so it must be carried forward, not swept.
        """
        _seed_both_environments(inventory)
        _narrow_run(inventory, connectors=[])

        assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Active"

    def test_a_fully_covered_platform_retires_across_every_kind(self, inventory):
        """With no coverage gaps there is nothing to carry, and sweeping is normal."""
        _seed_both_environments(inventory)
        wide = build_platform()  # tenant_wide=None -> claims all tenant-root kinds
        wide.connectors = []
        summary = DiscoverySkill(wide, inventory).discover("t1")

        assert summary.carried_forward == 0
        assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Retired"


# -- a scope that failed is a scope that cannot vouch --------------------------------


class TestAFailedScopeCarriesForwardInstead:
    def test_an_enumeration_failure_retires_nothing_of_that_kind(self, inventory):
        _seed_both_environments(inventory)
        before = inventory.active_keys()

        platform = build_platform()
        platform.fail_on = {"list_entra_apps"}
        summary = DiscoverySkill(platform, inventory).discover("t1")

        assert inventory.get(Kind.ENTRA_APP, "app-1").state == "Active"
        assert inventory.active_keys() == before
        assert any(r.error for r in summary.scopes if r.scope.kind is Kind.ENTRA_APP)

    def test_the_run_still_syncs_the_kinds_that_did_work(self, inventory):
        """A partial crawl is no longer a reason to abandon the whole pass."""
        _seed_both_environments(inventory)
        platform = build_platform()
        platform.fail_on = {"list_entra_apps"}
        platform.connectors = []
        summary = DiscoverySkill(platform, inventory).discover("t1")

        assert summary.synced is not None
        assert not summary.sync_blocked_reason
        # Connector enumerated cleanly, so its absence is still trusted.
        assert inventory.get(Kind.CONNECTOR, "conn-catalog-1").state == "Retired"

    def test_a_failed_scope_is_not_authoritative(self, inventory):
        platform = build_platform()
        platform.fail_on = {"list_entra_apps"}
        summary = DiscoverySkill(platform, inventory).discover("t1")

        failed = next(r for r in summary.scopes if r.scope.kind is Kind.ENTRA_APP)
        assert not failed.authoritative
        assert failed.scope not in summary.authoritative_scopes


# -- if the tenant's current state cannot be read, do not guess ----------------------


class TestAnUnreadableInventoryWithholdsTheSync:
    """Carry-forward needs the current rows. Without them the payload is a guess."""

    class _Unreadable:
        def __init__(self):
            self.sync_calls = 0

        def list_items(self, **_kw):
            raise InventoryApiError("GET failed")

        def sync_inventory(self, items, *, run_id=""):  # pragma: no cover - guard
            self.sync_calls += 1
            raise AssertionError("sync must not be attempted")

    def test_nothing_is_submitted(self, platform):
        inventory = self._Unreadable()
        summary = DiscoverySkill(platform, inventory).discover("t1")

        assert inventory.sync_calls == 0
        assert summary.synced is None

    def test_the_reason_names_the_read_failure(self, platform):
        summary = DiscoverySkill(platform, self._Unreadable()).discover("t1")
        assert "could not be read" in summary.sync_blocked_reason

    def test_the_run_is_not_an_abort(self, platform):
        """The crawl succeeded; only the write was withheld. Those differ."""
        summary = DiscoverySkill(platform, self._Unreadable()).discover("t1")
        assert not summary.aborted


class TestAnUnknownKindWithholdsTheSync:
    """A row this build cannot represent is a row it cannot promise to preserve."""

    def test_a_newer_services_kind_blocks_the_write(self, platform, inventory):
        inventory.items["Sasquatch:s-1"] = StoredItem(
            kind=Kind.CONNECTOR,  # placeholder; the wire row below is what matters
            natural_key="s-1",
            attributes={},
            environment_id="",
        )
        # Force the wire shape to advertise a kind the enum does not know.
        original = inventory.list_items

        def spoofed(**kw):
            rows = original(**kw)
            for row in rows:
                row["kind"] = "Sasquatch"
            return rows

        inventory.list_items = spoofed
        summary = DiscoverySkill(platform, inventory).discover("t1")

        assert inventory.sync_calls == 0
        assert "unrecognized kind" in summary.sync_blocked_reason


# -- caps: the payload can outgrow the request ---------------------------------------


class TestCapContention:
    """When a kind overflows, the carried rows win and the observed rows wait.

    That looks backwards -- the observed rows are fresher -- but only one direction is
    destructive. Dropping a carried row *retires* a resource that exists; dropping an
    observed row merely defers recording it until the next pass. The service holds at
    most ``cap`` rows per kind, so the carried set alone can never overflow.
    """

    def test_carried_rows_are_never_dropped_to_make_room(self, inventory):
        cap = 50
        for n in range(cap):
            inventory.items[f"Connector:old-{n:03d}"] = StoredItem(
                kind=Kind.CONNECTOR,
                natural_key=f"old-{n:03d}",
                attributes={},
                environment_id="",
            )
        # A narrow run that observes a brand-new connector: the kind is already full.
        _narrow_run(inventory)

        submitted = {
            i.natural_key for i in inventory.last_payload if i.kind is Kind.CONNECTOR
        }
        assert len(submitted) == cap
        assert all(f"old-{n:03d}" in submitted for n in range(cap))

    def test_no_pre_existing_row_is_retired_by_the_overflow(self, inventory):
        cap = 50
        for n in range(cap):
            inventory.items[f"Connector:old-{n:03d}"] = StoredItem(
                kind=Kind.CONNECTOR,
                natural_key=f"old-{n:03d}",
                attributes={},
                environment_id="",
            )
        _narrow_run(inventory)

        assert all(
            inventory.get(Kind.CONNECTOR, f"old-{n:03d}").state == "Active"
            for n in range(cap)
        )
