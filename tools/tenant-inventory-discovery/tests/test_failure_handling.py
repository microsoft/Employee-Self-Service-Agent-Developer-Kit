"""§10: completeness invariant -- what a partial crawl or a crash is allowed to do.

The whole-inventory contract inverted this file's stakes. Under reconcile, a scope that
failed to enumerate simply contributed no delete ids, and the worst case was stale
data. Under sync, a scope that failed to enumerate contributes *absences*, and absences
delete -- so the same failure that used to be harmless is now the one that can empty a
tenant.

The invariant these tests hold is therefore stronger than "don't retire the broken
scope". It is: **a run may only ever remove something it actually looked at and found
gone.** Everything else must survive, whether it went missing because a token expired,
a page failed, or the process died halfway through.
"""

from __future__ import annotations

import pytest

from conftest import ENV_A, build_platform
from tenant_inventory_discovery.config import DiscoveryConfig
from tenant_inventory_discovery.discovery_skill import DiscoverySkill
from tenant_inventory_discovery.errors import PlatformError
from tenant_inventory_discovery.models import Kind
from tenant_inventory_discovery.runner import DiscoveryRunner


class TestAFailedScopeIsMarkedIncomplete:
    def test_the_failure_is_recorded_not_swallowed(self, platform, inventory):
        platform.fail_on = {"list_connections"}
        summary = DiscoveryRunner(platform, inventory, DiscoveryConfig()).run()

        conn_reports = [s for s in summary.scopes if s.scope.kind is Kind.CONNECTION]
        assert conn_reports
        assert all(not r.complete and r.error for r in conn_reports)

    def test_healthy_scopes_are_unaffected(self, platform, inventory):
        platform.fail_on = {"list_connections"}
        summary = DiscoveryRunner(platform, inventory, DiscoveryConfig()).run()

        completed = {s.kind for s in summary.completed_scopes}
        assert Kind.CONNECTION not in completed
        assert Kind.EXTENSION_PACK in completed

    def test_a_failed_scope_never_becomes_authoritative(self, platform, inventory):
        """Authority is the licence to delete. A scope that errored has not earned it."""
        platform.fail_on = {"list_connections"}
        summary = DiscoveryRunner(platform, inventory, DiscoveryConfig()).run()

        for report in summary.scopes:
            if report.scope.kind is Kind.CONNECTION:
                assert not report.authoritative


class TestAPartialCrawlPreservesData:
    def test_a_failed_scopes_rows_survive(self, inventory):
        DiscoverySkill(build_platform(), inventory).discover("t1")

        broken = build_platform()
        broken.fail_on = {"list_connections"}
        DiscoverySkill(broken, inventory).discover("t1")

        assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c-1").state == "Active"

    def test_the_run_still_completes(self, inventory):
        """One broken kind is not a reason to abandon the other seven."""
        DiscoverySkill(build_platform(), inventory).discover("t1")

        broken = build_platform()
        broken.fail_on = {"list_connections"}
        summary = DiscoverySkill(broken, inventory).discover("t1")

        assert not summary.aborted
        assert summary.synced_ok

    def test_a_mid_enumeration_failure_still_preserves_the_kind(self, inventory):
        """Failing on page two is the nastiest case: some rows were seen, not all."""
        DiscoverySkill(build_platform(), inventory).discover("t1")

        broken = build_platform()
        calls = {"n": 0}
        original = broken.list_connections

        def flaky(env_id, page_size):
            for page in original(env_id, page_size):
                calls["n"] += 1
                yield page
                raise PlatformError("token expired mid-page")

        broken.list_connections = flaky
        DiscoverySkill(broken, inventory).discover("t1")

        assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c-1").state == "Active"


class TestACrashWritesNothing:
    def test_a_crash_during_the_crawl_never_reaches_the_sync(self, inventory):
        platform = build_platform()

        def explode(_page_size):
            raise RuntimeError("boom")

        platform.list_environments = explode  # type: ignore[assignment]

        with pytest.raises(RuntimeError):
            DiscoverySkill(platform, inventory).discover("t1")

        assert inventory.sync_calls == 0

    def test_a_crash_leaves_prior_rows_untouched(self, inventory):
        DiscoverySkill(build_platform(), inventory).discover("t1")
        before = inventory.active_keys()

        platform = build_platform()

        def explode(_page_size):
            raise RuntimeError("boom")

        platform.list_environments = explode  # type: ignore[assignment]

        with pytest.raises(RuntimeError):
            DiscoverySkill(platform, inventory).discover("t1")

        assert inventory.active_keys() == before


class TestATotallyFailedCrawlWritesNothing:
    """Every kind failed. The payload would be empty, and empty means "delete all"."""

    def _dead_platform(self):
        from tenant_inventory_discovery.platform_clients import FakePlatform

        return FakePlatform(
            fail_on={
                "list_environments",
                "list_entra_apps",
                "list_connectors",
                "list_sharepoint_sites",
            }
        )

    def test_no_scope_completes(self, inventory):
        summary = DiscoverySkill(self._dead_platform(), inventory).discover("t1")
        assert summary.completed_scopes == []

    def test_the_sync_is_withheld(self, inventory):
        summary = DiscoverySkill(self._dead_platform(), inventory).discover("t1")

        assert inventory.sync_calls == 0
        assert summary.sync_blocked_reason

    def test_an_existing_inventory_is_not_wiped(self, inventory):
        DiscoverySkill(build_platform(), inventory).discover("t1")
        before = inventory.active_keys()

        DiscoverySkill(self._dead_platform(), inventory).discover("t1")

        assert inventory.active_keys() == before
