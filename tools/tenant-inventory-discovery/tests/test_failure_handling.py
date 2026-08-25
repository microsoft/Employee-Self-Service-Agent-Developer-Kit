"""§10: completeness invariant -- partial crawl and crash never trigger reconcile."""

from __future__ import annotations

import pytest

from conftest import ENV_A, build_platform
from tenant_inventory_discovery.config import DiscoveryConfig
from tenant_inventory_discovery.discovery_skill import DiscoverySkill
from tenant_inventory_discovery.models import Kind
from tenant_inventory_discovery.runner import DiscoveryRunner


def test_failed_scope_excluded_from_reconcile(platform, inventory):
    # Connections enumeration fails -> that scope must not be swept (spec §7).
    platform.fail_on = {"list_connections"}
    runner = DiscoveryRunner(platform, inventory, DiscoveryConfig())
    summary = runner.run()

    completed_kinds = {s.kind for s in summary.completed_scopes}
    assert Kind.CONNECTION not in completed_kinds
    # Other scopes still complete normally.
    assert Kind.EXTENSION_PACK in completed_kinds
    # The failed scope is recorded as incomplete with an error.
    conn_reports = [s for s in summary.scopes if s.scope.kind is Kind.CONNECTION]
    assert conn_reports and all(not r.complete for r in conn_reports)


def test_partial_crawl_keeps_prior_rows(inventory):
    # Full run 1.
    skill = DiscoverySkill(build_platform(), inventory)
    skill.discover("t1")

    # Run 2: connection enumeration fails in ENV_A -> scope incomplete -> the existing
    # ENV_A connection must NOT be retired (spec §7).
    p2 = build_platform()
    p2.fail_on = {"list_connections"}
    skill2 = DiscoverySkill(p2, inventory)
    skill2.discover("t1")

    conn = inventory.get(Kind.CONNECTION, f"{ENV_A}:c-1")
    assert conn.state == "Active"  # not swept -- scope was incomplete


def test_crash_before_reconcile_retires_nothing(inventory):
    # A platform that raises a non-PlatformError during enumeration simulates a crash
    # that escapes the per-scope handler.
    platform = build_platform()

    def explode(_page_size):
        raise RuntimeError("boom")

    platform.list_environments = explode  # type: ignore[assignment]

    skill = DiscoverySkill(platform, inventory)
    with pytest.raises(RuntimeError):
        skill.discover("t1")

    # Crash path: the retire phase never ran -> nothing retired.
    assert inventory.reconcile_calls == 0
    assert inventory.retire_calls == 0


def test_upsert_failure_makes_scope_incomplete(platform):
    from tenant_inventory_discovery.errors import InventoryApiError

    class FlakyInventory:
        def __init__(self):
            self.reconcile_calls = 0

        def upsert(self, item, *, if_match=None, run_id=""):
            if item.kind is Kind.CONNECTOR:
                raise InventoryApiError("500")
            return None

        def reconcile(self, snapshots):
            self.reconcile_calls += 1
            return {}

    inv = FlakyInventory()
    runner = DiscoveryRunner(platform, inv, DiscoveryConfig())
    summary = runner.run()
    completed_kinds = {s.kind for s in summary.completed_scopes}
    assert Kind.CONNECTOR not in completed_kinds  # exhausted retries -> incomplete (§7)


def test_no_completed_scopes_skips_reconcile_call():
    from tenant_inventory_discovery.platform_clients import FakePlatform

    from spies import SpyInventoryClient

    # Environment enumeration fails -> no environments discovered; every tenant-root
    # kind that fails is incomplete. Make them all fail to force empty completed set.
    platform = FakePlatform(
        fail_on={
            "list_environments",
            "list_entra_apps",
            "list_connectors",
            "list_sharepoint_sites",
        }
    )
    inv = SpyInventoryClient()
    skill = DiscoverySkill(platform, inv)
    summary = skill.discover("t1")
    assert summary.completed_scopes == []
    assert inv.reconcile_calls == 0  # nothing to reconcile -> skip the call
    assert inv.retire_calls == 0
