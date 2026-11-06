# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path

import pytest

import reset_local_workspace as reset


def _create_workspace(kit_root: Path) -> None:
    (kit_root / ".local" / "setup").mkdir(parents=True)
    (kit_root / ".local" / "setup" / "config.json").write_text(
        '{"agent":"existing"}\n',
        encoding="utf-8",
    )
    (kit_root / ".local" / "config.json").write_text(
        '{"agent":"existing"}\n',
        encoding="utf-8",
    )
    (kit_root / ".local" / ".agentbuilder_token_cache.bin").write_bytes(b"token")
    (kit_root / ".local" / "object-model").mkdir()
    (kit_root / ".local" / "object-model" / "package.bin").write_bytes(b"package")
    (kit_root / "workspace" / "agents").mkdir(parents=True)
    (kit_root / "workspace" / "agents" / ".gitkeep").write_text(
        "",
        encoding="utf-8",
    )
    agent = kit_root / "workspace" / "agents" / "existing-agent"
    agent.mkdir()
    (agent / "agent.mcs.yml").write_text("kind: Agent\n", encoding="utf-8")
    flightcheck = kit_root / "workspace" / "flightcheck"
    flightcheck.mkdir()
    (flightcheck / "results.json").write_text("{}\n", encoding="utf-8")
    evaluations = kit_root / "workspace" / "evaluations"
    evaluations.mkdir()
    (evaluations / "keep.mcs.yml").write_text("kind: EvaluationSet\n", encoding="utf-8")


def test_reset_archives_setup_agents_and_flightcheck(tmp_path: Path) -> None:
    kit_root = tmp_path / "kit"
    _create_workspace(kit_root)

    result = reset.reset_local_workspace(
        kit_root,
        timestamp_factory=lambda: "20260918T120000Z",
    )

    backup = kit_root / ".local" / "workspace-reset-backups" / "20260918T120000Z"
    assert result == {
        "outcome": "workspace-reset",
        "kitRoot": str(kit_root.resolve()),
        "backupRoot": str(backup),
        "archivedPaths": [
            ".local/setup",
            ".local/config.json",
            "workspace/flightcheck",
            "workspace/agents/existing-agent",
        ],
    }
    assert (backup / ".local" / "setup" / "config.json").is_file()
    assert (backup / ".local" / "config.json").is_file()
    assert (backup / "workspace" / "agents" / "existing-agent" / "agent.mcs.yml").is_file()
    assert (backup / "workspace" / "flightcheck" / "results.json").is_file()
    assert not (kit_root / ".local" / "setup").exists()
    assert not (kit_root / ".local" / "config.json").exists()
    assert not (kit_root / "workspace" / "agents" / "existing-agent").exists()
    assert not (kit_root / "workspace" / "flightcheck").exists()


def test_reset_preserves_caches_scaffolding_and_unrelated_workspace_files(
    tmp_path: Path,
) -> None:
    kit_root = tmp_path / "kit"
    _create_workspace(kit_root)

    reset.reset_local_workspace(
        kit_root,
        timestamp_factory=lambda: "20260918T120000Z",
    )

    assert (kit_root / ".local" / ".agentbuilder_token_cache.bin").read_bytes() == b"token"
    assert (kit_root / ".local" / "object-model" / "package.bin").read_bytes() == b"package"
    assert (kit_root / "workspace" / "agents" / ".gitkeep").is_file()
    assert (kit_root / "workspace" / "evaluations" / "keep.mcs.yml").is_file()


def test_reset_uses_unique_backup_path_for_same_timestamp(tmp_path: Path) -> None:
    kit_root = tmp_path / "kit"
    _create_workspace(kit_root)
    existing = (
        kit_root
        / ".local"
        / "workspace-reset-backups"
        / "20260918T120000Z"
    )
    existing.mkdir(parents=True)

    result = reset.reset_local_workspace(
        kit_root,
        timestamp_factory=lambda: "20260918T120000Z",
    )

    assert result["backupRoot"].endswith("20260918T120000Z-2")


def test_reset_rejects_backup_root_outside_kit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit_root = tmp_path / "kit"
    _create_workspace(kit_root)
    monkeypatch.setattr(reset, "BACKUP_ROOT", Path("..") / "outside")

    with pytest.raises(
        reset.LocalWorkspaceResetError,
        match="Backup root is outside",
    ):
        reset.reset_local_workspace(kit_root)

    assert (kit_root / ".local" / "setup" / "config.json").is_file()
    assert (kit_root / "workspace" / "agents" / "existing-agent").is_dir()


def test_reset_reports_nothing_to_reset(tmp_path: Path) -> None:
    kit_root = tmp_path / "kit"
    (kit_root / "workspace" / "agents").mkdir(parents=True)
    (kit_root / "workspace" / "agents" / ".gitkeep").write_text(
        "",
        encoding="utf-8",
    )

    result = reset.reset_local_workspace(kit_root)

    assert result == {
        "outcome": "nothing-to-reset",
        "kitRoot": str(kit_root.resolve()),
        "backupRoot": None,
        "archivedPaths": [],
    }


def test_reset_rolls_back_paths_when_archive_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kit_root = tmp_path / "kit"
    _create_workspace(kit_root)
    real_move = reset.shutil.move
    move_count = 0

    def fail_second_move(source: str, destination: str) -> str:
        nonlocal move_count
        move_count += 1
        if move_count == 2:
            raise OSError("archive unavailable")
        return real_move(source, destination)

    monkeypatch.setattr(reset.shutil, "move", fail_second_move)

    with pytest.raises(
        reset.LocalWorkspaceResetError,
        match="archive unavailable",
    ):
        reset.reset_local_workspace(
            kit_root,
            timestamp_factory=lambda: "20260918T120000Z",
        )

    assert (kit_root / ".local" / "setup" / "config.json").is_file()
    assert (kit_root / ".local" / "config.json").is_file()
    assert (kit_root / "workspace" / "agents" / "existing-agent").is_dir()
    assert (kit_root / "workspace" / "flightcheck").is_dir()


def test_main_requires_explicit_confirmation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = reset.main(["--kit-root", str(tmp_path)])

    assert result == 2
    assert "requires --confirm-reset" in capsys.readouterr().err


def test_main_emits_reset_result(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    kit_root = tmp_path / "kit"
    _create_workspace(kit_root)

    result = reset.main(
        [
            "--kit-root",
            str(kit_root),
            "--confirm-reset",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out.strip()
    assert output.startswith(f"{reset.RESULT_MARKER}:")
    payload = json.loads(output.removeprefix(f"{reset.RESULT_MARKER}:"))
    assert payload["outcome"] == "workspace-reset"
    assert ".local/setup" in payload["archivedPaths"]


def test_main_emits_error_notes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_reset(_kit_root: Path) -> dict[str, object]:
        error = reset.LocalWorkspaceResetError("archive failed")
        error.add_note("Rollback failed for workspace/agents/existing-agent")
        raise error

    monkeypatch.setattr(reset, "reset_local_workspace", fail_reset)

    result = reset.main(
        [
            "--kit-root",
            str(tmp_path),
            "--confirm-reset",
        ]
    )

    assert result == 1
    assert capsys.readouterr().err.splitlines() == [
        "ERROR: LocalWorkspaceResetError: archive failed",
        "NOTE: Rollback failed for workspace/agents/existing-agent",
    ]
