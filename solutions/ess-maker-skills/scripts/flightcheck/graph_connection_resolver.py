# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Resolve a Graph external connection reference to its canonical record."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

GraphConnectionMatch = Literal["id", "name", "targeted_get"]
GraphConnectionResolutionReason = Literal[
    "empty_reference",
    "ambiguous",
    "not_found",
    "insufficient_permissions",
    "invalid_list",
    "invalid_connection",
]


@dataclass(frozen=True)
class ResolvedGraphConnection:
    reference: str
    connection: dict[str, Any]
    matched_by: GraphConnectionMatch

    @property
    def connection_id(self) -> str:
        return str(self.connection["id"])


class GraphConnectionResolutionError(ValueError):
    """A deterministic failure to resolve a Graph connection reference."""

    def __init__(
        self,
        reason: GraphConnectionResolutionReason,
        reference: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.reference = reference


def resolve_graph_connection(graph: Any, reference: str) -> ResolvedGraphConnection:
    """Resolve ``reference`` by ID, name, then a targeted Graph GET."""
    if not isinstance(reference, str) or not reference.strip():
        raise GraphConnectionResolutionError(
            "empty_reference",
            "",
            "Graph connection reference must be a non-empty string.",
        )

    normalized_reference = reference.strip()
    folded_reference = normalized_reference.casefold()
    connections = graph.get_external_connections()
    if not isinstance(connections, list):
        raise GraphConnectionResolutionError(
            "invalid_list",
            normalized_reference,
            "Microsoft Graph returned an invalid external connection list.",
        )

    valid_connections = [
        connection
        for connection in connections
        if isinstance(connection, dict)
        and isinstance(connection.get("id"), str)
        and bool(connection["id"].strip())
    ]

    id_matches = [
        connection
        for connection in valid_connections
        if connection["id"].casefold() == folded_reference
    ]
    if id_matches:
        return _resolved_list_match(normalized_reference, id_matches, "id")

    name_matches = [
        connection
        for connection in valid_connections
        if isinstance(connection.get("name"), str)
        and connection["name"].casefold() == folded_reference
    ]
    if name_matches:
        return _resolved_list_match(normalized_reference, name_matches, "name")

    connection = graph.get_external_connection(normalized_reference)
    if isinstance(connection, dict):
        status = connection.get("_status")
        error = connection.get("_error")
        if status == 404 or error == "not_found":
            raise GraphConnectionResolutionError(
                "not_found",
                normalized_reference,
                f"Graph external connection '{normalized_reference}' was not found.",
            )
        if status in (401, 403) or error == "insufficient_permissions":
            raise GraphConnectionResolutionError(
                "insufficient_permissions",
                normalized_reference,
                "Insufficient permission to read Graph external connection "
                f"'{normalized_reference}'.",
            )

    if (
        not isinstance(connection, dict)
        or not isinstance(connection.get("id"), str)
        or not connection["id"].strip()
    ):
        raise GraphConnectionResolutionError(
            "invalid_connection",
            normalized_reference,
            "Microsoft Graph returned an invalid external connection result "
            f"for '{normalized_reference}'.",
        )

    return ResolvedGraphConnection(
        reference=normalized_reference,
        connection=connection,
        matched_by="targeted_get",
    )


def _resolved_list_match(
    reference: str,
    matches: list[dict[str, Any]],
    matched_by: Literal["id", "name"],
) -> ResolvedGraphConnection:
    if len(matches) > 1:
        raise GraphConnectionResolutionError(
            "ambiguous",
            reference,
            f"Graph connection reference '{reference}' is ambiguous by {matched_by}.",
        )
    return ResolvedGraphConnection(
        reference=reference,
        connection=matches[0],
        matched_by=matched_by,
    )
