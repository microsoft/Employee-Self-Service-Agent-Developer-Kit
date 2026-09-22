# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline tests for shared AgentConfiguration token-cache persistence."""

from __future__ import annotations

import json
import multiprocessing
import os
import stat
import sys
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path

import pytest
import portalocker
from msal import SerializableTokenCache, TokenCache
from msal_extensions import PersistedTokenCache


REPO_ROOT = Path(__file__).parents[3]
CORE_DIR = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_core"
)
sys.path.insert(0, str(CORE_DIR))

import _token_cache  # noqa: E402
from _token_cache import create_token_cache  # noqa: E402


ACCOUNT = TokenCache.CredentialType.ACCOUNT
REFRESH_TOKEN = TokenCache.CredentialType.REFRESH_TOKEN
ACCESS_TOKEN = TokenCache.CredentialType.ACCESS_TOKEN
Worker = Callable[[Path, str], tuple[BaseProcess, Connection]]


def _account(name: str) -> dict[str, str]:
    return {
        "home_account_id": name,
        "environment": "login.example.test",
        "realm": "test",
        "username": name,
    }


def _add_account(cache: TokenCache, name: str) -> None:
    entry = _account(name)
    cache.modify(ACCOUNT, entry, entry)


def _names(cache: TokenCache) -> set[str]:
    return {entry["username"] for entry in cache.search(ACCOUNT)}


def _disk_names(path: Path) -> set[str]:
    serialized = SerializableTokenCache()
    serialized.deserialize(path.read_text(encoding="utf-8"))
    return _names(serialized)


def _worker(cache_path: str, connection: Connection, operation: str) -> None:
    cache = create_token_cache(cache_path)
    list(cache.search(ACCOUNT))
    connection.send("ready")
    assert connection.recv() == "go"
    if operation == "write":
        for index in range(20):
            _add_account(cache, f"worker-{index}")
    elif operation == "read":
        for _ in range(80):
            assert "original" in _names(cache)
    elif operation == "delete":
        cache.modify(ACCOUNT, _account("original"))
    elif operation == "interrupt":
        def interrupt_replace(source: str, destination: str) -> None:
            connection.send("publishing")
            connection.recv()

        _token_cache.os.replace = interrupt_replace
        _add_account(cache, "unpublished")
    connection.send("done")
    connection.close()


@pytest.fixture
def worker() -> Iterator[Worker]:
    context = multiprocessing.get_context("spawn")
    processes: list[BaseProcess] = []
    connections: list[Connection] = []

    def start(path: Path, operation: str) -> tuple[BaseProcess, Connection]:
        parent, child = context.Pipe()
        process = context.Process(target=_worker, args=(str(path), child, operation))
        process.start()
        child.close()
        processes.append(process)
        connections.append(parent)
        assert parent.poll(15), "Cache worker did not initialize"
        assert parent.recv() == "ready"
        return process, parent

    yield start

    for process in processes:
        if process.is_alive():
            process.terminate()
        process.join(timeout=10)
        assert not process.is_alive(), "Cache worker did not stop"
        process.close()
    for connection in connections:
        connection.close()


def _finish(process: BaseProcess, connection: Connection) -> None:
    assert connection.poll(15), "Cache worker did not finish"
    assert connection.recv() == "done"
    process.join(timeout=10)
    assert process.exitcode == 0


def test_factory_rejects_an_empty_path() -> None:
    with pytest.raises(ValueError, match="file path is required"):
        create_token_cache("")


def test_factory_does_not_read_or_replace_existing_cache(tmp_path: Path) -> None:
    path = tmp_path / "cache.bin"
    path.write_text("not yet readable as JSON", encoding="utf-8")
    cache = create_token_cache(str(path))

    assert isinstance(cache, PersistedTokenCache)
    assert path.read_text(encoding="utf-8") == "not yet readable as JSON"


def test_reads_existing_utf8_serialized_cache_without_rewriting(tmp_path: Path) -> None:
    path = tmp_path / "cache.bin"
    old_cache = SerializableTokenCache()
    _add_account(old_cache, "caf\u00e9")
    content = json.dumps(json.loads(old_cache.serialize()), ensure_ascii=False)
    path.write_text(content, encoding="utf-8")

    cache = create_token_cache(str(path))

    assert _names(cache) == {"caf\u00e9"}
    assert path.read_text(encoding="utf-8") == content
    _add_account(cache, "second")
    assert _disk_names(path) == {"caf\u00e9", "second"}


def test_missing_cache_is_empty_until_a_mutation(tmp_path: Path) -> None:
    path = tmp_path / "state" / "cache.bin"
    cache = create_token_cache(str(path))

    assert _names(cache) == set()
    assert not path.exists()
    _add_account(cache, "first")
    assert _disk_names(path) == {"first"}


