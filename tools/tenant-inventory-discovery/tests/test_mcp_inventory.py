"""Contract tests for :class:`McpInventoryClient`.

These run against a *fake* MCP server -- a small script that speaks the same
newline-delimited JSON-RPC over stdio -- so they exercise the real transport
(subprocess, handshake, framing, stderr drain) without a service, a token, or a
network. What they pin is the boundary itself: that the Protocol methods serialize
correctly, that both MCP result shapes are understood, and that the server's error
envelope is rebuilt into the *same* exception types the HTTP client raises, since the
runner's retry and abort logic branches on exactly those.
"""

from __future__ import annotations

import json
import sys
import textwrap
from datetime import datetime, timezone

import pytest

from tenant_inventory_discovery.errors import (
    InventoryApiError,
    NonRetryableApiError,
    PreconditionFailedError,
    ThrottledError,
)
from tenant_inventory_discovery.mcp_inventory import (
    McpInventoryClient,
    McpTransportError,
)
from tenant_inventory_discovery.models import InventoryItem, Kind

_TENANT = "contoso.onmicrosoft.com"

_FAKE_SERVER = '''
"""Fake MCP server: replays a scripted response per tool and logs the arguments."""
import json, sys

SCRIPT = json.loads({script!r})
LOG_PATH = {log!r}

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    if method == "initialize":
        sys.stdout.write(json.dumps({{
            "jsonrpc": "2.0", "id": msg["id"],
            "result": {{"protocolVersion": "2024-11-05", "capabilities": {{}},
                       "serverInfo": {{"name": "fake", "version": "0"}}}},
        }}) + "\\n")
        sys.stdout.flush()
        continue
    if msg.get("id") is None:
        continue  # notification
    if method == "tools/call":
        name = msg["params"]["name"]
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({{"name": name,
                                 "arguments": msg["params"]["arguments"]}}) + "\\n")
        sys.stdout.write(json.dumps({{
            "jsonrpc": "2.0", "id": msg["id"], "result": SCRIPT[name],
        }}) + "\\n")
        sys.stdout.flush()
'''


@pytest.fixture
def make_client(tmp_path):
    """Build a client wired to a fake server that returns ``script[tool] -> result``."""
    created = []

    def _factory(script: dict, *, structured: bool = True):
        # Wrap each scripted payload in whichever MCP result shape is under test.
        wrapped = {}
        for name, payload in script.items():
            if isinstance(payload, dict) and "__raw__" in payload:
                wrapped[name] = payload["__raw__"]
            elif structured:
                wrapped[name] = {"structuredContent": payload, "isError": False}
            else:
                wrapped[name] = {
                    "content": [{"type": "text", "text": json.dumps(payload)}],
                    "isError": False,
                }

        log = tmp_path / "calls.jsonl"
        server = tmp_path / "fake_server.py"
        server.write_text(
            textwrap.dedent(_FAKE_SERVER).format(
                script=json.dumps(wrapped), log=str(log)
            ),
            encoding="utf-8",
        )
        client = McpInventoryClient(
            _TENANT, server_argv=[sys.executable, str(server)]
        )
        created.append(client)
        return client, log

    yield _factory
    for client in created:
        client.close()


