# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Local persistence and synthetic restore tests; no native qualification claim."""

from copy import deepcopy
from dataclasses import replace
import sqlite3
from unittest.mock import Mock

import pytest
import requests

from topic_actions_client import TopicActionsClient
from tests.scripts.test_topic_actions_runtime import TARGET, dev_native_backend
from topic_actions_catalog import plan_catalog_actions
from topic_actions_execution import TopicActionSession
from topic_actions_state import TopicStateError, TopicStateStore


def _native_run(store, action, before, after, *, selected=("alpha", "beta"), confirm=None):
    backend = dev_native_backend(selected=selected, before=before, after=after)
    if action == "restore":
        backend.selected_keys = store.restore_keys()
        backend.state_store = store
        backend.restoring = True
    result = TopicActionSession(backend, action, state_store=store).run(confirm or (lambda _: "approve"))
    return result, backend


def _seed(store):
    original = {"a": "On", "shared": "Off", "b": "Off"}
    enabled = {"a": "On", "shared": "On", "b": "On"}
    result, _ = _native_run(store, "enable", original, enabled)
    assert result["completed"], result
    return original, enabled


def test_baseline_precedes_dispatch_and_survives_multiple_operations_and_restart(tmp_path):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    reviews = []
    original, enabled = _seed(store)
    baseline = deepcopy(store.load()["baseline"])
    assert len(baseline["topics"]) == 4
    assert baseline["topics"]["a"]["state"] == "On"
    assert baseline["topics"]["shared"]["state"] == "Off"
    assert "dialog" not in repr(baseline) and "private" not in repr(baseline)
    mixed = {**enabled, "a": "Off"}
    result, _ = _native_run(
        store, "disable", enabled, mixed, selected=("alpha",),
    )
    assert result["completed"] is False  # The shared topic is protected by beta.
    assert result["status"] == "completed_with_protections"
    restarted = TopicStateStore(tmp_path, TARGET)
    backend = dev_native_backend(before=mixed, after=original, selected=restarted.restore_keys())
    backend.state_store, backend.restoring = restarted, True

    def submit(payload):
        persisted = restarted.load()
        assert persisted["baseline"] == baseline
        assert persisted["journal"]["pending"]["status"] == "in_progress"
        updates = [row["component"] for row in payload["botComponentChanges"]]
        assert {item["state"] for item in updates} == {"Active", "Inactive"}
        assert {item["id"] for item in updates} == {"a", "shared", "b"}

    backend.components.submit_state_payload.side_effect = submit
    result = TopicActionSession(backend, "restore", state_store=restarted).run(
        lambda review: reviews.append(review) or "approve",
    )
    assert result["status"] == "completed" and result["completed"]
    backend.components.submit_state_payload.assert_called_once()
    assert len(reviews) == 1
    assert len(reviews[0]["restoreStates"]) == 3
    assert reviews[0]["baseline"]["status"] == "saved_original"
    assert restarted.load()["baseline"] == baseline
    assert restarted.load()["journal"]["pending"] is None


def test_original_is_durable_before_the_first_native_submission(tmp_path):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    backend = dev_native_backend(after={"a": "On", "shared": "On"})
    def submit(*args, **kwargs):
        saved = TopicStateStore(tmp_path, TARGET).load()
        assert saved["baseline"]["topics"]["a"]["state"] == "Off"
        assert saved["journal"]["pending"]["topics"]["a"]["after"] == "On"
    backend.components.submit_state_payload.side_effect = submit
    result = TopicActionSession(backend, "enable", state_store=store).run(lambda _: "approve")
    assert result["completed"]


@pytest.mark.parametrize("decision", ["deny", "cancel", "ambiguous"])
def test_denial_cancellation_and_ambiguous_consent_do_not_capture_or_write(tmp_path, decision):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    result, backend = _native_run(store, "enable", {}, {}, confirm=lambda _: decision)
    assert result["writeStatus"] == "not_attempted"
    assert not store.path.exists()
    backend.components.submit_state_payload.assert_not_called()


