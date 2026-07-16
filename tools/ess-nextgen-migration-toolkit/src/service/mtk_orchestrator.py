"""ESS NextGen Migration Toolkit — orchestration entry point.

This is the single entry point for the toolkit and the top of the dependency
graph (the Application / Orchestration layer). It composes and drives the lower
layers — the Pipeline Engine (``core.pipeline``), the pipeline-stage business
logic (``modules`` — preprocessing, migration, postprocessing), and the
Dataverse Client (``core.outbound``). For now it is a hello-world placeholder;
orchestration logic and any command surface are added by later tasks.

Run it via the ``mtk`` dispatcher (``./mtk.sh start``), which provisions the
environment and then launches this module.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Toolkit orchestration entry point. Placeholder until wired up."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Hello from the ESS NextGen Migration Toolkit orchestrator.")


if __name__ == "__main__":
    main()
