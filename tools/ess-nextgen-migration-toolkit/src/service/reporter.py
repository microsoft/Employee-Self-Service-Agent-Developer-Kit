"""Customer-facing migration report rendering (ESS service layer).

This is ESS-specific output: it renders the well-structured customer-facing
``migration_report.md`` — environment + agents context, the customizations
extracted, the mitigations applied per component, warnings/errors, and the
customer's next steps — from the ``MigrationContext`` collectors and domain
state. It lives in ``service/`` — not ``core/`` — so the framework's diagnostics
infrastructure (Logger, SessionManager) stays product-agnostic while the
migration-flavoured report shape is owned by the domain.
"""

from __future__ import annotations

from core.logging.session_manager import SessionManager
from core.models.execution_context import ChangeEntry, DiagnosticEntry
from modules.transformation.models import CustomizationComponent, MigrationContext

_NOT_PROVIDED = "—"


def _escape_cell(text: str) -> str:
    """Make a value safe for a single Markdown table cell."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def _state_label(statecode: int | None) -> str:
    """Human-readable botcomponent/bot record state."""
    if statecode == 0:
        return "Active"
    if statecode == 1:
        return "Inactive"
    return "unknown"


class Reporter:
    """Render the customer-facing ``migration_report.md`` from a MigrationContext."""

    def __init__(self, session_manager: SessionManager) -> None:
        self._session_manager = session_manager

    def render(self, context: MigrationContext) -> None:
        """Write the customer-facing report into the active session bundle."""
        report = "\n".join(self._build_lines(context)) + "\n"
        self._session_manager.paths.report_path.write_text(report, encoding="utf-8")

    def _build_lines(self, context: MigrationContext) -> list[str]:
        mode = context.mode.upper()
        title = self._title_for_mode(mode)
        return [
            f"# {title}",
            "",
            self._banner(context),
            "",
            "## 📋 Summary",
            "",
            *self._format_summary(context),
            "",
            "## 🌐 Environment",
            "",
            *self._format_environment(context),
            "",
            "## 🤖 Agents",
            "",
            *self._format_agents(context),
            "",
            "## 🧩 Customizations Extracted",
            "",
            *self._format_customizations(context),
            "",
            "## 🔧 Migration Mitigations by Component",
            "",
            *self._format_per_topic_summary(context.Changes),
            "",
            "## ⚠️ Warnings — Manual Review Required",
            "",
            *self._format_diagnostics(context.Warnings),
            "",
            "## ❌ Errors",
            "",
            *self._format_errors(context.Errors),
            "",
            "## ✅ Next Steps — Action Required",
            "",
            *self._format_next_steps(context),
            "",
            "---",
            "",
            "_Thanks for using the **ESS Migration Toolkit (MTK)**._ 🚀",
            "",
        ]

    def _title_for_mode(self, mode: str) -> str:
        if mode == "READONLY":
            return "Migration Readiness Report"
        return "Migration Report"

    def _banner(self, context: MigrationContext) -> str:
        """A one-line status banner summarising the run outcome."""
        mode = context.mode.upper()
        if context.Errors:
            return f"> ❌ **{len(context.Errors)} error(s)** — migration did not complete cleanly."
        if context.Warnings:
            return (
                f"> ⚠️ **Completed with {len(context.Warnings)} item(s) needing manual review.** "
                f"See *Next Steps* below."
            )
        if mode == "READONLY":
            return "> 🔍 **Read-only preview** — no changes were written back."
        return "> ✅ **Migration completed** — review the mitigations and run your own evals."

    def _format_summary(self, context: MigrationContext) -> list[str]:
        """Run metrics as a compact two-column table."""
        mode = context.mode.upper()
        components_changed = len({change.component or "" for change in context.Changes})
        warnings = len(context.Warnings)
        errors = len(context.Errors)
        return [
            "| Metric | Value |",
            "| --- | --- |",
            f"| Execution Mode | `{mode}` |",
            f"| Selected Agent | {_escape_cell(context.selected_agent_name or _NOT_PROVIDED)} |",
            f"| Customizations Discovered | {len(context.customizations)} |",
            f"| Components Changed | {components_changed} |",
            f"| Warnings | {warnings} {'⚠️' if warnings else '✅'} |",
            f"| Errors | {errors} {'❌' if errors else '✅'} |",
        ]

    def _format_environment(self, context: MigrationContext) -> list[str]:
        """Environment + tenant + target-solution context as a table."""
        target_solution = context.preferred_solution or context.ess_solution_unique_name
        rows = [
            ("Environment URL", context.environment_url),
            ("Tenant ID", context.tid),
            ("Signed-in User", context.upn),
            ("Target Solution", target_solution),
        ]
        lines = ["| Field | Value |", "| --- | --- |"]
        for field_name, value in rows:
            lines.append(f"| {field_name} | {_escape_cell(value or _NOT_PROVIDED)} |")
        return lines

    def _format_agents(self, context: MigrationContext) -> list[str]:
        """The ESS agents discovered in the environment + which one was migrated."""
        agents = context.discovered_agents
        if not agents:
            selected = context.selected_agent_name
            return [f"Selected agent: {selected}." if selected else "No ESS agents discovered."]

        lines = [
            f"Discovered {len(agents)} ESS agent(s) in the environment; "
            f"**{context.selected_agent_name or '(none)'}** was selected for migration.",
            "",
            "| Agent | Schema Name | State | Selected |",
            "| --- | --- | --- | --- |",
        ]
        for agent in agents:
            name = _string(agent.get("name")) or "(unnamed agent)"
            schema = _string(agent.get("schemaname")) or _NOT_PROVIDED
            state = _state_label(_int(agent.get("statecode")))
            selected = "✓" if _string(agent.get("botid")) == context.selected_agent_id else ""
            lines.append(
                f"| {_escape_cell(name)} | {_escape_cell(schema)} | {state} | {selected} |"
            )
        return lines

    def _format_customizations(self, context: MigrationContext) -> list[str]:
        """The customer customizations the toolkit extracted, with counts + details."""
        customizations = list(context.customizations.values())
        if not customizations:
            return ["No customer customizations were discovered for the selected agent."]

        lines = [
            f"Extracted {len(customizations)} customized component(s) for migration:",
            "",
            "| Component Type | Component | Schema Name | Original State |",
            "| --- | --- | --- | --- |",
        ]
        for component in sorted(customizations, key=_customization_sort_key):
            lines.append(
                f"| {_escape_cell(_component_type(component))} "
                f"| {_escape_cell(component.name or _NOT_PROVIDED)} "
                f"| {_escape_cell(component.schemaname or _NOT_PROVIDED)} "
                f"| {_state_label(component.statecode)} |"
            )
        return lines

    def _format_per_topic_summary(self, changes: list[ChangeEntry]) -> list[str]:
        """Per-component table: type, component, and every rule's mitigation applied.

        One row per component (topic), with all the rules' mitigations merged into
        the third cell — styled after the CA→DA component-support analysis. Surfaced
        in the migration report (READONLY previews too).
        """
        if not changes:
            return ["No component transformations recorded."]

        by_component: dict[str, list[ChangeEntry]] = {}
        for change in changes:
            key = change.component or "(agent-level)"
            by_component.setdefault(key, []).append(change)

        lines: list[str] = [
            "| Component Type | Component | Mitigations Applied (Rules) |",
            "| --- | --- | --- |",
        ]
        for component, entries in by_component.items():
            component_type = next(
                (entry.component_type for entry in entries if entry.component_type), "—"
            )
            mitigations = "<br>".join(self._mitigation_cell(entry) for entry in entries)
            lines.append(
                f"| {_escape_cell(component_type)} | {_escape_cell(component)} | {mitigations} |"
            )
        return lines

    @staticmethod
    def _mitigation_cell(entry: ChangeEntry) -> str:
        """One rule's mitigation, formatted for a Markdown table cell."""
        rule = " — ".join(part for part in (entry.rule_id, entry.title) if part)
        prefix = f"**{_escape_cell(rule)}**: " if rule else ""
        return f"{prefix}{_escape_cell(entry.message)}"

    def _format_next_steps(self, context: MigrationContext) -> list[str]:
        """Customer's post-migration checklist — validate before going further."""
        mode = context.mode.upper()
        agent = context.selected_agent_name or "the migrated agent"
        intro = (
            "This was a **read-only preview** — no changes were written back. Before applying them:"
            if mode == "READONLY"
            else "Changes were **written back** to your environment. Before relying on them:"
        )
        return [
            intro,
            "",
            f"- [ ] Review every mitigation in the table above for **{agent}** and confirm "
            "each disabled/deprecated topic matches your intent.",
            "- [ ] Manually validate the migrated agent in **Copilot Studio** — open the "
            "affected topics and check the applied changes.",
            "- [ ] **Run your own end-to-end evaluations** against the agent (happy paths "
            "and edge cases) and confirm responses meet your quality bar.",
            "- [ ] Address every item under *⚠️ Warnings — Manual Review Required* above; "
            "these need a human decision.",
            "- [ ] Only then promote the target solution through your **ALM pipeline** "
            "(dev → test → prod).",
        ]

    def _format_diagnostics(self, diagnostics: list[DiagnosticEntry]) -> list[str]:
        if not diagnostics:
            return ["✅ No manual-review warnings — nothing needs your attention here."]
        return self._diagnostics_table(diagnostics, detail_header="Reason")

    def _format_errors(self, errors: list[DiagnosticEntry]) -> list[str]:
        if not errors:
            return ["✅ No errors recorded — the run completed without failures."]
        return self._diagnostics_table(errors, detail_header="Error")

    @staticmethod
    def _diagnostics_table(entries: list[DiagnosticEntry], *, detail_header: str) -> list[str]:
        """Render warnings/errors as a numbered, readable table."""
        lines = [
            f"| # | Component | {detail_header} | Recommendation |",
            "| --- | --- | --- | --- |",
        ]
        for index, entry in enumerate(entries, start=1):
            component = _escape_cell(entry.component or _NOT_PROVIDED)
            message = _escape_cell(entry.message)
            recommendation = _escape_cell(entry.recommendation or _NOT_PROVIDED)
            lines.append(f"| {index} | {component} | {message} | {recommendation} |")
        return lines


def _component_type(component: CustomizationComponent) -> str:
    """A human-readable component-type label (e.g. ``botcomponent / Topic (V2)``)."""
    label = component.component_type_label or (
        f"componenttype {component.component_type}"
        if component.component_type is not None
        else None
    )
    return f"botcomponent / {label}" if label else "botcomponent"


def _customization_sort_key(component: CustomizationComponent) -> tuple[str, str]:
    return (component.name or "", component.schemaname or "")


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) else None
