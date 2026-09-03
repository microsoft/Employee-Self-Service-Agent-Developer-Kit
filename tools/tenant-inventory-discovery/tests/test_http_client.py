"""HTTP-level contract tests for :class:`HttpInventoryClient`.

These pin the parts of the client that the in-memory fake cannot see: the OData
route, whole-inventory ``syncInventory`` body, idempotency header, retry taxonomy,
and the read/probe calls that stayed unchanged across the write API migration.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tenant_inventory_discovery import inventory_client as client_module
from tenant_inventory_discovery.config import DiscoveryConfig, RetryPolicy
from tenant_inventory_discovery.errors import (
    InventoryApiError,
    NonRetryableApiError,
    ThrottledError,
)
from tenant_inventory_discovery.inventory_client import (
    HttpInventoryClient,
    odata_key_literal,
)
from tenant_inventory_discovery.mapping import map_resource
from tenant_inventory_discovery.models import Kind, encode_item_id

_BASE = "https://inventory.example.test"
_TENANT = "contoso.onmicrosoft.com"
_COLLECTION = (
    f"{_BASE}/api/beta/tenants('{_TENANT}')/agentConfigurationInventoryItems"
)
_ENV_ID = "5b0c4f4e-1111-4c2a-9a1f-0f9f2b3c4d5e"


def _config(**overrides) -> DiscoveryConfig:
    """Keep tests fast unless a case opts into a retry budget."""
    overrides.setdefault("retry", RetryPolicy(max_attempts=1, base_delay_seconds=0.0))
    return DiscoveryConfig(inventory_base_url=_BASE, **overrides)


def _client(handler, *, config: DiscoveryConfig | None = None) -> HttpInventoryClient:
    return HttpInventoryClient(
        _TENANT,
        config=config or _config(),
        auth_token_provider=lambda: "test-token",
        transport=httpx.MockTransport(handler),
    )


def _environment_item(env_id: str = _ENV_ID):
    return map_resource(
        Kind.ENVIRONMENT,
        {"environmentId": env_id, "region": "unitedstates"},
        display_name="Production",
    )


def _connection_item():
    return map_resource(
        Kind.CONNECTION,
        {
            "connectionId": "cr-1",
            "environmentId": _ENV_ID,
            "connectorId": "shared_service-now",
            "status": "Active",
        },
        display_name="ServiceNow ref",
    )


class TestSyncInventory:
    """The write path is one whole-tenant POST, never per-row writes."""

    def test_posts_the_bound_action_with_items_as_the_only_body_key(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "submittedCount": 2,
                    "upsertedCount": 2,
                    "retiredCount": 1,
                    "retiredItemIds": ["Connector:gone"],
                    "failedItems": [],
                },
            )

        result = _client(handler).sync_inventory(
            [_environment_item(), _connection_item()], run_id="run-1"
        )

        assert len(seen) == 1
        request = seen[0]
        assert request.method == "POST"
        assert str(request.url) == f"{_COLLECTION}/syncInventory"
        assert "If-Match" not in request.headers

        body = json.loads(request.content)
        assert set(body) == {"items"}
        assert len(body["items"]) == 2

        env_body = body["items"][0]
        assert env_body["tenantId"] == _TENANT
        assert env_body["kind"] == "Environment"
        assert env_body["naturalKey"] == _ENV_ID
        assert env_body["displayName"] == "Production"
        assert env_body["validationStatus"] == "Unvalidated"
        assert env_body["attributes"] == [
            {"key": "environmentId", "value": _ENV_ID},
            {"key": "region", "value": "unitedstates"},
        ]
        for forbidden in ("source", "submittedById", "state", "etag", "connectorId"):
            assert forbidden not in env_body

        connection_body = body["items"][1]
        assert connection_body["environmentId"] == _ENV_ID
        assert connection_body["attributes"] == [
            {"key": "connectionId", "value": "cr-1"},
            {"key": "connectorId", "value": "shared_service-now"},
            {"key": "environmentId", "value": _ENV_ID},
            {"key": "status", "value": "Active"},
        ]

        assert result.submitted_count == 2
        assert result.upserted_count == 2
        assert result.retired_item_ids == ["Connector:gone"]

    def test_idempotency_key_is_forwarded_and_scoped_to_the_run(self):
        """A retry within a pass replays; a later pass must really apply."""
        keys: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            keys.append(request.headers["Idempotency-Key"])
            return httpx.Response(200, json={"submittedCount": 1})

        item = _environment_item()
        client = _client(handler)
        client.sync_inventory([item], run_id="run-1")
        client.sync_inventory([item], run_id="run-1")
        client.sync_inventory([item], run_id="run-2")

        assert keys[0] == keys[1]
        assert keys[2] != keys[0]

    def test_parses_failed_items_as_partial_success(self):
        """A 200 with failedItems is not a transport failure; it is diagnostic data."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "submittedCount": 2,
                    "upsertedCount": 1,
                    "retiredCount": 0,
                    "retiredItemIds": [],
                    "failedItems": [
                        {"itemId": "Connection:missing-env", "reason": "no parent"}
                    ],
                },
            )

        result = _client(handler).sync_inventory([_environment_item()], run_id="r")

        assert result.submitted_count == 2
        assert result.upserted_count == 1
        assert result.failed_item_ids == ["Connection:missing-env"]
        assert result.failed_items[0].reason == "no parent"

    def test_empty_payload_never_reaches_the_wire(self):
        """Empty is legal on the service, but it would retire the whole tenant."""
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={})

        with pytest.raises(ValueError, match="empty payload"):
            _client(handler).sync_inventory([], run_id="r")

        assert calls == []


