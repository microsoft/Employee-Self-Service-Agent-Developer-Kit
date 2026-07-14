"""Generic staged super-pipeline composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from core.pipeline.pipeline import Pipeline

TContext = TypeVar("TContext")


@dataclass(frozen=True)
class StagedPipeline(Generic[TContext]):
    """Generic ordered composition of context-preserving stage pipelines.

    Purpose:
        Represent a super-pipeline: an ordered sequence of stage pipelines that
        each transform a single shared context, executed left to right.
    Responsibilities:
        Hold the ordered stages immutably, execute them in declaration order,
        and return the enriched context. Contains no product or domain logic.
    Inputs:
        Stage pipelines declared as ``Pipeline[TContext, TContext]`` and a
        shared ``TContext`` supplied at run time.
    Outputs:
        The same context type after every configured stage has run.
    """

    _stages: tuple[Pipeline[TContext, TContext], ...] = field(default_factory=tuple)

    @property
    def stages(self) -> tuple[Pipeline[TContext, TContext], ...]:
        """Return the ordered configured stages."""
        return self._stages

    def add(self, stage: Pipeline[TContext, TContext]) -> StagedPipeline[TContext]:
        """Return a new staged pipeline with ``stage`` appended after the rest."""
        return StagedPipeline(_stages=(*self._stages, stage))

    def _ordered_stages(self) -> tuple[Pipeline[TContext, TContext], ...]:
        """Return the stages to execute, in order.

        Subclasses override this to impose named-stage semantics and
        configuration validation while reusing :meth:`run`.
        """
        return self._stages

    def run(self, context: TContext) -> TContext:
        """Execute every configured stage in order and return the context."""
        current = context
        for stage in self._ordered_stages():
            current = stage.run(current)
        return current
