"""Per-tenant single-flight run lock (interim D6 mitigation, spec §7, Q-B).

Until the overlapping-run rule (DesignSpec D6) is finalized server-side, the skill must
**serialize runs per tenant** so two interleaving discovery runs can't restamp each
other's rows. This module provides a lock :class:`Protocol` and a simple file-based
implementation with a TTL so a crashed run's stale lock eventually clears.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Protocol

from .errors import RunLockError


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

    Acquisition is **atomic**: the claim is an ``O_EXCL`` create, so of two runs racing
    on a free lock exactly one wins. That matters because a check-then-write would let
    both contenders observe "free" and both proceed, which defeats the single-flight
    guarantee this class exists to provide. Reclaiming an *expired* lock is settled by
    replace-then-read-back, so a race there also resolves to one winner.

    The remaining gap is cross-host: two machines sharing a network path still race,
    because neither ``O_EXCL`` nor the read-back is atomic over most network
    filesystems. Single-host single-flight is what this delivers and all it claims.
    """

    def __init__(self, lock_dir: str | os.PathLike[str], ttl_seconds: int) -> None:
        self._dir = Path(lock_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_seconds

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

    def _claim(self, tenant_id: str, token: str) -> dict[str, object]:
        return {
            "token": token,
            "tenant_id": tenant_id,
            "expires_at": time.time() + self._ttl,
        }

    def acquire(self, tenant_id: str, token: str) -> None:
        path = self._path(tenant_id)
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
        """Take over a lock whose owner is gone, or refuse because one is live."""
        now = time.time()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = None
        if not isinstance(data, dict):
            # No usable expiry, so fall back to the file's own age. A *fresh*
            # unreadable lock is a contender that created it and has not written its
            # body yet -- stealing that is the exact race this guards. One older than
            # the TTL is a crash leftover, and ageing it out is what keeps a corrupt
            # file from wedging the tenant forever.
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
            path.write_text(body, encoding="utf-8")
            return
        if expires_at > now:
            raise RunLockError(
                f"tenant {tenant_id!r} run in progress (token={owner}); "
                f"serialize runs per tenant (spec §7)"
            )
        # The lock is expired. Replace it atomically and then read it back: if another
        # contender replaced it too, exactly one of us sees its own token and wins.
        suffix = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
        tmp = path.with_name(f"{path.name}.{suffix}.tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
        try:
            winner = json.loads(path.read_text(encoding="utf-8")).get("token")
        except (ValueError, OSError):
            winner = None
        if winner != token:
            raise RunLockError(
                f"tenant {tenant_id!r} run in progress (token={winner}); "
                f"lost the race to reclaim an expired lock (spec §7)"
            )

    def release(self, tenant_id: str, token: str) -> None:
        path = self._path(tenant_id)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
        # Only the owner clears the lock (don't stomp a run that reclaimed a stale lock).
        if data.get("token") == token:
            path.unlink(missing_ok=True)
