# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Atomic, process-coordinated persistence for the shared MSAL JSON cache."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import portalocker
from msal import SerializableTokenCache
from msal_extensions import FilePersistence, PersistedTokenCache


_LOCK_TIMEOUT_SECONDS = 5


class _AtomicFilePersistence(FilePersistence):
    """Keep the existing UTF-8 MSAL format while publishing complete files."""

    def load(self) -> str:
        try:
            with open(self.get_location(), encoding="utf-8") as handle:
                content = handle.read()
        except FileNotFoundError:
            return "{}"

        state = json.loads(content)
        if not isinstance(state, dict) or any(
            not isinstance(entries, dict)
            or any(not isinstance(entry, dict) for entry in entries.values())
            for entries in state.values()
        ):
            raise ValueError("MSAL cache must contain objects of credential entries")
        return content

    def save(self, content: str) -> None:
        location = self.get_location()
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=os.path.dirname(location),
                prefix=os.path.basename(location) + ".",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, location)
        finally:
            if temporary_path is not None:
                original_error = sys.exception()
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
                except OSError as cleanup_error:
                    if original_error is None:
                        raise
                    original_error.add_note(
                        f"Temporary MSAL cache cleanup failed: {cleanup_error}"
                    )


def _open_private(path: str, flags: int) -> int:
    return os.open(path, flags, 0o600)


class _SynchronizedTokenCache(PersistedTokenCache):
    """Reload each transaction; filesystem timestamps are not revision numbers."""

    def __init__(self, persistence: _AtomicFilePersistence) -> None:
        super().__init__(persistence)
        self._storage = persistence
        self._transaction_active = False

    def _disk_lock(self) -> portalocker.Lock:
        # Never unlink this file: POSIX waiters must all lock the same inode.
        return portalocker.Lock(
            self._storage.get_location() + ".lockfile",
            mode="a+b",
            timeout=_LOCK_TIMEOUT_SECONDS,
            check_interval=0.05,
            flags=portalocker.LOCK_EX | portalocker.LOCK_NB,
            opener=_open_private,
        )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            if self._transaction_active:
                yield
                return
            with self._disk_lock():
                self._transaction_active = True
                try:
                    yield
                finally:
                    self._transaction_active = False

    def modify(
        self,
        credential_type: str,
        old_entry: dict[str, Any],
        new_key_value_pairs: dict[str, Any] | None = None,
    ) -> None:
        with self._transaction():
            # Reload even after deletion, equal mtimes, or a failed earlier save.
            self.deserialize(self._storage.load())
            SerializableTokenCache.modify(
                self, credential_type, old_entry, new_key_value_pairs
            )
            self._storage.save(self.serialize())

    def search(
        self, credential_type: str, **kwargs: Any
    ) -> Iterator[dict[str, Any]]:
        with self._transaction():
            # Windows readers must close their handles before another writer replaces.
            self.deserialize(self._storage.load())
            # Expiry removals reenter the transaction; release locks before returning.
            return iter(list(SerializableTokenCache.search(self, credential_type, **kwargs)))


def create_token_cache(cache_path: str) -> PersistedTokenCache:
    """Create a cache without reading credentials; persistence errors propagate on use."""
    if not cache_path:
        raise ValueError("An MSAL cache file path is required")
    location = os.path.abspath(os.path.expanduser(cache_path))
    directory = os.path.dirname(location)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    if os.name != "nt":
        os.chmod(directory, 0o700)
    return _SynchronizedTokenCache(_AtomicFilePersistence(location))
