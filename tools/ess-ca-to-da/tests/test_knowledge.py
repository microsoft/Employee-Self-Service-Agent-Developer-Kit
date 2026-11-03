"""Wiring a carried Graph-connector knowledge source onto the DA.

A ServiceNow knowledge source is a ``KnowledgeSourceComponent`` whose
``GraphConnectorSearchSource`` resolves its connection through an environment
variable. These tests assert the two things the migration must reproduce so the
source actually works after import: the ``envvar:`` connection binding in the
config, and repointing a migrated topic's references from the old CA schema name
to the DA ``knowledge.<Name>`` name.
"""

from __future__ import annotations

from essmig import knowledge

DA_PREFIX = "gptagent_copilotforemployeeselfservicehr"


def _knowledge_agent() -> dict:
    return {
        "components": [
            {"kind": "DialogComponent", "schemaName": f"{DA_PREFIX}.topic.Other"},
            {
                "kind": "KnowledgeSourceComponent",
                "displayName": "ServiceNow-DEV",
                "schemaName": f"{DA_PREFIX}.knowledge.ServiceNowDEV",
                "configuration": {
                    "source": {
                        "kind": "GraphConnectorSearchSource",
                        "connectionId": {"schemaName": f"{DA_PREFIX}.envVar.rSdk_abc"},
                        "connectionName": "ServiceNowKB1",
                    }
                },
            },
        ]
    }


def test_graph_connections_reads_the_knowledge_source_connection() -> None:
    connections = knowledge.graph_connections(_knowledge_agent())

    assert len(connections) == 1
    connection = connections[0]
    assert connection.knowledge_schema == f"{DA_PREFIX}.knowledge.ServiceNowDEV"
    assert connection.display_name == "ServiceNow-DEV"
    assert connection.envvar_schema == f"{DA_PREFIX}.envVar.rSdk_abc"
    assert connection.connection_name == "ServiceNowKB1"


def test_graph_connections_ignores_non_graph_sources() -> None:
    agent = {
        "components": [
            {
                "kind": "KnowledgeSourceComponent",
                "schemaName": f"{DA_PREFIX}.knowledge.Site",
                "configuration": {"source": {"kind": "SharePointSearchSource"}},
            }
        ]
    }

    assert knowledge.graph_connections(agent) == []


def test_bind_connections_writes_the_envvar_value_into_config_values() -> None:
    agent = _knowledge_agent()
    config: dict = {"values": {"botName": "ESS CR Agent"}}
    connections = knowledge.graph_connections(agent)

    bound = knowledge.bind_connections(
        config, connections, {"envVar.rSdk_abc": "ServiceNowKB2605142004"}
    )

    key = f"envvar:{DA_PREFIX}.envVar.rSdk_abc"
    assert config["values"][key] == "ServiceNowKB2605142004"
    assert len(bound) == 1
    assert bound[0].value == "ServiceNowKB2605142004"
    assert bound[0].connection_name == "ServiceNowKB1"


def test_bind_connections_skips_a_variable_with_no_carried_value() -> None:
    config: dict = {"values": {}}
    connections = knowledge.graph_connections(_knowledge_agent())

    bound = knowledge.bind_connections(config, connections, {})

    assert bound == []
    assert config["values"] == {}


def test_bind_connections_creates_a_values_block_when_missing() -> None:
    config: dict = {}
    connections = knowledge.graph_connections(_knowledge_agent())

    knowledge.bind_connections(config, connections, {"envVar.rSdk_abc": "KB1"})

    assert config["values"][f"envvar:{DA_PREFIX}.envVar.rSdk_abc"] == "KB1"


def test_rewrite_references_repoints_the_old_schema_name() -> None:
    old = f"{DA_PREFIX}.topic.ServiceNowDEV_5DgXr1iseyWeuzzaV5ep_"
    new = f"{DA_PREFIX}.knowledge.ServiceNowDEV"
    agent = {
        "components": [
            {
                "kind": "DialogComponent",
                "actions": [
                    {
                        "kind": "SearchKnowledgeSources",
                        "knowledgeSources": {
                            "kind": "SearchSpecificKnowledgeSources",
                            "knowledgeSources": [old],
                        },
                    }
                ],
            }
        ]
    }

    rewritten = knowledge.rewrite_references(agent, {old: new})

    assert rewritten == 1
    source = agent["components"][0]["actions"][0]["knowledgeSources"]["knowledgeSources"]
    assert source == [new]


def test_rewrite_references_is_a_noop_without_renames() -> None:
    agent = {"components": [{"knowledgeSources": ["unchanged"]}]}

    assert knowledge.rewrite_references(agent, {}) == 0
    assert agent["components"][0]["knowledgeSources"] == ["unchanged"]
