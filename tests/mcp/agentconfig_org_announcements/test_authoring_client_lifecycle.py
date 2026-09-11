# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lifecycle guards for the process-global AgentConfiguration authoring client.

Three properties are load-bearing for an MCP server and are asserted here
because none of them is visible from the tool contracts:

* construction must not run on the asyncio event loop, because the shared core
  resolves a delegated token synchronously and can block on a human;
* nothing may reach stdout, because stdout is the JSON-RPC transport; and
* an expired token must be recoverable without restarting the MCP host.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import sys
import threading
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _mcp_modules import load_org_announcements_modules  # noqa: E402

_ORG_MODULES = load_org_announcements_modules()
org_server = _ORG_MODULES["server"]
org_client = _ORG_MODULES["client"]


@pytest.fixture(autouse=True)
def _reset_globals():
    """Never leak a fake client between tests or into another module."""
    org_server._client = None
    yield
    org_server._client = None


class _FakeAuthoringClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    async def list_bulletins(self) -> list[dict[str, Any]]:
        return []


# --------------------------------------------------------------------------
# Lazy, off-loop construction
# --------------------------------------------------------------------------


def test_importing_the_server_constructs_no_authoring_client() -> None:
    """Import must be side-effect free; a token prompt at import is fatal."""
    assert org_server._client is None


def test_the_authoring_client_is_constructed_off_the_event_loop(
    monkeypatch,
) -> None:
    """The shared core resolves its token synchronously in ``__init__``.

    On a cold cache that blocks for as long as a human takes to finish a browser
    sign-in. Running it inline would freeze the event loop — and with it every
    other in-flight request and the MCP stdio transport.
    """
    threads: list[int] = []

    def _construct() -> _FakeAuthoringClient:
        threads.append(threading.get_ident())
        return _FakeAuthoringClient()

    monkeypatch.setattr(org_server, "OrgAnnouncementsClient", _construct)

    async def run() -> int:
        loop_thread = threading.get_ident()
        await org_server.get_client()
        return loop_thread

    loop_thread = asyncio.run(run())

    assert len(threads) == 1
    assert threads[0] != loop_thread, "the client was built on the event loop"


def test_the_authoring_client_is_built_once_and_reused(monkeypatch) -> None:
    constructions: list[int] = []

    def _construct() -> _FakeAuthoringClient:
        constructions.append(1)
        return _FakeAuthoringClient()

    monkeypatch.setattr(org_server, "OrgAnnouncementsClient", _construct)

    async def run() -> None:
        first = await org_server.get_client()
        second = await org_server.get_client()
        assert first is second

    asyncio.run(run())

    assert constructions == [1]


def test_concurrent_first_calls_share_one_construction(monkeypatch) -> None:
    """Two tool calls at once must not race two interactive sign-ins."""
    constructions: list[int] = []

    def _construct() -> _FakeAuthoringClient:
        constructions.append(1)
        return _FakeAuthoringClient()

    monkeypatch.setattr(org_server, "OrgAnnouncementsClient", _construct)

    async def run() -> list:
        return await asyncio.gather(
            org_server.get_client(),
            org_server.get_client(),
            org_server.get_client(),
        )

    clients = asyncio.run(run())

    assert constructions == [1]
    assert clients[0] is clients[1] is clients[2]


# --------------------------------------------------------------------------
# Reauthentication after a 401
# --------------------------------------------------------------------------


def test_reset_drops_and_closes_the_authoring_client(monkeypatch) -> None:
    monkeypatch.setattr(
        org_server, "OrgAnnouncementsClient", _FakeAuthoringClient
    )

    async def run() -> _FakeAuthoringClient:
        client = await org_server.get_client()
        await org_server.reset_client()
        assert org_server._client is None
        return client

    client = asyncio.run(run())

    assert client.closed, "the stale client was dropped without being closed"


