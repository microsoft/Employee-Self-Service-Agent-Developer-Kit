"""ESS Migration Context — domain-specific extension of ExecutionContext."""

from __future__ import annotations

from dataclasses import dataclass

from core.models import ExecutionContext


@dataclass
class MigrationContext(ExecutionContext):
    """ESS migration-specific execution context.

    Extends the base ``ExecutionContext`` (which carries ExecutionMode
    and diagnostic collectors) with ESS domain state.  Migration-rule tasks
    will add fields here (e.g. ``ComponentSet``, agent metadata) as they land.

    All ESS migration steps operate on this type via ``MigrationPipelineStep``.
    """
