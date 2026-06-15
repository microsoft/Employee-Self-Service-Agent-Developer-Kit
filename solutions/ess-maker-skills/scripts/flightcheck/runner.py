# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — FlightCheck Runner

Orchestrates all validation checks, aggregates results, and reports.
"""

import json
import os
import time
import traceback
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Callable


class Status(str, Enum):
    PASSED = "Passed"
    FAILED = "Failed"
    WARNING = "Warning"
    NOT_CONFIGURED = "NotConfigured"
    SKIPPED = "Skipped"
    ERROR = "Error"
    # MANUAL — the check gathered everything the kit can verify
    # programmatically but the final comparison must be performed by
    # the operator against an external system the kit can't (or
    # shouldn't) read directly. The result carries the value the kit
    # observed; the remediation tells the operator what to compare it
    # against and where. MANUAL items do NOT fail readiness — they're
    # informational/actionable, similar to NOT_CONFIGURED.
    MANUAL = "Manual"


class Priority(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Role(str, Enum):
    """Persona who owns the next step on a check.

    A check's ``roles`` list names every admin persona whose action is
    required to FIX a failing/errored result or to PERFORM the manual
    validation of a MANUAL/NOT_CONFIGURED result. A check may need more
    than one role (e.g. a Workday SAML cert lives on an Entra app but is
    compared in the Workday tenant — Entra Admin + Workday Admin).

    The value is the human-readable label rendered in the report.
    """

    ENTRA_ADMIN = "Entra Admin"
    M365_ADMIN = "Microsoft 365 Admin"
    POWER_PLATFORM_ADMIN = "Power Platform Admin"
    WORKDAY_ADMIN = "Workday Admin"
    SERVICENOW_ADMIN = "ServiceNow Admin"
    SAP_ADMIN = "SAP Admin"
    ESS_MAKER = "ESS Maker / Agent Developer"


@dataclass
class CheckResult:
    checkpoint_id: str
    category: str
    priority: str          # Priority enum value
    status: str            # Status enum value
    description: str       # What was checked
    result: str            # Finding detail
    remediation: str = ""  # How to fix
    doc_link: str = ""     # Microsoft Learn URL
    # roles — the persona(s) who own the next step (fix or manual
    # validation). Every production check sets this; defaults to empty
    # so the runner's ERROR fallback and unit-test constructions still
    # build. Values are Role enum strings.
    roles: list[str] = field(default_factory=list)


@dataclass
class CategorySummary:
    category: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    not_configured: int = 0
    skipped: int = 0
    errors: int = 0
    manual: int = 0


@dataclass
class RunResult:
    scope: str
    started: str
    duration_secs: float = 0
    results: list[CheckResult] = field(default_factory=list)
    categories: list[CategorySummary] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    not_configured: int = 0
    manual: int = 0
    skipped: int = 0
    errors: int = 0
    overall: str = ""  # READY / READY_WITH_WARNINGS / NOT_READY


class FlightCheckRunner:
    """Executes registered check functions and aggregates results."""

    def __init__(self, scope: str = "full"):
        self.scope = scope
        self.results: list[CheckResult] = []
        self._check_fns: list[tuple[str, Callable]] = []

    def register(self, category: str, fn: Callable):
        """Register a check function. fn(runner) -> list[CheckResult]."""
        self._check_fns.append((category, fn))

    def run(self) -> RunResult:
        """Execute all registered checks and build the run result."""
        start = time.time()
        started_iso = time.strftime("%Y-%m-%dT%H:%M:%S")

        for category, fn in self._check_fns:
            try:
                results = fn(self)
                if results:
                    self.results.extend(results)
            except Exception as e:
                self.results.append(CheckResult(
                    checkpoint_id=f"{category[:3].upper()}-ERR",
                    category=category,
                    priority=Priority.HIGH.value,
                    status=Status.ERROR.value,
                    description=f"{category} validation",
                    result=f"Check failed with error: {e}",
                    remediation="Review permissions and retry. See terminal output for details.",
                    roles=[Role.ESS_MAKER.value],
                ))
                traceback.print_exc()

        duration = time.time() - start

        # Build category summaries
        cat_map: dict[str, CategorySummary] = {}
        for r in self.results:
            if r.category not in cat_map:
                cat_map[r.category] = CategorySummary(category=r.category)
            s = cat_map[r.category]
            s.total += 1
            if r.status == Status.PASSED.value:
                s.passed += 1
            elif r.status == Status.FAILED.value:
                s.failed += 1
            elif r.status == Status.WARNING.value:
                s.warnings += 1
            elif r.status == Status.NOT_CONFIGURED.value:
                s.not_configured += 1
            elif r.status == Status.SKIPPED.value:
                s.skipped += 1
            elif r.status == Status.ERROR.value:
                s.errors += 1
            elif r.status == Status.MANUAL.value:
                s.manual += 1

        total_failed = sum(c.failed for c in cat_map.values())
        total_warnings = sum(c.warnings for c in cat_map.values())
        total_passed = sum(c.passed for c in cat_map.values())
        # Tallied here so the verdict logic can consult errors. Errors
        # (a check raised mid-run) mean we don't actually know whether
        # ESS is healthy in that area, so they MUST count as
        # "not ready" — not "ready" or "ready with warnings". Before
        # this was added, an error-only run rendered as green READY
        # with all the errored rows visible under ACTION REQUIRED
        # directly below the green banner — exactly the at-a-glance
        # contradiction the prioritized report is meant to eliminate.
        total_errors = sum(c.errors for c in cat_map.values())

        if total_failed == 0 and total_errors == 0 and total_warnings == 0:
            overall = "READY"
        elif total_failed == 0 and total_errors == 0:
            overall = "READY_WITH_WARNINGS"
        else:
            overall = "NOT_READY"

        return RunResult(
            scope=self.scope,
            started=started_iso,
            duration_secs=round(duration, 1),
            results=self.results,
            categories=list(cat_map.values()),
            total=len(self.results),
            passed=total_passed,
            failed=total_failed,
            warnings=total_warnings,
            not_configured=sum(c.not_configured for c in cat_map.values()),
            manual=sum(c.manual for c in cat_map.values()),
            skipped=sum(c.skipped for c in cat_map.values()),
            errors=total_errors,
            overall=overall,
        )


def save_results(run_result: RunResult, output_dir: str = "workspace/flightcheck"):
    """Persist run results to JSON, tasks.md, and HTML report."""
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "history"), exist_ok=True)

    # Write results.json
    results_path = os.path.join(output_dir, "results.json")
    data = {
        "scope": run_result.scope,
        "started": run_result.started,
        "duration_secs": run_result.duration_secs,
        "overall": run_result.overall,
        "total": run_result.total,
        "passed": run_result.passed,
        "failed": run_result.failed,
        "warnings": run_result.warnings,
        "not_configured": run_result.not_configured,
        "manual": run_result.manual,
        "skipped": run_result.skipped,
        "errors": run_result.errors,
        "categories": [asdict(c) for c in run_result.categories],
        "results": [asdict(r) for r in run_result.results],
    }
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Generate HTML report
    html = _generate_html_report(run_result)

    # Archive HTML report to history
    history_path = os.path.join(
        output_dir, "history",
        f"{run_result.started.replace(':', '-')}.html",
    )
    with open(history_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Write HTML report (latest)
    report_path = os.path.join(output_dir, "report.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nResults saved to {results_path}")
    print(f"Report saved to {report_path}")


# --- Result bucketing for the prioritized report layout --------------

# Triage bucket model
# ------------------------------------------------------------------
# Results sort into one of three rendered sections, top to bottom:
#
#   1. ACTION_REQUIRED — Failed, Error. These are checks that did
#      not pass and the kit is confident the operator must act.
#      The blocking signal — fix-this-now items only.
#
#   2. MANUAL_VERIFICATION — Warning, Manual, NotConfigured. The
#      kit cannot make a yes/no judgement, or surfaced a soft
#      finding the operator should confirm is acceptable. Warnings
#      live here (not in Action required) because they are "should
#      I worry?" questions, not "fix this" instructions — the
#      verification path is the operator's, not the kit's. NotConfigured
#      means the kit had no creds/visibility to evaluate.
#
#   3. PASSED — Passed, Skipped. Skipped is grouped with Passed
#      because the kit chose not to run the check (e.g. it didn't
#      apply to this scope, or a precondition wasn't met); from the
#      operator's triage perspective the row needs no action and
#      should sit alongside the proof-of-work passes.
#
# Within each bucket, results are sorted by:
#   - priority (Critical > High > Medium > Low > unknown last)
#   - status (per _BUCKET_STATUS_ORDER below — worst first within bucket)
#   - checkpoint_id (alphabetical, stable within ties)
#
# The flat run-order `RunResult.results` list is preserved unchanged
# so JSON consumers and the pinned regression test for AUTH-005-style
# bucketed checks keep working.

BUCKET_ACTION = "action_required"
BUCKET_MANUAL = "manual_verification"
BUCKET_PASSED = "passed"

# Which statuses land in which bucket. Keys are Status enum string
# values (which is what CheckResult.status carries).
_STATUS_TO_BUCKET = {
    Status.FAILED.value: BUCKET_ACTION,
    Status.ERROR.value: BUCKET_ACTION,
    Status.WARNING.value: BUCKET_MANUAL,
    Status.MANUAL.value: BUCKET_MANUAL,
    Status.NOT_CONFIGURED.value: BUCKET_MANUAL,
    Status.SKIPPED.value: BUCKET_PASSED,
    Status.PASSED.value: BUCKET_PASSED,
}

# Within-bucket status sort order — lower index = surfaced first.
# Worst news in each bucket goes to the top.
_BUCKET_STATUS_ORDER = {
    # ACTION_REQUIRED — Failed first, then Error.
    Status.FAILED.value: 0,
    Status.ERROR.value: 1,
    # MANUAL_VERIFICATION — Warning first because it carries an
    # observed finding (vs Manual/NotConfigured, which are "we
    # didn't / couldn't evaluate").
    Status.WARNING.value: 0,
    Status.MANUAL.value: 1,
    Status.NOT_CONFIGURED.value: 2,
    # PASSED — actual passes first, then Skipped (no signal).
    Status.PASSED.value: 0,
    Status.SKIPPED.value: 1,
}

_PRIORITY_ORDER = {
    Priority.CRITICAL.value: 0,
    Priority.HIGH.value: 1,
    Priority.MEDIUM.value: 2,
    Priority.LOW.value: 3,
}


def _sort_key(r: CheckResult) -> tuple:
    """Sort by priority, then within-bucket status order, then id."""
    return (
        _PRIORITY_ORDER.get(r.priority, 99),
        _BUCKET_STATUS_ORDER.get(r.status, 99),
        r.checkpoint_id or "",
    )


def bucket_results(
    results: list[CheckResult],
) -> dict[str, list[CheckResult]]:
    """Group results into action_required / manual_verification / passed
    buckets, each sorted by priority then status then checkpoint_id.

    Unknown statuses fall into ACTION_REQUIRED as a defensive default
    so a future status that isn't wired here doesn't silently vanish
    from the report. The operator sees it under the most-visible
    section instead.
    """
    buckets: dict[str, list[CheckResult]] = {
        BUCKET_ACTION: [],
        BUCKET_MANUAL: [],
        BUCKET_PASSED: [],
    }
    for r in results:
        bucket = _STATUS_TO_BUCKET.get(r.status, BUCKET_ACTION)
        buckets[bucket].append(r)
    for key in buckets:
        buckets[key].sort(key=_sort_key)
    return buckets


def _generate_html_report(r: RunResult) -> str:
    """Generate the prioritized HTML report.

    Layout (top to bottom):
      - Header with timestamp / scope / duration
      - Verdict banner (green / yellow / red) with one-line summary
      - Summary count cards (Passed / Failed / Warnings / Manual /
        Not Configured / Skipped / Errors)
      - Section 1: ACTION REQUIRED (Failed + Error)
      - Section 2: NEEDS MANUAL VERIFICATION (Warning + Manual + NotConfigured)
      - Section 3: PASSED (collapsed by default — proof of work plus
        Skipped, not a triage queue)
    """
    buckets = bucket_results(r.results)

    verdict_class, verdict_icon, verdict_headline, verdict_sub = _verdict_text(r)

    action_rows = _render_rows(buckets[BUCKET_ACTION])
    manual_rows = _render_rows(buckets[BUCKET_MANUAL])
    passed_rows = _render_rows(buckets[BUCKET_PASSED])

    action_section = _render_section(
        section_id="section-action",
        title="Action required",
        subtitle=(
            "Items the kit confirmed are failing or errored. Fix each one "
            "before deploying. (Warnings live under \u201cNeeds manual "
            "verification\u201d below \u2014 they\u2019re questions the "
            "kit can\u2019t answer for you, not blocking failures.)"
        ),
        empty_text=(
            "No failing or errored items \u2014 nothing here needs your "
            "attention."
        ),
        rows_html=action_rows,
        count=len(buckets[BUCKET_ACTION]),
        open_by_default=True,
    )

    manual_section = _render_section(
        section_id="section-manual",
        title="Needs manual verification",
        subtitle=(
            "Warnings and other findings the kit can\u2019t confirm "
            "programmatically. For each row, verify the state in the "
            "portal / vendor system and confirm it\u2019s acceptable, "
            "or fix the reason the check couldn\u2019t run (missing "
            "credentials, permissions, or feature not enabled)."
        ),
        empty_text=(
            "Nothing requires manual verification \u2014 every check "
            "ran end-to-end."
        ),
        rows_html=manual_rows,
        count=len(buckets[BUCKET_MANUAL]),
        open_by_default=True,
    )

    passed_section = _render_section(
        section_id="section-passed",
        title="Passed",
        subtitle=(
            "Items the kit confirmed are in a good state, plus checks "
            "the kit chose to skip because they didn\u2019t apply to "
            "this scope. Expand for the full list."
        ),
        empty_text="No passing items in this run.",
        rows_html=passed_rows,
        count=len(buckets[BUCKET_PASSED]),
        open_by_default=False,
    )

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>ESS Pre-flight Validation Report</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .header {{ background-color: #0078d4; color: white; padding: 20px; border-radius: 5px; }}
        /* Verdict banner — the single biggest signal in the report.
           Three states match RunResult.overall: READY (green),
           READY_WITH_WARNINGS (amber), NOT_READY (red). The icon +
           headline + subline are all sized so the operator gets the
           verdict at a glance without reading anything else. */
        .verdict {{ padding: 24px; margin: 20px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); display: flex; align-items: center; gap: 20px; }}
        .verdict-icon {{ font-size: 48px; line-height: 1; flex-shrink: 0; }}
        .verdict-text h2 {{ margin: 0 0 4px 0; font-size: 24px; }}
        .verdict-text p {{ margin: 0; font-size: 14px; opacity: 0.9; }}
        .verdict-ready {{ background-color: #d4edda; color: #155724; border-left: 8px solid #28a745; }}
        .verdict-warnings {{ background-color: #fff3cd; color: #856404; border-left: 8px solid #ffc107; }}
        .verdict-not-ready {{ background-color: #f8d7da; color: #721c24; border-left: 8px solid #dc3545; }}
        .summary {{ background-color: white; padding: 20px; margin: 20px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 15px; }}
        .summary-item {{ text-align: center; padding: 15px; border-radius: 5px; }}
        .passed {{ background-color: #d4edda; color: #155724; }}
        .failed {{ background-color: #f8d7da; color: #721c24; }}
        .warning {{ background-color: #fff3cd; color: #856404; }}
        .notconfigured {{ background-color: #e7e7e7; color: #666; }}
        .manual {{ background-color: #cce5ff; color: #004085; }}
        .skipped {{ background-color: #e7e7e7; color: #666; }}
        .errored {{ background-color: #f8d7da; color: #721c24; }}
        /* Each section gets its own card. The <details> element is
           used so the operator can collapse PASSED to reduce noise;
           ACTION REQUIRED and MANUAL stay open by default because the
           operator's job is to look at every row. */
        .section {{ background-color: white; padding: 20px; margin: 20px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .section summary {{ cursor: pointer; outline: none; }}
        .section h2 {{ display: inline-block; margin: 0; font-size: 20px; }}
        .section .count-badge {{ display: inline-block; margin-left: 10px; padding: 2px 10px; border-radius: 12px; font-size: 14px; font-weight: bold; vertical-align: middle; }}
        .section .subtitle {{ margin: 8px 0 16px 0; color: #555; font-size: 13px; }}
        .section .empty-note {{ padding: 12px; background-color: #f5f5f5; border-radius: 4px; color: #555; font-style: italic; }}
        #section-action .count-badge {{ background-color: #f8d7da; color: #721c24; }}
        #section-manual .count-badge {{ background-color: #cce5ff; color: #004085; }}
        #section-passed .count-badge {{ background-color: #d4edda; color: #155724; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th {{ background-color: #0078d4; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px; border-bottom: 1px solid #ddd; vertical-align: top; word-wrap: break-word; overflow-wrap: break-word; }}
        /* cell-text preserves authored line breaks AND leading
           whitespace, so multi-line result/remediation strings (e.g.
           AUTH-006's "Detected apps:" list and "Step 1 / Step 2"
           sub-steps) render as written instead of collapsing into a
           wall of text. Applied only to the result + remediation
           cells; the other cells stay single-line. */
        td.cell-text {{ white-space: pre-wrap; line-height: 1.5; }}
        tr:hover {{ background-color: #f5f5f5; }}
        .status-passed {{ color: #28a745; font-weight: bold; }}
        .status-failed {{ color: #dc3545; font-weight: bold; }}
        .status-warning {{ color: #ffc107; font-weight: bold; }}
        .status-notconfigured {{ color: #6c757d; font-weight: bold; }}
        .status-manual {{ color: #004085; font-weight: bold; }}
        .priority-critical {{ background-color: #ffe6e6; }}
        .priority-high {{ background-color: #fff4e6; }}
        .footer {{ margin-top: 20px; text-align: center; color: #666; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>ESS Pre-flight Deployment Validation Report</h1>
        <p>Generated: {r.started}</p>
        <p>Validation Scope: {r.scope} | Duration: {r.duration_secs}s</p>
    </div>

    <div class="verdict {verdict_class}">
        <div class="verdict-icon">{verdict_icon}</div>
        <div class="verdict-text">
            <h2>{verdict_headline}</h2>
            <p>{verdict_sub}</p>
        </div>
    </div>

    <div class="summary">
        <h2>Validation Summary</h2>
        <div class="summary-grid">
            <div class="summary-item failed">
                <h3>{r.failed}</h3>
                <p>Failed</p>
            </div>
            <div class="summary-item errored">
                <h3>{r.errors}</h3>
                <p>Errored</p>
            </div>
            <div class="summary-item warning">
                <h3>{r.warnings}</h3>
                <p>Warnings</p>
            </div>
            <div class="summary-item manual">
                <h3>{r.manual}</h3>
                <p>Manual</p>
            </div>
            <div class="summary-item notconfigured">
                <h3>{r.not_configured}</h3>
                <p>Not Configured</p>
            </div>
            <div class="summary-item skipped">
                <h3>{r.skipped}</h3>
                <p>Skipped</p>
            </div>
            <div class="summary-item passed">
                <h3>{r.passed}</h3>
                <p>Passed</p>
            </div>
        </div>
    </div>

{action_section}

{manual_section}

{passed_section}

    <div class="footer">
        <p>ESS Maker Kit &mdash; FlightCheck v1.0</p>
        <p>For more information, visit: <a href="https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/">Microsoft Learn - Employee Self-Service</a></p>
    </div>
</body>
</html>"""


