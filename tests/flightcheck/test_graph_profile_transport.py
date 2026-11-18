# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only Graph batching and cancellable deadlines, including DNS shutdown."""

import asyncio
import json
import socket
import threading
from time import monotonic

import httpx
import pytest
import requests
import respx

from flightcheck.graph_client import GraphClient, GraphPermissionError
from flightcheck import graph_transport
from tests.conftest import require_validated_mock
from tests.mocks import graph, graph_profile as profiles


@pytest.fixture
def client():
    require_validated_mock(profiles)
    client = GraphClient(graph.MOCK_TENANT_ID)
    client._token = "test-token"
    return client


def _read(client, count=2, budget=30):
    return client.get_bounded_profiles(
        [profiles.directory_user(i + 1)["id"] for i in range(count)],
        time_budget=budget,
    )


@respx.mock
def test_batch_responses_are_correlated_by_id_not_response_order(client):
    def respond(request):
        rows = json.loads(request.content)["requests"]
        return httpx.Response(200, json={"responses": [
            {"id": row["id"], "status": 200, "body": {"id": row["id"], "names": []}}
            for row in reversed(rows)
        ]})
    respx.post(f"{profiles.GRAPH_BASE}/$batch").mock(side_effect=respond)
    assert [row["id"] for row in _read(client)] == ["0", "1"]


@pytest.mark.parametrize("variant", [
    "missing", "duplicate", "unknown", "bad_status", "bad_body", "bad_headers", "empty_headers_array",
])
@respx.mock
def test_invalid_batch_cannot_produce_partial_coverage(client, variant):
    rows = [{"id": str(i), "status": 200, "body": profiles.profile()} for i in range(2)]
    if variant == "missing":
        rows.pop()
    elif variant == "duplicate":
        rows[1]["id"] = "0"
    elif variant == "unknown":
        rows[1]["id"] = "unexpected"
    elif variant == "bad_status":
        rows[1]["status"] = "200"
    elif variant == "bad_body":
        rows[1]["body"] = []
    elif variant == "bad_headers":
        rows[1]["headers"] = {"Retry-After": 4}
    else:
        rows[1]["headers"] = []
    respx.post(f"{profiles.GRAPH_BASE}/$batch").respond(json={"responses": rows})
    with pytest.raises(ValueError, match="invalid|incomplete"):
        _read(client)


@pytest.mark.parametrize("status", [400, 401, 403, 404])
@respx.mock
def test_batch_success_does_not_hide_failed_subrequests(client, status):
    respx.post(f"{profiles.GRAPH_BASE}/$batch").respond(json={"responses": [
        {"id": "0", "status": 200, "body": profiles.profile()},
        {"id": "1", "status": status, "body": {"error": {"code": "Test"}}},
    ]})
    with pytest.raises(GraphPermissionError if status == 403 else requests.HTTPError):
        _read(client)


@respx.mock
def test_only_throttled_subrequests_are_retried_with_retry_after(client, monkeypatch):
    delays = []
    sleep = asyncio.sleep
    async def record(delay):
        delays.append(delay)
        await sleep(0)
    monkeypatch.setattr(graph_transport.asyncio, "sleep", record)
    route = respx.post(f"{profiles.GRAPH_BASE}/$batch").mock(side_effect=[
        httpx.Response(200, json={"responses": [
            {"id": "0", "status": 200, "body": profiles.profile()},
            {"id": "1", "status": 429, "headers": {"Retry-After": "7"}},
        ]}),
        httpx.Response(200, json={"responses": [{"id": "1", "status": 503}]}),
        httpx.Response(200, json={"responses": [{"id": "1", "status": 200, "body": profiles.profile()}]}),
    ])
    assert len(_read(client)) == 2
    assert delays == [7, 2]
    assert [
        [row["id"] for row in json.loads(call.request.content)["requests"]]
        for call in route.calls
    ] == [["0", "1"], ["1"], ["1"]]