def test_independent_instances_preserve_updates_with_unchanged_mtime(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cache.bin"
    first = create_token_cache(str(path))
    second = create_token_cache(str(path))
    _add_account(first, "first")
    assert _names(second) == {"first"}
    _add_account(first, "second")
    os.utime(path, (1, 1))

    _add_account(second, "third")

    assert _disk_names(path) == {"first", "second", "third"}
    os.utime(path, (1, 1))
    assert _names(first) == {"first", "second", "third"}


def test_stale_instance_does_not_resurrect_removed_entries(tmp_path: Path) -> None:
    path = tmp_path / "cache.bin"
    first = create_token_cache(str(path))
    second = create_token_cache(str(path))
    _add_account(first, "removed")
    _add_account(first, "retained")
    assert _names(second) == {"removed", "retained"}
    first.modify(ACCOUNT, _account("removed"))
    os.utime(path, (1, 1))

    _add_account(second, "new")
    first.modify(ACCOUNT, _account("retained"))

    assert _disk_names(path) == {"new"}


def test_deleted_cache_does_not_restore_an_old_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "removed")
    path.unlink()

    assert _names(cache) == set()
    _add_account(cache, "new")
    assert _disk_names(path) == {"new"}


def test_refresh_token_update_and_removal_preserve_other_mutations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cache.bin"
    first = create_token_cache(str(path))
    second = create_token_cache(str(path))
    token = {
        "credential_type": REFRESH_TOKEN,
        "home_account_id": "example",
        "environment": "login.example.test",
        "client_id": "test-client",
        "secret": "old-test-secret",
    }
    first.modify(REFRESH_TOKEN, token, token)
    cached_token = next(second.search(REFRESH_TOKEN))
    _add_account(first, "retained")

    second.update_rt(cached_token, "new-test-secret")

    refreshed = next(first.search(REFRESH_TOKEN))
    assert refreshed["secret"] == "new-test-secret"
    _add_account(second, "new")
    first.remove_rt(refreshed)
    assert list(create_token_cache(str(path)).search(REFRESH_TOKEN)) == []
    assert _disk_names(path) == {"retained", "new"}


def test_expired_access_token_removal_persists_without_deadlocking(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    expired = {
        "credential_type": ACCESS_TOKEN,
        "home_account_id": "example",
        "environment": "login.example.test",
        "client_id": "test-client",
        "realm": "test",
        "target": "scope",
        "secret": "expired-test-secret",
        "expires_on": "1",
    }
    cache.modify(ACCESS_TOKEN, expired, expired)
    _add_account(create_token_cache(str(path)), "retained")

    assert list(cache.search(ACCESS_TOKEN)) == []
    assert json.loads(path.read_text(encoding="utf-8"))[ACCESS_TOKEN] == {}
    assert _disk_names(path) == {"retained"}


@pytest.mark.parametrize("content", ["{", "", "null", "[]", '{"Account": []}', '{"Account": {"bad": 1}}'])
def test_malformed_cache_errors_are_surfaced_without_overwriting(
    tmp_path: Path, content: str,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "stale")
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError):
        _names(cache)
    with pytest.raises(ValueError):
        _add_account(cache, "new")
    assert path.read_text(encoding="utf-8") == content


def test_read_failure_is_not_treated_as_an_empty_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "original")
    original = path.read_bytes()

    def fail_load(self: _token_cache._AtomicFilePersistence) -> str:
        raise PermissionError("test read denied")

    monkeypatch.setattr(_token_cache._AtomicFilePersistence, "load", fail_load)
    with pytest.raises(PermissionError, match="test read denied"):
        _names(cache)
    with pytest.raises(PermissionError, match="test read denied"):
        _add_account(cache, "new")
    assert path.read_bytes() == original


def test_invalid_utf8_is_surfaced_without_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "cache.bin"
    path.write_bytes(b"\xff")
    cache = create_token_cache(str(path))

    with pytest.raises(UnicodeDecodeError):
        _names(cache)
    with pytest.raises(UnicodeDecodeError):
        _add_account(cache, "new")
    assert path.read_bytes() == b"\xff"


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_failed_publication_keeps_old_cache_and_discards_uncommitted_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "original")
    original = path.read_bytes()

    def fail(*args: object) -> None:
        raise OSError("test publication failed")

    with monkeypatch.context() as patch:
        patch.setattr(_token_cache.os, operation, fail)
        with pytest.raises(OSError, match="test publication failed"):
            _add_account(cache, "unpublished")

    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == []
    assert _names(cache) == {"original"}
    _add_account(cache, "next")
    assert _disk_names(path) == {"original", "next"}


def test_cleanup_failure_does_not_mask_publication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "original")

    def fail_replace(*args: object) -> None:
        raise OSError("test publication failed")

    def fail_unlink(*args: object) -> None:
        raise PermissionError("test cleanup denied")

    with monkeypatch.context() as patch:
        patch.setattr(_token_cache.os, "replace", fail_replace)
        patch.setattr(_token_cache.os, "unlink", fail_unlink)
        with pytest.raises(OSError, match="test publication failed") as error:
            _add_account(cache, "unpublished")

    assert any("test cleanup denied" in note for note in error.value.__notes__)
    assert _disk_names(path) == {"original"}


