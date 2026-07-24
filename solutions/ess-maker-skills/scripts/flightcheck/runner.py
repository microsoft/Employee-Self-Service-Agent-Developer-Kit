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
    doc_label: str = ""    # Link text for doc_link; falls back to "Docs"
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

    def __init__(self, scope: str = "full", target_matcher: Callable | None = None):
        self.scope = scope
        self.results: list[CheckResult] = []
        self._check_fns: list[tuple[str, Callable]] = []
        # Single-checkpoint mode (--checkpoint). When set, run() hydrates by
        # executing the registered prerequisite category functions in full,
        # then filters self.results down to the rows the matcher accepts (the
        # target checkpoint, or every member of a target family) before the
        # summary/verdict is built. None = normal full/scope run (no filter).
        self._target_matcher: Callable | None = target_matcher
        # Standalone-scope target selection (set by cli.py's
        # _resolve_target_selection in scope mode only). Pins the
        # ServiceNow connection SN-CONN-* should scope to; None ⇒ validate
        # every matching connection (legacy behavior). The Workday SSO-app
        # equivalent is carried on ``config["entraAppId"]`` instead, so it
        # flows through the existing ``_workday_hints`` path all Workday-app
        # checks already read. Single-checkpoint mode never sets these.
        self.servicenow_connection_pin: str | None = None

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

        # Single-checkpoint mode: the prerequisite category functions ran in
        # full to hydrate shared state; now keep only the rows belonging to the
        # requested target so the summary, verdict, and exit code reflect just
        # that checkpoint. A synthetic "{CAT}-ERR" sentinel (appended above when
        # a category function raised) is always kept so a hydration/owner
        # failure surfaces as an error instead of an empty, falsely-green run.
        if self._target_matcher is not None:
            self.results = [
                r for r in self.results
                if self._target_matcher(r.checkpoint_id)
                or r.checkpoint_id.endswith("-ERR")
            ]

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
    """Generate the category-grouped HTML report.

    Layout (top to bottom):
      - Header with scope / timestamp / duration and the verdict banner
        (green / amber / red) driven by ``_verdict_text``.
    - A collapsed "How to read this report" guide (below the verdict).
    - Action items panel: blocking failures/errors to fix, plus the
      warnings to review. Each links to its check card below. When the
      run has no blockers and no warnings, this becomes an "all clear"
      note instead.
    - Readiness at a glance: per-status totals plus one tile per
      category, coloured by the worst status in that category and
      linking to the category section.
    - Filter bar (All / Failed / Warnings / Manual / Passed) and
      Fold all / Unfold all controls.
    - One collapsible section per category (in ``RunResult.categories``
      order), each containing one card per check. Categories with any
      Failed/Error/Warning/Manual/NotConfigured row open by default;
      all-passing categories stay collapsed. Manual cards carry a
      per-run completion checklist built from their real remediation
      steps.

    Everything is derived from ``RunResult`` — no fabricated content.
    The bucket helpers (``bucket_results`` / ``_sort_key``) are reused
    only to order the action panel and to sort checks within a category.
    """
    buckets = bucket_results(r.results)

    verdict_class, verdict_icon, verdict_headline, verdict_sub = _verdict_text(r)

    categories = _group_by_category(r)
    sections_html = _render_sections(categories)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en" dir="ltr">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f"<title>FlightCheck Report \u2014 {_html_escape(r.scope)} scope</title>\n"
        f"<style>{_REPORT_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="wrap">\n'
        + _render_header(
            r, verdict_class, verdict_icon, verdict_headline, verdict_sub
        )
        + _render_howto()
        + _render_action_panel(buckets)
        + _render_synopsis(r, categories)
        + _FILTER_BAR
        + _VIEW_TOOLS
        + sections_html
        + _render_footer()
        + "</div>\n"
        f"<script>{_REPORT_SCRIPT}</script>\n"
        "</body>\n"
        "</html>"
    )


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


# ---------------------------------------------------------------------------
# HTML rendering — category-grouped card layout.
#
# The CSS and JS below are lifted verbatim from the approved design mockup
# so the generated report matches it pixel-for-pixel. They live in module
# constants (plain strings, NOT f-strings) so their many `{ }` braces need
# no escaping; only the small dynamic fragments below use f-strings.
# ---------------------------------------------------------------------------

