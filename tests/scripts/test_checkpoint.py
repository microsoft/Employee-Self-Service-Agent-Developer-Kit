# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json

import pytest

import checkpoint


def _write_agent_file(agent_dir, value: str) -> None:
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "topic.yml").write_text(value, encoding="utf-8")


def test_revert_reason_restores_named_checkpoint(tmp_path) -> None:
    agent_dir = tmp_path / "agent"
    _write_agent_file(agent_dir, "before")
    checkpoint.create_checkpoint(str(agent_dir), "before Workday redirect")

    _write_agent_file(agent_dir, "edited")
    checkpoint.create_checkpoint(str(agent_dir), "auto-save before push")
    _write_agent_file(agent_dir, "pushed")

    checkpoint.cmd_revert_reason(str(agent_dir), "before Workday redirect")

    assert (agent_dir / "topic.yml").read_text(encoding="utf-8") == "before"
    checkpoints_dir = agent_dir / ".checkpoints"
    reasons = []
    for meta_path in checkpoints_dir.glob("*/_meta.json"):
        reasons.append(json.loads(meta_path.read_text(encoding="utf-8"))["reason"])
    assert "auto-save before named revert" in reasons


def test_revert_reason_fails_when_checkpoint_is_missing(tmp_path) -> None:
    agent_dir = tmp_path / "agent"
    _write_agent_file(agent_dir, "current")

    with pytest.raises(SystemExit) as exc:
        checkpoint.cmd_revert_reason(str(agent_dir), "missing")

    assert exc.value.code == 1


def test_revert_reason_only_restores_matching_path(tmp_path) -> None:
    agent_dir = tmp_path / "agent"
    topic_dir = agent_dir / "topics"
    topic_dir.mkdir(parents=True)
    target = topic_dir / "user-context-setup.mcs.yml"
    unrelated = topic_dir / "other.mcs.yml"
    target.write_text("before", encoding="utf-8")
    unrelated.write_text("before-unrelated", encoding="utf-8")
    checkpoint.create_checkpoint(str(agent_dir), "before Workday redirect")

    target.write_text("edited", encoding="utf-8")
    unrelated.write_text("keep-this", encoding="utf-8")

    checkpoint.cmd_revert_reason(
        str(agent_dir),
        "before Workday redirect",
        only="topics/user-context-setup.mcs.yml",
    )

    assert target.read_text(encoding="utf-8") == "before"
    assert unrelated.read_text(encoding="utf-8") == "keep-this"


def test_revert_reason_only_rejects_parent_traversal(tmp_path) -> None:
    agent_dir = tmp_path / "agent"
    _write_agent_file(agent_dir, "before")
    checkpoint.create_checkpoint(str(agent_dir), "before Workday redirect")
    checkpoint_count = len(list((agent_dir / ".checkpoints").iterdir()))

    with pytest.raises(ValueError, match="escapes checkpoint"):
        checkpoint.cmd_revert_reason(
            str(agent_dir),
            "before Workday redirect",
            only="../outside.yml",
        )

    assert len(list((agent_dir / ".checkpoints").iterdir())) == checkpoint_count


def test_revert_reason_only_fails_when_pattern_matches_nothing(tmp_path) -> None:
    agent_dir = tmp_path / "agent"
    _write_agent_file(agent_dir, "before")
    checkpoint.create_checkpoint(str(agent_dir), "before Workday redirect")
    checkpoint_count = len(list((agent_dir / ".checkpoints").iterdir()))

    with pytest.raises(ValueError, match="matched no paths"):
        checkpoint.cmd_revert_reason(
            str(agent_dir),
            "before Workday redirect",
            only="topics/missing.yml",
        )

    assert len(list((agent_dir / ".checkpoints").iterdir())) == checkpoint_count


