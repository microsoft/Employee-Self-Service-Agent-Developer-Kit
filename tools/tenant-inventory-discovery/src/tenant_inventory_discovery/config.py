"""Skill configuration: endpoints, paging, concurrency, retry, and caps.

The Inventory API is an OData surface rooted on the tenant shard::

    {base_url}/{api_segment}/tenants('{tenantId}')/agentConfigurationInventoryItems

``base_url`` defaults to the production WeveNova origin so that persisting is the
skill's default behavior -- writing to the inventory is the whole point of a discovery
pass, so it should not require opting in. Non-production rings and dev tunnels override
it via ``--base-url`` or ``WEVENOVA_BASE_URL``; :meth:`DiscoveryConfig.require_base_url`
still fails loudly if it is explicitly cleared.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .schemas import AttributeCaps

#: Environment variables the kit bridge reads to configure the live write path.
ENV_BASE_URL = "WEVENOVA_BASE_URL"
ENV_ACCESS_TOKEN = "WEVENOVA_ACCESS_TOKEN"

#: Production WeveNova service origin. Taken from the service's own configuration
#: (``Weve.settings.ini`` -> ``UriPrefix=https://substrate.office.com/weveb2/``); the
#: ``api/beta`` OData prefix below is registered in ``AppBuilderExtensions`` via
#: ``MapODataRoute(routeName: "ODataRouteBeta", routePrefix: "api/beta", ...)``.
DEFAULT_INVENTORY_BASE_URL = "https://substrate.office.com/weveb2"

#: OAuth resource the WeveNova service accepts tokens for.
INVENTORY_SCOPE = "https://substrate.office.com/weve/.default"

#: Hosts that cannot be reached from off-box, so a self-signed certificate on them
#: cannot be a man-in-the-middle.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def is_loopback_url(url: str | None) -> bool:
    """Is ``url`` served from this machine?

    Decides TLS verification. The dev tunnel serves a self-signed certificate, which
    ``httpx`` rejects because it validates against ``certifi`` rather than the Windows
    certificate store that PowerShell and Insomnia use -- so the tunnel looks
    unreachable when it is only a trust-store difference.

    Relaxing verification for loopback only is what keeps that convenience from
    becoming a hazard: traffic to ``localhost`` never leaves the machine, so there is
    no position from which to intercept it, while any real host still gets a full
    certificate check and must opt out explicitly.
    """
    if not url:
        return False
    host = urlparse(url).hostname
    return host is not None and host.lower() in LOOPBACK_HOSTS


@dataclass
class RetryPolicy:
    """Bounded exponential backoff, honoring ``Retry-After`` on 429."""

    max_attempts: int = 5
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 30.0
    backoff_multiplier: float = 2.0


@dataclass
class DiscoveryConfig:
    """Top-level, tunable skill configuration."""

    # --- Inventory API -------------------------------------------------------------
    # Service origin. Defaults to production; override for other rings or a dev
    # tunnel. See module docstring.
    inventory_base_url: str | None = DEFAULT_INVENTORY_BASE_URL
    api_segment: str = "api/beta"
    entity_set: str = "agentConfigurationInventoryItems"
    sync_action: str = "syncInventory"

    # --- Crawl ---------------------------------------------------------------------
    # Per-platform enumeration page size.
    page_size: int = 200

    # OData $top used when listing existing rows. The service caps $top at 500.
    list_page_size: int = 500

    # --- Timeouts ------------------------------------------------------------------
    # Split three ways because the calls have wildly different shapes. A connect that
    # has not landed in 10s is a dead host, not a slow one. An ordinary read is a
    # single page and should not need 30s. The whole-inventory sync is the outlier: one
    # request drives up to ``max_items_per_sync`` server-side writes plus the
    # retirement sweep, so it routinely runs for minutes. Holding it to the read budget
    # is what turns a *working* sync into a timeout, a retry, and a re-POST of the
    # entire payload onto a service that was already busy applying the first one.
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 30.0
    sync_timeout_seconds: float = 600.0

    retry: RetryPolicy = field(default_factory=RetryPolicy)
    # The sync gets its own, much shallower budget. Every attempt re-sends the entire
    # payload, so the default five would pile ~50 minutes of duplicated work onto a
    # service that is merely slow. One retry is enough to ride out a dropped
    # connection -- and because it carries the same ``Idempotency-Key``, a server that
    # *did* finish replays its original answer instead of running the payload twice.
    sync_retry: RetryPolicy = field(
        default_factory=lambda: RetryPolicy(max_attempts=2, base_delay_seconds=2.0)
    )
    caps: AttributeCaps = field(default_factory=AttributeCaps)

    # Per-tenant single-flight run lock TTL. Single-host interim mitigation; a
    # multi-host deployment needs a distributed lock.
    run_lock_ttl_seconds: int = 3600

    @property
    def max_items_per_sync(self) -> int:
        """Ceiling on items in one ``syncInventory`` payload; more earns a 400.

        The service computes this as ``MaxItemsPerTenantAndKind x <kind count>`` off
        its own enum, so it grows automatically when a kind is added. Deriving it the
        same way here -- rather than hard-coding 400 -- keeps the two in step.
        """
        from .models import Kind

        return self.caps.max_items_per_tenant_and_kind * len(Kind)

    @classmethod
    def from_env(cls, **overrides: object) -> DiscoveryConfig:
        """Build a config, defaulting ``inventory_base_url`` from the environment."""
        base_url = (
            overrides.pop("inventory_base_url", None)
            or os.environ.get(ENV_BASE_URL)
            or DEFAULT_INVENTORY_BASE_URL
        )
        return cls(inventory_base_url=base_url, **overrides)  # type: ignore[arg-type]

    def require_base_url(self) -> str:
        """Return the configured base URL, or explain how to supply it."""
        if not self.inventory_base_url:
            raise ValueError(
                "No Inventory API base URL configured. Pass --base-url or set "
                f"{ENV_BASE_URL} to the WeveNova service origin."
            )
        return self.inventory_base_url.rstrip("/")
