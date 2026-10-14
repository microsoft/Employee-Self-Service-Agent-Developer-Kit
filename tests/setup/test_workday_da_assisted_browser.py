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
_SCRIPTS = _REPO_ROOT / "solutions" / "ess-maker-skills" / "scripts"


def test_companion_is_isolated_from_existing_workday_phases() -> None:
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
    validation = (_WORKDAY_DA / "verify-connection.md").read_text(encoding="utf-8")
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(encoding="utf-8")

    assert "workday_assisted_browser.py" not in cea
    assert "assisted-browser.md" not in connection
    assert "assisted-browser.md" not in validation
    assert "shared/assisted-browser.md" in entra
    assert "shared/entra-assisted-browser.md" in entra


def test_manual_worksheet_and_companion_share_one_collection_interaction() -> None:
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(encoding="utf-8")
    normalized = " ".join(entra.split())

    assert "Microsoft Entra app administrator handoff -" in entra
    assert "Your tenant values" in entra
    assert "Launch browser companion for assistance" in entra
    assert '"allowFreeformInput": true' in entra
    assert "Free-form entry is the manual path" in normalized
    assert (
        "`completed` companion result supplies the exact worksheet text" in normalized
    )
    assert "Continue with the manual worksheet" in normalized
    assert "Do not add **Continue with the manual worksheet**" in normalized
    assert "record-entra --verification-worksheet-file" in entra


def test_companion_renderer_never_uses_html_injection() -> None:
    markup = (
        _SCRIPTS / "workday_assisted_browser_assets" / "companion.html"
    ).read_text(encoding="utf-8")
    script = (_SCRIPTS / "workday_assisted_browser_assets" / "companion.js").read_text(
        encoding="utf-8"
    )

    assert "textContent" in script
    assert "replaceChildren" in script
    assert "acknowledgedRevision" in script
    assert "await acknowledgeRender()" in script
    assert 'request("/api/confirmation"' in script
    assert 'bridgeRequest(' in script
    assert '"/api/evidence-image"' in script
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
    assert '"Navigation complete"' not in script
    assert '"Navigation authorized"' not in script
    assert '"Capture authorization active"' not in script
    assert '"Navigation assistance active"' not in script
    assert "innerHTML" not in script
    assert "eval(" not in script


def test_companion_uses_user_opened_shared_integrated_browser() -> None:
    protocol = (
        _WORKDAY_DA / "shared" / "assisted-browser.md"
    ).read_text(encoding="utf-8")

    assert 'start --surface "{SURFACE}" --vscode' in protocol
    assert "**View** > **Browser**" in protocol
    assert "**Share with Agent**" in protocol
    assert "agent-opened private browser page" in protocol
    assert "built-in browser tools" in protocol
    assert "shared-browser-result" in protocol
    assert "start --surface \"{SURFACE}\" --launch" not in protocol
