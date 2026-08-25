"""Run engine: enumerate -> map -> upsert -> track completeness (spec §5, §6, §7).

This drives every crawler with identical run semantics and computes which
``(EnvironmentId, Kind)`` scopes are reconcile-eligible. It does **not** signal
run-complete or touch the lock/telemetry -- that orchestration lives in
:mod:`tenant_inventory_discovery.discovery_skill`. Keeping the two apart makes the
reconcile gate (the load-bearing safety property, §7) directly unit-testable.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from .config import DiscoveryConfig
from .crawlers.base import Crawler
from .crawlers.registry import ENV_SCOPED_CRAWLERS, TENANT_ROOT_CRAWLERS
from .errors import PlatformError, PreconditionFailedError
from .inventory_client import InventoryClient
from .mapping import map_resource
from .models import (
    InventoryItem,
    Kind,
    RunSummary,
    ScopeKey,
    ScopeReport,
)
from .platform_clients import PlatformSurface, drain
from .progress import NullProgressReporter, ProgressReporter
from .schemas import AttributeValidationError

logger = logging.getLogger("tenant_inventory_discovery")


class DiscoveryRunner:
    """Executes one discovery run and returns a :class:`RunSummary` (spec §5.1)."""

    def __init__(
        self,
        platform: PlatformSurface,
        inventory: InventoryClient,
        config: DiscoveryConfig,
        *,
        progress: ProgressReporter | None = None,
    ) -> None:
        self._platform = platform
        self._inventory = inventory
        self._config = config
        self._progress = progress or NullProgressReporter()
        self._kind_counts: dict[Kind, int] = {}
        self._run_id = ""

    def run(
        self, environment_ids: list[str] | None = None, *, run_id: str = ""
    ) -> RunSummary:
        """Crawl the tenant and return a :class:`RunSummary` (spec §5.1, §6.1).

        ``environment_ids=None`` performs a **full/tenant-root crawl**: all discovered
        environments are crawled and tenant-root kinds become reconcile-eligible. Passing
        an explicit subset performs a **partial env crawl**: env-scoped scopes for those
        environments may reconcile, but tenant-root kinds are **never** marked complete
        (tenant-root exemption, §6.3).

        ``run_id`` scopes each upsert's idempotency key to this pass; see
        :func:`~tenant_inventory_discovery.mapping.idempotency_key`.
        """
        full_crawl = environment_ids is None
        summary = RunSummary(correlation_id=run_id or f"run-{uuid.uuid4()}")
        self._run_id = summary.correlation_id
        # The reconcile watermark, captured *before* the first enumeration and
        # backdated by the configured skew allowance. Every row this pass observes is
        # re-upserted, so its server-stamped UpdatedAt lands after this instant;
        # anything still older was not observed and is drift.
        summary.pass_started_at = datetime.now(timezone.utc) - timedelta(
            seconds=self._config.clock_skew_allowance_seconds
        )
        reports: dict[ScopeKey, ScopeReport] = {}
        discovered_env_ids: list[str] = []
        # Rows written per kind this run. The server caps rows per (tenant, kind) --
        # not per scope -- so this counter spans every environment in the run.
        self._kind_counts: dict[Kind, int] = {}

        # Phase 1 -- tenant-root kinds first (spec §4 crawl order). The Environment crawl
        # yields the environment list that drives Phase 2.
        self._progress.phase("Reading tenant-wide resources")
        for crawler in TENANT_ROOT_CRAWLERS:
            report, items = self._crawl_tenant_root(crawler)
            reports[report.scope] = report
            summary.scopes.append(report)
            if crawler.kind is Kind.ENVIRONMENT:
                discovered_env_ids = [
                    str(it.attributes["environmentId"]) for it in items
                ]

        target_envs = discovered_env_ids if full_crawl else list(environment_ids or [])

        # Phase 2 -- env-scoped kinds inside each target environment (spec §4).
        for env_id in target_envs:
            self._progress.phase(f"Reading resources in {env_id}")
            for crawler in ENV_SCOPED_CRAWLERS:
                report = self._crawl_env(crawler, env_id)
                reports[report.scope] = report
                summary.scopes.append(report)

        summary.completed_scopes = self._completed_scopes(reports, full_crawl)
        return summary

    # -- crawl helpers --------------------------------------------------------------

    def _crawl_tenant_root(
        self, crawler: Crawler
    ) -> tuple[ScopeReport, list[InventoryItem]]:
        scope = ScopeKey.for_kind(crawler.kind)
        report = ScopeReport(scope=scope)
        assert crawler.tenant_root is not None
        self._progress.scope_started(crawler.kind, None)
        try:
            pages = crawler.tenant_root(self._platform, self._config.page_size)
            resources, fully = drain(pages)
        except PlatformError as exc:
            report.error = str(exc)
            logger.warning("enumeration failed for %s: %s", crawler.kind.discriminator, exc)
            self._progress.scope_finished(report)
            return report, []

        report.fully_enumerated = fully
        self._progress.scope_enumerated(crawler.kind, None, len(resources), fully)
        items = self._map_and_upsert(crawler.kind, resources, report)
        self._progress.scope_finished(report)
        return report, items

    def _crawl_env(self, crawler: Crawler, environment_id: str) -> ScopeReport:
        scope = ScopeKey.for_kind(crawler.kind, environment_id)
        report = ScopeReport(scope=scope)
        assert crawler.env_scoped is not None
        self._progress.scope_started(crawler.kind, environment_id)
        try:
            pages = crawler.env_scoped(
                self._platform, environment_id, self._config.page_size
            )
            resources, fully = drain(pages)
        except PlatformError as exc:
            report.error = str(exc)
            logger.warning(
                "enumeration failed for %s in env %s: %s",
                crawler.kind.discriminator,
                environment_id,
                exc,
            )
            self._progress.scope_finished(report)
            return report

        report.fully_enumerated = fully
        self._progress.scope_enumerated(
            crawler.kind, environment_id, len(resources), fully
        )
        self._map_and_upsert(crawler.kind, resources, report, environment_id)
        self._progress.scope_finished(report)
        return report

    def _map_and_upsert(
        self,
        kind: Kind,
        resources: list[dict[str, object]],
        report: ScopeReport,
        environment_id: str | None = None,
    ) -> list[InventoryItem]:
        report.enumerated = len(resources)

        # Client-side guard for the server's per-(tenant, kind) row cap. Writing past
        # it earns a 4xx per item; worse, the resulting partial view would make the
        # scope look authoritative. Truncate instead and mark the scope capped, which
        # disqualifies it from reconcile so nothing gets retired on a short view.
        cap = self._config.caps.max_items_per_tenant_and_kind
        already = self._kind_counts.get(kind, 0)
        remaining = max(0, cap - already)
        if len(resources) > remaining:
            logger.warning(
                "%s: %d resources exceed the remaining per-kind budget (%d of %d); "
                "truncating and skipping reconcile for this scope",
                kind.discriminator,
                len(resources),
                remaining,
                cap,
            )
            resources = resources[:remaining]
            report.capped = True

        items: list[InventoryItem] = []
        dropped: list[str] = []
        for resource in resources:
            if environment_id is not None:
                # Ensure env-scoped kinds carry the containment edge even if the surface
                # projection omitted it (spec §5.5).
                resource = {"environmentId": environment_id, **resource}
            try:
                item = map_resource(
                    kind, resource, caps=self._config.caps, dropped_out=dropped
                )
            except (AttributeValidationError, ValueError) as exc:
                # Fail the item and log; never silently drop a required key (spec §6).
                report.skipped_invalid += 1
                logger.warning("skipping invalid %s item: %s", kind.discriminator, exc)
                continue
            items.append(item)

        if dropped:
            report.dropped_attributes = sorted(set(dropped))
            logger.info(
                "%s: dropped schema-unlisted attributes %s",
                kind.discriminator,
                report.dropped_attributes,
            )

        self._upsert_all(items, report)
        self._kind_counts[kind] = already + report.upserted
        return items

    def _upsert_all(self, items: list[InventoryItem], report: ScopeReport) -> None:
        """Upsert items with bounded concurrency; order-independent (spec §5.1, §6).

        Any item whose upsert exhausts retries makes the scope **incomplete** (§7) so no
        reconcile fires for it. A 412 (concurrent writer won) is logged and counted as
        applied -- not a failure (§5.2).

        Every observed item is written **even when unchanged**: the server's reconcile
        decides drift by comparing each row's ``UpdatedAt`` against the pass watermark,
        so skipping a no-op write would make a live resource look abandoned and retire
        it. ``report.observed_keys`` records the applied natural keys, which the
        tenant-root sweep diffs against the server's current rows (the server refuses
        to reconcile tenant-rooted kinds itself).

        Results are collected **as each write completes** rather than in submission
        order, so progress can be reported while the batch is still in flight. Nothing
        downstream depends on the ordering: ``observed_keys`` is consumed as a set and
        ``upserted`` is a count.
        """
        if not items:
            return
        workers = max(1, self._config.max_concurrency)
        kind = report.scope.kind
        environment_id = report.scope.environment_id or None
        total = len(items)

        def _one(item: InventoryItem) -> tuple[str, bool]:
            try:
                self._inventory.upsert(item, run_id=self._run_id)
                return item.natural_key, True
            except PreconditionFailedError as exc:
                logger.info("precondition failed (concurrent writer won): %s", exc)
                return item.natural_key, True
            except Exception as exc:  # exhausted retries -> scope incomplete (§7)
                logger.error("upsert failed for %s: %s", item.natural_key, exc)
                report.error = report.error or f"upsert failed: {exc}"
                return item.natural_key, False

        results: list[tuple[str, bool]] = []
        if workers == 1:
            for item in items:
                results.append(_one(item))
                self._progress.upsert_progress(
                    kind, environment_id, len(results), total
                )
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_one, item) for item in items]
                for future in as_completed(futures):
                    # _one never raises, so result() cannot fail the batch here.
                    results.append(future.result())
                    self._progress.upsert_progress(
                        kind, environment_id, len(results), total
                    )

        report.upserted = sum(1 for _, ok in results if ok)
        report.observed_keys = [nk for nk, ok in results if ok]

    # -- reconcile gate -------------------------------------------------------------

    @staticmethod
    def _completed_scopes(
        reports: dict[ScopeKey, ScopeReport], full_crawl: bool
    ) -> list[ScopeKey]:
        """Scopes eligible for server reconcile (spec §6.3, §7).

        A scope qualifies only if it enumerated fully with no fatal error **and** (for
        tenant-root kinds) the run was a full crawl.
        """
        completed: list[ScopeKey] = []
        for scope, report in reports.items():
            if not report.complete:
                continue
            if scope.kind.is_tenant_root and not full_crawl:
                continue  # tenant-root exemption (§6.3)
            completed.append(scope)
        return completed