def test_simultaneous_processes_preserve_both_sets_of_updates(
    tmp_path: Path, worker: Worker,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "original")
    process, connection = worker(path, "write")
    connection.send("go")

    for index in range(20):
        _add_account(cache, f"parent-{index}")
    _finish(process, connection)

    assert _disk_names(path) == (
        {"original"}
        | {f"parent-{index}" for index in range(20)}
        | {f"worker-{index}" for index in range(20)}
    )


def test_independent_reader_sees_complete_caches_during_writes(
    tmp_path: Path, worker: Worker,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "original")
    process, connection = worker(path, "read")
    connection.send("go")

    for index in range(20):
        _add_account(cache, f"parent-{index}")
    _finish(process, connection)

    assert len(_disk_names(path)) == 21


def test_process_deletion_survives_a_stale_writer(
    tmp_path: Path, worker: Worker,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "original")
    process, connection = worker(path, "delete")
    connection.send("go")
    _finish(process, connection)
    os.utime(path, (1, 1))

    _add_account(cache, "new")

    assert _disk_names(path) == {"new"}


def test_killed_publisher_leaves_old_cache_and_releases_process_lock(
    tmp_path: Path, worker: Worker,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "original")
    original = path.read_bytes()
    process, connection = worker(path, "interrupt")
    connection.send("go")
    assert connection.poll(15), "Worker did not reach publication"
    assert connection.recv() == "publishing"
    process.terminate()
    process.join(timeout=10)

    assert path.read_bytes() == original
    _add_account(cache, "next")
    assert _disk_names(path) == {"original", "next"}


def test_lock_timeout_is_surfaced_without_reading_or_mutating_stale_memory(
    tmp_path: Path, worker: Worker, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "original")
    original = path.read_bytes()
    process, connection = worker(path, "interrupt")
    connection.send("go")
    assert connection.poll(15), "Worker did not reach publication"
    assert connection.recv() == "publishing"
    monkeypatch.setattr(_token_cache, "_LOCK_TIMEOUT_SECONDS", 0.1)

    with pytest.raises(portalocker.exceptions.LockException):
        _names(cache)
    with pytest.raises(portalocker.exceptions.LockException):
        _add_account(cache, "unpublished")

    assert path.read_bytes() == original
    process.terminate()
    process.join(timeout=10)
    _add_account(cache, "next")
    assert _disk_names(path) == {"original", "next"}


def test_threads_sharing_one_instance_preserve_updates(tmp_path: Path) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = [
            executor.submit(_add_account, cache, f"thread-{index}")
            for index in range(20)
        ]
        for result in results:
            result.result(timeout=10)

    assert _disk_names(path) == {f"thread-{index}" for index in range(20)}


def test_search_iterator_does_not_hold_a_process_lock(
    tmp_path: Path, worker: Worker,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "original")
    entries = cache.search(ACCOUNT)
    assert next(entries)["username"] == "original"
    process, connection = worker(path, "write")
    connection.send("go")
    _finish(process, connection)

    assert len(_names(cache)) == 21


def test_publishes_fsynced_private_unique_sibling_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    real_fsync = os.fsync
    real_replace = os.replace
    synchronized: list[Path] = []
    published: list[Path] = []

    def check_fsync(descriptor: int) -> None:
        temporary, = tmp_path.glob("*.tmp")
        assert _disk_names(temporary)
        if os.name != "nt":
            assert stat.S_IMODE(temporary.stat().st_mode) == 0o600
        real_fsync(descriptor)
        synchronized.append(temporary)

    def check_replace(source: str, destination: str) -> None:
        temporary = Path(source)
        assert temporary.parent == path.parent
        assert temporary in synchronized
        assert temporary not in published
        real_replace(source, destination)
        published.append(temporary)

    monkeypatch.setattr(_token_cache.os, "fsync", check_fsync)
    monkeypatch.setattr(_token_cache.os, "replace", check_replace)
    _add_account(cache, "first")
    _add_account(cache, "second")

    assert _disk_names(path) == {"first", "second"}
    assert len(set(published)) == 2
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.skipif(os.name != "nt", reason="Windows denies replacing an unshared open file")
def test_external_windows_reader_blocks_publication_without_truncation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "original")
    with path.open("rb") as reader:
        original = reader.read()
        with pytest.raises(PermissionError):
            _add_account(cache, "unpublished")
        reader.seek(0)
        assert reader.read() == original

    assert path.read_bytes() == original
    assert _names(cache) == {"original"}
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_cache_and_directory_have_private_posix_permissions(tmp_path: Path) -> None:
    directory = tmp_path / "state"
    directory.mkdir(mode=0o755)
    path = directory / "cache.bin"
    cache = create_token_cache(str(path))
    _add_account(cache, "first")
    _add_account(cache, "second")

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
