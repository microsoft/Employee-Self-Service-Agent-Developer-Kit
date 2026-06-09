# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for the prioritized FlightCheck report layout introduced
in PR for grahamc/flightcheck-report-prioritized-format.

The redesign reshapes the operator's triage path: a verdict banner at
the top tells them at a glance whether the deployment is ready, and
results are split into three sections so they don't have to scan a
single mixed table to find what needs action.

This file pins the layout contracts so a future refactor cannot
silently break the "find what needs my attention" path the report
was designed for.

The three buckets are:
  - ACTION REQUIRED:  Failed, Error
  - MANUAL:           Warning, Manual, NotConfigured
  - PASSED:           Passed, Skipped

Warnings live under MANUAL (not ACTION) because they're "should I
worry?" questions the kit can't answer — the verification path is
the operator's. Skipped lives under PASSED because the kit chose
not to run the check (didn't apply / precondition not met); from a
triage perspective the row needs no action.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _scripts_on_path():
    """Ensure scripts/ is on sys.path so `from flightcheck...` resolves."""
    scripts_dir = (
        Path(__file__).resolve().parents[1]
        / "solutions" / "ess-maker-skills" / "scripts"
    )
    sys.path.insert(0, str(scripts_dir))
    try:
        yield
    finally:
        try:
            sys.path.remove(str(scripts_dir))
        except ValueError:
            pass


def _make_result(checkpoint_id, status, priority="High", category="Test"):
    """Lightweight CheckResult factory for layout tests."""
    from flightcheck.runner import CheckResult
    return CheckResult(
        checkpoint_id=checkpoint_id,
        category=category,
        priority=priority,
        status=status,
        description=f"desc for {checkpoint_id}",
        result=f"result for {checkpoint_id}",
        remediation=(
            f"remediation for {checkpoint_id}"
            if status not in ("Passed",)
            else ""
        ),
    )


# ---------------------------------------------------------------------------
# bucket_results — the core grouping helper.
# ---------------------------------------------------------------------------


def test_bucket_results_assigns_statuses_to_correct_buckets():
    """Every status maps to exactly one of the three buckets per
    the contract documented in runner.py. Warning routes to MANUAL
    (it's an operator-verification question, not a fix-this); Skipped
    routes to PASSED (the kit chose not to run the check, so the
    row isn't actionable)."""
    from flightcheck.runner import (
        bucket_results,
        BUCKET_ACTION,
        BUCKET_MANUAL,
        BUCKET_PASSED,
    )

    results = [
        _make_result("FAIL-1", "Failed"),
        _make_result("ERR-1", "Error"),
        _make_result("WARN-1", "Warning"),
        _make_result("MAN-1", "Manual"),
        _make_result("CFG-1", "NotConfigured"),
        _make_result("SKIP-1", "Skipped"),
        _make_result("PASS-1", "Passed"),
    ]
    b = bucket_results(results)

    action_ids = [r.checkpoint_id for r in b[BUCKET_ACTION]]
    manual_ids = [r.checkpoint_id for r in b[BUCKET_MANUAL]]
    passed_ids = [r.checkpoint_id for r in b[BUCKET_PASSED]]

    assert set(action_ids) == {"FAIL-1", "ERR-1"}
    assert set(manual_ids) == {"WARN-1", "MAN-1", "CFG-1"}
    assert set(passed_ids) == {"SKIP-1", "PASS-1"}


def test_bucket_results_sorts_by_priority_then_status_then_id():
    """Within ACTION REQUIRED:
       - Critical-priority items come before High before Medium.
       - Within the same priority, Failed comes before Error.
       - Within the same priority + status, ids sort alphabetically.
    """
    from flightcheck.runner import bucket_results, BUCKET_ACTION

    results = [
        _make_result("Z-ERR", "Error", priority="Critical"),
        _make_result("Z-FAIL", "Failed", priority="Critical"),
        _make_result("A-FAIL", "Failed", priority="Critical"),
        _make_result("HI-FAIL", "Failed", priority="High"),
        _make_result("MED-FAIL", "Failed", priority="Medium"),
    ]
    ordered = [r.checkpoint_id for r in bucket_results(results)[BUCKET_ACTION]]

    assert ordered == ["A-FAIL", "Z-FAIL", "Z-ERR", "HI-FAIL", "MED-FAIL"]


def test_bucket_results_manual_bucket_sorts_warning_before_manual_then_notconfigured():
    """Within the MANUAL bucket, Warning surfaces FIRST because it
    carries an observed finding the kit chose to flag. Manual and
    NotConfigured come after because they're "we didn't / couldn't
    evaluate" rather than "we found something". Operators triaging
    the manual section read top-to-bottom, so observed-findings-first
    is the high-signal order."""
    from flightcheck.runner import bucket_results, BUCKET_MANUAL

    results = [
        _make_result("CFG-1", "NotConfigured", priority="High"),
        _make_result("MAN-1", "Manual", priority="High"),
        _make_result("WARN-1", "Warning", priority="High"),
    ]
    ordered = [r.checkpoint_id for r in bucket_results(results)[BUCKET_MANUAL]]
    assert ordered == ["WARN-1", "MAN-1", "CFG-1"]


def test_bucket_results_passed_bucket_sorts_passed_before_skipped():
    """Within PASSED, actual Passed rows come before Skipped rows so
    the operator's "proof of work" sits at the top of the (collapsed)
    section, with Skipped — which has no signal — below it."""
    from flightcheck.runner import bucket_results, BUCKET_PASSED

    results = [
        _make_result("SKIP-1", "Skipped", priority="High"),
        _make_result("PASS-1", "Passed", priority="High"),
    ]
    ordered = [r.checkpoint_id for r in bucket_results(results)[BUCKET_PASSED]]
    assert ordered == ["PASS-1", "SKIP-1"]


def test_bucket_results_unknown_status_lands_in_action_required():
    """Defensive default: an unrecognized status should surface in
    the most-visible bucket, not silently vanish."""
    from flightcheck.runner import bucket_results, BUCKET_ACTION

    r = _make_result("UNKNOWN-1", "SomeFutureStatus")
    bucketed = bucket_results([r])
    assert r in bucketed[BUCKET_ACTION]


# ---------------------------------------------------------------------------
# Verdict banner — the single largest signal at the top of the report.
# ---------------------------------------------------------------------------


def _build_run_with(results):
    """Run a registered no-op check that returns the supplied results."""
    from flightcheck.runner import FlightCheckRunner
    runner = FlightCheckRunner(scope="test")
    runner.register("Test", lambda _r: list(results))
    return runner.run()


def test_verdict_banner_ready_when_all_passed(tmp_path):
    from flightcheck.runner import save_results
    result = _build_run_with([_make_result("OK-1", "Passed")])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert result.overall == "READY"
    assert "verdict-ready" in html
    assert "Ready for deployment" in html


def test_verdict_banner_warnings_when_only_warnings(tmp_path):
    from flightcheck.runner import save_results
    result = _build_run_with([_make_result("W-1", "Warning")])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert result.overall == "READY_WITH_WARNINGS"
    assert "verdict-warnings" in html
    assert "Ready with warnings" in html


def test_verdict_banner_not_ready_when_any_failure(tmp_path):
    from flightcheck.runner import save_results
    result = _build_run_with([
        _make_result("F-1", "Failed"),
        _make_result("W-1", "Warning"),
        _make_result("OK-1", "Passed"),
    ])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert result.overall == "NOT_READY"
    assert "verdict-not-ready" in html
    assert "Not ready" in html
    # Subline mentions counts so operator knows the scale.
    assert "1 failing/errored" in html
    assert "1 warning" in html


def test_verdict_ready_subline_mentions_manual_count_when_present(tmp_path):
    """When the run is READY but contains manual items, the verdict
    subline must point the operator to the manual section."""
    from flightcheck.runner import save_results
    result = _build_run_with([
        _make_result("OK-1", "Passed"),
        _make_result("OK-2", "Passed"),
        _make_result("M-1", "Manual"),
    ])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert "verdict-ready" in html
    # "1 item(s) need manual verification" — operator must not miss
    # the manual items just because the verdict is green.
    assert "need manual verification" in html


def test_verdict_warnings_subline_points_at_manual_section_not_action(tmp_path):
    """READY_WITH_WARNINGS subline must direct the operator to
    \"Needs manual verification\" \u2014 where warnings actually live
    under the new bucketing. The old wording \"Action required\" was
    a stale pointer once warnings moved out of that section, and
    operators would scroll to an empty Action Required and miss the
    warnings entirely."""
    from flightcheck.runner import save_results
    result = _build_run_with([_make_result("W-1", "Warning")])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    # Find the verdict text block — the subline lives next to the
    # verdict-warnings class on the banner.
    m = re.search(r'<div class="verdict verdict-warnings">.*?</div>\s*</div>', html, flags=re.S)
    assert m is not None, "verdict-warnings block not found"
    verdict_block = m.group(0)

    assert "Needs manual verification" in verdict_block, verdict_block
    # The old wording must not regress \u2014 it would point the
    # operator at an empty section.
    assert "Action required" not in verdict_block, verdict_block


def test_verdict_not_ready_subline_separates_action_from_verification(tmp_path):
    """When the run is NOT_READY and also has warnings, the subline
    must say BOTH where to act (Action required) AND where to
    verify (Needs manual verification). Bundling them under one
    section name misroutes the operator."""
    from flightcheck.runner import save_results
    result = _build_run_with([
        _make_result("F-1", "Failed"),
        _make_result("W-1", "Warning"),
    ])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    m = re.search(r'<div class="verdict verdict-not-ready">.*?</div>\s*</div>', html, flags=re.S)
    assert m is not None
    verdict_block = m.group(0)

    assert "1 failing/errored" in verdict_block, verdict_block
    assert "1 warning" in verdict_block, verdict_block
    assert "need action" in verdict_block, verdict_block
    assert "need manual verification" in verdict_block, verdict_block


def test_verdict_not_ready_headline_counts_failures_only_not_warnings(tmp_path):
    """The NOT_READY headline counts only blocking items
    (Failed + Error). Warnings are NOT blockers \u2014 they live in
    the manual-verification section \u2014 so counting them in the
    headline would overstate the action load."""
    from flightcheck.runner import save_results
    result = _build_run_with([
        _make_result("F-1", "Failed"),
        _make_result("W-1", "Warning"),
        _make_result("W-2", "Warning"),
    ])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    # Headline must read "Not ready — 1 issue need attention" (one
    # failure), NOT "3 issues" (which would include the warnings).
    m = re.search(r'<h2>Not ready[^<]*</h2>', html)
    assert m is not None, html
    headline = m.group(0)
    assert "1 issue" in headline, headline
    # Defensive: the old behavior was to add the warning count into
    # the headline; this pin prevents a regression.
    assert "3 issues" not in headline, headline


# ---------------------------------------------------------------------------
# Section rendering — the three stacked sections.
# ---------------------------------------------------------------------------


def test_html_renders_three_named_sections(tmp_path):
    """The three section anchors must exist regardless of which
    sections happen to be populated, so the layout is stable for any
    downstream tooling that links into specific section ids."""
    from flightcheck.runner import save_results
    result = _build_run_with([
        _make_result("F-1", "Failed"),
        _make_result("M-1", "Manual"),
        _make_result("P-1", "Passed"),
    ])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert 'id="section-action"' in html
    assert 'id="section-manual"' in html
    assert 'id="section-passed"' in html
    assert "Action required" in html
    assert "Needs manual verification" in html
    assert ">Passed</h2>" in html


def test_action_section_open_by_default_passed_section_collapsed(tmp_path):
    """The ACTION section must be open (operator sees rows
    immediately), the PASSED section must be collapsed (operator
    isn't forced to scroll past every passing row)."""
    from flightcheck.runner import save_results
    result = _build_run_with([
        _make_result("F-1", "Failed"),
        _make_result("P-1", "Passed"),
    ])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    # <details id="section-action" class="section" open> — note the
    # exact attribute presence, since absence flips the default.
    assert re.search(
        r'<details id="section-action" class="section" open>', html
    ), "Action section must be open by default"
    assert re.search(
        r'<details id="section-manual" class="section" open>', html
    ), "Manual section must be open by default"

    # PASSED has no `open` attribute — collapsed.
    passed_block = re.search(
        r'<details id="section-passed"[^>]*>', html
    )
    assert passed_block is not None
    assert " open" not in passed_block.group(0), (
        "Passed section must NOT be open by default"
    )


def test_empty_section_shows_friendly_note_not_an_empty_table(tmp_path):
    """A section with zero results must show a friendly empty-note,
    not an empty table the operator has to decode."""
    from flightcheck.runner import save_results
    # Only passing rows — both action_required and manual sections
    # are empty.
    result = _build_run_with([_make_result("OK-1", "Passed")])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    assert "nothing here" in html.lower() or "no failing" in html.lower()
    # The empty section should NOT have a table inside it; check that
    # by ensuring action section header is followed by the empty-note
    # class before the next section.
    m = re.search(
        r'id="section-action".*?</details>', html, flags=re.S
    )
    assert m is not None
    assert "empty-note" in m.group(0)
    assert "<table>" not in m.group(0)


def test_status_to_section_routing_in_rendered_html(tmp_path):
    """Each status renders inside the section its bucket dictates.
    Warning lands under MANUAL (operator must verify); Skipped lands
    under PASSED (kit chose not to run the check)."""
    from flightcheck.runner import save_results
    result = _build_run_with([
        _make_result("FAIL-X", "Failed"),
        _make_result("WARN-X", "Warning"),
        _make_result("MAN-X", "Manual"),
        _make_result("SKIP-X", "Skipped"),
        _make_result("PASS-X", "Passed"),
    ])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    def section_html(section_id: str) -> str:
        m = re.search(
            rf'id="{section_id}".*?</details>', html, flags=re.S
        )
        assert m is not None, f"Section {section_id} not in HTML"
        return m.group(0)

    action_html = section_html("section-action")
    manual_html = section_html("section-manual")
    passed_html = section_html("section-passed")

    # FAIL belongs in action
    assert "FAIL-X" in action_html
    assert "FAIL-X" not in manual_html and "FAIL-X" not in passed_html

    # WARN + MAN belong in manual (Warning folds here per design —
    # it's an operator-verification question, not a fix-this).
    assert "WARN-X" in manual_html
    assert "MAN-X" in manual_html
    assert "WARN-X" not in action_html and "WARN-X" not in passed_html
    assert "MAN-X" not in action_html and "MAN-X" not in passed_html

    # PASS + SKIP belong in passed (Skipped folds here per design —
    # the kit chose not to run the check, so the row needs no action).
    assert "PASS-X" in passed_html
    assert "SKIP-X" in passed_html
    assert "PASS-X" not in action_html and "PASS-X" not in manual_html
    assert "SKIP-X" not in action_html and "SKIP-X" not in manual_html


def test_section_count_badge_matches_bucket_size(tmp_path):
    """The badge next to each section header shows the bucket count
    so the operator sees scale before expanding. Counts reflect the
    new mapping: Warning is in MANUAL (not ACTION), Skipped is in
    PASSED (not MANUAL)."""
    from flightcheck.runner import save_results
    result = _build_run_with([
        _make_result("F-1", "Failed"),
        _make_result("F-2", "Failed"),
        _make_result("W-1", "Warning"),
        _make_result("M-1", "Manual"),
        _make_result("S-1", "Skipped"),
        _make_result("P-1", "Passed"),
        _make_result("P-2", "Passed"),
        _make_result("P-3", "Passed"),
    ])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    def badge_count_for(section_id: str) -> str:
        m = re.search(
            rf'id="{section_id}".*?count-badge">(\d+)</span>',
            html, flags=re.S,
        )
        assert m is not None, f"No count badge for {section_id}"
        return m.group(1)

    assert badge_count_for("section-action") == "2"   # 2 Failed only
    assert badge_count_for("section-manual") == "2"   # 1 Warning + 1 Manual
    assert badge_count_for("section-passed") == "4"   # 3 Passed + 1 Skipped


def test_action_rows_sorted_critical_before_high_in_html(tmp_path):
    """Within ACTION REQUIRED, a Critical-priority row must appear
    BEFORE a High-priority row in the rendered table — even if
    Critical was registered later."""
    from flightcheck.runner import save_results
    result = _build_run_with([
        _make_result("HIGH-1", "Failed", priority="High"),
        _make_result("CRIT-1", "Failed", priority="Critical"),
        _make_result("MED-1", "Failed", priority="Medium"),
    ])
    save_results(result, output_dir=str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf-8")

    action_section_match = re.search(
        r'id="section-action".*?</details>', html, flags=re.S,
    )
    assert action_section_match is not None
    section_html = action_section_match.group(0)

    crit_pos = section_html.index("CRIT-1")
    high_pos = section_html.index("HIGH-1")
    med_pos = section_html.index("MED-1")
    assert crit_pos < high_pos < med_pos, (
        "Within Action Required, priorities must render Critical -> "
        "High -> Medium so operator triages worst-first."
    )


# ---------------------------------------------------------------------------
# JSON contract — adding `skipped`/`errors` must not break existing fields.
# ---------------------------------------------------------------------------


def test_json_summary_includes_skipped_and_errors_counts(tmp_path):
    """Top-level JSON gains `skipped` and `errors` so the new summary
    cards have numbers to display. The existing six counters
    (passed/failed/warnings/not_configured/manual + overall) must
    continue to exist with the same keys."""
    from flightcheck.runner import save_results
    result = _build_run_with([
        _make_result("F-1", "Failed"),
        _make_result("E-1", "Error"),
        _make_result("S-1", "Skipped"),
        _make_result("S-2", "Skipped"),
        _make_result("P-1", "Passed"),
    ])
    save_results(result, output_dir=str(tmp_path))

    data = json.loads(
        (tmp_path / "results.json").read_text(encoding="utf-8")
    )
    assert data["skipped"] == 2
    assert data["errors"] == 1
    # Backwards-compat: existing keys still present.
    for key in (
        "overall", "total", "passed", "failed", "warnings",
        "not_configured", "manual", "categories", "results",
    ):
        assert key in data, (
            f"Missing top-level JSON key '{key}' — existing consumers "
            "depend on it."
        )


def test_json_results_list_preserves_run_order(tmp_path):
    """The `results[]` array in results.json must stay in run-order so
    consumers that index it (or that diff between runs) don't break.
    Bucketing happens at render time, not in the underlying data."""
    from flightcheck.runner import save_results
    # Register in mixed status order so bucket sort would re-order.
    rs = [
        _make_result("FIRST",  "Passed"),
        _make_result("SECOND", "Failed", priority="Critical"),
        _make_result("THIRD",  "Manual"),
        _make_result("FOURTH", "Warning"),
    ]
    result = _build_run_with(rs)
    save_results(result, output_dir=str(tmp_path))

    data = json.loads(
        (tmp_path / "results.json").read_text(encoding="utf-8")
    )
    ids_in_order = [r["checkpoint_id"] for r in data["results"]]
    assert ids_in_order == ["FIRST", "SECOND", "THIRD", "FOURTH"], (
        "results.json must preserve run-order; bucket sort applies "
        "only to the rendered HTML."
    )


def test_runresult_skipped_and_errors_tallied():
    """The runner must populate the new `skipped` and `errors`
    top-level RunResult fields off the same source as the categories.
    """
    from flightcheck.runner import (
        FlightCheckRunner, CheckResult, Status, Priority,
    )

    runner = FlightCheckRunner(scope="test")
    runner.register("Cat", lambda _r: [
        CheckResult(
            checkpoint_id="S-1", category="Cat",
            priority=Priority.HIGH.value, status=Status.SKIPPED.value,
            description="d", result="r",
        ),
        CheckResult(
            checkpoint_id="E-1", category="Cat",
            priority=Priority.HIGH.value, status=Status.ERROR.value,
            description="d", result="r", remediation="x",
        ),
    ])
    result = runner.run()

    assert result.skipped == 1
    assert result.errors == 1


def test_overall_verdict_treats_error_only_run_as_not_ready():
    """An error-only run must not render as READY.

    The verdict banner is the report's single biggest at-a-glance
    signal. An ERROR (a check raised mid-run) means we don't actually
    know whether ESS is healthy in that area, so the verdict MUST
    NOT be green.

    Pre-fix the verdict logic inspected only failed+warnings and
    ignored errors entirely (runner.py:148). An error-only run
    therefore rendered a green ``verdict-ready`` banner reading
    *"All N check(s) passed. Your environment looks ready to
    deploy."* with all the errored rows listed under ACTION REQUIRED
    directly below — exactly the at-a-glance contradiction the
    prioritized report is meant to eliminate.

    Repro recipe: kill BAP auth mid-run so EXT-001 / ENV-001 /
    WD-CONN-001 all raise. Nothing else fails or warns. Banner
    shows READY. The errored rows appear directly below it.
    """
    from flightcheck.runner import (
        CheckResult,
        FlightCheckRunner,
        Priority,
        Status,
    )

    runner = FlightCheckRunner(scope="test")
    runner.register("Cat", lambda _r: [
        CheckResult(
            checkpoint_id="E-1", category="Cat",
            priority=Priority.HIGH.value, status=Status.ERROR.value,
            description="External systems validation",
            result="Check failed with error: boom",
            remediation="Review permissions and retry.",
        ),
        CheckResult(
            checkpoint_id="PRE-001", category="Cat",
            priority=Priority.CRITICAL.value, status=Status.PASSED.value,
            description="License", result="OK",
        ),
    ])
    result = runner.run()

    assert result.errors == 1
    assert result.failed == 0
    assert result.warnings == 0
    assert result.overall == "NOT_READY"


def test_overall_verdict_error_plus_warning_is_not_ready_not_ready_with_warnings():
    """Same blind spot at the READY_WITH_WARNINGS boundary: an error
    plus a warning must NOT render as READY_WITH_WARNINGS (which
    would silently swallow the error in the verdict). It is
    NOT_READY because we have an error.
    """
    from flightcheck.runner import (
        CheckResult,
        FlightCheckRunner,
        Priority,
        Status,
    )

    runner = FlightCheckRunner(scope="test")
    runner.register("Cat", lambda _r: [
        CheckResult(
            checkpoint_id="E-1", category="Cat",
            priority=Priority.HIGH.value, status=Status.ERROR.value,
            description="External systems validation",
            result="Check failed with error: boom",
            remediation="Review permissions and retry.",
        ),
        CheckResult(
            checkpoint_id="W-1", category="Cat",
            priority=Priority.MEDIUM.value, status=Status.WARNING.value,
            description="Soft issue", result="meh",
            remediation="Look at this.",
        ),
    ])
    result = runner.run()

    assert result.errors == 1
    assert result.warnings == 1
    assert result.overall == "NOT_READY"
