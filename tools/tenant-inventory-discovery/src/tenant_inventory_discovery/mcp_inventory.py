# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""``InventoryClient`` backed by the local WeveNova MCP server.

The third implementation of the :class:`InventoryClient` Protocol, alongside
``HttpInventoryClient`` (direct HTTP) and ``InMemoryInventoryClient`` (no service).
It speaks MCP over stdio to a server the caller spawns, so the crawler never handles
a bearer token, a self-signed certificate, or an OData URL -- the server owns all
three. See ``solutions/ess-maker-skills/src/mcp/wevenova/server.py``.

**Why a hand-rolled JSON-RPC client rather than the MCP SDK's:** the SDK client is
async, and the crawler is synchronous top to bottom. Adapting it would mean either an
event loop per call or a background loop thread, both of which are more machinery than
the four requests this needs. The stdio transport is newline-delimited JSON-RPC 2.0,
so a synchronous client stays small and adds no dependency to a package whose only
runtime import today is ``httpx``.

The transport is **multiplexed**, not request/response-in-lockstep: a single reader
thread owns stdout and routes each frame to the caller waiting on its id. See
:class:`_StdioJsonRpc`.

Errors raised by the server are re-raised here as the *same* exception types the HTTP
client raises. That is what lets the runner and skill treat this as a drop-in: their
retry and abort logic both branch on that taxonomy.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Sequence
from typing import Any

from .config import DiscoveryConfig
from .errors import (
    InventoryApiError,
    NonRetryableApiError,
    ThrottledError,
)
from .models import (
    FailedSyncItem,
    InventoryItem,
    Kind,
    SyncResult,
)

#: MCP revision this client negotiates. The server tolerates older clients.
PROTOCOL_VERSION = "2024-11-05"

#: How long one MCP call may take before the server is declared wedged. Deliberately
#: generous: the sync call carries the tenant's whole inventory in one request, and
#: answering it can mean minting a token (up to 180s) and then replaying a throttled
#: POST through the HTTP client's whole backoff budget. A bound still matters --
#: without one, a server that dies holding the pipe open would hang the crawl forever
#: instead of failing it.
#:
#: Kept strictly **above** :attr:`DiscoveryConfig.sync_timeout_seconds`, because the
#: server runs that HTTP call inside this RPC and whichever budget expires first owns
#: the error the user sees. The inner one names the payload size, says the write may
#: still be landing, and points at the knob to turn; this one can only report that the
#: server went quiet. Equal budgets race, and the race loses the better message.
DEFAULT_REQUEST_TIMEOUT = DiscoveryConfig().sync_timeout_seconds + 120.0

#: Server-reported error type name -> local exception class.
_ERROR_TYPES: dict[str, type[Exception]] = {
    "ThrottledError": ThrottledError,
    "NonRetryableApiError": NonRetryableApiError,
    "InventoryApiError": InventoryApiError,
}


class McpTransportError(InventoryApiError):
    """The MCP server could not be reached, or answered with something unusable.

    Subclasses :class:`InventoryApiError` so a transport fault is treated as transient
    and retried, matching how the HTTP client classifies a dropped connection.
    """


