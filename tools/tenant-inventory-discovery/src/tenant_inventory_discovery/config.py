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
    reconcile_action: str = "reconcile"

    # --- Crawl ---------------------------------------------------------------------
    # Per-platform enumeration page size.
    page_size: int = 200

    # Bounded parallelism for upserts. Conservative: the service counts rows per
    # (tenant, kind) on every create, so hammering it buys little.
    max_concurrency: int = 4

    # OData $top used when listing existing rows. The service caps $top at 500.
    list_page_size: int = 500

    retry: RetryPolicy = field(default_factory=RetryPolicy)
    caps: AttributeCaps = field(default_factory=AttributeCaps)

    # Reconcile compares a *client-supplied* watermark against *server-stamped*
    # UpdatedAt values. If the client clock runs ahead, rows written during the pass
    # can look older than the watermark and be wrongly retired. Backdating the
    # watermark by this allowance trades a little staleness (drift lingers one extra
    # run) for never retiring a row the crawl actually observed.
    clock_skew_allowance_seconds: int = 300

    # Per-tenant single-flight run lock TTL. Single-host interim mitigation; a
    # multi-host deployment needs a distributed lock.
    run_lock_ttl_seconds: int = 3600

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
