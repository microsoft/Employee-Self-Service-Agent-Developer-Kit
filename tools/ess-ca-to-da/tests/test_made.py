"""The ``customizationsMade.md`` diff: shipped Declarative Agent vs produced package.

:mod:`essmig.made` captures a :func:`~essmig.made.snapshot` of the reference's
Declarative Agent before the merge (shipped) and another after it (produced), then
diffs the two component-by-component. These tests exercise that directly and once
end-to-end through :func:`essmig.merge.merge`.
"""

from __future__ import annotations

from conftest import DA_PREFIX, ca_component, dialog_component, reference_set
from essmig import made
from essmig.merge import merge


def _config(bot_name: str | None = None) -> dict[str, object]:
    values: dict[str, object] = {}
    if bot_name is not None:
        values["botName"] = bot_name
        values["gptDisplayName"] = bot_name
    return {"formatVersion": "1.0", "realm": "dev", "values": values}


def test_snapshot_captures_components_and_metadata() -> None:
    reference = reference_set(
        components=[dialog_component("topic.Welcome", {"beginDialog": {"kind": "OnRedirect"}})],
        config=_config("Employee Self-Service HR"),
    )
    reference.agent["entity"]["description"] = "The shipped description."

    snap = made.snapshot(reference)

    assert set(snap.components) == {"topic.Welcome"}
    assert snap.components["topic.Welcome"].kind == "DialogComponent"
    assert snap.display_name == "Employee Self-Service HR"
    assert snap.description == "The shipped description."


def test_changed_component_produces_diff() -> None:
    component = dialog_component("topic.Welcome", {"beginDialog": {"kind": "OnRedirect"}})
    reference = reference_set(components=[component])

    before = made.snapshot(reference)
    # Simulate what the merge does: edit the component in place.
    component["dialog"]["beginDialog"]["kind"] = "OnRecognizedIntent"
    after = made.snapshot(reference)

    entries = made.changes(before, after)
    assert len(entries) == 1
    assert entries[0].change is made.Change.CHANGED
    assert entries[0].suffix == "topic.Welcome"
    assert "-    kind: OnRedirect" in entries[0].diff
    assert "+    kind: OnRecognizedIntent" in entries[0].diff


def test_added_component_is_shown_in_full() -> None:
    reference = reference_set(components=[dialog_component("topic.Welcome", {"x": 1})])
    before = made.snapshot(reference)
    reference.agent["components"].append(
        dialog_component("topic.BrandNew", {"beginDialog": {"kind": "OnRedirect"}})
    )
    after = made.snapshot(reference)

    entries = made.changes(before, after)
    assert [e.suffix for e in entries] == ["topic.BrandNew"]
    assert entries[0].change is made.Change.ADDED
    assert "kind: OnRedirect" in entries[0].diff


def test_removed_component_is_reported() -> None:
    reference = reference_set(
        components=[
            dialog_component("topic.Welcome", {"x": 1}),
            dialog_component("topic.Gone", {"y": 2}),
        ]
    )
    before = made.snapshot(reference)
    reference.agent["components"] = [reference.agent["components"][0]]
    after = made.snapshot(reference)

    entries = made.changes(before, after)
    assert [e.suffix for e in entries] == ["topic.Gone"]
    assert entries[0].change is made.Change.REMOVED


def test_identical_snapshots_produce_no_entries() -> None:
    reference = reference_set(components=[dialog_component("topic.Welcome", {"x": 1})])
    snap = made.snapshot(reference)
    assert made.changes(snap, snap) == []


def test_render_flags_agent_name_change() -> None:
    before = made.Snapshot(display_name="Shipped Name")
    after = made.Snapshot(display_name="Customer Name")

    body = made.render_markdown(
        "hr",
        before,
        after,
        source_solution="CustomerSolution",
        da_schemaname=DA_PREFIX,
    )
    assert "## Agent settings" in body
    assert "`Shipped Name`" in body
    assert "`Customer Name`" in body


def test_render_reports_no_changes() -> None:
    empty = made.Snapshot()
    body = made.render_markdown(
        "hr", empty, empty, source_solution="CustomerSolution", da_schemaname=DA_PREFIX
    )
    assert "made no changes" in body


def test_render_summary_counts() -> None:
    before = made.Snapshot(
        components={"topic.A": made.ComponentText("topic.A", f"{DA_PREFIX}.topic.A", "D", "a: 1\n")}
    )
    after = made.Snapshot(
        components={
            "topic.A": made.ComponentText("topic.A", f"{DA_PREFIX}.topic.A", "D", "a: 2\n"),
            "topic.B": made.ComponentText("topic.B", f"{DA_PREFIX}.topic.B", "D", "b: 1\n"),
        }
    )
    body = made.render_markdown(
        "hr", before, after, source_solution="S", da_schemaname=DA_PREFIX
    )
    assert "| Changed (differs from the shipped template) | 1 |" in body
    assert "| Added (new in the produced package) | 1 |" in body
    assert "| Removed (dropped from the produced package) | 0 |" in body


def test_end_to_end_net_new_topic_shows_as_added() -> None:
    """A customer's net-new topic must appear as Added after a real merge."""
    reference = reference_set(
        components=[dialog_component("topic.Welcome", {"beginDialog": {"kind": "OnRedirect"}})],
    )
    net_new = ca_component(
        "topic.MyNewTopic",
        "kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRecognizedIntent\n",
        solutions=("Active",),
    )

    before = made.snapshot(reference)
    merge(reference, {net_new.schemaname: net_new}, "hr")
    after = made.snapshot(reference)

    entries = made.changes(before, after)
    added = [e.suffix for e in entries if e.change is made.Change.ADDED]
    assert any(suffix.endswith("MyNewTopic") for suffix in added)
