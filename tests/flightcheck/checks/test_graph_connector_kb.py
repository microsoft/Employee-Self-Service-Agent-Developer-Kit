# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the Graph Connector knowledge source
FlightCheck check (EXT-002 + per-source EXT-002-{N}).

The check (``solutions/ess-maker-skills/scripts/flightcheck/checks/
graph_connector_kb.py``) is conditional: it gates on the agent having
at least one knowledge source whose ``configuration.source.$kind`` is
``GraphConnectorSearchSource``. These tests build a minimal fake PVA
(Island Gateway) client that returns canned KnowledgeSourceComponent
records for the gating step, plus a real Microsoft Graph client driven
through ``responses`` for the validation step.

We rely on the validatable ``tests/mocks/graph.py`` builders (Microsoft
Graph CSDL-derived). PVA is NOT mocked through that registry — the gate
simply needs an object that returns a list of dicts the check can scan
for the ``$kind`` marker, so a hand-built stand-in here is sufficient
and keeps the test focused.

Same pattern as ``test_workday_env_vars.py`` and
``test_workday_connections.py``; consult those files for the broader
template.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import graph as g

require_validated_mock(g)


FAKE_BOT_ID = "00000000-0000-0000-0000-000000003333"
FAKE_TENANT_ID = "00000000-0000-0000-0000-000000001111"


# ───────────────────────────────────────────────────────────────────────
# Fakes
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _FakePVA:
    """Stand-in for the Island Gateway client. Returns a canned list of
    KnowledgeSourceComponent dicts when ``get_knowledge_sources`` is called.

    The check never imports the real PVA class — it just calls
    ``runner.pva.get_knowledge_sources(bot_id)`` and checks
    ``runner.pva.is_configured``, so a duck-typed stand-in is enough.
    """

    knowledge_sources: list[dict[str, Any]] = field(default_factory=list)
    is_configured: bool = True

    def get_knowledge_sources(self, bot_id: str) -> list[dict[str, Any]]:
        return list(self.knowledge_sources)


@dataclass
class _MinimalRunner:
    pva: Any
    graph: Any
    config: dict[str, Any]


def _graph_client(fake_token: str):
    """Build a real GraphClient with a pre-populated token."""
    from flightcheck.graph_client import GraphClient

    client = GraphClient(tenant_id=FAKE_TENANT_ID)
    client._token = fake_token
    return client


def _gc_knowledge_source(
    *,
    connection_name: str = g.MOCK_EXTERNAL_CONNECTION_ID,
    display_name: str = "Mock GC KB",
    state: str = "mc",
    status: str = "Active",
) -> dict[str, Any]:
    """Build a KnowledgeSourceComponent that uses a Graph Connector source.

    Mirrors the shape returned by the Island Gateway for a Graph
    Connector knowledge source — see the captured cassette
    ``tests/fixtures/cassettes/island_gateway_botcomponents.yaml``
    line 372-374 (component with ``$kind: KnowledgeSourceComponent``,
    ``configuration.source.$kind: GraphConnectorSearchSource``).
    """
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


def _build_runner(*, knowledge_sources: list[dict[str, Any]], graph) -> _MinimalRunner:
    return _MinimalRunner(
        pva=_FakePVA(knowledge_sources=knowledge_sources),
        graph=graph,
        config={"agent": {"botId": FAKE_BOT_ID}},
    )