def _verdict_text(r: RunResult) -> tuple[str, str, str, str]:
    """Return (css_class, icon, headline, subline) for the verdict banner.

    Drives the single biggest signal on the page, so word choice
    matters: the headline answers "is my deployment OK?" in five
    words or less; the subline says exactly what to do next.

    Section pointers in the subline reflect the bucket model:
    Failed / Error live under "Action required"; Warning / Manual /
    NotConfigured live under "Needs manual verification". Pointing
    operators at the right section is the whole reason the verdict
    has a subline.
    """
    failing = r.failed + r.errors
    manual_count = r.warnings + r.manual + r.not_configured

    if r.overall == "READY":
        if manual_count:
            sub = (
                f"All {r.passed} automated check(s) passed. "
                f"{manual_count} item(s) need manual verification \u2014 "
                "see \u201cNeeds manual verification\u201d below."
            )
        else:
            sub = (
                f"All {r.passed} check(s) passed. Your environment "
                "looks ready to deploy."
            )
        return ("verdict-ready", "\u2713", "Ready for deployment", sub)

    if r.overall == "READY_WITH_WARNINGS":
        sub = (
            f"{r.warnings} warning(s) found. Review each one in "
            "\u201cNeeds manual verification\u201d below and confirm "
            "it\u2019s acceptable before deploying."
        )
        return (
            "verdict-warnings",
            "\u26a0",
            "Ready with warnings",
            sub,
        )

    # NOT_READY (or any unrecognized overall) — treat as a blocker.
    # Headline counts failures/errors as the truly blocking items;
    # warnings (now in the manual section) are mentioned in the
    # subline so the operator knows their scale without thinking
    # they're additional blockers.
    issue_word = "issue" if failing == 1 else "issues"
    if r.warnings:
        sub = (
            f"{failing} failing/errored check(s) need action; "
            f"{r.warnings} warning(s) need manual verification. "
            "Start with \u201cAction required\u201d below."
        )
    else:
        sub = (
            f"{failing} failing/errored check(s) need action. "
            "See \u201cAction required\u201d below."
        )
    return (
        "verdict-not-ready",
        "\u2717",
        f"Not ready \u2014 {failing} {issue_word} need attention",
        sub,
    )


