# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import create_fresh_workspace as workspace


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _create_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "--quiet")
    _git(path, "config", "user.email", "workspace-test@example.com")
    _git(path, "config", "user.name", "Workspace Test")
    (path / ".gitignore").write_text(
        "solutions/ess-maker-skills/.local/*\n"
        "!solutions/ess-maker-skills/.local/.gitkeep\n"
        "solutions/ess-maker-skills/workspace/\n",
        encoding="utf-8",
    )
    kit_root = path / workspace.KIT_SUBFOLDER
    kit_root.mkdir(parents=True)
    (kit_root / ".local").mkdir()
    (kit_root / ".local" / ".gitkeep").write_text("", encoding="utf-8")
    (kit_root / "README.md").write_text("ESS Maker Skills\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "--quiet", "-m", "test fixture")
    return kit_root


def test_create_worktree_preserves_current_workspace_state(tmp_path: Path) -> None:
    repo_root = tmp_path / "source"
    kit_root = _create_repo(repo_root)
    local_state = kit_root / ".local" / "setup" / "config.json"
    local_state.parent.mkdir(parents=True)
    local_state.write_text('{"agent":"existing"}\n', encoding="utf-8")
    destination = tmp_path / "fresh"

    result = workspace.create_worktree(kit_root, destination)

    assert result["outcome"] == "workspace-created"
    assert result["worktreeRoot"] == str(destination.resolve())
    assert result["kitRoot"] == str((destination / workspace.KIT_SUBFOLDER).resolve())
    assert result["sourceCommit"] == _git(repo_root, "rev-parse", "HEAD").stdout.strip()
    assert (destination / workspace.KIT_SUBFOLDER / "README.md").is_file()
    assert (destination / workspace.KIT_SUBFOLDER / ".local" / ".gitkeep").is_file()
    assert not (
        destination / workspace.KIT_SUBFOLDER / ".local" / "config.json"
    ).exists()
    assert not (destination / workspace.KIT_SUBFOLDER / "workspace").exists()
    assert local_state.is_file()


def test_create_worktree_rejects_dirty_source_without_creating_destination(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "source"
    kit_root = _create_repo(repo_root)
    (kit_root / "README.md").write_text("uncommitted change\n", encoding="utf-8")
    destination = tmp_path / "fresh"

    with pytest.raises(workspace.FreshWorkspaceError, match="uncommitted"):
        workspace.create_worktree(kit_root, destination)

    assert not destination.exists()


def test_create_worktree_rejects_revision_that_tracks_local_state(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "source"
    kit_root = _create_repo(repo_root)
    tracked_state = kit_root / ".local" / "config.json"
    tracked_state.write_text('{"agent":"must-not-copy"}\n', encoding="utf-8")
    _git(repo_root, "add", "--force", str(tracked_state))
    _git(repo_root, "commit", "--quiet", "-m", "track invalid local state")
    destination = tmp_path / "fresh"

    with pytest.raises(workspace.FreshWorkspaceError, match="tracks local state"):
        workspace.create_worktree(kit_root, destination)

    assert not destination.exists()


def test_create_worktree_rejects_existing_destination(tmp_path: Path) -> None:
    repo_root = tmp_path / "source"
    kit_root = _create_repo(repo_root)
    destination = tmp_path / "fresh"
    destination.mkdir()

    with pytest.raises(workspace.FreshWorkspaceError, match="already exists"):
        workspace.create_worktree(kit_root, destination)


def test_create_worktree_rejects_destination_inside_source_repo(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "source"
    kit_root = _create_repo(repo_root)
    destination = repo_root / "nested-worktree"

    with pytest.raises(workspace.FreshWorkspaceError, match="sibling folder"):
        workspace.create_worktree(kit_root, destination)

    assert not destination.exists()


def test_create_worktree_rejects_non_sibling_destination(tmp_path: Path) -> None:
    repo_root = tmp_path / "source"
    kit_root = _create_repo(repo_root)
    other_parent = tmp_path / "other-parent"
    other_parent.mkdir()
    destination = other_parent / "fresh"

    with pytest.raises(workspace.FreshWorkspaceError, match="sibling folder"):
        workspace.create_worktree(kit_root, destination)

    assert not destination.exists()


def test_open_vscode_targets_new_ess_maker_skills_folder(tmp_path: Path) -> None:
    kit_root = tmp_path / workspace.KIT_SUBFOLDER
    kit_root.mkdir(parents=True)
    commands: list[list[str]] = []

    def run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    workspace.open_vscode_workspace(
        kit_root,
        code_executable="code",
        runner=run,
    )

    assert commands == [["code", "-n", str(kit_root.resolve())]]


def test_main_emits_created_workspace_identity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = tmp_path / "source"
    kit_root = _create_repo(repo_root)
    destination = tmp_path / "fresh"

    result = workspace.main(
        [
            "--source",
            str(kit_root),
            "--destination",
            str(destination),
        ]
    )

    assert result == 0
    output = capsys.readouterr().out.strip()
    assert output.startswith(f"{workspace.RESULT_MARKER}:")
    payload = json.loads(output.removeprefix(f"{workspace.RESULT_MARKER}:"))
    assert payload["outcome"] == "workspace-created"
    assert payload["vscodeOpened"] is False
    assert payload["kitRoot"] == str(
        (destination / workspace.KIT_SUBFOLDER).resolve()
    )


def test_main_preserves_created_workspace_when_vscode_open_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "source"
    kit_root = _create_repo(repo_root)
    destination = tmp_path / "fresh"

    def fail_open(_kit_root: Path) -> None:
        raise workspace.FreshWorkspaceError("VS Code launcher unavailable")

    monkeypatch.setattr(workspace, "open_vscode_workspace", fail_open)

    result = workspace.main(
        [
            "--source",
            str(kit_root),
            "--destination",
            str(destination),
            "--open-vscode",
        ]
    )

    assert result == 2
    captured = capsys.readouterr()
    payload = json.loads(
        captured.out.strip().removeprefix(f"{workspace.RESULT_MARKER}:")
    )
    assert payload["outcome"] == "workspace-created-open-failed"
    assert payload["vscodeOpened"] is False
    assert payload["openError"] == "VS Code launcher unavailable"
    assert "ERROR: VS Code launcher unavailable" in captured.err
    assert (destination / workspace.KIT_SUBFOLDER).is_dir()
