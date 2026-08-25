"""Exception taxonomy (spec §8 error taxonomy: platform vs Inventory API vs validation)."""

from __future__ import annotations


class DiscoveryError(Exception):
    """Base class for all discovery-skill errors."""


class PlatformError(DiscoveryError):
    """A failure enumerating a resource from its platform surface (§6.2)."""


class InventoryApiError(DiscoveryError):
    """A failure talking to the WeveNova Inventory API (§8)."""


class NonRetryableApiError(InventoryApiError):
    """A 4xx the service will answer identically no matter how often it is asked.

    Schema violations, a missing role, and the per-(tenant, kind) row cap all land
    here. Retrying them burns the backoff budget and delays the run for nothing, so
    :func:`~tenant_inventory_discovery.inventory_client.with_retry` lets them through
    on the first attempt.
    """


class PreconditionFailedError(NonRetryableApiError):
    """HTTP 412 -- an ``If-Match`` ETag was stale; a concurrent writer won (§5.2).

    Not retryable in place: the caller must re-read the row and re-apply, because a
    blind replay would clobber whatever the concurrent writer just stored.
    """

    def __init__(self, natural_key: str, message: str = "precondition failed") -> None:
        super().__init__(f"{message} for {natural_key}")
        self.natural_key = natural_key


class ThrottledError(InventoryApiError):
    """HTTP 429 -- throttled; ``retry_after`` seconds requested by the server (§6)."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("throttled (429)")
        self.retry_after = retry_after


class RunLockError(DiscoveryError):
    """Another discovery run holds the per-tenant lock (interim D6 mitigation, §7)."""
