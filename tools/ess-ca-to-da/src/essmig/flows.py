"""Carry customer-authored cloud flows the migrated topics invoke.

A migrated topic can *call* a cloud flow — a ``- kind: InvokeFlowAction`` with a
``flowId`` — and the Declarative Agent declares each flow it uses in a top-level
``flows:`` block (the flow's *interface*: its id, its input and output
parameters). But the DA package (``agent.yml`` + ``app.config.dev.json`` +
``package.json``) has nowhere to put the flow's *definition*. A cloud flow is a
Power Platform environment component, provisioned by a **solution import**, not a
part the agent package can hold. That is why the shipped ESS template only
*references* its ``ESS Workday Runtime`` flows — a separate ESS solution installs
them in the environment.

So a customer-authored flow that a carried topic invokes cannot travel inside the
one agent package. It must travel as a **second artifact**: a small unmanaged
solution zip that *creates* the flow in the target environment, imported
**before** the agent package so the agent's ``InvokeFlowAction`` references
resolve. Import them in the other order and the flow registrar rejects the agent
package with *"a referenced flow could not be registered because it was deleted or
you do not have access"* — the flow simply is not there yet.

This module:

* reads which flows the merged agent actually references
  (:func:`referenced_flow_ids`) and which the template already provides
  (:func:`declared_flow_ids`);
* synthesises the agent.yml ``flows:`` interface entry for each carried flow from
  the flow's own trigger and response schemas (:func:`add_interfaces`); and
* re-emits the customer's flows as an importable unmanaged solution
  (:func:`build_solution_zip`) — near-verbatim from their export, so the flow
  definitions and their connection references carry across exactly.

The flow definitions only exist in an *exported* package, so carrying flows is a
capability of the ``--from-package`` source. The live-Dataverse path cannot read a
flow's definition, so it can only *report* a referenced flow it cannot carry
(:func:`plan` with ``export=None``).
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# JSON-schema scalar types -> the Declarative Agent flow parameter types. Anything
# not scalar (object/array) is surfaced to the agent as a String, which is how
# Copilot Studio itself degrades a complex flow parameter.
_TYPE_MAP = {
    "string": "String",
    "integer": "Number",
    "number": "Number",
    "boolean": "Boolean",
}
_DEFAULT_TYPE = "String"

_GUID_BODY = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_MISSING_DEPENDENCIES = re.compile(
    r"<MissingDependencies\b[^>]*>.*?</MissingDependencies>", re.DOTALL
)
_MISSING_DEPENDENCIES_EMPTY = re.compile(r"<MissingDependencies\b[^>/]*/>")

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/octet-stream" />'
    '<Default Extension="json" ContentType="application/octet-stream" />'
    "</Types>"
)


def canonical_id(value: Any) -> str:
    """A workflow id as the platform stores it in ``flowId``: lowercase, no braces."""
    return str(value).strip().strip("{}").lower()


@dataclass(frozen=True)
class CarriedFlow:
    """One customer-authored cloud flow, read from an exported solution."""

    workflow_id: str
    """Canonical (lowercase, unbraced) — matches a topic's ``flowId``."""
    name: str
    description: str
    json_name: str
    """Base name of the flow-definition part inside ``Workflows/``."""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    connectors: tuple[str, ...] = ()
    """Connector ids the flow binds (e.g. ``shared_office365users``) — for the report."""


@dataclass(frozen=True)
class FlowExport:
    """The flows read from an exported CA solution plus the raw parts to re-emit them."""

    flows: tuple[CarriedFlow, ...]
    solution_xml: str
    customizations_xml: str
    workflow_files: dict[str, bytes]
    """``Workflows/<name>`` part name -> its verbatim bytes."""

    def by_id(self) -> dict[str, CarriedFlow]:
        return {flow.workflow_id: flow for flow in self.flows}


