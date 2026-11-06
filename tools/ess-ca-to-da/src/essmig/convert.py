"""Classify and convert ``AnswerQuestionWithAI`` nodes to supported building blocks.

The Custom Engine Agent ``AnswerQuestionWithAI`` node (Copilot Studio's "create
generative answers") has no Declarative Agent equivalent, so :mod:`essmig.rules`
would otherwise disable any topic that uses it. But in the ESS agents the node is
almost never a knowledge-grounded Q&A — it is one of two mechanical patterns:

* **Response composition** — the topic calls a flow/API, ``ParseValue`` parses the
  result into a record, and the node phrases that record for the user. The GA
  templates do exactly this with a deterministic ``SendActivity`` over the parsed
  record (``InvokeFlow → ParseValue → SendActivity``), using **no** generative node.
  So we rewrite the node into a ``SetVariable`` that renders the record's scalar
  fields into the same output variable the following ``SendActivity`` already reads.
* **Intent classification** — the node turns the user's text into a label that a
  ``ConditionGroup`` branches on. Routing a label still needs a model (or an
  orchestrator-level rewrite), so these are classified but left for a human.

Anything that genuinely reads a knowledge source, or answers from the model's
general knowledge, is classified and left alone with accurate guidance.

:func:`convert_dialog` mutates the dialog in place and returns one
:class:`NodeConversion` per ``AnswerQuestionWithAI`` node it saw, so the report can
say what it upgraded and what still needs a human.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

_NODE_KIND = "AnswerQuestionWithAI"

# Power Fx / Copilot value types that render to a single string with ``Text()``.
_SCALAR_TYPES = frozenset(
    {"String", "Number", "Boolean", "DateTime", "Date", "Decimal"}
)

_TOPIC_VAR = re.compile(r"Topic\.[A-Za-z0-9_]+")


class ConversionClass(StrEnum):
    """How an ``AnswerQuestionWithAI`` node is being used."""

    RESPONSE_COMPOSITION = "response composition"
    INTENT_CLASSIFICATION = "intent classification"
    KNOWLEDGE_GROUNDED = "knowledge grounded"
    GENERAL_KNOWLEDGE = "general knowledge"
    UNKNOWN = "unknown"


@dataclass
class NodeConversion:
    """The outcome of inspecting one ``AnswerQuestionWithAI`` node."""

    node_name: str
    cls: ConversionClass
    converted: bool
    note: str


def convert_dialog(dialog: Any) -> list[NodeConversion]:
    """Rewrite convertible ``AnswerQuestionWithAI`` nodes in ``dialog`` in place.

    Returns one :class:`NodeConversion` per node encountered. A node is converted
    only when it is response composition over a record whose referenced fields are
    all scalar — the one shape a deterministic ``SendActivity`` can reproduce
    exactly. Every other node is left untouched for the caller to flag.
    """
    if not isinstance(dialog, dict):
        return []

    records = _record_definitions(dialog)
    consumers = _ConsumerIndex(dialog)
    conversions: list[NodeConversion] = []

    def visit(items: list[Any]) -> None:
        for index, item in enumerate(items):
            if _is_node(item):
                conversion = _convert_node(item, records, consumers)
                conversions.append(conversion)
                if conversion.converted:
                    items[index] = _render_node(item, records)

    _walk_lists(dialog, visit)
    return conversions


def _convert_node(
    node: dict[str, Any],
    records: dict[str, dict[str, Any]],
    consumers: _ConsumerIndex,
) -> NodeConversion:
    name = _node_name(node)
    output = _variable_name(node.get("variable"))
    referenced = _referenced_records(node, records)
    cls = _classify(node, output, referenced, consumers)

    if cls is not ConversionClass.RESPONSE_COMPOSITION:
        return NodeConversion(name, cls, False, _why_not(cls))

    record_var = _first_all_scalar(referenced, records)
    if record_var is None:
        return NodeConversion(
            name,
            cls,
            False,
            "renders tabular or nested data a deterministic template cannot "
            "reproduce — rebuild the rendering by hand",
        )
    note = f"deterministic rendering of {record_var}"
    return NodeConversion(name, cls, True, note)


def _classify(
    node: dict[str, Any],
    output: str | None,
    referenced: list[str],
    consumers: _ConsumerIndex,
) -> ConversionClass:
    if _reads_knowledge(node):
        return ConversionClass.KNOWLEDGE_GROUNDED
    if output is not None and consumers.is_classified(output):
        return ConversionClass.INTENT_CLASSIFICATION
    # Anything that phrases a record the topic already parsed is response
    # composition — whether it hands the text to a downstream activity, auto-sends
    # it, or the record turns out to be tabular (only scalar records convert).
    composes = (
        bool(referenced)
        or (output is not None and consumers.in_activity(output))
        or node.get("autoSend") is True
    )
    if composes and referenced:
        return ConversionClass.RESPONSE_COMPOSITION
    if composes:
        return ConversionClass.UNKNOWN
    return ConversionClass.GENERAL_KNOWLEDGE


def _render_node(node: dict[str, Any], records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    output = _variable_name(node.get("variable"))
    record_var = _first_all_scalar(_referenced_records(node, records), records)
    assert output is not None and record_var is not None  # guarded by caller
    properties = records[record_var]
    value = _render_expression(record_var, properties)
    rendered: dict[str, Any] = {"kind": "SetVariable", "variable": output, "value": value}
    node_id = node.get("id")
    if node_id is not None:
        rendered["id"] = node_id
    name = node.get("displayName")
    if isinstance(name, str) and name:
        rendered["displayName"] = f"{name} (auto-upgraded to deterministic rendering)"
    return rendered


def _render_expression(record_var: str, properties: dict[str, Any]) -> str:
    parts = [
        f'"{_humanize(prop)}: " & Text({record_var}.{prop})'
        for prop in properties
        if _is_scalar(properties[prop])
    ]
    return "=" + ' & Char(10) & '.join(parts)


def _reads_knowledge(node: dict[str, Any]) -> bool:
    """True when the node actually searches files or a knowledge source."""
    sources = node.get("knowledgeSources")
    if isinstance(sources, dict):
        kind = sources.get("kind")
        if kind == "SearchAllKnowledgeSources":
            return True
        if kind == "SearchSpecificKnowledgeSources":
            for value in sources.values():
                if isinstance(value, list) and value:
                    return True
    files = node.get("fileSearchDataSource")
    if isinstance(files, dict):
        mode = files.get("searchFilesMode")
        if isinstance(mode, dict) and mode.get("kind") not in (None, "DoNotSearchFiles"):
            return True
    return False


def _referenced_records(
    node: dict[str, Any], records: dict[str, dict[str, Any]]
) -> list[str]:
    text = " ".join(
        str(node.get(key, "")) for key in ("userInput", "additionalInstructions")
    )
    output = _variable_name(node.get("variable"))
    seen: list[str] = []
    for match in _TOPIC_VAR.findall(text):
        if match in records and match != output and match not in seen:
            seen.append(match)
    return seen


def _first_all_scalar(
    referenced: list[str], records: dict[str, dict[str, Any]]
) -> str | None:
    for var in referenced:
        properties = records[var]
        if properties and all(_is_scalar(value) for value in properties.values()):
            return var
    return None


def _record_definitions(dialog: Any) -> dict[str, dict[str, Any]]:
    """Map every ``ParseValue`` record variable to its property definitions."""
    records: dict[str, dict[str, Any]] = {}

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("kind") == "ParseValue":
                var = _variable_name(node.get("variable"))
                value_type = node.get("valueType")
                if (
                    var is not None
                    and isinstance(value_type, dict)
                    and value_type.get("kind") == "Record"
                    and isinstance(value_type.get("properties"), dict)
                ):
                    records[var] = dict(value_type["properties"])
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    collect(dialog)
    return records


class _ConsumerIndex:
    """Where each variable is read: activity text, branch conditions, derived set."""

    def __init__(self, dialog: Any) -> None:
        self._activity: list[str] = []
        self._condition: list[str] = []
        self._classifier_values: list[str] = []
        self._collect(dialog)

    def _collect(self, node: Any) -> None:
        if isinstance(node, dict):
            kind = node.get("kind")
            if kind == "SendActivity":
                self._activity.append(_flatten(node.get("activity")))
            elif kind == "ConditionGroup":
                for condition in node.get("conditions", []) or []:
                    if isinstance(condition, dict):
                        self._condition.append(str(condition.get("condition", "")))
            elif kind == "SetVariable":
                value = str(node.get("value", ""))
                if re.search(r"\b(If|Switch)\s*\(", value):
                    self._classifier_values.append(value)
            for value in node.values():
                self._collect(value)
        elif isinstance(node, list):
            for item in node:
                self._collect(item)

    def in_activity(self, var: str) -> bool:
        return any(_mentions(text, var) for text in self._activity)

    def is_classified(self, var: str) -> bool:
        """The variable drives a branch — read by a condition or a label-mapping set."""
        if any(_mentions(text, var) for text in self._condition):
            return True
        return any(_mentions(text, var) for text in self._classifier_values)


def _walk_lists(node: Any, visit: Any) -> None:
    if isinstance(node, dict):
        for value in node.values():
            _walk_lists(value, visit)
    elif isinstance(node, list):
        for item in node:
            _walk_lists(item, visit)
        visit(node)


def _is_node(item: Any) -> bool:
    return isinstance(item, dict) and item.get("kind") == _NODE_KIND


def _is_scalar(value: Any) -> bool:
    return isinstance(value, str) and value in _SCALAR_TYPES


def _variable_name(value: Any) -> str | None:
    return value if isinstance(value, str) and value.startswith("Topic.") else None


def _node_name(node: dict[str, Any]) -> str:
    name = node.get("displayName")
    if isinstance(name, str) and name:
        return name
    node_id = node.get("id")
    return str(node_id) if node_id is not None else _NODE_KIND


def _mentions(text: str, var: str) -> bool:
    return re.search(re.escape(var) + r"(?![A-Za-z0-9_])", text) is not None


def _flatten(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    return ""


def _humanize(name: str) -> str:
    spaced = name.replace("_", " ")
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
    spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
    return spaced.strip()


def _why_not(cls: ConversionClass) -> str:
    if cls is ConversionClass.INTENT_CLASSIFICATION:
        return (
            "classifies the user's request into a label a branch routes on — let the "
            "agent's native intent routing pick the right tool, or rebuild as its own topic"
        )
    if cls is ConversionClass.KNOWLEDGE_GROUNDED:
        return (
            "answers from a knowledge source — connect the knowledge source to the agent "
            "and let it answer from your content"
        )
    if cls is ConversionClass.GENERAL_KNOWLEDGE:
        return (
            "answers from the model's general knowledge — fold this into the agent's "
            "instructions"
        )
    return "could not be classified — review and rebuild on supported building blocks"
