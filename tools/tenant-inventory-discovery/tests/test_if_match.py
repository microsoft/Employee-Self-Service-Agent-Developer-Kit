"""Conditional-write handling for upserts over rows that already exist.

The service refuses a blind write over an existing row: an upsert without ``If-Match``
comes back ``400 {"Target": "If-Match"}``. A first crawl therefore always succeeded
(every row was a create) while every subsequent crawl failed to update anything -- a
bug no mock caught, because the in-memory fake does not model the rule.

Two live findings shape the fix and are pinned here:

* **ETags cannot be fetched per item.** A GET by key 404s for any id containing
  percent-escapes (``SharePointSite:https%3A%2F%2F...``), and no client-side encoding
  reaches it. The ETag is read from the collection listing instead.
* **Ids are not comparable strings.** The service rewrites ids into its own canonical
  form on the way out -- ``%3A`` decoded back to ``:``, ``/`` encoded to ``%2F`` -- so a
  submitted id never equals the returned id for those keys. ``naturalKey`` round-trips
  verbatim, so the lookup is keyed on ``(kind, naturalKey)``.
"""

from __future__ import annotations

import httpx
import pytest

from tenant_inventory_discovery.config import DiscoveryConfig, RetryPolicy
from tenant_inventory_discovery.errors import (
    InventoryApiError,
    PreconditionFailedError,
)
from tenant_inventory_discovery.inventory_client import HttpInventoryClient
from tenant_inventory_discovery.mapping import map_resource
from tenant_inventory_discovery.models import Kind

_BASE = "https://inventory.example.test"
_TENANT = "contoso.onmicrosoft.com"

#: Verbatim 400 body the live service returns for a blind write over an existing row.
IF_MATCH_REQUIRED = {
    "Code": "BadRequest",
    "Message": "The calling client sent a bad request to the service.",
    "Target": "If-Match",
    "Details": [
        {
            "Code": "ValidationError",
            "Message": (
                "If-Match header is required for this operation on "
                "'inventory(Environment:env-prod)'."
            ),
        }
    ],
}


def _client(handler) -> HttpInventoryClient:
    return HttpInventoryClient(
        _TENANT,
        config=DiscoveryConfig(
            inventory_base_url=_BASE,
            retry=RetryPolicy(max_attempts=1, base_delay_seconds=0.0),
        ),
        auth_token_provider=lambda: "token",
        transport=httpx.MockTransport(handler),
    )


def _env_item(natural_key: str = "env-prod"):
    return map_resource(
        Kind.ENVIRONMENT,
        {"environmentId": natural_key, "displayName": "Production"},
    )


def _site_item(site_url: str = "https://contoso.sharepoint.com/hr"):
    return map_resource(Kind.SHAREPOINT_SITE, {"siteUrl": site_url})


def _row(kind: str, natural_key: str, etag: str) -> dict:
    """A listing row in the service's PascalCase wire shape."""
    return {
        "AgentConfigurationInventoryItemId": f"{kind}:{natural_key}",
        "Kind": kind,
        "NaturalKey": natural_key,
        "Source": "Discovered",
        "ETag": etag,
    }


class _Service:
    """A stand-in that demands If-Match on writes, like the real service."""

    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.posts: list[str | None] = []
        self.list_calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            self.list_calls += 1
            return httpx.Response(200, json={"value": self.rows})
        if_match = request.headers.get("If-Match")
        self.posts.append(if_match)
        if if_match is None:
            return httpx.Response(400, json=IF_MATCH_REQUIRED)
        return httpx.Response(200, json={"ETag": 'W/"9"'})


class TestBlindWriteIsRetriedWithTheCurrentEtag:
    def test_retries_and_succeeds(self):
        service = _Service([_row("Environment", "env-prod", 'W/"3"')])
        result = _client(service).upsert(_env_item(), run_id="run-1")

        assert service.posts == [None, 'W/"3"']
        assert result.etag == 'W/"9"'

    def test_reports_an_update_not_a_create(self):
        service = _Service([_row("Environment", "env-prod", 'W/"3"')])
        result = _client(service).upsert(_env_item(), run_id="run-1")

        assert result.created is False

    def test_a_row_the_service_does_not_have_is_created_without_a_retry(self):
        service = _Service([_row("Environment", "env-prod", 'W/"3"')])

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                service.posts.append(request.headers.get("If-Match"))
                return httpx.Response(201, json={"ETag": 'W/"1"'})
            return service(request)

        _client(handler).upsert(_env_item("env-new"), run_id="run-1")
        assert service.posts == [None]


