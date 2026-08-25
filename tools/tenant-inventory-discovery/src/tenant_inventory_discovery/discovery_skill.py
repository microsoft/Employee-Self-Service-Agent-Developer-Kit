"""Public entry point for the Tenant Inventory discovery skill (spec §3, §5.1, §7, §8).

Orchestrates the full run lifecycle:

1. Mint a local ``correlation_id`` for logs/telemetry (never sent to inventory, never
   stamped on rows).
2. Acquire the per-tenant single-flight lock (interim D6 mitigation, §7).
3. Run the crawl (enumerate -> map -> upsert), capturing the ``passStartedAt``
   watermark before the first enumeration.
4. **Retire drift**, for fully-crawled scopes only. A crashed run never reaches this
   step, so nothing is retired (§7). Two mechanisms, because the service splits them:

   - **Env-scoped kinds** use the server's ``reconcile`` action, one call per
     ``(kind, environmentId)``. It is *watermark*-based: rows in the scope whose
     ``UpdatedAt`` predates ``passStartedAt`` are retired.
   - **Tenant-rooted kinds** (Environment, EntraApp, Connector, SharePointSite) are
     rejected by ``reconcile``, so the skill sweeps them itself: list the scope's
     current rows, diff against the keys this pass observed, and ``DELETE`` the
     remainder. That diff -- not a timestamp -- is what makes the sweep safe.

5. Emit the structured run-summary telemetry and release the lock.
"""

from __future__ import annotations

import logging
import uuid

from .config import DiscoveryConfig
from .errors import InventoryApiError
from .inventory_client import InventoryClient
from .lock import RunLock
from .models import Kind, RunSummary, ScopeReport
from .platform_clients import PlatformSurface
from .progress import NullProgressReporter, ProgressReporter
from .runner import DiscoveryRunner
from .telemetry import LoggingTelemetrySink, TelemetrySink

logger = logging.getLogger("tenant_inventory_discovery")


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

    def discover(
        self,
        tenant_id: str,
        *,
        environment_ids: list[str] | None = None,
    ) -> RunSummary:
        """Run one discovery pass for ``tenant_id`` (spec §5.1).

        Returns the :class:`RunSummary`. On a crash before the retire phase,
        ``aborted`` is True and nothing is retired (the completeness invariant, §7);
        the remedy is a recrawl.
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
        try:
            summary = runner.run(environment_ids=environment_ids, run_id=correlation_id)
            self._retire_drift(summary)
        except Exception:
            # Crash path: the retire phase never ran, so nothing was retired (§7).
            # Surface the failure; recrawl is the recovery path.
            summary.aborted = True
            logger.exception(
                "discovery run %s aborted; nothing retired", correlation_id
            )
            self._progress.run_finished(summary)
            raise
        finally:
            self._telemetry.emit_run_summary(summary)
            if self._lock is not None:
                self._lock.release(tenant_id, correlation_id)

        self._progress.run_finished(summary)
        return summary

    # -- retire phase ----------------------------------------------------------------

    def _retire_drift(self, summary: RunSummary) -> None:
        """Retire rows the run proved absent, for fully-crawled scopes only."""
        completed = set(summary.completed_scopes)
        eligible = [r for r in summary.scopes if r.scope in completed]
        if not eligible:
            logger.info(
                "run %s: no fully-crawled scopes; skipping retire phase",
                summary.correlation_id,
            )
            return

        self._progress.retire_started(len(eligible))
        for report in eligible:
            if report.scope.kind.is_env_scoped:
                self._reconcile_scope(summary, report)
            else:
                self._sweep_tenant_root(summary, report)

    def _reconcile_scope(self, summary: RunSummary, report: ScopeReport) -> None:
        """Server-side watermark reconcile for one env-scoped ``(kind, env)``."""
        assert summary.pass_started_at is not None
        kind = report.scope.kind
        env_id = report.scope.environment_id
        try:
            result = self._inventory.reconcile(kind, env_id, summary.pass_started_at)
        except InventoryApiError as exc:
            # A failed reconcile is not a failed run: the rows are correct, drift just
            # lingers until the next pass.
            logger.error(
                "reconcile failed for %s in env %s: %s", kind.discriminator, env_id, exc
            )
            return

        summary.reconciled.append(result)
        report.retired_item_ids = list(result.retired_item_ids)
        self._progress.scope_retired(kind, env_id, result.retired_count)
        if result.retired_count:
            summary.retired_counts[f"{env_id}|{kind.discriminator}"] = (
                result.retired_count
            )

    def _sweep_tenant_root(self, summary: RunSummary, report: ScopeReport) -> None:
        """Client-side list/diff/DELETE sweep for one tenant-rooted kind.

        ``reconcile`` rejects these kinds, so completeness has to be proven here: the
        scope is already known fully-enumerated and uncapped, which is what makes
        "listed but not observed" mean "gone" rather than "not reached".
        """
        kind: Kind = report.scope.kind
        observed = set(report.observed_keys)
        try:
            rows = self._inventory.list_items(kind=kind)
        except InventoryApiError as exc:
            logger.error(
                "drift sweep failed to list %s: %s", kind.discriminator, exc
            )
            return

        for row in rows:
            # Only ever retire rows this skill authored. A hand-authored row is a
            # deliberate act and is not drift.
            if row.get("source") != "Discovered":
                continue
            if row.get("naturalKey") in observed:
                continue
            item_id = row.get("agentConfigurationInventoryItemId")
            if not item_id:
                continue
            try:
                self._inventory.retire(item_id)
            except InventoryApiError as exc:
                logger.error("failed to retire %s: %s", item_id, exc)
                continue
            report.retired_item_ids.append(item_id)

        if report.retired_item_ids:
            summary.retired_counts[f"|{kind.discriminator}"] = len(
                report.retired_item_ids
            )
        self._progress.scope_retired(kind, None, len(report.retired_item_ids))
