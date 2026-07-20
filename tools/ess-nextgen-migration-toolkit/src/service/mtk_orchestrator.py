"""ESS NextGen Migration Toolkit — orchestration entry point."""

from __future__ import annotations

from pathlib import Path

from core.logging import Logger, Reporter
from core.models import ExecutionMode
from core.pipelines import ChainedPipeline
from modules.migration import MigrationContext
from modules.migration.migration_pipeline import build_migration_pipeline
from modules.postprocessing import build_output_pipeline
from modules.preprocessing import build_input_pipeline

OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "output"


def main() -> None:
    """Build and run the ESS migration super-pipeline."""
    context = MigrationContext(ExecutionMode=ExecutionMode.READONLY)
    logger = Logger.start_session(OUTPUT_ROOT, context)
    try:
        toolkit = (
            ChainedPipeline[MigrationContext]()
            .add(build_input_pipeline(logger))
            .add(build_migration_pipeline(logger))
            .add(build_output_pipeline(logger))
        )
        toolkit.run(context)
    finally:
        try:
            Reporter(logger.session_manager).render(context)
            logger.LogInfo(
                f"Session bundle written to {logger.session_manager.paths.session_dir}",
                pipeline_stage="Output",
                pipeline_step="Reporter",
            )
        finally:
            logger.close()


if __name__ == "__main__":
    main()