# CSS copied verbatim from the approved design mockup, then extended with a
# few override rules for the verdict banner (the mockup hard-codes a red pill;
# we colour it by outcome) and the "all clear" action panel. Plain string so
# the braces stay literal.
_REPORT_CSS = """
  :root{
    --bg:#f4f5f7; --surface:#ffffff; --ink:#1a1c1f; --muted:#5b6168;
    --line:#e2e5e9; --line-strong:#cbd0d6;
    --pass:#1a7f37; --pass-bg:#e7f4ec; --pass-line:#a9d6b8;
    --fail:#b42318; --fail-bg:#fbeae8; --fail-line:#f0b4ac;
    --warn:#9a6700; --warn-bg:#fbf3e0; --warn-line:#eccf8f;
    --manual:#4a4f55; --manual-bg:#eceef0; --manual-line:#cdd2d8;
    --na:#5b6168; --na-bg:#eef0f2; --na-line:#d3d8de;
    --accent:#b8501e; --accent-ink:#ffffff;
    --code-bg:#1f2429; --code-ink:#e8edf2;
    --chip:#eef0f2; --shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.1);
    --radius:10px;
  }
  @media (prefers-color-scheme: dark){
    :root{
      --bg:#15171a; --surface:#1d2024; --ink:#e8ecf1; --muted:#9aa1a9;
      --line:#2b2f35; --line-strong:#3a3f46;
      --pass:#5fd07f; --pass-bg:#10261a; --pass-line:#1f4d31;
      --fail:#ff7a6b; --fail-bg:#2a1311; --fail-line:#5a241e;
      --warn:#e7b75a; --warn-bg:#2a2008; --warn-line:#574412;
      --manual:#b6bdc5; --manual-bg:#22262b; --manual-line:#393f46;
      --na:#9aa1a9; --na-bg:#202428; --na-line:#363c43;
      --accent:#d9743f; --accent-ink:#15171a;
      --code-bg:#0e1114; --code-ink:#dce3ea;
      --chip:#262a2f;
    }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
  .wrap{max-width:1080px;margin:0 auto;padding:24px 20px 64px}
  a{color:var(--accent);text-decoration:none}
  a:hover{text-decoration:underline}
  code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}

  /* Header / verdict */
  header.report{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);overflow:hidden;margin-bottom:18px}
  .bar{height:6px;background:var(--accent)}
  .head-pad{padding:20px 22px}
  .eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:600}
  h1{font-size:22px;margin:4px 0 2px}
  .meta{color:var(--muted);font-size:13px;margin-top:6px}
  .meta b{color:var(--ink);font-weight:600}
  .verdict-note{display:block;margin-top:10px;color:var(--muted);font-size:13.5px;max-width:78ch}

  /* Filters */
  .filters{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}
  .filters button{font:inherit;font-size:13px;cursor:pointer;border:1px solid var(--line-strong);background:var(--surface);
    color:var(--ink);padding:6px 12px;border-radius:999px}
  .filters button[aria-pressed="true"]{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}

  /* Sections */
  details.sec{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);margin-bottom:12px;overflow:hidden}
  details.sec>summary{list-style:none;cursor:pointer;padding:14px 18px;display:flex;align-items:center;gap:12px;
    font-weight:650;font-size:15.5px}
  details.sec>summary::-webkit-details-marker{display:none}
  .sec .stage-no{width:24px;height:24px;border-radius:6px;background:var(--chip);color:var(--muted);
    display:inline-flex;align-items:center;justify-content:center;font-size:12.5px;font-weight:700;flex:none}
  summary .spacer{flex:1}
  .mini{display:inline-flex;gap:6px;align-items:center;font-weight:600;font-size:12.5px;color:var(--muted)}
  .mini .b{padding:2px 7px;border-radius:999px;border:1px solid var(--line-strong)}
  .mini .b.fail{color:var(--fail);background:var(--fail-bg);border-color:var(--fail-line)}
  .mini .b.warn{color:var(--warn);background:var(--warn-bg);border-color:var(--warn-line)}
  .mini .b.pass{color:var(--pass);background:var(--pass-bg);border-color:var(--pass-line)}
  .sec-body{border-top:1px solid var(--line);padding:6px 0 4px}
  /* Per-agent nesting: base subgroups inside one agent section. */
  .subsec{border-top:1px solid var(--line)}
  .subsec:first-child{border-top:none}
  .subhead{display:flex;align-items:center;gap:12px;padding:11px 18px;font-weight:650;
    font-size:13.5px;color:var(--ink);background:var(--bg)}

  /* Check rows */
  .check{padding:14px 18px;border-bottom:1px solid var(--line)}
  .check:last-child{border-bottom:none}
  .check-head{display:flex;align-items:flex-start;gap:12px}
  .pill{flex:none;font-size:11.5px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;
    padding:3px 9px;border-radius:999px;border:1px solid;margin-top:1px;white-space:nowrap}
  .pill.pass{color:var(--pass);background:var(--pass-bg);border-color:var(--pass-line)}
  .pill.fail{color:var(--fail);background:var(--fail-bg);border-color:var(--fail-line)}
  .pill.warn{color:var(--warn);background:var(--warn-bg);border-color:var(--warn-line)}
  .pill.manual{color:var(--manual);background:var(--manual-bg);border-color:var(--manual-line)}
  .pill.na{color:var(--na);background:var(--na-bg);border-color:var(--na-line)}
  .check-title{font-weight:650;flex:1}
  .check-title .id{font-weight:600;color:var(--muted);font-size:12.5px;font-family:ui-monospace,monospace;margin-inline-start:6px}
  .role{flex:none;font-size:12px;color:var(--muted);border:1px dashed var(--line-strong);border-radius:6px;padding:2px 8px;margin-top:1px}
  .kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:10px 0 0 0;font-size:13.5px}
  .kv dt{color:var(--muted)} .kv dd{margin:0}
  pre.err{background:var(--code-bg);color:var(--code-ink);border-radius:8px;padding:12px 14px;margin:10px 0 0;
    font-size:12px;line-height:1.55;overflow-x:auto;white-space:pre}
  .next{margin:10px 0 0;font-size:13.5px}
  .next b{font-weight:650}
  .actions{margin-top:10px;display:flex;flex-wrap:wrap;gap:8px}
  .btn{font-size:12.5px;font-weight:600;border-radius:7px;padding:6px 11px;border:1px solid;display:inline-flex;gap:6px;align-items:center}
  .btn.link{background:var(--surface);color:var(--accent);border-color:var(--line-strong)}

  footer{margin-top:26px;color:var(--muted);font-size:12.5px;line-height:1.6}
  footer h3{font-size:13px;color:var(--ink);margin:0 0 6px}
  .grid-note{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px 18px;box-shadow:var(--shadow)}
  .legend{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 4px}
  .legend span{font-size:12px;color:var(--muted);display:inline-flex;gap:6px;align-items:center}
  .sw{width:10px;height:10px;border-radius:3px;display:inline-block}
  .hidden{display:none !important}

  /* Collapsed "how to read this" guide (below the verdict). */
  details.howto{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);margin:0 0 16px;overflow:hidden}
  details.howto>summary{list-style:none;cursor:pointer;padding:12px 18px;font-weight:650;font-size:14px;
    display:flex;align-items:center;gap:8px}
  details.howto>summary::-webkit-details-marker{display:none}
  details.howto>summary::before{content:"\\25B8";color:var(--muted);font-size:12px}
  details.howto[open]>summary::before{content:"\\25BE"}
  .howto-body{border-top:1px solid var(--line);padding:12px 18px;font-size:13px;color:var(--muted);line-height:1.6}
  .howto-body b{color:var(--ink)}

  /* View tools: fold / unfold all sections. */
  .viewtools{display:flex;gap:8px;margin:0 0 16px;justify-content:flex-end}
  .viewtools button{font:inherit;font-size:12.5px;font-weight:600;cursor:pointer;
    border:1px solid var(--line-strong);background:var(--surface);color:var(--ink);
    border-radius:7px;padding:6px 12px}
  .viewtools button:hover{border-color:var(--accent)}

  /* Manual completion checklist (per-run, not persisted). */
  .checklist{margin:12px 0 2px;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--surface)}
  .cl-head{display:flex;align-items:center;gap:10px;padding:9px 12px;background:var(--manual-bg);
    border-bottom:1px solid var(--line);font-size:12.5px;font-weight:650;color:var(--ink)}
  .cl-head .cl-count{margin-inline-start:auto;font-size:12px;font-weight:600;color:var(--muted);
    border:1px solid var(--line-strong);border-radius:999px;padding:1px 9px}
  .cl-head .cl-count.done{color:var(--pass);border-color:var(--pass-line);background:var(--pass-bg)}
  .cl-note{padding:6px 12px;font-size:11.5px;color:var(--muted);border-bottom:1px solid var(--line);font-style:italic}
  .cl-item{display:flex;gap:10px;align-items:flex-start;padding:9px 12px;border-bottom:1px solid var(--line);
    cursor:pointer;font-size:13px;color:var(--ink)}
  .cl-item:last-child{border-bottom:none}
  .cl-item:hover{background:var(--bg)}
  .cl-item input{margin:2px 0 0;width:15px;height:15px;accent-color:var(--pass);flex:none;cursor:pointer}
  .cl-item code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:12px}
  .cl-item.done{color:var(--muted)}
  .cl-item.done .cl-text{text-decoration:line-through}

  /* Action items panel */
  .actions-panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);padding:16px 18px;margin:0 0 16px;border-inline-start:4px solid var(--fail)}
  .ap-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;margin-bottom:12px}
  .ap-head h2{font-size:16px;margin:0}
  .ap-sub{color:var(--muted);font-size:13px}
  .ap-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
  .ap-item{display:flex;gap:12px;align-items:flex-start;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg)}
  .ap-pri{flex:none;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.03em;
    padding:3px 9px;border-radius:999px;border:1px solid;margin-top:1px;white-space:nowrap;
    color:var(--fail);background:var(--fail-bg);border-color:var(--fail-line)}
  .ap-pri.critical{color:var(--fail);background:var(--fail-bg);border-color:var(--fail-line)}
  .ap-pri.high{color:var(--warn);background:var(--warn-bg);border-color:var(--warn-line)}
  .ap-pri.medium{color:var(--manual);background:var(--manual-bg);border-color:var(--manual-line)}
  .ap-pri.low{color:var(--na);background:var(--na-bg);border-color:var(--na-line)}
  .ap-title{font-weight:650;font-size:14px}
  .ap-title .id{font-family:ui-monospace,monospace;font-size:12px;color:var(--muted);font-weight:600;margin-inline-start:6px}
  .ap-meta{color:var(--muted);font-size:12.5px;margin-top:3px}
  .ap-review{margin:12px 0 0;padding-top:10px;border-top:1px dashed var(--line-strong);font-size:13px;color:var(--muted)}
  .ap-review b{color:var(--ink)}
  .ap-review ul{margin:6px 0 0;padding-inline-start:18px}
  .ap-review li{margin:3px 0}

  /* Visual synopsis — traffic-light pipeline */
  .synopsis{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);padding:16px 18px;margin:0 0 16px}
  .syn-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;margin-bottom:6px}
  .syn-head h2{font-size:16px;margin:0}
  .syn-head .hint{color:var(--muted);font-size:12.5px}
  .dot{width:11px;height:11px;border-radius:50%;display:inline-block;flex:none}
  .dot.red{background:var(--fail)} .dot.amber{background:var(--warn)}
  .dot.green{background:var(--pass)} .dot.gray{background:var(--manual)}
  .syn-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
  @media (max-width:760px){.syn-grid{grid-template-columns:repeat(2,1fr)}}
  .syn-tile{display:block;text-decoration:none;color:inherit;border:1px solid var(--line);border-radius:9px;
    padding:10px 12px;background:var(--bg);transition:border-color .12s,transform .12s}
  .syn-tile:hover{text-decoration:none;border-color:var(--line-strong);transform:translateY(-1px)}
  .syn-tile:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .syn-tile.red{border-inline-start:3px solid var(--fail)}
  .syn-tile.amber{border-inline-start:3px solid var(--warn)}
  .syn-tile.green{border-inline-start:3px solid var(--pass)}
  .syn-tile.gray{border-inline-start:3px solid var(--manual)}
  .syn-top{display:flex;align-items:center;gap:8px}
  .syn-no{font-size:11px;font-weight:700;color:var(--muted)}
  .syn-name{font-weight:650;font-size:13px;line-height:1.25;margin-top:6px}
  .syn-role{font-size:11.5px;color:var(--muted);margin-top:5px;min-height:1em}
  .syn-role.act{color:var(--ink);font-weight:600}
  .syn-rollup{margin-top:12px;padding-top:10px;border-top:1px dashed var(--line-strong);font-size:12.5px;color:var(--muted)}
  .syn-rollup b{color:var(--ink)}
  .syn-stats{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 14px}
  .syn-stats .stat{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;color:var(--muted);
    border:1px solid var(--line);border-radius:999px;padding:4px 11px;background:var(--bg)}
  .syn-stats .stat b{font-size:14px;font-weight:700;color:var(--ink)}
  .syn-stats .stat.pass b{color:var(--pass)}
  .syn-stats .stat.fail b{color:var(--fail)}
  .syn-stats .stat.warn b{color:var(--warn)}
  .syn-stats .stat.manual b{color:var(--manual)}
  .syn-stats .stat.na b{color:var(--na)}

  /* Verdict banner — coloured by run outcome (overrides the mockup pill). */
  .verdict{display:flex;align-items:flex-start;gap:12px;margin-top:14px;padding:14px 18px;
    border-radius:var(--radius);font-weight:700;font-size:16px;border:1px solid}
  .verdict-icon{font-size:20px;line-height:1.2;flex:none}
  .verdict-text h2{font-size:17px;margin:0}
  .verdict-text p.verdict-note{display:block;margin:6px 0 0;font-weight:500;font-size:13.5px;color:inherit;opacity:.85;max-width:78ch}
  .verdict-ready{background:var(--pass-bg);color:var(--pass);border-color:var(--pass-line)}
  .verdict-warnings{background:var(--warn-bg);color:var(--warn);border-color:var(--warn-line)}
  .verdict-not-ready{background:var(--fail-bg);color:var(--fail);border-color:var(--fail-line)}
  .actions-panel.allclear{border-inline-start-color:var(--pass)}
"""

