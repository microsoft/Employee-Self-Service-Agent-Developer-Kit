"""Customer-facing migration report rendering."""

from __future__ import annotations

from core.logging.session_manager import SessionManager
from core.models.migration_context import ChangeEntry, DiagnosticEntry, MigrationContext


class Reporter:
    """Render ``migration_report.md`` from MigrationContext collectors."""

    def __init__(self, session_manager: SessionManager) -> None:
        self._session_manager = session_manager

    def render(self, context: MigrationContext) -> None:
        """Write the customer-facing report into the active session bundle."""
        report = "\n".join(self._build_lines(context)) + "\n"
        self._session_manager.paths.report_path.write_text(report, encoding="utf-8")

    def _build_lines(self, context: MigrationContext) -> list[str]:
        mode = context.ExecutionMode.upper()
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
            "## Changes",
            "",
            *self._format_changes(context.Changes),
            "",
            "## Warnings — Manual Review Required",
            "",
            *self._format_diagnostics(context.Warnings),
            "",
        ]

    def _title_for_mode(self, mode: str) -> str:
        if mode == "DISCOVER":
            return "Migration Readiness Report"
        if mode == "PREVIEW":
            return "Migration Preview Report"
        return "Migration Report"

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
