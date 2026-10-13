# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKDAY_DA = (
    _REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "setup"
    / "workday-da"
)
_SCRIPTS = (
    _REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
)


def test_assisted_browser_is_scoped_to_native_da_workday() -> None:
    cea = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "skills"
        / "connect"
        / "workday"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    connection = (_WORKDAY_DA / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )
    validation = (_WORKDAY_DA / "verify-connection.md").read_text(
        encoding="utf-8"
    )
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(
        encoding="utf-8"
    )

    assert "workday_assisted_browser.py" not in cea
    assert "shared/assisted-browser.md" in entra
    assert "shared/assisted-browser.md" in connection
    assert "shared/assisted-browser.md" in validation


def test_all_native_da_browser_boundaries_use_named_surfaces() -> None:
    connection = (_WORKDAY_DA / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )
    validation = (_WORKDAY_DA / "verify-connection.md").read_text(
        encoding="utf-8"
    )
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(
        encoding="utf-8"
    )
    guide = (_WORKDAY_DA / "shared" / "assisted-browser.md").read_text(
        encoding="utf-8"
    )

    for surface in (
        "dataverse-connection",
        "workday-connection",
        "agent-connections",
        "workday-topics",
    ):
        assert surface in connection
        assert surface in guide
    assert "entra-configuration" in entra
    assert "entra-configuration" in guide
    assert "maker-validation" in validation
    assert "maker-validation" in guide


def test_helper_preserves_maker_owned_actions_and_controller_authority() -> None:
    guide = (_WORKDAY_DA / "shared" / "assisted-browser.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(guide.split())

    assert "`scripts/workday_connect.py` remains the sole lifecycle authority" in guide
    assert "must not automate Edge browser chrome" in guide
    for action in ("Create", "Manage", "Save", "Allow"):
        assert f"**{action}**" in guide
    assert "send a Test-pane prompt" in normalized
    assert "Verify outcomes through the existing controller command" in guide


def test_entra_companion_preserves_administrator_ownership() -> None:
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(entra.split())

    assert "presentation choice only" in normalized
    assert "must not be written to controller state" in normalized
    assert "The administrator manually performs and attests" in normalized
    assert "the helper must not navigate the application pane" in normalized
    assert "certificate body" in normalized
    assert "entra-directory-display-name" in normalized
    assert "Confirm or reject each candidate in the companion" in normalized


def test_companion_renderer_never_uses_html_injection() -> None:
    markup = (
        _SCRIPTS
        / "workday_assisted_browser_assets"
        / "companion.html"
    ).read_text(encoding="utf-8")
    script = (
        _SCRIPTS
        / "workday_assisted_browser_assets"
        / "companion.js"
    ).read_text(encoding="utf-8")

    assert "textContent" in script
    assert "replaceChildren" in script
    assert "acknowledgedRevision" in script
    assert "await acknowledgeRender()" in script
    assert 'request("/api/confirmation"' in script
    assert 'fetch("/api/evidence-image"' in script
    assert "URL.createObjectURL" in script
    assert "Show me what to click" in script
    assert 'request("/api/entry"' in script
    assert "renderedEntryKey" in script
    assert "renderedConfirmationKey" in script
    assert "renderTargetPointers" in script
    assert 'id="target-rail"' in markup
    assert 'id="target-pointers"' in markup
    assert 'tooltip.className = "target-tooltip"' in script
    assert 'pointer.textContent = "←"' in script
    assert "navigation-disclaimer" in script
    assert "innerHTML" not in script
    assert "eval(" not in script


def test_navigate_only_reads_are_not_limited_to_navigation_controls() -> None:
    helper = (_SCRIPTS / "workday_assisted_browser.py").read_text(
        encoding="utf-8"
    )
    contract = (
        _WORKDAY_DA / "shared" / "assisted-browser.md"
    ).read_text(encoding="utf-8")

    assert "if navigation_only:" not in helper
    assert (
        "including worksheet-value elements, to locate targets and support "
        "administrator comparison"
    ) in contract
    assert (
        "prohibits remote-state modification in every assistance mode"
        in contract
    )
    assert (
        "works generically across all supported worksheet operations and "
        "portal lists"
    ) in contract
    assert "sole modification-control exception" in contract
    assert "row's manual instructions determine the Edit control" in contract
    assert "companion disclaimer name that exact control" in contract
    assert "Arbitrary Edit controls are still prohibited" in contract
