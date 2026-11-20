"""Guard tests for the ServiceNow Connect controller output contract."""

from __future__ import annotations

from typing import Any

import pytest

import connect_servicenow_da as snow

PROFILES = ("hrsd", "itsm")


@pytest.fixture(autouse=True)
def _reset_profile(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(snow, "ACTIVE_AGENT_NAME", None)
    yield
    snow.configure_product_profile("hrsd")


def _output(result: dict[str, Any], command: str | None = None) -> dict[str, Any]:
    return snow._with_agent_rules(result, command, None)


def _card(header: str, options: list[str] | None = None, body: str = "") -> dict:
    card: dict[str, Any] = {
        "header": header,
        "question": body or header,
        "allowFreeformInput": options is None,
    }
    if options is not None:
        card["options"] = [{"label": label} for label in options]
    return card


@pytest.mark.parametrize("profile", PROFILES)
def test_lead_in_without_wait_cue_auto_continues(profile: str) -> None:
    snow.configure_product_profile(profile)
    out = _output(
        {
            "status": "ready",
            "renderBlock": {
                "kind": "progress",
                "text": "We're checking whether your account can configure "
                "this agent before setup begins.",
            },
            "checkpoints": {"commands": [{"command": "python scripts/x.py check"}]},
        },
        "resume-handoff",
    )
    assert list(out)[:3] == ["chatMessage", "endTurn", "nextCommand"]
    assert out["endTurn"] is False
    assert "python scripts/x.py check" in out["nextCommand"]
    assert not snow.has_wait_cue(out["chatMessage"])


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize(
    "text",
    [
        "Return here and tell us which connection you used.",
        "Paste their reply here when you have it.",
        "Let us know what happened.",
        "Reply here once you are ready.",
        "Is the portal correct?",
    ],
)
def test_wait_cue_message_ends_turn_without_next_command(
    profile: str, text: str
) -> None:
    snow.configure_product_profile(profile)
    out = _output(
        {
            "status": "ready",
            "renderBlock": {"kind": "progress", "text": text},
            "action": {"actionDoc": "src/skills/connect/x/actions/next.md"},
        },
        "resume-handoff",
    )
    assert out["endTurn"] is True
    assert "nextCommand" not in out
    assert "afterReply" in out


def test_pending_card_title_is_the_question_and_has_no_body() -> None:
    out = _output(
        {
            "status": "input-required",
            "question": _card(
                "Which ServiceNow instance should ESS IT use?",
                body="Use only the instance root, for example the dev instance.",
            ),
        },
        "resume-handoff",
    )
    card = out["pendingCard"]["askUserArguments"]
    assert "Use only the instance root" in out["chatMessage"]
    assert card["message"] == "Which ServiceNow instance should ESS IT use?"
    field = next(iter(card["requestedSchema"]["properties"].values()))
    assert "description" not in field
    assert out["endTurn"] is False
    assert "pendingCard" in out["nextCommand"]


@pytest.mark.parametrize(
    "labels",
    [["Yes", "No"], ["Enable all", "Keep current", "Not now"]],
)
def test_option_labels_stay_short(labels: list[str]) -> None:
    arguments = snow.adapt_question_to_ask_user(
        _card("Should we continue?", options=labels)
    )["askUserArguments"]
    field = next(iter(arguments["requestedSchema"]["properties"].values()))
    shown = [item["title"] for item in field["oneOf"]]
    assert shown == labels
    assert all(len(label) <= 25 for label in shown)


@pytest.mark.parametrize("profile", PROFILES)
def test_agent_name_is_single_resolver(profile: str) -> None:
    snow.configure_product_profile(profile)
    snow._remember_agent_name({"agent": {"display_name": "ESS IT"}})
    assert snow._spec_agent_name() == "ESS IT"


def test_agent_rules_pin_wait_and_card_behaviour() -> None:
    rules = " ".join(snow.AGENT_RULES)
    assert "endTurn is true" in rules
    assert "nextCommand" in rules
    assert "card title is the question" in rules
