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
from typing import Protocol


class DebugPlantError(ValueError):
    """Base error for debug plant/strip operations."""


class NoAnchorError(DebugPlantError):
    """The anchor action id was not found — nothing was planted."""


def _split(data: str) -> tuple[list[str], str]:
    nl = "\r\n" if "\r\n" in data else "\n"
    return data.split(nl), nl


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def plant_debug_node(
    data: str, *, after_action_id: str, node_id: str, activity: str
) -> tuple[str, int]:
    """Insert a DBG SendActivity node as the next sibling after the action whose
    ``id:`` is ``after_action_id``. Returns (modified_data, count). count==0 (and
    data unchanged) when the anchor action id is absent — the caller treats that
    as fatal (a mis-targeted plant)."""
    # The node is written as single-line YAML scalars; a line break in either
    # value would inject additional YAML lines (extra nodes) at the anchor indent.
    for field, value in (("node_id", node_id), ("activity", activity)):
        if "\n" in value or "\r" in value:
            raise ValueError(f"{field} must be single-line (no newlines): {value!r}")

    lines, nl = _split(data)

    id_idx = next((i for i, line in enumerate(lines)
                   if line.strip() == f"id: {after_action_id}"), None)
    if id_idx is None:
        return data, 0

    # Owning list item: nearest preceding '- kind:' line.
    anchor_idx = next((i for i in range(id_idx, -1, -1)
                       if lines[i].lstrip().startswith("- kind:")), None)
    if anchor_idx is None:
        return data, 0
    anchor_indent = _indent(lines[anchor_idx])

    # End of the anchor action's block: the next non-blank line at indent
    # <= anchor_indent (a sibling '-' or a dedent to the parent).
    end_idx = len(lines)
    for i in range(anchor_idx + 1, len(lines)):
        if lines[i].strip() == "":
            continue
        if _indent(lines[i]) <= anchor_indent:
            end_idx = i
            break
    # Insert after the block's last CONTENT line (skip trailing blanks so the
    # planted node sits with the action, and any original separator blank stays
    # after it — keeping the round-trip exact).
    last_content = end_idx - 1
    while last_content > anchor_idx and lines[last_content].strip() == "":
        last_content -= 1

    pad = " " * anchor_indent
    node = [
        "",
        f"{pad}- kind: SendActivity",
        f"{pad}  id: {node_id}",
        f"{pad}  activity: {activity}",
    ]
    new_lines = lines[: last_content + 1] + node + lines[last_content + 1:]
    return nl.join(new_lines), 1


def strip_debug_nodes(
    data: str, node_ids: list[str] | None = None, *, marker: str | None = None
) -> tuple[str, list[str]]:
    """Remove planted DBG SendActivity blocks. Match by ``node_ids`` (exact id)
    and/or ``marker`` (the node's ``activity`` contains it). Returns
    (modified_data, removed_ids). At least one of node_ids/marker is required
    (stripping with neither is ambiguous). Removes the one leading blank line the
    plant inserts, so plant->strip is byte-identical."""
    if node_ids is None and marker is None:
        raise DebugPlantError("strip_debug_nodes requires node_ids or marker")
    id_set = set(node_ids or ())
    lines, nl = _split(data)

    out: list[str] = []
    removed: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("- kind: SendActivity"):
            base = _indent(line)
            block = [line]
            j = i + 1
            while j < len(lines) and lines[j].strip() != "" and _indent(lines[j]) > base:
                block.append(lines[j])
                j += 1
            nid = None
            act = None
            for b in block:
                bs = b.strip()
                if bs.startswith("id: "):
                    nid = bs[len("id: "):].strip()
                elif bs.startswith("activity: "):
                    act = bs[len("activity: "):].strip()
            matched = (nid in id_set) or (
                marker is not None and act is not None and marker in act)
            if matched:
                removed.append(nid)
                # reverse the plant's leading blank line
                if out and out[-1].strip() == "":
                    out.pop()
                i = j
                continue
        out.append(line)
        i += 1
    return nl.join(out), removed


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
