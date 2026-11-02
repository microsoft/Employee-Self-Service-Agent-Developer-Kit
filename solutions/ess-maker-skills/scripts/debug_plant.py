# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DBG SendActivity plant/strip — pure text transforms over a topic's
botcomponent ``data`` YAML.

Codifies the debug-oracle instrumentation pattern: insert a DBG ``SendActivity``
node after a named action to project internal topic state into the transcript,
then strip it so debug noise never ships. Both transforms are pure and
byte-reversible, so a live orchestration can guarantee an exact revert.

Design choices, each addressing a real fragility of manual debug-node insertion:

- Anchor by ACTION ID, not by field text — a field like
  ``ServiceNowData: Topic.ServiceNowData`` recurs across branches and is
  ambiguous, whereas an action ``id:`` is unique.
- Derive the planted node's indentation from the anchor action's ``- kind:``
  line, so the YAML list stays well-formed regardless of nesting depth.
- Plant inserts the node as the next SIBLING after the anchor action's whole
  block, with one leading blank line; strip removes exactly that, so
  ``strip(plant(x)) == x`` byte-for-byte. Ordering matters: the debug node must
  land AFTER the action that populates the state it prints, or it reads a
  not-yet-set value.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Protocol

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


class DebugPlantError(ValueError):
    """Base error for debug plant/strip operations."""


class NoAnchorError(DebugPlantError):
    """The anchor action id was not found — nothing was planted."""


def _split(data: str) -> tuple[list[str], str]:
    nl = "\r\n" if "\r\n" in data else "\n"
    return data.split(nl), nl


@dataclass(frozen=True)
class _Action:
    content: dict
    line: int
    indent: int
    end: int


def _content_end(node) -> int:
    if isinstance(node, ScalarNode):
        return node.end_mark.line + bool(node.end_mark.column)
    if isinstance(node, MappingNode):
        return max(_content_end(child) for pair in node.value for child in pair)
    return max((_content_end(child) for child in node.value), default=node.end_mark.line)


def _actions(data: str) -> list[_Action]:
    """Locate parsed action-list members, never action-like text in messages."""
    loader = yaml.SafeLoader(data)
    actions = []
    lines = data.splitlines()

    def visit(node, ancestors: set[int]) -> None:
        if id(node) in ancestors:
            raise DebugPlantError("Recursive YAML aliases are not supported.")
        ancestors = ancestors | {id(node)}
        if isinstance(node, MappingNode):
            for key, child in node.value:
                if (
                    isinstance(key, ScalarNode)
                    and key.value in {"actions", "elseActions"}
                    and isinstance(child, SequenceNode)
                ):
                    for action in child.value:
                        if not isinstance(action, MappingNode):
                            continue
                        content = loader.construct_object(action, deep=True)
                        if "kind" not in content:
                            continue
                        if child.flow_style or action.flow_style:
                            raise DebugPlantError("Action lists must use block-style YAML.")
                        if sum(key.value == "id" for key, _ in action.value) > 1:
                            raise DebugPlantError("An action contains duplicate id fields.")
                        line = lines[action.start_mark.line]
                        indent = len(line) - len(line.lstrip(" "))
                        if not line[indent:].startswith("-"):
                            raise DebugPlantError("An action mapping must share its sequence dash's line.")
                        actions.append(_Action(
                            content, action.start_mark.line, indent,
                            _content_end(action),
                        ))
                # Activity payloads are message/card data, not dialog action lists.
                if not isinstance(key, ScalarNode) or key.value != "activity":
                    visit(child, ancestors)
        elif isinstance(node, SequenceNode):
            for child in node.value:
                visit(child, ancestors)

    try:
        root = loader.get_single_node()
        if root is not None:
            visit(root, set())
    except yaml.YAMLError as exc:
        raise DebugPlantError(f"Could not parse topic YAML: {exc}") from exc
    finally:
        loader.dispose()
    return actions


def plant_debug_node(
    data: str, *, after_action_id: str, node_id: str, activity: str
) -> tuple[str, int]:
    """Insert a DBG SendActivity node as the next sibling after the action whose
    ``id:`` is ``after_action_id``. Returns (modified_data, count). count==0 (and
    data unchanged) when the anchor action id is absent — the caller treats that
    as fatal (a mis-targeted plant). Duplicate anchors and an already-used
    diagnostic action ID raise DebugPlantError before returning a plant."""
    # The node is written as single-line YAML scalars; a line break in either
    # value would inject additional YAML lines (extra nodes) at the anchor indent.
    for field, value in (("node_id", node_id), ("activity", activity)):
        if "\n" in value or "\r" in value:
            raise ValueError(f"{field} must be single-line (no newlines): {value!r}")

    actions = _actions(data)
    anchors = [action for action in actions if action.content.get("id") == after_action_id]
    if len(anchors) > 1:
        raise DebugPlantError(f"Duplicate anchor action ID: {after_action_id!r}")
    if not anchors:
        return data, 0
    if any(action.content.get("id") == node_id for action in actions):
        raise DebugPlantError(f"Diagnostic action ID already exists: {node_id!r}")

    lines, nl = _split(data)
    end_idx = anchors[0].end
    pad = " " * anchors[0].indent
    node = [
        "",
        f"{pad}- kind: SendActivity",
        f"{pad}  id: {json.dumps(node_id, ensure_ascii=False)}",
        f"{pad}  activity: {activity}",
    ]
    new_lines = lines[:end_idx] + node + lines[end_idx:]
    return nl.join(new_lines), 1


