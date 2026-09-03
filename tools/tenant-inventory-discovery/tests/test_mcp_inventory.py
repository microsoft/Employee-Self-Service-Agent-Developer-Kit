"""Contract tests for :class:`McpInventoryClient`.

These run against a fake MCP server that speaks newline-delimited JSON-RPC over
stdio, so they exercise the real transport while pinning the migrated Protocol
surface: ``sync_inventory`` plus the unchanged read/probe helpers.
"""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from tenant_inventory_discovery.errors import (
    InventoryApiError,
    NonRetryableApiError,
    ThrottledError,
)
from tenant_inventory_discovery.mcp_inventory import McpInventoryClient, McpTransportError
from tenant_inventory_discovery.models import InventoryItem, Kind

_TENANT = "contoso.onmicrosoft.com"

_FAKE_SERVER = '''
"""Fake MCP server: replays a scripted response per tool and logs arguments."""
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
        continue
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
    """Build a client wired to a fake server that returns ``script[tool]``."""
    created = []

    def _factory(script: dict, *, structured: bool = True):
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
        client = McpInventoryClient(_TENANT, server_argv=[sys.executable, str(server)])
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


def _environment_item() -> InventoryItem:
    return InventoryItem(
        kind=Kind.ENVIRONMENT,
        natural_key="env-1",
        attributes={"environmentId": "env-1"},
        display_name="Env One",
        description="first",
    )


class TestProtocolMethods:
    """Each Protocol method must serialize arguments as the server expects."""

    def test_probe_sends_tenant(self, make_client):
        client, log = make_client({"probe": _ok({"reachable": True})})
        client.probe()
        assert _calls(log) == [{"name": "probe", "arguments": {"tenant_id": _TENANT}}]

    def test_sync_inventory_flattens_items_and_forwards_run_id(self, make_client):
        client, log = make_client(
            {
                "sync_inventory": _ok(
                    {
                        "submittedCount": 1,
                        "upsertedCount": 1,
                        "retiredCount": 0,
                        "retiredItemIds": [],
                        "failedItems": [],
                    }
                )
            }
        )

        result = client.sync_inventory([_environment_item()], run_id="run-7")

        call = _calls(log)[0]
        assert call["name"] == "sync_inventory"
        args = call["arguments"]
        assert args["tenant_id"] == _TENANT
        assert args["run_id"] == "run-7"
        assert args["items"] == [
            {
                "kind": "Environment",
                "natural_key": "env-1",
                "attributes": {"environmentId": "env-1"},
                "environment_id": None,
                "display_name": "Env One",
                "description": "first",
            }
        ]
        assert result.submitted_count == 1
        assert result.upserted_count == 1

    def test_sync_inventory_parses_failed_items(self, make_client):
        client, _ = make_client(
            {
                "sync_inventory": _ok(
                    {
                        "submittedCount": 2,
                        "upsertedCount": 1,
                        "retiredCount": 0,
                        "retiredItemIds": [],
                        "failedItems": [
                            {"itemId": "Connection:e1:c1", "reason": "missing parent"}
                        ],
                    }
                )
            }
        )

        result = client.sync_inventory([_environment_item()], run_id="r")

        assert result.submitted_count == 2
        assert result.failed_item_ids == ["Connection:e1:c1"]
        assert result.failed_items[0].reason == "missing parent"

    def test_list_items_sends_the_kind_discriminator(self, make_client):
        rows = [{"id": "a"}, {"id": "b"}]
        client, log = make_client({"list_items": _ok(rows)})

        assert client.list_items(kind=Kind.CONNECTION, environment_id="env-1") == rows

        args = _calls(log)[0]["arguments"]
        assert args["tenant_id"] == _TENANT
        assert args["kind"] == "Connection"
        assert args["environment_id"] == "env-1"

    def test_list_items_without_a_filter_sends_nulls(self, make_client):
        client, log = make_client({"list_items": _ok([])})
        client.list_items()
        args = _calls(log)[0]["arguments"]
        assert args["kind"] is None
        assert args["environment_id"] is None


class TestResultShapes:
    """FastMCP may answer with structured content or only JSON text."""

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
    """The runner branches on the taxonomy, so exact types must survive."""

    def _err(self, **error):
        return {"ok": False, "error": error}

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
        client, _ = make_client(
            {"probe": self._err(type="ValueError", message="Unknown kind 'Nope'.")}
        )
        with pytest.raises(InventoryApiError, match="Unknown kind"):
            client.probe()


class TestTransportFailures:
    def test_a_server_that_will_not_start_fails_loudly(self, tmp_path):
        script = tmp_path / "boom.py"
        script.write_text(
            "import sys; sys.stderr.write('cannot import wevenova\\n'); sys.exit(3)",
            encoding="utf-8",
        )
        with pytest.raises(McpTransportError) as excinfo:
            McpInventoryClient(_TENANT, server_argv=[sys.executable, str(script)])
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
    item = (msg["params"]["arguments"].get("items") or [{}])[0]
    key = item.get("natural_key") or ""
    time.sleep(0.05 if key.endswith("0") else 0.005)
    send({
        "jsonrpc": "2.0",
        "id": msg["id"],
        "result": {
            "structuredContent": {
                "ok": True,
                "data": {
                    "submittedCount": 1,
                    "upsertedCount": 1,
                    "retiredCount": 0,
                    "retiredItemIds": ["id-" + key],
                    "failedItems": [],
                },
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
    """One process, one pipe, many caller threads must not lose replies."""

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
            kind=Kind.ENVIRONMENT,
            natural_key=f"key-{index}",
            display_name=f"Item {index}",
            attributes={"environmentId": f"key-{index}"},
        )

    def test_every_caller_gets_its_own_reply(self, client):
        from concurrent.futures import ThreadPoolExecutor

        count = 24
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [
                pool.submit(client.sync_inventory, [self._item(i)])
                for i in range(count)
            ]
            results = [f.result(timeout=60) for f in futures]

        assert len(results) == count
        assert [r.retired_item_ids for r in results] == [
            [f"id-key-{i}"] for i in range(count)
        ]

    def test_ids_stay_unique_under_concurrent_callers(self, client):
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [
                pool.submit(client.sync_inventory, [self._item(i)])
                for i in range(40)
            ]
            retired = [f.result(timeout=60).retired_item_ids[0] for f in futures]

        assert len(set(retired)) == 40
