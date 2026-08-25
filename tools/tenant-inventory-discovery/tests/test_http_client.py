"""HTTP-level contract tests for :class:`HttpInventoryClient`.

These pin the parts of the client that are invisible to the in-memory fake: the URL
shape, the double-encoding of the opaque item id, the wire body, and the reconcile
payload. They run against an ``httpx`` mock transport -- no service required.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tenant_inventory_discovery.config import DiscoveryConfig, RetryPolicy
from tenant_inventory_discovery.errors import (
    InventoryApiError,
    NonRetryableApiError,
    PreconditionFailedError,
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
    # No sleeping in tests: one attempt unless a case opts into more.
    overrides.setdefault("retry", RetryPolicy(max_attempts=1, base_delay_seconds=0.0))
    return DiscoveryConfig(inventory_base_url=_BASE, **overrides)


def _client(handler, *, config: DiscoveryConfig | None = None) -> HttpInventoryClient:
    return HttpInventoryClient(
        _TENANT,
        config=config or _config(),
        auth_token_provider=lambda: "test-token",
        transport=httpx.MockTransport(handler),
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


class TestUpsert:
    def test_posts_the_server_wire_shape(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                201,
                headers={"ETag": 'W/"1"'},
                json={"agentConfigurationInventoryItemId": "Connection:abc"},
            )

        item = _connection_item()
        result = _client(handler).upsert(item, run_id="run-1")

        assert len(seen) == 1
        request = seen[0]
        assert request.method == "POST"
        assert str(request.url) == _COLLECTION

        body = json.loads(request.content)
        assert body["kind"] == "Connection"
        assert body["naturalKey"] == f"{_ENV_ID}:cr-1"
        assert body["environmentId"] == _ENV_ID
        assert body["displayName"] == "ServiceNow ref"
        # attributes is an array of {key, value} entries with string values -- a
        # plain object binds to a list of empty objects server-side.
        assert body["attributes"] == [
            {"key": "connectionId", "value": "cr-1"},
            {"key": "connectorId", "value": "shared_service-now"},
            {"key": "environmentId", "value": _ENV_ID},
            {"key": "status", "value": "Active"},
        ]
        # The server stamps these; sending them is rejected or ignored.
        for forbidden in ("source", "submittedById", "state", "connectorId"):
            assert forbidden not in body

        assert request.headers["Idempotency-Key"]
        assert result.created is True
        assert result.etag == 'W/"1"'
        assert result.item_id == "Connection:abc"

    def test_idempotency_key_is_scoped_to_the_run(self):
        """Two passes over an unchanged resource must not collide in the 24h cache."""
        keys: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            keys.append(request.headers["Idempotency-Key"])
            return httpx.Response(201, json={})

        item = _connection_item()
        client = _client(handler)
        client.upsert(item, run_id="run-1")
        client.upsert(item, run_id="run-1")  # retry within the pass -> same key
        client.upsert(item, run_id="run-2")  # next pass -> must differ

        assert keys[0] == keys[1]
        assert keys[2] != keys[0]

    def test_if_match_is_forwarded(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(201, json={})

        _client(handler).upsert(_connection_item(), if_match='W/"7"', run_id="r")
        assert seen[0].headers["If-Match"] == 'W/"7"'

    def test_412_is_not_retried(self):
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(412)

        config = _config(retry=RetryPolicy(max_attempts=4, base_delay_seconds=0.0))
        with pytest.raises(PreconditionFailedError):
            _client(handler, config=config).upsert(_connection_item(), run_id="r")
        assert len(calls) == 1  # a stale ETag is the caller's problem to resolve

    def test_429_is_retried_with_the_same_idempotency_key(self):
        keys: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            keys.append(request.headers["Idempotency-Key"])
            if len(keys) < 3:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return httpx.Response(201, json={})

        config = _config(retry=RetryPolicy(max_attempts=4, base_delay_seconds=0.0))
        _client(handler, config=config).upsert(_connection_item(), run_id="r")

        assert len(keys) == 3
        assert len(set(keys)) == 1  # replay-safe: the retry must reuse the key

    def test_4xx_surfaces_the_server_message(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="attributes[0].key is not allowed")

        with pytest.raises(InventoryApiError) as exc:
            _client(handler).upsert(_connection_item(), run_id="r")
        assert "attributes[0].key is not allowed" in str(exc.value)

    def test_4xx_is_not_retried(self):
        """A schema violation or the row cap answers identically every time."""
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(400, text="per-kind cap exceeded")

        config = _config(retry=RetryPolicy(max_attempts=4, base_delay_seconds=0.0))
        with pytest.raises(NonRetryableApiError):
            _client(handler, config=config).upsert(_connection_item(), run_id="r")
        assert len(calls) == 1

    def test_5xx_is_retried(self):
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) < 3:
                return httpx.Response(503)
            return httpx.Response(201, json={})

        config = _config(retry=RetryPolicy(max_attempts=4, base_delay_seconds=0.0))
        _client(handler, config=config).upsert(_connection_item(), run_id="r")
        assert len(calls) == 3

    def test_transport_error_becomes_an_inventory_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        with pytest.raises(InventoryApiError):
            _client(handler).upsert(_connection_item(), run_id="r")


class TestItemIdEncoding:
    def test_percent_signs_survive_the_path_decode(self):
        """A composite natural key is already percent-encoded inside the id.

        Encoding the id again is what keeps ``%3A`` from collapsing back to ``:``
        and turning a lookup into a miss.
        """
        site_url = "https://contoso.sharepoint.com/sites/HR"
        item_id = encode_item_id(Kind.SHAREPOINT_SITE, site_url)
        literal = odata_key_literal(item_id)

        assert "%25" in literal  # the id's own escapes are re-escaped
        assert ":" not in literal
        assert "/" not in literal

    def test_single_quotes_are_doubled_for_the_odata_literal(self):
        literal = odata_key_literal("Connector:shared_o'brien")
        # '' (doubled quote) percent-encodes to %27%27.
        assert "%27%27" in literal

    def test_retire_targets_the_encoded_key_segment(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(204)

        item_id = encode_item_id(Kind.SHAREPOINT_SITE, "https://contoso.sharepoint.com/sites/HR")
        _client(handler).retire(item_id)

        assert seen[0].method == "DELETE"
        assert str(seen[0].url) == f"{_COLLECTION}('{odata_key_literal(item_id)}')"

    def test_retire_tolerates_an_already_gone_row(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                # The row is genuinely gone, so it is not in the listing either.
                return httpx.Response(200, json={"value": []})
            return httpx.Response(404)

        _client(handler).retire("Connection:gone")  # soft delete is idempotent


class TestList:
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

        client = _client(handler, config=_config(list_page_size=2))
        rows = client.list_items()

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

    def test_narrowing_filters_client_side(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "value": [
                        {"kind": "Connection", "naturalKey": "a", "environmentId": _ENV_ID},
                        {"kind": "Connection", "naturalKey": "b", "environmentId": "other"},
                        {"kind": "Connector", "naturalKey": "c"},
                    ]
                },
            )

        client = _client(handler)
        rows = client.list_items(kind=Kind.CONNECTION, environment_id=_ENV_ID)
        assert [r["naturalKey"] for r in rows] == ["a"]


class TestReconcile:
    def test_posts_the_bound_action_with_a_utc_watermark(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "kind": "Connection",
                    "environmentId": _ENV_ID,
                    "evaluatedCount": 9,
                    "retiredCount": 2,
                    "retiredItemIds": ["Connection:x", "Connection:y"],
                },
            )

        watermark = datetime(2026, 3, 1, 12, 0, tzinfo=timezone(timedelta(hours=-8)))
        result = _client(handler).reconcile(Kind.CONNECTION, _ENV_ID, watermark)

        assert str(seen[0].url) == f"{_COLLECTION}/reconcile"
        body = json.loads(seen[0].content)
        assert body["kind"] == "Connection"
        assert body["environmentId"] == _ENV_ID
        assert body["passStartedAt"] == "2026-03-01T20:00:00+00:00"

        assert result.evaluated_count == 9
        assert result.retired_count == 2
        assert result.retired_item_ids == ["Connection:x", "Connection:y"]

    def test_naive_watermark_is_treated_as_utc(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={})

        _client(handler).reconcile(
            Kind.CONNECTION, _ENV_ID, datetime(2026, 3, 1, 20, 0)
        )
        assert json.loads(seen[0].content)["passStartedAt"] == "2026-03-01T20:00:00+00:00"

    def test_rejection_of_a_tenant_rooted_kind_surfaces(self):
        """The service refuses tenant-rooted scopes; the client must not swallow it."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="Kind 'Connector' is not environment-scoped.")

        with pytest.raises(InventoryApiError) as exc:
            _client(handler).reconcile(Kind.CONNECTOR, _ENV_ID, datetime.now(timezone.utc))
        assert "not environment-scoped" in str(exc.value)