def test_previews_and_already_correct_do_not_initialize_a_baseline(tmp_path):
    store = TopicStateStore(tmp_path, TARGET)
    backend = dev_native_backend()
    result = TopicActionSession(backend, "enable", state_store=store).run(
        lambda _: pytest.fail("Preview cannot ask for consent."), preview=True,
    )
    assert result["status"] == "preview"
    result, backend = _native_run(store, "disable", {}, {})
    assert result["status"] == "already_correct" and result["completed"]
    assert not store.path.exists()
    backend.components.submit_state_payload.assert_not_called()


def test_missing_original_is_not_silently_replaced_by_todays_state(tmp_path):
    store = TopicStateStore(tmp_path, TARGET)
    result, backend = _native_run(
        store, "enable", {}, {}, confirm=lambda _: pytest.fail("Original baseline is missing."),
    )
    assert result["blockers"] == ["original_baseline_missing"]
    backend.components.submit_state_payload.assert_not_called()
    with pytest.raises(TopicStateError, match="Original topic states"):
        store.restore_keys()
    assert not store.path.exists()


def test_restore_noop_rechecks_after_approval_without_writing(tmp_path):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    original, enabled = _seed(store)
    result, _ = _native_run(store, "restore", enabled, original)
    assert result["completed"]
    reviews = []
    result, backend = _native_run(
        store, "restore", original, original, confirm=lambda p: reviews.append(p) or "approve",
    )
    assert result["status"] == "already_correct" and result["completed"]
    assert len(reviews) == 1
    assert backend.components.read_components.call_count == 2
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("change", ["state", "content", "schema", "missing", "replacement", "membership"])
def test_restore_blocks_external_edits_and_identity_or_membership_drift(tmp_path, change):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    _, enabled = _seed(store)
    backend = dev_native_backend(before=enabled)
    packets = list(backend.components.read_components.side_effect)
    for body in packets:
        topic = body["botComponentChanges"][1]["component"]
        if change == "state":
            topic.update(state="Inactive", status="Inactive")
        elif change == "content":
            topic["dialog"]["newAction"] = "external-edit"
        elif change == "schema":
            topic["schemaName"] += "-renamed"
        elif change == "missing":
            body["botComponentChanges"].pop(1)
        elif change == "replacement":
            topic["id"] = "recreated-topic"
    if change == "membership":
        backend.selected_keys = ("alpha",)
    backend.components.read_components.side_effect = packets
    backend.state_store, backend.restoring = store, True
    result = TopicActionSession(backend, "restore", state_store=store).run(
        lambda _: pytest.fail("Conflicting restore cannot ask for consent."),
    )
    assert result["status"] == "blocked"
    assert result["blockers"][0] in {
        "restore_conflict", "baseline_topic_identity_changed", "restore_membership_changed",
    }
    backend.components.submit_state_payload.assert_not_called()


def test_unrelated_edits_are_preserved_and_reported_not_restored(tmp_path):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    original, enabled = _seed(store)
    reviews = []
    result, backend = _native_run(
        store, "restore", {**enabled, "unrelated": "Off"}, {**original, "unrelated": "Off"},
        confirm=lambda p: reviews.append(p) or "approve",
    )
    assert result["completed"]
    assert "unrelated_topic_states_differ_from_original_and_will_be_preserved" in result["warnings"]
    payload = backend.components.submit_state_payload.call_args.args[0]
    assert {row["component"]["id"] for row in payload["botComponentChanges"]} == {"shared", "b"}
    assert all(item["componentId"] != "unrelated" for item in reviews[0]["proposedChanges"])


def test_disk_failure_prevents_submission(tmp_path, monkeypatch):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    monkeypatch.setattr(store, "_save", Mock(side_effect=OSError("disk unavailable")))
    result, backend = _native_run(store, "enable", {}, {})
    assert result["writeStatus"] == "not_attempted"
    assert "baseline_storage_unavailable" in result["blockers"]
    backend.components.submit_state_payload.assert_not_called()
    monkeypatch.undo()
    result, _ = _native_run(store, "enable", {}, {"a": "On", "shared": "On", "b": "On"})
    assert result["completed"]  # An empty database from a failed transaction is not an original.


