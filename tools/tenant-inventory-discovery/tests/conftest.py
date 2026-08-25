"""Shared fixtures: a populated fake tenant across all eight kinds."""

from __future__ import annotations

import pytest

from tenant_inventory_discovery.platform_clients import FakePlatform

from spies import SpyInventoryClient

ENV_A = "env-aaaa"
ENV_B = "env-bbbb"


def build_platform() -> FakePlatform:
    """A two-environment tenant with at least one resource of every kind."""
    return FakePlatform(
        environments=[
            {"environmentId": ENV_A, "displayName": "Prod"},
            {"environmentId": ENV_B, "displayName": "Test"},
        ],
        entra_apps=[{"appId": "app-1", "displayName": "ESS Agent App"}],
        connectors=[{"connectorId": "conn-catalog-1", "displayName": "ServiceNow"}],
        sharepoint_sites=[
            {"siteUrl": "https://contoso.sharepoint.com/hr", "siteId": "site-1"}
        ],
        connections={
            ENV_A: [
                {
                    "environmentId": ENV_A,
                    "connectionId": "c-1",
                    "connectorId": "conn-catalog-1",
                }
            ],
            ENV_B: [
                {
                    "environmentId": ENV_B,
                    "connectionId": "c-1",  # same id, different env -> must not collide
                    "connectorId": "conn-catalog-1",
                }
            ],
        },
        knowledge_sources={
            ENV_A: [
                {
                    "environmentId": ENV_A,
                    "botId": "bot-1",
                    "sourceId": "ks-1",
                    "sourceType": "SharePoint",
                }
            ],
        },
        extension_packs={
            # One row per environment: the schema has no identity attribute of its
            # own -- installed/hrsd/itsm/flavor/flowCount all describe *this*
            # environment's pack install. `packName`/`version` are unlisted and get
            # dropped client-side.
            ENV_A: [
                {
                    "environmentId": ENV_A,
                    "installed": True,
                    "hrsd": True,
                    "itsm": False,
                    "flavor": "ServiceNow",
                    "flowCount": 12,
                }
            ],
        },
        scenario_templates={
            ENV_A: [
                {
                    "environmentId": ENV_A,
                    "uniqueName": "GetPayslip",
                    "operation": "GetPayslip",
                    "status": "Active",
                }
            ],
        },
    )


@pytest.fixture
def platform() -> FakePlatform:
    return build_platform()


@pytest.fixture
def inventory() -> SpyInventoryClient:
    return SpyInventoryClient()
