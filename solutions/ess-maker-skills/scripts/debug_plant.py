# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DBG SendActivity plant/strip — pure text transforms over a topic's
botcomponent ``data`` YAML.

Codifies the debug-oracle instrumentation pattern: insert a DBG ``SendActivity``
node after a named action to project internal topic state into the transcript,
then strip it locally. Both transforms are pure and byte-reversible; neither
reads, saves or publishes a deployed topic.

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

class DebugPlantError(ValueError):
    """Base error for debug plant/strip operations."""


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
