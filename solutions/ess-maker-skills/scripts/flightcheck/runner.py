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

    The report is presentation-only: all content is derived from ``RunResult``
    and existing render helpers. The Fluent 2 shell wraps category sections in
    one checks card, but it does not change which checks run or how statuses
    are computed.
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
        + '  <section class="checks-card" aria-label="Check details">\n'
        + _FILTER_BAR
        + sections_html
        + '  </section>\n'
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

_APP_ICON_DATA_URI = 'data:image/png;base64,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'

# CSS copied verbatim from the approved design mockup, then extended with a
# few override rules for the verdict banner (the mockup hard-codes a red pill;
# we colour it by outcome) and the "all clear" action panel. Plain string so
# the braces stay literal.
_REPORT_CSS = """
  :root{
    /* Microsoft Fluent 2 design tokens — light */
    --bg:#f5f5f5; --surface:#ffffff; --ink:#242424; --muted:#616161;
    --line:#e0e0e0; --line-strong:#d1d1d1;
    --pass:#0e700e; --pass-bg:#dff6dd; --pass-line:#9fd89f;
    --fail:#b10e1c; --fail-bg:#fde7e9; --fail-line:#eeacb2;
    --warn:#835b00; --warn-bg:#fff4ce; --warn-line:#ecd6a0;
    --manual:#424242; --manual-bg:#f0f0f0; --manual-line:#d1d1d1;
    --na:#616161; --na-bg:#f5f5f5; --na-line:#e0e0e0;
    --accent:#0f6cbd; --accent-ink:#ffffff;
    --code-bg:#242424; --code-ink:#f2f2f2;
    --chip:#f0f0f0; --shadow:0 2px 4px rgba(0,0,0,.14),0 0 2px rgba(0,0,0,.12);
    --radius:4px;
    --ink-2:#424242; --verdict:#942228; --pill-warn:#f7630c;
    --tile-pass:#107C10; --tile-fail:#c50f1f; --tile-warn:#8a3707; --tile-na:#616161;
  }
  @media (prefers-color-scheme: dark){
    :root{
      /* Microsoft Fluent 2 design tokens — dark */
      --bg:#141414; --surface:#292929; --ink:#ffffff; --muted:#adadad;
      --line:#525252; --line-strong:#666666;
      --pass:#5ec75e; --pass-bg:#0c2a0c; --pass-line:#245c24;
      --fail:#e0808a; --fail-bg:#3a1417; --fail-line:#6e2a30;
      --warn:#e0b34d; --warn-bg:#2a2109; --warn-line:#5a4712;
      --manual:#d6d6d6; --manual-bg:#333333; --manual-line:#525252;
      --na:#adadad; --na-bg:#1f1f1f; --na-line:#3d3d3d;
      --accent:#479ef5; --accent-ink:#0a0a0a;
      --code-bg:#0f0f0f; --code-ink:#e6e6e6;
      --chip:#333333;
      --ink-2:#d6d6d6; --verdict:#e0808a; --pill-warn:#f7630c;
      --tile-pass:#5ec75e; --tile-fail:#e0808a; --tile-warn:#e0b34d; --tile-na:#adadad;
    }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:15px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,Roboto,Helvetica,Arial,sans-serif;}
  .wrap{max-width:1080px;margin:0 auto;padding:24px 20px 64px}
  a{color:var(--accent);text-decoration:none}
  a:hover{text-decoration:underline}
  code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}

  /* Header / verdict */
  header.report{background:var(--surface);border:1px solid var(--line);border-top:6px solid var(--accent);border-radius:var(--radius);
    box-shadow:var(--shadow);overflow:hidden;margin-bottom:18px}
  .bar{display:none}
  .head-pad{padding:20px 20px}
  .brand{display:flex;flex-direction:column;align-items:flex-start;gap:12px;margin:0 0 12px}
  .app-icon{width:56px;height:56px;display:block;filter:drop-shadow(0 2px 5px rgba(0,0,0,.18))}
  .brand-title{font-size:24px;line-height:32px;font-weight:600;color:var(--ink)}
  h1{font-size:32px;line-height:40px;font-weight:600;margin:8px 0 12px;letter-spacing:-.01em}
  .meta{color:var(--muted);font-size:14px;line-height:20px;margin-top:2px}
  .meta>div{margin:1px 0}
  .meta b{color:var(--ink);font-weight:600}
  .hr{height:1px;background:var(--line);margin:16px 0}
  .verdict{display:flex;align-items:center;gap:10px;margin:0;padding:0;border:0;background:none;border-radius:0;
    font-weight:600;font-size:24px;line-height:32px;color:var(--verdict)}
  .verdict svg{width:26px;height:26px;flex:none}
  .verdict-note{display:block;margin-top:12px;color:var(--ink);font-size:14px;line-height:20px}

  /* Summary tiles */
  .tiles{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:16px 0 6px}
  .tile{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:12px 14px;box-shadow:var(--shadow)}
  .tile .n{font-size:24px;font-weight:700;line-height:1}
  .tile .l{font-size:12px;color:var(--muted);margin-top:4px;text-transform:uppercase;letter-spacing:.04em}
  .tile.pass .n{color:var(--pass)} .tile.fail .n{color:var(--fail)} .tile.warn .n{color:var(--warn)}
  .tile.manual .n{color:var(--manual)} .tile.na .n{color:var(--na)}
  @media (max-width:720px){.tiles{grid-template-columns:repeat(2,1fr)}}

  /* Coverage */
  .coverage{display:flex;align-items:center;gap:12px;background:var(--surface);border:1px solid var(--line);
    border-radius:var(--radius);padding:12px 16px;box-shadow:var(--shadow);margin:10px 0 18px;font-size:13.5px;color:var(--muted)}
  .covbar{flex:1;height:8px;border-radius:999px;background:var(--manual-bg);overflow:hidden;min-width:120px}
  .covbar > i{display:block;height:100%;width:91%;background:var(--pass)}
  .coverage b{color:var(--ink)}

  /* Filters — Fluent tab bar */
  .checks-card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);padding:4px 20px 8px;margin:0 0 16px}
  .filters{display:flex;flex-wrap:wrap;gap:2px;align-items:center;margin:20px 0 20px;border-bottom:1px solid var(--line)}
  .filters button{font:inherit;font-size:14px;cursor:pointer;border:0;background:none;color:var(--muted);
    padding:10px 12px;border-radius:0;border-bottom:2px solid transparent;margin-bottom:-1px}
  .filters button:hover{color:var(--ink)}
  .filters button[aria-pressed="true"]{background:none;color:var(--accent);border-bottom-color:var(--accent);font-weight:600}
  .filters .fl-spacer{flex:1 1 auto;min-width:8px}
  .filters button.fold{color:var(--ink);border:1px solid var(--line-strong);border-radius:4px;
    padding:6px 12px;margin:5px 0;align-self:center}
  .filters button.fold:hover{border-color:var(--muted);background:var(--bg)}

  /* Collapsed how-to guide */
  details.howto{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);margin:0 0 16px;overflow:hidden}
  details.howto>summary{list-style:none;cursor:pointer;padding:12px 18px;font-weight:650;font-size:14px;
    display:flex;align-items:center;gap:8px;color:var(--ink)}
  details.howto>summary::-webkit-details-marker{display:none}
  details.howto>summary::before{content:"›";font-size:17px;line-height:1;color:var(--muted);transition:transform .15s}
  details.howto[open]>summary::before{transform:rotate(90deg)}
  .howto-body{border-top:1px solid var(--line);padding:14px 18px;font-size:13px;color:var(--muted);line-height:1.6}
  .howto-body .legend{margin:12px 0 4px}
  .howto-body .ground{margin:12px 0 0}

  /* Redacted / masked sensitive values */
  .mask{font-family:ui-monospace,monospace;font-size:12px;background:var(--chip);border:1px solid var(--line-strong);
    border-radius:4px;padding:0 6px;color:var(--muted);letter-spacing:.5px;white-space:nowrap}

  /* Checklist per-run note */
  .cl-note{font-size:11.5px;color:var(--muted);padding:8px 12px;border-top:1px dashed var(--line-strong);background:var(--bg)}

  /* Numbered steps (manual section) */
  .steps{margin:20px 0 2px;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--surface)}
  .steps-head{padding:9px 12px;background:var(--manual-bg);border-bottom:1px solid var(--line);font-size:12.5px;font-weight:650;color:var(--ink)}
  .steps-sub{padding:12px 14px 4px;font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:20px;font-weight:600;color:var(--ink)}
  ol.steps-list{margin:0;padding:0;list-style:none;counter-reset:step}
  ol.steps-list li{position:relative;padding:10px 14px 10px 46px;font-size:13px;line-height:1.5;color:var(--ink);counter-increment:step}
  ol.steps-list li:last-child{border-bottom:none}
  ol.steps-list li::before{content:counter(step);position:absolute;left:12px;top:8px;width:24px;min-width:24px;height:24px;border-radius:9999px;background:#EBEBEB;color:#616161;font-family:'Segoe UI',system-ui,sans-serif;font-size:12px;line-height:16px;font-weight:600;display:inline-flex;align-items:center;justify-content:center}
  ol.steps-list li code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:12px}

  /* Sections — grouped accordion inside checks-card */
  details.sec{background:none;border:0;border-radius:0;box-shadow:none;margin:0;
    border-bottom:1px solid var(--line);overflow:hidden}
  details.sec:last-child{border-bottom:0}
  details.sec>summary{list-style:none;cursor:pointer;padding:16px 2px;display:flex;align-items:center;gap:12px;
    font-weight:600;font-size:16px;color:var(--ink)}
  details.sec>summary::-webkit-details-marker{display:none}
  details.sec>summary::after{content:"";width:9px;height:9px;flex:none;margin-inline-start:4px;
    border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);transform:rotate(45deg);
    transition:transform .15s;margin-top:-4px}
  details.sec[open]>summary::after{transform:rotate(-135deg);margin-top:2px}
  .sec .stage-no{display:none}
  summary .spacer{flex:1}
  .mini{display:inline-flex;gap:6px;align-items:center;font-weight:600;font-size:12px;color:var(--muted)}
  .mini .b{font-family:'Segoe UI',system-ui,sans-serif;font-size:12px;font-weight:600;line-height:16px;letter-spacing:.01em;text-transform:capitalize;display:inline-flex;align-items:center;padding:3px 10px;border-radius:9999px;border:none}
  .mini .b.fail{color:#fff;background:var(--tile-fail)}
  .mini .b.warn{color:#242424;background:#F7630C}
  .mini .b.pass{color:#fff;background:var(--tile-pass)}
  .mini .b.manual{color:#fff;background:#242424}
  .sec-body{padding:6px 0 8px}

  /* Check rows */
  .check{padding:20px 18px;border-bottom:1px solid var(--line);display:grid;grid-template-columns:96px 1fr;column-gap:12px;align-items:start}
  .check>*{grid-column:2;min-width:0}
  .check:last-child{border-bottom:none}
  .check.last-vis{border-bottom:none}
  .check-head{display:contents}
  .pill-col{grid-column:1;grid-row:1 / span 30;justify-self:start;align-self:start;display:flex;flex-direction:column;align-items:flex-start;gap:8px;min-width:0}
  .ch-main{grid-column:2;flex:1;display:flex;flex-wrap:wrap;align-items:flex-start;gap:4px 10px;min-width:0}
  .pill{flex:none;justify-self:start;align-self:start;font-family:'Segoe UI',system-ui,sans-serif;font-size:12px;font-weight:600;line-height:16px;letter-spacing:.01em;
    display:inline-flex;align-items:center;padding:3px 8px;border-radius:9999px;border:1px solid transparent;margin-top:1px;white-space:nowrap}
  .pill.pass{color:#fff;background:var(--tile-pass)}
  .pill.fail{color:#fff;background:var(--tile-fail)}
  .pill.warn{color:#242424;background:#F7630C}
  .pill.manual{color:#fff;background:#242424}
  .pill.na{color:var(--na);background:var(--na-bg);border-color:var(--na-line);white-space:normal;text-align:center;max-width:100%;line-height:14px}
  .check-title{font-family:'Segoe UI',system-ui,sans-serif;font-size:16px;line-height:22px;font-weight:600;flex:1 1 auto;min-width:0}
  .check-title .id{font-weight:600;color:var(--muted);font-size:12.5px;font-family:ui-monospace,monospace;margin-inline-start:6px}
  .role{flex:0 0 100%;font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:20px;color:var(--ink);font-weight:600;margin-top:4px;white-space:nowrap}
  .role::before{content:"Assigned to: "}
  .role.none{display:none}
  .kv{display:block;margin:20px 0 0 0;font-size:14px;line-height:20px;color:var(--ink)}
  .kv + .kv{margin-top:8px}
  .kv dt{display:inline;font-weight:600;color:var(--ink)}
  .kv dt::after{content:":\\00a0"}
  .kv dd{display:inline;margin:0;color:var(--ink)}
  .kv dd::after{content:"";display:block;height:6px}
  .kv .exp{color:var(--pass);font-family:ui-monospace,monospace;font-size:12.5px}
  .kv .act-bad{color:var(--fail);font-family:ui-monospace,monospace;font-size:12.5px}
  .kv .act-ok{color:var(--ink);font-family:ui-monospace,monospace;font-size:12.5px}
  pre.err{background:var(--code-bg);color:var(--code-ink);border-radius:8px;padding:12px 14px;margin:20px 0 0;
    font-size:12px;line-height:1.55;overflow-x:auto;white-space:pre}
  .next{margin:20px 0 0;font-size:14px;line-height:20px;color:var(--ink)}
  .next b{font-weight:600;display:block;margin-bottom:4px;color:var(--ink)}
  .actions{margin-top:20px;display:flex;flex-wrap:wrap;gap:8px}
  .btn{box-sizing:border-box;font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:20px;font-weight:600;border-radius:4px;padding:2px 8px;gap:4px;border:1px solid #D1D1D1;background:#FFFFFF;color:#242424;display:inline-flex;align-items:center;justify-content:center}
  .btn.fix{background:#FFFFFF;color:#242424;border-color:#D1D1D1}
  .btn.link{background:#FFFFFF;color:#242424;border-color:#D1D1D1}
  .stuck{font-size:12.5px;color:var(--muted);margin-top:8px}

  /* Manual completion checklist (interactive) */
  .checklist{margin:12px 0 2px;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:var(--surface)}
  .cl-head{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:9px 12px;background:var(--manual-bg);
    border-bottom:1px solid var(--line);font-size:12.5px;font-weight:650;color:var(--ink)}
  .cl-head .cl-count{margin-inline-start:auto;font-size:12px;font-weight:600;color:var(--muted);
    background:var(--surface);border:1px solid var(--line-strong);border-radius:999px;padding:2px 10px}
  .cl-head .cl-count.done{color:var(--pass);border-color:var(--pass-line);background:var(--pass-bg)}
  /* Priority + blocked shown on the check's item line */
  .check-head .pri{flex:none;font-family:'Segoe UI',system-ui,sans-serif;font-size:12px;font-weight:600;line-height:16px;letter-spacing:.01em;
    display:inline-flex;align-items:center;padding:3px 10px;border-radius:9999px;border:1px solid transparent;background:transparent;white-space:nowrap}
  .check-head .pri.critical{color:#C50F1F;background:transparent;border-color:#C50F1F}
  .check-head .pri.high{color:#DA3B01;background:transparent;border-color:#F4BFAB}
  .check-head .cstatus{flex:none;font-family:'Segoe UI',system-ui,sans-serif;font-size:12px;font-weight:600;line-height:16px;letter-spacing:.01em;
    display:inline-flex;align-items:center;justify-content:center;text-align:center;padding:3px 8px;border-radius:9999px;border:1px solid #EEACB2;background:#FDF3F4;color:#B10E1C;white-space:nowrap}
  .cl-bar{height:6px;background:var(--manual-bg)}
  .cl-bar>i{display:block;height:100%;width:0;background:var(--pass);transition:width .25s ease}
  .cl-item{display:flex;gap:10px;align-items:flex-start;padding:9px 12px;border-bottom:1px solid var(--line);
    cursor:pointer;font-size:13px;color:var(--ink)}
  .cl-item:last-child{border-bottom:none}
  .cl-item:hover{background:var(--bg)}
  .cl-item input{margin:2px 0 0;width:15px;height:15px;accent-color:var(--pass);flex:none;cursor:pointer}
  .cl-item code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:12px}
  .cl-item.done{color:var(--muted)}
  .cl-item.done .cl-text{text-decoration:line-through}

  footer{margin-top:26px;color:var(--muted);font-size:12.5px;line-height:1.6}
  footer h3{font-size:13px;color:var(--ink);margin:0 0 6px}
  .grid-note{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:14px 18px;box-shadow:var(--shadow)}
  .legend{display:flex;flex-wrap:wrap;gap:10px;margin:14px 0 4px}
  .legend span{font-size:12px;color:var(--muted);display:inline-flex;gap:6px;align-items:center}
  .sw{width:10px;height:10px;border-radius:3px;display:inline-block}
  .hidden{display:none !important}

  /* Action items panel */
  .actions-panel{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);padding:16px 20px;margin:0 0 16px}
  .ap-head{display:block;margin-bottom:14px}
  .ap-head h2{font-size:24px;line-height:32px;font-weight:600;margin:0;color:var(--ink)}
  .ap-sub{color:var(--muted);font-size:14px;line-height:20px;display:block;margin-top:4px}
  .ap-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
  .ap-item{display:flex;gap:12px;align-items:flex-start;padding:8px 0;border:0;border-radius:0;background:none}
  .ap-pri{font-family:'Segoe UI',system-ui,sans-serif;font-size:12px;font-weight:600;line-height:16px;letter-spacing:.01em;
    display:inline-flex;align-items:center;padding:3px 10px;border-radius:9999px;border:1px solid #C50F1F;white-space:nowrap;color:#C50F1F;background:transparent}
  .ap-pri.high{color:#DA3B01;background:transparent;border-color:#F4BFAB}
  .ap-prios{flex:none;width:96px;display:flex;flex-direction:column;gap:8px;align-items:flex-start;margin-top:2px}
  .ap-status{display:none}
  .ap-id{font-family:ui-monospace,monospace;font-size:12px;color:var(--muted);font-weight:600;margin-bottom:4px}
  .ap-title{font-weight:600;font-size:16px;line-height:22px;color:var(--ink)}
  .ap-meta{color:var(--muted);font-size:14px;line-height:20px;margin-top:8px}
  .ap-review{margin:16px 0 0;padding-top:16px;border-top:1px solid var(--line);font-size:14px;line-height:20px;color:var(--ink);font-weight:400}
  .ap-review .ap-review-h{display:block;font-size:24px;line-height:32px;font-weight:600;color:var(--ink);margin-bottom:8px}
  .ap-review b{color:var(--ink)}
  .ap-review ul{margin:8px 0 0;padding-inline-start:18px}
  .ap-review li{margin:8px 0;color:var(--muted)}
  .ap-review .ap-tip{color:var(--muted);font-weight:400}
  /* "show more" disclosure for lists longer than 3 items */
  .ap-item[hidden],.ap-review li[hidden]{display:none}
  .ap-more{margin-top:12px;display:inline-flex;align-items:center;gap:6px;cursor:pointer;
    font-family:'Segoe UI',system-ui,sans-serif;font-size:14px;line-height:20px;font-weight:600;color:var(--ink);
    background:#fff;border:1px solid #D1D1D1;border-radius:4px;padding:5px 12px}
  .ap-more:hover{background:#F5F5F5}
  .ap-more .chev{width:8px;height:8px;flex:none;border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);
    transform:rotate(45deg);transition:transform .15s;margin-top:-3px}
  .ap-more[aria-expanded="true"] .chev{transform:rotate(-135deg);margin-top:2px}
  .ap-review .ap-more{margin-inline-start:18px}

  /* Visual synopsis — readiness at a glance */
  .synopsis{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);padding:20px;margin:0 0 16px}
  .syn-head{display:block;margin-bottom:16px}
  .syn-head h2{font-size:24px;line-height:32px;font-weight:600;margin:0;color:var(--ink)}
  .syn-head .hint{color:var(--muted);font-size:14px;line-height:20px;display:block;margin-top:4px}
  .dot{width:11px;height:11px;border-radius:50%;display:inline-block;flex:none}
  .dot.red{background:var(--tile-fail)} .dot.amber{background:var(--pill-warn)}
  .dot.green{background:var(--tile-pass)} .dot.gray{background:var(--manual)}
  .syn-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
  @media (max-width:760px){.syn-grid{grid-template-columns:repeat(2,1fr)}}
  .syn-tile{display:block;text-decoration:none;color:inherit;border:2px solid var(--line);border-radius:4px;
    padding:12px;background:var(--surface);transition:box-shadow .12s,transform .12s}
  .syn-tile:hover{text-decoration:none;box-shadow:var(--shadow);transform:translateY(-1px)}
  .syn-tile:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  .syn-tile.red{border-color:var(--tile-fail)}
  .syn-tile.amber{border-color:var(--tile-warn)}
  .syn-tile.green{border-color:var(--tile-pass)}
  .syn-tile.gray{border-color:var(--tile-na)}
  .syn-no{font-size:14px;font-weight:600;color:var(--ink)}
  .syn-role{font-size:12px;line-height:16px;color:var(--muted);margin-top:2px;min-height:1em}
  .syn-name{font-weight:600;font-size:14px;line-height:20px;color:var(--ink-2);margin-top:6px}
  .syn-role.act{color:var(--muted)}
  .syn-stats{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}
  .syn-stats .stat{display:inline-flex;align-items:center;gap:7px;font-size:13px;color:var(--muted);
    border:1px solid var(--line);border-radius:999px;padding:4px 11px;background:var(--bg)}
  .syn-stats .stat b{font-size:14px;font-weight:600;color:var(--ink)}
  .syn-stats .stat.pass b{color:var(--pass)}
  .syn-stats .stat.fail b{color:var(--fail)}
  .syn-stats .stat.warn b{color:var(--pill-warn)}
  .syn-stats .stat.manual b{color:var(--manual)}
  .syn-stats .stat.na b{color:var(--na)}

  /* FlightCheck data-driven overrides. */
  .verdict.verdict-ready{color:var(--pass)}
  .verdict.verdict-warnings{color:var(--pill-warn)}
  .verdict.verdict-not-ready{color:var(--fail)}
  .ap-pri.medium{color:var(--manual);background:transparent;border-color:var(--manual-line)}
  .ap-pri.low{color:var(--na);background:transparent;border-color:var(--na-line)}
  .actions-panel.allclear{border-inline-start:0}
  .actions-panel.allclear .ap-head h2{color:var(--pass)}
  .mini .b.manual{color:#fff;background:#242424}
  .check-head .pri.medium{color:var(--manual);background:transparent;border-color:var(--manual-line)}
  .check-head .pri.low{color:var(--na);background:transparent;border-color:var(--na-line)}
  .check-head .pri.manual{color:var(--manual);background:transparent;border-color:var(--manual-line)}
  .kv dd.detail{white-space:normal}

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
      var d = el.closest ? el.closest('details') : null;
      if(d){ d.open = true; }
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

  // Collapse lists in the Action items section to the first 3, revealing the
  // rest behind a "Show N more" disclosure. Applies to any list with >3 items.
  (function(){
    function makeCollapsible(listEl, itemSel, noun){
      if(!listEl) return;
      var items = Array.prototype.slice.call(listEl.querySelectorAll(itemSel));
      if(items.length <= 3) return;
      var extras = items.slice(3);
      extras.forEach(function(it){ it.hidden = true; });
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ap-more';
      btn.setAttribute('aria-expanded','false');
      var label = document.createElement('span');
      var chev = document.createElement('span'); chev.className = 'chev';
      btn.appendChild(label); btn.appendChild(chev);
      function render(){
        var open = btn.getAttribute('aria-expanded') === 'true';
        label.textContent = open ? 'Show fewer'
          : ('Show ' + extras.length + ' more ' + noun + (extras.length > 1 ? 's' : ''));
      }
      render();
      btn.addEventListener('click', function(){
        var open = btn.getAttribute('aria-expanded') !== 'true';
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        extras.forEach(function(it){ it.hidden = !open; });
        render();
      });
      listEl.parentNode.insertBefore(btn, listEl.nextSibling);
    }
    makeCollapsible(document.querySelector('.ap-list'), '.ap-item', 'action item');
    makeCollapsible(document.querySelector('.ap-review ul'), 'li', 'warning');
  })();

  (function(){
    var bar = document.getElementById('filters');
    if(!bar) return;
    bar.hidden = false;
    var checks = Array.prototype.slice.call(document.querySelectorAll('.check'));
    var secs = Array.prototype.slice.call(document.querySelectorAll('details.sec'));
    var subsecs = Array.prototype.slice.call(document.querySelectorAll('.subsec'));
    var parent = secs.length ? secs[0].parentNode : null;
    var originalOrder = secs.slice();
    // Single fold toggle: one button flips every section open/closed and
    // relabels itself. syncFoldLabel keeps the label right when a section is
    // toggled by hand or a filter opens/closes panels.
    function syncFoldLabel(){
      var foldBtn = bar.querySelector('[data-fold]');
      if(!foldBtn) return;
      var anyClosed = secs.some(function(s){ return !s.open; });
      foldBtn.textContent = anyClosed ? 'Expand all' : 'Collapse all';
    }
    secs.forEach(function(s){ s.addEventListener('toggle', syncFoldLabel); });
    syncFoldLabel();
    function visibleRows(root){ return root.querySelectorAll('.check:not(.hidden)'); }
    function updateSubsections(f){
      subsecs.forEach(function(ss){
        var anyVisible = ss.querySelector('.check:not(.hidden)');
        ss.classList.toggle('hidden', f!=='all' && !anyVisible);
      });
    }
    function updateLastVisible(){
      checks.forEach(function(c){ c.classList.remove('last-vis'); });
      secs.forEach(function(s){
        var vis = visibleRows(s);
        if(vis.length){ vis[vis.length-1].classList.add('last-vis'); }
      });
    }
    bar.addEventListener('click', function(e){
      var btn = e.target.closest('button'); if(!btn) return;
      var fold = btn.getAttribute('data-fold');
      if(fold){
        var anyClosed = secs.some(function(s){ return !s.open; });
        secs.forEach(function(s){ s.open = anyClosed; });
        syncFoldLabel();
        return;
      }
      var f = btn.getAttribute('data-f');
      if(!f) return;
      bar.querySelectorAll('button[data-f]').forEach(function(b){ b.setAttribute('aria-pressed', b===btn ? 'true':'false'); });
      checks.forEach(function(c){
        c.classList.toggle('hidden', !(f==='all' || c.getAttribute('data-s')===f));
      });
      updateSubsections(f);
      secs.forEach(function(s){
        var anyVisible = s.querySelector('.check:not(.hidden)');
        if(f!=='all'){ s.open = !!anyVisible; }
      });
      updateLastVisible();
      syncFoldLabel();
      if(parent){
        if(f==='all'){
          originalOrder.forEach(function(s){ parent.appendChild(s); });
        } else {
          var matched=[], rest=[];
          originalOrder.forEach(function(s){
            (s.querySelector('.check:not(.hidden)') ? matched : rest).push(s);
          });
          matched.concat(rest).forEach(function(s){ parent.appendChild(s); });
        }
      }
    });
  })();

  // Manual-check completion checklist: tick a step to advance the counter,
  // fill the progress bar, and strike through the item. Delegated so it
  // covers every .checklist without per-card wiring. Progress is in-page
  // only (no persistence) and each .checklist is scoped independently.
  (function(){
    function refresh(cl){
      var boxes = Array.prototype.slice.call(
        cl.querySelectorAll('.cl-item input[type=checkbox]'));
      var total = boxes.length;
      if(!total) return;
      var done = 0;
      boxes.forEach(function(b){
        var item = b.closest('.cl-item');
        if(item){ item.classList.toggle('done', b.checked); }
        if(b.checked){ done++; }
      });
      var count = cl.querySelector('.cl-count');
      if(count){
        count.textContent = done + ' / ' + total;
        count.classList.toggle('done', done === total);
      }
      var bar = cl.querySelector('.cl-bar > i');
      if(bar){ bar.style.width = Math.round(done / total * 100) + '%'; }
    }
    document.addEventListener('change', function(e){
      var box = e.target;
      if(!box || box.type !== 'checkbox') return;
      var cl = box.closest && box.closest('.checklist');
      if(!cl) return;
      refresh(cl);
    });
  })();
"""

