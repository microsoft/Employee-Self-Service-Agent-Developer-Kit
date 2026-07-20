"""ESS migration step base — mode-gating layer above the generic PipelineStep.

The generic ``PipelineStep`` is context-agnostic (``can_execute`` returns True).
This module provides ``MigrationPipelineStep``, the mandatory base for all ESS
migration steps.  It binds the step to ``MigrationContext`` and implements
automatic execution-mode gating via ``supported_modes``.

Future consumers (non-ESS toolkits) that extend ``MigrationContext`` with their
own fields get mode-gating for free by subclassing ``MigrationPipelineStep``.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.pipelines import PipelineStep
from modules.migration.models.migration_context import MigrationContext


class MigrationPipelineStep(PipelineStep[MigrationContext, MigrationContext]):
    """Base for all ESS migration steps operating on MigrationContext.

    Provides automatic execution-mode gating: if a subclass declares
    ``supported_modes`` (e.g. ``("PREVIEW", "MIGRATE")``), the step is
    skipped when the context's ``ExecutionMode`` is not in that set.

    Steps with empty ``supported_modes`` (the default) run in all modes.

    Subclasses may override ``can_execute`` for richer conditions but should
    call ``super().can_execute(context)`` to preserve mode gating.
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        description: str | None = None,
        supported_modes: Iterable[str] = (),
    ) -> None:
        super().__init__(
            input_type=MigrationContext,
            output_type=MigrationContext,
            name=name,
            description=description,
            supported_modes=supported_modes,
        )

    def can_execute(self, context: MigrationContext) -> bool:
        """Gate execution by ``supported_modes`` against ``context.ExecutionMode``.

        Returns True if:
        - ``supported_modes`` is empty (step runs in all modes), OR
        - ``context.ExecutionMode`` is in ``supported_modes``.
        """
        modes = self.supported_modes()
        if modes:
            return context.ExecutionMode.upper() in modes
        return True
