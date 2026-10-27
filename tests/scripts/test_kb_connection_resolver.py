# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for ``kb_connection_resolver.py``.

Uses a fake ``PVAClient``-shaped object (no network access). The
KnowledgeSourceComponent fixture shape mirrors
``tests/flightcheck/checks/test_graph_connector_kb.py``'s
``_gc_knowledge_source`` / ``_sharepoint_knowledge_source`` builders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flightcheck.kb_connection_resolver import resolve_bound_connections

FAKE_BOT_ID = "00000000-0000-0000-0000-000000003333"


@dataclass
class _FakePVA:
    """Duck-typed stand-in for ``PVAClient``."""

    knowledge_sources: list[dict[str, Any]] = field(default_factory=list)
    is_configured: bool = True
    error: Exception | None = None

    def get_knowledge_sources(self, bot_id: str) -> list[dict[str, Any]]:
        if self.error is not None:
            raise self.error
        return list(self.knowledge_sources)


def _gc_knowledge_source(
    *,
    connection_name: str = "ServiceNowKB48",
    display_name: str = "Mock GC KB",
    state: str = "mc",
    status: str = "Active",
) -> dict[str, Any]:
    """Build a KnowledgeSourceComponent that uses a Graph Connector source."""
    return {
        "$kind": "KnowledgeSourceComponent",
        "displayName": display_name,
        "id": "00000000-0000-0000-0000-000000007777",
        "state": state,
        "status": status,
        "configuration": {
            "$kind": "KnowledgeSourceConfiguration",
            "source": {
                "$kind": "GraphConnectorSearchSource",
                "connectionId": {
                    "$kind": "EnvironmentVariableReference",
                    "schemaName": "msdyn_copilotforemployeeselfservicehr.envVar.SPhVehW_7-UYoSpSne-v3",
                },
                "connectionName": connection_name,
                "contentSourceDisplayName": display_name,
                "publisherName": "Microsoft",
            },
        },
    }


def _sharepoint_knowledge_source(*, display_name: str = "Mock SP KB") -> dict[str, Any]:
    """Build a KnowledgeSourceComponent that uses the OOTB SharePoint source."""
    return {
        "$kind": "KnowledgeSourceComponent",
        "displayName": display_name,
        "id": "00000000-0000-0000-0000-000000008888",
        "state": "mc",
        "status": "Active",
        "configuration": {
            "$kind": "KnowledgeSourceConfiguration",
            "source": {
                "$kind": "SharePointSearchSource",
                "siteUrl": "https://contoso.sharepoint.com/sites/hr",
            },
        },
    }


class TestNoneBound:
    def test_zero_knowledge_sources_returns_none_bound(self) -> None:
        pva = _FakePVA(knowledge_sources=[])
        result = resolve_bound_connections(pva, FAKE_BOT_ID)
        assert result.status == "none_bound"
        assert result.connections == []

    def test_only_non_graph_connector_sources_returns_none_bound(self) -> None:
        pva = _FakePVA(knowledge_sources=[_sharepoint_knowledge_source()])
        result = resolve_bound_connections(pva, FAKE_BOT_ID)
        assert result.status == "none_bound"
        assert result.connections == []


class TestOkSingle:
    def test_single_graph_connector_source_returns_ok(self) -> None:
        pva = _FakePVA(
            knowledge_sources=[
                _gc_knowledge_source(
                    connection_name="ServiceNowKB48", state="ready", status="Active"
                )
            ]
        )
        result = resolve_bound_connections(pva, FAKE_BOT_ID)
        assert result.status == "ok"
        assert len(result.connections) == 1
        conn = result.connections[0]
        assert conn.connection_name == "ServiceNowKB48"
        assert conn.state == "ready"
        assert conn.status == "Active"


class TestOkMultiple:
    def test_multiple_graph_connector_sources_preserve_order(self) -> None:
        pva = _FakePVA(
            knowledge_sources=[
                _gc_knowledge_source(connection_name="ConnA", state="ready", status="Active"),
                _gc_knowledge_source(connection_name="ConnB", state="mc", status="Warning"),
                _gc_knowledge_source(connection_name="ConnC", state="draft", status="Failed"),
            ]
        )
        result = resolve_bound_connections(pva, FAKE_BOT_ID)
        assert result.status == "ok"
        names = [c.connection_name for c in result.connections]
        assert names == ["ConnA", "ConnB", "ConnC"]
        assert result.connections[1].state == "mc"
        assert result.connections[1].status == "Warning"


class TestFiltersNonGraphConnector:
    def test_mixed_sources_filters_out_sharepoint(self) -> None:
        pva = _FakePVA(
            knowledge_sources=[
                _sharepoint_knowledge_source(display_name="Native SP"),
                _gc_knowledge_source(connection_name="OnlyThisOne"),
            ]
        )
        result = resolve_bound_connections(pva, FAKE_BOT_ID)
        assert result.status == "ok"
        assert len(result.connections) == 1
        assert result.connections[0].connection_name == "OnlyThisOne"


class TestConnectionNameFallback:
    def test_missing_connection_name_falls_back_to_connection_id_schema_name(self) -> None:
        src = _gc_knowledge_source(state="ready", status="Active")
        src["configuration"]["source"].pop("connectionName")
        pva = _FakePVA(knowledge_sources=[src])
        result = resolve_bound_connections(pva, FAKE_BOT_ID)
        assert result.status == "ok"
        assert len(result.connections) == 1
        # Falls back per real `_connector_reference()` semantics: the
        # env-var reference's own schemaName.
        assert result.connections[0].connection_name == (
            "msdyn_copilotforemployeeselfservicehr.envVar.SPhVehW_7-UYoSpSne-v3"
        )


class TestPvaNotConfigured:
    def test_pva_none_returns_error(self) -> None:
        result = resolve_bound_connections(None, FAKE_BOT_ID)
        assert result.status == "error"
        assert result.error
        assert result.connections == []

    def test_pva_not_configured_returns_error(self) -> None:
        pva = _FakePVA(is_configured=False)
        result = resolve_bound_connections(pva, FAKE_BOT_ID)
        assert result.status == "error"
        assert result.connections == []
        # Message should name what's missing (auth/config), per
        # PVAClient.authenticate()/is_configured failure modes.
        assert "configur" in result.error.lower() or "authenticat" in result.error.lower()


class TestGetKnowledgeSourcesRaises:
    def test_exception_is_caught_and_surfaced(self) -> None:
        pva = _FakePVA(error=RuntimeError("botcomponents lookup failed: 503"))
        result = resolve_bound_connections(pva, FAKE_BOT_ID)
        assert result.status == "error"
        assert result.connections == []
        assert "botcomponents lookup failed: 503" in result.error
