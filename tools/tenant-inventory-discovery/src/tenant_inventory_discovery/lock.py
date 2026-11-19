"""Per-tenant single-flight run lock (interim D6 mitigation, spec §7, Q-B).

Until the overlapping-run rule (DesignSpec D6) is finalized server-side, the skill must
**serialize runs per tenant** so two interleaving discovery runs can't restamp each
other's rows. This module provides a lock :class:`Protocol` and a simple file-based
implementation with a TTL so a crashed run's stale lock eventually clears.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from .errors import RunLockError

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> None:
        # LK_NBLCK fails at once (PermissionError) rather than LK_LOCK's built-in retries.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(fd: int) -> None:
        # flock, not lockf: lockf locks are per-process and would not exclude two
        # threads of one process; flock locks belong to the open file description.
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


_GUARD_POLL_SECONDS = 0.01


class RunLock(Protocol):
    """A per-tenant advisory lock (spec §7).

    ``token`` is an opaque ownership token (the skill passes its local ``correlation_id``);
    it is lock bookkeeping only and is never sent to inventory or stamped on rows.
    """

    def acquire(self, tenant_id: str, token: str) -> None: ...
    def release(self, tenant_id: str, token: str) -> None: ...


class FileRunLock:
    """File-based per-tenant lock with a TTL (interim D6 mitigation, spec §7).

    A lock file records the owning ``token``, the raw tenant id, and an expiry.
    Acquisition fails with :class:`RunLockError` if a live (non-expired) lock is held by
    another run. A stale lock (past its TTL -- e.g. left by a crashed run) is reclaimed.

    Every transition -- claim, refresh, stale takeover, release -- is a read-decide-write,
    and each runs under a per-tenant **guard**: an OS lock (``flock`` on POSIX,
    ``msvcrt.locking`` on Windows) on a sibling ``.guard`` file. Without it, two runs can
    both read the same expired lock and both take it over, or a run whose lock lapsed
    can delete the lock a successor has just claimed. The OS drops the guard when its
    holder exits, so a crash cannot wedge it; a holder that hangs makes the next
    transition fail with :class:`RunLockError` after ``guard_timeout_seconds`` instead of
    blocking forever. Refresh and takeover write a temp file and ``os.replace`` it, so a
    crash mid-write leaves the previous claim intact rather than a truncated file.

    The remaining gap is cross-host: two machines sharing a network path still race,
    because neither OS file locks nor ``O_EXCL`` are reliable over most network
    filesystems. Single-host single-flight is what this delivers and all it claims.
    """

    def __init__(
        self,
        lock_dir: str | os.PathLike[str],
        ttl_seconds: int,
        *,
        guard_timeout_seconds: float = 10.0,
    ) -> None:
        self._dir = Path(lock_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_seconds
        self._guard_timeout = guard_timeout_seconds

    def _path(self, tenant_id: str) -> Path:
        """Map a tenant id to a lock file **injectively**.

        The obvious approach -- replace every character that is awkward in a filename
        with ``_`` -- is not injective, and for a lock that is a correctness bug rather
        than a cosmetic one: ``contoso.example.com`` and ``contoso_example_com`` would
        share a lock file, so an unrelated tenant's run could block this one, or worse,
        reclaim its lock as stale. Hashing gives a filename that is one-to-one with the
        id; the raw id goes inside the file so the lock is still debuggable.
        """
        digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
        return self._dir / f"discovery-{digest}.lock"

    @contextlib.contextmanager
    def _guarded(self, tenant_id: str) -> Iterator[None]:
        """Hold the tenant's guard for one lock transition.

        A fresh descriptor per call is what makes the guard exclude other threads of this
        process as well as other processes. The guard file is never deleted: removing it
        would let a waiter lock the orphaned file while a newcomer locks a new one.
        """
        guard = self._path(tenant_id).with_suffix(".guard")
        fd = os.open(guard, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            deadline = time.monotonic() + self._guard_timeout
            while True:
                try:
                    _try_lock(fd)
                    break
                except (BlockingIOError, PermissionError):
                    if time.monotonic() >= deadline:
                        raise RunLockError(
                            f"tenant {tenant_id!r}: timed out after "
                            f"{self._guard_timeout:g}s waiting for {guard}; another run "
                            f"appears stuck mid-transition (spec §7)"
                        ) from None
                    time.sleep(_GUARD_POLL_SECONDS)
            try:
                yield
            finally:
                _unlock(fd)
        finally:
            os.close(fd)

    def _replace(self, path: Path, token: str, body: str) -> None:
        """Rewrite the lock atomically, so a crash mid-write leaves the old claim intact."""
        suffix = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
        tmp = path.with_name(f"{path.name}.{suffix}.tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)

    def _claim(self, tenant_id: str, token: str) -> dict[str, object]:
        return {
            "token": token,
            "tenant_id": tenant_id,
            "expires_at": time.time() + self._ttl,
        }

    def acquire(self, tenant_id: str, token: str) -> None:
        path = self._path(tenant_id)
        with self._guarded(tenant_id):
            body = json.dumps(self._claim(tenant_id, token))
            try:
                # Atomic: exactly one contender can create the file, so two runs starting
                # in the same millisecond cannot both conclude the lock is free. A
                # check-then-write would let both pass the check and both write.
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                self._reclaim_if_stale(path, tenant_id, token, body)
                return
            try:
                os.write(fd, body.encode("utf-8"))
            finally:
                os.close(fd)

    def _reclaim_if_stale(
        self, path: Path, tenant_id: str, token: str, body: str
    ) -> None:
        """Take over a lock whose owner is gone, or refuse because one is live.

        Called with the guard held, so nothing can change the lock between this read
        and the write that acts on it.
        """
        now = time.time()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = None
        if not isinstance(data, dict):
            # No usable expiry, so fall back to the file's own age. A *fresh*
            # unreadable lock cannot be proven abandoned, so it is refused rather than
            # stolen. One older than the TTL is a crash leftover, and ageing it out is
            # what keeps a corrupt file from wedging the tenant forever.
            try:
                stale_by_age = (now - path.stat().st_mtime) > self._ttl
            except OSError:
                stale_by_age = False
            if not stale_by_age:
                raise RunLockError(
                    f"tenant {tenant_id!r} has an unreadable lock at {path} that is "
                    f"too recent to age out; another run is most likely starting. "
                    f"Delete it if you are certain no run is in flight (spec §7)"
                )
            data = {}
        expires_at = float(data.get("expires_at", 0) or 0)
        owner = data.get("token")
        if owner == token:
            # Re-acquiring our own lock refreshes its expiry, as the check-then-write
            # version did. A long run must not let its own lock lapse underneath it.
            self._replace(path, token, body)
            return
        if expires_at > now:
            raise RunLockError(
                f"tenant {tenant_id!r} run in progress (token={owner}); "
                f"serialize runs per tenant (spec §7)"
            )
        # Expired. The guard means no other contender can have read this same expired
        # lock and be about to take it over too, so a plain atomic replace settles it.
        self._replace(path, token, body)

    def release(self, tenant_id: str, token: str) -> None:
        path = self._path(tenant_id)
        if not path.exists():
            return
        with self._guarded(tenant_id):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = {}
            # Only the owner clears the lock (don't stomp a run that reclaimed a stale
            # lock). The guard keeps this check and the unlink a single step.
            if data.get("token") == token:
                path.unlink(missing_ok=True)