# Progressive-enhancement JS: anchor-jump that opens the target <details>,
# the status filter bar, fold/unfold-all controls, and the manual completion
# checklists. The checklists are per-run only (no localStorage persistence)
# and are built from real CheckResult.remediation steps, so nothing is
# fabricated.
_REPORT_SCRIPT = """
  // Progressive enhancement only — the report is fully readable without JS.

  // Synopsis markers + action links open the target stage, then scroll to it.
  (function(){
    function openTarget(hash){
      if(!hash || hash.length < 2) return;
      var el = document.getElementById(hash.slice(1));
      if(!el) return;
      if(el.tagName === 'DETAILS'){ el.open = true; }
      var d = el.parentElement;
      while(d){ if(d.tagName === 'DETAILS'){ d.open = true; } d = d.parentElement; }
      el.scrollIntoView({behavior:'smooth', block:'start'});
    }
    document.addEventListener('click', function(e){
      var a = e.target.closest && e.target.closest('a[href^="#"]');
      if(!a) return;
      var hash = a.getAttribute('href');
      if(hash && hash.length > 1){ e.preventDefault(); openTarget(hash); if(history.replaceState){ history.replaceState(null,'',hash); } }
    });
    if(location.hash){ openTarget(location.hash); }
  })();

  (function(){
    var bar = document.getElementById('filters');
    if(!bar) return;
    bar.hidden = false;
    var checks = Array.prototype.slice.call(document.querySelectorAll('.check'));
    var secs = Array.prototype.slice.call(document.querySelectorAll('details.sec'));
    var subsecs = Array.prototype.slice.call(document.querySelectorAll('.subsec'));
    bar.addEventListener('click', function(e){
      var btn = e.target.closest('button'); if(!btn) return;
      var f = btn.getAttribute('data-f');
      bar.querySelectorAll('button').forEach(function(b){ b.setAttribute('aria-pressed', b===btn ? 'true':'false'); });
      checks.forEach(function(c){
        c.classList.toggle('hidden', !(f==='all' || c.getAttribute('data-s')===f));
      });
      // hide agent subgroups that have no visible rows under the active filter
      subsecs.forEach(function(ss){
        var anyVisible = ss.querySelector('.check:not(.hidden)');
        ss.classList.toggle('hidden', f!=='all' && !anyVisible);
      });
      // open sections that still have visible rows; collapse empty ones
      secs.forEach(function(s){
        var anyVisible = s.querySelector('.check:not(.hidden)');
        if(f!=='all'){ s.open = !!anyVisible; }
      });
    });
  })();

  // Fold all / Unfold all — open or collapse every category section at once.
  (function(){
    var vt = document.getElementById('viewtools');
    if(!vt) return;
    vt.hidden = false;
    var secs = Array.prototype.slice.call(document.querySelectorAll('details.sec'));
    var unfold = document.getElementById('unfoldAll');
    var fold = document.getElementById('foldAll');
    if(unfold){ unfold.addEventListener('click', function(){ secs.forEach(function(s){ s.open = true; }); }); }
    if(fold){ fold.addEventListener('click', function(){ secs.forEach(function(s){ s.open = false; }); }); }
  })();

  // Manual completion checklists — live counter, per-run only (not saved).
  (function(){
    var lists = Array.prototype.slice.call(document.querySelectorAll('.checklist'));
    lists.forEach(function(list){
      var items = Array.prototype.slice.call(list.querySelectorAll('.cl-item'));
      var count = list.querySelector('.cl-count');
      function update(){
        var done = 0;
        items.forEach(function(it){
          var box = it.querySelector('input');
          var on = !!(box && box.checked);
          it.classList.toggle('done', on);
          if(on){ done++; }
        });
        if(count){
          count.textContent = done + ' / ' + items.length;
          count.classList.toggle('done', done === items.length && items.length > 0);
        }
      }
      items.forEach(function(it){
        var box = it.querySelector('input');
        if(box){ box.addEventListener('change', update); }
      });
      update();
    });
  })();
"""

