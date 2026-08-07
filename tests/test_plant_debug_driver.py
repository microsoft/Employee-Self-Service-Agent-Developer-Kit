# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the plant/strip driver's testable contracts: throttle-tolerant
publish and provenance round-tripping.

The Dataverse-touching adapter methods (get_topic/patch_topic/publish_bot) are
live-only; these cover the offline logic — the publish retry policy (a bare 401
or 429, or a 400 wrapping an inner 429, is transient throttling on a valid token)
and provenance serialize/deserialize (so a later strip restores byte-identically).
"""
from __future__ import annotations

import pytest

from debug_plant import PlantProvenance, PlantSpec
from http_errors import APIError
from plant_debug import (
    _is_transient_publish_error,
    load_provenance,
    publish_with_retry,
    save_provenance,
)


def _api_error(status_code, message="err"):
    return APIError(status_code=status_code, message=message, tip="")


# --------------------------------------------------------------------------- #
# throttle classification
# --------------------------------------------------------------------------- #

def test_401_and_429_are_transient():
    assert _is_transient_publish_error(_api_error(401)) is True
    assert _is_transient_publish_error(_api_error(429)) is True


def test_400_wrapping_429_is_transient():
    assert _is_transient_publish_error(
        _api_error(400, "Bad request while trying to publish (inner 429)")) is True


def test_plain_400_403_404_are_not_transient():
    assert _is_transient_publish_error(_api_error(400, "malformed body")) is False
    assert _is_transient_publish_error(_api_error(403)) is False
    assert _is_transient_publish_error(_api_error(404)) is False


# --------------------------------------------------------------------------- #
# publish_with_retry
# --------------------------------------------------------------------------- #

def test_publish_succeeds_first_try_without_sleeping():
    calls = {"publish": 0, "sleep": 0}

    def publish():
        calls["publish"] += 1

    def sleep(_):
        calls["sleep"] += 1

    publish_with_retry(publish, sleep=sleep)
    assert calls["publish"] == 1
    assert calls["sleep"] == 0


def test_publish_retries_transient_then_succeeds():
    state = {"n": 0}
    slept = []

    def publish():
        state["n"] += 1
        if state["n"] < 3:
            raise _api_error(429)

    publish_with_retry(publish, attempts=5, base_delay=1.0, sleep=slept.append)
    assert state["n"] == 3
    # backed off before the 2nd and 3rd attempts: 1.0 * 2**0, 1.0 * 2**1
    assert slept == [1.0, 2.0]


def test_publish_non_transient_raises_immediately():
    slept = []

    def publish():
        raise _api_error(400, "malformed body")

    with pytest.raises(APIError):
        publish_with_retry(publish, sleep=slept.append)
    assert slept == []  # no retry on a real error


def test_publish_reraises_after_exhausting_attempts():
    calls = {"n": 0}

    def publish():
        calls["n"] += 1
        raise _api_error(429)

    with pytest.raises(APIError):
        publish_with_retry(publish, attempts=3, base_delay=1.0, sleep=lambda _: None)
    assert calls["n"] == 3  # tried the full budget, then re-raised


# --------------------------------------------------------------------------- #
# provenance round-trip
# --------------------------------------------------------------------------- #

def test_provenance_round_trips(tmp_path):
    path = tmp_path / ".dbg_provenance.json"
    prov = PlantProvenance(
        topic="snow_sys",
        record_id="rec-1",
        planted_node_ids=["sendActivity_DBG_a", "sendActivity_DBG_b"],
        specs=[
            PlantSpec(after_action_id="setVariable_a", node_id="sendActivity_DBG_a",
                      activity="DBG branch=a"),
            PlantSpec(after_action_id="beginDialog_b", node_id="sendActivity_DBG_b",
                      activity="DBG branch=b"),
        ],
    )
    save_provenance(prov, path)
    loaded = load_provenance(path)

    assert loaded.topic == prov.topic
    assert loaded.record_id == prov.record_id
    assert loaded.planted_node_ids == prov.planted_node_ids
    assert loaded.specs == prov.specs  # frozen dataclasses compare by value


def test_saved_provenance_ends_with_newline(tmp_path):
    path = tmp_path / ".dbg_provenance.json"
    prov = PlantProvenance(topic="t", record_id="r", planted_node_ids=["n"],
                           specs=[PlantSpec("a", "n", "DBG x")])
    save_provenance(prov, path)
    assert path.read_text(encoding="utf-8").endswith("}\n")


# --------------------------------------------------------------------------- #
# AuthDataverseClient uses the real botcomponent field name (`data`, not
# `content`) — a regression guard for the live-only field-name bug that the pure
# FakeDataverse tests could not catch (the topic body lives in the `data`
# column; get/patch against `content` silently read/wrote nothing).
# --------------------------------------------------------------------------- #

def test_get_topic_selects_and_reads_data_field(monkeypatch):
    import auth as auth_mod
    from plant_debug import AuthDataverseClient

    captured = {}

    def fake_query_all(env_url, token, entity_set, select, filter_expr=None):
        captured["entity_set"] = entity_set
        captured["select"] = select
        captured["filter"] = filter_expr
        return [{"botcomponentid": "rec-1", "data": "TOPIC_BODY"}]

    monkeypatch.setattr(auth_mod, "query_all", fake_query_all)
    client = AuthDataverseClient("https://x.crm.dynamics.com", "tok")
    rec_id, body = client.get_topic("msdyn_x.topic.Foo")

    assert rec_id == "rec-1"
    assert body == "TOPIC_BODY"
    assert captured["entity_set"] == "botcomponents"
    # The topic body must be selected via the `data` column, never `content`.
    assert "data" in captured["select"]
    assert "content" not in captured["select"]


def test_patch_topic_writes_data_field(monkeypatch):
    import auth as auth_mod
    from plant_debug import AuthDataverseClient

    captured = {}

    def fake_update_record(env_url, token, entity_set, record_id, data):
        captured["entity_set"] = entity_set
        captured["record_id"] = record_id
        captured["payload"] = data

    monkeypatch.setattr(auth_mod, "update_record", fake_update_record)
    client = AuthDataverseClient("https://x.crm.dynamics.com", "tok")
    client.patch_topic("rec-1", "NEW_BODY")

    assert captured["entity_set"] == "botcomponents"
    assert captured["record_id"] == "rec-1"
    # The topic body must be PATCHed into the `data` column, never `content`.
    assert captured["payload"] == {"data": "NEW_BODY"}
    assert "content" not in captured["payload"]


# --------------------------------------------------------------------------- #
# resolve_topic_schema: accept a friendly filename/stem/display-name and map it
# to the immutable botcomponent schemaname, so a maker does not have to hand-type
# `msdyn_copilotforemployeeselfservicehr.topic.<Stem>`.
# --------------------------------------------------------------------------- #

_COMPONENT_MAP = {
    "topics/servicenow-hrsd-get-cases-by-status.mcs.yml": {
        "botcomponentid": "aaaa",
        "schemaname": "msdyn_x.topic.ServiceNowHRSDGetCasesByStatus",
        "name": "ServiceNow HRSD Get Cases By Status",
    },
    "topics/workday-get-passports.mcs.yml": {
        "botcomponentid": "bbbb",
        "schemaname": "msdyn_x.topic.WorkdayGetPassports",
        "name": "Workday Get Passports",
    },
}


def test_resolve_full_schemaname_passes_through():
    from plant_debug import resolve_topic_schema
    assert resolve_topic_schema("msdyn_x.topic.Foo", {}) == "msdyn_x.topic.Foo"


def test_resolve_by_stem():
    from plant_debug import resolve_topic_schema
    assert resolve_topic_schema(
        "servicenow-hrsd-get-cases-by-status", _COMPONENT_MAP
    ) == "msdyn_x.topic.ServiceNowHRSDGetCasesByStatus"


def test_resolve_by_filename_with_extension():
    from plant_debug import resolve_topic_schema
    assert resolve_topic_schema(
        "servicenow-hrsd-get-cases-by-status.mcs.yml", _COMPONENT_MAP
    ) == "msdyn_x.topic.ServiceNowHRSDGetCasesByStatus"


def test_resolve_by_full_map_key():
    from plant_debug import resolve_topic_schema
    assert resolve_topic_schema(
        "topics/servicenow-hrsd-get-cases-by-status.mcs.yml", _COMPONENT_MAP
    ) == "msdyn_x.topic.ServiceNowHRSDGetCasesByStatus"


def test_resolve_by_display_name_case_insensitive():
    from plant_debug import resolve_topic_schema
    assert resolve_topic_schema(
        "workday get passports", _COMPONENT_MAP
    ) == "msdyn_x.topic.WorkdayGetPassports"


def test_resolve_not_found_raises_lookup_error():
    from plant_debug import resolve_topic_schema
    with pytest.raises(LookupError) as exc:
        resolve_topic_schema("no-such-topic", _COMPONENT_MAP)
    assert "no-such-topic" in str(exc.value)


def test_resolve_ambiguous_raises_value_error():
    from plant_debug import resolve_topic_schema
    ambiguous = {
        "topics/foo.mcs.yml": {"schemaname": "msdyn_x.topic.FooA", "name": "A"},
        "variables/foo.mcs.yml": {"schemaname": "msdyn_x.component.FooB", "name": "B"},
    }
    with pytest.raises(ValueError) as exc:
        resolve_topic_schema("foo", ambiguous)
    assert "ambiguous" in str(exc.value).lower()