@respx.mock
def test_subrequest_retry_exhaustion_is_error_without_successful_subset(client, monkeypatch):
    sleep = asyncio.sleep
    async def no_wait(_delay):
        await sleep(0)
    monkeypatch.setattr(graph_transport.asyncio, "sleep", no_wait)
    route = respx.post(f"{profiles.GRAPH_BASE}/$batch").respond(json={"responses": [
        {"id": "0", "status": 503},
    ]})
    with pytest.raises(requests.HTTPError) as failed:
        _read(client, count=1)
    assert failed.value.response.status_code == 503 and route.call_count == 4


@respx.mock
def test_outer_transport_retry_and_inner_retry_preserve_all_profiles(client, monkeypatch):
    sleep = asyncio.sleep
    async def no_wait(_delay):
        await sleep(0)
    monkeypatch.setattr(graph_transport.asyncio, "sleep", no_wait)
    route = respx.post(f"{profiles.GRAPH_BASE}/$batch").mock(side_effect=[
        httpx.ConnectError("Temporary network failure"),
        httpx.Response(200, json={"responses": [
            {"id": "0", "status": 200, "body": {"id": "first", "names": []}},
            {"id": "1", "status": 429, "headers": {"Retry-After": "1"}},
        ]}),
        httpx.ReadTimeout("Temporary network failure"),
        httpx.Response(200, json={"responses": [
            {"id": "1", "status": 200, "body": {"id": "second", "names": []}},
        ]}),
    ])
    assert [row["id"] for row in _read(client)] == ["first", "second"]
    assert [
        [row["id"] for row in json.loads(call.request.content)["requests"]]
        for call in route.calls
    ] == [["0", "1"], ["0", "1"], ["1"], ["1"]]


@pytest.mark.parametrize("failure", ["slow", "subrequest_backoff", "batch_backoff", "network"])
@respx.mock
def test_deadline_covers_all_batch_and_subrequest_waits(client, failure):
    async def respond(request):
        if failure == "subrequest_backoff":
            return httpx.Response(200, json={"responses": [
                {"id": "0", "status": 429, "headers": {"Retry-After": "60"}},
            ]})
        if failure == "batch_backoff":
            return httpx.Response(429, headers={"Retry-After": "60"})
        if failure == "network":
            raise httpx.ConnectError("Temporary failure")
        await asyncio.sleep(10)
        return profiles.batch_response(request)
    respx.post(f"{profiles.GRAPH_BASE}/$batch").mock(side_effect=respond)
    started = monotonic()
    with pytest.raises(TimeoutError, match="budget expired; no partial coverage"):
        _read(client, count=1, budget=0.5)
    assert monotonic() - started < 2


@pytest.mark.parametrize("scope", ["tenant", "me", "batch"])
def test_slow_dns_does_not_delay_shutdown_and_worker_is_reaped(client, monkeypatch, scope):
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    processes = []
    create_process = asyncio.create_subprocess_exec
    async def record_process(*args, **kwargs):
        process = await create_process(*args, **kwargs)
        processes.append(process)
        return process
    def slow_dns(*_args, **_kwargs):
        threading.Event().wait(3)
        raise socket.gaierror(socket.EAI_AGAIN, "Simulated slow DNS")
    monkeypatch.setattr(graph_transport, "_DNS_LOOKUP", "import time; time.sleep(10)\n" + graph_transport._DNS_LOOKUP)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", record_process)
    monkeypatch.setattr(socket, "getaddrinfo", slow_dns)
    started = monotonic()
    with pytest.raises(TimeoutError, match="budget expired; no partial coverage"):
        if scope == "tenant":
            client.get_bounded_collection("/users", params={}, limit=100, time_budget=0.5)
        elif scope == "me":
            client.get_bounded_profile(params={}, time_budget=0.5)
        else:
            _read(client, budget=0.5)
    assert monotonic() - started < 2
    assert processes and all(process.returncode is not None for process in processes)


@pytest.mark.parametrize("host,family", [("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6)])
def test_dns_preserves_address_families(host, family):
    with asyncio.Runner(loop_factory=graph_transport._bounded_event_loop) as runner:
        addresses = runner.run(asyncio.wait_for(
            graph_transport._bounded_getaddrinfo(host, 443, family=family, type=socket.SOCK_STREAM, flags=socket.AI_NUMERICHOST),
            timeout=5,
        ))
    assert addresses and all(row[0] == family and row[4][0] == host and row[4][1] == 443 for row in addresses)
