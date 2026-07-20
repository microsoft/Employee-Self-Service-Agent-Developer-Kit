"""Pipeline context contracts."""

from __future__ import annotations

from typing import Protocol


class PipelineContext(Protocol):
    """Marker contract for state threaded through context-preserving pipelines.

    Purpose:
        Identify objects that may serve as the shared pipeline context.
    Responsibilities:
        Carry all state between steps without hidden globals.
    Inputs:
        The concrete context object supplied to a pipeline run.
    Outputs:
        The same context type, enriched by each context-preserving step.
    """