def _result_by_id(results: list, checkpoint_id: str):
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) == 1, (
        f"Expected exactly one result for {checkpoint_id}, got {len(matches)}: "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


# ───────────────────────────────────────────────────────────────────────
# Gating — when no Graph Connector KB is attached, the check is silent.
# This is the most important property: the check must NEVER false-
# positive the OOTB native-SharePoint deployment path.
# ───────────────────────────────────────────────────────────────────────


class TestGating:
    def test_no_knowledge_sources_returns_empty(self, fake_token: str) -> None:
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        runner = _build_runner(knowledge_sources=[], graph=_graph_client(fake_token))
        assert run_graph_connector_kb_checks(runner) == []

    def test_only_sharepoint_sources_returns_empty(self, fake_token: str) -> None:
        """OOTB ESS path uses SharePointSearchSource — EXT-002 must not fire."""
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        runner = _build_runner(
            knowledge_sources=[
                _sharepoint_knowledge_source(display_name="HR Site"),
                _sharepoint_knowledge_source(display_name="IT Site"),
            ],
            graph=_graph_client(fake_token),
        )
        assert run_graph_connector_kb_checks(runner) == []

    def test_no_pva_returns_empty(self, fake_token: str) -> None:
        """Without an Island Gateway client we cannot determine whether a
        Graph Connector is in play — silently skip rather than emit a
        misleading SKIPPED on every full run."""
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        runner = _MinimalRunner(
            pva=None,
            graph=_graph_client(fake_token),
            config={"agent": {"botId": FAKE_BOT_ID}},
        )
        assert run_graph_connector_kb_checks(runner) == []

    def test_pva_not_configured_returns_empty(self, fake_token: str) -> None:
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        runner = _MinimalRunner(
            pva=_FakePVA(knowledge_sources=[], is_configured=False),
            graph=_graph_client(fake_token),
            config={"agent": {"botId": FAKE_BOT_ID}},
        )
        assert run_graph_connector_kb_checks(runner) == []


# ───────────────────────────────────────────────────────────────────────
# GOOD state — connector present, ready, last crawl completed.
# ───────────────────────────────────────────────────────────────────────


class TestGoodConfig:
    @responses.activate
    def test_single_ready_connector_with_completed_crawl_passes(
        self, fake_token: str
    ) -> None:
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[g.external_connection(state="ready")],
        ))
        responses.add(**g.list_connection_operations(
            operations=[g.connection_operation(status="completed")],
        ))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source(display_name="ServiceNow KB")],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        ext_002 = _result_by_id(results, "EXT-002")
        assert ext_002.status == "Passed"
        assert "1 Graph Connector knowledge source(s)" in ext_002.result

        per_source = _result_by_id(results, "EXT-002-001")
        assert per_source.status == "Passed"
        assert "ready" in per_source.result.lower()
        assert "completed" in per_source.result.lower()

        # The manual ACL row is always present and always NotConfigured —
        # we cannot enumerate item ACLs via the public Graph API.
        acl = _result_by_id(results, "EXT-002-ACL")
        assert acl.status == "NotConfigured"
        assert "deny" in acl.remediation.lower()

    @responses.activate
    def test_multiple_connectors_all_pass(self, fake_token: str) -> None:
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[
                g.external_connection(connection_id="ConnectorA", state="ready"),
                g.external_connection(connection_id="ConnectorB", state="ready"),
            ],
        ))
        responses.add(**g.list_connection_operations(
            connection_id="ConnectorA",
            operations=[g.connection_operation(status="completed")],
        ))
        responses.add(**g.list_connection_operations(
            connection_id="ConnectorB",
            operations=[g.connection_operation(status="completed")],
        ))

        runner = _build_runner(
            knowledge_sources=[
                _gc_knowledge_source(connection_name="ConnectorA", display_name="A"),
                _gc_knowledge_source(connection_name="ConnectorB", display_name="B"),
            ],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        assert _result_by_id(results, "EXT-002").status == "Passed"
        for cid in ("EXT-002-001", "EXT-002-002"):
            assert _result_by_id(results, cid).status == "Passed"


# ───────────────────────────────────────────────────────────────────────
# BAD state — fail when the connector is missing, non-ready, or its
# most recent crawl failed.
# ───────────────────────────────────────────────────────────────────────


class TestBadConfig:
    @responses.activate
    def test_referenced_connector_missing_returns_failed(
        self, fake_token: str
    ) -> None:
        """The agent references ``ServiceNowKB48`` but the tenant has no
        connector with that id or name. This is the most common deploy-
        time failure for Graph Connector KBs."""
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        # List call returns zero connectors.
        responses.add(**g.list_external_connections(connections=[]))
        # Targeted GET returns 404.
        responses.add(**g.get_external_connection_not_found(
            connection_id=g.MOCK_EXTERNAL_CONNECTION_ID,
        ))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source(display_name="ServiceNow KB")],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        ext_002 = _result_by_id(results, "EXT-002")
        assert ext_002.status == "Failed"
        assert "1 failed" in ext_002.result

        per_source = _result_by_id(results, "EXT-002-001")
        assert per_source.status == "Failed"
        assert g.MOCK_EXTERNAL_CONNECTION_ID in per_source.result
        assert "no microsoft graph external connection" in per_source.result.lower()
        assert "admin center" in per_source.remediation.lower()

    @responses.activate
    def test_connector_in_draft_state_returns_failed(self, fake_token: str) -> None:
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[g.external_connection(state="draft")],
        ))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source(display_name="Draft KB")],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        per_source = _result_by_id(results, "EXT-002-001")
        assert per_source.status == "Failed"
        assert "draft" in per_source.result.lower()
        assert "publish schema" in per_source.remediation.lower()

    @responses.activate
    def test_connector_in_obsolete_state_returns_failed(self, fake_token: str) -> None:
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[g.external_connection(state="obsolete")],
        ))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source()],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        per_source = _result_by_id(results, "EXT-002-001")
        assert per_source.status == "Failed"
        assert "obsolete" in per_source.result.lower()
        assert "recreate" in per_source.remediation.lower()

    @responses.activate
    def test_connector_limit_exceeded_returns_failed(self, fake_token: str) -> None:
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[g.external_connection(state="limitExceeded")],
        ))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source()],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        per_source = _result_by_id(results, "EXT-002-001")
        assert per_source.status == "Failed"
        assert "limit" in per_source.remediation.lower()

    @responses.activate
    def test_failed_crawl_returns_failed(self, fake_token: str) -> None:
        """Connector is ready but the most recent crawl operation failed
        — KB queries return stale/incomplete results."""
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[g.external_connection(state="ready")],
        ))
        responses.add(**g.list_connection_operations(
            operations=[
                g.connection_operation(operation_id="op-001", status="completed"),
                g.connection_operation(
                    operation_id="op-099",
                    status="failed",
                    error={"code": "CrawlFailed", "message": "Source unreachable"},
                ),
            ],
        ))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source()],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        per_source = _result_by_id(results, "EXT-002-001")
        assert per_source.status == "Failed"
        assert "failed" in per_source.result.lower()
        assert "re-crawl" in per_source.remediation.lower()


