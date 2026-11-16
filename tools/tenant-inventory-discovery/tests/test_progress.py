"""Tests for live progress narration.

The crawl is silent for minutes at a time -- eight paged enumerations behind a token
mint and a retry budget, then one large POST. That silence is what made ``/discover``
look wedged, so these tests pin the two properties that actually prevent it: **every
line is flushed immediately**, and **the stream never goes quiet for longer than the
heartbeat**.

The write phase no longer has a row counter to tick (it is a single request), which
makes the ``sync_started`` / ``sync_finished`` pair the only thing standing between
the operator and an apparently frozen terminal. Those are pinned hardest.

Formatting is checked only loosely (does the line mention the thing it is about);
pinning exact wording here would make the copy impossible to improve.
"""

from __future__ import annotations

import io
import threading
import time

import pytest

from tenant_inventory_discovery.models import (
    FailedSyncItem,
    Kind,
    RunSummary,
    ScopeKey,
    ScopeReport,
    SyncResult,
)
from tenant_inventory_discovery.progress import (
    ConsoleProgressReporter,
    NullProgressReporter,
    label_for,
)


class _RecordingStream(io.StringIO):
    """A stream that remembers whether each write was followed by a flush."""

    def __init__(self) -> None:
        super().__init__()
        self.flushes = 0
        self.unflushed = 0
        self._lock = threading.Lock()

    def write(self, text: str) -> int:  # type: ignore[override]
        with self._lock:
            self.unflushed += 1
            return super().write(text)

    def flush(self) -> None:
        with self._lock:
            self.flushes += 1
            self.unflushed = 0
        super().flush()

    def lines(self) -> list[str]:
        return [ln for ln in self.getvalue().splitlines() if ln.strip()]


@pytest.fixture
def stream() -> _RecordingStream:
    return _RecordingStream()


class TestNullReporter:
    def test_it_stays_silent(self, capsys):
        reporter = NullProgressReporter()
        reporter.run_started("contoso", ["env-prod"])
        reporter.phase("reading things")
        reporter.scope_started(Kind.CONNECTION, "env-prod")
        reporter.scope_mapped(Kind.CONNECTION, "env-prod", 1, 2)
        reporter.sync_started(3)
        reporter.run_finished(RunSummary(correlation_id="run-1"))

        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == ""

    def test_it_supports_the_same_lifecycle_as_the_console_reporter(self):
        # --quiet swaps this in for ConsoleProgressReporter; if the two do not share a
        # lifecycle, the quiet path blows up at the point it tries to shut down.
        reporter = NullProgressReporter()
        reporter.start()
        reporter.stop()
        with reporter as ctx:
            assert ctx is reporter

    @pytest.mark.parametrize(
        "method",
        [
            "start",
            "stop",
            "run_started",
            "phase",
            "scope_started",
            "scope_enumerated",
            "scope_mapped",
            "scope_finished",
            "sync_started",
            "sync_skipped",
            "sync_finished",
            "run_finished",
        ],
    )
    def test_it_is_substitutable_for_the_console_reporter(self, method):
        assert hasattr(NullProgressReporter(), method)
        assert hasattr(ConsoleProgressReporter(io.StringIO()), method)