@dataclass(frozen=True)
class FlowFindings:
    """What one agent's migration needs to say — and do — about flows."""

    carried: tuple[CarriedFlow, ...] = ()
    """Referenced flows whose definition is in hand and travels in the flows zip."""
    dangling: tuple[str, ...] = ()
    """Referenced flow ids with no definition to carry — the import will fail without them."""
    template_provided: tuple[str, ...] = ()
    """Referenced ids the DA template itself provides (nothing to do)."""

    @property
    def needs_flow_import(self) -> bool:
        return bool(self.carried)

    @property
    def has_dangling(self) -> bool:
        return bool(self.dangling)

    def connectors(self) -> list[str]:
        seen: dict[str, None] = {}
        for flow in self.carried:
            for connector in flow.connectors:
                seen.setdefault(connector, None)
        return list(seen)


# --- reading references out of the merged agent -----------------------------


def referenced_flow_ids(agent: Any) -> set[str]:
    """Every flow id a topic in ``agent`` invokes (``InvokeFlowAction.flowId``)."""
    found: set[str] = set()
    for node in _walk(agent):
        if isinstance(node, dict) and node.get("kind") == "InvokeFlowAction":
            flow_id = node.get("flowId")
            if isinstance(flow_id, str) and flow_id.strip():
                found.add(canonical_id(flow_id))
    return found


def declared_flow_ids(agent: Any) -> set[str]:
    """Flow ids already declared in the agent's top-level ``flows:`` block."""
    declared: set[str] = set()
    flows = agent.get("flows") if isinstance(agent, dict) else None
    if isinstance(flows, list):
        for entry in flows:
            if isinstance(entry, dict) and entry.get("workflowId"):
                declared.add(canonical_id(entry["workflowId"]))
    return declared


def _walk(node: Any) -> Iterator[Any]:
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


# --- planning ---------------------------------------------------------------


def plan(agent: Any, export: FlowExport | None) -> FlowFindings:
    """Decide, for one merged agent, which referenced flows carry and which dangle.

    ``export`` is the flows read from the customer's package, or ``None`` for the
    live-Dataverse source (which cannot read a flow definition). A referenced flow
    is *template-provided* if the DA already declares it, *carried* if its
    definition is in the export, and *dangling* otherwise — the last being a hard
    import blocker the operator must resolve by hand.
    """
    referenced = referenced_flow_ids(agent)
    template = declared_flow_ids(agent) & referenced
    available = export.by_id() if export is not None else {}
    carried = tuple(
        available[flow_id]
        for flow_id in sorted(available)
        if flow_id in referenced and flow_id not in template
    )
    carried_ids = {flow.workflow_id for flow in carried}
    dangling = tuple(sorted(referenced - template - carried_ids))
    return FlowFindings(
        carried=carried,
        dangling=dangling,
        template_provided=tuple(sorted(template)),
    )


# --- agent.yml interface synthesis ------------------------------------------


def add_interfaces(agent: Any, flows: Iterable[CarriedFlow]) -> list[CarriedFlow]:
    """Add a ``flows:`` interface entry for each carried flow not already declared.

    The interface tells the Declarative Agent the flow's id and the shape of its
    inputs and outputs, mirroring the entries the ESS template ships for its own
    flows. Mutates ``agent`` in place; returns the flows for which an entry was
    added (a flow already declared by the template is left untouched).
    """
    if not isinstance(agent, dict):
        return []
    declared = declared_flow_ids(agent)
    added: list[CarriedFlow] = []
    entries = agent.get("flows")
    if not isinstance(entries, list):
        entries = []
        agent["flows"] = entries
    for flow in flows:
        if flow.workflow_id in declared:
            continue
        entries.append(interface_entry(flow))
        declared.add(flow.workflow_id)
        added.append(flow)
    return added