class TestEtagLookupIsKeyedOnNaturalKeyNotItemId:
    def test_resolves_a_row_whose_id_the_service_rewrote(self):
        """The submitted id is percent-escaped; the stored id is not comparable."""
        stored = _row(
            "SharePointSite",
            "https://contoso.sharepoint.com/hr",
            'W/"1"',
        )
        stored["AgentConfigurationInventoryItemId"] = (
            "SharePointSite:https:%2F%2Fcontoso.sharepoint.com%2Fhr"
        )
        service = _Service([stored])

        item = _site_item()
        assert item.item_id != stored["AgentConfigurationInventoryItemId"]

        _client(service).upsert(item, run_id="run-1")
        assert service.posts == [None, 'W/"1"']

    def test_distinguishes_two_kinds_sharing_one_natural_key(self):
        """Environment and ExtensionPack both key on 'env-prod'."""
        service = _Service(
            [
                _row("ExtensionPack", "env-prod", 'W/"7"'),
                _row("Environment", "env-prod", 'W/"3"'),
            ]
        )
        _client(service).upsert(_env_item(), run_id="run-1")
        assert service.posts == [None, 'W/"3"']


class TestTheListingIsFetchedAtMostOncePerPass:
    def test_two_upserts_share_one_listing(self):
        service = _Service(
            [
                _row("Environment", "env-prod", 'W/"3"'),
                _row("Environment", "env-test", 'W/"4"'),
            ]
        )
        client = _client(service)
        client.upsert(_env_item("env-prod"), run_id="run-1")
        client.upsert(_env_item("env-test"), run_id="run-1")

        assert service.list_calls == 1
        assert service.posts == [None, 'W/"3"', None, 'W/"4"']

    def test_a_rewritten_row_reuses_the_etag_from_its_own_response(self):
        """No second listing, and no stale ETag, when a row is written twice."""
        service = _Service([_row("Environment", "env-prod", 'W/"3"')])
        client = _client(service)
        client.upsert(_env_item(), run_id="run-1")
        client.upsert(_env_item(), run_id="run-1")

        assert service.list_calls == 1
        assert service.posts == [None, 'W/"3"', None, 'W/"9"']


class TestTheRetryIsNarrow:
    def test_a_caller_supplied_etag_is_not_second_guessed(self):
        service = _Service([_row("Environment", "env-prod", 'W/"3"')])
        _client(service).upsert(_env_item(), run_id="run-1", if_match='W/"2"')

        assert service.posts == ['W/"2"']
        assert service.list_calls == 0

    def test_an_unrelated_400_still_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400, json={"Code": "BadRequest", "Target": "displayName"}
            )

        with pytest.raises(InventoryApiError):
            _client(handler).upsert(_env_item(), run_id="run-1")

    def test_a_row_missing_from_the_listing_surfaces_the_original_400(self):
        """No retry loop when the ETag cannot be resolved."""
        service = _Service([])
        with pytest.raises(InventoryApiError, match="If-Match"):
            _client(service).upsert(_env_item(), run_id="run-1")
        assert service.posts == [None]

    def test_a_stale_etag_surfaces_as_a_precondition_failure(self):
        service = _Service([_row("Environment", "env-prod", 'W/"3"')])

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.headers.get("If-Match"):
                return httpx.Response(412, json={"Code": "PreconditionFailed"})
            return service(request)

        with pytest.raises(PreconditionFailedError):
            _client(handler).upsert(_env_item(), run_id="run-1")


class TestRetireDoesNotClaimAnUnresolvableKey:
    """A 404 means "already gone" *or* "the service could not route this key"."""

    def _handler(self, rows: list[dict]):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"value": rows})
            return httpx.Response(404, text="not found")

        return handler

    def test_a_genuinely_absent_row_is_success(self):
        _client(self._handler([])).retire("Environment:env-gone")

    def test_a_row_that_is_still_listed_raises(self):
        rows = [_row("SharePointSite", "https://contoso.sharepoint.com/hr", 'W/"1"')]
        rows[0]["AgentConfigurationInventoryItemId"] = (
            "SharePointSite:https:%2F%2Fcontoso.sharepoint.com%2Fhr"
        )

        with pytest.raises(InventoryApiError, match="still listed"):
            _client(self._handler(rows)).retire(
                "SharePointSite:https:%2F%2Fcontoso.sharepoint.com%2Fhr"
            )

    def test_a_successful_delete_never_consults_the_listing(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.method)
            return httpx.Response(204)

        _client(handler).retire("Environment:env-prod")
        assert calls == ["DELETE"]
