from __future__ import annotations

from conftest import ca_component
from essmig.merge import Conflict, Resolution
from essmig.resolve import (
    _MERGE_MARKER as _MARKER,
)
from essmig.resolve import (
    _after_marker,
    _delta,
    _editor_template,
    console_resolver_factory,
)


def _component(name: str = "ServiceNow ITSM"):
    return ca_component("topic.ServiceNowITSM", "kind: AdaptiveDialog\n", name=name)


def _conflict(path: str = "topic.ServiceNowITSM.a") -> Conflict:
    return Conflict(path=path, base="b", ours="mine", theirs="theirs", reason="both sides changed")


class _Script:
    """A canned sequence of console answers, recording every prompt shown."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = list(answers)
        self.prompts: list[str] = []
        self.output: list[str] = []

    def prompt(self, text: str) -> str:
        self.prompts.append(text)
        return self._answers.pop(0)

    def echo(self, text: str) -> None:
        self.output.append(text)


def test_pressing_enter_keeps_ess_version() -> None:
    script = _Script(["", "n"])
    resolve = console_resolver_factory(prompt=script.prompt, echo=script.echo)(_component())
    assert resolve(_conflict()).resolution is Resolution.THEIRS


def test_answering_m_keeps_our_version() -> None:
    script = _Script(["m", "n"])
    resolve = console_resolver_factory(prompt=script.prompt, echo=script.echo)(_component())
    assert resolve(_conflict()).resolution is Resolution.OURS


def test_apply_to_rest_of_topic_answers_later_spots_without_prompting() -> None:
    script = _Script(["m", "y"])  # first: keep mine, then apply to the rest
    resolve = console_resolver_factory(prompt=script.prompt, echo=script.echo)(_component())
    assert resolve(_conflict("topic.ServiceNowITSM.a")).resolution is Resolution.OURS
    assert resolve(_conflict("topic.ServiceNowITSM.b")).resolution is Resolution.OURS
    assert resolve(_conflict("topic.ServiceNowITSM.c")).resolution is Resolution.OURS
    # Only the first spot was prompted; the sticky choice covered the other two.
    assert len(script.prompts) == 2


def test_instruction_conflicts_are_never_prompted() -> None:
    script = _Script([])  # would IndexError if it tried to prompt
    resolve = console_resolver_factory(prompt=script.prompt, echo=script.echo)(_component())
    assert resolve(_conflict("gpt.default.instructions")) is None
    assert script.prompts == []


def test_an_invalid_answer_is_reprompted() -> None:
    script = _Script(["huh?", "e", "n"])
    resolve = console_resolver_factory(prompt=script.prompt, echo=script.echo)(_component())
    assert resolve(_conflict()).resolution is Resolution.THEIRS
    assert any("E (keep ESS's)" in line for line in script.output)


# --- manual (hand-merge) resolution -----------------------------------------


def test_opening_the_editor_returns_the_hand_merged_value() -> None:
    script = _Script(["o"])  # choose the editor
    seen: dict[str, str] = {}

    def edit(initial: str) -> str:
        seen["initial"] = initial
        # Keep the header/marker, replace the editable body with the user's value.
        return initial.split("\n")[0] + "\n" + _MARKER + "\nkind: MyBlend\nvalue: 42\n"

    resolve = console_resolver_factory(
        prompt=script.prompt, echo=script.echo, edit=edit
    )(_component())
    decision = resolve(_conflict())
    assert decision.resolution is Resolution.MANUAL
    assert decision.value == {"kind": "MyBlend", "value": 42}
    # The editor was seeded with both sides for reference.
    assert "YOUR VERSION" in seen["initial"] and "ESS'S VERSION" in seen["initial"]
    # After a hand-merge, no 'apply to the rest' prompt is offered.
    assert not any("rest of this topic" in p for p in script.prompts)


def test_an_empty_hand_merge_reprompts_then_falls_back_to_ess() -> None:
    script = _Script(["o", "e", "n"])  # editor first, then keep ESS's

    def edit(initial: str) -> str:
        return initial.split(_MARKER)[0] + _MARKER + "\n   \n"  # nothing below the marker

    resolve = console_resolver_factory(
        prompt=script.prompt, echo=script.echo, edit=edit
    )(_component())
    assert resolve(_conflict()).resolution is Resolution.THEIRS
    assert any("Nothing below the edit line" in line for line in script.output)


def test_unparseable_hand_merge_reprompts() -> None:
    script = _Script(["o", "m", "n"])  # editor first, then keep mine

    def edit(initial: str) -> str:
        return initial.split(_MARKER)[0] + _MARKER + "\nkey: : : not yaml\n"

    resolve = console_resolver_factory(
        prompt=script.prompt, echo=script.echo, edit=edit
    )(_component())
    assert resolve(_conflict()).resolution is Resolution.OURS
    assert any("Could not parse" in line for line in script.output)


def test_editor_template_carries_both_sides_and_seeds_with_ess() -> None:
    conflict = Conflict(
        path="topic.T.inputs", base=None, ours=["a"], theirs=["b"], reason="both changed"
    )
    template = _editor_template(conflict)
    assert _MARKER in template
    body = _after_marker(template)
    assert "b" in body and "a" not in body  # seeded from ESS's version, not yours


# --- rendering conflicts as *what changed* ----------------------------------


def test_delta_shows_only_the_fields_the_customer_changed() -> None:
    base = [
        {"kind": "ManualTaskInput", "propertyName": "ConfigName", "value": "ACME"},
        {"kind": "ManualTaskInput", "propertyName": "SysId", "value": ""},
    ]
    ours = [
        {"kind": "ManualTaskInput", "propertyName": "ConfigName", "value": "CONTOSO"},
        {"kind": "ManualTaskInput", "propertyName": "SysId", "value": ""},
    ]
    assert _delta(base, ours) == ['~ changed ConfigName: value: "ACME" -> "CONTOSO"']


def test_delta_reports_added_and_removed_list_items_by_their_key() -> None:
    base = [{"propertyName": "A", "value": 1}]
    ours = [{"propertyName": "A", "value": 1}, {"propertyName": "B", "value": 2}]
    assert _delta(base, ours) == ["+ added B"]
    assert _delta(ours, base) == ["- removed B"]


def test_delta_describes_a_scalar_change_inline() -> None:
    assert _delta("old", "new") == ['changed from "old" to "new"']


def test_delta_of_a_removal_says_so() -> None:
    assert _delta({"a": 1}, None) == ["(you removed this entirely)"]


def test_delta_is_none_without_a_baseline_so_the_caller_shows_the_value() -> None:
    assert _delta(None, {"a": 1}) is None