# Filter bar markup. Rendered hidden; the filter IIFE un-hides it when JS runs
# so the no-JS view shows all rows without a dead control.
_FILTER_BAR = (
    '  <div class="filters" id="filters" hidden>\n'
    '    <button data-f="all" aria-pressed="true">All</button>\n'
    '    <button data-f="fail" aria-pressed="false">Failed</button>\n'
    '    <button data-f="warn" aria-pressed="false">Warnings</button>\n'
    '    <button data-f="manual" aria-pressed="false">Manual</button>\n'
    '    <button data-f="pass" aria-pressed="false">Passed</button>\n'
    '    <span class="fl-spacer"></span>\n'
    '    <button class="fold" data-fold="toggle" type="button">Collapse all</button>\n'
    '  </div>\n'
)

# Fold/unfold-all controls. Hidden until the fold IIFE un-hides them, so the
# no-JS view isn't left with dead buttons (each section is a native <details>
# the reader can still toggle by hand).
_VIEW_TOOLS = ""


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
        minis.append(f'<span class="b manual">{n_other} manual</span>')
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
    """Render the Fluent 2 report header with dynamic run metadata."""
    rerun = "/flightcheck" if r.scope == "full" else f"/flightcheck --scope {r.scope}"
    agents = sorted(
        {
            agent
            for summary in r.categories
            for _base, agent in [_split_agent(summary.category)]
            if agent
        }
    )
    agent_meta = ", ".join(agents) if agents else "Not specified by this RunResult"
    # Verdict glyph matches the mockup: a state-appropriate Fluent icon
    # inline with the headline, coloured by the verdict-* class.
    verdict_svgs = {
        "verdict-ready": (
            '<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">'
            '<path d="M10 1.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Zm3.86 6.15'
            '-4.2 4.2a.75.75 0 0 1-1.06 0L6.14 9.65a.75.75 0 1 1 1.06-1.06l1.83 '
            '1.83 3.67-3.67a.75.75 0 1 1 1.06 1.06Z"/></svg>'
        ),
        "verdict-warnings": (
            '<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">'
            '<path d="M9.13 2.98a1 1 0 0 1 1.74 0l7.03 12.26a1 1 0 0 1-.87 1.5'
            'H2.97a1 1 0 0 1-.87-1.5L9.13 2.98ZM10 7a.75.75 0 0 0-.75.75v3.5a.75'
            '.75 0 0 0 1.5 0v-3.5A.75.75 0 0 0 10 7Zm0 6.5a.9.9 0 1 0 0 1.8.9.9 '
            '0 0 0 0-1.8Z"/></svg>'
        ),
        "verdict-not-ready": (
            '<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">'
            '<path d="M10 1.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Zm6 8.5c0 1.35'
            '-.45 2.6-1.2 3.6L6.4 5.2A6 6 0 0 1 16 10ZM4 10c0-1.35.45-2.6 1.2-3.6'
            'l8.4 8.4A6 6 0 0 1 4 10Z"/></svg>'
        ),
    }
    verdict_svg = verdict_svgs.get(verdict_class, "")
    brand_title = (
        "Employee Self-Service FlightCheck \u00b7 "
        f"{_html_escape(r.scope.title())} deployment readiness"
    )
    return (
        '  <header class="report">\n'
        '    <div class="head-pad">\n'
        '      <div class="brand">\n'
        f'        <img class="app-icon" src="{_APP_ICON_DATA_URI}"'
        ' alt="Employee Self-Service icon">\n'
        f'        <div class="brand-title">{brand_title}</div>\n'
        '      </div>\n'
        '      <div class="meta">\n'
        f'        <div>Agent: <b>{_html_escape(agent_meta)}</b></div>\n'
        f'        <div>Scope: <b>{_html_escape(r.scope)}</b></div>\n'
        f'        <div>Run: <b>{_html_escape(r.started)}</b></div>\n'
        f'        <div>Completed in: <b>{r.duration_secs}s</b></div>\n'
        f'        <div>Re-run: <code>{_html_escape(rerun)}</code></div>\n'
        '      </div>\n'
        '      <div class="hr"></div>\n'
        f'      <div class="verdict {verdict_class}">{verdict_svg} '
        f'{_html_escape(verdict_headline)}</div>\n'
        f'      <span class="verdict-note">{_html_escape(verdict_sub)}</span>\n'
        '    </div>\n'
        '  </header>\n'
    )

