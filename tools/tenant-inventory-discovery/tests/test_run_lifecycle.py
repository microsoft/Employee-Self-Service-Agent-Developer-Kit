"""§10: run lifecycle -- what one pass does, and what it costs.

The shape of a run changed with the write contract. It used to be a crawl interleaved
with hundreds of per-item writes and a trailing sweep; it is now a crawl that builds a
payload, followed by exactly one request. The tests here pin that shape: every kind is
visited, the payload is assembled once, and a run that cannot describe the tenant
safely still terminates cleanly rather than half-writing.
"""

from __future__ import annotations

from conftest import ENV_A, ENV_B, build_platform
from tenant_inventory_discovery.config import DiscoveryConfig
from tenant_inventory_discovery.discovery_skill import DiscoverySkill
from tenant_inventory_discovery.models import Kind
from tenant_inventory_discovery.runner import DiscoveryRunner


def _runner(platform, inventory):
    return DiscoveryRunner(platform, inventory, DiscoveryConfig())


class TestTheCrawlCoversEverything:
    def test_all_eight_kinds_are_recorded(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        assert {s.kind for s in inventory.active_items()} == set(Kind)

    def test_a_completed_scope_reports_the_keys_it_observed(self, platform, inventory):
        summary = _runner(platform, inventory).run()
        env_report = next(s for s in summary.scopes if s.scope.kind is Kind.ENVIRONMENT)
        assert set(env_report.observed_keys) == {ENV_A, ENV_B}

    def test_every_crawled_scope_completes_on_a_healthy_tenant(
        self, platform, inventory
    ):
        summary = _runner(platform, inventory).run()
        completed = {s.kind for s in summary.completed_scopes}

        assert Kind.ENVIRONMENT in completed
        assert Kind.CONNECTION in completed
        assert not summary.aborted

    def test_the_same_key_in_two_environments_stays_two_rows(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c-1") is not None
        assert inventory.get(Kind.CONNECTION, f"{ENV_B}:c-1") is not None


class TestTheRunCostsOneWrite:
    """The per-item write loop is gone; so is the separate retire pass."""

    def test_a_whole_pass_is_a_single_request(self, platform, inventory):
        DiscoverySkill(platform, inventory).discover("t1")
        assert inventory.sync_calls == 1

    def test_the_inventory_is_read_once_to_build_the_payload(self, platform, inventory):
        """One GET for carry-forward, not one per scope as the old diff needed."""
        DiscoverySkill(platform, inventory).discover("t1")
        assert inventory.list_calls == 1

    def test_a_rerun_over_an_unchanged_tenant_skips_the_write(
        self, platform, inventory
    ):
        """The sync is the expensive call; a no-op one is worth not making.

        The payload is compared against the inventory already fetched for
        carry-forward, so proving the write redundant costs nothing extra. The run
        still reports success -- the server's state *is* the payload, which is exactly
        what a sync would have guaranteed.
        """
        DiscoverySkill(platform, inventory).discover("t1")
        summary = DiscoverySkill(build_platform(), inventory).discover("t1")

        assert inventory.sync_calls == 1  # only the first run had anything to say
        assert summary.sync_unchanged
        assert summary.synced_ok
        assert not summary.sync_blocked_reason
        assert sum(summary.retired_counts.values()) == 0

    def test_a_changed_tenant_still_writes(self, platform, inventory):
        """The skip must key off actual equality, not merely "we ran before"."""
        DiscoverySkill(platform, inventory).discover("t1")
        changed = build_platform()
        changed.connectors = []
        summary = DiscoverySkill(changed, inventory).discover("t1")

        assert inventory.sync_calls == 2
        assert not summary.sync_unchanged
        assert summary.synced is not None


class TestTheSummaryDescribesTheRun:
    def test_a_healthy_run_reports_success(self, platform, inventory):
        summary = DiscoverySkill(platform, inventory).discover("t1")

        assert summary.correlation_id
        assert not summary.aborted
        assert not summary.sync_blocked_reason
        assert summary.synced_ok

    def test_submitted_counts_match_the_payload(self, platform, inventory):
        summary = DiscoverySkill(platform, inventory).discover("t1")
        assert sum(summary.submitted_counts.values()) == len(summary.payload)

    def test_a_fully_covered_run_vouches_for_every_scope(self, platform, inventory):
        summary = DiscoverySkill(platform, inventory).discover("t1")
        assert set(summary.authoritative_scopes) == set(summary.completed_scopes)