# Filter bar markup. Rendered hidden; the filter IIFE un-hides it when JS runs
# so the no-JS view shows all rows without a dead control.
_FILTER_BAR = (
    '  <div class="filters" id="filters" hidden>\n'
    '    <button data-f="all" aria-pressed="true">All</button>\n'
    '    <button data-f="fail">Failed</button>\n'
    '    <button data-f="warn">Warnings</button>\n'
    '    <button data-f="manual">Manual</button>\n'
    '    <button data-f="pass">Passed</button>\n'
    '  </div>\n'
)

# Fold/unfold-all controls. Hidden until the fold IIFE un-hides them, so the
# no-JS view isn't left with dead buttons (each section is a native <details>
# the reader can still toggle by hand).
_VIEW_TOOLS = (
    '  <div class="viewtools" id="viewtools" hidden>\n'
    '    <button id="unfoldAll" type="button">Unfold all</button>\n'
    '    <button id="foldAll" type="button">Fold all</button>\n'
    '  </div>\n'
)


# Maps a CheckResult.status to (pill CSS class, human label, data-s filter
# key). data-s drives the filter bar: pass/fail/warn/manual/na. Skipped and
# NotConfigured share the neutral "na" bucket (reachable only via "All").
_STATUS_STYLE = {
    Status.PASSED.value: ("pass", "Pass", "pass"),
    Status.FAILED.value: ("fail", "Fail", "fail"),
    Status.ERROR.value: ("fail", "Error", "fail"),
    Status.WARNING.value: ("warn", "Warning", "warn"),
    Status.MANUAL.value: ("manual", "Manual", "manual"),
    Status.NOT_CONFIGURED.value: ("na", "Not configured", "na"),
    Status.SKIPPED.value: ("na", "Skipped", "na"),
}


def _slug(text: str) -> str:
    """Turn a category name or checkpoint id into a stable anchor slug."""
    import re
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "item"


def _base_category(category: str) -> str:
    """Collapse a per-agent category to its base name for the synopsis.

    FlightCheck scans every agent under ``workspace/agents/``, so many
    categories arrive suffixed with the agent name, e.g.
    ``"Topics (Contoso HR)"``. The readiness synopsis rolls these up to a
    single tile per base name (``"Topics"``) so the at-a-glance grid stays
    compact regardless of how many agents were scanned. Categories with no
    trailing ``"(...)"`` suffix (shared infra / prerequisite checks) pass
    through unchanged.
    """
    import re
    return re.sub(r"\s*\([^()]*\)\s*$", "", category).strip() or category


# Base category names that FlightCheck emits once per scanned agent, suffixed
# with the agent name, e.g. "Topics (Contoso HR)". The detail view nests these
# under a single section per agent instead of listing every agent x base pair
# as a flat sibling, which otherwise explodes to ~20 sections for a 5-agent run.
_AGENT_SCOPED_BASES = ("Configuration", "Topics", "Knowledge Sources", "Template Configs")


