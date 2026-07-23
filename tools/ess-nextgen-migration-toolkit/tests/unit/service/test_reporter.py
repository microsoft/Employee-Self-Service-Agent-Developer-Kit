"""Unit tests for the ESS service-layer migration Reporter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.logging import Logger, SessionManager
from core.models import ChangeEntry, DiagnosticEntry
from modules.transformation.models import CustomizationComponent, ExecutionMode, MigrationContext
from service.reporter import Reporter

FIXED_TIME = datetime(2026, 7, 18, 14, 32, 5)


def test_reporter_renders_customer_report_from_context_collectors(tmp_path: Path) -> None:
    context = MigrationContext(
        mode=ExecutionMode.WRITEBACK,
        environment_url="https://contoso.crm.dynamics.com",
        tid="tenant-123",
        upn="admin@contoso.com",
        preferred_solution="contoso_ess",
        selected_agent_id="bot-hr",
        selected_agent_name="ESS HR Agent",
        discovered_agents=[
            {
                "name": "ESS HR Agent",
                "botid": "bot-hr",
                "statecode": 0,
                "schemaname": "msdyn_copilotforemployeeselfservicehr",
            },
            {
                "name": "ESS IT Agent",
                "botid": "bot-it",
                "statecode": 0,
                "schemaname": "msdyn_copilotforemployeeselfserviceit",
            },
        ],
        customizations={
            "c1": CustomizationComponent(
                component_id="c1",
                schemaname="ess_escalate",
                name="Escalate to Agent",
                component_type=9,
                component_type_label="Topic (V2)",
                statecode=0,
                statuscode=1,
            )
        },
        Changes=[
            ChangeEntry(
                message="Disabled the topic and prefixed its title [DEPRECATED].",
                rule_id="RULE-006",
                title="Handle OnEscalate Topic",
                component="Escalate to Agent [ess_escalate]",
                component_type="botcomponent / Topic (V2)",
            )
        ],
        Warnings=[
            DiagnosticEntry(
                message="OnEscalate trigger unsupported.",
                severity="WARNING",
                component="Escalate to Agent",
                recommendation="Implement escalation via a supported hand-off action.",
            )
        ],
    )
    manager = SessionManager(tmp_path, clock=lambda: FIXED_TIME)
    manager.create_session()

    Reporter(manager).render(context)

    report = manager.paths.report_path.read_text(encoding="utf-8")
    # Title + banner + summary table.
    assert "# Migration Report" in report
    assert "## 📋 Summary" in report
    assert "| Execution Mode | `WRITEBACK` |" in report
    assert "| Selected Agent | ESS HR Agent |" in report
    assert "| Customizations Discovered | 1 |" in report
    # Environment table.
    assert "## 🌐 Environment" in report
    assert "| Environment URL | https://contoso.crm.dynamics.com |" in report
    assert "| Target Solution | contoso_ess |" in report
    # Agents table + selected marker.
    assert "## 🤖 Agents" in report
    assert "| ESS IT Agent |" in report
    assert "| ESS HR Agent | msdyn_copilotforemployeeselfservicehr | Active | ✓ |" in report
    # Customizations extracted table.
    assert "## 🧩 Customizations Extracted" in report
    assert "| botcomponent / Topic (V2) | Escalate to Agent | ess_escalate | Active |" in report
    # Mitigations table.
    assert "## 🔧 Migration Mitigations by Component" in report
    assert "| Component Type | Component | Mitigations Applied (Rules) |" in report
    assert "**RULE-006 — Handle OnEscalate Topic**" in report
    # Warnings table.
    assert "## ⚠️ Warnings — Manual Review Required" in report
    assert "| # | Component | Reason | Recommendation |" in report
    assert (
        "| 1 | Escalate to Agent | OnEscalate trigger unsupported. "
        "| Implement escalation via a supported hand-off action. |"
    ) in report
    # Next steps (actionable checkboxes) + closing.
    assert "## ✅ Next Steps — Action Required" in report
    assert "- [ ] **Run your own end-to-end evaluations**" in report
    assert "_Thanks for using the **ESS Migration Toolkit (MTK)**._ 🚀" in report


def test_reporter_renders_empty_sections_gracefully(tmp_path: Path) -> None:
    context = MigrationContext(mode=ExecutionMode.READONLY)
    manager = SessionManager(tmp_path, clock=lambda: FIXED_TIME)
    manager.create_session()

    Reporter(manager).render(context)

    report = manager.paths.report_path.read_text(encoding="utf-8")
    assert "# Migration Readiness Report" in report
    assert "No ESS agents discovered." in report
    assert "No customer customizations were discovered for the selected agent." in report
    assert "No component transformations recorded." in report
    assert "✅ No manual-review warnings — nothing needs your attention here." in report
    assert "✅ No errors recorded — the run completed without failures." in report
    assert "_Thanks for using the **ESS Migration Toolkit (MTK)**._ 🚀" in report


def test_logger_and_reporter_leave_exactly_two_bundle_files(tmp_path: Path) -> None:
    context = MigrationContext()
    logger = Logger.start_session(
        tmp_path, context, report_filename="migration_report.md", clock=lambda: FIXED_TIME
    )
    logger.close()

    Reporter(logger.session_manager).render(context)

    bundle_files = sorted(path.name for path in logger.session_manager.paths.session_dir.iterdir())
    assert bundle_files == ["migration_report.md", "session.log"]
