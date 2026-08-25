"""Tenant Inventory discovery skill (ADK) -- admin-run crawler.

Enumerates a tenant's shared agent resources across eight kinds and writes each as one
idempotent ``InventoryItem`` to the WeveNova Inventory API, then retires drift so the tenant picture stays current on every re-run.

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
    PreconditionFailedError,
    RunLockError,
    ThrottledError,
)
from .inventory_client import HttpInventoryClient, InventoryClient
from .models import (
    InventoryItem,
    Kind,
    RunSummary,
    Scope,
    ScopeKey,
    ScopeReport,
    ReconcileResult,
    UpsertResult,
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
    "ReconcileResult",
    "RunSummary",
    "UpsertResult",
    "DiscoveryError",
    "PlatformError",
    "InventoryApiError",
    "NonRetryableApiError",
    "PreconditionFailedError",
    "ThrottledError",
    "RunLockError",
]

__version__ = "0.1.0"
