# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Server-side contract for the inventory write path folded into the ess-planner MCP.

The discovery crawler drives four stdio tools -- ``probe``, ``list_items``,
``sync_inventory``, ``server_info`` -- and unwraps a ``{ok, data|error}`` envelope from
each, rebuilding the inventory error taxonomy from ``error.type``. ``InventorySurface``
owns that server half over the canonical ``HttpInventoryClient``, so these pin the
envelope shapes, the error-taxonomy mapping, the domain<->wire helpers, the TLS rule,
and the one guarantee that makes ``server_info`` safe to print: it never carries the
token.

No network and no real HTTP client: ``HttpInventoryClient`` is monkeypatched to a stub
so every call is exercised in-process. The suite's pytest config promotes warnings to
errors, which is exactly why the real client (an unclosed ``httpx.Client`` would warn
on GC) is never constructed here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[3]
PLANNER_DIR = REPO_ROOT / "solutions" / "ess-maker-skills" / "src" / "mcp" / "agentconfig_planner"
sys.path.insert(0, str(PLANNER_DIR))

import inventory_surface  # noqa: E402

# inventory_surface puts the tenant-inventory package on sys.path at import, so these
# resolve without a second bootstrap.
from tenant_inventory_discovery.errors import (  # noqa: E402
    InventoryApiError,
    NonRetryableApiError,
    ThrottledError,
)
from tenant_inventory_discovery.models import (  # noqa: E402
    FailedSyncItem,
    InventoryItem,
    Kind,
    SyncResult,
)


class _StubClient:
    """Stand-in for ``HttpInventoryClient``: records calls, never touches the network.

    Constructed with the exact signature ``InventorySurface`` uses so the surface's
    wiring (tenant id, token provider, TLS decision) is observable after construction.
    """

    def __init__(self, tenant_id, *, config=None, auth_token_provider=None, verify=True, **_kw):
        self.tenant_id = tenant_id
        self.config = config
        self.auth_token_provider = auth_token_provider
        self.verify = verify
        self.probe_calls = 0
        self.list_calls: list[tuple] = []
        self.sync_calls: list[tuple] = []
        self.closed = False
        self.probe_raises: Exception | None = None
        self.list_raises: Exception | None = None
        self.list_return: list[dict] = []
        self.sync_raises: Exception | None = None
        self.sync_return: SyncResult | None = None

    def probe(self):
        self.probe_calls += 1
        if self.probe_raises is not None:
            raise self.probe_raises

    def list_items(self, *, kind=None, environment_id=None):
        self.list_calls.append((kind, environment_id))
        if self.list_raises is not None:
            raise self.list_raises
        return self.list_return

    def sync_inventory(self, items, *, run_id=""):
        self.sync_calls.append((list(items), run_id))
        if self.sync_raises is not None:
            raise self.sync_raises
        return self.sync_return

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Never inherit the developer's real token, TLS override, or base URL."""
    monkeypatch.delenv("WEVENOVA_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("WEVENOVA_VERIFY_TLS", raising=False)
    monkeypatch.delenv("WEVENOVA_BASE_URL", raising=False)


@pytest.fixture
def make_surface(monkeypatch):
    """Build an ``InventorySurface`` over the stub client, returning (surface, stub)."""

    def _make(token_provider=lambda: "planner-token", tenant_id="contoso.onmicrosoft.com"):
        monkeypatch.setattr(inventory_surface, "HttpInventoryClient", _StubClient)
        surface = inventory_surface.InventorySurface(token_provider, tenant_id)
        return surface, surface._client

    return _make


class TestTlsVerificationFollowsTheTarget:
    """Loopback dev tunnels aren't verified; any real host is, unless overridden.

    Ports the standalone server's rule so ``--insecure`` behaves identically whether a
    crawl writes directly or through this MCP.
    """

    @pytest.mark.parametrize(
        "url",
        ["https://localhost:444/weveb2", "https://127.0.0.1:444/weveb2", "https://[::1]:444/weveb2"],
    )
    def test_loopback_is_not_verified(self, url):
        assert inventory_surface.verify_tls(url) is False

    def test_a_real_host_is_verified(self):
        assert inventory_surface.verify_tls("https://substrate.office.com/weveb2") is True

    def test_a_lookalike_host_is_verified(self):
        # 'localhost.evil.test' is not loopback -- substring matching would be a hole.
        assert inventory_surface.verify_tls("https://localhost.evil.test/weveb2") is True

    @pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE"])
    def test_explicit_true_overrides_the_loopback_rule(self, monkeypatch, value):
        monkeypatch.setenv("WEVENOVA_VERIFY_TLS", value)
        assert inventory_surface.verify_tls("https://localhost:444/weveb2") is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "FALSE"])
    def test_explicit_false_overrides_a_real_host(self, monkeypatch, value):
        monkeypatch.setenv("WEVENOVA_VERIFY_TLS", value)
        assert inventory_surface.verify_tls("https://substrate.office.com/weveb2") is False