def _split_agent(category: str) -> tuple[str, str | None]:
    """Split ``"<Base> (<Agent>)"`` into ``(base, agent)`` for agent-scoped
    categories; return ``(category, None)`` for tenant-wide categories.

    Only the known per-agent bases are treated as agent-scoped so that a
    tenant category that happens to carry a trailing parenthetical is left
    intact.
    """
    import re
    match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", category)
    if not match:
        return category, None
    base, agent = match.group(1).strip(), match.group(2).strip()
    if base in _AGENT_SCOPED_BASES and agent:
        return base, agent
    return category, None


def _status_minis(results: list[CheckResult]) -> tuple[str, bool]:
    """Build the "N fail / N warn / N manual / N ok" mini badges for a group.

    Returns the badge HTML and whether the group has any actionable row
    (fail/error/warning/manual/not-configured) so callers can decide
    whether to open the section by default.
    """
    n_fail = sum(
        1 for x in results
        if x.status in (Status.FAILED.value, Status.ERROR.value)
    )
    n_warn = sum(1 for x in results if x.status == Status.WARNING.value)
    n_other = sum(
        1 for x in results
        if x.status in (Status.MANUAL.value, Status.NOT_CONFIGURED.value)
    )
    n_ok = sum(
        1 for x in results
        if x.status in (Status.PASSED.value, Status.SKIPPED.value)
    )
    minis = []
    if n_fail:
        minis.append(f'<span class="b fail">{n_fail} fail</span>')
    if n_warn:
        minis.append(f'<span class="b warn">{n_warn} warn</span>')
    if n_other:
        minis.append(f'<span class="b">{n_other} manual</span>')
    if n_ok:
        minis.append(f'<span class="b pass">{n_ok} ok</span>')
    return "".join(minis), bool(n_fail or n_warn or n_other)


def _group_by_category(r: RunResult) -> list[tuple[str, list[CheckResult]]]:
    """Group results by category, ordered per RunResult.categories.

    Within each category results are sorted with the shared _sort_key
    (priority -> status -> id). Any category present in results but not
    in r.categories is appended in first-seen order so nothing is lost.
    """
    by_cat: dict[str, list[CheckResult]] = {}
    for res in r.results:
        by_cat.setdefault(res.category, []).append(res)

    ordered: list[tuple[str, list[CheckResult]]] = []
    seen: set[str] = set()
    for summary in r.categories:
        name = summary.category
        if name in by_cat and name not in seen:
            ordered.append((name, sorted(by_cat[name], key=_sort_key)))
            seen.add(name)
    for name, items in by_cat.items():
        if name not in seen:
            ordered.append((name, sorted(items, key=_sort_key)))
            seen.add(name)
    return ordered


def _category_color(results: list[CheckResult]) -> str:
    """Worst-status colour for a category tile: red > amber > gray > green."""
    statuses = [x.status for x in results]
    if any(s in (Status.FAILED.value, Status.ERROR.value) for s in statuses):
        return "red"
    if any(s == Status.WARNING.value for s in statuses):
        return "amber"
    if any(
        s in (Status.MANUAL.value, Status.NOT_CONFIGURED.value)
        for s in statuses
    ):
        return "gray"
    return "green"


def _category_roles(results: list[CheckResult]) -> list[str]:
    """Distinct roles across the actionable results in a category."""
    roles: list[str] = []
    for x in results:
        if x.status in (Status.PASSED.value, Status.SKIPPED.value):
            continue
        for role in x.roles:
            if role not in roles:
                roles.append(role)
    return roles


def _render_header(
    r: RunResult,
    verdict_class: str,
    verdict_icon: str,
    verdict_headline: str,
    verdict_sub: str,
) -> str:
    """Report header: eyebrow, title, run meta, and the verdict banner.

    The verdict banner keeps the same DOM shape as before
    (``<div class="verdict {class}"> ... <h2>{headline}</h2>
    <p class="verdict-note">{sub}</p> ...``) because the layout tests
    pin those hooks and the wording comes straight from _verdict_text.
    """
    return (
        '  <header class="report">\n'
        '    <div class="bar"></div>\n'
        '    <div class="head-pad">\n'
        f'      <div class="eyebrow">FlightCheck \u00b7 '
        f'{_html_escape(r.scope)} deployment readiness</div>\n'
        '      <h1>Deployment Readiness Report</h1>\n'
        '      <div class="meta">\n'
        f'        Scope <b>{_html_escape(r.scope)}</b> \u00b7 '
        f'Run <b>{_html_escape(r.started)}</b> \u00b7 '
        f'Completed in <b>{r.duration_secs}s</b> \u00b7 '
        'Re-run: <code>/flightcheck</code>\n'
        '      </div>\n'
        f'      <div class="verdict {verdict_class}">\n'
        f'        <div class="verdict-icon">{verdict_icon}</div>\n'
        '        <div class="verdict-text">\n'
        f'          <h2>{verdict_headline}</h2>\n'
        f'          <p class="verdict-note">{verdict_sub}</p>\n'
        '        </div>\n'
        '      </div>\n'
        '    </div>\n'
        '  </header>\n'
    )


