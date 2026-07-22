"""Unit tests for the DA-compatibility transformation step."""

from __future__ import annotations

import json
from typing import Any, cast

from core.logging import Logger
from modules.transformation.models import MigrationContext
from modules.transformation.steps.apply_da_compatibility_step import (
    ApplyDaCompatibilityStep,
    transform_bot_configuration,
    transform_bot_template,
    transform_gpt_data,
)


class FakeLogger:
    def LogInfo(self, *_: object, **__: object) -> None: ...
    def LogWarning(self, *_: object, **__: object) -> None: ...
    def LogDebug(self, *_: object, **__: object) -> None: ...


def _step() -> ApplyDaCompatibilityStep:
    return ApplyDaCompatibilityStep(cast(Logger, FakeLogger()), ("READONLY", "WRITEBACK"))


# --- pure transforms ---


def test_transform_bot_template_rewrites_default_to_gptagent() -> None:
    assert transform_bot_template("default-2.1.0") == ("gptagent-1.0.0", True)


def test_transform_bot_template_leaves_da_template_untouched() -> None:
    assert transform_bot_template("gptagent-1.0.0") == ("gptagent-1.0.0", False)


def test_transform_gpt_data_rewrites_preview_models_kind_and_drops_hint() -> None:
    data = (
        "aISettings:\n"
        "  model:\n"
        "    kind: PreviewModels\n"
        "    modelNameHint: GPT41\n"
        "  extensionData:\n"
    )
    updated, changed = transform_gpt_data(data)

    assert changed is True
    assert "kind: MicrosoftCopilotModels" in updated
    assert "PreviewModels" not in updated
    assert "modelNameHint" not in updated
    # Indentation preserved.
    assert "    kind: MicrosoftCopilotModels\n" in updated


def test_transform_gpt_data_is_idempotent_for_already_da_values() -> None:
    data = "aISettings:\n  model:\n    kind: MicrosoftCopilotModels\n"
    assert transform_gpt_data(data) == (data, False)


def test_transform_bot_configuration_adds_model_to_ai_settings() -> None:
    config = json.dumps({"aISettings": {"optInUseLatestModels": False}, "recognizer": {}})

    updated, changed = transform_bot_configuration(config)

    assert changed is True
    parsed = json.loads(updated)
    assert parsed["aISettings"]["model"] == {"$kind": "MicrosoftCopilotModels"}
    assert parsed["aISettings"]["optInUseLatestModels"] is False
    assert parsed["recognizer"] == {}


def test_transform_bot_configuration_is_idempotent_when_model_present() -> None:
    config = json.dumps({"aISettings": {"model": {"$kind": "MicrosoftCopilotModels"}}})
    assert transform_bot_configuration(config) == (config, False)


def test_transform_bot_configuration_ignores_non_json() -> None:
    assert transform_bot_configuration("not-json") == ("not-json", False)


# --- step wiring ---


def test_step_produces_pending_writes_for_bot_and_gpt_component() -> None:
    step = _step()
    context = MigrationContext(
        selected_agent_id="bot-1",
        agent_bot_record={
            "template": "default-2.1.0",
            "configuration": json.dumps({"aISettings": {"optInUseLatestModels": False}}),
        },
        agent_gpt_component={
            "botcomponentid": "gpt-1",
            "data": "aISettings:\n  model:\n    kind: PreviewModels\n",
        },
    )

    result = step.execute(context)

    writes: dict[str, dict[str, Any]] = {w["entity_set"]: w for w in result.pending_writes}
    assert set(writes) == {"bots", "botcomponents"}

    bot_write = writes["bots"]
    assert bot_write["record_id"] == "bot-1"
    assert bot_write["changes"]["template"] == "gptagent-1.0.0"
    assert json.loads(bot_write["changes"]["configuration"])["aISettings"]["model"] == {
        "$kind": "MicrosoftCopilotModels"
    }

    gpt_write = writes["botcomponents"]
    assert gpt_write["record_id"] == "gpt-1"
    assert "MicrosoftCopilotModels" in gpt_write["changes"]["data"]


def test_step_produces_no_writes_when_already_da_compatible() -> None:
    step = _step()
    context = MigrationContext(
        selected_agent_id="bot-1",
        agent_bot_record={
            "template": "gptagent-1.0.0",
            "configuration": json.dumps(
                {"aISettings": {"model": {"$kind": "MicrosoftCopilotModels"}}}
            ),
        },
        agent_gpt_component={
            "botcomponentid": "gpt-1",
            "data": "aISettings:\n  model:\n    kind: MicrosoftCopilotModels\n",
        },
    )

    result = step.execute(context)

    assert result.pending_writes == []


def test_step_no_writes_when_agent_data_absent() -> None:
    step = _step()
    result = step.execute(MigrationContext(selected_agent_id="bot-1"))
    assert result.pending_writes == []