class TestErrorsAndRetry:
    """Only transient failures retry, and every retry must use the same key."""

    @pytest.mark.parametrize("status", [400, 403])
    def test_4xx_other_than_throttle_is_non_retryable(self, status: int):
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(status, text="request will not become valid")

        config = _config(retry=RetryPolicy(max_attempts=4, base_delay_seconds=0.0))
        with pytest.raises(NonRetryableApiError, match="request will not become valid"):
            _client(handler, config=config).sync_inventory([_environment_item()], run_id="r")

        assert len(calls) == 1

    def test_429_is_retried_after_the_server_delay_with_the_same_key(self, monkeypatch):
        keys: list[str] = []
        sleeps: list[float] = []
        monkeypatch.setattr(client_module.time, "sleep", sleeps.append)

        def handler(request: httpx.Request) -> httpx.Response:
            keys.append(request.headers["Idempotency-Key"])
            if len(keys) < 3:
                return httpx.Response(429, headers={"Retry-After": "0.25"})
            return httpx.Response(200, json={"submittedCount": 1})

        config = _config(sync_retry=RetryPolicy(max_attempts=4, base_delay_seconds=0.0))
        _client(handler, config=config).sync_inventory([_environment_item()], run_id="r")

        assert len(keys) == 3
        assert len(set(keys)) == 1
        assert sleeps == [0.25, 0.25]

    def test_5xx_is_retried_with_exponential_backoff(self, monkeypatch):
        calls: list[httpx.Request] = []
        sleeps: list[float] = []
        monkeypatch.setattr(client_module.time, "sleep", sleeps.append)

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) < 3:
                return httpx.Response(503)
            return httpx.Response(200, json={"submittedCount": 1})

        config = _config(
            sync_retry=RetryPolicy(
                max_attempts=4,
                base_delay_seconds=0.5,
                backoff_multiplier=2.0,
                max_delay_seconds=10.0,
            )
        )
        _client(handler, config=config).sync_inventory([_environment_item()], run_id="r")

        assert len(calls) == 3
        assert sleeps == [0.5, 1.0]

    def test_the_sync_does_not_inherit_the_deep_read_retry_budget(self, monkeypatch):
        """Every sync attempt re-sends the whole payload.

        The read budget is five attempts, which is right for a cheap paged GET and
        badly wrong for a call that can drive hundreds of server-side writes: retrying
        it five times piles ~50 minutes of duplicated work onto a service whose only
        problem was being slow. The sync gets its own, shallower budget.
        """
        monkeypatch.setattr(client_module.time, "sleep", lambda _s: None)
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(503)

        with pytest.raises(InventoryApiError):
            _client(handler).sync_inventory([_environment_item()], run_id="r")

        assert len(calls) == DiscoveryConfig().sync_retry.max_attempts
        assert len(calls) < DiscoveryConfig().retry.max_attempts

    def test_a_slow_sync_is_not_mistaken_for_a_dead_endpoint(self, monkeypatch):
        """The timeout message must name the budget and say the write may have landed.

        A bare ``ReadTimeout`` reads exactly like an unreachable host, and the two need
        opposite responses -- raise the budget versus go fix the service.
        """
        monkeypatch.setattr(client_module.time, "sleep", lambda _s: None)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        with pytest.raises(InventoryApiError, match="did not complete within 600s"):
            _client(handler).sync_inventory([_environment_item()], run_id="r")

    def test_the_sync_gets_a_longer_read_budget_than_an_ordinary_call(self):
        """The one whole-inventory POST runs for minutes; a paged GET must not."""
        config = DiscoveryConfig()

        assert config.sync_timeout_seconds > config.read_timeout_seconds
        # The connect leg stays short either way: a host that is *down* should still
        # say so in seconds.
        assert config.connect_timeout_seconds <= config.read_timeout_seconds

    def test_transport_error_becomes_inventory_error(self, monkeypatch):
        monkeypatch.setattr(client_module.time, "sleep", lambda _s: None)

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with pytest.raises(InventoryApiError, match="POST"):
            _client(handler).sync_inventory([_environment_item()], run_id="r")

    def test_an_exhausted_retry_does_not_back_off_on_the_way_out(self, monkeypatch):
        """The last delay spaces out a try that never happens.

        Sleeping after the final attempt is pure dead wait bolted onto a call that has
        already failed -- and the sync's backoff is measured in seconds, so it is long
        enough for a user to sit through.
        """
        sleeps: list[float] = []
        monkeypatch.setattr(client_module.time, "sleep", sleeps.append)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        config = _config(sync_retry=RetryPolicy(max_attempts=3, base_delay_seconds=1.0))
        with pytest.raises(InventoryApiError):
            _client(handler, config=config).sync_inventory(
                [_environment_item()], run_id="r"
            )

        assert len(sleeps) == 2  # three attempts, two gaps between them


