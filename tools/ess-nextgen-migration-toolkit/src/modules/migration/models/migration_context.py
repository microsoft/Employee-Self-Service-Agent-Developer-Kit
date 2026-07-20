"""ESS Migration Context — domain-specific extension of ExecutionContext."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.models import ExecutionContext


@dataclass
class MigrationContext(ExecutionContext):
    """ESS migration-specific execution context.

    Extends the base ``ExecutionContext`` (which carries ExecutionMode
    and diagnostic collectors) with ESS domain state.  Migration-rule tasks
    will add fields here (e.g. ``ComponentSet``, agent metadata) as they land.

    All ESS migration steps operate on this type via ``MigrationPipelineStep``.
    """

    tenant_id: str | None = None
    user_id: str | None = None
    user_email: str | None = None
    environment_url: str | None = None
    preferred_solution: str | None = None
    selected_agent_id: str | None = None
    selected_agent_name: str | None = None
    dataverse_client: Any = field(default=None, repr=False)
