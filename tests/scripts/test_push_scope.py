# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the --only / --only-from scoping added to scripts/push.py.

Pure-logic, no network. The most important guard here is
``update_baseline_scoped``: a scoped push must refresh ONLY the pushed files'
baseline entries. If it refreshed the whole baseline it would silently mark
unpushed working-tree changes as "pushed", so the next /push would never
retry them — a correctness bug.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import push


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


class TestMatchesOnly:
    def test_empty_globs_matches_everything(self):
        assert push.matches_only("anything/at/all.yml", []) is True

    def test_exact_path(self):
        assert push.matches_only("topics/A.mcs.yml", ["topics/A.mcs.yml"])
        assert not push.matches_only("topics/B.mcs.yml", ["topics/A.mcs.yml"])

    def test_wildcard(self):
        assert push.matches_only("topics/A.mcs.yml", ["topics/*.mcs.yml"])
        assert not push.matches_only(
            "workflows/f/workflow.json", ["topics/*.mcs.yml"])

    def test_backslash_path_normalised(self):
        assert push.matches_only("topics\\A.mcs.yml", ["topics/A.mcs.yml"])


class TestUpdateBaselineScoped:
    def _agent(self, tmp_path: Path) -> Path:
        agent = tmp_path / "agent"
        (agent / "topics").mkdir(parents=True)
        (agent / ".baseline" / "topics").mkdir(parents=True)
        return agent

    def test_only_scoped_file_is_refreshed(self, tmp_path: Path):
        agent = self._agent(tmp_path)
        # A: changed and IN scope -> baseline should update to new content.
        (agent / "topics" / "A.mcs.yml").write_text("new-A")
        (agent / ".baseline" / "topics" / "A.mcs.yml").write_text("old-A")
        # B: new and OUT of scope -> baseline must NOT gain B.
        (agent / "topics" / "B.mcs.yml").write_text("new-B")

        push.update_baseline_scoped(str(agent), ["topics/A.mcs.yml"])

        assert (agent / ".baseline" / "topics" / "A.mcs.yml").read_text() == "new-A"
        assert not (agent / ".baseline" / "topics" / "B.mcs.yml").exists()

    def test_template_config_drags_meta_companion(self, tmp_path: Path):
        agent = self._agent(tmp_path)
        (agent / "template-configs").mkdir()
        (agent / "template-configs" / "X.xml").write_text("<x/>")
        (agent / "template-configs" / "X.meta.json").write_text("{}")

        push.update_baseline_scoped(str(agent), ["template-configs/X.xml"])

        b = agent / ".baseline" / "template-configs"
        assert (b / "X.xml").read_text() == "<x/>"
        assert (b / "X.meta.json").read_text() == "{}"

    def test_scoped_delete_removes_from_baseline(self, tmp_path: Path):
        agent = self._agent(tmp_path)
        # C exists only in baseline (deleted from working) and is in scope.
        (agent / ".baseline" / "topics" / "C.mcs.yml").write_text("old-C")
        # D exists only in baseline but is OUT of scope -> must remain.
        (agent / ".baseline" / "topics" / "D.mcs.yml").write_text("old-D")

        push.update_baseline_scoped(str(agent), ["topics/C.mcs.yml"])

        assert not (agent / ".baseline" / "topics" / "C.mcs.yml").exists()
        assert (agent / ".baseline" / "topics" / "D.mcs.yml").exists()


class _FakeResp:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeHTTPError(Exception):
    """Mimics requests.HTTPError: carries a .response with a status_code."""

    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.response = _FakeResp(status_code)


class _FakeAuth:
    def __init__(self):
        self.token = "tok"

    def refresh(self):
        self.token = "tok2"
        return self.token


class TestVerifyBotExists:
    """Pre-flight guard: a stale botId must fail fast with the real cause,
    not the misleading "solution may not be deployed" 404 the friendly error
    layer would otherwise emit for every component."""

    def test_missing_bot_exits_with_actionable_message(self, monkeypatch, capsys):
        def boom(env_url, token, path, params=None):
            raise _FakeHTTPError(404)

        monkeypatch.setattr(push, "dataverse_get", boom)
        with pytest.raises(SystemExit) as exc:
            push._verify_bot_exists(
                _FakeAuth(), "https://x.crm.dynamics.com", "bad-bot")
        assert exc.value.code == 2
        out = capsys.readouterr().out
        assert "does not exist in this environment" in out
        assert "/setup" in out
        assert "bad-bot" in out

    def test_existing_bot_passes_and_targets_right_path(self, monkeypatch):
        seen = {}

        def ok(env_url, token, path, params=None):
            seen["path"] = path
            return {"botid": "good-bot"}

        monkeypatch.setattr(push, "dataverse_get", ok)
        push._verify_bot_exists(
            _FakeAuth(), "https://x.crm.dynamics.com", "good-bot")
        assert seen["path"] == "bots(good-bot)"

    def test_non_404_error_propagates(self, monkeypatch):
        def boom(env_url, token, path, params=None):
            raise _FakeHTTPError(500)

        monkeypatch.setattr(push, "dataverse_get", boom)
        with pytest.raises(_FakeHTTPError):
            push._verify_bot_exists(
                _FakeAuth(), "https://x.crm.dynamics.com", "any")