class TestItemIdEncoding:
    """Single-row reads still address opaque ids as OData key literals."""

    def test_percent_signs_survive_the_path_decode(self):
        """The id's own escapes must not collapse while routing the key segment."""
        site_url = "https://contoso.sharepoint.com/sites/HR"
        item_id = encode_item_id(Kind.SHAREPOINT_SITE, site_url)
        literal = odata_key_literal(item_id)

        assert "%25" in literal
        assert ":" not in literal
        assert "/" not in literal

    def test_single_quotes_are_doubled_for_the_odata_literal(self):
        literal = odata_key_literal("Connector:shared_o'brien")
        assert "%27%27" in literal


class TestList:
    """The GET collection call kept its paging and client-side narrowing contract."""

    def test_pages_until_a_short_page(self):
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            skip = int(request.url.params["$skip"])
            if skip == 0:
                rows = [
                    {"kind": "Connection", "naturalKey": f"k{i}", "environmentId": _ENV_ID}
                    for i in range(2)
                ]
            else:
                rows = [{"kind": "Connector", "naturalKey": "c1"}]
            return httpx.Response(200, json={"value": rows})

        rows = _client(handler, config=_config(list_page_size=2)).list_items()

        assert len(urls) == 2
        assert "$top=2&$skip=0" in urls[0]
        assert "$top=2&$skip=2" in urls[1]
        assert len(rows) == 3

    def test_top_is_clamped_to_the_service_max(self):
        urls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            urls.append(str(request.url))
            return httpx.Response(200, json={"value": []})

        _client(handler, config=_config(list_page_size=5000)).list_items()
        assert "$top=500" in urls[0]

    def test_narrowing_filters_client_side_after_normalizing_pascal_case_rows(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"Kind": "Connection", "NaturalKey": "a", "EnvironmentId": _ENV_ID},
                        {"Kind": "Connection", "NaturalKey": "b", "EnvironmentId": "other"},
                        {"Kind": "Connector", "NaturalKey": "c"},
                    ]
                },
            )

        rows = _client(handler).list_items(kind=Kind.CONNECTION, environment_id=_ENV_ID)
        assert [r["naturalKey"] for r in rows] == ["a"]

    def test_throttle_without_retry_after_still_raises_throttled(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        with pytest.raises(ThrottledError):
            _client(handler).list_items()


class TestProbe:
    """Pre-flight still uses a one-row GET before the expensive crawl begins."""

    def test_probe_requests_a_single_row(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"value": []})

        _client(handler).probe()

        assert len(seen) == 1
        assert seen[0].method == "GET"
        assert str(seen[0].url) == f"{_COLLECTION}?$top=1"

    def test_probe_succeeds_on_an_empty_tenant(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"value": []})

        assert _client(handler).probe() is None

    def test_probe_surfaces_forbidden_as_non_retryable(self):
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(403, text="app not authorized")

        config = _config(retry=RetryPolicy(max_attempts=4, base_delay_seconds=0.0))
        with pytest.raises(NonRetryableApiError):
            _client(handler, config=config).probe()
        assert len(calls) == 1

    def test_probe_surfaces_transport_failure(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("name resolution failed")

        with pytest.raises(InventoryApiError):
            _client(handler).probe()
