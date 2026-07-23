"""RULE-006 — Disable additional unsupported-trigger topics.

Beyond OnActivity (RULE-003) and OnGeneratedResponse (RULE-004), several other
topic triggers have no Declarative Agent equivalent (per the CA->DA component
support analysis). They are handled with the same disable-but-preserve mitigation
via the shared ``DeprecateTriggerTopicStep`` base.
"""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.deprecate_trigger_topic_step import DeprecateTriggerTopicStep

# Additional unsupported topic triggers -> customer guidance (analysis-sourced).
_UNSUPPORTED_TRIGGERS = {
    "OnUnknownIntent": (
        "Recreate fallback handling with supported DA capabilities (e.g. agent instructions)."
    ),
    "OnPlanComplete": "Re-implement any post-plan behavior with supported DA constructs.",
    "OnSystemRedirect": "Legacy trigger with no DA equivalent; remove or redesign the scenario.",
    "OnSelectIntent": (
        "Rely on DA instructions to avoid multiple-topic selection; redesign if needed."
    ),
    "OnEscalate": (
        "Re-implement live-agent hand-off when DA support lands (tracked for a later wave)."
    ),
}


class DisableUnsupportedTriggerTopicsStep(DeprecateTriggerTopicStep):
    """Disable + deprecate topics whose trigger is one of the additional unsupported kinds."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="DisableUnsupportedTriggerTopics",
            description="Disable + deprecate additional unsupported-trigger topics (RULE-006).",
            rule_id="RULE-006",
            rule_name="Disable Unsupported-Trigger Topics",
            triggers=_UNSUPPORTED_TRIGGERS,
        )
