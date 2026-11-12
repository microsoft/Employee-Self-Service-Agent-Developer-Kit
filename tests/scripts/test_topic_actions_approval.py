# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Cross-process review/apply and consent safety with synthetic evidence only."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

import topic_actions as entry
from topic_actions_approval import TopicReviewError, TopicReviewStore
from topic_actions_execution import TopicActionSession
from tests.scripts.test_topic_actions_runtime import TARGET, SyntheticBackend, operation_evidence


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "solutions" / "ess-maker-skills" / "scripts"
REQUEST = {
    "contractVersion": 1,
    "target": {
        "tenantId": TARGET.tenant_id, "environmentId": TARGET.environment_id,
        "agentId": TARGET.agent_id,
    },
    "action": "disable", "setKeys": ["alpha"], "entry": "direct", "initializeBaseline": True,
}

# Each invocation imports the actual entry/controller in a new interpreter.
HARNESS = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, {scripts!r})
sys.path.insert(0, {root!r})
import topic_actions as entry
import topic_actions_native
from agentbuilder import derive_environment_host
from tests.scripts.test_topic_actions_runtime import TARGET, dev_native_backend

scenario = {scenario!r}
root = Path({workspace!r})
entry._workspace_target = lambda *a, **k: {{
    "ring": "test",
    "host": derive_environment_host(TARGET.environment_id, "test", resolver=lambda *a: None),
    "api_version": "2022-03-01-preview",
}}
entry.authenticate_flightcheck = lambda *a, **k: ("private-token", TARGET.tenant_id, "synthetic-maker")
before = {{}} if scenario == "noop" else {{"a": "On", "shared": "On"}}
after = {{}}
if scenario == "restore":
    before = {{}}
    after = {{"a": "On", "shared": "On"}}
backend = dev_native_backend(before=before, after=after)
if scenario == "drift":
    packets = list(backend.components.read_components.side_effect)
    for packet in packets[:2]:
        packet["changeToken"] = "changed"
    backend.components.read_components.side_effect = packets
if scenario == "account":
    entry.authenticate_flightcheck = lambda *a, **k: ("private-token", TARGET.tenant_id, "other-account")
    backend.account_id = "other-account"
    backend.components.signed_in_username = "other-account"
def submitted(*args):
    with (root / "submissions.txt").open("a") as f:
        f.write("submitted\n")
    if scenario == "failure":
        raise TimeoutError("Synthetic uncertain submission")