# ───────────────────────────────────────────────────────────────────────
# WARNING branches — in-progress crawl, no operations recorded.
# ───────────────────────────────────────────────────────────────────────


class TestWarningBranches:
    @responses.activate
    def test_inprogress_crawl_returns_warning(self, fake_token: str) -> None:
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[g.external_connection(state="ready")],
        ))
        responses.add(**g.list_connection_operations(
            operations=[g.connection_operation(status="inprogress")],
        ))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source()],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        per_source = _result_by_id(results, "EXT-002-001")
        assert per_source.status == "Warning"
        assert "in progress" in per_source.result.lower()
        assert "wait" in per_source.remediation.lower()

    @responses.activate
    def test_no_operations_returns_warning(self, fake_token: str) -> None:
        """Connector is ready but no crawl has ever run — items aren't
        searchable yet."""
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[g.external_connection(state="ready")],
        ))
        responses.add(**g.list_connection_operations(operations=[]))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source()],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        per_source = _result_by_id(results, "EXT-002-001")
        assert per_source.status == "Warning"
        assert "no completed crawl" in per_source.result.lower()
        assert "trigger an initial crawl" in per_source.remediation.lower()

    @responses.activate
    def test_unknown_state_returns_warning(self, fake_token: str) -> None:
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[g.external_connection(state="someFutureState")],
        ))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source()],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        per_source = _result_by_id(results, "EXT-002-001")
        assert per_source.status == "Warning"
        assert "unrecognized state" in per_source.result.lower()


# ───────────────────────────────────────────────────────────────────────
# Mixed state — at least one source is broken, summary reflects that.
# ───────────────────────────────────────────────────────────────────────