def test_the_call_after_a_reset_builds_a_fresh_client(monkeypatch) -> None:
    """Rebuilding is the reauthentication mechanism.

    The shared core resolves its token once, in ``__init__``, and never
    refreshes it, so a new object is what re-runs silent-first MSAL.
    """
    built: list[_FakeAuthoringClient] = []

    def _construct() -> _FakeAuthoringClient:
        client = _FakeAuthoringClient()
        built.append(client)
        return client

    monkeypatch.setattr(org_server, "OrgAnnouncementsClient", _construct)

    async def run() -> None:
        first = await org_server.get_client()
        await org_server.reset_client()
        second = await org_server.get_client()
        assert first is not second

    asyncio.run(run())

    assert len(built) == 2


def test_an_authoring_401_resets_the_client(monkeypatch) -> None:
    """A stale token must not fail every later tool call until restart."""
    monkeypatch.setattr(
        org_server, "OrgAnnouncementsClient", _FakeAuthoringClient
    )

    async def run() -> None:
        client = await org_server.get_client()
        failure = await org_server._failure_from(
            org_client.AgentConfigApiError("HttpError: HTTP 401", http_status=401)
        )
        assert failure.code == "AuthenticationRequired"
        assert org_server._client is None
        assert client.closed

    asyncio.run(run())


def test_a_graph_401_does_not_reset_the_authoring_client(monkeypatch) -> None:
    """Both surfaces report ``AuthenticationRequired``; only one should reset.

    The Graph client handles its own expiry, so resetting here would throw away
    a perfectly good WeveNova token and force a needless second sign-in.
    """
    monkeypatch.setattr(
        org_server, "OrgAnnouncementsClient", _FakeAuthoringClient
    )
    graph_error = _ORG_MODULES["graph_directory_client"].GraphDirectoryError(
        "graph token expired", code="AuthenticationRequired", retryable=False
    )

    async def run() -> None:
        client = await org_server.get_client()
        failure = await org_server._failure_from(graph_error)
        assert failure.code == "AuthenticationRequired"
        assert failure.source == org_server.SOURCE_GRAPH
        assert org_server._client is client
        assert not client.closed

    asyncio.run(run())


@pytest.mark.parametrize("status", [403, 404, 429, 500, 503])
def test_non_401_authoring_failures_keep_the_client(monkeypatch, status) -> None:
    monkeypatch.setattr(
        org_server, "OrgAnnouncementsClient", _FakeAuthoringClient
    )

    async def run() -> None:
        client = await org_server.get_client()
        await org_server._failure_from(
            org_client.AgentConfigApiError(
                f"HttpError: HTTP {status}", http_status=status
            )
        )
        assert org_server._client is client
        assert not client.closed

    asyncio.run(run())


def test_resetting_when_no_client_exists_is_a_no_op() -> None:
    async def run() -> None:
        await org_server.reset_client()
        assert org_server._client is None

    asyncio.run(run())


# --------------------------------------------------------------------------
# stdout purity
# --------------------------------------------------------------------------


