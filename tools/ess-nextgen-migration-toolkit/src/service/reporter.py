"""Customer-facing migration report rendering (ESS service layer).

This is ESS-specific output: it renders the customer-facing
``migration_report.md`` (titles, sections, mode line) from the generic
``ExecutionContext`` collectors. It lives in ``service/`` — not ``core/`` — so
the framework's diagnostics infrastructure (Logger, SessionManager) stays
product-agnostic while the migration-flavoured report shape is owned by the
domain.
"""

from __future__ import annotations

from core.logging.session_manager import SessionManager
from core.models.execution_context import ChangeEntry, DiagnosticEntry, ExecutionContext


class Reporter:
    """Render ``migration_report.md`` from ExecutionContext collectors."""

    def __init__(self, session_manager: SessionManager) -> None:
        self._session_manager = session_manager

    def render(self, context: ExecutionContext) -> None:
        """Write the customer-facing report into the active session bundle."""
        report = "\n".join(self._build_lines(context)) + "\n"
        self._session_manager.paths.report_path.write_text(report, encoding="utf-8")

    def _build_lines(self, context: ExecutionContext) -> list[str]:
        mode = context.mode.upper()
        title = self._title_for_mode(mode)
        return [
            f"# {title}",
            "",
            "## Summary",
            "",
            f"- Execution Mode: {mode}",
            f"- Changes: {len(context.Changes)}",
            f"- Warnings: {len(context.Warnings)}",
            f"- Errors: {len(context.Errors)}",
            "",
            "## Per-Topic Migration Summary",
            "",
            *self._format_per_topic_summary(context.Changes),
            "",
            "## Changes",
            "",
            *self._format_changes(context.Changes),
            "",
            "## Warnings — Manual Review Required",
            "",
            *self._format_diagnostics(context.Warnings),
            "",
            "## Errors",
            "",
            *self._format_errors(context.Errors),
            "",
        ]

    def _title_for_mode(self, mode: str) -> str:
        if mode == "READONLY":
            return "Migration Readiness Report"
        return "Migration Report"

    def _format_per_topic_summary(self, changes: list[ChangeEntry]) -> list[str]:
        """Group changes by component (topic) → the rules that acted + mitigations.

        Answers, per topic, "which rules acted and what mitigation/transformation
        was applied" — the migration report's per-topic view (rendered in READONLY
        previews too).
        """
        if not changes:
            return ["No topic transformations recorded."]

        by_topic: dict[str, list[ChangeEntry]] = {}
        for change in changes:
            key = change.component or "(agent-level)"
            by_topic.setdefault(key, []).append(change)

        lines: list[str] = []
        for topic, entries in by_topic.items():
            lines.append(f"### {topic}")
            for entry in entries:
                parts = [part for part in (entry.rule_id, entry.title) if part]
                label = " — ".join(parts) or "Change"
                lines.append(f"- {label}: {entry.message}")
            lines.append("")
        return lines[:-1] if lines and lines[-1] == "" else lines

    def _format_changes(self, changes: list[ChangeEntry]) -> list[str]:
        if not changes:
            return ["No changes recorded."]

        lines: list[str] = []
        for change in changes:
            heading_parts = [part for part in (change.rule_id, change.title) if part]
            if heading_parts:
                lines.append(f"### {' — '.join(heading_parts)}")
            if change.component:
                lines.append(f"Component          {change.component}")
            lines.append(f"Change             {change.message}")
            lines.extend(change.details)
            lines.append("")
        return lines[:-1] if lines and lines[-1] == "" else lines

    def _format_diagnostics(self, diagnostics: list[DiagnosticEntry]) -> list[str]:
        if not diagnostics:
            return ["No manual-review warnings recorded."]

        lines: list[str] = []
        for diagnostic in diagnostics:
            if diagnostic.component:
                lines.append(f"Component          {diagnostic.component}")
            lines.append(f"Reason             {diagnostic.message}")
            if diagnostic.recommendation:
                lines.append(f"Recommendation     {diagnostic.recommendation}")
            lines.append("")
        return lines[:-1] if lines and lines[-1] == "" else lines

    def _format_errors(self, errors: list[DiagnosticEntry]) -> list[str]:
        if not errors:
            return ["No errors recorded."]

        lines: list[str] = []
        for error in errors:
            if error.component:
                lines.append(f"Component          {error.component}")
            lines.append(f"Error              {error.message}")
            if error.recommendation:
                lines.append(f"Recommendation     {error.recommendation}")
            lines.append("")
        return lines[:-1] if lines and lines[-1] == "" else lines
