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
    styles = (
        _SCRIPTS / "workday_assisted_browser_assets" / "companion.css"
    ).read_text(encoding="utf-8")
    script = (_SCRIPTS / "workday_assisted_browser_assets" / "companion.js").read_text(
        encoding="utf-8"
    )

    body_rule = styles.split("body {", 1)[1].split("}", 1)[0]
    assert "color: #000;" in body_rule
    assert "textContent" in script
    assert "replaceChildren" in script
    assert "acknowledgedRevision" in script
    assert "await acknowledgeRender()" in script
    assert 'request("/api/confirmation"' in script
    assert 'bridgeRequest(' in script
    assert '"/api/evidence-image"' in script
    assert "URL.createObjectURL" in script
    assert "Show me what to click" in script
    assert 'request("/api/visual-help"' in script
    assert "Preparing screenshot..." in script
    assert "Screenshot unsuccessful" in script
    assert 'request("/api/entry"' in script
    assert "renderedEntryKey" in script
    assert "renderedConfirmationKey" in script
    assert "renderTargetPointers" in script
    assert 'id="target-rail"' in markup
    assert 'id="target-pointers"' in markup
    assert 'tooltip.className = "target-tooltip"' in script
    assert 'pointer.textContent = "◀"' in script
    assert "navigation-explanation" in script
    assert "Assists without capturing values for ADK." in script
    assert "Assists and captures values for ADK." in script
    assert 'textElement("strong", `${action.label}:`)' in script
    assert '"Authorizing..."' not in script
    assert '"Navigating..."' in script
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
    assert "point-targets" in protocol
    assert "wait for the row's exact `confirmation` or `entry`" in protocol
    assert "screenshot controls are not rendered there" in protocol
    assert "does not render screenshot controls or captured images" in protocol
    assert "only in the active companion session" in protocol
    assert "A search with no matching candidate is not a browser failure" in protocol
    assert "start --surface \"{SURFACE}\" --launch" not in protocol


def test_vscode_companion_retains_edge_search_and_retry_behavior() -> None:
    protocol = (_WORKDAY_DA / "shared" / "assisted-browser.md").read_text(
        encoding="utf-8"
    )
    entra = (_WORKDAY_DA / "shared" / "entra-assisted-browser.md").read_text(
        encoding="utf-8"
    )

    for capability in (
        "inspect bounded visible-page evidence",
        "follow an already-inspected visible Entra link",
        "fill an already-inspected visible search or filter input",
        "attempt one bounded contextual screenshot",
        "show its approximate position in the companion rail",
    ):
        assert capability in protocol
    assert "retain the row authorization" in entra
    assert "A missing first result is not a completed search" in entra
    assert "Do not stop or return to chat" in entra
    assert "every visible result and available result page" in entra


def test_entra_companion_has_explicit_capture_and_visual_help_contract() -> None:
    protocol = (_WORKDAY_DA / "shared" / "assisted-browser.md").read_text(
        encoding="utf-8"
    )
    entra = (_WORKDAY_DA / "shared" / "entra-assisted-browser.md").read_text(
        encoding="utf-8"
    )

    assert "| Sensitive |" in entra
    assert entra.count("| No        |") == 13
    assert '"label": "Navigate only"' in entra
    assert '"label": "Navigate and capture"' in entra
    assert '"mode": "navigate-only"' in entra
    assert '"mode": "navigate-and-capture"' in entra
    assert '"label": "Detected {WORKSHEET_ROW}"' in entra
    assert (
        '"prompt": "This is the value detected for {WORKSHEET_ROW}. '
        'Record it in the worksheet?"'
    ) in entra
    assert '"label": "{VISIBLE_TARGET_LABEL}"' in entra
    assert "`pointerError`" in entra
    assert "pointer positioning never blocks the initial render" in entra
    assert "complete `targets` array" in entra
    assert "Build `positionRatio` from the post-scroll geometry" in protocol
    assert "Set `centered` to `true` when" in protocol


def test_entra_companion_uses_compact_authoritative_worksheet_projection() -> None:
    protocol = (_WORKDAY_DA / "shared" / "assisted-browser.md").read_text(
        encoding="utf-8"
    )
    entra = (_WORKDAY_DA / "shared" / "entra-assisted-browser.md").read_text(
        encoding="utf-8"
    )

    assert "present --view-file -" in protocol
    assert "only an input payload" in protocol
    assert "never use it to infer worksheet progress" in protocol
    assert "entra-companion-draft.json" in entra
    assert "confirmed worksheet values only" in entra
    assert "worksheet-status" in entra
    assert "`activeRow`" in entra
    assert "`worksheet.recordedRows`" in entra
    assert "`worksheet.nextOperation`" in entra
    assert "deliberately omits confirmed values and historical views" in entra
    assert "Do not reconstruct progress" in entra
    assert "A **worksheet row** is one entry" in entra
    assert "do not reread the root setup skill" in entra
    assert "worksheet-browser-complete-and-record" in entra
    assert "records only an accepted result" in entra
    assert "pointer positioning never blocks the initial render" in entra
    assert "A `stage` of `recorded`" in entra
    assert "standalone revision-bound `wait` and `worksheet-record`" in entra
    assert "worksheet-record" in entra
    assert "screenshot controls are not rendered there" in protocol
    assert "native cancellation" in entra
    assert "Do not call `workday_assisted_browser.py stop`" in entra
    assert "worksheet-reset" in entra
    assert "clears only worksheet draft and companion interaction state" in entra
    assert "worksheet-present" in entra
    assert "Never manually author, patch, or reuse a row view payload" in entra
    assert "lastKnownUrlTemplate" in entra