def register_config_flows(config: Any, flows: Iterable[CarriedFlow]) -> list[str]:
    """Register each carried flow id in ``app.config.dev.json``'s ``flows`` map.

    The DA config file carries a ``flows`` block mapping each flow id to itself
    (``"<id>": "<id>"``) — the environment binding the platform reads alongside the
    agent's ``flows:`` interface. The ESS template lists its own runtime flows here;
    a carried customer flow must be listed too, or the agent import cannot resolve
    the flow at publish time. Mutates ``config`` in place; returns the ids added.
    """
    if not isinstance(config, dict):
        return []
    entries = config.get("flows")
    if not isinstance(entries, dict):
        entries = {}
        config["flows"] = entries
    added: list[str] = []
    for flow in flows:
        if flow.workflow_id not in entries:
            entries[flow.workflow_id] = flow.workflow_id
            added.append(flow.workflow_id)
    return added


def interface_entry(flow: CarriedFlow) -> dict[str, Any]:
    """The agent.yml ``flows:`` entry for one carried flow, from its own schemas."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    entry: dict[str, Any] = {
        "version": 1,
        "auditInfo": {"createdTimeUtc": stamp, "modifiedTimeUtc": stamp},
        "displayName": flow.name,
        "isEnabled": True,
        "workflowId": flow.workflow_id,
        "inputType": {"properties": _parameters(flow.input_schema, inputs=True)},
    }
    outputs = _parameters(flow.output_schema, inputs=False)
    if outputs:
        entry["outputType"] = {"properties": outputs}
    # Grounded in the only real-world DA flow entries ESS ships: agent-called flows
    # use a Copilot trigger and the EmbeddedOnly connection type, and mark their
    # inputs and outputs secure.
    entry["triggerType"] = "Copilot"
    entry["connectionType"] = "EmbeddedOnly"
    entry["secureInputs"] = True
    entry["secureOutputs"] = True
    return entry


def _parameters(schema: dict[str, Any], *, inputs: bool) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return {}
    required = schema.get("required") if isinstance(schema, dict) else None
    required_set = set(required) if isinstance(required, list) else set()
    result: dict[str, Any] = {}
    for key, spec in properties.items():
        spec = spec if isinstance(spec, dict) else {}
        parameter: dict[str, Any] = {"displayName": str(spec.get("title") or key)}
        description = spec.get("description")
        if inputs and isinstance(description, str) and description:
            parameter["description"] = description
        if inputs:
            parameter["isRequired"] = key in required_set
        parameter["type"] = _TYPE_MAP.get(str(spec.get("type")), _DEFAULT_TYPE)
        result[key] = parameter
    return result


# --- the flows solution zip -------------------------------------------------


def build_solution_zip(export: FlowExport) -> bytes:
    """The customer's flows as an importable unmanaged solution zip.

    Re-emits the export's own ``solution.xml`` and ``customizations.xml`` — so the
    flow definitions, their localized names and their connection references carry
    across exactly — with only the ``<MissingDependencies>`` stripped. Those
    dependencies name the managed CA botcomponents the customer edited; they are
    absent from a Declarative Agent target and would block the flow import, and the
    flows themselves do not need them.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("solution.xml", _strip_missing_dependencies(export.solution_xml))
        archive.writestr("customizations.xml", export.customizations_xml)
        for name, data in export.workflow_files.items():
            archive.writestr(f"Workflows/{name}", data)
    return buffer.getvalue()


def _strip_missing_dependencies(solution_xml: str) -> str:
    without = _MISSING_DEPENDENCIES.sub("<MissingDependencies></MissingDependencies>", solution_xml)
    return _MISSING_DEPENDENCIES_EMPTY.sub("<MissingDependencies></MissingDependencies>", without)


__all__ = [
    "CarriedFlow",
    "FlowExport",
    "FlowFindings",
    "add_interfaces",
    "build_solution_zip",
    "canonical_id",
    "declared_flow_ids",
    "interface_entry",
    "plan",
    "referenced_flow_ids",
    "register_config_flows",
]
