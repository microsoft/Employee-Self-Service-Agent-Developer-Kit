"""Run engine: enumerate -> map -> collect -> track completeness (spec §5, §6, §7).

This drives every crawler with identical run semantics and assembles the whole-tenant
sync payload. It deliberately **writes nothing**: under ``syncInventory`` the tenant's
inventory is replaced in one call whose absences retire, so no scope can safely be
submitted on its own. Deciding whether the assembled payload may be sent at all, and
sending it, lives in :mod:`tenant_inventory_discovery.discovery_skill`.

Keeping the two apart makes the sync gate -- the load-bearing safety property, and now
the only thing standing between a half-read tenant and mass retirement -- directly
unit-testable.
"""

from __future__ import annotations

import logging
import uuid

from .config import DiscoveryConfig
from .crawlers.base import Crawler
from .crawlers.registry import ENV_SCOPED_CRAWLERS, TENANT_ROOT_CRAWLERS
from .errors import PlatformError
from .inventory_client import InventoryClient
from .mapping import map_resource
from .models import (
    InventoryItem,
    Kind,
    RunSummary,
    ScopeKey,
    ScopeReport,
)
from .platform_clients import PlatformSurface, coverage_of, drain
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

        Nothing is written here. The run collects every mapped item into
        :attr:`RunSummary.payload`; deciding whether that payload is safe to submit --
        and submitting it -- belongs to
        :class:`~tenant_inventory_discovery.discovery_skill.DiscoverySkill`.

        ``environment_ids=None`` performs a **full crawl**: every environment the
        Environment kind yielded is visited. Passing an explicit subset performs a
        **partial crawl**, which is still safe to sync -- the skill carries forward the
        service's existing rows for every scope this run did not visit, so an
        unvisited environment is present in the payload rather than absent from it.
        """
        full_crawl = environment_ids is None
        summary = RunSummary(correlation_id=run_id or f"run-{uuid.uuid4()}")
        summary.full_crawl = full_crawl
        self._run_id = summary.correlation_id
        # Which tenant-root kinds this platform sees in full. Env-scoped kinds are
        # always covered for an environment the run actually visited: the surface is
        # asked for that environment by id, so "everything in it" is what it returns.
        coverage = coverage_of(self._platform)
        reports: dict[ScopeKey, ScopeReport] = {}
        discovered_env_ids: list[str] = []
        payload: list[InventoryItem] = []
        # Rows collected per kind this run. The server caps rows per (tenant, kind) --
        # not per scope -- so this counter spans every environment in the run.
        self._kind_counts: dict[Kind, int] = {}

        # Phase 1 -- tenant-root kinds first (spec §4 crawl order). The Environment crawl
        # yields the environment list that drives Phase 2.
        self._progress.phase("Reading tenant-wide resources")
        for crawler in TENANT_ROOT_CRAWLERS:
            report, items = self._crawl_tenant_root(crawler)
            report.covered = crawler.kind in coverage
            reports[report.scope] = report
            summary.scopes.append(report)
            payload.extend(items)
            if crawler.kind is Kind.ENVIRONMENT:
                discovered_env_ids = [
                    str(it.attributes["environmentId"]) for it in items
                ]

        target_envs = discovered_env_ids if full_crawl else list(environment_ids or [])

        # Phase 2 -- env-scoped kinds inside each target environment (spec §4).
        for env_id in target_envs:
            self._progress.phase(f"Reading resources in {env_id}")
            for crawler in ENV_SCOPED_CRAWLERS:
                report, items = self._crawl_env(crawler, env_id)
                report.covered = True
                reports[report.scope] = report
                summary.scopes.append(report)
                payload.extend(items)

        summary.payload = payload
        summary.submitted_counts = {}
        for item in payload:
            key = item.kind.discriminator
            summary.submitted_counts[key] = summary.submitted_counts.get(key, 0) + 1
        summary.authoritative_scopes = [
            scope for scope, report in reports.items() if report.authoritative
        ]
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
        items = self._map_and_collect(crawler.kind, resources, report)
        self._progress.scope_finished(report)
        return report, items

    def _crawl_env(
        self, crawler: Crawler, environment_id: str
    ) -> tuple[ScopeReport, list[InventoryItem]]:
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
            return report, []

        report.fully_enumerated = fully
        self._progress.scope_enumerated(
            crawler.kind, environment_id, len(resources), fully
        )
        items = self._map_and_collect(
            crawler.kind, resources, report, environment_id
        )
        self._progress.scope_finished(report)
        return report, items

    def _map_and_collect(
        self,
        kind: Kind,
        resources: list[dict[str, object]],
        report: ScopeReport,
        environment_id: str | None = None,
    ) -> list[InventoryItem]:
        """Map a scope's resources into payload items. Writes nothing.

        Under whole-inventory sync there is no per-scope write. Every scope's items are
        accumulated and submitted once, at the end, by the skill -- which is also the
        only place that can decide whether submitting is safe at all.
        """
        report.enumerated = len(resources)

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
                # This also withholds the whole sync: a resource that exists but cannot
                # be described would be omitted from the payload, and omission retires.
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

        items = self._enforce_kind_cap(kind, items, report)

        report.mapped = len(items)
        report.observed_keys = [i.natural_key for i in items]
        self._kind_counts[kind] = self._kind_counts.get(kind, 0) + len(items)
        self._progress.scope_mapped(kind, environment_id, len(items), len(resources))
        return items

    def _enforce_kind_cap(
        self, kind: Kind, items: list[InventoryItem], report: ScopeReport
    ) -> list[InventoryItem]:
        """Trim a kind to the server's per-(tenant, kind) row ceiling.

        The cap is a storage limit, not a reading failure: the service refuses a
        payload carrying more than this many rows of one kind, and could not have
        stored them anyway. Truncating is therefore the only way to sync at all, and
        the rows dropped here are rows the inventory has never been able to hold.

        Selection is **sorted by natural key**, not enumeration order. An arbitrary
        prefix would pick a different 50 whenever a platform reordered its listing, and
        because absence retires, that churn would retire and revive rows on alternating
        runs. A stable key makes the chosen set the same every pass.

        The counter spans environments, because the server counts rows per
        ``(tenant, kind)`` rather than per scope.
        """
        cap = self._config.caps.max_items_per_tenant_and_kind
        already = self._kind_counts.get(kind, 0)
        remaining = max(0, cap - already)
        if len(items) <= remaining:
            return items

        items = sorted(items, key=lambda i: i.natural_key)
        kept, dropped = items[:remaining], len(items) - remaining
        report.capped = True
        report.truncated = dropped
        logger.warning(
            "%s: %d rows exceed the per-kind cap of %d; syncing the first %d by "
            "natural key and dropping %d",
            kind.discriminator,
            already + len(items),
            cap,
            len(kept),
            dropped,
        )
        return kept

    # -- sync gate -------------------------------------------------------------------

    @staticmethod
    def _completed_scopes(reports: dict[ScopeKey, ScopeReport]) -> list[ScopeKey]:
        """Scopes read without error (spec §7)."""
        return [scope for scope, report in reports.items() if report.complete]
