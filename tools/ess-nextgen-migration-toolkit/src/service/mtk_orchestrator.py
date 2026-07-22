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


def _is_dev_mode() -> bool:
    return "--dev" in sys.argv


def main() -> None:
    """Build and run the ESS migration super-pipeline."""
    is_dev_mode = _is_dev_mode()
    context = MigrationContext(mode=ExecutionMode.READONLY)
    logger = Logger.start_session(OUTPUT_ROOT, context, report_filename=REPORT_FILENAME)
    try:
        toolkit = (
            ChainedPipeline[MigrationContext]()
            .add(build_input_pipeline(logger, SUPPORTED_MODES, is_dev_mode=is_dev_mode))
            .add(build_transformation_pipeline(logger, SUPPORTED_MODES))
            .add(build_output_pipeline(logger, SUPPORTED_MODES))
        )
        toolkit.run(context)
    except Exception:
        import traceback

        traceback.print_exc()
        raise
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