def _fake_msal(monkeypatch, tmp_path, *, interactive: bool):
    """Patch MSAL so the shared core runs its sign-in path without a browser.

    The interactive path is exercised for real up to and including the sign-in
    notice — that notice is what these tests are about — so the loopback
    listener is replaced with a fake that completes immediately instead of
    blocking on a callback that will never arrive.
    """
    import base_client

    class _FakeApp:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_accounts(self):
            return [] if interactive else [{"username": "maker@contoso.com"}]

        def acquire_token_silent(self, *args: Any, **kwargs: Any):
            return None if interactive else {"access_token": _fake_jwt()}

        def initiate_auth_code_flow(self, *args: Any, **kwargs: Any):
            return {"auth_uri": "https://login.microsoftonline.com/fake"}

        def acquire_token_by_auth_code_flow(self, *args: Any, **kwargs: Any):
            return {"access_token": _fake_jwt()}

    class _FakeCache:
        has_state_changed = False

        def deserialize(self, data: str) -> None:
            pass

        def serialize(self) -> str:
            return ""

    class _FakeHTTPServer:
        """Stands in for the loopback form_post listener."""

        server_port = 54321

        def __init__(self, address, handler) -> None:
            self._handler = handler

        def handle_request(self) -> None:
            self._handler.captured = {"code": "fake-auth-code"}

        def server_close(self) -> None:
            pass

    import msal

    monkeypatch.setattr(msal, "PublicClientApplication", _FakeApp)
    monkeypatch.setattr(base_client, "create_token_cache", lambda path: _FakeCache())
    monkeypatch.setattr(base_client, "_TOKEN_CACHE_PATH", str(tmp_path / "c.bin"))
    monkeypatch.setattr(base_client, "_LOCAL_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(base_client.http.server, "HTTPServer", _FakeHTTPServer)
    # Never open a real browser.
    monkeypatch.setattr(base_client.webbrowser, "open", lambda url: True)
    return base_client


def _fake_jwt() -> str:
    import base64
    import json

    payload = base64.urlsafe_b64encode(
        json.dumps({"tid": "11111111-2222-3333-4444-555555555555"}).encode()
    ).rstrip(b"=")
    return f"header.{payload.decode('ascii')}.signature"


def test_the_shared_core_sign_in_notice_never_touches_stdout(
    monkeypatch, tmp_path
) -> None:
    """stdout is the MCP JSON-RPC transport.

    A bare line printed there injects non-protocol text into the stream and
    corrupts the session for every MCP server built on this shared core, not
    just this one.
    """
    base_client = _fake_msal(monkeypatch, tmp_path, interactive=True)

    captured_out, captured_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(
        captured_err
    ):
        token = base_client.acquire_token_msal_interactive()

    assert token == _fake_jwt()
    assert captured_out.getvalue() == "", "the sign-in notice reached stdout"
    # The cue is preserved for the maker, on the safe stream.
    assert "Opening browser" in captured_err.getvalue()


def test_a_silent_sign_in_writes_nothing_at_all(monkeypatch, tmp_path) -> None:
    base_client = _fake_msal(monkeypatch, tmp_path, interactive=False)

    captured_out, captured_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(captured_out), contextlib.redirect_stderr(
        captured_err
    ):
        base_client.acquire_token_msal_interactive()

    assert captured_out.getvalue() == ""
    assert captured_err.getvalue() == ""


def test_constructing_the_authoring_client_writes_nothing_to_stdout(
    monkeypatch, tmp_path
) -> None:
    """End-to-end: the server's own construction path stays stdout-clean."""
    _fake_msal(monkeypatch, tmp_path, interactive=True)
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)
    monkeypatch.setenv(
        "ORG_ANNOUNCEMENTS_BASE_URL", "https://substrate.office.com/weveb2/api/v1.1"
    )

    captured_out = io.StringIO()

    async def run() -> Any:
        with contextlib.redirect_stdout(captured_out):
            return await org_server.get_client()

    client = asyncio.run(run())

    assert isinstance(client, org_client.OrgAnnouncementsClient)
    assert captured_out.getvalue() == ""


def test_no_module_in_the_server_writes_to_stdout_at_import() -> None:
    """A bare print at import corrupts the transport before any tool runs."""
    source_dir = (
        REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "mcp"
        / "agentconfig_org_announcements"
    )
    core_dir = (
        REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "mcp"
        / "agentconfig_core"
    )

    offenders: list[str] = []
    for path in sorted(source_dir.glob("*.py")) + sorted(core_dir.glob("*.py")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            stripped = line.strip()
            if not stripped.startswith("print("):
                continue
            # A print is only acceptable when it is explicitly routed to stderr.
            window = "\n".join(
                path.read_text(encoding="utf-8").splitlines()[number - 1 : number + 5]
            )
            if "file=sys.stderr" not in window:
                offenders.append(f"{path.name}:{number}: {stripped}")

    assert not offenders, "print() to stdout in an MCP server module: " + "; ".join(
        offenders
    )


def test_httpx_logging_stays_off_the_transport() -> None:
    """httpx logs requests at INFO; the URL would carry the tenant endpoint."""
    import logging

    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING
