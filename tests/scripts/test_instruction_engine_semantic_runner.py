import json

import pytest

from instruction_engine.semantic_rules.runner import (
    SemanticRunnerError,
    run_semantic_pass,
)


def _stub_client(response_json):
    def _client(prompt):
        assert "INSTR-" in prompt or "Rule pack" in prompt
        return json.dumps(response_json)
    return _client


def test_parses_findings_from_stubbed_llm_response():
    stub_findings = [
        {
            "id": "INSTR-020",
            "severity": "warn",
            "category": "over-commitment",
            "section": "Formatting rules",
            "anchor": "Always offer to help with anything else.",
            "message": "Unsolicited offer with no source authorization.",
            "suggestion": "Remove the standing offer to help.",
        }
    ]
    findings = run_semantic_pass(
        "some instructions", rule_pack_text="rule pack text",
        llm_client=_stub_client(stub_findings),
    )
    assert len(findings) == 1
    f = findings[0]
    assert f.id == "INSTR-020"
    assert f.source == "semantic"
    assert f.severity == "warn"
    assert f.suggestion == "Remove the standing offer to help."


def test_empty_findings_list_from_stub():
    findings = run_semantic_pass(
        "clean instructions", rule_pack_text="rule pack text",
        llm_client=_stub_client([]),
    )
    assert findings == []


def test_strips_markdown_code_fences():
    def _client(prompt):
        return "```json\n[]\n```"
    findings = run_semantic_pass(
        "instructions", rule_pack_text="rule pack text", llm_client=_client,
    )
    assert findings == []


def test_raises_on_non_json_response():
    def _client(prompt):
        return "not json at all"
    with pytest.raises(SemanticRunnerError):
        run_semantic_pass("instructions", rule_pack_text="rule pack text", llm_client=_client)


def test_raises_on_non_array_response():
    def _client(prompt):
        return json.dumps({"id": "INSTR-001"})
    with pytest.raises(SemanticRunnerError):
        run_semantic_pass("instructions", rule_pack_text="rule pack text", llm_client=_client)


def test_scope_hint_included_in_prompt():
    captured = {}

    def _client(prompt):
        captured["prompt"] = prompt
        return "[]"

    run_semantic_pass(
        "instructions", rule_pack_text="rule pack text",
        scope_hint="follow-up suggestions after read-only topics",
        llm_client=_client,
    )
    assert "follow-up suggestions after read-only topics" in captured["prompt"]


def test_default_rule_pack_loaded_when_not_provided():
    captured = {}

    def _client(prompt):
        captured["prompt"] = prompt
        return "[]"

    run_semantic_pass("instructions", llm_client=_client)
    assert "INSTR-001" in captured["prompt"]
