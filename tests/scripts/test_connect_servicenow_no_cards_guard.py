# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Guards: ServiceNow Connect must never surface a card to the maker."""

from __future__ import annotations

import json
import re

from pathlib import Path

import pytest

import connect_servicenow_da as snow


REPO = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills"
CONNECT_DOCS = REPO / "src" / "skills" / "connect"
CARD_TOOL = re.compile(r"ask_user|vscode_askQuestions|AskUserQuestion")
NEGATION = re.compile(r"\b(never|not|no|don't|do not|without)\b", re.I)
GUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)
INTERNAL_LABELS = (
    "Values from the maker",
    "Send back to the maker",
)


def _servicenow_docs() -> list[Path]:
    roots = [
        CONNECT_DOCS / "servicenow-da",
        CONNECT_DOCS / "servicenow-da-hrsd",
        CONNECT_DOCS / "servicenow-da-itsm",
        CONNECT_DOCS / "shared" / "runtime-instructions",
    ]
    docs = [path for root in roots for path in root.rglob("*.md")]
    docs += [
        CONNECT_DOCS / "servicenow" / "entry.md",
        CONNECT_DOCS / "servicenow" / "realms.md",
    ]
    return docs


def test_entry_documents_carry_the_hard_no_card_rule() -> None:
    prompt = (REPO / ".github" / "prompts" / "connect.prompt.md").read_text(
        encoding="utf-8"
    )
    entry = (CONNECT_DOCS / "servicenow" / "entry.md").read_text(
        encoding="utf-8"
    )
    realms = (CONNECT_DOCS / "servicenow" / "realms.md").read_text(
        encoding="utf-8"
    )
    for name, text in (
        ("connect.prompt.md", prompt),
        ("entry.md", entry),
        ("realms.md", realms),
    ):
        top = text[:1800]
        assert "HARD RULE" in top, name
        assert "ask_user" in top and "never" in top.lower(), name
        assert "chatMessage" in top, name


def test_servicenow_docs_never_instruct_a_card_tool() -> None:
    offenders: list[str] = []
    for path in _servicenow_docs():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not CARD_TOOL.search(line):
                continue
            window = " ".join(lines[max(0, index - 2) : index + 3])
            if not NEGATION.search(window):
                offenders.append(f"{path.name}:{index + 1}")
    assert offenders == []


def test_legacy_servicenow_step_is_marked_retired() -> None:
    step1 = (CONNECT_DOCS / "servicenow" / "step1.md").read_text(
        encoding="utf-8"
    )
    assert "Retired legacy flow" in step1[:600]
    assert "entry.md" in step1[:600]


def test_administrator_packets_have_no_internal_labels() -> None:
    for path in _servicenow_docs():
        text = path.read_text(encoding="utf-8")
        for label in INTERNAL_LABELS:
            assert label not in text, f"{path.name}: {label}"


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _assert_no_card(output: dict) -> None:
    for node in _walk(output):
        if not isinstance(node, dict):
            continue
        assert "askUserArguments" not in node
        assert not node.get("questions")
        assert not (
            isinstance(node.get("question"), str)
            and ("options" in node or "allowFreeformInput" in node)
        )


def _pending_card() -> dict:
    return snow._native_question(
        header="ServiceNow administrator",
        question="Is your ServiceNow administrator available?",
        option_labels=["Yes, available now", "No, not yet"],
    )


@pytest.mark.parametrize(
    "key",
    ["businessGroupAvailability", "instanceQuestion", "userField", "ready"],
)
def test_pending_question_reaches_the_maker_as_the_final_chat_message(
    key: str,
) -> None:
    payload = {
        "decision": "ask",
        "renderBlock": {"text": ""},
        "transport": {key: {"question": _pending_card()}},
        "questions": [_pending_card()],
    }

    wrapped = snow._with_agent_rules(
        snow.plain_text_output(payload), "resume-handoff"
    )

    _assert_no_card(wrapped)
    assert wrapped["endTurn"] is True
    assert "Is your ServiceNow administrator available?" in (
        wrapped["chatMessage"]
    )
    assert wrapped["chatMessage"].rstrip().endswith("Reply **Yes** or **No**.")
    assert list(wrapped)[:2] == ["chatMessage", "endTurn"]
    rules = " ".join(wrapped["agentRules"])
    assert "never uses ask_user" in rules
    assert "END YOUR TURN" in rules


def test_question_helpers_are_not_wrapped_with_chat_message() -> None:
    result = {"schemaVersion": "servicenow.plain-question.v1"}
    assert snow._with_agent_rules(result, "adapt-question") is result
    assert snow._with_agent_rules(result, "match-reply") is result


@pytest.mark.parametrize("profile", ["hrsd", "itsm"])
def test_instance_question_is_maker_friendly(
    profile: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snow, "ACTIVE_AGENT_NAME", "ESS IT")
    context = {
        "agent": {"id": "x", "workspace_slug": "agent"},
        "environment": {"id": "env"},
    }
    with snow.product_profile_context(profile):
        question, choices, _ = snow._preflight_instance_question(
            context=context,
            candidates=["dev123"],
            discovery_error=None,
        )
        text = snow.adapt_question_to_plain_text(question)["plainText"]

    assert "ESS IT" in text
    assert "Employee Self-Service" not in text
    assert "http" not in text.lower()
    assert "service-now.com" not in text
    assert not GUID.search(text)
    assert "Reply **Yes** or **No**" in text
    assert choices["Yes, use dev123"] == "https://dev123.service-now.com"


@pytest.mark.parametrize("profile", ["hrsd", "itsm"])
def test_every_maker_text_uses_the_recorded_agent_name(
    profile: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snow, "ACTIVE_AGENT_NAME", "ESS Recorded")
    context = {
        "agent": {
            "id": "00000000-0000-4000-8000-000000002222",
            "display_name": "ESS Recorded",
            "workspace_slug": "agent",
        },
        "environment": {
            "id": "00000000-0000-4000-8000-000000001111",
            "display_name": "Contoso Dev",
            "ring": "test",
        },
    }
    with snow.product_profile_context(profile):
        texts = [
            snow._dev_opening_text(context, None),
            snow._current_task_guidance(
                context, {}, phase_id="credential", role="maker"
            ),
        ]
        question, _, manual = snow._preflight_instance_question(
            context=context, candidates=[], discovery_error=None
        )
        texts.append(question["question"])
        texts.append(manual["question"])

    for text in texts:
        assert "ESS Recorded" in text or "Which ServiceNow" in text
        assert "Employee Self-Service" not in text
    assert any("ESS Recorded" in text for text in texts)


def test_card_output_would_have_failed_this_guard() -> None:
    leaked = {"askUserArguments": {"questions": [_pending_card()]}}
    with pytest.raises(AssertionError):
        _assert_no_card(leaked)
    with pytest.raises(AssertionError):
        _assert_no_card({"questions": [_pending_card()]})
    assert json.dumps(snow.plain_text_output(leaked)).count(
        "askUserArguments"
    ) == 0
