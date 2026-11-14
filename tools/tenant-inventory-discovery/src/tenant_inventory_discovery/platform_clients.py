"""Tenant-platform enumeration surfaces (spec §4, §6.2).

Each ``Kind`` is enumerated from a platform surface. In the real ADK these bind to the
existing tenant-platform client layer (BAP, Dataverse, Microsoft Graph, Copilot Studio) --
**do not add new SDKs if a client already exists** (spec §2). Here we define narrow
:class:`Protocol` surfaces the crawlers depend on, plus an in-memory
:class:`FakePlatform` for tests/dry-runs.

Every enumerator yields raw resources already projected into the §5.3 camelCase key
space and **must page to completion** -- an un-paged first page is a *partial crawl*
(spec §6). The ``paged`` flag on each yielded page lets crawlers assert full enumeration.

A surface also declares, via :meth:`PlatformSurface.tenant_wide_kinds`, which kinds it
enumerates across the **whole tenant** rather than a slice of it. That distinction is
load-bearing under whole-inventory sync, where an omitted row is a deleted row: only a
kind the surface can see completely may have its absences treated as deletions. A
surface that does not declare anything gets the safe reading -- nothing is complete, so
nothing it fails to mention is ever retired.

The distinction is not the same as :attr:`Kind.is_tenant_root`, which says where a row
is *filed*, not how much of the tenant was *looked at*. The ESS kit is the worked
example: it files ``Environment``, ``Connector`` and ``SharePointSite`` at the tenant
root but derives all three from the single environment configured during ``/setup``, so
only ``EntraApp`` is genuinely tenant-wide there.

.. warning::
   **Q-A (spec §9).** The specific surfaces for ``EntraApp`` (Graph app registrations),
   ``SharePointSite`` (Graph sites), and ``KnowledgeSource`` (Copilot Studio) are the
   *expected* sources and must be ``[verify]``-confirmed against the live platform APIs.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

from .models import Kind

# A discovered resource is a dict of §5.3 camelCase attributes.
Resource = dict[str, object]


@dataclass
class Page:
    """One page of enumeration results plus paging state (spec §6)."""

    items: list[Resource]
    is_last: bool


class PlatformSurface(Protocol):
    """The enumeration methods the crawlers call. [verify Q-A] real bindings."""

    # Tenant-root surfaces --------------------------------------------------------
    def list_environments(self, page_size: int) -> Iterator[Page]: ...
    def list_entra_apps(self, page_size: int) -> Iterator[Page]: ...
    def list_connectors(self, page_size: int) -> Iterator[Page]: ...
    def list_sharepoint_sites(self, page_size: int) -> Iterator[Page]: ...

    # Env-scoped surfaces ---------------------------------------------------------
    def list_connections(self, environment_id: str, page_size: int) -> Iterator[Page]: ...
    def list_knowledge_sources(
        self, environment_id: str, page_size: int
    ) -> Iterator[Page]: ...
    def list_extension_packs(
        self, environment_id: str, page_size: int
    ) -> Iterator[Page]: ...
    def list_scenario_templates(
        self, environment_id: str, page_size: int
    ) -> Iterator[Page]: ...

    # Coverage --------------------------------------------------------------------
    def tenant_wide_kinds(self) -> set[Kind]:
        """Tenant-root kinds this surface enumerates across the entire tenant.

        Optional: :func:`coverage_of` treats an undeclared surface as covering
        nothing, which is the non-destructive reading.
        """
        ...


def coverage_of(platform: object) -> frozenset[Kind]:
    """Which tenant-root kinds ``platform`` enumerates completely.

    Defaults to **nothing**. A surface that has not thought about the question is
    exactly the surface whose absences must not be trusted, so the fallback has to be
    the one that never deletes.
    """
    declare = getattr(platform, "tenant_wide_kinds", None)
    if declare is None:
        return frozenset()
    return frozenset(declare())


def _paginate(resources: list[Resource], page_size: int) -> Iterator[Page]:
    """Yield ``resources`` in pages, marking the final page ``is_last=True``."""
    if not resources:
        yield Page(items=[], is_last=True)
        return
    for start in range(0, len(resources), page_size):
        chunk = resources[start : start + page_size]
        is_last = start + page_size >= len(resources)
        yield Page(items=list(chunk), is_last=is_last)


@dataclass
class FakePlatform:
    """In-memory :class:`PlatformSurface` for tests and dry-runs.

    Populate the per-kind collections; env-scoped collections are keyed by
    ``environment_id``. Set an entry in :attr:`fail_on` to simulate a fatal enumeration
    error mid-crawl (used by the partial-crawl tests, §10).
    """

    environments: list[Resource] = field(default_factory=list)
    entra_apps: list[Resource] = field(default_factory=list)
    connectors: list[Resource] = field(default_factory=list)
    sharepoint_sites: list[Resource] = field(default_factory=list)
    connections: dict[str, list[Resource]] = field(default_factory=dict)
    knowledge_sources: dict[str, list[Resource]] = field(default_factory=dict)
    extension_packs: dict[str, list[Resource]] = field(default_factory=dict)
    scenario_templates: dict[str, list[Resource]] = field(default_factory=dict)

    # Method names that should raise to simulate a fatal enumeration error (§7).
    fail_on: set[str] = field(default_factory=set)

    #: Tenant-root kinds this fake claims to see completely. ``None`` means all of
    #: them, which is the honest answer for an in-memory tenant: the fake *is* the
    #: whole tenant. Narrow it to reproduce a surface that only sees a slice.
    tenant_wide: set[Kind] | None = None

    def tenant_wide_kinds(self) -> set[Kind]:
        if self.tenant_wide is None:
            return {kind for kind in Kind if kind.is_tenant_root}
        return set(self.tenant_wide)

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail_on:
            from .errors import PlatformError

            raise PlatformError(f"simulated enumeration failure in {name}")

    def list_environments(self, page_size: int) -> Iterator[Page]:
        self._maybe_fail("list_environments")
        return _paginate(self.environments, page_size)

    def list_entra_apps(self, page_size: int) -> Iterator[Page]:
        self._maybe_fail("list_entra_apps")
        return _paginate(self.entra_apps, page_size)

    def list_connectors(self, page_size: int) -> Iterator[Page]:
        self._maybe_fail("list_connectors")
        return _paginate(self.connectors, page_size)

    def list_sharepoint_sites(self, page_size: int) -> Iterator[Page]:
        self._maybe_fail("list_sharepoint_sites")
        return _paginate(self.sharepoint_sites, page_size)

    def list_connections(self, environment_id: str, page_size: int) -> Iterator[Page]:
        self._maybe_fail("list_connections")
        return _paginate(self.connections.get(environment_id, []), page_size)

    def list_knowledge_sources(self, environment_id: str, page_size: int) -> Iterator[Page]:
        self._maybe_fail("list_knowledge_sources")
        return _paginate(self.knowledge_sources.get(environment_id, []), page_size)

    def list_extension_packs(self, environment_id: str, page_size: int) -> Iterator[Page]:
        self._maybe_fail("list_extension_packs")
        return _paginate(self.extension_packs.get(environment_id, []), page_size)

    def list_scenario_templates(self, environment_id: str, page_size: int) -> Iterator[Page]:
        self._maybe_fail("list_scenario_templates")
        return _paginate(self.scenario_templates.get(environment_id, []), page_size)


def drain(pages: Iterable[Page]) -> tuple[list[Resource], bool]:
    """Consume every page; return ``(all_items, fully_enumerated)`` (spec §6).

    ``fully_enumerated`` is True only when the iterator yielded a page with
    ``is_last=True`` -- i.e. paging ran to completion. Any exception propagates to the
    caller, which marks the scope incomplete (§7).
    """
    items: list[Resource] = []
    saw_last = False
    for page in pages:
        items.extend(page.items)
        if page.is_last:
            saw_last = True
            break
    return items, saw_last
