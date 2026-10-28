# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only pending inspection and captured-content acknowledgement."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import push
import topic_authoring
import workspace_state
from unittest.mock import Mock


class TestParseOnlyGlobs:
    def test_repeated_only_flags(self):
        argv = ["--only", "topics/A.mcs.yml", "--only", "topics/B.mcs.yml"]
        assert push.parse_only_globs(argv) == [
            "topics/A.mcs.yml", "topics/B.mcs.yml"]

    def test_equals_form(self):
        assert push.parse_only_globs(["--only=topics/*.mcs.yml"]) == [
            "topics/*.mcs.yml"]

    def test_backslashes_normalised(self):
        assert push.parse_only_globs(["--only", "topics\\A.mcs.yml"]) == [
            "topics/A.mcs.yml"]

    def test_no_flags_is_empty(self):
        assert push.parse_only_globs(["--dry-run", "--yes"]) == []

    def test_only_from_file(self, tmp_path: Path):
        manifest = tmp_path / "m.txt"
        manifest.write_text(
            "# a comment\n"
            "topics/A.mcs.yml\n"
            "\n"
            "template-configs\\X.xml\n"
        )
        globs = push.parse_only_globs(["--only-from", str(manifest)])
        assert globs == ["topics/A.mcs.yml", "template-configs/X.xml"]

    def test_only_from_equals_form(self, tmp_path: Path):
        # The `--only-from=FILE` equals form must resolve the same manifest
        # as the space-separated form.
        manifest = tmp_path / "m.txt"
        manifest.write_text("topics/A.mcs.yml\n")
        assert push.parse_only_globs([f"--only-from={manifest}"]) == [
            "topics/A.mcs.yml"]

    def test_mixed_only_and_only_from(self, tmp_path: Path):
        # --only globs and --only-from manifest entries accumulate together.
        manifest = tmp_path / "m.txt"
        manifest.write_text("topics/B.mcs.yml\n")
        globs = push.parse_only_globs(
            ["--only", "topics/A.mcs.yml", "--only-from", str(manifest)])
        assert globs == ["topics/A.mcs.yml", "topics/B.mcs.yml"]


class TestMatchesOnly:
    def test_empty_globs_matches_everything(self):
        assert workspace_state.matches_only("anything/at/all.yml", []) is True

    def test_exact_path(self):
        assert workspace_state.matches_only("topics/A.mcs.yml", ["topics/A.mcs.yml"])
        assert not workspace_state.matches_only("topics/B.mcs.yml", ["topics/A.mcs.yml"])

    def test_wildcard(self):
        assert workspace_state.matches_only("topics/A.mcs.yml", ["topics/*.mcs.yml"])
        assert not workspace_state.matches_only(
            "workflows/f/workflow.json", ["topics/*.mcs.yml"])

    def test_backslash_path_normalised(self):
        assert workspace_state.matches_only("topics\\A.mcs.yml", ["topics/A.mcs.yml"])


def _topic_workspace(root):
    (root / ".baseline" / "topics").mkdir(parents=True)
    (root / "topics").mkdir()
    (root / ".baseline" / "topics" / "A.mcs.yml").write_text("old", encoding="utf-8")
    (root / "topics" / "A.mcs.yml").write_text("submitted", encoding="utf-8")
    return root


def test_pending_inspection_neither_authenticates_nor_acknowledges(tmp_path, monkeypatch):
    root = _topic_workspace(tmp_path / "agent")
    (root / "topics" / "B.mcs.yml").write_text("new", encoding="utf-8")
    (root / ".component-map.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        push.MinimalBotEvaluationClient, "from_config",
        lambda config: pytest.fail("Local inspection must not create a remote client."),
    )
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    result = push.main(["--dry-run"], config={"agent": {"folder": str(root)}})
    assert result["changes"] == {
        "modified": ["topics/A.mcs.yml"], "new": ["topics/B.mcs.yml"], "deleted": [],
    }
    assert result["remoteVerified"] is False
    assert {path: path.read_bytes() for path in before} == before


def test_pending_inspection_does_not_hide_unreadable_directories(tmp_path, monkeypatch):
    root = _topic_workspace(tmp_path / "agent")
    cause = PermissionError("A workspace directory cannot be read")

    def unreadable(path, *, onerror):
        onerror(cause)
        return iter(())

    monkeypatch.setattr(workspace_state.os, "walk", unreadable)
    with pytest.raises(PermissionError) as error:
        workspace_state.inspect_pending_changes(root)
    assert error.value is cause


