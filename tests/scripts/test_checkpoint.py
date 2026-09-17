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

    with pytest.raises(ValueError, match="escapes checkpoint"):
        checkpoint.cmd_revert_reason(
            str(agent_dir),
            "before Workday redirect",
            only="../outside.yml",
        )


def test_revert_reason_only_fails_when_pattern_matches_nothing(tmp_path) -> None:
    agent_dir = tmp_path / "agent"
    _write_agent_file(agent_dir, "before")
    checkpoint.create_checkpoint(str(agent_dir), "before Workday redirect")

    with pytest.raises(ValueError, match="matched no paths"):
        checkpoint.cmd_revert_reason(
            str(agent_dir),
            "before Workday redirect",
            only="topics/missing.yml",
        )
