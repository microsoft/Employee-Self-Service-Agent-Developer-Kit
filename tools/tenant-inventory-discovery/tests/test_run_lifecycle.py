"""§10: run lifecycle -- idempotent re-run, reconcile gating."""

from __future__ import annotations

from conftest import ENV_A, ENV_B
from tenant_inventory_discovery.config import DiscoveryConfig
from tenant_inventory_discovery.discovery_skill import DiscoverySkill
from tenant_inventory_discovery.models import Kind
from tenant_inventory_discovery.runner import DiscoveryRunner


def _run(platform, inventory, **kw):
    runner = DiscoveryRunner(platform, inventory, DiscoveryConfig())
    return runner


def test_all_eight_kinds_upserted(platform, inventory):
    runner = _run(platform, inventory)
    runner.run()
    kinds = {s.kind for s in inventory.active_items()}
    assert kinds == set(Kind)


def test_completed_scope_reports_observed_keys(platform, inventory):
    runner = _run(platform, inventory)
    summary = runner.run()
    env_report = next(s for s in summary.scopes if s.scope.kind is Kind.ENVIRONMENT)
    # Observed keys are the natural keys upserted in the scope (the reconcile snapshot).
    assert set(env_report.observed_keys) == {ENV_A, ENV_B}


def test_idempotent_rerun_no_duplicates(platform, inventory):
    runner = _run(platform, inventory)
    runner.run()
    count_after_first = len(inventory.items)
    runner.run()
    assert len(inventory.items) == count_after_first  # overwrite in place


def test_env_scoped_no_cross_environment_collision(platform, inventory):
    runner = _run(platform, inventory)
    runner.run()
    # Connection c-1 exists in both ENV_A and ENV_B -> two distinct rows.
    assert inventory.get(Kind.CONNECTION, f"{ENV_A}:c-1") is not None
    assert inventory.get(Kind.CONNECTION, f"{ENV_B}:c-1") is not None


def test_full_run_completes_all_crawled_scopes(platform, inventory):
    runner = _run(platform, inventory)
    summary = runner.run()
    # Tenant-root kinds + env-scoped scopes that had data are all complete.
    completed_kinds = {s.kind for s in summary.completed_scopes}
    assert Kind.ENVIRONMENT in completed_kinds
    assert Kind.CONNECTION in completed_kinds
    # Even empty scopes (e.g. KnowledgeSource in ENV_B) are fully enumerated -> complete.
    assert not summary.aborted


def test_skill_retires_drift_and_returns_summary(platform, inventory):
    """One server reconcile per completed env-scoped scope; tenant-root swept locally."""
    skill = DiscoverySkill(platform, inventory)
    summary = skill.discover("tenant-1")

    env_scoped_completed = [s for s in summary.completed_scopes if s.kind.is_env_scoped]
    assert inventory.reconcile_calls == len(env_scoped_completed)
    # Tenant-rooted kinds are rejected by the server action, so they are listed+diffed.
    assert inventory.list_calls == len(
        [s for s in summary.completed_scopes if s.kind.is_tenant_root]
    )
    assert summary.correlation_id
    assert summary.pass_started_at is not None
    assert not summary.aborted


def test_reconcile_is_never_called_for_tenant_root_kinds(platform, inventory):
    """The service rejects them; calling anyway would fail every tenant-root scope."""
    calls: list[Kind] = []
    original = inventory.reconcile

    def _spy(kind, environment_id, pass_started_at):
        calls.append(kind)
        return original(kind, environment_id, pass_started_at)

    inventory.reconcile = _spy
    DiscoverySkill(platform, inventory).discover("tenant-1")
    assert calls and all(k.is_env_scoped for k in calls)
