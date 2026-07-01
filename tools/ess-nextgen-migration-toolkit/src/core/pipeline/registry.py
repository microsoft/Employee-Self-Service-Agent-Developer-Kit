"""Pipeline step registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.pipeline.exceptions import PipelineConfigurationError
from core.pipeline.step import PipelineStep


@dataclass(frozen=True)
class PipelineRegistry:
    """Ordered immutable registry of pipeline steps.

    Purpose:
        Maintain the configured step order for a pipeline.
    Responsibilities:
        Register steps, reject duplicate names, and expose immutable snapshots.
        Registration order is the explicit deterministic execution order.
    Inputs:
        PipelineStep instances supplied by a builder.
    Outputs:
        A tuple of steps used to build an immutable Pipeline.
    """

    _steps: tuple[PipelineStep[Any, Any], ...] = field(default_factory=tuple)

    def register(self, step: PipelineStep[Any, Any]) -> PipelineRegistry:
        """Return a new registry containing ``step`` after duplicate validation."""
        step_name = step.name()
        if step_name in self.names():
            raise PipelineConfigurationError(f"Pipeline step '{step_name}' is already registered.")
        return PipelineRegistry((*self._steps, step))

    def steps(self) -> tuple[PipelineStep[Any, Any], ...]:
        """Return the registered steps in deterministic execution order."""
        return self._steps

    def names(self) -> tuple[str, ...]:
        """Return registered step names in deterministic execution order."""
        return tuple(step.name() for step in self._steps)

    def __len__(self) -> int:
        """Return the number of registered steps."""
        return len(self._steps)