class TestMixedState:
    @responses.activate
    def test_one_ready_one_failed_summary_is_failed(self, fake_token: str) -> None:
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[
                g.external_connection(connection_id="GoodConn", state="ready"),
                g.external_connection(connection_id="BadConn", state="draft"),
            ],
        ))
        responses.add(**g.list_connection_operations(
            connection_id="GoodConn",
            operations=[g.connection_operation(status="completed")],
        ))

        runner = _build_runner(
            knowledge_sources=[
                _gc_knowledge_source(connection_name="GoodConn", display_name="Good"),
                _gc_knowledge_source(connection_name="BadConn", display_name="Bad"),
            ],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        ext_002 = _result_by_id(results, "EXT-002")
        assert ext_002.status == "Failed"
        assert "1 ready" in ext_002.result
        assert "1 failed" in ext_002.result

        assert _result_by_id(results, "EXT-002-001").status == "Passed"
        assert _result_by_id(results, "EXT-002-002").status == "Failed"


# ───────────────────────────────────────────────────────────────────────
# Connector resolution — the agent knowledge source's ``connectionName``
# might match the externalConnection ``id`` field OR ``name`` field; the
# check accepts either to be robust to both customer naming conventions.
# ───────────────────────────────────────────────────────────────────────


class TestConnectorResolution:
    @responses.activate
    def test_resolves_by_connection_name_field(self, fake_token: str) -> None:
        """The list call returns a connector whose ``name`` (display
        name) matches the agent's reference, even though its ``id`` is
        a GUID-like internal identifier."""
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(
            connections=[g.external_connection(
                connection_id="00000000-0000-0000-0000-000000099999",
                name="ServiceNowKB48",
                state="ready",
            )],
        ))
        responses.add(**g.list_connection_operations(
            connection_id="00000000-0000-0000-0000-000000099999",
            operations=[g.connection_operation(status="completed")],
        ))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source(connection_name="ServiceNowKB48")],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        assert _result_by_id(results, "EXT-002-001").status == "Passed"

    @responses.activate
    def test_falls_back_to_targeted_get(self, fake_token: str) -> None:
        """If the list call doesn't include the connector (paging,
        filtering), the check falls back to a direct GET by id."""
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(connections=[]))
        responses.add(**g.get_external_connection(
            connection_id=g.MOCK_EXTERNAL_CONNECTION_ID,
            record=g.external_connection(state="ready"),
        ))
        responses.add(**g.list_connection_operations(
            operations=[g.connection_operation(status="completed")],
        ))

        runner = _build_runner(
            knowledge_sources=[_gc_knowledge_source()],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        assert _result_by_id(results, "EXT-002-001").status == "Passed"

    @responses.activate
    def test_missing_connection_reference_returns_warning(
        self, fake_token: str
    ) -> None:
        """A KnowledgeSourceComponent with neither connectionName nor
        connectionId is malformed — surface as WARNING with a pointer
        at the agent's Knowledge editor."""
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        responses.add(**g.list_external_connections(connections=[]))

        broken_source = _gc_knowledge_source()
        broken_source["configuration"]["source"].pop("connectionName")
        broken_source["configuration"]["source"].pop("connectionId")

        runner = _build_runner(
            knowledge_sources=[broken_source],
            graph=_graph_client(fake_token),
        )
        results = run_graph_connector_kb_checks(runner)

        per_source = _result_by_id(results, "EXT-002-001")
        assert per_source.status == "Warning"
        assert "no connection identifier" in per_source.result.lower()


# ───────────────────────────────────────────────────────────────────────
# Graph-side failures — surface as WARNING with operator guidance, NOT
# as a silent skip.
# ───────────────────────────────────────────────────────────────────────


class TestGraphAvailability:
    def test_no_graph_client_with_gc_source_returns_warning(
        self, fake_token: str
    ) -> None:
        """Customer opted into the at-risk Graph Connector path but Graph
        auth is missing — must NOT be silent."""
        from flightcheck.checks.graph_connector_kb import run_graph_connector_kb_checks

        runner = _MinimalRunner(
            pva=_FakePVA(knowledge_sources=[_gc_knowledge_source()]),
            graph=None,
            config={"agent": {"botId": FAKE_BOT_ID}},
        )
        results = run_graph_connector_kb_checks(runner)

        ext_002 = _result_by_id(results, "EXT-002")
        assert ext_002.status == "Warning"
        assert "graph authentication is unavailable" in ext_002.result.lower()
        assert "ExternalConnection.Read.All" in ext_002.remediation
