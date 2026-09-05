"""Wire-shape normalization for payloads coming back from the Inventory API.

The service serializes EDM properties in PascalCase; everything downstream here --
the drift sweep, the local mirror, the in-memory fake -- reads camelCase. The mismatch
does not raise, it silently empties results, so it survived every mock-based test until
a live call exposed it. The fixture below is a **verbatim capture** from the running
service so these tests fail if that shape ever drifts again.
"""

from __future__ import annotations

import httpx

from tenant_inventory_discovery.config import DiscoveryConfig, RetryPolicy
from tenant_inventory_discovery.inventory_client import (
    HttpInventoryClient,
    normalize_row,
)
from tenant_inventory_discovery.mapping import map_resource
from tenant_inventory_discovery.models import Kind

_BASE = "https://inventory.example.test"
_TENANT = "contoso.onmicrosoft.com"

#: Verbatim response body captured from the live service (2026-08-20).
LIVE_ROW = {
    "AgentConfigurationInventoryItemId": "Environment:env-prod",
    "TenantId": "b12869b9-fcf2-413d-8be5-d47d2c31cc30",
    "Kind": "Environment",
    "NaturalKey": "env-prod",
    "State": "Active",
    "ValidationStatus": "Unvalidated",
    "EnvironmentId": None,
    "Source": "Discovered",
    "SubmittedById": "523fecdf-19d9-4db8-8bf5-1f7de47fde29",
    "DisplayName": "Production Environment",
    "Description": "Test environment inventory item",
    "CreatedAt": "2026-08-18T22:44:58.5435144Z",
    "UpdatedAt": "2026-08-20T20:22:41.2940038Z",
    "ETag": 'W/"3"',
    "Attributes": [
        {
            "Key": "environmentId",
            "Value": "env-prod",
            "Description": "Power Platform environment ID",
        },
        {"Key": "region", "Value": "unitedstates", "Description": None},
    ],
}


def _config(**overrides) -> DiscoveryConfig:
    overrides.setdefault("retry", RetryPolicy(max_attempts=1, base_delay_seconds=0.0))
    overrides.setdefault("inventory_base_url", _BASE)
    return DiscoveryConfig(**overrides)


def _client(handler) -> HttpInventoryClient:
    transport = httpx.MockTransport(handler)
    return HttpInventoryClient(
        _TENANT,
        config=_config(),
        auth_token_provider=lambda: "token",
        transport=transport,
    )


class TestNormalizeRow:
    def test_lowercases_the_leading_character(self):
        result = normalize_row(LIVE_ROW)
        assert result["naturalKey"] == "env-prod"
        assert result["kind"] == "Environment"
        assert result["state"] == "Active"
        assert result["source"] == "Discovered"
        assert result["displayName"] == "Production Environment"
        assert result["environmentId"] is None

    def test_maps_the_long_id_property(self):
        # The drift sweep needs this to issue a DELETE; without it every row is skipped.
        assert (
            normalize_row(LIVE_ROW)["agentConfigurationInventoryItemId"]
            == "Environment:env-prod"
        )

    def test_etag_does_not_become_e_tag(self):
        """A naive first-letter rule yields "eTag", which no caller reads."""
        assert normalize_row(LIVE_ROW)["etag"] == 'W/"3"'
        assert "eTag" not in normalize_row(LIVE_ROW)

    def test_odata_annotation_etag_is_also_accepted(self):
        assert normalize_row({"@odata.etag": 'W/"9"'})["etag"] == 'W/"9"'

    def test_normalizes_keys_inside_attributes(self):
        attributes = normalize_row(LIVE_ROW)["attributes"]
        assert attributes[0]["key"] == "environmentId"
        assert attributes[0]["value"] == "env-prod"
        assert attributes[0]["description"] == "Power Platform environment ID"

    def test_is_idempotent(self):
        """The in-memory fake already emits camelCase; it must survive unchanged."""
        once = normalize_row(LIVE_ROW)
        assert normalize_row(once) == once

    def test_leaves_values_untouched(self):
        # Only keys are rewritten -- a value like "Discovered" is compared verbatim.
        assert normalize_row(LIVE_ROW)["updatedAt"] == "2026-08-20T20:22:41.2940038Z"

    def test_handles_an_empty_row(self):
        assert normalize_row({}) == {}


class TestListItemsAgainstTheLiveShape:
    def test_returns_camel_cased_rows(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"value": [LIVE_ROW]})

        rows = _client(handler).list_items()
        assert rows[0]["naturalKey"] == "env-prod"
        assert rows[0]["source"] == "Discovered"

    def test_kind_filter_matches_the_pascal_case_payload(self):
        """Filtering the raw payload silently returned [] -- the original bug."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"value": [LIVE_ROW]})

        rows = _client(handler).list_items(kind=Kind.ENVIRONMENT)
        assert len(rows) == 1

    def test_kind_filter_still_excludes_other_kinds(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"value": [LIVE_ROW]})

        assert _client(handler).list_items(kind=Kind.CONNECTION) == []

    def test_environment_filter_matches_the_pascal_case_payload(self):
        row = dict(LIVE_ROW, EnvironmentId="env-1", Kind="Connection")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"value": [row]})

        rows = _client(handler).list_items(environment_id="env-1")
        assert len(rows) == 1


class TestSyncAgainstTheLiveShape:
    def test_a_pascal_case_sync_response_is_normalized(self):
        """The write response goes through the same PascalCase treatment as reads."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "SubmittedCount": 2,
                    "UpsertedCount": 2,
                    "RetiredCount": 1,
                    "RetiredItemIds": ["Connector:gone"],
                    "FailedItems": [],
                },
            )

        item = map_resource(
            Kind.ENVIRONMENT,
            {"environmentId": "env-prod", "displayName": "Production Environment"},
        )
        result = _client(handler).sync_inventory([item], run_id="run-1")

        assert result.submitted_count == 2
        assert result.upserted_count == 2
        assert result.retired_item_ids == ["Connector:gone"]

    def test_pascal_case_failed_items_are_normalized(self):
        """``FailedItems`` is the one part of a 200 that reports trouble. Reading it
        from the wrong key space turns a partial success into a silent one."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "SubmittedCount": 2,
                    "UpsertedCount": 1,
                    "RetiredCount": 0,
                    "RetiredItemIds": [],
                    "FailedItems": [
                        {"ItemId": "Connection:c-9", "Reason": "no environment"}
                    ],
                },
            )

        item = map_resource(Kind.ENVIRONMENT, {"environmentId": "env-prod"})
        result = _client(handler).sync_inventory([item], run_id="run-1")

        assert len(result.failed_items) == 1
        assert result.failed_items[0].item_id == "Connection:c-9"
        assert result.failed_items[0].reason == "no environment"

    def test_a_row_the_service_returns_can_be_sent_straight_back(self):
        """Carry-forward depends on this: server-managed fields are ignored inbound,
        so a GET body is a legal sync entry after normalization."""
        row = normalize_row(LIVE_ROW)
        assert row["kind"] == "Environment"
        assert row["naturalKey"] == "env-prod"
        assert row["state"] == "Active"
        assert row["validationStatus"] == "Unvalidated"
        assert {a["key"] for a in row["attributes"]} == {"environmentId", "region"}
