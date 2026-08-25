"""Live progress reporting for a discovery run.

A crawl is long and almost entirely I/O: it enumerates eight kinds across a tenant and
then writes every observed row back, one POST each. Without a running commentary the
process is silent for minutes at a stretch, which reads as a hang -- both to a person
watching a terminal and to a tool that treats "no output" as a stalled command.

So the run engine emits events as it goes, and a reporter decides what to do with
them. :class:`NullProgressReporter` is the default and costs nothing;
:class:`ConsoleProgressReporter` prints a human-readable line per event plus a
**heartbeat** while a single slow call is in flight, so the stream never goes quiet
for longer than the heartbeat interval.

Progress is deliberately *not* the run summary: it is best-effort narration. A
reporter must never raise into the crawl, so :class:`ConsoleProgressReporter` swallows
its own write failures -- a broken pipe on stderr is not a reason to abandon a crawl.
"""

from __future__ import annotations

import threading
import time
from typing import Protocol, TextIO

from .models import Kind, RunSummary, ScopeReport

#: How long the console reporter may stay silent before it emits a heartbeat.
DEFAULT_HEARTBEAT_SECONDS = 10.0

#: Friendly labels, mirroring the table the /discover skill renders.
KIND_LABELS: dict[str, str] = {
    "Environment": "environments",
    "EntraApp": "app registrations",
    "Connector": "connectors",
    "Connection": "connections",
    "SharePointSite": "SharePoint sites",
    "KnowledgeSource": "knowledge sources",
    "ExtensionPack": "extension packs",
    "ScenarioTemplate": "scenario templates",
}


def label_for(kind: Kind) -> str:
    return KIND_LABELS.get(kind.discriminator, kind.discriminator)


class ProgressReporter(Protocol):
    """Narration hooks called by the run engine. Every method is best-effort."""

    def run_started(self, tenant_id: str, environment_ids: list[str] | None) -> None: ...

    def phase(self, message: str) -> None:
        """A coarse stage change ('reading tenant-wide resources')."""
        ...

    def scope_started(self, kind: Kind, environment_id: str | None) -> None: ...

    def scope_enumerated(
        self, kind: Kind, environment_id: str | None, count: int, complete: bool
    ) -> None: ...

    def upsert_progress(
        self, kind: Kind, environment_id: str | None, done: int, total: int
    ) -> None: ...

    def scope_finished(self, report: ScopeReport) -> None: ...

    def retire_started(self, scope_count: int) -> None: ...

    def scope_retired(
        self, kind: Kind, environment_id: str | None, retired: int
    ) -> None: ...

    def run_finished(self, summary: RunSummary) -> None: ...


class NullProgressReporter:
    """Default reporter: reports nothing, allocates nothing.

    Implements the same lifecycle as :class:`ConsoleProgressReporter` so callers can
    swap one for the other -- including as a context manager -- without branching.
    """

    def start(self) -> NullProgressReporter:
        return self

    def stop(self) -> None:
        return None

    def __enter__(self) -> NullProgressReporter:
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def run_started(self, tenant_id: str, environment_ids: list[str] | None) -> None:
        return None

    def phase(self, message: str) -> None:
        return None

    def scope_started(self, kind: Kind, environment_id: str | None) -> None:
        return None

    def scope_enumerated(
        self, kind: Kind, environment_id: str | None, count: int, complete: bool
    ) -> None:
        return None

    def upsert_progress(
        self, kind: Kind, environment_id: str | None, done: int, total: int
    ) -> None:
        return None

    def scope_finished(self, report: ScopeReport) -> None:
        return None

    def retire_started(self, scope_count: int) -> None:
        return None

    def scope_retired(
        self, kind: Kind, environment_id: str | None, retired: int
    ) -> None:
        return None

    def run_finished(self, summary: RunSummary) -> None:
        return None


