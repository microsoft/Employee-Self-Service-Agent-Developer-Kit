# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""WeveNova tenant-inventory write path, folded into the ess-planner MCP.

A discovery crawl persists through the *same* MCP the planner already uses rather
than a separate server process. The crawler
(``tenant_inventory_discovery.mcp_inventory.McpInventoryClient``) drives four stdio
tools -- ``probe``, ``list_items``, ``sync_inventory``, and ``server_info`` -- and
expects each to answer with a ``{ok, data|error}`` envelope whose error ``type`` is
drawn from the inventory taxonomy (``ThrottledError`` / ``NonRetryableApiError`` /
``InventoryApiError``). This module owns the server half of that contract.

It is a thin wrapper over the canonical ``HttpInventoryClient`` -- the exact client the
direct (non-MCP) write path uses -- so the OData URL construction, pagination, retry,
idempotency key, and PascalCase/camelCase normalization live in one place and cannot
drift. The crawler sends items in their *domain* shape, not the wire shape, precisely
so the attribute-array encoding stays the shared client's job; this module only
rebuilds the dataclass and lets that client encode the body.

Identity follows the ess-planner rule: the tenant and bearer token come from the
access token the planner core already resolved, never from a tool argument. The
``tenant_id`` the crawler sends is part of its wire contract, but the token's ``tid``
is authoritative for URL construction. ``WEVENOVA_ACCESS_TOKEN`` (CI escape hatch) and
``WEVENOVA_BASE_URL`` / ``WEVENOVA_VERIFY_TLS`` (dev-tunnel overrides) remain honored,
matching what ``discover_inventory.py`` passes into the child environment.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable, Optional

# agentconfig_planner -> mcp -> src -> ess-maker-skills -> solutions -> <repo root>.
# The tenant-inventory package is the canonical home of the Inventory API client and
# its wire encoders; reuse it rather than re-implementing the OData surface here.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, *([os.pardir] * 5)))
_TENANT_INVENTORY_SRC = os.path.join(
    _REPO_ROOT, "tools", "tenant-inventory-discovery", "src"
)
if _TENANT_INVENTORY_SRC not in sys.path:
    sys.path.insert(0, _TENANT_INVENTORY_SRC)

from tenant_inventory_discovery.config import (  # noqa: E402
    ENV_ACCESS_TOKEN,
    DiscoveryConfig,
    is_loopback_url,
)
from tenant_inventory_discovery.errors import (  # noqa: E402
    NonRetryableApiError,
    ThrottledError,
)
from tenant_inventory_discovery.inventory_client import HttpInventoryClient  # noqa: E402
from tenant_inventory_discovery.models import InventoryItem, Kind, SyncResult  # noqa: E402


#: Override that forces TLS verification on or off regardless of the loopback rule.
ENV_VERIFY_TLS = "WEVENOVA_VERIFY_TLS"


def verify_tls(base_url: str) -> bool:
    """Decide TLS verification for the inventory endpoint.

    Mirrors the kit's rule so ``--insecure`` behaves identically whether the write
    path is direct or through this server: an explicit ``WEVENOVA_VERIFY_TLS`` wins;
    otherwise a loopback dev tunnel (a self-signed certificate ``httpx`` rejects
    because it validates against ``certifi``, not the Windows store) is not verified
    while any real host is fully checked.
    """
    forced = os.environ.get(ENV_VERIFY_TLS, "").strip().lower()
    if forced in {"true", "1", "yes"}:
        return True
    if forced in {"false", "0", "no"}:
        return False
    return not is_loopback_url(base_url)


def item_from_payload(raw: dict[str, Any]) -> InventoryItem:
    """Rebuild a domain ``InventoryItem`` from the crawler's domain-shaped dict.

    The crawler deliberately sends items in their domain shape -- encoding to the
    ``{key, value}`` attribute array is ``HttpInventoryClient``'s job -- so this only
    reconstructs the dataclass and leaves the wire encoding to the shared client.
    """
    attributes = raw.get("attributes") or {}
    return InventoryItem(
        kind=Kind.from_discriminator(str(raw["kind"])),
        natural_key=str(raw["natural_key"]),
        attributes=dict(attributes),
        environment_id=raw.get("environment_id"),
        display_name=raw.get("display_name"),
        description=raw.get("description"),
    )


