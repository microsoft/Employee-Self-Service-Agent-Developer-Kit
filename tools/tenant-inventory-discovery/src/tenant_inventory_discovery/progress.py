"""Live progress reporting for a discovery run.

A crawl is long and almost entirely I/O: it enumerates eight kinds across a tenant and
then submits the whole picture in one call. Without a running commentary the process is
silent for minutes at a stretch, which reads as a hang -- both to a person watching a
terminal and to a tool that treats "no output" as a stalled command.

So the run engine emits events as it goes, and a reporter decides what to do with
them. :class:`NullProgressReporter` is the default and costs nothing;
:class:`ConsoleProgressReporter` prints a human-readable line per event plus a
**heartbeat** while a single slow call is in flight, so the stream never goes quiet
for longer than the heartbeat interval.

The narration has two acts, matching what the run actually does. The crawl *reads* and
maps -- it writes nothing, so its lines say "found" and "prepared", never "recorded".
The sync is one call that either goes out or is withheld, so it gets exactly one of
:meth:`ProgressReporter.sync_finished` or :meth:`ProgressReporter.sync_skipped`. A
withheld sync is the loudest line the reporter emits, because it is the one outcome a
watching operator must not mistake for success.

Progress is deliberately *not* the run summary: it is best-effort narration. A
reporter must never raise into the crawl, so :class:`ConsoleProgressReporter` swallows
its own write failures -- a broken pipe on stderr is not a reason to abandon a crawl.
"""

from __future__ import annotations

import threading
import time
from typing import Protocol, TextIO

from .models import Kind, RunSummary, ScopeReport, SyncResult

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

    def scope_mapped(
        self, kind: Kind, environment_id: str | None, mapped: int, enumerated: int
    ) -> None:
        """A scope finished mapping. Nothing has been written -- this is payload."""
        ...

    def scope_finished(self, report: ScopeReport) -> None: ...

    def sync_started(self, item_count: int) -> None:
        """The whole-inventory payload is going out."""
        ...

    def sync_skipped(self, reason: str) -> None:
        """The payload was withheld. Nothing changed server-side."""
        ...

    def sync_unchanged(self, item_count: int) -> None:
        """The payload already matched the service, so nothing was sent."""
        ...

    def sync_finished(self, result: SyncResult) -> None: ...

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

    def scope_mapped(
        self, kind: Kind, environment_id: str | None, mapped: int, enumerated: int
    ) -> None:
        return None

    def scope_finished(self, report: ScopeReport) -> None:
        return None

    def sync_started(self, item_count: int) -> None:
        return None

    def sync_skipped(self, reason: str) -> None:
        return None

    def sync_unchanged(self, item_count: int) -> None:
        return None

    def sync_finished(self, result: SyncResult) -> None:
        return None

    def run_finished(self, summary: RunSummary) -> None:
        return None


class ConsoleProgressReporter:
    """Writes plain-text progress to a stream, with a heartbeat between events.

    Two properties matter more than the formatting:

    * **Every write is flushed.** A pipe-buffered stream would hold the narration
      until the process exits, which defeats the entire purpose.
    * **Silence is bounded.** A single call can block for a long time (token mint,
      retry backoff, and above all the one whole-inventory sync at the end). A
      background heartbeat thread prints an elapsed-time line whenever nothing else
      has been written for ``heartbeat_seconds``, so a caller watching the stream can
      always tell "still working" from "wedged".

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

    def scope_mapped(
        self, kind: Kind, environment_id: str | None, mapped: int, enumerated: int
    ) -> None:
        self._set_activity(f"preparing {label_for(kind)}")
        if mapped != enumerated:
            self._write(
                f"   prepared {mapped}/{enumerated} {label_for(kind)} for the sync"
            )

    def scope_finished(self, report: ScopeReport) -> None:
        label = label_for(report.scope.kind)
        if report.error:
            self._write(f"   ! {label} could not be read: {report.error}")
        elif report.skipped_invalid:
            self._write(
                f"   ! {report.skipped_invalid} {label} could not be described and "
                "were skipped"
            )
        elif report.capped:
            self._write(
                f"   ! {label} hit the per-type row limit; syncing the first "
                f"{report.mapped} and leaving out {report.truncated}"
            )

    def sync_started(self, item_count: int) -> None:
        self._set_activity(f"saving {item_count} resource(s) to the inventory")
        self._write(
            f">> Saving the tenant picture: {item_count} resource(s) in one request"
        )
        # Set expectations before the wait, not after. This single call does all the
        # writing and all the retiring for the run, so minutes of silence here is
        # normal -- and a caller who does not know that kills the process.
        self._write(
            "   This is one large request and can take several minutes. "
            "Progress lines continue below; do not cancel."
        )

    def sync_skipped(self, reason: str) -> None:
        self._set_activity("finishing up")
        self._write(f"!! Nothing was saved: {reason}.")
        self._write("   The inventory is unchanged. Fix the above and re-run.")

    def sync_unchanged(self, item_count: int) -> None:
        self._set_activity("finishing up")
        self._write(
            f"   inventory already matches all {item_count} resource(s) -- "
            "nothing to save, skipping the request"
        )

    def sync_finished(self, result: SyncResult) -> None:
        self._set_activity("finishing up")
        self._write(
            f"   saved {result.upserted_count} resource(s); "
            f"removed {result.retired_count} that no longer exist"
        )
        for failed in result.failed_items:
            self._write(f"   ! could not save {failed.item_id}: {failed.reason}")

    def run_finished(self, summary: RunSummary) -> None:
        self._set_activity("finishing up")
        if summary.aborted:
            self._write("Discovery stopped early. Nothing was changed.")
            return
        if summary.synced is None:
            if summary.sync_unchanged:
                self._write(
                    f"Discovery finished: {len(summary.payload)} resource(s) "
                    "confirmed, nothing changed since the last run."
                )
                return
            # sync_skipped already explained why; don't imply anything was stored.
            self._write(
                f"Discovery finished reading {len(summary.payload)} resource(s), "
                "but saved nothing."
            )
            return
        self._write(
            f"Discovery finished: {summary.synced.upserted_count} resource(s) saved "
            f"across {len(summary.scopes)} scope(s)."
        )