def test_topic_save_acknowledges_captured_content_not_concurrent_disk_edit(tmp_path):
    root = _topic_workspace(tmp_path / "agent")
    updates = [{
        "path": "topics/A.mcs.yml", "submittedYaml": "submitted",
        "componentId": "topic-a", "schemaName": "agent.topic.A",
        "expectedDialog": {"old": True}, "dialog": {"submitted": True},
    }]
    client = Mock()

    def save(selected, **kwargs):
        (root / "topics" / "A.mcs.yml").write_text("later edit", encoding="utf-8")
        return {"verifiedComponents": 1, "components": [{"id": "topic-a"}]}

    client.update_dialog_components.side_effect = save
    result = topic_authoring.save_workspace_topic_updates(
        client, root, updates, retry_on_conflict=False,
    )
    client.update_dialog_components.assert_called_once_with(updates, _retry_on_conflict=False)
    assert result["verifiedComponents"] == 1
    assert (root / ".baseline" / "topics" / "A.mcs.yml").read_text() == "submitted"
    assert (root / "topics" / "A.mcs.yml").read_text() == "later edit"
    assert workspace_state.inspect_pending_changes(root)["modified"] == ["topics/A.mcs.yml"]


def test_local_ack_failure_keeps_known_remote_result_and_cause(tmp_path, monkeypatch):
    root = _topic_workspace(tmp_path / "agent")
    client = Mock()
    known = {"verifiedComponents": 1, "components": [{"id": "topic-a"}]}
    client.update_dialog_components.return_value = known
    cause = PermissionError("Baseline is locked")
    monkeypatch.setattr(topic_authoring, "acknowledge_files", Mock(side_effect=cause))
    with pytest.raises(topic_authoring.ComponentEditError) as error:
        topic_authoring.save_workspace_topic_updates(client, root, [{
            "path": "topics/A.mcs.yml", "submittedYaml": "submitted", "dialog": {},
        }])
    assert error.value.__cause__ is cause
    assert error.value.evidence["remoteResult"] == known
    assert error.value.evidence["acknowledgementComplete"] is False
    client.update_dialog_components.assert_called_once()


@pytest.mark.parametrize(
    "relative",
    ["../outside", r"C:\outside", "C:outside", "/outside", "topics/A:stream",
     "topics/../outside", r"\\host\share\outside"],
)
def test_captured_acknowledgement_rejects_escape_before_any_write(tmp_path, relative):
    root = _topic_workspace(tmp_path / "agent")
    with pytest.raises(ValueError, match="Invalid acknowledged"):
        workspace_state.acknowledge_files(root, {
            "topics/A.mcs.yml": "submitted", relative: "unsafe",
        })
    assert (root / ".baseline" / "topics" / "A.mcs.yml").read_text() == "old"


@pytest.mark.parametrize("flag", ["--repair", "--force-delete"])
def test_retired_write_flags_stop_before_configuration_or_auth(monkeypatch, flag):
    monkeypatch.setattr(push, "load_config", lambda: pytest.fail("No configuration needed"))
    with pytest.raises(SystemExit) as stopped:
        push.main([flag, "--yes"])
    assert stopped.value.code == 2


def test_scoped_cli_retains_known_remote_result_when_acknowledgement_fails(
    tmp_path, monkeypatch, capsys,
):
    root = _topic_workspace(tmp_path / "agent")
    client = Mock()
    monkeypatch.setattr(push.MinimalBotEvaluationClient, "from_config", lambda config: client)
    monkeypatch.setattr(push, "_minimalbot_topic_update_plan", lambda *args, **kwargs: [{
        "displayName": "A", "path": "topics/A.mcs.yml",
        "dialog": {}, "submittedYaml": "submitted",
    }])
    known = {"verifiedComponents": 1, "verified": True, "writeAttempted": True}
    client.update_dialog_components.return_value = known
    cause = PermissionError("Baseline is locked")
    monkeypatch.setattr(topic_authoring, "acknowledge_files", Mock(side_effect=cause))
    with pytest.raises(SystemExit) as stopped:
        push._minimalbot_push({"agent": {"folder": str(root)}}, auto_yes=True)
    observed = json.loads(capsys.readouterr().err)
    assert observed["evidence"]["remoteResult"] == known
    assert observed["errors"][-1]["type"] == "PermissionError"
    assert stopped.value.__cause__.__cause__ is cause


@pytest.mark.parametrize("scope", ["topics/A.mcs.yml", "evaluations/set/*", "workflows/*"])
def test_dataverse_push_has_no_write_fallback(tmp_path, monkeypatch, scope):
    monkeypatch.setattr(
        push.MinimalBotEvaluationClient, "from_config",
        lambda config: pytest.fail("No remote client may be constructed"),
    )
    config = {
        "dataverseEndpoint": "https://example.crm.dynamics.com",
        "agent": {"folder": str(tmp_path)},
    }
    with pytest.raises(SystemExit) as stopped:
        push.main(["--only", scope, "--yes"], config=config)
    assert stopped.value.code == 2
