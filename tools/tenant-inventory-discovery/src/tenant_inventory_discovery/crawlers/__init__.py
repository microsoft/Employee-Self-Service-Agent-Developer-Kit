"""Per-kind crawlers (spec §4).

Each crawler binds a :class:`~tenant_inventory_discovery.models.Kind` to the
:class:`~tenant_inventory_discovery.platform_clients.PlatformSurface` method that
enumerates it. Crawlers are intentionally declarative -- the enumerate/map/upsert loop
and completeness tracking live in the run engine
(:mod:`tenant_inventory_discovery.runner`) so every kind gets identical run semantics.
"""

from __future__ import annotations

from .base import Crawler
from .registry import ENV_SCOPED_CRAWLERS, TENANT_ROOT_CRAWLERS, all_crawlers

__all__ = [
    "Crawler",
    "ENV_SCOPED_CRAWLERS",
    "TENANT_ROOT_CRAWLERS",
    "all_crawlers",
]
