# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the DBG SendActivity plant/strip pure transforms (debug_plant).

Two pure text transforms over a topic's botcomponent ``data`` YAML:

- plant_debug_node : insert a ``- kind: SendActivity`` DBG node immediately AFTER
                     the action whose ``id:`` is ``after_action_id``, at that
                     action's indentation. Returns (modified, count). count==0
                     when the anchor action id is absent (caller treats as fatal).
- strip_debug_nodes: remove planted DBG SendActivity blocks (by node id list, or
                     all whose activity carries the DBG marker). Byte-reversible
                     against the pre-plant data.

Round-trip invariant: strip(plant(data)) == data (byte-identical).
These tests exercise local text only, not a deployed-topic cleanup path.
"""
from __future__ import annotations

import pytest

from debug_plant import (
    DebugPlantError,
    plant_debug_node,
    strip_debug_nodes,
)

# A minimal topic with two actions at different indents (a SetVariable inside a
# ConditionGroup action, and a BeginDialog under elseActions).
_TOPIC = """\
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  actions:
    - kind: ConditionGroup
      id: conditionGroup_root
      conditions:
        - id: conditionItem_cache
          actions:
            - kind: SetVariable
              id: setVariable_cacheHit
              variable: Topic.ServiceNowData
              value: =Global.Cache
      elseActions:
        - kind: BeginDialog
          id: beginDialog_fetch
          output:
            binding:
              ServiceNowData: Topic.ServiceNowData
"""


# --------------------------------------------------------------------------- #
# plant_debug_node
# --------------------------------------------------------------------------- #

def test_plant_inserts_node_after_anchor_action():
    out, n = plant_debug_node(
        _TOPIC, after_action_id="setVariable_cacheHit",
        node_id="sendActivity_DBG_cacheHit",
        activity="DBG branch=cache-hit")
    assert n == 1
    assert "sendActivity_DBG_cacheHit" in out
    assert "DBG branch=cache-hit" in out
    # the DBG node appears AFTER the anchor action's id, not before it
    assert out.index("setVariable_cacheHit") < out.index("sendActivity_DBG_cacheHit")


def test_plant_rejects_newline_in_activity_or_node_id():
    import pytest
    # A newline would inject extra YAML lines (extra nodes) at the anchor indent.
    with pytest.raises(ValueError):
        plant_debug_node(_TOPIC, after_action_id="setVariable_cacheHit",
                         node_id="dbg", activity="ok\n        - kind: SendActivity")
    with pytest.raises(ValueError):
        plant_debug_node(_TOPIC, after_action_id="setVariable_cacheHit",
                         node_id="dbg\nid: evil", activity="ok")


def test_plant_uses_anchor_action_indentation():
    out, _ = plant_debug_node(
        _TOPIC, after_action_id="setVariable_cacheHit",
        node_id="sendActivity_DBG_cacheHit",
        activity="DBG branch=cache-hit")
    # the anchor '- kind: SetVariable' is indented 12 spaces; the planted
    # '- kind: SendActivity' must match so the YAML list stays well-formed.
    planted_line = next(pl for pl in out.splitlines() if "kind: SendActivity" in pl)
    assert planted_line.startswith(" " * 12 + "- kind: SendActivity")


def test_plant_absent_anchor_counts_zero_and_unchanged():
    out, n = plant_debug_node(
        _TOPIC, after_action_id="setVariable_nonexistent",
        node_id="sendActivity_DBG_x", activity="DBG x")
    assert n == 0
    assert out == _TOPIC


def test_plant_result_still_parses_as_yaml():
    import yaml
    out, _ = plant_debug_node(
        _TOPIC, after_action_id="beginDialog_fetch",
        node_id="sendActivity_DBG_fetch", activity="DBG branch=fetch")
    doc = yaml.safe_load(out)  # must not raise
    assert doc["kind"] == "AdaptiveDialog"


def test_plant_disambiguates_by_action_id_not_text():
    # 'ServiceNowData: Topic.ServiceNowData' occurs twice in the topic; anchoring
    # by ACTION ID must place the node relative to the right action, unaffected
    # by the ambiguous field text.
    out, n = plant_debug_node(
        _TOPIC, after_action_id="beginDialog_fetch",
        node_id="sendActivity_DBG_fetch", activity="DBG branch=fetch")
    assert n == 1
    # planted after beginDialog_fetch (the else branch), not after the cache one
    assert out.index("beginDialog_fetch") < out.index("sendActivity_DBG_fetch")


# --------------------------------------------------------------------------- #
# strip_debug_nodes
# --------------------------------------------------------------------------- #

def test_strip_by_node_id_removes_planted_node():
    planted, _ = plant_debug_node(
        _TOPIC, after_action_id="setVariable_cacheHit",
        node_id="sendActivity_DBG_cacheHit", activity="DBG branch=cache-hit")
    out, removed = strip_debug_nodes(planted, node_ids=["sendActivity_DBG_cacheHit"])
    assert removed == ["sendActivity_DBG_cacheHit"]
    assert "sendActivity_DBG_cacheHit" not in out
    assert "DBG branch=cache-hit" not in out


def test_strip_round_trip_is_byte_identical():
    planted, _ = plant_debug_node(
        _TOPIC, after_action_id="setVariable_cacheHit",
        node_id="sendActivity_DBG_cacheHit", activity="DBG branch=cache-hit")
    out, _ = strip_debug_nodes(planted, node_ids=["sendActivity_DBG_cacheHit"])
    assert out == _TOPIC   # guaranteed-revert property


def test_strip_by_marker_removes_all_dbg_nodes():
    p1, _ = plant_debug_node(_TOPIC, after_action_id="setVariable_cacheHit",
                             node_id="sendActivity_DBG_a", activity="DBG branch=a")
    p2, _ = plant_debug_node(p1, after_action_id="beginDialog_fetch",
                             node_id="sendActivity_DBG_b", activity="DBG branch=b")
    out, removed = strip_debug_nodes(p2, marker="DBG")
    assert set(removed) == {"sendActivity_DBG_a", "sendActivity_DBG_b"}
    assert "DBG branch=" not in out
    assert out == _TOPIC


def test_strip_absent_node_removes_nothing():
    out, removed = strip_debug_nodes(_TOPIC, node_ids=["sendActivity_DBG_missing"])
    assert removed == []
    assert out == _TOPIC


def test_strip_requires_node_ids_or_marker():
    with pytest.raises(DebugPlantError):
        strip_debug_nodes(_TOPIC)  # neither node_ids nor marker -> ambiguous


def test_multi_plant_then_marker_strip_round_trips():
    # plant two (the debug-oracle shape) then strip-all returns the original
    data = _TOPIC
    for aid, nid, act in [
        ("setVariable_cacheHit", "sendActivity_DBG_cacheHit", "DBG branch=cache-hit"),
        ("beginDialog_fetch", "sendActivity_DBG_fetch", "DBG branch=fetch"),
    ]:
        data, n = plant_debug_node(data, after_action_id=aid, node_id=nid, activity=act)
        assert n == 1
    stripped, removed = strip_debug_nodes(data, marker="DBG")
    assert len(removed) == 2
    assert stripped == _TOPIC
