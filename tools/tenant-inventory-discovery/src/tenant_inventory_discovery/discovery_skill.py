"""Public entry point for the Tenant Inventory discovery skill (spec §3, §5.1, §7, §8).

Orchestrates the full run lifecycle:

1. Mint a local ``correlation_id`` for logs/telemetry (never sent to inventory, never
   stamped on rows).
2. Acquire the per-tenant single-flight lock (interim D6 mitigation, §7).
3. Run the crawl (enumerate -> map -> collect). Nothing is written.
4. **Carry forward everything the crawl cannot vouch for**, then submit the result as
   one ``syncInventory`` call.

   This step is the whole safety story, and it inverted with the service's move to
   whole-inventory sync. The service treats the payload as the tenant's desired end
   state: everything in it is upserted, and **everything Active that it omits is
   retired**. There is no client-side diff and no id list naming what to remove.

   So the old failure direction reversed. A partially-authorized crawl used to retire
   too *little* -- a scope that failed to enumerate contributed no ids, and nothing of
   its was touched. The same failure would now retire too *much*: every row that scope
   could not read becomes an absence, and every absence is a deletion. The service
   offers no guardrail, so the client provides one.

   The guardrail is **not** "refuse to sync unless everything read perfectly" -- that
   would make the skill useless on any real tenant, since it deliberately looks at one
   configured environment rather than the whole estate. Instead the payload is
   completed before it is sent: :meth:`_carry_forward` fetches the current inventory
   and re-sends, verbatim, every Active row belonging to a scope this run did not
   fully see. A scope is trusted to delete only when it is
   :attr:`~...ScopeReport.authoritative` -- read without error *and* covering the whole
   space it describes (see
   :func:`~tenant_inventory_discovery.platform_clients.coverage_of`).

   The result: an unreadable scope, an unmappable resource, a truncated listing and an
   environment that was never visited all become rows that are *present* in the
   payload, so none of them can retire anything. Only two things still withhold the
   sync -- an inventory that could not be read at all, and an empty payload -- because
   in both cases the request would describe a tenant the client has no evidence for.

5. Emit the structured run-summary telemetry and release the lock.
"""

from __future__ import annotations

import logging
import uuid

from .config import DiscoveryConfig
from .errors import InventoryApiError
from .inventory_client import InventoryClient
from .lock import RunLock
from .mapping import SyncPayloadError, to_sync_entry
from .models import InventoryItem, Kind, RunSummary, ScopeKey, SyncResult
from .platform_clients import PlatformSurface
from .progress import NullProgressReporter, ProgressReporter
from .runner import DiscoveryRunner
from .telemetry import LoggingTelemetrySink, TelemetrySink

logger = logging.getLogger("tenant_inventory_discovery")


def _item_from_row(kind: Kind, natural_key: str, row: dict) -> InventoryItem:
    """Rebuild a payload item from a row the service returned.

    The row is echoed, not re-derived. Its ``naturalKey`` and attributes are taken as
    given rather than recomposed from the attribute bag, because the point of carrying
    a row forward is that it survives byte-identically -- a recomposed key that differs
    by one percent-encoded character reads to the service as "the old row is absent,
    here is a new one", which retires exactly the row this was meant to protect.

    Attributes arrive as the wire's ``[{key, value}]`` array; a dict is tolerated so a
    fake or a future service shape passes through unchanged.
    """
    raw = row.get("attributes")
    attributes: dict[str, object] = {}
    if isinstance(raw, dict):
        attributes = dict(raw)
    elif isinstance(raw, list):
        for entry in raw:
            if isinstance(entry, dict) and entry.get("key") is not None:
                attributes[str(entry["key"])] = entry.get("value")

    environment_id = row.get("environmentId") or None
    return InventoryItem(
        kind=kind,
        natural_key=natural_key,
        attributes=attributes,
        environment_id=str(environment_id) if environment_id else None,
        display_name=row.get("displayName"),
        description=row.get("description"),
    )