class _Pending:
    """One in-flight request, waiting for the reader thread to hand it a reply."""

    __slots__ = ("event", "message", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.message: dict[str, Any] | None = None
        self.error: Exception | None = None


class _StdioJsonRpc:
    """Thread-safe synchronous JSON-RPC 2.0 client over a child process's stdio.

    One pipe carries every request, and replies may come back **out of order**: the MCP
    server dispatches each incoming message with ``task_group.start_soon``
    (``mcp.server.lowlevel.Server.run``), so nothing guarantees the server answers in
    arrival order even when a client sends one request at a time.

    That rules out the obvious "send, then read until my own id appears" loop. Two
    threads reading the same pipe race for each line, and the winner *discards* any
    frame that is not its own -- so the thread that reply actually belonged to waits
    forever on a response no one will send again.

    Hence: exactly one reader thread owns stdout and routes each frame to the waiter
    registered under its id. Callers block on their own event, never on the pipe, and
    a bounded wait turns a wedged server into an error instead of a hang.
    """

    def __init__(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        env=None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self._proc = subprocess.Popen(  # noqa: S603 - argv is caller-controlled
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=cwd,
            env=env,
        )
        self._timeout = timeout
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._fatal: Exception | None = None
        self._stderr: list[str] = []
        # Drain stderr continuously: a full pipe would deadlock the server, and the
        # text is the only useful diagnostic when the process dies during startup.
        self._stderr_thread = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_thread.start()
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()
        try:
            self._handshake()
        except BaseException:
            # The constructor is the only thing holding this subprocess. If it raises,
            # the caller never gets an object to close(), so the child would survive
            # with its stdio pipes open until it decided to exit on its own.
            self.close()
            raise

    def _drain_stderr(self) -> None:
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            self._stderr.append(line.rstrip())
            del self._stderr[:-50]  # keep only the tail

    def _stderr_tail(self) -> str:
        return "\n".join(self._stderr[-10:]).strip()

    # -- reader thread ---------------------------------------------------------------

    def _read_loop(self) -> None:
        """Own stdout: parse frames and hand each one to the waiter for its id."""
        assert self._proc.stdout is not None
        try:
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    break  # EOF: the server closed its output
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    # Anything the server prints to stdout that is not a frame would
                    # corrupt the stream; skip it rather than failing the whole run.
                    continue
                request_id = message.get("id")
                if request_id is None:
                    continue  # server-initiated notification
                with self._pending_lock:
                    pending = self._pending.pop(request_id, None)
                if pending is not None:
                    pending.message = message
                    pending.event.set()
        except Exception as exc:  # noqa: BLE001 - surfaced to every waiter below
            self._fail_all(McpTransportError(f"MCP server stream failed: {exc}"))
            return
        # The stderr drain may not have caught up with the crash that closed stdout,
        # and that tail is the only diagnostic worth having here.
        self._stderr_thread.join(timeout=1.0)
        self._fail_all(
            McpTransportError(
                "MCP server closed its output before responding. "
                f"stderr: {self._stderr_tail() or '(empty)'}"
            )
        )

    def _fail_all(self, exc: Exception) -> None:
        """Record a terminal transport fault and wake every waiter with it."""
        with self._pending_lock:
            if self._fatal is None:
                self._fatal = exc
            pending, self._pending = self._pending, {}
        for waiter in pending.values():
            waiter.error = exc
            waiter.event.set()

    # -- request/response ------------------------------------------------------------

    def _send(self, message: dict[str, Any]) -> None:
        if self._proc.poll() is not None:
            raise McpTransportError(
                f"MCP server exited with code {self._proc.returncode}. "
                f"stderr: {self._stderr_tail() or '(empty)'}"
            )
        assert self._proc.stdin is not None
        try:
            # One writer at a time: two interleaved writes would produce a frame the
            # server cannot parse.
            with self._write_lock:
                self._proc.stdin.write(json.dumps(message) + "\n")
                self._proc.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise McpTransportError(
                f"MCP server closed its input: {exc}. "
                f"stderr: {self._stderr_tail() or '(empty)'}"
            ) from exc

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        with self._id_lock:
            self._next_id += 1
            request_id = self._next_id

        pending = _Pending()
        with self._pending_lock:
            if self._fatal is not None:
                raise self._fatal
            # Register *before* sending: a fast reply must never arrive with no
            # waiter to route it to.
            self._pending[request_id] = pending

        try:
            self._send({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            })
        except Exception:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise

        if not pending.event.wait(self._timeout):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise McpTransportError(
                f"MCP {method} did not answer within {self._timeout:.0f}s. "
                f"stderr: {self._stderr_tail() or '(empty)'}"
            )

        if pending.error is not None:
            raise pending.error
        message = pending.message or {}
        if "error" in message:
            error = message["error"]
            raise McpTransportError(
                f"MCP {method} failed: {error.get('message')} "
                f"(code {error.get('code')})"
            )
        return message.get("result") or {}

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _handshake(self) -> None:
        self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "tenant-inventory-discovery",
                    "version": "1.0.0",
                },
            },
        )
        self.notify("notifications/initialized", {})

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.close()
                self._proc.wait(timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                self._proc.kill()
        self._reader_thread.join(timeout=5)
        self._fail_all(McpTransportError("MCP server connection was closed."))


def default_server_argv(repo_root: str) -> list[str]:
    """Command that launches the bundled WeveNova MCP server."""
    import os

    return [
        sys.executable,
        os.path.join(
            repo_root,
            "solutions",
            "ess-maker-skills",
            "src",
            "mcp",
            "wevenova",
            "server.py",
        ),
    ]


class McpInventoryClient:
    """Talks to the Inventory API through the local WeveNova MCP server."""

    def __init__(
        self,
        tenant_id: str,
        *,
        server_argv: list[str],
        cwd: str | None = None,
        env=None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
    ) -> None:
        self._tenant_id = tenant_id
        self._rpc = _StdioJsonRpc(server_argv, cwd=cwd, env=env, timeout=timeout)

    # -- plumbing --------------------------------------------------------------------

    def _tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call one MCP tool and unwrap the ``{ok, data|error}`` envelope."""
        result = self._rpc.request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        payload = self._unwrap(result, name)

        if not isinstance(payload, dict) or "ok" not in payload:
            raise McpTransportError(
                f"Tool '{name}' returned an unrecognized payload: {payload!r}"
            )
        if payload["ok"]:
            return payload.get("data")

        error = payload.get("error") or {}
        exc_type = _ERROR_TYPES.get(error.get("type", ""), InventoryApiError)
        message = error.get("message", "unknown error")
        # Rebuild the richer type from its own fields so the caller still sees
        # ``retry_after``, not just a sentence.
        if exc_type is ThrottledError:
            raise ThrottledError(error.get("retryAfter"))
        raise exc_type(message)

    @staticmethod
    def _unwrap(result: dict[str, Any], name: str) -> Any:
        """Pull the tool's return value out of an MCP ``tools/call`` result."""
        if result.get("isError"):
            blocks = result.get("content") or []
            text = blocks[0].get("text", "") if blocks else ""
            raise InventoryApiError(f"Tool '{name}' failed: {text or 'unknown error'}")

        # Newer servers send the value directly; older ones only serialize it as text.
        if "structuredContent" in result:
            return result["structuredContent"]

        blocks = result.get("content") or []
        if not blocks:
            raise McpTransportError(f"Tool '{name}' returned no content.")
        text = blocks[0].get("text", "")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise McpTransportError(
                f"Tool '{name}' returned non-JSON content: {text[:200]}"
            ) from exc

    # -- InventoryClient Protocol ----------------------------------------------------

    def probe(self) -> None:
        self._tool("probe", {"tenant_id": self._tenant_id})

    def list_items(
        self, *, kind: Kind | None = None, environment_id: str | None = None
    ) -> list[dict[str, Any]]:
        data = self._tool(
            "list_items",
            {
                "tenant_id": self._tenant_id,
                "kind": kind.discriminator if kind else None,
                "environment_id": environment_id,
            },
        )
        return list(data or [])

    def sync_inventory(
        self, items: Sequence[InventoryItem], *, run_id: str = ""
    ) -> SyncResult:
        """Submit the tenant's whole inventory in one call.

        The items cross the pipe in their domain shape, not the wire shape: building
        the request body is :class:`HttpInventoryClient`'s job, and duplicating it here
        would give the payload two independent encoders to drift apart.
        """
        payload = [
            {
                "kind": item.kind.discriminator,
                "natural_key": item.natural_key,
                "attributes": item.attributes,
                "environment_id": item.environment_id,
                "display_name": item.display_name,
                "description": item.description,
            }
            for item in items
        ]
        data = self._tool(
            "sync_inventory",
            {
                "tenant_id": self._tenant_id,
                "items": payload,
                "run_id": run_id,
            },
        )
        failed = [
            FailedSyncItem(
                item_id=str(f.get("itemId") or ""),
                reason=str(f.get("reason") or ""),
            )
            for f in (data.get("failedItems") or [])
        ]
        return SyncResult(
            submitted_count=int(data.get("submittedCount", len(payload))),
            upserted_count=int(data.get("upsertedCount", 0)),
            retired_count=int(data.get("retiredCount", 0)),
            retired_item_ids=list(data.get("retiredItemIds") or []),
            failed_items=failed,
        )

    def server_info(self) -> dict[str, Any]:
        """Target and token strategy the server is using. Never includes the token."""
        return self._tool("server_info", {})

    def close(self) -> None:
        self._rpc.close()
