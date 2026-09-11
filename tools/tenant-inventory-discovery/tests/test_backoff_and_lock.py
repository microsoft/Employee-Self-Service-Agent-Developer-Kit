"""§10: throttling backoff + per-tenant run lock (interim D6 mitigation)."""

from __future__ import annotations

import json
import threading
import time

import pytest

from tenant_inventory_discovery.config import RetryPolicy
from tenant_inventory_discovery.errors import (
    InventoryApiError,
    RunLockError,
    ThrottledError,
)
from tenant_inventory_discovery.inventory_client import with_retry
from tenant_inventory_discovery.lock import FileRunLock


def test_backoff_honors_retry_after(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(
        "tenant_inventory_discovery.inventory_client.time.sleep",
        lambda s: sleeps.append(s),
    )
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ThrottledError(retry_after=2.0)
        return "ok"

    policy = RetryPolicy(max_attempts=5, base_delay_seconds=0.1, max_delay_seconds=30)
    assert with_retry(flaky, policy) == "ok"
    assert sleeps == [2.0, 2.0]  # honored Retry-After, not exponential base


def test_retry_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(
        "tenant_inventory_discovery.inventory_client.time.sleep", lambda s: None
    )

    def always_500():
        raise InventoryApiError("500")

    policy = RetryPolicy(max_attempts=3)
    with pytest.raises(InventoryApiError):
        with_retry(always_500, policy)


def test_run_lock_blocks_concurrent_run(tmp_path):
    lock = FileRunLock(tmp_path, ttl_seconds=3600)
    lock.acquire("tenant-1", "R1")
    with pytest.raises(RunLockError):
        lock.acquire("tenant-1", "R2")  # another run in flight
    lock.release("tenant-1", "R1")
    lock.acquire("tenant-1", "R2")  # now free


def test_stale_lock_reclaimed(tmp_path):
    lock = FileRunLock(tmp_path, ttl_seconds=-1)  # already expired
    lock.acquire("tenant-1", "R1")
    lock.acquire("tenant-1", "R2")  # stale lock reclaimed, no error


def test_distinct_tenants_do_not_share_a_lock_file(tmp_path):
    """Punctuation must not collapse two tenants onto one lock.

    A non-injective filename lets an unrelated tenant's run block this one -- or,
    combined with TTL expiry, reclaim its lock as stale.
    """
    lock = FileRunLock(tmp_path, ttl_seconds=3600)
    lock.acquire("contoso.example.com", "R1")
    lock.acquire("contoso_example_com", "R2")  # different tenant, must not collide
    lock.acquire("contoso:example:com", "R3")
    assert len(list(tmp_path.glob("*.lock"))) == 3


def test_the_raw_tenant_id_is_recoverable_from_the_lock(tmp_path):
    """Hashing the filename must not cost the operator the ability to debug it."""
    lock = FileRunLock(tmp_path, ttl_seconds=3600)
    lock.acquire("contoso.example.com", "R1")
    written = json.loads(next(tmp_path.glob("*.lock")).read_text(encoding="utf-8"))
    assert written["tenant_id"] == "contoso.example.com"


def test_only_one_of_two_racing_acquirers_wins(tmp_path):
    """The lock's entire purpose is single-flight, so a race must produce one winner.

    A check-then-write acquire fails this: both threads observe "no lock", both write,
    and both proceed. Threads are started against a barrier to make them contend.
    """
    lock = FileRunLock(tmp_path, ttl_seconds=3600)
    contenders = 8
    barrier = threading.Barrier(contenders)
    won: list[str] = []
    lost: list[str] = []
    won_lock = threading.Lock()

    def attempt(token: str) -> None:
        barrier.wait()
        try:
            lock.acquire("tenant-1", token)
        except RunLockError:
            with won_lock:
                lost.append(token)
        else:
            with won_lock:
                won.append(token)

    threads = [
        threading.Thread(target=attempt, args=(f"R{i}",)) for i in range(contenders)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(won) == 1, f"expected exactly one winner, got {won}"
    assert len(lost) == contenders - 1


def test_an_unreadable_lock_is_not_treated_as_free(tmp_path):
    """A half-written lock file has no usable expiry, so it cannot be proven stale.

    Treating it as free would steal the lock from the run that is mid-write -- the
    exact race the lock exists to prevent.
    """
    lock = FileRunLock(tmp_path, ttl_seconds=3600)
    lock.acquire("tenant-1", "R1")
    next(tmp_path.glob("*.lock")).write_text("{ truncated", encoding="utf-8")
    with pytest.raises(RunLockError):
        lock.acquire("tenant-1", "R2")


def test_a_corrupt_lock_still_ages_out(tmp_path):
    """Refusing an unreadable lock must not wedge the tenant forever.

    Once it is older than the TTL it can only be a crash leftover, so it is reclaimed
    like any other stale lock rather than needing a human to delete it.
    """
    lock = FileRunLock(tmp_path, ttl_seconds=-1)  # everything is instantly aged out
    lock.acquire("tenant-1", "R1")
    next(tmp_path.glob("*.lock")).write_text("{ truncated", encoding="utf-8")
    lock.acquire("tenant-1", "R2")  # reclaimed, no error


def test_reacquiring_your_own_lock_refreshes_it(tmp_path):
    """A long run must be able to extend its own lock rather than let it lapse."""
    lock = FileRunLock(tmp_path, ttl_seconds=3600)
    lock.acquire("tenant-1", "R1")
    path = next(tmp_path.glob("*.lock"))
    first = json.loads(path.read_text(encoding="utf-8"))["expires_at"]
    time.sleep(0.01)
    lock.acquire("tenant-1", "R1")
    assert json.loads(path.read_text(encoding="utf-8"))["expires_at"] > first


def test_a_reclaim_leaves_no_temp_files_behind(tmp_path):
    lock = FileRunLock(tmp_path, ttl_seconds=-1)
    lock.acquire("tenant-1", "R1")
    lock.acquire("tenant-1", "R2")
    assert list(tmp_path.glob("*.tmp")) == []
