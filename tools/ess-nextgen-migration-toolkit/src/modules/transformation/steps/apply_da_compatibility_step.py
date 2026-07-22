"""Apply DA-compatibility transformations to the agent's bot record + gpt component.

This is the first transformation step. A CA agent becomes a DA agent only when
its GPT-model nomenclature and template are DA-compatible. A customer overlay
(created e.g. by renaming the agent, or editing instructions/starters) keeps
overriding the managed base even after a major-version update, so the effective
record can still point at the CA values (``PreviewModels`` / ``default-*``) and
block the CA->DA transition. We rewrite them:

- gpt.default component ``data`` (YAML): ``aISettings.model.kind: PreviewModels``
  (+ ``modelNameHint``) -> ``kind: MicrosoftCopilotModels``.
- bot ``template``: ``default-<version>`` -> ``gptagent-1.0.0``.
- bot ``configuration`` (JSON): add ``aISettings.model = {"$kind": "MicrosoftCopilotModels"}``.

The transforms are idempotent (already-DA values are left untouched). Only
changed records produce a pending writeback for the output module.
"""

from __future__ import annotations

import json
import re
from typing import Any

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import MigrationContext

_BOTS_ENTITY = "bots"
_BOTCOMPONENTS_ENTITY = "botcomponents"

# Dataverse record fields (confirm against a live record if writeback fails).
_BOT_TEMPLATE_FIELD = "template"
_BOT_CONFIGURATION_FIELD = "configuration"
_BOTCOMPONENT_ID_FIELD = "botcomponentid"
_BOTCOMPONENT_DATA_FIELD = "data"

# CA -> DA nomenclature.
_CA_TEMPLATE_PREFIX = "default"
_DA_TEMPLATE = "gptagent-1.0.0"
_DA_MODEL = {"$kind": "MicrosoftCopilotModels"}

_PREVIEW_MODEL_KIND_RE = re.compile(r"(?m)^(?P<indent>[ \t]*)kind:[ \t]*PreviewModels[ \t]*$")
_MODEL_NAME_HINT_RE = re.compile(r"(?m)^[ \t]*modelNameHint:.*(?:\r?\n)?")


class ApplyDaCompatibilityStep(MigrationPipelineStep):
    """Rewrite CA GPT-model nomenclature + template to DA-compatible values."""

    def __init__(self, logger: Logger, supported_modes: tuple[str, ...]) -> None:
        super().__init__(
            description="Apply DA-compatibility transformations to the agent's core config.",
            supported_modes=supported_modes,
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        self._transform_bot_record(context)
        self._transform_gpt_component(context)
        self._logger.LogInfo(
            f"DA-compatibility produced {len(context.pending_writes)} pending write(s).",
            pipeline_stage="Transformation",
            pipeline_step=self.name(),
        )
        return context

    def _transform_bot_record(self, context: MigrationContext) -> None:
        bot = context.agent_bot_record
        if not bot:
            return
        record_id = context.selected_agent_id
        if not record_id:
            return

        changes: dict[str, Any] = {}
        new_template, template_changed = transform_bot_template(bot.get(_BOT_TEMPLATE_FIELD))
        if template_changed:
            changes[_BOT_TEMPLATE_FIELD] = new_template
        new_config, config_changed = transform_bot_configuration(bot.get(_BOT_CONFIGURATION_FIELD))
        if config_changed:
            changes[_BOT_CONFIGURATION_FIELD] = new_config

        if changes:
            _append_pending_write(context, _BOTS_ENTITY, record_id, changes)

    def _transform_gpt_component(self, context: MigrationContext) -> None:
        component = context.agent_gpt_component
        if not component:
            return
        record_id = component.get(_BOTCOMPONENT_ID_FIELD)
        if not isinstance(record_id, str) or not record_id:
            self._logger.LogWarning(
                "gpt.default component has no id; skipping DA-compatibility rewrite.",
                pipeline_stage="Transformation",
                pipeline_step=self.name(),
            )
            return

        new_data, data_changed = transform_gpt_data(component.get(_BOTCOMPONENT_DATA_FIELD))
        if data_changed:
            _append_pending_write(
                context,
                _BOTCOMPONENTS_ENTITY,
                record_id,
                {_BOTCOMPONENT_DATA_FIELD: new_data},
            )


def transform_bot_template(template: Any) -> tuple[Any, bool]:
    """Rewrite a CA ``default-*`` template to the DA ``gptagent-1.0.0`` template."""
    if isinstance(template, str) and template.startswith(_CA_TEMPLATE_PREFIX):
        return _DA_TEMPLATE, True
    return template, False


def transform_bot_configuration(configuration: Any) -> tuple[Any, bool]:
    """Add ``aISettings.model = MicrosoftCopilotModels`` to the bot configuration JSON.

    The configuration is stored as a JSON string. Returns the (possibly updated)
    JSON string and whether it changed. Non-JSON / unexpected shapes are left as-is.
    """
    if not isinstance(configuration, str) or not configuration:
        return configuration, False
    try:
        parsed = json.loads(configuration)
    except json.JSONDecodeError:
        return configuration, False
    if not isinstance(parsed, dict):
        return configuration, False

    ai_settings = parsed.get("aISettings")
    if not isinstance(ai_settings, dict):
        return configuration, False
    if ai_settings.get("model") == _DA_MODEL:
        return configuration, False

    ai_settings["model"] = dict(_DA_MODEL)
    return json.dumps(parsed, ensure_ascii=False), True


def transform_gpt_data(data: Any) -> tuple[Any, bool]:
    """Rewrite the gpt component YAML model kind from Preview to MicrosoftCopilotModels."""
    if not isinstance(data, str) or not data:
        return data, False
    updated, kind_count = _PREVIEW_MODEL_KIND_RE.subn(
        lambda match: f"{match.group('indent')}kind: MicrosoftCopilotModels", data
    )
    updated, hint_count = _MODEL_NAME_HINT_RE.subn("", updated)
    return updated, (kind_count > 0 or hint_count > 0)


def _append_pending_write(
    context: MigrationContext, entity_set: str, record_id: str, changes: dict[str, Any]
) -> None:
    context.pending_writes.append(
        {"entity_set": entity_set, "record_id": record_id, "changes": changes}
    )