def strip_debug_nodes(
    data: str, node_ids: list[str] | None = None, *, marker: str | None = None,
    expected_nodes: dict[str, dict] | None = None,
) -> tuple[str, list[str]]:
    """Remove planted DBG SendActivity blocks. Match by ``node_ids`` (exact id)
    and/or ``marker`` (the node's ``activity`` contains it). Returns
    (modified_data, removed_ids). At least one of node_ids/marker is required
    (stripping with neither is ambiguous). Removes the one leading blank line the
    plant inserts, so plant->strip is byte-identical.

    Explicit IDs must identify at most one action, including non-SendActivity
    actions. Optional expected_nodes maps every explicit ID to its complete
    parsed YAML action (kind/id/activity etc.); absent or changed owned content
    raises DebugPlantError. This guard cannot be combined with marker matching.
    Marker-only cleanup retains its legacy broad matching semantics."""
    if node_ids is None and marker is None:
        raise DebugPlantError("strip_debug_nodes requires node_ids or marker")
    id_set = set(node_ids or ())
    actions = _actions(data)
    for node_id in id_set:
        matches = [action for action in actions if action.content.get("id") == node_id]
        if len(matches) > 1:
            raise DebugPlantError(f"Duplicate cleanup action ID: {node_id!r}")
    if expected_nodes is not None:
        if node_ids is None or marker is not None or set(expected_nodes) != id_set:
            raise DebugPlantError("expected_nodes must cover exactly the explicit IDs without a marker.")
        for node_id, expected in expected_nodes.items():
            matches = [action for action in actions if action.content.get("id") == node_id]
            if (
                len(matches) != 1
                or matches[0].content.get("kind") != "SendActivity"
                or matches[0].content != expected
            ):
                raise DebugPlantError(f"Owned diagnostic action is absent or changed: {node_id!r}")
    lines, nl = _split(data)
    selected = [
        action for action in actions
        if action.content.get("kind") == "SendActivity"
        and (
            action.content.get("id") in id_set
            or (
                marker is not None
                and isinstance(action.content.get("activity"), str)
                and marker in action.content["activity"]
            )
        )
    ]
    for action in sorted(selected, key=lambda action: action.line, reverse=True):
        start = action.line
        if start and not lines[start - 1].strip():
            start -= 1
        del lines[start:action.end]
    return nl.join(lines), [action.content.get("id") for action in selected]


# --------------------------------------------------------------------------- #
# Live orchestration — deterministic; plant, PATCH, and (caller-driven) publish.
# The DataverseClient Protocol is structural, so any object exposing the three
# methods satisfies it without an import — keeping this core decoupled from the
# concrete Dataverse access layer.
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class PlantSpec:
    """One DBG node to plant: WHERE (after_action_id) + WHAT (node_id, activity).
    Choosing these values is the judgment/authoring touch; this struct is the
    deterministic contract that feeds plant_debug_node."""
    after_action_id: str
    node_id: str
    activity: str


@dataclass(frozen=True)
class PlantProvenance:
    """Everything strip_debug_nodes_live needs for a guaranteed byte-identical
    revert, plus the verifier specs a caller uses to confirm each plant is live."""
    topic: str
    record_id: str
    planted_node_ids: list[str]
    specs: list[PlantSpec]

    def verifier_specs(self) -> list[dict]:
        """The {nodeId, topic, marker} specs a verifier checks to confirm the
        planted DBG line rendered — so plant -> verify -> run is one loop.
        marker = the activity text (its DBG prefix is what a caller asserts on)."""
        return [{"nodeId": s.node_id, "topic": self.topic, "marker": s.activity}
                for s in self.specs]


class DataverseClient(Protocol):
    def get_topic(self, schemaname: str) -> tuple[str, str]: ...
    def patch_topic(self, record_id: str, content: str) -> None: ...


def plant_debug_nodes_live(
    client: DataverseClient, topic_schemaname: str, specs: list[PlantSpec]
) -> PlantProvenance:
    """Fetch the deployed topic, plant every spec, and PATCH it back in one write.
    Raises NoAnchorError (WITHOUT patching) if any spec's anchor action id is
    absent — a mis-targeted plant would otherwise silently instrument the wrong
    place or partially write. Returns provenance for a guaranteed strip.

    Publish is the caller's responsibility (a topic-layer change is dormant until
    publish); this leaves publish separate so the caller can batch/throttle it.
    """
    record_id, data = client.get_topic(topic_schemaname)
    new_data = data
    for spec in specs:
        new_data, count = plant_debug_node(
            new_data, after_action_id=spec.after_action_id,
            node_id=spec.node_id, activity=spec.activity)
        if count == 0:
            raise NoAnchorError(
                f"anchor action id {spec.after_action_id!r} not found in topic "
                f"{topic_schemaname!r}; refusing to PATCH (mis-targeted plant?)")
    client.patch_topic(record_id, new_data)
    return PlantProvenance(
        topic=topic_schemaname, record_id=record_id,
        planted_node_ids=[s.node_id for s in specs], specs=list(specs))


def strip_debug_nodes_live(client: DataverseClient, provenance: PlantProvenance) -> int:
    """Remove the planted nodes using captured provenance. Idempotent: if the
    nodes are already gone (already stripped), it is a no-op returning 0. Returns
    the number of nodes removed."""
    record_id, data = client.get_topic(provenance.topic)
    stripped, removed = strip_debug_nodes(data, node_ids=provenance.planted_node_ids)
    if removed:
        client.patch_topic(record_id, stripped)
    return len(removed)