class TestUrlComposition:
    def test_collection_url_is_rooted_on_the_tenant_shard(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"value": []})

        client = _client(handler)
        assert client._collection_url == _COLLECTION

    def test_missing_base_url_fails_loudly(self):
        """Explicitly clearing the origin must fail, not fall back to production."""
        with pytest.raises(ValueError, match="WEVENOVA_BASE_URL"):
            HttpInventoryClient(_TENANT, config=DiscoveryConfig(inventory_base_url=None))

    def test_base_url_defaults_to_production(self):
        """Persisting is the default, so a bare config must be usable as-is."""
        from tenant_inventory_discovery.config import DEFAULT_INVENTORY_BASE_URL

        assert DiscoveryConfig().inventory_base_url == DEFAULT_INVENTORY_BASE_URL

    def test_throttle_without_retry_after_still_raises_throttled(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429)

        with pytest.raises(ThrottledError):
            _client(handler).list_items()


class TestProbe:
    """Pre-flight: the bridge uses this to fail fast before a long crawl."""

    def test_probe_requests_a_single_row(self):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"value": []})

        _client(handler).probe()
        assert len(seen) == 1
        assert seen[0].method == "GET"
        # A probe that paged the whole partition would defeat the point.
        assert str(seen[0].url) == f"{_COLLECTION}?$top=1"

    def test_probe_succeeds_on_an_empty_tenant(self):
        """An empty inventory is a valid state, not a broken write path."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"value": []})

        assert _client(handler).probe() is None

    def test_probe_surfaces_forbidden_as_non_retryable(self):
        """403 is the app-id allow-list rejection; retrying it just wastes the budget."""
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