def _render_action_panel(dict_buckets: dict[str, list[CheckResult]]) -> str:
    """Action items panel: blockers to fix + warnings to review.

    Blockers are the ACTION bucket (Failed + Error); the review list is
    the Warning subset of the MANUAL bucket. When there are neither, the
    panel becomes a positive "nothing needs action" note instead of a
    confusingly empty red box.
    """
    blockers = dict_buckets[BUCKET_ACTION]
    warnings = [
        x for x in dict_buckets[BUCKET_MANUAL]
        if x.status == Status.WARNING.value
    ]

    if not blockers and not warnings:
        return (
            '  <section class="actions-panel allclear" '
            'aria-label="Action items">\n'
            '    <div class="ap-head"><h2>\u2713 Nothing needs action</h2>'
            '<span class="ap-sub">No blocking failures and no warnings in '
            'this run.</span></div>\n'
            '  </section>\n'
        )

    n_block, n_warn = len(blockers), len(warnings)
    block_word = "blocker" if n_block == 1 else "blockers"
    warn_word = "warning" if n_warn == 1 else "warnings"
    sub = (
        f"{n_block} {block_word} to fix before deploy \u00b7 "
        f"{n_warn} {warn_word} to review. Each links to full detail below."
    )
    parts = [
        '  <section class="actions-panel" aria-label="Action items">\n',
        f'    <div class="ap-head"><h2>\u2691 Action items</h2>'
        f'<span class="ap-sub">{sub}</span></div>\n',
    ]

    if blockers:
        parts.append('    <ul class="ap-list">\n')
        for b in blockers:
            owner = _html_escape(", ".join(b.roles)) if b.roles else "\u2014"
            anchor = f"chk-{_slug(b.checkpoint_id)}"
            prio_cls = _html_escape((b.priority or "").lower())
            id_html = (
                f'<span class="id">{_html_escape(b.checkpoint_id)}</span>'
                if b.checkpoint_id else ""
            )
            parts.append(
                '      <li class="ap-item">'
                f'<span class="ap-pri {prio_cls}">{_html_escape(b.priority)}</span>'
                f'<div><div class="ap-title">{_html_escape(b.description)}'
                f'{id_html}</div>'
                f'<div class="ap-meta">Owner <b>{owner}</b> \u00b7 '
                f'<a href="#{anchor}">Details \u2193</a></div></div></li>\n'
            )
        parts.append('    </ul>\n')

    if warnings:
        parts.append('    <div class="ap-review">\n')
        parts.append(
            f'      <b>Then review {n_warn} {warn_word}</b> '
            '(degraded, non-blocking):\n      <ul>\n'
        )
        for w in warnings:
            anchor = f"chk-{_slug(w.checkpoint_id)}"
            id_html = (
                f' \u00b7 <code>{_html_escape(w.checkpoint_id)}</code>'
                if w.checkpoint_id else ""
            )
            parts.append(
                f'        <li><a href="#{anchor}">'
                f'{_html_escape(w.description)}</a>{id_html}</li>\n'
            )
        parts.append('      </ul>\n')
        parts.append(
            '      <span style="display:block;margin-top:8px">Tip: use the '
            '<b>Warnings</b> filter to isolate them.</span>\n'
        )
        parts.append('    </div>\n')

    parts.append('  </section>\n')
    return "".join(parts)


def _render_synopsis(
    r: RunResult,
    categories: list[tuple[str, list[CheckResult]]],
) -> str:
    """Readiness-at-a-glance: per-status totals + a tile per category.

    Per-agent categories (e.g. ``"Topics (Agent A)"``,
    ``"Topics (Agent B)"``) are collapsed to a single base tile
    (``"Topics"``) so the grid stays compact when several agents are
    scanned. A base tile is coloured by the worst status across all its
    agents and links to the first matching category's detail section.
    """
    stats = [
        ("pass", "green", r.passed, "Passed"),
        ("fail", "red", r.failed, "Failed"),
        ("warn", "amber", r.warnings, "Warning"),
        ("manual", "gray", r.manual, "Manual"),
        ("na", "gray", r.not_configured, "Not configured"),
    ]
    if r.errors:
        stats.insert(2, ("fail", "red", r.errors, "Errored"))
    if r.skipped:
        stats.append(("na", "gray", r.skipped, "Skipped"))
    stat_html = "".join(
        f'<span class="stat {cls}"><i class="dot {dot}"></i>'
        f'<b>{n}</b> {label}</span>'
        for cls, dot, n, label in stats
    )

    # Collapse per-agent categories into one group per base name. Each
    # group keeps the first matching category's anchor and accumulates the
    # results of every agent so the tile colour reflects the worst status
    # across all of them.
    groups: list[list] = []  # [base_name, combined_results, first_anchor_cat]
    base_index: dict[str, int] = {}
    for category, results in categories:
        base = _base_category(category)
        if base in base_index:
            groups[base_index[base]][1].extend(results)
        else:
            base_index[base] = len(groups)
            groups.append([base, list(results), category])

    tiles = []
    fix_count = review_count = 0
    for index, (base, results, anchor_cat) in enumerate(groups, start=1):
        color = _category_color(results)
        if color == "red":
            fix_count += 1
        elif color in ("amber", "gray"):
            review_count += 1
        roles = _category_roles(results)
        role_txt = " + ".join(roles) if roles else "No action"
        role_cls = " act" if roles else ""
        tiles.append(
            f'      <a class="syn-tile {color}" href="#cat-{_slug(anchor_cat)}">'
            f'<div class="syn-top"><i class="dot {color}"></i>'
            f'<span class="syn-no">Stage {index}</span></div>'
            f'<div class="syn-name">{_html_escape(base)}</div>'
            f'<div class="syn-role{role_cls}">{_html_escape(role_txt)}</div>'
            '</a>\n'
        )

    fix_word = "stage" if fix_count == 1 else "stages"
    rollup = (
        f'<b>{fix_count} {fix_word} need a fix</b> \u00b7 '
        f'<b>{review_count} to review</b> \u00b7 '
        f'<b>{r.passed} of {r.total}</b> checks passed this run.'
    )
    return (
        '  <section class="synopsis" aria-label="Readiness at a glance">\n'
        '    <div class="syn-head"><h2>Readiness at a glance</h2>'
        '<span class="hint">Grouped by category \u2014 select any tile to '
        'jump to the detail.</span></div>\n'
        f'    <div class="syn-stats" aria-label="Check totals">'
        f'{stat_html}</div>\n'
        '    <div class="syn-grid">\n' + "".join(tiles) + '    </div>\n'
        f'    <div class="syn-rollup">{rollup}</div>\n'
        '  </section>\n'
    )