def test_corrupt_or_other_target_baseline_never_authorizes_restore(tmp_path):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    _seed(store)
    other = TopicStateStore(tmp_path, replace(TARGET, agent_id=TARGET.tenant_id))
    assert other.load() is None
    other.path.write_bytes(store.path.read_bytes())
    with pytest.raises(TopicStateError) as error:
        other.restore_keys()
    assert error.value.reason == "baseline_invalid"
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE state SET checksum='corrupt'")
    with pytest.raises(TopicStateError) as error:
        store.restore_keys()
    assert error.value.reason == "baseline_invalid"


def test_second_process_store_cannot_dispatch_while_an_intent_is_open(tmp_path):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    packet = dev_native_backend().read()
    revision, _ = store.review(packet, restoring=False)
    plan = plan_catalog_actions(packet.snapshot, "enable")
    operation = store.begin(packet, plan, revision)
    result, backend = _native_run(
        TopicStateStore(tmp_path, TARGET), "enable", {}, {},
        confirm=lambda _: pytest.fail("Another durable intent is open."),
    )
    assert result["blockers"] == ["topic_operation_in_progress_or_interrupted"]
    backend.components.submit_state_payload.assert_not_called()
    store.finish(operation, None, verified=False, attempted=False)
    assert store.load()["journal"]["pending"] is None


def test_baseline_head_drift_after_review_requires_fresh_approval(tmp_path):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    backend = dev_native_backend()
    packet = dev_native_backend().read()
    plan = plan_catalog_actions(packet.snapshot, "enable")
    def approve(_):
        revision, _ = store.review(packet, restoring=False)
        store.begin(packet, plan, revision)
        return "approve"
    result = TopicActionSession(backend, "enable", state_store=store).run(approve)
    assert result["status"] == "review_required"
    assert "baseline_changed_review_required" in result["blockers"]
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("readback", [True, False])
def test_uncertain_submission_requires_explicit_restore_not_normal_replay(tmp_path, readback):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    original, enabled = {"a": "Off", "shared": "Off", "b": "Off"}, {"a": "On", "shared": "On", "b": "On"}
    backend = dev_native_backend(selected=("alpha", "beta"), after=enabled)
    backend.components.submit_state_payload.side_effect = requests.Timeout("private service body")
    if not readback:
        packets = list(backend.components.read_components.side_effect)
        backend.components.read_components.side_effect = [*packets[:2], ValueError("unavailable")]
    result = TopicActionSession(backend, "enable", state_store=store).run(lambda _: "approve")
    assert result["status"] == "unverified"
    assert store.load()["journal"]["pending"]["status"] == "uncertain"
    backend.components.submit_state_payload.assert_called_once()
    result, blocked = _native_run(
        store, "disable", enabled, original,
        confirm=lambda _: pytest.fail("Uncertain write cannot be replayed as a normal action."),
    )
    assert result["blockers"] == ["previous_write_uncertain_restore_required"]
    blocked.components.submit_state_payload.assert_not_called()
    reviews = []
    result, restored = _native_run(
        TopicStateStore(tmp_path, TARGET), "restore", enabled, original,
        confirm=lambda p: reviews.append(p) or "approve",
    )
    assert result["completed"]
    assert "previous_submission_outcome_uncertain" in reviews[0]["warnings"]
    restored.components.submit_state_payload.assert_called_once()
    assert store.load()["journal"]["pending"] is None


def test_restore_mixed_states_uses_topic_owned_writer_once(tmp_path, monkeypatch):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    original, enabled = _seed(store)
    mixed = {**enabled, "a": "Off"}
    _native_run(store, "disable", enabled, mixed, selected=("alpha",))
    backend = dev_native_backend(before=mixed, selected=store.restore_keys())
    remote = deepcopy(next(backend.components.read_components.side_effect))
    client = TopicActionsClient(
        TARGET.environment_id, TARGET.agent_id, TARGET.tenant_id,
        ring=backend.client.ring, host=backend.client.host,
        token="private-token", account=backend.account_id,
    )
    backend.components = client
    backend.state_store, backend.restoring = store, True
    writes = []
    def request(method, url, **kwargs):
        assert url == client._components_url
        if method == "PUT":
            writes.append(deepcopy(kwargs["body"]))
            changes = {row["component"]["id"]: row["component"] for row in kwargs["body"]["botComponentChanges"]}
            for row in remote["botComponentChanges"]:
                identity = row["component"]["id"]
                if identity in changes:
                    row["component"] = deepcopy(changes[identity])
            remote["changeToken"] = "r2"
        else:
            assert method == "POST"
        return Mock(status_code=200), deepcopy(remote)
    monkeypatch.setattr(client, "_request", request)
    result = TopicActionSession(backend, "restore", state_store=store).run(lambda _: "approve")
    assert result["completed"], result
    assert len(writes) == 1
    changes = {row["component"]["id"]: row["component"] for row in writes[0]["botComponentChanges"]}
    assert changes["a"]["state"] == "Active"
    assert changes["shared"]["state"] == changes["b"]["state"] == "Inactive"
    assert "unrelated" not in changes
    assert store.load()["baseline"]["topics"]["a"]["state"] == original["a"]