class TestErrorEnvelopeTaxonomy:
    """``error.type`` is the crawler's only signal for retryable vs not, so the mapping
    and the ``retryAfter`` passthrough are load-bearing."""

    def test_throttled_keeps_retry_after(self):
        env = inventory_surface.error_envelope(ThrottledError(retry_after=12.5))
        assert env["ok"] is False
        assert env["error"]["type"] == "ThrottledError"
        assert env["error"]["retryAfter"] == 12.5

    def test_non_retryable_maps_to_non_retryable(self):
        env = inventory_surface.error_envelope(NonRetryableApiError("bad request"))
        assert env["error"]["type"] == "NonRetryableApiError"
        assert "retryAfter" not in env["error"]

    def test_plain_value_error_is_non_retryable(self):
        # An unknown kind discriminator / invalid payload is a request the service
        # would reject identically, so it must not burn the retry budget.
        env = inventory_surface.error_envelope(ValueError("Unknown kind discriminator: 'Nope'"))
        assert env["error"]["type"] == "NonRetryableApiError"

    def test_generic_inventory_error_is_retryable(self):
        env = inventory_surface.error_envelope(InventoryApiError("POST ... -> 503"))
        assert env["error"]["type"] == "InventoryApiError"

    def test_unknown_exception_degrades_to_retryable_base(self):
        env = inventory_surface.error_envelope(RuntimeError("socket died"))
        assert env["error"]["type"] == "InventoryApiError"


class TestDomainWireHelpers:
    def test_item_from_payload_round_trips_the_domain_shape(self):
        raw = {
            "kind": "Connection",
            "natural_key": "env-1:conn-9",
            "attributes": {"environmentId": "env-1", "connectionId": "conn-9"},
            "environment_id": "env-1",
            "display_name": "My Connection",
            "description": "desc",
        }
        item = inventory_surface.item_from_payload(raw)
        assert isinstance(item, InventoryItem)
        assert item.kind is Kind.CONNECTION
        assert item.natural_key == "env-1:conn-9"
        assert item.attributes == {"environmentId": "env-1", "connectionId": "conn-9"}
        assert item.environment_id == "env-1"
        assert item.display_name == "My Connection"
        assert item.description == "desc"

    def test_item_from_payload_tolerates_missing_optionals(self):
        item = inventory_surface.item_from_payload({"kind": "Environment", "natural_key": "env-1"})
        assert item.attributes == {}
        assert item.environment_id is None
        assert item.display_name is None

    def test_item_from_payload_rejects_an_unknown_kind(self):
        with pytest.raises(ValueError, match="Unknown kind discriminator"):
            inventory_surface.item_from_payload({"kind": "Nope", "natural_key": "x"})

    def test_sync_result_to_data_is_the_camelcase_the_crawler_reads(self):
        result = SyncResult(
            submitted_count=5,
            upserted_count=4,
            retired_count=1,
            retired_item_ids=["Environment:old"],
            failed_items=[FailedSyncItem(item_id="Connection:env-1:c", reason="missing parent")],
        )
        data = inventory_surface.sync_result_to_data(result)
        assert data == {
            "submittedCount": 5,
            "upsertedCount": 4,
            "retiredCount": 1,
            "retiredItemIds": ["Environment:old"],
            "failedItems": [{"itemId": "Connection:env-1:c", "reason": "missing parent"}],
        }


class TestTokenResolution:
    def test_defaults_to_the_planner_token(self, make_surface):
        surface, _ = make_surface(token_provider=lambda: "planner-token")
        assert surface._resolve_token() == "planner-token"

    def test_env_override_wins(self, make_surface, monkeypatch):
        monkeypatch.setenv("WEVENOVA_ACCESS_TOKEN", "ci-token")
        surface, _ = make_surface(token_provider=lambda: "planner-token")
        assert surface._resolve_token() == "ci-token"

    def test_the_resolver_is_wired_into_the_client(self, make_surface):
        surface, stub = make_surface(token_provider=lambda: "planner-token")
        # The client authenticates through the surface's resolver, not a raw provider.
        assert stub.auth_token_provider == surface._resolve_token