def _render_category_section(
    index: int,
    category: str,
    results: list[CheckResult],
) -> str:
    """One collapsible <details> section per category, with a card per check.

    Opens by default when the category has any Failed/Error/Warning/
    Manual/NotConfigured row; all-passing categories stay collapsed.
    Defensive: a category with zero results (shouldn't happen, since
    grouping only emits categories that have checks) renders a friendly
    note instead of an empty card list.
    """
    if not results:
        return (
            f'  <details class="sec" id="cat-{_slug(category)}">\n'
            f'    <summary><span class="stage-no">{index}</span> '
            f'{_html_escape(category)}<span class="spacer"></span>'
            '<span class="mini"></span></summary>\n'
            '    <div class="sec-body"><div class="check">'
            'Nothing here \u2014 no checks ran in this category.'
            '</div></div>\n'
            '  </details>\n'
        )

    n_fail = sum(
        1 for x in results
        if x.status in (Status.FAILED.value, Status.ERROR.value)
    )
    n_warn = sum(1 for x in results if x.status == Status.WARNING.value)
    n_other = sum(
        1 for x in results
        if x.status in (Status.MANUAL.value, Status.NOT_CONFIGURED.value)
    )
    n_ok = sum(
        1 for x in results
        if x.status in (Status.PASSED.value, Status.SKIPPED.value)
    )

    minis = []
    if n_fail:
        minis.append(f'<span class="b fail">{n_fail} fail</span>')
    if n_warn:
        minis.append(f'<span class="b warn">{n_warn} warn</span>')
    if n_other:
        minis.append(f'<span class="b">{n_other} manual</span>')
    if n_ok:
        minis.append(f'<span class="b pass">{n_ok} ok</span>')

    open_attr = " open" if (n_fail or n_warn or n_other) else ""
    cards = "".join(_render_check_card(x) for x in results)
    return (
        f'  <details class="sec" id="cat-{_slug(category)}"{open_attr}>\n'
        f'    <summary><span class="stage-no">{index}</span> '
        f'{_html_escape(category)}<span class="spacer"></span>'
        f'<span class="mini">{"".join(minis)}</span></summary>\n'
        f'    <div class="sec-body">\n{cards}    </div>\n'
        '  </details>\n'
    )


def _render_agent_section(
    index: int,
    agent: str,
    subs: list[tuple[str, str, list[CheckResult]]],
) -> str:
    """One collapsible section per scanned agent, with a subgroup per base.

    ``subs`` is a list of ``(base, full_category, results)`` for that agent,
    e.g. ``("Topics", "Topics (Contoso HR)", [...])``. Each subgroup keeps
    the original per-agent anchor id (``cat-topics-contoso-hr``) so the
    readiness synopsis tiles still resolve, and the outer section opens by
    default when any of the agent's checks are actionable.
    """
    all_results = [x for _base, _cat, results in subs for x in results]
    minis_html, actionable = _status_minis(all_results)
    open_attr = " open" if actionable else ""

    body_parts = []
    for base, category, results in subs:
        sub_minis, _ = _status_minis(results)
        cards = "".join(_render_check_card(x) for x in results)
        body_parts.append(
            f'      <div class="subsec" id="cat-{_slug(category)}">\n'
            f'        <div class="subhead">{_html_escape(base)}'
            '<span class="spacer"></span>'
            f'<span class="mini">{sub_minis}</span></div>\n'
            f'{cards}      </div>\n'
        )

    return (
        f'  <details class="sec" id="cat-agent-{_slug(agent)}"{open_attr}>\n'
        f'    <summary><span class="stage-no">{index}</span> '
        f'{_html_escape(agent)}<span class="spacer"></span>'
        f'<span class="mini">{minis_html}</span></summary>\n'
        f'    <div class="sec-body">\n{"".join(body_parts)}    </div>\n'
        '  </details>\n'
    )


def _render_sections(
    categories: list[tuple[str, list[CheckResult]]],
) -> str:
    """Render all detail sections, nesting per-agent categories.

    Tenant-wide categories render as flat sections in their existing order.
    Agent-scoped categories (Configuration / Topics / Knowledge Sources /
    Template Configs) are folded into a single section per agent, placed at
    the position where that agent first appears, so the section list stays
    readable regardless of how many agents were scanned.
    """
    agent_subs: dict[str, list[tuple[str, str, list[CheckResult]]]] = {}
    items: list[tuple] = []  # ("cat", category, results) | ("agent", agent)
    for category, results in categories:
        base, agent = _split_agent(category)
        if agent is None:
            items.append(("cat", category, results))
        else:
            if agent not in agent_subs:
                agent_subs[agent] = []
                items.append(("agent", agent))
            agent_subs[agent].append((base, category, results))

    parts = []
    for index, item in enumerate(items, start=1):
        if item[0] == "cat":
            parts.append(_render_category_section(index, item[1], item[2]))
        else:
            agent = item[1]
            parts.append(_render_agent_section(index, agent, agent_subs[agent]))
    return "".join(parts)


def _render_check_card(res: CheckResult) -> str:
    """One check rendered as a card: pill, title, role, result, next step.

    result renders as a dark <pre> when it spans multiple lines (to
    preserve authored payload formatting) or a compact key/value row for
    one-liners. remediation becomes the "Next step" line; doc_link becomes
    an action button. All check-authored text is HTML-escaped.
    """
    pill_class, label, data_s = _STATUS_STYLE.get(
        res.status, ("na", res.status, "na")
    )
    actionable = res.status not in (
        Status.PASSED.value, Status.SKIPPED.value
    )
    role_txt = (
        _html_escape(", ".join(res.roles))
        if (actionable and res.roles) else "\u2014"
    )
    id_attr = f' id="chk-{_slug(res.checkpoint_id)}"' if res.checkpoint_id else ""
    id_html = (
        f'<span class="id">{_html_escape(res.checkpoint_id)}</span>'
        if res.checkpoint_id else ""
    )

    parts = [
        f'      <div class="check"{id_attr} data-s="{data_s}">\n',
        '        <div class="check-head">'
        f'<span class="pill {pill_class}">{_html_escape(label)}</span>'
        f'<span class="check-title">{_html_escape(res.description)}'
        f'{id_html}</span>'
        f'<span class="role">{role_txt}</span></div>\n',
    ]
    if res.result:
        if "\n" in res.result:
            parts.append(
                f'        <pre class="err">{_html_escape(res.result)}</pre>\n'
            )
        else:
            parts.append(
                '        <dl class="kv"><dt>Detail</dt>'
                f'<dd>{_html_escape(res.result)}</dd></dl>\n'
            )
    if res.remediation:
        if res.status == Status.MANUAL.value:
            parts.append(_render_manual_checklist(res.remediation))
        else:
            parts.append(
                '        <div class="next"><b>Next step</b> \u2014 '
                f'{_md_links_to_html(res.remediation)}</div>\n'
            )
    if res.doc_link:
        link_text = _html_escape(res.doc_label) if res.doc_label else "Docs"
        parts.append(
            '        <div class="actions">'
            f'<a class="btn link" href="{_html_escape(res.doc_link)}" '
            f'target="_blank">{link_text} \u2197</a></div>\n'
        )
    parts.append('      </div>\n')
    return "".join(parts)


