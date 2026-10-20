# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path


_INSTRUCTIONS = (
    Path(__file__).resolve().parents[1] / ".github" / "copilot-instructions.md"
)


def _sections() -> tuple[str, str]:
    content = _INSTRUCTIONS.read_text(encoding="utf-8")
    boundary, separator, discovery = content.partition("## Discover Maker Kit operations")
    assert separator
    assert "## Workspace boundary" in boundary
    return " ".join(boundary.split()), " ".join(discovery.split())


def test_workspace_boundary_runs_before_catalog_discovery() -> None:
    boundary, discovery = _sections()

    assert (
        "Only show folder-selection guidance when the active workspace is positively "
        "identified as the repository root and no Maker Kit workspace folder is active."
        in boundary
    )
    assert "Only after the workspace boundary permits repo-root routing" in discovery
    assert "relative to the active repository-root workspace" in discovery


def test_open_maker_workspace_does_not_redirect_when_root_rules_are_inherited() -> None:
    boundary, _ = _sections()

    assert "reading it does not prove that the repository root is the active workspace" in boundary
    assert (
        "If the Maker Kit folder or one of its descendants is the active workspace, "
        "do not redirect."
        in boundary
    )
    assert "If a multi-root workspace includes the Maker Kit folder, do not redirect." in boundary
    assert "Follow that workspace's local Copilot instructions and prompt catalog" in boundary
    assert "is not evidence that the user opened the wrong workspace" in boundary


def test_uncertain_workspace_and_redirect_reports_do_not_repeat_folder_guidance() -> None:
    boundary, _ = _sections()

    assert (
        "Prefer the active VS Code workspace-folder information over a shell session's "
        "working directory or the Git repository root."
        in boundary
    )
    assert (
        "If the user confirms that the Maker Kit workspace is already open, do not "
        "repeat folder-selection guidance."
        in boundary
    )
    assert (
        "If workspace evidence conflicts or is unavailable, investigate the mismatch"
        in boundary
    )
    assert (
        "Reports about incorrect redirects and requests to inspect or edit skill source "
        "are development requests, not Maker Kit operation invocations."
        in boundary
    )
