"""Wire a customer's ServiceNow (or other Graph-connector) knowledge sources.

A Declarative Agent exposes a ServiceNow knowledge base as a
``KnowledgeSourceComponent`` whose ``configuration.source`` is a
``GraphConnectorSearchSource``. The source names its connection *indirectly*, by an
environment variable: ``connectionId.schemaName`` points at an ``envVar.*``
component, and the agent's ``app.config.dev.json`` binds that variable in its
``values`` block under an ``envvar:<schema>`` key whose value is the Graph
connector's connection id. A real DA export shows exactly this shape::

    values:
      envvar:gptagent_....envVar.LJq_...: ServiceNowKB2607302258

The migration already carries the customer's knowledge-source component onto the
DA (:func:`essmig.projection._as_new_knowledge_source`), but two things the
platform would normally wire have to be reproduced by hand, or the source silently
disappears after import:

* the **connection binding** — the ``envvar:`` entry in the config. Without it the
  source's Graph-connector connection cannot resolve, so the import drops the
  source. Its value is environment-specific (it names a Graph connector in the
  *source* tenant), so it is carried as a starting point and flagged for rebind.
* the **rename fix** — a net-new knowledge source is renamed to the DA-valid
  ``knowledge.<Name>`` schema, but a migrated topic that searches it still
  references the *old* CA schema name in its ``SearchSpecificKnowledgeSources``
  action. Those references must be repointed at the new name or the topic dangles.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from essmig.ess import schema_suffix

_CONFIG_ENVVAR_PREFIX = "envvar:"
_GRAPH_SOURCE_KIND = "GraphConnectorSearchSource"


@dataclass(frozen=True)
class GraphConnection:
    """A carried knowledge source backed by a Graph-connector connection."""

    knowledge_schema: str
    """The DA schema name of the knowledge source, e.g. ``...knowledge.ServiceNowDEV``."""
    display_name: str
    envvar_schema: str
    """The environment variable the source's connection resolves through."""
    connection_name: str
    """The Graph connector's connection name, e.g. ``ServiceNowKB1`` — for the report."""
    value: str | None = None
    """The carried env-var value, once bound into the config (else ``None``)."""


def graph_connections(agent: Any) -> list[GraphConnection]:
    """Every Graph-connector knowledge source declared in the merged agent."""
    components = agent.get("components") if isinstance(agent, dict) else None
    if not isinstance(components, list):
        return []
    found: list[GraphConnection] = []
    for entry in components:
        connection = _graph_connection(entry)
        if connection is not None:
            found.append(connection)
    return found


def _graph_connection(entry: Any) -> GraphConnection | None:
    if not isinstance(entry, dict) or entry.get("kind") != "KnowledgeSourceComponent":
        return None
    configuration = entry.get("configuration")
    source = configuration.get("source") if isinstance(configuration, dict) else None
    if not isinstance(source, dict) or source.get("kind") != _GRAPH_SOURCE_KIND:
        return None
    connection_id = source.get("connectionId")
    envvar = connection_id.get("schemaName") if isinstance(connection_id, dict) else None
    if not isinstance(envvar, str) or not envvar.strip():
        return None
    return GraphConnection(
        knowledge_schema=str(entry.get("schemaName") or ""),
        display_name=str(entry.get("displayName") or ""),
        envvar_schema=envvar.strip(),
        connection_name=str(source.get("connectionName") or ""),
    )


def bind_connections(
    config: Any, connections: list[GraphConnection], env_values: dict[str, str]
) -> list[GraphConnection]:
    """Write the ``envvar:`` config binding for each Graph-connector knowledge source.

    ``env_values`` maps an environment-variable schema *suffix* (``envVar.<id>``,
    agent-prefix independent) to the value the customer's export carried. For each
    knowledge source whose connection variable has a carried value, set
    ``values["envvar:<schema>"]`` so the source's connection resolves on import.
    Returns the connections that were bound (with their carried value) for the
    report's rebind list. Mutates ``config`` in place.
    """
    if not isinstance(config, dict):
        return []
    values = config.get("values")
    if not isinstance(values, dict):
        values = {}
        config["values"] = values
    bound: list[GraphConnection] = []
    for connection in connections:
        value = env_values.get(schema_suffix(connection.envvar_schema))
        if value is None:
            continue
        values[f"{_CONFIG_ENVVAR_PREFIX}{connection.envvar_schema}"] = value
        bound.append(replace(connection, value=value))
    return bound


def rewrite_references(agent: Any, renames: dict[str, str]) -> int:
    """Repoint every reference to a renamed knowledge source at its new schema name.

    A net-new knowledge source is renamed to ``knowledge.<Name>`` for the DA, but a
    migrated topic that searched it still carries the old CA schema name in its
    ``SearchSpecificKnowledgeSources`` list. Those references are exact schema-name
    strings, so repoint each one at the new name. Returns the number of references
    rewritten. Mutates ``agent`` in place.
    """
    if not renames:
        return 0
    return _rewrite(agent, renames)


def _rewrite(node: Any, renames: dict[str, str]) -> int:
    rewritten = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and value in renames:
                node[key] = renames[value]
                rewritten += 1
            else:
                rewritten += _rewrite(value, renames)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            if isinstance(item, str) and item in renames:
                node[index] = renames[item]
                rewritten += 1
            else:
                rewritten += _rewrite(item, renames)
    return rewritten


__all__ = [
    "GraphConnection",
    "bind_connections",
    "graph_connections",
    "rewrite_references",
]
