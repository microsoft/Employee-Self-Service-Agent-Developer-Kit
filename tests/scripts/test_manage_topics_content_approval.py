# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Cross-process review/apply of content-backed add with synthetic evidence only."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

import manage_topics as entry
from tests.scripts.test_manage_topics_approval import REQUEST


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "solutions" / "ess-maker-skills" / "scripts"

# Each invocation imports the actual entry/controller in a new interpreter.
HARNESS = r'''
import json, sys
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, {scripts!r})
sys.path.insert(0, {root!r})
import manage_topics as entry
import manage_topics_native
from agentbuilder import derive_environment_host
from tests.scripts.test_manage_topics_runtime import TARGET, dev_native_backend
from tests.scripts.test_manage_topics_content_runtime import content_native_backend, converted_topic_content

scenario = {scenario!r}
root = Path({workspace!r})
entry._workspace_target = lambda *a, **k: {{
    "ring": "test",
    "host": derive_environment_host(TARGET.environment_id, "test", resolver=lambda *a: None),
    "api_version": "2022-03-01-preview",
}}
entry.authenticate_flightcheck = lambda *a, **k: ("private-token", TARGET.tenant_id, "synthetic-maker")
backend = dev_native_backend(before={{"a": "On", "shared": "On"}}, after={{}})
if scenario.startswith("add"):
    import agentbuilder_object_model
    agentbuilder_object_model.yaml_to_object_models = converted_topic_content
    backend, body = content_native_backend()
    if scenario == "add-drift":
        body["changeToken"] = "changed"
original_submit = backend.components.submit_state_payload.side_effect
if scenario == "catalog-unreadable":
    import manage_topics_catalog
    from manage_topics_discovery import DiscoveryError
    def unavailable():
        raise DiscoveryError("content_unreadable", "Content files cannot be read.")
    manage_topics_catalog.load_catalog = unavailable
if scenario == "unreadable":
    backend.components.read_components.side_effect = AssertionError("Live read was forbidden")
def submitted(*args):
    with (root / "submissions.txt").open("a") as f:
        f.write("submitted\n")
    if original_submit:
        original_submit(*args)
backend.components.submit_state_payload.side_effect = submitted
manage_topics_native.NativeActionBackend = lambda *a: backend
backend.client.session = Mock()
entry.AgentBuilderClient = lambda *a, **k: backend.client
raise SystemExit(entry.main(sys.argv[1:]))
'''


def cli(workspace, args, *, request=None, scenario="add"):
    harness = HARNESS.format(
        scripts=str(SCRIPTS), root=str(ROOT), workspace=str(workspace), scenario=scenario,
    )
    process = subprocess.run(
        [sys.executable, "-c", harness, "--workspace-root", str(workspace), *args],
        input=json.dumps(request) if request is not None else "",
        text=True, capture_output=True, timeout=30,
    )
    assert "private-token" not in process.stdout + process.stderr
    lines = process.stdout.splitlines()
    assert lines and lines[-1].startswith(entry.RESULT_MARKER), process.stdout + process.stderr
    return process, json.loads(lines[-1].removeprefix(entry.RESULT_MARKER))


@pytest.mark.parametrize("mode", [[], ["--preview"], ["--review"]])
def test_content_catalog_failure_returns_a_structured_no_change_result(tmp_path, mode):
    request = {**REQUEST, "action": "add", "setKeys": ["diagnostics"]}
    _, result = cli(tmp_path, mode, request=request, scenario="catalog-unreadable")
    assert result["status"] == "blocked"
    assert result["reason"] == "content_unreadable"
    assert "No topics were changed" in result["userMessage"]


def test_add_changed_evidence_requires_a_new_cross_process_review(tmp_path):
    request = {**REQUEST, "action": "add", "setKeys": ["diagnostics"]}
    _, review = cli(tmp_path, ["--review"], request=request, scenario="add")
    _, result = cli(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], scenario="add-drift")
    assert result["status"] == "review_required"
    assert "evidence_changed" in result["blockers"]
    assert "No topics were changed" in result["userMessage"]
    assert not (tmp_path / "submissions.txt").exists()


@pytest.mark.parametrize("mode", [[], ["--preview"], ["--review"]])
@pytest.mark.parametrize("keys", [["workday-da-hr"], ["diagnostics", "workday-da-hr"], ["unknown"]])
def test_add_without_shipped_content_is_refused_before_any_live_read(tmp_path, keys, mode):
    request = {**REQUEST, "action": "add", "setKeys": keys}
    _, result = cli(tmp_path, mode, request=request, scenario="unreadable")
    assert result["reason"].startswith("content_required")
    assert "No topics were changed" in result["userMessage"]
    assert not (tmp_path / "submissions.txt").exists()


@pytest.mark.parametrize("decision,status", [("approve", "completed"), ("deny", "denied"), ("cancel", "cancelled")])
def test_add_cli_review_is_single_use_and_only_approval_writes(tmp_path, decision, status):
    request = {**REQUEST, "action": "add", "setKeys": ["diagnostics"]}
    process, review = cli(tmp_path, ["--review"], request=request)
    assert process.returncode == 0 and review["status"] == "review_ready"
    assert "Add" in review["approvalQuestion"]["question"]
    assert not (tmp_path / "submissions.txt").exists()
    process, result = cli(tmp_path, ["--apply-review", review["reviewId"], "--decision", decision])
    assert process.returncode == 0 and result["status"] == status
    assert (tmp_path / "submissions.txt").exists() is (decision == "approve")
    assert ("draft" in result["userMessage"]) is (decision == "approve")
    if decision != "approve":
        assert "No topics were changed" in result["userMessage"]
    _, replay = cli(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"])
    assert replay["reason"] == "review_unavailable"
    assert replay["writeStatus"] == "not_attempted"


@pytest.mark.parametrize("decision", ["approve", "deny", "cancel"])
def test_add_review_copy_distinguishes_this_decision_from_a_consumed_review(tmp_path, decision):
    request = {**REQUEST, "action": "add", "setKeys": ["diagnostics"]}
    _, review = cli(tmp_path, ["--review"], request=request)
    args = ["--apply-review", review["reviewId"], "--decision", decision]
    _, result = cli(tmp_path, args)
    if decision == "approve":
        note = "The change is in the draft. Microsoft 365 Copilot sees it after you publish in Copilot Studio."
        assert result["message"] == f"The requested topic additions were verified. {note}"
        assert result["userMessage"].endswith("\n\n" + note)
        assert result["userMessage"].count(note) == 1
        assert "No topics were changed." not in result["userMessage"]
    else:
        text = "Not approved." if decision == "deny" else "Canceled."
        assert result["message"] == result["userMessage"] == text + " No topics were changed."
    _, replay = cli(tmp_path, args)
    assert replay["userMessage"] == (
        "This review is unavailable or has already been used.\n\n"
        "**NEXT STEPS**\n\nMake a new request for a fresh review and approval."
    )


@pytest.mark.parametrize("mode", [[], ["--preview"], ["--review"]])
def test_remove_is_not_an_action_and_is_refused_before_any_live_read(tmp_path, mode):
    # Deleting components stays a maker action in Copilot Studio; this command only inserts.
    request = {**REQUEST, "action": "remove", "setKeys": ["diagnostics"]}
    _, result = cli(tmp_path, mode, request=request, scenario="unreadable")
    assert result["reason"] == "invalid_request"
    assert "Remove" not in result["userMessage"] and "remove" not in result["userMessage"]
    assert "No topics were changed" in result["userMessage"]
    assert not (tmp_path / "submissions.txt").exists()
