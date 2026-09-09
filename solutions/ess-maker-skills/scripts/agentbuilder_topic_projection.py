# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Project fetched AgentBuilder dialog objects into Copilot Studio YAML."""

from __future__ import annotations

from typing import Any

import yaml


KIND = "$kind"
DERIVED_FIELDS = {
    "diagnostics",
    "structuredCondition",
    "structuredRecordExpression",
}
SCALAR_EXPRESSION_KINDS = {
    "AdaptiveCardExpression",
    "ArrayExpressionOnly_T",
    "BoolExpression",
    "DialogExpression",
    "IntExpression",
    "StringExpression",
    "ValueExpression",
}
KINDLESS_OBJECT_KINDS = {
    "ActionInputBinding",
    "ActionOutputBinding",
    "ConditionItem",
    "ConnectionProperties",
    "ContentShareContext",
    "Intent",
    "InterruptionPolicy",
    "PropertyInfo",
    "Record",
}
NAMED_SCALAR_KINDS = {
    "Boolean",
    "String",
    "StringPrebuiltEntity",
}


class ProjectionError(ValueError):
    """Raised when a fetched dialog cannot be projected without data loss."""


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _represent_string)


def _expression_to_yaml(node: dict[str, Any]) -> Any:
    if "variableReference" in node:
        return f"={node['variableReference']}"
    if "expressionText" in node:
        return f"={node['expressionText']}"
    if "literalValue" in node:
        value = node["literalValue"]
        if isinstance(value, str) and value.startswith("="):
            raise ProjectionError(
                "Literal strings beginning with '=' cannot be projected safely."
            )
        return wire_to_yaml(value)
    raise ProjectionError(
        f"{node.get(KIND)} has no supported expression value."
    )


def _template_line_to_yaml(node: dict[str, Any]) -> str:
    rendered: list[str] = []
    for segment in node.get("segments", []):
        kind = segment.get(KIND)
        if kind == "TextSegment":
            text = segment.get("value", "")
            if "{" in text or "}" in text:
                raise ProjectionError(
                    "Literal message braces require a confirmed platform escape."
                )
            rendered.append(text)
        elif kind == "ExpressionSegment":
            expression = _expression_to_yaml(segment["expression"])
            if not isinstance(expression, str) or not expression.startswith("="):
                raise ProjectionError(
                    "Message expression segment is not an expression."
                )
            rendered.append("{" + expression[1:] + "}")
        else:
            raise ProjectionError(
                f"Unsupported message segment kind: {kind!r}."
            )
    return "".join(rendered)


def _message_to_yaml(node: dict[str, Any]) -> Any:
    result: dict[str, Any] = {}
    if "text" in node:
        lines = [_template_line_to_yaml(line) for line in node["text"]]
        if set(node) <= {KIND, "text"} and len(lines) == 1:
            return lines[0]
        result["text"] = lines
    if "speak" in node:
        result["speak"] = [
            _template_line_to_yaml(line) for line in node["speak"]
        ]
    if "attachments" in node:
        result["attachments"] = wire_to_yaml(node["attachments"])
    unknown = set(node) - {
        KIND,
        "text",
        "speak",
        "attachments",
        "diagnostics",
    }
    if unknown:
        raise ProjectionError(
            f"Unsupported Message fields: {sorted(unknown)}."
        )
    return result


def wire_to_yaml(value: Any) -> Any:
    """Project a fetched AgentBuilder wire value into authored YAML data."""
    if isinstance(value, list):
        return [wire_to_yaml(item) for item in value]
    if not isinstance(value, dict):
        return value

    kind = value.get(KIND)
    if kind in SCALAR_EXPRESSION_KINDS:
        return _expression_to_yaml(value)
    if kind == "Message":
        return _message_to_yaml(value)
    if kind == "TemplateLine":
        return _template_line_to_yaml(value)
    if kind == "AdaptiveCardTemplate":
        return {
            "kind": kind,
            "cardContent": wire_to_yaml(value["cardContent"]),
        }
    if kind in NAMED_SCALAR_KINDS:
        return kind
    if kind == "StructuredRecordExpression":
        return {
            key: wire_to_yaml(item)
            for key, item in value.get("properties", {}).items()
        }
    if kind == "OptionDataValue":
        return value.get("value")
    if kind == "SystemOptionSet":
        return value.get("name")

    result: dict[str, Any] = {}
    if kind and kind not in KINDLESS_OBJECT_KINDS:
        result["kind"] = kind
    for key, item in value.items():
        if key == KIND or key in DERIVED_FIELDS:
            continue
        result[key] = wire_to_yaml(item)
    return result


def project_dialog(dialog: dict[str, Any]) -> str:
    """Return authored YAML for one fetched AdaptiveDialog."""
    if dialog.get(KIND) != "AdaptiveDialog":
        raise ProjectionError("Dialog component is not an AdaptiveDialog.")
    return yaml.dump(
        wire_to_yaml(dialog),
        Dumper=_Dumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    )
