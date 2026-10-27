# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure-logic tests for Graph external connection canonicalization."""

from __future__ import annotations

from typing import Any

import pytest

from flightcheck.graph_connection_resolver import (
    GraphConnectionResolutionError,
    resolve_graph_connection,
)


class _FakeGraph:
    def __init__(self, listed: Any, targeted: Any = None) -> None:
        self.listed = listed
        self.targeted = targeted
        self.targeted_references: list[str] = []

    def get_external_connections(self) -> Any:
        return self.listed

    def get_external_connection(self, reference: str) -> Any:
        self.targeted_references.append(reference)
        return self.targeted


@pytest.mark.parametrize("reference", ["connector-id", "CoNnEcToR-Id"])
def test_resolves_exact_case_insensitive_id_match(reference: str) -> None:
    connection = {"id": "Connector-ID", "name": "HR knowledge", "state": "ready"}
    graph = _FakeGraph([connection])

    resolved = resolve_graph_connection(graph, reference)

    assert resolved.reference == reference
    assert resolved.connection is connection
    assert resolved.connection_id == "Connector-ID"
    assert resolved.matched_by == "id"
    assert graph.targeted_references == []


@pytest.mark.parametrize("reference", ["hr knowledge", "HR KnOwLeDgE"])
def test_resolves_exact_case_insensitive_name_match(reference: str) -> None:
    connection = {"id": "connector-id", "name": "HR Knowledge", "state": "ready"}

    resolved = resolve_graph_connection(_FakeGraph([connection]), reference)

    assert resolved.connection is connection
    assert resolved.connection_id == "connector-id"
    assert resolved.matched_by == "name"


def test_rejects_duplicate_case_insensitive_name_matches() -> None:
    graph = _FakeGraph(
        [
            {"id": "first", "name": "HR Knowledge"},
            {"id": "second", "name": "hr knowledge"},
        ]
    )

    with pytest.raises(GraphConnectionResolutionError, match="ambiguous"):
        resolve_graph_connection(graph, "HR KNOWLEDGE")


def test_falls_back_to_targeted_get_and_preserves_canonical_connection() -> None:
    connection = {"id": "Canonical-ID", "name": "Canonical name", "state": "ready"}
    graph = _FakeGraph([], connection)

    resolved = resolve_graph_connection(graph, "requested-id")

    assert resolved.connection is connection
    assert resolved.connection_id == "Canonical-ID"
    assert resolved.matched_by == "targeted_get"
    assert graph.targeted_references == ["requested-id"]


@pytest.mark.parametrize(
    ("sentinel", "message"),
    [
        ({"_error": "not_found", "_status": 404}, "not found"),
        (
            {"_error": "insufficient_permissions", "_status": 403},
            "permission",
        ),
    ],
)
def test_rejects_targeted_get_sentinels(
    sentinel: dict[str, Any], message: str
) -> None:
    with pytest.raises(GraphConnectionResolutionError, match=message):
        resolve_graph_connection(_FakeGraph([], sentinel), "missing")


def test_ignores_malformed_list_rows_before_targeted_get() -> None:
    connection = {"id": "canonical-id", "name": "Canonical"}
    graph = _FakeGraph(
        [None, "not-a-row", {}, {"id": None}, {"name": "Missing id"}],
        connection,
    )

    resolved = resolve_graph_connection(graph, "canonical-id")

    assert resolved.connection is connection
    assert resolved.matched_by == "targeted_get"


@pytest.mark.parametrize("invalid_list", [None, {}, "not-a-list", 42])
def test_rejects_invalid_list_shape(invalid_list: Any) -> None:
    graph = _FakeGraph(invalid_list, {"id": "unused"})

    with pytest.raises(GraphConnectionResolutionError, match="list"):
        resolve_graph_connection(graph, "connector-id")

    assert graph.targeted_references == []


@pytest.mark.parametrize(
    "invalid_targeted",
    [None, [], "not-a-connection", {}, {"name": "Missing id"}],
)
def test_rejects_invalid_targeted_result_shape(invalid_targeted: Any) -> None:
    with pytest.raises(GraphConnectionResolutionError, match="invalid"):
        resolve_graph_connection(_FakeGraph([], invalid_targeted), "connector-id")


@pytest.mark.parametrize("reference", [None, "", "   ", "\t\n"])
def test_rejects_empty_reference(reference: Any) -> None:
    graph = _FakeGraph([])

    with pytest.raises(GraphConnectionResolutionError, match="non-empty"):
        resolve_graph_connection(graph, reference)

    assert graph.targeted_references == []