@pytest.mark.parametrize("pattern", [".", "topics/..", "**"])
def test_revert_reason_only_rejects_agent_root_matches(
    tmp_path, pattern
) -> None:
    agent_dir = tmp_path / "agent"
    topic_dir = agent_dir / "topics"
    topic_dir.mkdir(parents=True)
    (topic_dir / "topic.yml").write_text("before", encoding="utf-8")
    checkpoint.create_checkpoint(str(agent_dir), "before Workday redirect")
    checkpoint_count = len(list((agent_dir / ".checkpoints").iterdir()))

    with pytest.raises(
        ValueError, match="agent root|protected path"
    ):
        checkpoint.cmd_revert_reason(
            str(agent_dir),
            "before Workday redirect",
            only=pattern,
        )

    assert agent_dir.exists()
    assert len(list((agent_dir / ".checkpoints").iterdir())) == checkpoint_count


@pytest.mark.parametrize("pattern", [".checkpoints/**", ".baseline/**"])
def test_revert_reason_only_rejects_protected_recovery_paths(
    tmp_path, pattern
) -> None:
    agent_dir = tmp_path / "agent"
    _write_agent_file(agent_dir, "before")
    checkpoint.create_checkpoint(str(agent_dir), "before Workday redirect")
    baseline = agent_dir / ".baseline"
    baseline.mkdir()
    (baseline / "topic.yml").write_text("baseline", encoding="utf-8")
    checkpoint_count = len(list((agent_dir / ".checkpoints").iterdir()))

    with pytest.raises(ValueError, match="protected path"):
        checkpoint.cmd_revert_reason(
            str(agent_dir),
            "before Workday redirect",
            only=pattern,
        )

    assert (baseline / "topic.yml").read_text(encoding="utf-8") == "baseline"
    assert len(list((agent_dir / ".checkpoints").iterdir())) == checkpoint_count


def test_create_checkpoint_rejects_reparse_points(
    tmp_path, monkeypatch
) -> None:
    agent_dir = tmp_path / "agent"
    redirected = agent_dir / "redirected"
    redirected.mkdir(parents=True)
    _write_agent_file(agent_dir, "before")
    original = checkpoint._is_reparse_point
    monkeypatch.setattr(
        checkpoint,
        "_is_reparse_point",
        lambda path: str(path) == str(redirected) or original(path),
    )

    with pytest.raises(ValueError, match="reparse point"):
        checkpoint.create_checkpoint(str(agent_dir), "unsafe")

    assert not (agent_dir / ".checkpoints").exists()


def test_scoped_restore_rejects_reparse_point_target_parent(
    tmp_path, monkeypatch
) -> None:
    agent_dir = tmp_path / "agent"
    target_dir = agent_dir / "topics"
    target_dir.mkdir(parents=True)
    target = target_dir / "topic.yml"
    target.write_text("before", encoding="utf-8")
    checkpoint.create_checkpoint(str(agent_dir), "before Workday redirect")
    target.write_text("edited", encoding="utf-8")
    checkpoint_count = len(list((agent_dir / ".checkpoints").iterdir()))
    original = checkpoint._is_reparse_point
    monkeypatch.setattr(
        checkpoint,
        "_is_reparse_point",
        lambda path: str(path) == str(target_dir) or original(path),
    )

    with pytest.raises(ValueError, match="reparse point"):
        checkpoint.cmd_revert_reason(
            str(agent_dir),
            "before Workday redirect",
            only="topics/topic.yml",
        )

    assert target.read_text(encoding="utf-8") == "edited"
    assert len(list((agent_dir / ".checkpoints").iterdir())) == checkpoint_count


def test_main_reports_scoped_restore_error_without_traceback(
    tmp_path, monkeypatch, capsys
) -> None:
    agent_dir = tmp_path / "agent"
    _write_agent_file(agent_dir, "before")
    checkpoint.create_checkpoint(str(agent_dir), "before Workday redirect")
    monkeypatch.setattr(
        checkpoint,
        "load_config",
        lambda: {"agent": {"folder": str(agent_dir)}},
    )
    monkeypatch.setattr(
        checkpoint.sys,
        "argv",
        [
            "checkpoint.py",
            "--revert-reason",
            "before Workday redirect",
            "--only",
            "topics/missing.yml",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        checkpoint.main()

    assert exc.value.code == 1
    assert 'ERROR: Restore pattern matched no paths: "topics/missing.yml"' in (
        capsys.readouterr().out
    )