backend.components.submit_state_payload.side_effect = submitted
topic_actions_native.NativeActionBackend = lambda *a: backend
raise SystemExit(entry.main(sys.argv[1:]))
'''


def cli(workspace, args, *, request=None, scenario="normal"):
    harness = HARNESS.format(
        scripts=str(SCRIPTS), root=str(ROOT), workspace=str(workspace), scenario=scenario,
    )
    process = subprocess.run(
        [sys.executable, "-c", harness, "--workspace-root", str(workspace), *args],
        input=json.dumps(request) if request is not None else "",
        text=True, capture_output=True, timeout=30,
    )
    assert "private-token" not in process.stdout + process.stderr
    assert "unchanged-a" not in process.stdout + process.stderr
    lines = process.stdout.splitlines()
    assert lines and lines[-1].startswith(entry.RESULT_MARKER), process.stdout + process.stderr
    return process, json.loads(lines[-1].removeprefix(entry.RESULT_MARKER))


@pytest.mark.parametrize(("decision", "status", "writes"), [
    ("approve", "completed", 1), ("deny", "denied", 0), ("cancel", "cancelled", 0),
])
def test_fresh_process_applies_only_the_explicit_chat_decision(tmp_path, decision, status, writes):
    process, review = cli(tmp_path, ["--review"], request=REQUEST)
    assert process.returncode == 0
    assert review["status"] == "review_ready"
    assert review["writeStatus"] == "not_attempted"
    assert "## Review topic changes" in review["userMessage"]
    assert review["review"]["baseline"]["status"] == "capture_before_first_write"
    assert not (tmp_path / "submissions.txt").exists()
    process, result = cli(
        tmp_path, ["--apply-review", review["reviewId"], "--decision", decision],
    )
    assert process.returncode == 0
    assert result["status"] == status
    submissions = tmp_path / "submissions.txt"
    assert (len(submissions.read_text().splitlines()) if submissions.exists() else 0) == writes
    if writes:
        assert result["writeStatus"] == "submitted"
        assert result["completed"] is True
        assert len(submissions.read_text().splitlines()) == 1
    process, replay = cli(
        tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"],
    )
    assert process.returncode == 1
    assert replay["reason"] == "review_unavailable"
    assert replay["writeStatus"] == "not_attempted"
    assert (len(submissions.read_text().splitlines()) if submissions.exists() else 0) == writes


@pytest.mark.parametrize("scenario", ["drift", "account"])
def test_changed_evidence_or_account_invalidates_cross_process_approval(tmp_path, scenario):
    _, review = cli(tmp_path, ["--review"], request=REQUEST)
    _, result = cli(
        tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], scenario=scenario,
    )
    assert result["status"] == "review_required"
    assert result["blockers"] == ["evidence_changed"]
    assert not (tmp_path / "submissions.txt").exists()


def test_noop_still_requires_a_review_and_explicit_approval(tmp_path):
    _, review = cli(tmp_path, ["--review"], request=REQUEST, scenario="noop")
    assert review["status"] == "review_ready"
    assert "No change" in review["userMessage"]
    _, result = cli(
        tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], scenario="noop",
    )
    assert result["status"] == "already_correct"
    assert result["completed"]
    assert not (tmp_path / "submissions.txt").exists()


def test_original_state_restore_uses_the_same_chat_review_and_apply_flow(tmp_path):
    _, review = cli(tmp_path, ["--review"], request=REQUEST)
    _, disabled = cli(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"])
    assert disabled["completed"]
    restore = {**REQUEST, "action": "restore", "setKeys": [], "initializeBaseline": False}
    _, review = cli(tmp_path, ["--review"], request=restore, scenario="restore")
    assert review["status"] == "review_ready"
    assert review["review"]["baseline"]["status"] == "saved_original"
    _, restored = cli(
        tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], scenario="restore",
    )
    assert restored["completed"]
    assert restored["status"] == "completed"
    assert len((tmp_path / "submissions.txt").read_text().splitlines()) == 2


def test_uncertain_write_consumes_review_and_cannot_replay(tmp_path):
    _, review = cli(tmp_path, ["--review"], request=REQUEST)
    _, result = cli(
        tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], scenario="failure",
    )
    assert result["writeStatus"] == "submitted"
    assert not result["completed"]
    _, replay = cli(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"])
    assert replay["reason"] == "review_unavailable"
    assert (tmp_path / "submissions.txt").read_text().splitlines() == ["submitted"]


def test_expired_review_cannot_authenticate_or_execute(tmp_path, monkeypatch):
    store = TopicReviewStore(tmp_path, clock=lambda: 0, monotonic=lambda: 0)
    review = store.create(REQUEST, "a" * 64)
    monkeypatch.setattr(entry, "run_topic_actions", lambda *a, **k: pytest.fail("No execution allowed"))
    result = entry.apply_topic_review(review["reviewId"], "approve", workspace_root=tmp_path)
    assert result["status"] == "review_required"
    assert result["reason"] == "approval_expired"
    assert result["writeStatus"] == "not_attempted"


def test_review_preparation_has_no_write_scope_and_no_baseline_mutation(tmp_path, monkeypatch):
    from agentbuilder import DEFAULT_API_VERSION, derive_environment_host

    calls = []
    backend = SyntheticBackend([operation_evidence({"a": "On", "shared": "On"})])
    monkeypatch.setattr(entry, "_workspace_target", lambda *a, **k: {
        "ring": "test", "api_version": DEFAULT_API_VERSION,
        "host": derive_environment_host(TARGET.environment_id, "test", resolver=lambda *a: None),
    })
    def authenticate(*args, **kwargs):
        calls.append(kwargs)
        return "private-token", TARGET.tenant_id, "synthetic-account"
    monkeypatch.setattr(entry, "authenticate_flightcheck", authenticate)
    def adapter(*args):
        assert args[-1].read_only
        return backend
    monkeypatch.setattr("topic_actions_native.NativeActionBackend", adapter)
    review = entry.review_topic_actions(REQUEST, workspace_root=tmp_path)
    assert review["status"] == "review_ready"
    assert calls[0]["allow_write"] is False
    assert not backend.submissions
    assert len(list((tmp_path / ".local" / "topic-actions").glob("*.sqlite3"))) == 1
    assert (tmp_path / ".local" / "topic-actions" / "reviews.sqlite3").exists()


@pytest.mark.parametrize("decision", ["yes", "", None])
def test_ambiguous_decision_consumes_review_without_auth_or_write(tmp_path, decision, monkeypatch):
    store = TopicReviewStore(tmp_path)
    review = store.create(REQUEST, "a" * 64)
    monkeypatch.setattr(entry, "run_topic_actions", lambda *a, **k: pytest.fail("No execution allowed"))
    result = entry.apply_topic_review(review["reviewId"], decision, workspace_root=tmp_path)
    assert result["reason"] == "explicit_approval_required"
    assert result["writeStatus"] == "not_attempted"
    with pytest.raises(TopicReviewError, match="fresh"):
        store.consume(review["reviewId"])


@pytest.mark.parametrize(("wall", "mono"), [(1300, 40), (1000, 340), (999, 40), (1000, 39)])
def test_expiry_and_clock_rollback_fail_closed_and_consume_review(tmp_path, wall, mono):
    clocks = [1000, 40]
    store = TopicReviewStore(tmp_path, clock=lambda: clocks[0], monotonic=lambda: clocks[1])
    review = store.create(REQUEST, "a" * 64)
    clocks[:] = wall, mono
    with pytest.raises(TopicReviewError) as error:
        store.consume(review["reviewId"])
    assert error.value.reason == "approval_expired"
    with pytest.raises(TopicReviewError) as error:
        store.consume(review["reviewId"])
    assert error.value.reason == "review_unavailable"


def test_pending_store_never_persists_context_components_or_approval(tmp_path):
    store = TopicReviewStore(tmp_path)
    request = {**REQUEST, "entry": "caller", "callerContext": {"private": "do-not-persist"}}
    review = store.create(request, "a" * 64)
    with sqlite3.connect(store.path) as connection:
        payload = connection.execute("SELECT payload FROM pending_reviews").fetchone()[0]
    assert "callerContext" not in payload and "do-not-persist" not in payload
    assert "approve" not in payload and "dialog" not in payload and "token" not in payload
    assert store.consume(review["reviewId"])["request"]["entry"] == "direct"


def test_only_one_concurrent_process_can_consume_a_review(tmp_path):
    store = TopicReviewStore(tmp_path)
    review = store.create(REQUEST, "a" * 64)
    command = (
        f"import sys; sys.path.insert(0, {str(SCRIPTS)!r}); from pathlib import Path; "
        "from topic_actions_approval import TopicReviewStore; "
        f"TopicReviewStore(Path({str(tmp_path)!r})).consume({review['reviewId']!r})"
    )
    def consume(_):
        return subprocess.run([sys.executable, "-c", command], capture_output=True, timeout=20).returncode
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(consume, range(2)))
    assert results.count(0) == 1


def test_corrupt_pending_review_is_consumed_without_execution(tmp_path):
    store = TopicReviewStore(tmp_path)
    review = store.create(REQUEST, "a" * 64)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE pending_reviews SET payload='{}'")
    result = entry.apply_topic_review(review["reviewId"], "approve", workspace_root=tmp_path)
    assert result["reason"] == "review_invalid"
    assert result["writeStatus"] == "not_attempted"
    with pytest.raises(TopicReviewError):
        store.consume(review["reviewId"])


@pytest.mark.parametrize("change", ["account", "body", "state", "membership"])
def test_pending_binding_covers_complete_evidence_not_only_visible_plan(change):
    before = operation_evidence({"a": "On", "shared": "On"})
    review = TopicActionSession(SyntheticBackend([before]), "disable").run(None, review_only=True)
    fresh = deepcopy(before)
    if change == "account":
        fresh = replace(fresh, account_id="another-account")
    elif change == "body":
        fresh.body["botComponentChanges"][-1]["component"]["dialog"]["private"] = "edit"
    elif change == "state":
        fresh = operation_evidence({"a": "Off", "shared": "On"})
    else:
        fresh = operation_evidence({"a": "On", "shared": "On"}, selected=("alpha", "beta"))
    backend = SyntheticBackend([fresh])
    result = TopicActionSession(backend, "disable").run(
        lambda _: pytest.fail("Changed review cannot approve"), approved_binding=review["_reviewBinding"],
    )
    assert result["status"] == "review_required"
    assert result["blockers"] == ["evidence_changed"]
    assert not backend.submissions


def test_original_deadline_is_not_reset_during_authentication_or_discovery():
    before = operation_evidence({"a": "On", "shared": "On"})
    review = TopicActionSession(SyntheticBackend([before]), "disable").run(None, review_only=True)
    backend = SyntheticBackend([before])
    result = TopicActionSession(backend, "disable", clock=lambda: 301).run(
        lambda _: "approve", approved_binding=review["_reviewBinding"], approval_deadline=300,
    )
    assert result["blockers"] == ["approval_expired"]
    assert not backend.submissions