def _calls(log_path) -> list[dict]:
    if not log_path.exists():
        return []
    return [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _ok(data):
    return {"ok": True, "data": data}


class TestProtocolMethods:
    """Each Protocol method must serialize its arguments the way the server expects."""

    def test_probe_sends_tenant(self, make_client):
        client, log = make_client({"probe": _ok({"reachable": True})})
        client.probe()
        assert _calls(log) == [{"name": "probe", "arguments": {"tenant_id": _TENANT}}]

    def test_upsert_flattens_the_item_and_forwards_run_id(self, make_client):
        client, log = make_client(
            {
                "upsert_item": _ok(
                    {
                        "naturalKey": "env-1",
                        "itemId": "opaque-1",
                        "etag": 'W/"3"',
                        "created": True,
                    }
                )
            }
        )
        item = InventoryItem(
            kind=Kind.ENVIRONMENT,
            natural_key="env-1",
            attributes={"environmentId": "env-1"},
            display_name="Env One",
            description="first",
        )

        result = client.upsert(item, if_match='W/"2"', run_id="run-7")

        args = _calls(log)[0]["arguments"]
        assert args["kind"] == "Environment"
        assert args["natural_key"] == "env-1"
        assert args["attributes"] == {"environmentId": "env-1"}
        assert args["display_name"] == "Env One"
        assert args["description"] == "first"
        assert args["if_match"] == 'W/"2"'
        # run_id must survive: it scopes the service-side idempotency key to this
        # pass, and dropping it would let a later pass replay an older write.
        assert args["run_id"] == "run-7"

        assert result.item_id == "opaque-1"
        assert result.etag == 'W/"3"'
        assert result.created is True
        assert result.kind is Kind.ENVIRONMENT

    def test_list_items_sends_the_kind_discriminator(self, make_client):
        rows = [{"id": "a"}, {"id": "b"}]
        client, log = make_client({"list_items": _ok(rows)})

        assert client.list_items(kind=Kind.CONNECTION, environment_id="env-1") == rows

        args = _calls(log)[0]["arguments"]
        assert args["kind"] == "Connection"
        assert args["environment_id"] == "env-1"

    def test_list_items_without_a_filter_sends_nulls(self, make_client):
        client, log = make_client({"list_items": _ok([])})
        client.list_items()
        args = _calls(log)[0]["arguments"]
        assert args["kind"] is None
        assert args["environment_id"] is None

    def test_retire_forwards_the_etag(self, make_client):
        client, log = make_client({"retire_item": _ok({"retired": "opaque-1"})})
        client.retire("opaque-1", if_match='W/"9"')
        args = _calls(log)[0]["arguments"]
        assert args["item_id"] == "opaque-1"
        assert args["if_match"] == 'W/"9"'

    def test_reconcile_normalizes_a_naive_watermark_to_utc(self, make_client):
        client, log = make_client(
            {
                "reconcile": _ok(
                    {
                        "evaluatedCount": 5,
                        "retiredCount": 2,
                        "retiredItemIds": ["x", "y"],
                    }
                )
            }
        )

        result = client.reconcile(
            Kind.CONNECTION, "env-1", datetime(2024, 5, 1, 12, 0, 0)
        )

        sent = _calls(log)[0]["arguments"]["pass_started_at"]
        # The service rejects an ambiguous watermark, so the offset must be explicit.
        assert datetime.fromisoformat(sent).tzinfo is not None
        assert datetime.fromisoformat(sent) == datetime(
            2024, 5, 1, 12, 0, tzinfo=timezone.utc
        )
        assert result.evaluated_count == 5
        assert result.retired_count == 2
        assert result.retired_item_ids == ["x", "y"]
        assert result.kind is Kind.CONNECTION


class TestResultShapes:
    """FastMCP may answer with structured content or only a JSON text block."""

    def test_reads_structured_content(self, make_client):
        client, _ = make_client({"list_items": _ok([{"id": "a"}])}, structured=True)
        assert client.list_items() == [{"id": "a"}]

    def test_falls_back_to_the_text_block(self, make_client):
        client, _ = make_client({"list_items": _ok([{"id": "a"}])}, structured=False)
        assert client.list_items() == [{"id": "a"}]

    def test_tool_level_failure_is_reported(self, make_client):
        client, _ = make_client(
            {
                "probe": {
                    "__raw__": {
                        "isError": True,
                        "content": [{"type": "text", "text": "tool exploded"}],
                    }
                }
            }
        )
        with pytest.raises(InventoryApiError, match="tool exploded"):
            client.probe()

    def test_non_json_content_is_a_transport_error(self, make_client):
        client, _ = make_client(
            {
                "probe": {
                    "__raw__": {
                        "isError": False,
                        "content": [{"type": "text", "text": "not json at all"}],
                    }
                }
            }
        )
        with pytest.raises(McpTransportError, match="non-JSON"):
            client.probe()

    def test_unrecognized_envelope_is_a_transport_error(self, make_client):
        client, _ = make_client({"probe": {"surprise": True}})
        with pytest.raises(McpTransportError, match="unrecognized payload"):
            client.probe()


class TestErrorRoundTrip:
    """The runner branches on the taxonomy, so the exact type has to survive."""

    def _err(self, **error):
        return {"ok": False, "error": error}

    def test_precondition_failed_keeps_its_natural_key(self, make_client):
        client, _ = make_client(
            {
                "upsert_item": self._err(
                    type="PreconditionFailedError",
                    message="precondition failed for env-1",
                    naturalKey="env-1",
                )
            }
        )
        item = InventoryItem(
            kind=Kind.ENVIRONMENT, natural_key="env-1", attributes={}
        )
        with pytest.raises(PreconditionFailedError) as excinfo:
            client.upsert(item, run_id="r")
        # Drift handling re-reads the row by natural key, so it must not be lost.
        assert excinfo.value.natural_key == "env-1"

    def test_throttled_keeps_retry_after(self, make_client):
        client, _ = make_client(
            {
                "list_items": self._err(
                    type="ThrottledError", message="throttled (429)", retryAfter=12.5
                )
            }
        )
        with pytest.raises(ThrottledError) as excinfo:
            client.list_items()
        # Backoff honours the server's requested delay rather than guessing.
        assert excinfo.value.retry_after == 12.5

    def test_non_retryable_stays_non_retryable(self, make_client):
        client, _ = make_client(
            {"probe": self._err(type="NonRetryableApiError", message="403 forbidden")}
        )
        with pytest.raises(NonRetryableApiError, match="403 forbidden"):
            client.probe()

    def test_retryable_stays_retryable(self, make_client):
        client, _ = make_client(
            {"probe": self._err(type="InventoryApiError", message="503 unavailable")}
        )
        with pytest.raises(InventoryApiError) as excinfo:
            client.probe()
        assert not isinstance(excinfo.value, NonRetryableApiError)

    def test_unknown_error_type_degrades_to_retryable(self, make_client):
        # A ValueError from the server (e.g. an unknown kind) has no local twin.
        client, _ = make_client(
            {"probe": self._err(type="ValueError", message="Unknown kind 'Nope'.")}
        )
        with pytest.raises(InventoryApiError, match="Unknown kind"):
            client.probe()


class TestTransportFailures:
    def test_a_server_that_will_not_start_fails_loudly(self, tmp_path):
        script = tmp_path / "boom.py"
        script.write_text(
            "import sys; sys.stderr.write('cannot import wevenova\\n'); "
            "sys.exit(3)",
            encoding="utf-8",
        )
        with pytest.raises(McpTransportError) as excinfo:
            McpInventoryClient(_TENANT, server_argv=[sys.executable, str(script)])
        # The stderr tail is the only clue when a server dies during startup.
        assert "cannot import wevenova" in str(excinfo.value)

    def test_a_server_that_dies_mid_session_fails_loudly(self, tmp_path):
        script = tmp_path / "half.py"
        script.write_text(
            textwrap.dedent(
                """
                import json, sys
                line = sys.stdin.readline()
                msg = json.loads(line)
                sys.stdout.write(json.dumps({
                    "jsonrpc": "2.0", "id": msg["id"], "result": {}}) + "\\n")
                sys.stdout.flush()
                sys.stderr.write("crashed\\n")
                sys.exit(1)
                """
            ),
            encoding="utf-8",
        )
        client = McpInventoryClient(_TENANT, server_argv=[sys.executable, str(script)])
        with pytest.raises(McpTransportError):
            client.probe()
        client.close()


# A server that answers on threads, deliberately out of arrival order -- which the real
# MCP SDK also does, since it dispatches each request with ``tg.start_soon``.
_CONCURRENT_SERVER = '''
"""Fake MCP server that answers concurrently and out of order."""
import json, sys, threading, time

write_lock = threading.Lock()
workers = []


def send(payload):
    with write_lock:
        sys.stdout.write(json.dumps(payload) + "\\n")
        sys.stdout.flush()


def handle(msg):
    key = msg["params"]["arguments"].get("natural_key") or ""
    # Invert latency against arrival order so replies are guaranteed to interleave.
    time.sleep(0.05 if key.endswith("0") else 0.005)
    send({
        "jsonrpc": "2.0",
        "id": msg["id"],
        "result": {
            "structuredContent": {
                "ok": True,
                # Echo the key back so the test can prove each caller got *its* reply.
                "data": {"naturalKey": key, "itemId": "id-" + key, "created": True},
            },
            "isError": False,
        },
    })


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        send({
            "jsonrpc": "2.0", "id": msg["id"],
            "result": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "serverInfo": {"name": "fake", "version": "0"}},
        })
        continue
    if msg.get("id") is None:
        continue
    worker = threading.Thread(target=handle, args=(msg,), daemon=True)
    workers.append(worker)
    worker.start()

for worker in workers:
    worker.join()
'''


class TestConcurrentCalls:
    """One process, one pipe, many caller threads.

    The runner upserts through a ``ThreadPoolExecutor``, so several threads share this
    single client. A transport that scans the pipe for its *own* id and drops whatever
    else it reads will swallow another thread's reply and hang that thread forever --
    which is exactly what made ``/discover`` go silent mid-run. These tests pin the
    multiplexing behaviour that prevents it.
    """

    @pytest.fixture
    def client(self, tmp_path):
        server = tmp_path / "concurrent_server.py"
        server.write_text(textwrap.dedent(_CONCURRENT_SERVER), encoding="utf-8")
        client = McpInventoryClient(
            _TENANT, server_argv=[sys.executable, str(server)], timeout=60.0
        )
        yield client
        client.close()

    @staticmethod
    def _item(index: int) -> InventoryItem:
        return InventoryItem(
            kind=Kind.CONNECTION,
            natural_key=f"key-{index}",
            display_name=f"Item {index}",
            environment_id="env-prod",
            attributes={},
        )

    def test_every_caller_gets_its_own_reply(self, client):
        from concurrent.futures import ThreadPoolExecutor

        count = 24
        with ThreadPoolExecutor(max_workers=4) as pool:
            # A deadlock here would hang the suite, so bound the wait: any thread that
            # loses its reply shows up as a timeout, not a stuck test run.
            futures = [
                pool.submit(client.upsert, self._item(i)) for i in range(count)
            ]
            results = [f.result(timeout=60) for f in futures]

        assert len(results) == count
        # Not just "all completed": each reply must be routed back to the caller that
        # asked for it, even though the server answered in a shuffled order.
        assert [r.natural_key for r in results] == [f"key-{i}" for i in range(count)]
        assert [r.item_id for r in results] == [f"id-key-{i}" for i in range(count)]

    def test_ids_stay_unique_under_concurrent_callers(self, client):
        from concurrent.futures import ThreadPoolExecutor

        # Allocating a request id is a read-modify-write; if it races, two in-flight
        # requests collide on one id and one of them can never be answered.
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(client.upsert, self._item(i)) for i in range(40)]
            keys = [f.result(timeout=60).natural_key for f in futures]

        assert len(set(keys)) == 40