def _render_rows(results: list[CheckResult]) -> str:
    """Render the <tr> rows for a list of results."""
    rows = []
    for res in results:
        status_class = {
            Status.PASSED.value: "status-passed",
            Status.FAILED.value: "status-failed",
            Status.WARNING.value: "status-warning",
            Status.NOT_CONFIGURED.value: "status-notconfigured",
            Status.SKIPPED.value: "status-notconfigured",
            Status.ERROR.value: "status-failed",
            Status.MANUAL.value: "status-manual",
        }.get(res.status, "")

        priority_class = {
            Priority.CRITICAL.value: "priority-critical",
            Priority.HIGH.value: "priority-high",
        }.get(res.priority, "")

        remediation = _md_links_to_html(res.remediation or "")
        if res.doc_link:
            remediation += f' <a href="{res.doc_link}" target="_blank">[docs]</a>'

        # The Role column names who owns the next step (fix / manual
        # validation). It only applies to actionable rows — a Passed or
        # Skipped check has no next step, so its Role cell is blank.
        actionable = res.status not in (Status.PASSED.value, Status.SKIPPED.value)
        roles_text = _html_escape(", ".join(res.roles)) if (actionable and res.roles) else "—"

        rows.append(
            f'                <tr class="{priority_class}">\n'
            f"                    <td>{res.checkpoint_id}</td>\n"
            f"                    <td>{res.category}</td>\n"
            f"                    <td>{res.priority}</td>\n"
            f'                    <td class="{status_class}">{res.status}</td>\n'
            f"                    <td>{roles_text}</td>\n"
            f'                    <td class="cell-text">{_html_escape(res.result)}</td>\n'
            f'                    <td class="cell-text">{remediation}</td>\n'
            f"                </tr>"
        )
    return "\n".join(rows)