class TestOutputIsImmediate:
    """Buffered narration is no narration: it all arrives at exit, after the wait."""

    def test_every_line_is_flushed_as_it_is_written(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.phase("reading tenant-wide resources")
        assert stream.unflushed == 0
        reporter.scope_started(Kind.CONNECTOR, None)
        assert stream.unflushed == 0
        assert stream.flushes >= 2

    def test_it_narrates_the_stages_it_is_given(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.run_started("contoso", ["env-prod"])
        reporter.phase("reading tenant-wide resources")
        reporter.scope_started(Kind.CONNECTION, "env-prod")
        reporter.scope_enumerated(Kind.CONNECTION, "env-prod", 3, complete=True)

        text = "\n".join(stream.lines())
        assert "contoso" in text
        assert "env-prod" in text
        assert label_for(Kind.CONNECTION) in text
        assert "3" in text

    def test_a_partial_read_is_called_out(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.scope_enumerated(Kind.CONNECTION, "env-prod", 2, complete=False)
        # An incomplete scope means nothing gets retired for it -- the operator needs
        # to know the number they are looking at is not the whole picture.
        assert "partial" in "\n".join(stream.lines()).lower()


class TestTheSyncIsNarrated:
    """One request replaced hundreds, so the counter spam is gone -- but the single
    slow call is now the *only* thing between "reading" and "done". It has to speak."""

    def test_the_size_of_the_payload_is_announced_up_front(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.sync_started(137)
        # The operator is about to wait on one request; the number tells them why.
        assert any("137" in ln for ln in stream.lines())

    def test_the_long_wait_is_predicted_before_it_starts(self, stream):
        """The reason a user kills the process is that nobody warned them.

        This call does all the writing and all the retiring for the run, so minutes of
        near-silence is the healthy case. Saying so *after* the wait is useless.
        """
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.sync_started(400)
        text = "\n".join(stream.lines()).lower()

        assert "minute" in text
        assert "cancel" in text

    def test_a_skipped_redundant_sync_does_not_read_as_a_failure(self, stream):
        """"Nothing to save" and "nothing was saved" are opposite outcomes."""
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.sync_unchanged(12)
        text = "\n".join(stream.lines())

        assert "12" in text
        assert "!!" not in text  # the withheld marker
        assert "re-run" not in text.lower()

    def test_the_outcome_separates_saved_from_removed(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.sync_finished(
            SyncResult(submitted_count=10, upserted_count=10, retired_count=2)
        )
        text = "\n".join(stream.lines())
        assert "10" in text
        assert "2" in text

    def test_a_partial_success_names_the_rows_that_failed(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.sync_finished(
            SyncResult(
                submitted_count=2,
                upserted_count=1,
                failed_items=[
                    FailedSyncItem(item_id="Connection:c-9", reason="no environment")
                ],
            )
        )
        text = "\n".join(stream.lines())
        assert "Connection:c-9" in text
        assert "no environment" in text

    def test_a_withheld_sync_is_unmistakable(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.sync_skipped("the crawl produced no items")
        text = "\n".join(stream.lines())
        # The dangerous misreading is "it finished, so it saved". Rule that out.
        assert "Nothing was saved" in text
        assert "unchanged" in text

    def test_mapping_reports_a_shortfall(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.scope_mapped(Kind.CONNECTION, "env-prod", 8, 10)
        assert "8/10" in "\n".join(stream.lines())

    def test_mapping_stays_quiet_when_nothing_was_lost(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.scope_mapped(Kind.CONNECTION, "env-prod", 10, 10)
        assert stream.lines() == []

class TestHeartbeat:
    """The anti-stale guarantee: a slow call still produces output."""

    def test_it_speaks_up_while_a_single_slow_call_is_in_flight(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0.3)
        reporter.phase("recording connections")
        with reporter:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                if any("still" in ln for ln in stream.lines()):
                    break
                time.sleep(0.05)

        beats = [ln for ln in stream.lines() if "still" in ln]
        assert beats, "no heartbeat while the run was silent"
        # It should name what it is waiting on, not just prove the process is alive.
        assert "recording connections" in beats[0]

    def test_it_stays_quiet_while_events_keep_arriving(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=1.0)
        with reporter:
            for _ in range(6):
                reporter.phase("working")
                time.sleep(0.1)

        assert not [ln for ln in stream.lines() if "still" in ln]

    def test_stopping_is_idempotent_and_ends_the_thread(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0.3)
        reporter.start()
        reporter.stop()
        reporter.stop()

        names = [t.name for t in threading.enumerate()]
        assert "discovery-heartbeat" not in names

    def test_a_zero_interval_disables_it(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        with reporter:
            time.sleep(0.4)
        assert "discovery-heartbeat" not in [t.name for t in threading.enumerate()]


class TestNarrationNeverBreaksTheCrawl:
    def test_a_broken_stream_is_swallowed(self):
        class Broken(io.StringIO):
            def write(self, text):  # type: ignore[override]
                raise BrokenPipeError("downstream went away")

        reporter = ConsoleProgressReporter(Broken(), heartbeat_seconds=0)
        # A closed pipe on stderr is not a reason to abandon a discovery run.
        reporter.run_started("contoso", None)
        reporter.phase("still going")
        reporter.run_finished(RunSummary(correlation_id="run-1"))


class TestRunOutcome:
    def _summary(self, *, aborted: bool = False, synced: bool = True) -> RunSummary:
        summary = RunSummary(correlation_id="run-1", aborted=aborted)
        report = ScopeReport(scope=ScopeKey.for_kind(Kind.CONNECTION, "env-prod"))
        report.mapped = 7
        summary.scopes.append(report)
        if synced:
            summary.synced = SyncResult(
                submitted_count=7, upserted_count=7, retired_count=0
            )
        return summary

    def test_a_finished_run_reports_what_it_saved(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.run_finished(self._summary())
        assert "7" in "\n".join(stream.lines())

    def test_an_aborted_run_says_nothing_changed(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.run_finished(self._summary(aborted=True))
        # Abort is the one outcome an operator must not misread as success.
        assert "Nothing was changed" in "\n".join(stream.lines())

    def test_a_run_that_withheld_the_sync_never_claims_to_have_saved(self, stream):
        """The crawl succeeded but nothing was written -- the two must not blur."""
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        reporter.run_finished(self._summary(synced=False))
        assert "saved nothing" in "\n".join(stream.lines())

    def test_a_failed_scope_is_surfaced(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        report = ScopeReport(scope=ScopeKey.for_kind(Kind.CONNECTION, "env-prod"))
        report.error = "403 forbidden"
        reporter.scope_finished(report)
        assert "403 forbidden" in "\n".join(stream.lines())

    def test_a_capped_scope_says_what_was_left_out(self, stream):
        reporter = ConsoleProgressReporter(stream, heartbeat_seconds=0)
        report = ScopeReport(scope=ScopeKey.for_kind(Kind.CONNECTION, "env-prod"))
        report.capped = True
        report.mapped = 50
        report.truncated = 3
        reporter.scope_finished(report)
        text = "\n".join(stream.lines())
        assert "50" in text
        assert "3" in text