class TestServerInfoDoesNotLeak:
    def test_reports_the_target_and_strategy_without_the_token(self, make_surface):
        surface, _ = make_surface(token_provider=lambda: "super-secret-token")
        info = surface.server_info()
        assert info["ok"] is True
        data = info["data"]
        assert data["baseUrl"] == "https://substrate.office.com/weveb2"
        assert data["tenantId"] == "contoso.onmicrosoft.com"
        assert data["verifyTls"] is True
        assert "planner access token" in data["tokenStrategy"]
        # The whole point of server_info is that it is safe to print and log.
        assert "super-secret-token" not in repr(info)

    def test_reports_the_env_var_as_the_strategy(self, make_surface, monkeypatch):
        monkeypatch.setenv("WEVENOVA_ACCESS_TOKEN", "super-secret-token")
        surface, _ = make_surface()
        info = surface.server_info()
        assert info["data"]["tokenStrategy"] == "WEVENOVA_ACCESS_TOKEN"
        assert "super-secret-token" not in repr(info)


class TestProbeEnvelope:
    def test_success_is_ok_with_null_data(self, make_surface):
        surface, stub = make_surface()
        assert surface.probe() == {"ok": True, "data": None}
        assert stub.probe_calls == 1

    def test_throttle_flows_through_as_an_error_envelope(self, make_surface):
        surface, stub = make_surface()
        stub.probe_raises = ThrottledError(retry_after=30)
        env = surface.probe()
        assert env["ok"] is False
        assert env["error"]["type"] == "ThrottledError"
        assert env["error"]["retryAfter"] == 30


class TestListItemsEnvelope:
    def test_resolves_the_kind_discriminator_and_passes_the_scope(self, make_surface):
        surface, stub = make_surface()
        stub.list_return = [{"naturalKey": "env-1"}]
        env = surface.list_items(kind="Environment", environment_id="env-1")
        assert env == {"ok": True, "data": [{"naturalKey": "env-1"}]}
        assert stub.list_calls == [(Kind.ENVIRONMENT, "env-1")]

    def test_no_kind_lists_everything(self, make_surface):
        surface, stub = make_surface()
        surface.list_items()
        assert stub.list_calls == [(None, None)]

    def test_an_unknown_kind_is_a_non_retryable_envelope(self, make_surface):
        surface, stub = make_surface()
        env = surface.list_items(kind="Bogus")
        assert env["ok"] is False
        assert env["error"]["type"] == "NonRetryableApiError"
        # Resolution failed before any network call.
        assert stub.list_calls == []


class TestSyncInventoryEnvelope:
    def test_builds_domain_items_and_returns_the_counts(self, make_surface):
        surface, stub = make_surface()
        stub.sync_return = SyncResult(submitted_count=1, upserted_count=1)
        env = surface.sync_inventory(
            items=[{"kind": "Environment", "natural_key": "env-1", "attributes": {"environmentId": "env-1"}}],
            run_id="run-42",
        )
        assert env == {
            "ok": True,
            "data": {
                "submittedCount": 1,
                "upsertedCount": 1,
                "retiredCount": 0,
                "retiredItemIds": [],
                "failedItems": [],
            },
        }
        sent_items, run_id = stub.sync_calls[0]
        assert run_id == "run-42"
        assert isinstance(sent_items[0], InventoryItem)
        assert sent_items[0].kind is Kind.ENVIRONMENT

    def test_a_bad_payload_item_is_a_non_retryable_envelope(self, make_surface):
        surface, stub = make_surface()
        env = surface.sync_inventory(items=[{"kind": "Nope", "natural_key": "x"}])
        assert env["ok"] is False
        assert env["error"]["type"] == "NonRetryableApiError"
        # The encode failed client-side; nothing was sent.
        assert stub.sync_calls == []

    def test_a_service_failure_flows_through_the_taxonomy(self, make_surface):
        surface, stub = make_surface()
        stub.sync_raises = NonRetryableApiError("POST ... -> 400: row cap")
        env = surface.sync_inventory(items=[{"kind": "Environment", "natural_key": "env-1"}])
        assert env["error"]["type"] == "NonRetryableApiError"


def test_close_releases_the_underlying_client(make_surface):
    surface, stub = make_surface()
    surface.close()
    assert stub.closed is True