def test_restore_approval_expiry_never_submits_or_changes_the_baseline(tmp_path):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    original, enabled = _seed(store)
    saved = store.path.read_bytes()
    backend = dev_native_backend(before=enabled, after=original, selected=store.restore_keys())
    backend.state_store, backend.restoring = store, True
    clock = [0]
    def approve(_):
        clock[0] = 301
        return "approve"
    result = TopicActionSession(
        backend, "restore", state_store=store, clock=lambda: clock[0],
    ).run(approve)
    assert result["status"] == "review_required" and result["blockers"] == ["approval_expired"]
    backend.components.submit_state_payload.assert_not_called()
    assert store.path.read_bytes() == saved


def test_unknown_initial_state_outside_selected_set_blocks_first_write(tmp_path):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    backend = dev_native_backend()
    packets = list(backend.components.read_components.side_effect)
    for body in packets:
        body["botComponentChanges"][-1]["component"].update(state=None, status=None)
    backend.components.read_components.side_effect = packets
    result = TopicActionSession(backend, "enable", state_store=store).run(
        lambda _: pytest.fail("Every original topic state must be known before first write."),
    )
    assert result["blockers"] == ["baseline_topic_evidence_unavailable"]
    backend.components.submit_state_payload.assert_not_called()
    assert not store.path.exists()


def test_journal_failure_after_dispatch_is_unverified_and_never_replayed(tmp_path, monkeypatch):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    monkeypatch.setattr(store, "finish", Mock(side_effect=OSError("private-path")))
    result, backend = _native_run(
        store, "enable", {}, {"a": "On", "shared": "On", "b": "On"},
    )
    assert result["status"] == "unverified" and not result["completed"]
    assert result["writeStatus"] == "submitted"
    assert "state_journal_update_failed" in result["blockers"]
    assert "private-path" not in repr(result)
    backend.components.submit_state_payload.assert_called_once()
    assert store.load()["journal"]["pending"]["status"] == "in_progress"


def test_restore_expiring_after_intent_save_does_not_clear_prior_uncertainty(tmp_path, monkeypatch):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    enabled = {"a": "On", "shared": "On", "b": "On"}
    backend = dev_native_backend(selected=("alpha", "beta"), after=enabled)
    backend.components.submit_state_payload.side_effect = requests.Timeout()
    result = TopicActionSession(backend, "enable", state_store=store).run(lambda _: "approve")
    assert result["status"] == "unverified"
    restoring = dev_native_backend(before=enabled, selected=store.restore_keys())
    restoring.state_store, restoring.restoring = store, True
    clock = [0]
    original_begin = store.begin
    def begin(*args):
        operation = original_begin(*args)
        clock[0] = 301
        return operation
    monkeypatch.setattr(store, "begin", begin)
    result = TopicActionSession(
        restoring, "restore", state_store=store, clock=lambda: clock[0],
    ).run(lambda _: "approve")
    assert result["blockers"] == ["approval_expired"]
    restoring.components.submit_state_payload.assert_not_called()
    assert store.load()["journal"]["pending"]["status"] == "uncertain"
    with pytest.raises(TopicStateError) as error:
        store.review(dev_native_backend(before=enabled).read(), restoring=False)
    assert error.value.reason == "previous_write_uncertain_restore_required"