class DiscoverySkill:
    """The admin-run crawler facade (spec §1, §3)."""

    def __init__(
        self,
        platform: PlatformSurface,
        inventory: InventoryClient,
        *,
        config: DiscoveryConfig | None = None,
        run_lock: RunLock | None = None,
        telemetry: TelemetrySink | None = None,
        progress: ProgressReporter | None = None,
    ) -> None:
        self._platform = platform
        self._inventory = inventory
        self._config = config or DiscoveryConfig()
        self._lock = run_lock
        self._telemetry = telemetry or LoggingTelemetrySink()
        self._progress = progress or NullProgressReporter()
        self._carry_forward_error = ""
        self._server_state: dict[tuple[Kind, str], InventoryItem] | None = None

    def discover(
        self,
        tenant_id: str,
        *,
        environment_ids: list[str] | None = None,
    ) -> RunSummary:
        """Run one discovery pass for ``tenant_id`` (spec §5.1).

        Returns the :class:`RunSummary`. On a crash before the sync phase, ``aborted``
        is True and nothing was written at all -- the crawl is read-only up to that
        point, so a half-finished run cannot retire anything. The remedy is a recrawl.
        """
        correlation_id = f"run-{uuid.uuid4()}"
        runner = DiscoveryRunner(
            self._platform,
            self._inventory,
            self._config,
            progress=self._progress,
        )

        if self._lock is not None:
            self._lock.acquire(tenant_id, correlation_id)

        summary = RunSummary(correlation_id=correlation_id)
        self._progress.run_started(tenant_id, environment_ids)
        # Per-run state, cleared here rather than only in _carry_forward: a crash
        # before that point must not leave the next run judging its payload against a
        # previous run's picture of the tenant.
        self._carry_forward_error = ""
        self._server_state = None
        try:
            summary = runner.run(environment_ids=environment_ids, run_id=correlation_id)
            self._carry_forward(summary)
            self._sync(summary)
        except Exception:
            # Crash path: the sync never ran, so the tenant's inventory is untouched.
            # Surface the failure; recrawl is the recovery path.
            summary.aborted = True
            logger.exception(
                "discovery run %s aborted; nothing written", correlation_id
            )
            self._progress.run_finished(summary)
            raise
        finally:
            self._telemetry.emit_run_summary(summary)
            if self._lock is not None:
                self._lock.release(tenant_id, correlation_id)

        self._progress.run_finished(summary)
        return summary

    # -- carry-forward ---------------------------------------------------------------

    def _carry_forward(self, summary: RunSummary) -> None:
        """Re-send the service's rows for every scope this run cannot vouch for.

        This is what makes a narrow crawl safe under whole-inventory sync. The service
        retires whatever the payload omits, so the payload must mention every row that
        should survive -- including rows in parts of the tenant this run never looked
        at. Fetching the current inventory and appending those rows verbatim turns
        "I didn't look there" from a deletion into a no-op.

        Only :attr:`~...ScopeReport.authoritative` scopes are skipped, and that is the
        entire point: those are the scopes the run *did* see completely, so an absence
        there is a genuine deletion and must stay an absence.

        Failing to read the current inventory withholds the sync
        (:meth:`_blocking_reason` checks :attr:`_carry_forward_error`) rather than
        proceeding, because a payload built without it would retire everything the
        crawl did not happen to cover.
        """
        self._carry_forward_error = ""
        self._server_state = None
        authoritative = set(summary.authoritative_scopes)
        try:
            rows = self._inventory.list_items()
        except InventoryApiError as exc:
            self._carry_forward_error = (
                f"the current inventory could not be read ({exc}), so the rows this "
                "crawl does not cover cannot be preserved"
            )
            logger.warning(
                "run %s: %s", summary.correlation_id, self._carry_forward_error
            )
            return

        present = {(i.kind, i.natural_key) for i in summary.payload}
        server_state: dict[tuple[Kind, str], InventoryItem] = {}
        carried: list[InventoryItem] = []
        for row in rows:
            if str(row.get("state") or "Active") != "Active":
                continue
            discriminator = str(row.get("kind") or "")
            try:
                kind = Kind.from_discriminator(discriminator)
            except ValueError:
                # A kind this build does not know -- the service has grown one. It
                # cannot be represented as an InventoryItem, so it cannot be put in the
                # payload, so submitting would retire it. Withhold instead: an ADK that
                # is merely out of date must not delete rows a newer client owns.
                # Self-healing -- upgrading the client clears it.
                self._carry_forward_error = (
                    f"the inventory contains rows of an unrecognized kind "
                    f"({discriminator!r}) that this build cannot preserve; syncing "
                    "would retire them. Upgrade the discovery client."
                )
                logger.error(
                    "run %s: %s", summary.correlation_id, self._carry_forward_error
                )
                return
            natural_key = str(row.get("naturalKey") or "")
            if not natural_key:
                continue
            # Every Active row, not just the carried ones: this is the "before" picture
            # the no-op check in _sync compares the finished payload against.
            server_state[(kind, natural_key)] = _item_from_row(kind, natural_key, row)
            if (kind, natural_key) in present:
                continue
            if ScopeKey(str(row.get("environmentId") or ""), kind) in authoritative:
                continue  # the crawl looked here; absence means deleted
            carried.append(_item_from_row(kind, natural_key, row))
            present.add((kind, natural_key))

        self._server_state = server_state

        if carried:
            summary.payload.extend(carried)
            summary.carried_forward = len(carried)
            for item in carried:
                key = item.kind.discriminator
                summary.submitted_counts[key] = summary.submitted_counts.get(key, 0) + 1
            logger.info(
                "run %s: carrying forward %d row(s) outside this crawl's coverage",
                summary.correlation_id,
                len(carried),
            )
        self._fit_to_caps(summary, {id(i) for i in carried})

    def _fit_to_caps(self, summary: RunSummary, carried_ids: set[int]) -> None:
        """Drop freshly observed rows until each kind fits the server's row cap.

        Carried-forward rows are never dropped and observed rows are. That looks
        backwards -- the observed rows are the fresher truth -- but only one of the two
        is destructive: omitting a carried row *retires* a resource that exists, while
        omitting an observed row merely defers recording it to the next pass. The
        service holds at most ``cap`` rows per kind, so the carried set alone can never
        overflow and this always converges.
        """
        cap = self._config.caps.max_items_per_tenant_and_kind
        counts: dict[Kind, int] = {}
        for item in summary.payload:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        over = {kind for kind, count in counts.items() if count > cap}
        if not over:
            return

        kept: list[InventoryItem] = []
        room = {kind: cap for kind in over}
        # Carried rows first so they claim their slots before any observed row can.
        for item in summary.payload:
            if item.kind not in over or id(item) in carried_ids:
                kept.append(item)
                if item.kind in over:
                    room[item.kind] -= 1
        dropped = 0
        for item in sorted(summary.payload, key=lambda i: i.natural_key):
            if item.kind not in over or id(item) in carried_ids:
                continue
            if room[item.kind] > 0:
                room[item.kind] -= 1
                kept.append(item)
            else:
                dropped += 1

        for kind in sorted(over, key=lambda k: k.discriminator):
            logger.warning(
                "%s: %d rows exceed the per-kind cap of %d; keeping every row already "
                "in the inventory and deferring the rest",
                kind.discriminator,
                counts[kind],
                cap,
            )
            for report in summary.scopes:
                if report.scope.kind is kind:
                    report.capped = True

        summary.payload = kept
        summary.submitted_counts = {}
        for item in kept:
            key = item.kind.discriminator
            summary.submitted_counts[key] = summary.submitted_counts.get(key, 0) + 1
        if dropped:
            logger.warning("deferred %d observed row(s) to stay within the caps", dropped)

    # -- sync phase ------------------------------------------------------------------

    def _is_unchanged(self, summary: RunSummary) -> bool:
        """Would submitting this payload change anything the service holds?

        Comparison is on the **wire form**, not the objects: a locally observed
        attribute may be an ``int`` where the service echoes ``"5"``, and
        :func:`to_sync_entry` is exactly the normalization the service will see. Two
        payloads that serialize identically are indistinguishable to it, so posting one
        over the other is provably a no-op.

        This matters because the sync is the expensive call in the run -- minutes of
        server-side writes -- and the overwhelmingly common case is a re-run over an
        unchanged tenant. Skipping it there costs one comparison against a list this
        method did not have to fetch: :meth:`_carry_forward` already needed it.

        Conservative by construction: anything that does not compare equal, including a
        state this build cannot model, falls through to the sync. The failure mode is a
        redundant write, never a skipped one.
        """
        state = self._server_state
        if state is None:
            return False  # never read the inventory; assume it differs

        def wire(item: InventoryItem) -> tuple:
            # The tenant id is immaterial: it is identical on both sides and is not
            # part of the tuple, so any value serializes the rest the same way.
            entry = to_sync_entry(item, "")
            attributes = sorted(
                (str(a.get("key")), str(a.get("value")))
                for a in entry.get("attributes") or []
            )
            return (
                entry.get("kind"),
                entry.get("naturalKey"),
                entry.get("environmentId"),
                entry.get("displayName"),
                entry.get("description"),
                entry.get("validationStatus"),
                tuple(attributes),
            )

        payload = {(i.kind, i.natural_key): i for i in summary.payload}
        if payload.keys() != state.keys():
            return False  # something appeared or disappeared
        return all(wire(item) == wire(state[key]) for key, item in payload.items())

    def _blocking_reason(self, summary: RunSummary) -> str:
        """Why this run must not be submitted, or ``""`` if it may be.

        The list is short because :meth:`_carry_forward` already neutralizes the
        common hazards: an unreadable scope, an unmappable item and an environment the
        run never visited all end up *present* in the payload rather than absent from
        it, so none of them can retire anything. What remains are the cases where the
        payload itself cannot be trusted to describe the tenant at all.
        """
        if self._carry_forward_error:
            return self._carry_forward_error

        if not summary.payload:
            return (
                "the crawl produced no items; an empty payload would retire the "
                "tenant's entire inventory"
            )
        return ""

    def _sync(self, summary: RunSummary) -> None:
        """Submit the whole inventory, or explain why it was withheld."""
        reason = self._blocking_reason(summary)
        if reason:
            summary.sync_blocked_reason = reason
            logger.error("run %s: withholding sync -- %s", summary.correlation_id, reason)
            self._progress.sync_skipped(reason)
            return

        self._progress.sync_started(len(summary.payload))
        if self._is_unchanged(summary):
            # The expensive call in the run, skipped because it provably does nothing.
            summary.sync_unchanged = True
            logger.info(
                "run %s: inventory already matches all %d item(s); skipping the sync",
                summary.correlation_id,
                len(summary.payload),
            )
            self._progress.sync_unchanged(len(summary.payload))
            return

        try:
            result = self._inventory.sync_inventory(
                summary.payload, run_id=summary.correlation_id
            )
        except SyncPayloadError as exc:
            # A payload the service is certain to reject. Withholding it is the same
            # decision as above, reached one layer down.
            summary.sync_blocked_reason = str(exc)
            logger.error(
                "run %s: withholding sync -- %s", summary.correlation_id, exc
            )
            self._progress.sync_skipped(str(exc))
            return
        except InventoryApiError:
            logger.exception("run %s: sync failed", summary.correlation_id)
            raise

        summary.synced = result
        self._attribute_retirements(summary, result)

        if result.failed_items:
            # Partial success: everything else applied. The documented cause is a child
            # whose environment the payload omitted, which the next pass corrects.
            for item in result.failed_items:
                logger.warning(
                    "sync could not apply %s: %s", item.item_id, item.reason
                )

        logger.info(
            "run %s: synced %d item(s); %d upserted, %d retired, %d failed",
            summary.correlation_id,
            result.submitted_count,
            result.upserted_count,
            result.retired_count,
            len(result.failed_items),
        )
        self._progress.sync_finished(result)

    @staticmethod
    def _attribute_retirements(summary: RunSummary, result: SyncResult) -> None:
        """Group the service's retired ids by kind, for the run report.

        Kind is as far as this can honestly go. The ids come back opaque
        (``{Kind}:{percentEncoded(naturalKey)}``) and the kind prefix needs no decoding
        -- a natural key may contain ``:`` but a kind discriminator may not, so one
        split is unambiguous. Attributing further, to the environment a retired row
        lived in, would mean decoding a composite key whose shape varies by kind, and
        the run has no scope report to hang it on anyway: the payload that caused the
        retirement was tenant-wide, not per-scope.
        """
        known = {k.discriminator for k in Kind}
        for item_id in result.retired_item_ids:
            prefix = item_id.split(":", 1)[0]
            key = prefix if prefix in known else "Unknown"
            summary.retired_counts[key] = summary.retired_counts.get(key, 0) + 1
