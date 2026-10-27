# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the scoped connected knowledge-base search CLI."""

from __future__ import annotations

import json
from typing import Any

import pytest

from connected_kb_context import ConnectedKBContext
import search_connected_kb

SYS_ID = "0123456789abcdef0123456789abcdef"


class _FakeGraph:
    instances: list["_FakeGraph"] = []
    listed: Any = []
    targeted: Any = None
    search_response: Any = {"value": [{"hitsContainers": [{"hits": []}]}]}
    authenticate_error: Exception | None = None
    authenticate_output = ""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.search_calls: list[tuple[str, str, int]] = []
        _FakeGraph.instances.append(self)

    def authenticate(self, extra_scopes: list[str] | None = None) -> str:
        if self.authenticate_output:
            print(self.authenticate_output)
        if self.authenticate_error is not None:
            raise self.authenticate_error
        return "secret-token"

    def get_external_connections(self) -> Any:
        return self.listed

    def get_external_connection(self, _reference: str) -> Any:
        return self.targeted

    def search_external_items(
        self, connection_id: str, query: str, *, size: int
    ) -> Any:
        self.search_calls.append((connection_id, query, size))
        return self.search_response


@pytest.fixture(autouse=True)
def _patch_dependencies(monkeypatch: pytest.MonkeyPatch):
    _FakeGraph.instances = []
    _FakeGraph.listed = [
        {
            "id": "canonical-id",
            "name": "ServiceNow knowledge",
            "description": "Employee articles",
            "rawSecret": "do-not-emit",
        }
    ]
    _FakeGraph.targeted = None
    _FakeGraph.search_response = {"value": [{"hitsContainers": [{"hits": []}]}]}
    _FakeGraph.authenticate_error = None
    _FakeGraph.authenticate_output = ""
    monkeypatch.setattr(search_connected_kb, "GraphClient", _FakeGraph)
    monkeypatch.setattr(
        search_connected_kb,
        "load_connected_kb_context",
        lambda: ConnectedKBContext(
            bot_id="bot-id",
            tenant_id="tenant-id",
            dataverse_endpoint="https://contoso.crm.dynamics.com",
        ),
    )
    yield
    _FakeGraph.instances = []


def _search_payload(*, mapped: bool = True) -> dict[str, Any]:
    properties = {
        "title": "Parental leave",
        "url": (
            "https://example.service-now.com/kb"
            f"?id=kb_article&sys_id={SYS_ID}"
        ),
        "body": "full article body must not leak",
        "credential": "must not leak",
    }
    if mapped:
        properties["sys_id"] = SYS_ID
    else:
        properties["url"] = "https://example.invalid/article"
    return {
        "value": [
            {
                "hitsContainers": [
                    {
                        "total": 999,
                        "hits": [
                            {
                                "hitId": "opaque-sensitive-id",
                                "rank": 1,
                                "summary": "Leave policy summary",
                                "resource": {
                                    "id": "raw-item-id",
                                    "properties": properties,
                                },
                            }
                        ],
                    }
                ]
            }
        ],
        "rawToken": "must not leak",
    }


def test_success_emits_exact_bounded_shape_and_uses_canonical_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _FakeGraph.search_response = _search_payload()

    exit_code = search_connected_kb.main(
        ["--connection", "ServiceNow knowledge", "--query", "parental leave",
         "--limit", "20"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "status": "ok",
        "connection": {
            "reference": "ServiceNow knowledge",
            "id": "canonical-id",
            "name": "ServiceNow knowledge",
            "classification": "ambiguous",
            "classificationEvidence": ["name mentions ServiceNow"],
        },
        "query": "parental leave",
        "total": 1,
        "hits": [
            {
                "rank": 1,
                "title": "Parental leave",
                "summary": "Leave policy summary",
                "sourceUrl": (
                    "https://example.service-now.com/kb"
                    f"?id=kb_article&sys_id={SYS_ID}"
                ),
                "identifier": {"kind": "sys_id", "value": SYS_ID},
                "skipReason": None,
            }
        ],
    }
    assert _FakeGraph.instances[0].tenant_id == "tenant-id"
    assert _FakeGraph.instances[0].search_calls == [
        ("canonical-id", "parental leave", 20)
    ]
    serialized = json.dumps(payload)
    for forbidden in (
        "secret-token",
        "rawSecret",
        "rawToken",
        "opaque-sensitive-id",
        "raw-item-id",
        "full article body",
        "credential",
        "properties",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "argv",
    [
        ["--query", "leave"],
        ["--connection", "   ", "--query", "leave"],
        ["--connection", "kb", "--query", "   "],
        ["--connection", "kb", "--query", "leave", "--limit", "0"],
        ["--connection", "kb", "--query", "leave", "--limit", "101"],
        ["--connection", "kb", "--query", "leave", "--limit", "not-an-int"],
    ],
)
def test_invalid_arguments_emit_one_json_error(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = search_connected_kb.main(argv)

    assert exit_code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "error"
    assert payload["hits"] == []
    assert payload["error"]
    assert captured.err == ""


def test_graph_authentication_failure_is_json_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _FakeGraph.authenticate_error = RuntimeError("auth boom")

    exit_code = search_connected_kb.main(
        ["--connection", "kb", "--query", "leave"]
    )

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "hits": [],
        "error": "Microsoft Graph authentication failed: auth boom",
    }


def test_authentication_chatter_does_not_break_single_json_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _FakeGraph.authenticate_output = "Opening browser for sign-in..."

    exit_code = search_connected_kb.main(
        ["--connection", "canonical-id", "--query", "leave"]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out)["status"] == "ok"


def test_connection_resolution_error_is_json_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _FakeGraph.listed = [
        {"id": "one", "name": "duplicate"},
        {"id": "two", "name": "DUPLICATE"},
    ]

    exit_code = search_connected_kb.main(
        ["--connection", "duplicate", "--query", "leave"]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["hits"] == []
    assert "ambiguous by name" in payload["error"]


def test_graph_permission_sentinel_is_json_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _FakeGraph.search_response = {
        "_error": "insufficient_permissions",
        "_status": 403,
    }

    exit_code = search_connected_kb.main(
        ["--connection", "canonical-id", "--query", "leave"]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["hits"] == []
    assert "permission" in payload["error"].lower()


def test_zero_results_returns_ok(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = search_connected_kb.main(
        ["--connection", "canonical-id", "--query", "leave", "--limit", "1"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["total"] == 0
    assert payload["hits"] == []


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        [],
        {},
        {"value": None},
        {"value": [None]},
        {"value": [{"hitsContainers": None}]},
        {"value": [{"hitsContainers": [{"hits": "not-a-list"}]}]},
    ],
)
def test_malformed_search_response_is_json_error(
    malformed: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    _FakeGraph.search_response = malformed

    exit_code = search_connected_kb.main(
        ["--connection", "canonical-id", "--query", "leave"]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "error"
    assert payload["hits"] == []
    assert "invalid" in payload["error"].lower()


def test_unmapped_hit_is_emitted_with_stable_skip_reason(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _FakeGraph.search_response = _search_payload(mapped=False)

    exit_code = search_connected_kb.main(
        ["--connection", "canonical-id", "--query", "leave"]
    )

    assert exit_code == 0
    hit = json.loads(capsys.readouterr().out)["hits"][0]
    assert hit["identifier"] is None
    assert hit["skipReason"] == "No verified ServiceNow identifier found."