def _render_action_panel(dict_buckets: dict[str, list[CheckResult]]) -> str:
    """Action items panel: blockers to fix + warnings to review."""
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
        f'    <div class="ap-head"><h2>Action items</h2>'
        f'<span class="ap-sub">{sub}</span></div>\n',
    ]

    if blockers:
        parts.append('    <ul class="ap-list">\n')
        for b in blockers:
            owner = _html_escape(", ".join(b.roles)) if b.roles else "\u2014"
            anchor = f"chk-{_slug(b.checkpoint_id)}"
            prio_cls = _html_escape((b.priority or "").lower())
            id_html = (
                f'<div class="ap-id">{_html_escape(b.checkpoint_id)}</div>'
                if b.checkpoint_id else ""
            )
            parts.append(
                '      <li class="ap-item">'
                '<div class="ap-prios">'
                f'<span class="ap-pri {prio_cls}">{_html_escape(b.priority)}</span>'
                '</div>'
                f'<div>{id_html}'
                f'<div class="ap-title">{_html_escape(b.description)}</div>'
                f'<div class="ap-meta">Assigned to <b>{owner}</b> '
                f'\u00b7 <a href="#{anchor}">Details \u2193</a></div>'
                '</div></li>\n'
            )
        parts.append('    </ul>\n')

    if warnings:
        parts.append('    <div class="ap-review">\n')
        parts.append(
            f'      <span class="ap-review-h">Review {n_warn} {warn_word}</span>\n'
            '      <ul>\n'
        )
        for w in warnings:
            anchor = f"chk-{_slug(w.checkpoint_id)}"
            id_html = (
                f'<b>{_html_escape(w.checkpoint_id)}</b> '
                if w.checkpoint_id else ""
            )
            parts.append(
                f'        <li><a href="#{anchor}">{id_html}'
                f'{_html_escape(w.description)}</a></li>\n'
            )
        parts.append('      </ul>\n')
        parts.append(
            '      <span class="ap-tip">Use the <b>Warnings</b> tab to isolate them.</span>\n'
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
    for index, (base, results, anchor_cat) in enumerate(groups, start=1):
        color = _category_color(results)
        roles = _category_roles(results)
        role_txt = " + ".join(roles) if roles else "No action"
        role_cls = " act" if roles else ""
        tiles.append(
            f'      <a class="syn-tile {color}" href="#cat-{_slug(anchor_cat)}">'
            f'<div class="syn-no">Stage {index}</div>'
            f'<div class="syn-name">{_html_escape(base)}</div>'
            f'<div class="syn-role{role_cls}">{_html_escape(role_txt)}</div>'
            '</a>\n'
        )

    return (
        '  <section class="synopsis" aria-label="Readiness at a glance">\n'
        '    <div class="syn-head"><h2>Readiness at a glance</h2>'
        '<span class="hint">Grouped by category \u2014 select any tile to '
        'jump to the detail.</span></div>\n'
        f'    <div class="syn-stats" aria-label="Check totals">'
        f'{stat_html}</div>\n'
        '    <div class="syn-grid">\n' + "".join(tiles) + '    </div>\n'
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
        minis.append(f'<span class="b manual">{n_other} manual</span>')
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
    """One check rendered as a Fluent 2 row with preserved data hooks."""
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
    role_cls = "" if (actionable and res.roles) else " none"
    id_attr = f' id="chk-{_slug(res.checkpoint_id)}"' if res.checkpoint_id else ""
    id_html = (
        f'<span class="id">{_html_escape(res.checkpoint_id)}</span>'
        if res.checkpoint_id else ""
    )
    pri_cls = _html_escape((res.priority or "").lower())
    priority_html = (
        f'<span class="pri {pri_cls}">{_html_escape(res.priority)}</span>'
        if actionable and res.priority else ""
    )
    blocked_html = (
        '<span class="cstatus">Blocked</span>'
        if res.status in (Status.FAILED.value, Status.ERROR.value) else ""
    )

    parts = [
        f'      <div class="check"{id_attr} data-s="{data_s}">\n',
        '        <div class="check-head">'
        '<div class="pill-col">'
        f'<span class="pill {pill_class}">{_html_escape(label)}</span>'
        f'{priority_html}{blocked_html}</div>'
        '<div class="ch-main">'
        f'<span class="check-title">{_html_escape(res.description)}{id_html}</span>'
        f'<span class="role{role_cls}">{role_txt}</span>'
        '</div></div>\n',
    ]
    if res.result:
        parts.append(
            '        <dl class="kv"><dt>Detail</dt>'
            f'<dd class="detail">{_multiline_html(_mask_sensitive(res.result))}</dd></dl>\n'
        )
    if res.remediation:
        if res.status == Status.MANUAL.value:
            parts.append(_render_manual_checklist(res.remediation))
        else:
            parts.append(
                '        <div class="next"><b>Next step</b>'
                f'{_md_links_to_html(_mask_sensitive(res.remediation))}</div>\n'
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
        'on one status, or <b>Collapse all</b> / <b>Expand all</b> to fold '
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
        '      <p style="margin:12px 0 0">The <b>manual section</b> lists the '
        'numbered steps to clear each sign-off \u2014 complete them, then '
        're-run FlightCheck.</p>\n'
        '      <p style="margin:8px 0 0"><b>Identifying values are masked</b> '
        '\u2014 user emails and resource GUIDs in the report text are partly '
        'redacted so a shared report doesn\u2019t leak them. IDs inside links '
        'are kept so the links still resolve; retrieve full values from the '
        'source system.</p>\n'
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
    """Escape text, then render BOTH markdown links and bare URLs as
    clickable ``<a target="_blank">`` anchors.

    Two link forms reach the report from check ``remediation`` strings:
    markdown ``[label](url)`` and bare ``https://…`` URLs. Only the
    markdown form used to be linkified, so a check that pasted a raw URL
    produced a non-clickable link. That inconsistency surfaced as "the
    link works sometimes but not others" on MANUAL / NotConfigured rows,
    where remediation URLs are the operator's only path to the fix. Both
    forms are now anchored so the operator can always click through,
    regardless of how the check authored the URL.
    """
    import re
    escaped = _html_escape(text)
    # Markdown links first. Escaping left [] and () intact, so the raw
    # [label](url) survives to here; turn it into a real anchor.
    with_md = re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        r'<a href="\2" target="_blank">\1</a>',
        escaped,
    )
    # Then autolink any remaining bare URLs, skipping the anchors we just
    # created so their href/label URLs aren't wrapped a second time.
    return _autolink_bare_urls(with_md)


def _autolink_bare_urls(html: str) -> str:
    """Wrap bare ``http(s)://…`` URLs in ``html`` as clickable anchors.

    Operates on text that has already been HTML-escaped and had its
    markdown links converted to ``<a>…</a>``. Those existing anchors are
    stepped over untouched (matched by ``anchor_re``) so a URL inside an
    ``href`` or an anchor label is never double-wrapped. Only the plain
    text between anchors is scanned for bare URLs.
    """
    import re
    # A bare URL: scheme + run of non-space, non-quote, non-']' chars.
    # ')' is allowed here so balanced-paren links (e.g. ".../Foo_(bar)")
    # survive intact; the replacer resolves paren balance and trailing
    # punctuation, so "see https://aka.ms/x." and "(see https://x)" keep
    # the trailing char outside the link.
    bare_url_re = re.compile(r'https?://[^\s<>"\'\]]+')
    # An anchor already emitted by the markdown pass; keep it verbatim.
    anchor_re = re.compile(r'<a\b[^>]*>.*?</a>', re.IGNORECASE | re.DOTALL)
    # A ';' that closes an HTML entity belongs to the URL, so it must not
    # be peeled as if it were sentence punctuation. Only '&amp;' (a real
    # query-string '&') is kept; '&lt;'/'&gt;' are handled separately below
    # because an unescaped angle bracket can never be a valid URL char.
    entity_tail_re = re.compile(r'&amp;$')
    # A trailing escaped delimiter entity from a wrapped URL, e.g. an
    # angle-bracket-wrapped "<https://x>" (escapes to "&lt;https://x&gt;")
    # or a quote-wrapped '"https://x"' ("&quot;https://x&quot;"). Angle
    # brackets and quotes are URL delimiters, never valid unescaped URL
    # chars, so peel the whole entity back into the surrounding text.
    delim_tail_re = re.compile(r'&(?:lt|gt|quot);$')

    def _wrap(segment: str) -> str:
        def repl(m: "re.Match[str]") -> str:
            url = m.group(0)
            trail = ""
            # Peel trailing sentence punctuation, unbalanced closing parens,
            # and escaped delimiter entities (in any order) off the link
            # target. A balanced paren pair (".../Foo_(bar)") is kept; an
            # unbalanced ")" ("(see https://x)") is pushed back into the
            # surrounding text.
            while url:
                delim = delim_tail_re.search(url)
                if delim:
                    trail = url[delim.start():] + trail
                    url = url[: delim.start()]
                    continue
                last = url[-1]
                if last == ";" and entity_tail_re.search(url):
                    break  # ';' closes an '&amp;' entity; keep it in the URL
                if last in ".,;:!?":
                    trail = last + trail
                    url = url[:-1]
                elif last == ")" and url.count("(") < url.count(")"):
                    trail = ")" + trail
                    url = url[:-1]
                else:
                    break
            if not url:
                return m.group(0)
            return f'<a href="{url}" target="_blank">{url}</a>{trail}'
        return bare_url_re.sub(repl, segment)

    out: list[str] = []
    last = 0
    for m in anchor_re.finditer(html):
        out.append(_wrap(html[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_wrap(html[last:]))
    return "".join(out)


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

    Text inside an ``http(s)://`` URL is left verbatim. A remediation deep
    link (e.g. Copilot Studio ``.../environments/<env_id>/bots/<bot_id>``)
    carries GUIDs as path segments; masking them rewrites the ``href`` and
    the link stops resolving. Those ids already appear in every deep link
    the report emits, so keeping them in the URL leaks nothing new while
    keeping the link clickable. Standalone GUIDs / emails in prose are
    still masked.
    """
    import re
    email_re = re.compile(
        r'([A-Za-z0-9])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})'
    )
    guid_re = re.compile(
        r'\b([0-9a-fA-F]{8})-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'
    )
    # A URL run: scheme + non-space chars, stopping before a ')' so a
    # markdown target "[label](url)" ends at its wrapping paren.
    url_re = re.compile(r'https?://[^\s)]+')

    def _mask_prose(segment: str) -> str:
        # Email / UPN -> keep first char + full domain: j***@contoso.com
        segment = email_re.sub(r'\1***\2', segment)
        # GUID -> keep first block: 1a2b3c4d-****-****-****-************
        segment = guid_re.sub(r'\1-****-****-****-************', segment)
        return segment

    out: list[str] = []
    last = 0
    for m in url_re.finditer(text):
        out.append(_mask_prose(text[last:m.start()]))
        out.append(m.group(0))  # URL kept verbatim so its GUIDs survive
        last = m.end()
    out.append(_mask_prose(text[last:]))
    return "".join(out)


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
    """Render real manual remediation steps plus the interactive checklist."""
    preamble, steps = _manual_checklist_items(remediation)
    parts = []
    if preamble:
        parts.append(
            '        <div class="next"><b>Manual check</b>'
            f'{_md_links_to_html(_mask_sensitive(preamble))}</div>\n'
        )
    if steps:
        parts.append('        <div class="steps">\n')
        parts.append('          <div class="steps-head">Steps to complete</div>\n')
        parts.append('          <ol class="steps-list">\n')
        for step in steps:
            parts.append(
                f'            <li>{_multiline_html(_mask_sensitive(step))}</li>\n'
            )
        parts.append('          </ol>\n')
        parts.append('        </div>\n')
    total = len(steps) + 1
    parts.append('        <div class="checklist">\n')
    parts.append(
        '          <div class="cl-head">Completion checklist'
        f'<span class="cl-count">0 / {total}</span></div>\n'
    )
    parts.append('          <div class="cl-bar"><i></i></div>\n')
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
    parts.append(
        '          <div class="cl-note">Progress applies to this run only.'
        '</div>\n'
    )
    parts.append('        </div>\n')
    return "".join(parts)
