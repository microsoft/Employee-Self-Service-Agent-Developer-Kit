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

    def upsert_progress(self, kind, environment_id, done, total):
        self.events.append(("upsert_progress", (kind, environment_id, done, total)))

    def scope_finished(self, report):
        self.events.append(("scope_finished", report))

    def retire_started(self, scope_count):
        self.events.append(("retire_started", scope_count))

    def scope_retired(self, kind, environment_id, retired):
        self.events.append(("scope_retired", (kind, environment_id, retired)))

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


class TestUpsertsReportIncrementally:
    def test_progress_is_reported_while_rows_are_written(self, summary, progress):
        assert progress.payloads("upsert_progress"), (
            "no per-row progress during the write phase"
        )

    def test_the_counter_never_exceeds_the_total(self, summary, progress):
        for _kind, _env, done, total in progress.payloads("upsert_progress"):
            assert 1 <= done <= total

    def test_each_scope_counts_all_the_way_up(self, summary, progress):
        finals: dict[tuple[Kind, Any], tuple[int, int]] = {}
        for kind, env, done, total in progress.payloads("upsert_progress"):
            best = finals.get((kind, env), (0, total))
            finals[(kind, env)] = (max(best[0], done), total)
        # The last thing reported for a scope must be "done", or a watcher is left
        # staring at a stalled-looking fraction.
        for (_kind, _env), (done, total) in finals.items():
            assert done == total


class TestRetireIsNarrated:
    def test_the_retire_phase_announces_itself(self, summary, progress):
        assert "retire_started" in progress._names()

    def test_retire_is_announced_after_the_crawl(self, summary, progress):
        names = progress._names()
        assert names.index("retire_started") > names.index("scope_started")

    def test_retire_counts_are_reported_per_scope(self, platform, inventory, progress):
        # First pass populates the inventory...
        DiscoverySkill(platform, inventory).discover("contoso.onmicrosoft.com")

        # ...then a resource disappears, so the second pass must retire it. Use a
        # tenant-root kind: its sweep is a list/diff, not a watermark compare, so it
        # does not depend on wall-clock separation between the two passes.
        platform2 = build_platform()
        platform2.connectors = []

        DiscoverySkill(platform2, inventory, progress=progress).discover(
            "contoso.onmicrosoft.com"
        )

        retired = {
            (kind, env): count
            for kind, env, count in progress.payloads("scope_retired")
        }
        assert retired.get((Kind.CONNECTOR, None)) == 1


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