def _render_howto() -> str:
    """Collapsed "how to read this report" guide, shown below the verdict.

    Placed after the verdict banner (not first) so the headline outcome
    is what the operator sees on load; the guide expands on demand. The
    content is static reading guidance plus the status colour legend.
    """
    return (
        '  <details class="howto">\n'
        '    <summary>How to read this report</summary>\n'
        '    <div class="howto-body">\n'
        '      Fix the <b style="color:var(--fail)">red</b> items first '
        '\u2014 they block deployment. '
        '<b style="color:var(--warn)">Warnings</b> and <b>Manual</b> items '
        'need your review but don\u2019t block. Manual checks include a '
        'completion checklist you can tick off as you verify each step '
        '(progress applies to this run only). Use the filter bar to focus '
        'on one status, or <b>Fold all</b> / <b>Unfold all</b> to collapse '
        'the sections. After fixing, re-run <code>/flightcheck</code>.\n'
        '      <div class="legend">\n'
        '        <span><i class="sw" style="background:var(--pass)"></i> '
        'Passed</span>\n'
        '        <span><i class="sw" style="background:var(--fail)"></i> '
        'Failed / Error</span>\n'
        '        <span><i class="sw" style="background:var(--warn)"></i> '
        'Warning</span>\n'
        '        <span><i class="sw" style="background:var(--manual)"></i> '
        'Manual</span>\n'
        '        <span><i class="sw" style="background:var(--na)"></i> '
        'Not configured</span>\n'
        '      </div>\n'
        '    </div>\n'
        '  </details>\n'
    )


def _render_footer() -> str:
    """Static footer: status legend + re-run pointer.

    The prose reading guide lives in the collapsed top guide
    (``_render_howto``); the footer keeps only the always-visible colour
    legend so the two don't duplicate the same paragraph.
    """
    return (
        '  <footer>\n'
        '    <div class="grid-note">\n'
        '      <h3>Status legend</h3>\n'
        '      <div class="legend">\n'
        '        <span><i class="sw" style="background:var(--pass)"></i> '
        'Passed</span>\n'
        '        <span><i class="sw" style="background:var(--fail)"></i> '
        'Failed / Error</span>\n'
        '        <span><i class="sw" style="background:var(--warn)"></i> '
        'Warning</span>\n'
        '        <span><i class="sw" style="background:var(--manual)"></i> '
        'Manual</span>\n'
        '        <span><i class="sw" style="background:var(--na)"></i> '
        'Not configured</span>\n'
        '      </div>\n'
        '      <div style="margin-top:10px">After fixing the red items, '
        're-run <code>/flightcheck</code>.</div>\n'
        '    </div>\n'
        '  </footer>\n'
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


def _multiline_html(text: str) -> str:
    """HTML for multi-line text: escape, linkify markdown, keep line breaks.

    Used for manual checklist step blocks, which carry a "Step N" line
    plus its indented a/b/c sub-lines. Line breaks become <br> so the
    authored structure survives inside a single checkbox label.
    """
    return _md_links_to_html(text).replace("\n", "<br>")


def _mask_sensitive(text: str) -> str:
    """Redact operator-identifying values before they reach the report.

    The manual completion checklist echoes ``CheckResult.remediation``,
    which can name a specific user (email / UPN) or a resource GUID. These
    aren't secrets, but a readiness report is often shared beyond the
    operator, so we mask the local part of addresses and the middle of
    GUIDs while keeping enough context (domain, first block) to stay
    actionable.
    """
    import re
    # Email / UPN -> keep first char + full domain: j***@contoso.com
    text = re.sub(
        r'([A-Za-z0-9])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})',
        r'\1***\2', text,
    )
    # GUID -> keep first block: 1a2b3c4d-****-****-****-************
    text = re.sub(
        r'\b([0-9a-fA-F]{8})-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b',
        r'\1-****-****-****-************', text,
    )
    return text


def _manual_checklist_items(remediation: str) -> tuple[str, list[str]]:
    """Split a manual check's remediation into (preamble, step blocks).

    Real manual remediation is uneven: a few checks carry numbered
    "Step 1 ... Step 2 ..." blocks (each with indented a/b/c sub-lines),
    most are a single paragraph. This surfaces the numbered blocks as
    checklist items (one tick per real step) and returns any leading text
    as preamble context. Nothing is invented: a check with no "Step N"
    markers yields an empty step list, so the caller renders only the
    explicit "Mark as verified" affordance.
    """
    import re
    lines = remediation.splitlines()
    step_starts = [
        i for i, ln in enumerate(lines)
        if re.match(r'^\s*Step\s+\d+\b', ln)
    ]
    if not step_starts:
        return remediation.strip(), []
    preamble = "\n".join(lines[:step_starts[0]]).strip()
    bounds = step_starts + [len(lines)]
    steps = []
    for start, end in zip(step_starts, bounds[1:]):
        block = "\n".join(lines[start:end]).strip()
        if block:
            steps.append(block)
    return preamble, steps


def _render_manual_checklist(remediation: str) -> str:
    """Render a manual check's remediation as a per-run completion checklist.

    Always includes an explicit "Mark as verified" checkbox; where the
    remediation has real numbered steps, each becomes its own tick. Any
    leading context renders above the list. Progress is NOT persisted (the
    JS counter resets on reload; the "this run only" note sets that
    expectation). Identifying values are masked via ``_mask_sensitive``.
    """
    preamble, steps = _manual_checklist_items(remediation)
    parts = []
    if preamble:
        parts.append(
            '        <div class="next"><b>Manual check</b> \u2014 '
            f'{_md_links_to_html(_mask_sensitive(preamble))}</div>\n'
        )
    total = len(steps) + 1  # +1 for the explicit "Mark as verified" item
    parts.append('        <div class="checklist">\n')
    parts.append(
        '          <div class="cl-head">Completion checklist'
        f'<span class="cl-count">0 / {total}</span></div>\n'
    )
    parts.append(
        '          <div class="cl-note">Progress applies to this run only.'
        '</div>\n'
    )
    for step in steps:
        label = _multiline_html(_mask_sensitive(step))
        parts.append(
            '          <label class="cl-item"><input type="checkbox">'
            f'<span class="cl-text">{label}</span></label>\n'
        )
    parts.append(
        '          <label class="cl-item"><input type="checkbox">'
        '<span class="cl-text">Mark as verified \u2014 I\u2019ve completed '
        'this manual check.</span></label>\n'
    )
    parts.append('        </div>\n')
    return "".join(parts)