def test_uncertain_unapplied_write_can_be_reconciled_by_approved_noop_restore(tmp_path):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    backend = dev_native_backend(selected=("alpha", "beta"))
    backend.components.submit_state_payload.side_effect = requests.Timeout()
    result = TopicActionSession(backend, "enable", state_store=store).run(lambda _: "approve")
    assert result["status"] == "unverified"
    reviews = []
    result, restored = _native_run(
        store, "restore", {}, {}, confirm=lambda p: reviews.append(p) or "approve",
    )
    assert result["status"] == "already_correct" and result["completed"]
    assert len(reviews) == 1
    restored.components.submit_state_payload.assert_not_called()
    assert store.load()["journal"]["pending"] is None


def _record_expression_packets(backend, *, parsed):
    packets = list(backend.components.read_components.side_effect)
    for index, body in enumerate(packets):
        value = {"$kind": "ValueExpression", "expressionText": "{ worker: Global.Worker }"}
        if parsed or index == 2:
            value["structuredRecordExpression"] = {"$kind": "StructuredRecordExpression", "fields": []}
        body["botComponentChanges"][0]["component"]["dialog"]["value"] = value
    backend.components.read_components.side_effect = packets
    return packets


@pytest.mark.parametrize("edit", [False, True])
def test_restore_after_uncertain_write_ignores_only_derived_record_data(tmp_path, edit):
    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    enabled = {"a": "On", "shared": "On", "b": "On"}
    backend = dev_native_backend(selected=("alpha", "beta"), after=enabled)
    _record_expression_packets(backend, parsed=False)
    backend.components.submit_state_payload.side_effect = requests.Timeout()
    result = TopicActionSession(backend, "enable", state_store=store).run(lambda _: "approve")
    assert result["status"] == "unverified"
    baseline = deepcopy(store.load()["baseline"])
    saved = store.path.read_bytes()
    restored = dev_native_backend(before=enabled, selected=store.restore_keys())
    packets = _record_expression_packets(restored, parsed=True)
    if edit:
        for packet in packets:
            packet["botComponentChanges"][0]["component"]["dialog"]["value"]["expressionText"] = "{ worker: Global.Other }"
    restored.components.read_components.side_effect = packets
    restored.state_store, restored.restoring = store, True
    reviews = []

    result = TopicActionSession(restored, "restore", state_store=store).run(
        lambda p: reviews.append(p) or "approve",
    )

    assert store.load()["baseline"] == baseline
    if edit:
        assert result["blockers"] == ["restore_conflict"]
        assert not reviews
        restored.components.submit_state_payload.assert_not_called()
        assert store.path.read_bytes() == saved
    else:
        assert result["completed"], result
        assert len(reviews) == 1
        restored.components.submit_state_payload.assert_called_once()
        assert store.load()["journal"]["pending"] is None


@pytest.mark.parametrize("uncertain", [False, True])
def test_restore_accepts_exact_legacy_record_fingerprint_without_rewriting_baseline(
    tmp_path, monkeypatch, uncertain,
):
    import topic_actions_state as state

    store = TopicStateStore(tmp_path, TARGET, first_use=True)
    enabled = {"a": "On", "shared": "On", "b": "On"}
    backend = dev_native_backend(selected=("alpha", "beta"), after=enabled)
    _record_expression_packets(backend, parsed=True)
    if uncertain:
        backend.components.submit_state_payload.side_effect = requests.Timeout()
    current_topics = state._topics
    with monkeypatch.context() as legacy:
        legacy.setattr(
            state, "_topics", lambda e: current_topics(e, normalize_structured_records=False),
        )
        result = TopicActionSession(backend, "enable", state_store=store).run(lambda _: "approve")
    assert result["status"] == ("unverified" if uncertain else "completed")
    baseline = deepcopy(store.load()["baseline"])
    restored = dev_native_backend(before=enabled, selected=store.restore_keys())
    _record_expression_packets(restored, parsed=True)
    restored.state_store, restored.restoring = store, True

    result = TopicActionSession(restored, "restore", state_store=store).run(lambda _: "approve")

    assert result["completed"], result
    restored.components.submit_state_payload.assert_called_once()
    assert store.load()["baseline"] == baseline
    assert store.load()["journal"]["pending"] is None
