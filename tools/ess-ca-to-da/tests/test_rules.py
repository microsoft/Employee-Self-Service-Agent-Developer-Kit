from __future__ import annotations

from essmig.rules import (
    DEPRECATED_MARKER,
    UNSUPPORTED_NODES,
    UNSUPPORTED_TRIGGERS,
    Owner,
    deprecate,
    find_unsupported,
    is_deprecated,
    trigger_kind,
)


def dialog(trigger: str = "OnRedirect", actions: list[dict[str, object]] | None = None) -> dict:
    return {
        "beginDialog": {
            "kind": trigger,
            "id": "main",
            "actions": actions or [{"kind": "SendActivity", "id": "a1"}],
        }
    }


def test_the_trigger_is_read_from_begin_dialog() -> None:
    assert trigger_kind(dialog("OnConversationStart")) == "OnConversationStart"


def test_a_supported_topic_reports_nothing() -> None:
    assert find_unsupported(dialog()) == []


def test_an_unsupported_trigger_is_reported_with_guidance() -> None:
    found = find_unsupported(dialog("OnUnknownIntent"))
    assert [c.kind for c in found] == ["OnUnknownIntent"]
    assert found[0].is_trigger is True
    assert "fallback" in found[0].guidance


def test_an_unsupported_node_is_found_however_deeply_it_is_nested() -> None:
    nested = dialog(
        actions=[
            {
                "kind": "ConditionGroup",
                "id": "c1",
                "conditions": [
                    {"id": "i1", "actions": [{"kind": "SearchAndSummarizeContent", "id": "s"}]}
                ],
            }
        ]
    )
    assert [c.kind for c in find_unsupported(nested)] == ["SearchAndSummarizeContent"]


def test_a_node_used_twice_is_reported_once() -> None:
    repeated = dialog(
        actions=[
            {"kind": "RecognizeIntent", "id": "a"},
            {"kind": "RecognizeIntent", "id": "b"},
        ]
    )
    assert len(find_unsupported(repeated)) == 1


def test_the_trigger_is_reported_before_the_nodes() -> None:
    found = find_unsupported(
        dialog("OnActivity", actions=[{"kind": "ConversationHistory", "id": "a"}])
    )
    assert [c.kind for c in found] == ["OnActivity", "ConversationHistory"]


def test_deprecating_disables_the_component_and_marks_its_title() -> None:
    entry = {"state": "Active", "status": "Active", "displayName": "My Topic", "dialog": {}}
    deprecate(entry)
    assert entry["state"] == entry["status"] == "Inactive"
    assert entry["displayName"] == f"{DEPRECATED_MARKER} My Topic"
    assert is_deprecated(entry)


def test_deprecating_twice_does_not_double_the_marker() -> None:
    entry = {"state": "Active", "status": "Active", "displayName": "My Topic"}
    deprecate(entry)
    deprecate(entry)
    assert entry["displayName"] == f"{DEPRECATED_MARKER} My Topic"


def test_every_gap_says_who_must_act() -> None:
    for construct in (*UNSUPPORTED_TRIGGERS, *UNSUPPORTED_NODES):
        assert construct.owner in tuple(Owner), construct.kind
        assert construct.guidance.strip(), construct.kind


def test_maker_owned_gaps_point_at_an_adk_command() -> None:
    # R2: guidance must distinguish what the Maker has to do, and route them to it.
    for construct in (*UNSUPPORTED_TRIGGERS, *UNSUPPORTED_NODES):
        if construct.owner is Owner.MAKER:
            assert "/" in construct.adk, construct.kind


def test_unpreservable_gaps_promise_no_route() -> None:
    for construct in (*UNSUPPORTED_TRIGGERS, *UNSUPPORTED_NODES):
        if construct.owner is Owner.PLATFORM:
            assert not construct.adk, construct.kind


def test_advice_carries_ownership_and_the_adk_route() -> None:
    fallback = next(c for c in UNSUPPORTED_TRIGGERS if c.kind == "OnUnknownIntent")
    assert fallback.advice.startswith("**You need to rebuild this.**")
    assert "ADK: " in fallback.advice
