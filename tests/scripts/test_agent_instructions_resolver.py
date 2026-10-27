# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit tests for ``agent_instructions_resolver.py``.

Uses a fake ``AgentBuilder``/``PVAClient``-shaped object (no network
access). The ``GptComponent`` fixture shape mirrors a real captured
``botComponentChanges`` changeset: each change wraps a ``component`` dict,
and the instruction text lives in the ``GptComponent`` under
``metadata.instructions.segments[*].value``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from flightcheck.agent_instructions_resolver import resolve_agent_instructions

FAKE_BOT_ID = "00000000-0000-0000-0000-000000003333"


@dataclass
class _FakePVA:
    """Duck-typed stand-in for the component-fetching client."""

    changeset: list[dict[str, Any]] = field(default_factory=list)
    is_configured: bool = True
    error: Exception | None = None

    def get_bot_components(self, bot_id: str) -> list[dict[str, Any]]:
        if self.error is not None:
            raise self.error
        return list(self.changeset)


def _gpt_component(*, segments: list[str] | None = None) -> dict[str, Any]:
    """Build a realistic ``GptComponent`` change entry.

    ``segments`` is a list of raw segment ``value`` strings that become the
    ``TextSegment`` entries under ``metadata.instructions.segments``.
    """
    if segments is None:
        segments = ["You are a helpful assistant."]
    return {
        "component": {
            "$kind": "GptComponent",
            "metadata": {
                "$kind": "GptComponentMetadata",
                "instructions": {
                    "$kind": "TemplateLine",
                    "segments": [
                        {"$kind": "TextSegment", "value": v} for v in segments
                    ],
                },
            },
        }
    }


def _knowledge_component() -> dict[str, Any]:
    """A non-GptComponent change entry (should be ignored)."""
    return {
        "component": {
            "$kind": "KnowledgeSourceComponent",
            "displayName": "Mock KB",
        }
    }


class TestOkSingle:
    def test_single_segment_returns_ok(self) -> None:
        pva = _FakePVA(changeset=[_gpt_component(segments=["Hello world."])])
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "ok"
        assert result.instructions == "Hello world."

    def test_gpt_component_among_others_is_found(self) -> None:
        pva = _FakePVA(
            changeset=[
                _knowledge_component(),
                _gpt_component(segments=["Live instructions."]),
            ]
        )
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "ok"
        assert result.instructions == "Live instructions."


class TestOkMultiple:
    def test_multiple_segments_joined_in_order(self) -> None:
        pva = _FakePVA(
            changeset=[
                _gpt_component(segments=["First. ", "Second. ", "Third."])
            ]
        )
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "ok"
        assert result.instructions == "First. Second. Third."


class TestNotFound:
    def test_no_gpt_component_returns_not_found(self) -> None:
        pva = _FakePVA(changeset=[_knowledge_component()])
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "not_found"
        assert not result.instructions
        # Message should name what was looked for.
        assert "GptComponent" in (result.error or "")

    def test_empty_changeset_returns_not_found(self) -> None:
        pva = _FakePVA(changeset=[])
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "not_found"
        assert not result.instructions

    def test_missing_segments_returns_not_found(self) -> None:
        comp = _gpt_component()
        comp["component"]["metadata"]["instructions"].pop("segments")
        pva = _FakePVA(changeset=[comp])
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "not_found"
        assert not result.instructions

    def test_missing_metadata_returns_not_found(self) -> None:
        comp = _gpt_component()
        comp["component"].pop("metadata")
        pva = _FakePVA(changeset=[comp])
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "not_found"
        assert not result.instructions

    def test_all_empty_segments_returns_not_found(self) -> None:
        pva = _FakePVA(changeset=[_gpt_component(segments=["", "", ""])])
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "not_found"
        assert not result.instructions

    def test_whitespace_only_segments_returns_not_found(self) -> None:
        pva = _FakePVA(changeset=[_gpt_component(segments=["   ", "\t", "\n"])])
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "not_found"
        assert not result.instructions


class TestError:
    def test_client_none_returns_error(self) -> None:
        result = resolve_agent_instructions(None, FAKE_BOT_ID)
        assert result.status == "error"
        assert result.error
        assert result.instructions is None

    def test_not_configured_returns_error(self) -> None:
        pva = _FakePVA(is_configured=False)
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "error"
        assert result.instructions is None
        assert "configur" in result.error.lower() or "authenticat" in result.error.lower()

    def test_empty_bot_id_returns_error(self) -> None:
        pva = _FakePVA(changeset=[_gpt_component()])
        result = resolve_agent_instructions(pva, "")
        assert result.status == "error"
        assert result.instructions is None
        assert "botId" in result.error or "botid" in result.error.lower()

    def test_fetch_raises_is_caught_and_surfaced(self) -> None:
        pva = _FakePVA(error=RuntimeError("botcomponents lookup failed: 503"))
        result = resolve_agent_instructions(pva, FAKE_BOT_ID)
        assert result.status == "error"
        assert result.instructions is None
        assert result.error == "botcomponents lookup failed: 503"
