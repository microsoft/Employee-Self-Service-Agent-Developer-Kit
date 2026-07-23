"""ESS NextGen Migration Toolkit — orchestration entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from core.logging import Logger
from core.pipelines import ChainedPipeline
from modules.postprocessing import build_output_pipeline
from modules.preprocessing import build_input_pipeline
from modules.transformation import MigrationContext
from modules.transformation.models import ExecutionMode
from modules.transformation.transformation_pipeline import build_transformation_pipeline
from service.constants import REPORT_FILENAME, SUPPORTED_MODES
from service.reporter import Reporter

TOOLKIT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = TOOLKIT_ROOT / "output"


def _is_dev_mode(argv: list[str]) -> bool:
    return "--dev" in argv


def _resolve_mode(argv: list[str]) -> ExecutionMode:
    """Resolve the execution mode from ``--mode readonly|writeback`` (default READONLY).

    Accepts both ``--mode writeback`` and ``--mode=writeback`` (case-insensitive).
    """
    value: str | None = None
    for index, arg in enumerate(argv):
        if arg == "--mode" and index + 1 < len(argv):
            value = argv[index + 1]
            break
        if arg.startswith("--mode="):
            value = arg.split("=", 1)[1]
            break
    if value is None or value == "":
        return ExecutionMode.READONLY
    try:
        return ExecutionMode(value.strip().upper())
    except ValueError:
        valid = ", ".join(mode.value.lower() for mode in ExecutionMode)
        raise SystemExit(f"Invalid --mode '{value}'. Valid modes: {valid}.") from None


def main(argv: list[str] | None = None) -> None:
    """Build and run the ESS migration super-pipeline."""
    args = list(sys.argv[1:]) if argv is None else list(argv)
    is_dev_mode = _is_dev_mode(args)
    context = MigrationContext(mode=_resolve_mode(args))
    logger = Logger.start_session(OUTPUT_ROOT, context, report_filename=REPORT_FILENAME)
    try:
        toolkit = (
            ChainedPipeline[MigrationContext]()
            .add(build_input_pipeline(logger, SUPPORTED_MODES, is_dev_mode=is_dev_mode))
            .add(build_transformation_pipeline(logger, SUPPORTED_MODES))
            .add(build_output_pipeline(logger, SUPPORTED_MODES))
        )
        toolkit.run(context)
        _log_summary(logger, context)
    except Exception as exc:
        logger.LogError(
            f"Migration failed ({context.mode}): {exc}. "
            f"See the session log at {logger.session_manager.paths.log_path}.",
            pipeline_stage="Orchestrator",
            pipeline_step="main",
        )
        raise
    finally:
        try:
            _render_report_if_missing(logger, context)
        finally:
            logger.close()


def _log_summary(logger: Logger, context: MigrationContext) -> None:
    """Print a one-line session summary (mode, agent, counts, bundle path)."""
    agent = context.selected_agent_name or context.selected_agent_id or "(none)"
    logger.LogInfo(
        f"Migration complete — mode={context.mode} agent={agent} "
        f"changes={len(context.Changes)} warnings={len(context.Warnings)} "
        f"errors={len(context.Errors)}. "
        f"Bundle: {logger.session_manager.paths.session_dir}",
        pipeline_stage="Orchestrator",
        pipeline_step="summary",
    )


def _render_report_if_missing(logger: Logger, context: MigrationContext) -> None:
    """Render a best-effort failure report if Output did not reach report generation."""
    if logger.session_manager.paths.report_path.exists():
        return
    Reporter(logger.session_manager).render(context)


if __name__ == "__main__":
    main()
