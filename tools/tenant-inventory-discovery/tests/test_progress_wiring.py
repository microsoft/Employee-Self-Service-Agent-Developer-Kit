"""Tests that a real crawl actually emits progress events.

``test_progress.py`` pins how a reporter behaves once it is called. These pin the
other half: that the run engine calls it at all, at the right moments, for a normal
crawl. Without this the narration silently stops the next time someone refactors the
crawl loop, and ``/discover`` goes quiet again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from conftest import build_platform
from tenant_inventory_discovery.discovery_skill import DiscoverySkill
from tenant_inventory_discovery.models import Kind, RunSummary, ScopeReport


@dataclass
class RecordingProgress:
    """Captures the event stream instead of rendering it."""

    events: list[tuple[str, Any]] = field(default_factory=list)

    def _names(self) -> list[str]:
        return [name for name, _ in self.events]

    def payloads(self, name: str) -> list[Any]:
        """Payloads for one event type. Filter *before* destructuring."""
        return [payload for event_name, payload in self.events if event_name == name]

    def run_started(self, tenant_id, environment_ids):
        self.events.append(("run_started", (tenant_id, environment_ids)))

    def phase(self, message):
        self.events.append(("phase", message))

    def scope_started(self, kind, environment_id):
        self.events.append(("scope_started", (kind, environment_id)))

    def scope_enumerated(self, kind, environment_id, count, complete):
        self.events.append(
            ("scope_enumerated", (kind, environment_id, count, complete))
        )

    def scope_mapped(self, kind, environment_id, mapped, enumerated):
        self.events.append(("scope_mapped", (kind, environment_id, mapped, enumerated)))

    def scope_finished(self, report):
        self.events.append(("scope_finished", report))

    def sync_started(self, item_count):
        self.events.append(("sync_started", item_count))

    def sync_skipped(self, reason):
        self.events.append(("sync_skipped", reason))

    def sync_unchanged(self, item_count):
        self.events.append(("sync_unchanged", item_count))

    def sync_finished(self, result):
        self.events.append(("sync_finished", result))

    def run_finished(self, summary):
        self.events.append(("run_finished", summary))


@pytest.fixture
def progress() -> RecordingProgress:
    return RecordingProgress()


@pytest.fixture
def summary(platform, inventory, progress) -> RunSummary:
    skill = DiscoverySkill(platform, inventory, progress=progress)
    return skill.discover("contoso.onmicrosoft.com")


class TestRunLifecycleIsNarrated:
    def test_a_run_announces_its_start_and_its_end(self, summary, progress):
        names = progress._names()
        assert names[0] == "run_started"
        assert names[-1] == "run_finished"

    def test_the_finished_event_carries_the_real_summary(self, summary, progress):
        _, reported = progress.events[-1]
        assert reported is summary

    def test_the_start_event_names_the_tenant(self, summary, progress):
        _, (tenant_id, _envs) = progress.events[0]
        assert tenant_id == "contoso.onmicrosoft.com"


class TestEveryScopeIsNarrated:
    def test_each_crawled_kind_is_announced_before_it_is_read(self, summary, progress):
        started = {kind for kind, _env in progress.payloads("scope_started")}
        # All eight kinds are crawled, so all eight must be narrated -- a silent kind
        # is exactly the gap that makes a long run look hung.
        assert started == set(Kind)

    def test_a_scope_is_announced_before_its_count_is_known(self, progress, summary):
        order = [n for n in progress._names() if n.startswith("scope_")]
        assert order.index("scope_started") < order.index("scope_enumerated")

    def test_enumerated_counts_match_the_summary(self, summary, progress):
        reported = {
            (kind, env): count
            for kind, env, count, _complete in progress.payloads("scope_enumerated")
        }
        for report in summary.scopes:
            env = report.scope.environment_id or None
            assert reported[(report.scope.kind, env)] == report.enumerated

    def test_every_started_scope_is_also_finished(self, summary, progress):
        starts = sum(1 for n in progress._names() if n == "scope_started")
        finishes = sum(1 for n in progress._names() if n == "scope_finished")
        assert starts == finishes


class TestMappingIsNarrated:
    """The crawl's own progress. There is no per-row write phase to narrate anymore --
    the writing is one request -- so what a watcher follows is the *reading*."""

    def test_each_scope_reports_what_it_mapped(self, summary, progress):
        assert progress.payloads("scope_mapped"), (
            "no per-scope mapping progress during the crawl"
        )

    def test_the_mapped_count_never_exceeds_what_was_enumerated(
        self, summary, progress
    ):
        for _kind, _env, mapped, enumerated in progress.payloads("scope_mapped"):
            assert 0 <= mapped <= enumerated

    def test_mapping_is_reported_for_every_scope_that_found_something(
        self, summary, progress
    ):
        reported = {(kind, env) for kind, env, _m, _e in progress.payloads("scope_mapped")}
        for report in summary.scopes:
            if report.enumerated:
                assert (report.scope.kind, report.scope.environment_id or None) in reported


class TestTheSyncIsNarrated:
    """The single write is the slow, destructive step; it must never be silent."""

    def test_the_sync_announces_itself_with_a_size(self, summary, progress):
        counts = progress.payloads("sync_started")
        assert counts == [len(summary.payload)]

    def test_the_sync_is_announced_after_the_crawl(self, summary, progress):
        names = progress._names()
        assert names.index("sync_started") > names.index("scope_started")

    def test_the_result_is_reported_back(self, summary, progress):
        results = progress.payloads("sync_finished")
        assert results and results[0] is summary.synced

    def test_a_withheld_sync_says_so_instead_of_going_quiet(self, inventory, progress):
        """Silence after a refusal reads as a hang; the reason must be narrated."""
        empty = build_platform()
        empty.environments = []
        empty.entra_apps = []
        empty.connectors = []
        empty.sharepoint_sites = []
        empty.connections = {}
        empty.knowledge_sources = {}
        empty.extension_packs = {}
        empty.scenario_templates = {}

        DiscoverySkill(empty, inventory, progress=progress).discover("contoso")

        skipped = progress.payloads("sync_skipped")
        assert skipped and "empty payload" in skipped[0]
        assert "sync_started" not in progress._names()

    def test_a_retirement_is_visible_in_the_result(self, platform, inventory, progress):
        DiscoverySkill(platform, inventory).discover("contoso")

        gone = build_platform()
        gone.connectors = []
        DiscoverySkill(gone, inventory, progress=progress).discover("contoso")

        result = progress.payloads("sync_finished")[0]
        assert result.retired_item_ids == ["Connector:conn-catalog-1"]


class TestFailuresAreNarrated:
    def test_a_scope_that_fails_still_reports_finished(
        self, platform, inventory, progress
    ):
        from tenant_inventory_discovery.errors import PlatformError

        def boom(_env_id, _page_size=None):
            raise PlatformError("403 forbidden")

        platform.list_connections = boom

        DiscoverySkill(platform, inventory, progress=progress).discover(
            "contoso.onmicrosoft.com"
        )

        failed = [
            report
            for report in progress.payloads("scope_finished")
            if isinstance(report, ScopeReport)
            and report.scope.kind is Kind.CONNECTION
        ]
        # A scope that blew up must not simply stop narrating: silence after an error
        # is indistinguishable from a hang.
        assert failed and all(r.error for r in failed)
