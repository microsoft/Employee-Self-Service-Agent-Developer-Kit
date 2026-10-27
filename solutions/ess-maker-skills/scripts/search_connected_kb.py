# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Search one connected knowledge base through Microsoft Graph."""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
from typing import Any

from connected_kb_context import load_connected_kb_context
from flightcheck.connected_kb_search import (
    classify_graph_connection,
    normalize_external_item_hits,
)
from flightcheck.graph_client import SEARCH_SCOPES, GraphClient
from flightcheck.graph_connection_resolver import resolve_graph_connection


class _JSONArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _error_result(message: str) -> dict[str, Any]:
    return {"status": "error", "hits": [], "error": message}


def _parser() -> argparse.ArgumentParser:
    parser = _JSONArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--connection", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=20)
    return parser


def _validated_arguments(
    argv: list[str] | None,
) -> tuple[str, str, int]:
    args = _parser().parse_args(argv)
    connection = str(args.connection).strip()
    query = str(args.query).strip()
    if not connection:
        raise ValueError("--connection must be a non-empty string")
    if not query:
        raise ValueError("--query must be a non-empty string")
    if not 1 <= args.limit <= 100:
        raise ValueError("--limit must be an integer between 1 and 100")
    return connection, query, args.limit


def _serialize_hit(hit: Any) -> dict[str, Any]:
    identifier = hit.service_now_identifier
    return {
        "rank": hit.rank,
        "title": hit.title,
        "summary": hit.summary,
        "sourceUrl": hit.source_url,
        "identifier": (
            {"kind": identifier.kind, "value": identifier.value}
            if identifier is not None
            else None
        ),
        "skipReason": hit.skip_reason,
    }


def _is_valid_search_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    responses = payload.get("value")
    if not isinstance(responses, list):
        return False
    for response in responses:
        if not isinstance(response, dict):
            return False
        containers = response.get("hitsContainers")
        if not isinstance(containers, list):
            return False
        for container in containers:
            if (
                not isinstance(container, dict)
                or not isinstance(container.get("hits"), list)
            ):
                return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Run the scoped Graph connected-KB search CLI."""
    try:
        connection_reference, query, limit = _validated_arguments(argv)
    except (TypeError, ValueError) as exc:
        print(json.dumps(_error_result(str(exc))))
        return 1

    try:
        context = load_connected_kb_context()
    except Exception as exc:
        print(json.dumps(_error_result(str(exc))))
        return 1

    try:
        graph = GraphClient(context.tenant_id)
        with redirect_stdout(io.StringIO()):
            graph.authenticate(extra_scopes=SEARCH_SCOPES)
    except Exception as exc:
        print(json.dumps(_error_result(
            f"Microsoft Graph authentication failed: {exc}"
        )))
        return 1

    try:
        resolved = resolve_graph_connection(graph, connection_reference)
    except Exception as exc:
        print(json.dumps(_error_result(str(exc))))
        return 1

    classification = classify_graph_connection(resolved.connection)
    try:
        search_payload = graph.search_external_items(
            resolved.connection_id,
            query,
            size=limit,
        )
    except Exception as exc:
        print(json.dumps(_error_result(
            f"Microsoft Graph connected knowledge search failed: {exc}"
        )))
        return 1

    if (
        isinstance(search_payload, dict)
        and search_payload.get("_error") == "insufficient_permissions"
    ):
        print(json.dumps(_error_result(
            "Insufficient permission to search the Graph external connection."
        )))
        return 1
    if not _is_valid_search_payload(search_payload):
        print(json.dumps(_error_result(
            "Microsoft Graph returned an invalid connected knowledge search response."
        )))
        return 1

    hits = normalize_external_item_hits(search_payload)
    connection_name = resolved.connection.get("name")
    payload = {
        "status": "ok",
        "connection": {
            "reference": resolved.reference,
            "id": resolved.connection_id,
            "name": connection_name if isinstance(connection_name, str) else "",
            "classification": classification.kind,
            "classificationEvidence": list(classification.evidence),
        },
        "query": query,
        "total": len(hits),
        "hits": [_serialize_hit(hit) for hit in hits],
    }
    print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
