"""Tenant Inventory discovery skill (ADK) -- admin-run crawler.

Enumerates a tenant's shared agent resources across eight kinds, maps each to an
``InventoryItem``, and submits the whole picture to the WeveNova Inventory API in one
``syncInventory`` call. The payload *is* the desired end state: anything Active the
service does not see in it is retired, so the crawl must be complete before it is sent.

Grounding: ``Tenant-Inventory-DesignSpec.md`` (not vendored here) + the ADK
implementation spec. See ``README.md`` for the ``[verify]`` items (Dep-1/Dep-3, Q-A).
"""

from __future__ import annotations

from .config import DiscoveryConfig, RetryPolicy
from .discovery_skill import DiscoverySkill
from .errors import (
    DiscoveryError,
    InventoryApiError,
    NonRetryableApiError,
    PlatformError,
    RunLockError,
    ThrottledError,
)
from .inventory_client import HttpInventoryClient, InventoryClient
from .mapping import SyncPayloadError
from .models import (
    FailedSyncItem,
    InventoryItem,
    Kind,
    RunSummary,
    Scope,
    ScopeKey,
    ScopeReport,
    SyncResult,
)
from .runner import DiscoveryRunner

__all__ = [
    "DiscoveryConfig",
    "RetryPolicy",
    "DiscoverySkill",
    "DiscoveryRunner",
    "HttpInventoryClient",
    "InventoryClient",
    "InventoryItem",
    "Kind",
    "Scope",
    "ScopeKey",
    "ScopeReport",
    "RunSummary",
    "SyncResult",
    "FailedSyncItem",
    "SyncPayloadError",
    "DiscoveryError",
    "PlatformError",
    "InventoryApiError",
    "NonRetryableApiError",
    "ThrottledError",
    "RunLockError",
]

__version__ = "0.1.0"