def _render_section(
    *,
    section_id: str,
    title: str,
    subtitle: str,
    empty_text: str,
    rows_html: str,
    count: int,
    open_by_default: bool,
) -> str:
    """Render one of the 3 result sections as a <details> block.

    When the section is empty we still render the section card but
    swap the table for a friendly "nothing here" note so the operator
    sees at a glance that the kit checked the bucket and found
    nothing to flag.
    """
    open_attr = " open" if open_by_default else ""
    if count == 0:
        body = f'        <div class="empty-note">{empty_text}</div>'
    else:
        body = (
            '        <table>\n'
            '            <thead>\n'
            '                <tr>\n'
            '                    <th>Checkpoint</th>\n'
            '                    <th>Category</th>\n'
            '                    <th>Priority</th>\n'
            '                    <th>Status</th>\n'
            '                    <th>Role</th>\n'
            '                    <th>Result</th>\n'
            '                    <th>Remediation</th>\n'
            '                </tr>\n'
            '            </thead>\n'
            '            <tbody>\n'
            f"{rows_html}\n"
            '            </tbody>\n'
            '        </table>'
        )

    return (
        f'    <details id="{section_id}" class="section"{open_attr}>\n'
        f'        <summary><h2>{title}</h2>'
        f'<span class="count-badge">{count}</span></summary>\n'
        f'        <p class="subtitle">{subtitle}</p>\n'
        f'{body}\n'
        '    </details>'
    )


def _html_escape(text: str) -> str:
    """Basic HTML escaping."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _md_links_to_html(text: str) -> str:
    """Convert markdown links [text](url) to HTML <a> tags with target=_blank."""
    import re
    escaped = _html_escape(text)
    # Now convert markdown links (which got escaped) back to real HTML links
    # The escaping turned [text](url) into [text](url) since [] and () aren't escaped
    return re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        r'<a href="\2" target="_blank">\1</a>',
        escaped,
    )