class ConsoleProgressReporter:
    """Writes plain-text progress to a stream, with a heartbeat between events.

    Two properties matter more than the formatting:

    * **Every write is flushed.** A pipe-buffered stream would hold the narration
      until the process exits, which defeats the entire purpose.
    * **Silence is bounded.** A single upsert can block for a long time (token mint,
      retry backoff). A background heartbeat thread prints an elapsed-time line
      whenever nothing else has been written for ``heartbeat_seconds``, so a caller
      watching the stream can always tell "still working" from "wedged".

    Use as a context manager so the heartbeat thread is always stopped.
    """

    def __init__(
        self,
        stream: TextIO,
        *,
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
        prefix: str = "",
        clock=time.monotonic,
    ) -> None:
        self._stream = stream
        self._heartbeat_seconds = heartbeat_seconds
        self._prefix = prefix
        self._clock = clock
        self._lock = threading.RLock()
        self._activity = "starting"
        self._activity_started = clock()
        self._last_write = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Upsert progress is per-item and can be hundreds of calls; only the
        # transitions worth reading are printed.
        self._last_upsert_report = 0.0

    # -- lifecycle -------------------------------------------------------------------

    def start(self) -> ConsoleProgressReporter:
        if self._heartbeat_seconds > 0 and self._thread is None:
            self._thread = threading.Thread(
                target=self._heartbeat_loop, name="discovery-heartbeat", daemon=True
            )
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2)

    def __enter__(self) -> ConsoleProgressReporter:
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    # -- writing ---------------------------------------------------------------------

    def _write(self, text: str) -> None:
        """Emit one line. Never raises -- narration must not fail a crawl."""
        with self._lock:
            self._last_write = self._clock()
            try:
                self._stream.write(f"{self._prefix}{text}\n")
                self._stream.flush()
            except Exception:  # noqa: BLE001 - a closed stream is not a crawl failure
                pass

    def _set_activity(self, activity: str) -> None:
        with self._lock:
            self._activity = activity
            self._activity_started = self._clock()

    def _heartbeat_loop(self) -> None:
        # Poll at a fraction of the interval so the first heartbeat lands close to it.
        tick = max(0.25, min(1.0, self._heartbeat_seconds / 4))
        while not self._stop.wait(tick):
            with self._lock:
                idle = self._clock() - self._last_write
                activity = self._activity
                elapsed = self._clock() - self._activity_started
            if idle >= self._heartbeat_seconds:
                self._write(f"   ... still {activity} ({elapsed:.0f}s elapsed)")

    # -- ProgressReporter ------------------------------------------------------------

    def run_started(self, tenant_id: str, environment_ids: list[str] | None) -> None:
        scope = (
            ", ".join(environment_ids)
            if environment_ids
            else "every environment in the tenant"
        )
        self._set_activity("starting the crawl")
        self._write(f"Discovery started for {tenant_id} ({scope}).")

    def phase(self, message: str) -> None:
        self._set_activity(message)
        self._write(f">> {message}")

    def scope_started(self, kind: Kind, environment_id: str | None) -> None:
        where = f" in {environment_id}" if environment_id else ""
        self._set_activity(f"reading {label_for(kind)}{where}")
        self._write(f"   reading {label_for(kind)}{where}...")

    def scope_enumerated(
        self, kind: Kind, environment_id: str | None, count: int, complete: bool
    ) -> None:
        note = "" if complete else " (partial read)"
        self._set_activity(f"recording {count} {label_for(kind)}")
        self._write(f"   found {count} {label_for(kind)}{note}")

    def upsert_progress(
        self, kind: Kind, environment_id: str | None, done: int, total: int
    ) -> None:
        self._set_activity(f"recording {label_for(kind)} ({done}/{total})")
        # Throttle: one line per second is enough to prove liveness without burying
        # the meaningful events under hundreds of counter updates.
        now = self._clock()
        with self._lock:
            due = now - self._last_upsert_report >= 1.0
            if due:
                self._last_upsert_report = now
        if due or done == total:
            self._write(f"   recorded {done}/{total} {label_for(kind)}")

    def scope_finished(self, report: ScopeReport) -> None:
        if report.error:
            self._write(
                f"   ! {label_for(report.scope.kind)} incomplete: {report.error}"
            )
        elif report.capped:
            self._write(
                f"   ! {label_for(report.scope.kind)} hit the per-type row limit; "
                "nothing will be removed for it"
            )

    def retire_started(self, scope_count: int) -> None:
        self._set_activity("removing resources that no longer exist")
        self._write(
            f">> Checking {scope_count} resource type(s) for entries that no longer "
            "exist"
        )

    def scope_retired(
        self, kind: Kind, environment_id: str | None, retired: int
    ) -> None:
        if retired:
            self._write(f"   removed {retired} stale {label_for(kind)}")

    def run_finished(self, summary: RunSummary) -> None:
        self._set_activity("finishing up")
        if summary.aborted:
            self._write("Discovery stopped early. Nothing was changed.")
            return
        total = sum(scope.upserted for scope in summary.scopes)
        self._write(
            f"Discovery finished: recorded {total} resource(s) across "
            f"{len(summary.scopes)} scope(s)."
        )
