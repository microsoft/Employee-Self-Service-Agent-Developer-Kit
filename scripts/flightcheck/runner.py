# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit — FlightCheck Runner

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


class Priority(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


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

        total_failed = sum(c.failed for c in cat_map.values())
        total_warnings = sum(c.warnings for c in cat_map.values())
        total_passed = sum(c.passed for c in cat_map.values())

        if total_failed == 0 and total_warnings == 0:
            overall = "READY"
        elif total_failed == 0:
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
            overall=overall,
        )


def save_results(run_result: RunResult, output_dir: str = "my/flightcheck"):
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


def _generate_html_report(r: RunResult) -> str:
    """Generate an HTML report matching the ESS FlightCheck template style."""
    # Build table rows
    rows = []
    for res in r.results:
        status_class = {
            Status.PASSED.value: "status-passed",
            Status.FAILED.value: "status-failed",
            Status.WARNING.value: "status-warning",
            Status.NOT_CONFIGURED.value: "status-notconfigured",
            Status.SKIPPED.value: "status-notconfigured",
            Status.ERROR.value: "status-failed",
        }.get(res.status, "")

        priority_class = {
            Priority.CRITICAL.value: "priority-critical",
            Priority.HIGH.value: "priority-high",
        }.get(res.priority, "")

        remediation = _md_links_to_html(res.remediation or "")
        if res.doc_link:
            remediation += f' <a href="{res.doc_link}" target="_blank">[docs]</a>'

        rows.append(
            f'                <tr class="{priority_class}">\n'
            f"                    <td>{res.checkpoint_id}</td>\n"
            f"                    <td>{res.category}</td>\n"
            f"                    <td>{res.priority}</td>\n"
            f'                    <td class="{status_class}">{res.status}</td>\n'
            f"                    <td>{_html_escape(res.result)}</td>\n"
            f"                    <td>{remediation}</td>\n"
            f"                </tr>"
        )

    rows_html = "\n".join(rows)

    return f"""<!DOCTYPE html>
<html>
<head>
    <title>ESS Pre-flight Validation Report</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .header {{ background-color: #0078d4; color: white; padding: 20px; border-radius: 5px; }}
        .summary {{ background-color: white; padding: 20px; margin: 20px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .summary-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }}
        .summary-item {{ text-align: center; padding: 15px; border-radius: 5px; }}
        .passed {{ background-color: #d4edda; color: #155724; }}
        .failed {{ background-color: #f8d7da; color: #721c24; }}
        .warning {{ background-color: #fff3cd; color: #856404; }}
        .notconfigured {{ background-color: #e7e7e7; color: #666; }}
        .results {{ background-color: white; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
        th {{ background-color: #0078d4; color: white; padding: 12px; text-align: left; }}
        td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
        tr:hover {{ background-color: #f5f5f5; }}
        .status-passed {{ color: #28a745; font-weight: bold; }}
        .status-failed {{ color: #dc3545; font-weight: bold; }}
        .status-warning {{ color: #ffc107; font-weight: bold; }}
        .status-notconfigured {{ color: #6c757d; font-weight: bold; }}
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

    <div class="summary">
        <h2>Validation Summary</h2>
        <div class="summary-grid">
            <div class="summary-item passed">
                <h3>{r.passed}</h3>
                <p>Passed</p>
            </div>
            <div class="summary-item failed">
                <h3>{r.failed}</h3>
                <p>Failed</p>
            </div>
            <div class="summary-item warning">
                <h3>{r.warnings}</h3>
                <p>Warnings</p>
            </div>
            <div class="summary-item notconfigured">
                <h3>{r.not_configured}</h3>
                <p>Not Configured</p>
            </div>
        </div>
    </div>

    <div class="results">
        <h2>Detailed Results</h2>
        <table>
            <thead>
                <tr>
                    <th>Checkpoint</th>
                    <th>Category</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Result</th>
                    <th>Remediation</th>
                </tr>
            </thead>
            <tbody>
{rows_html}
            </tbody>
        </table>
    </div>

    <div class="footer">
        <p>ESS Copilot Kit — FlightCheck v1.0</p>
        <p>For more information, visit: <a href="https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service/">Microsoft Learn - Employee Self-Service</a></p>
    </div>
</body>
</html>"""


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