def sync_result_to_data(result: SyncResult) -> dict[str, Any]:
    """Serialize a ``SyncResult`` into the envelope ``data`` the crawler parses back.

    Keys are the camelCase the crawler reads (``submittedCount`` ... ``failedItems``
    with ``itemId`` / ``reason``); see ``McpInventoryClient.sync_inventory``.
    """
    return {
        "submittedCount": result.submitted_count,
        "upsertedCount": result.upserted_count,
        "retiredCount": result.retired_count,
        "retiredItemIds": list(result.retired_item_ids),
        "failedItems": [
            {"itemId": f.item_id, "reason": f.reason} for f in result.failed_items
        ],
    }


def error_envelope(exc: Exception) -> dict[str, Any]:
    """Map an inventory failure to a ``{ok: False, error: {type, message, ...}}`` body.

    Order matters: ``ThrottledError`` and ``NonRetryableApiError`` are both subclasses
    of ``InventoryApiError`` and must be matched first, and ``ThrottledError`` carries
    ``retry_after`` the crawler reconstructs. A client-side ``ValueError`` (an invalid
    payload -- ``SyncPayloadError`` subclasses it -- or an unknown kind discriminator)
    is a request the service would also reject identically, so it is reported as
    non-retryable. Anything else degrades to the retryable base type.
    """
    if isinstance(exc, ThrottledError):
        return {
            "ok": False,
            "error": {
                "type": "ThrottledError",
                "message": str(exc),
                "retryAfter": exc.retry_after,
            },
        }
    if isinstance(exc, (NonRetryableApiError, ValueError)):
        return {
            "ok": False,
            "error": {"type": "NonRetryableApiError", "message": str(exc)},
        }
    return {
        "ok": False,
        "error": {"type": "InventoryApiError", "message": str(exc)},
    }


class InventorySurface:
    """Server-side half of the four inventory tools, over one ``HttpInventoryClient``.

    One instance per server process, built lazily once the planner core has resolved a
    token. ``token_provider`` is re-read per request so a refreshed planner token is
    picked up; ``WEVENOVA_ACCESS_TOKEN`` still overrides it for CI.
    """

    def __init__(self, token_provider: Callable[[], str], tenant_id: str) -> None:
        self._token_provider = token_provider
        self._tenant_id = tenant_id
        self._config = DiscoveryConfig.from_env()
        self._base_url = self._config.require_base_url()
        self._client = HttpInventoryClient(
            tenant_id,
            config=self._config,
            auth_token_provider=self._resolve_token,
            verify=verify_tls(self._base_url),
        )

    def _resolve_token(self) -> str:
        override = os.environ.get(ENV_ACCESS_TOKEN, "").strip()
        if override:
            return override
        return self._token_provider()

    # -- the four tools, each returning a ``{ok, data|error}`` envelope ---------------

    def probe(self) -> dict[str, Any]:
        """Pre-flight the endpoint (``$top=1`` GET). ``data`` is null on success."""
        try:
            self._client.probe()
        except Exception as exc:  # noqa: BLE001 - taxonomy flows through the envelope
            return error_envelope(exc)
        return {"ok": True, "data": None}

    def list_items(
        self, *, kind: Optional[str] = None, environment_id: Optional[str] = None
    ) -> dict[str, Any]:
        """List non-retired rows, optionally narrowed to one kind / environment."""
        try:
            resolved_kind = Kind.from_discriminator(kind) if kind else None
            rows = self._client.list_items(
                kind=resolved_kind, environment_id=environment_id
            )
        except Exception as exc:  # noqa: BLE001
            return error_envelope(exc)
        return {"ok": True, "data": rows}

    def sync_inventory(
        self, *, items: list[dict[str, Any]], run_id: str = ""
    ) -> dict[str, Any]:
        """Persist the whole inventory; ``data`` carries the sync counts and failures."""
        try:
            domain_items = [item_from_payload(raw) for raw in items]
            result = self._client.sync_inventory(domain_items, run_id=run_id)
        except Exception as exc:  # noqa: BLE001
            return error_envelope(exc)
        return {"ok": True, "data": sync_result_to_data(result)}

    def server_info(self) -> dict[str, Any]:
        """Report the target and token strategy, never the token itself."""
        token_strategy = (
            ENV_ACCESS_TOKEN
            if os.environ.get(ENV_ACCESS_TOKEN, "").strip()
            else "planner access token (tid/oid from the signed-in principal)"
        )
        return {
            "ok": True,
            "data": {
                "baseUrl": self._base_url,
                "tenantId": self._tenant_id,
                "verifyTls": verify_tls(self._base_url),
                "tokenStrategy": token_strategy,
            },
        }

    def close(self) -> None:
        self._client.close()
