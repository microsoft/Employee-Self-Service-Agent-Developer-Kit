"""Unit tests for the WritebackPlan coalescing / no-op-guarded accumulator."""

from __future__ import annotations

from modules.transformation.models import WritebackPlan


def test_coalesces_multiple_steps_into_one_write_per_record() -> None:
    plan = WritebackPlan()
    # Two steps touch the same bot record, each editing a different field.
    plan.target("bots", "bot-1", original={"template": "default-2", "configuration": "{}"}).set(
        "template", "gptagent-1.0.0"
    )
    plan.target("bots", "bot-1").set("configuration", '{"model":"da"}')

    writes = plan.pending_writes()

    assert writes == [
        {
            "entity_set": "bots",
            "record_id": "bot-1",
            "changes": {"template": "gptagent-1.0.0", "configuration": '{"model":"da"}'},
        }
    ]


def test_chains_edits_via_working_value() -> None:
    plan = WritebackPlan()
    # Rule A edits the topic data; rule B reads the *working* value and edits again.
    target = plan.target("botcomponents", "topic-1", original={"data": "v0"})
    target.set("data", target.get("data") + "+A")
    target = plan.target("botcomponents", "topic-1")
    target.set("data", target.get("data") + "+B")

    writes = plan.pending_writes()

    assert writes == [
        {"entity_set": "botcomponents", "record_id": "topic-1", "changes": {"data": "v0+A+B"}}
    ]


def test_no_op_edit_produces_no_write() -> None:
    plan = WritebackPlan()
    # Stage the same value as the original -> no meaningful change -> no write.
    plan.target("bots", "bot-1", original={"template": "gptagent-1.0.0"}).set(
        "template", "gptagent-1.0.0"
    )

    assert plan.pending_writes() == []


def test_write_emitted_only_for_changed_fields() -> None:
    plan = WritebackPlan()
    target = plan.target("bots", "bot-1", original={"template": "default-2", "configuration": "{}"})
    target.set("template", "gptagent-1.0.0")  # changed
    target.set("configuration", "{}")  # unchanged -> excluded

    writes = plan.pending_writes()

    assert writes == [
        {"entity_set": "bots", "record_id": "bot-1", "changes": {"template": "gptagent-1.0.0"}}
    ]


def test_first_touch_original_baseline_wins() -> None:
    plan = WritebackPlan()
    plan.target("bots", "bot-1", original={"template": "default-2"})
    # A later target() call must not overwrite the true baseline.
    target = plan.target("bots", "bot-1", original={"template": "gptagent-1.0.0"})
    target.set("template", "gptagent-1.0.0")

    # Still a change vs the original "default-2" baseline.
    assert plan.pending_writes() == [
        {"entity_set": "bots", "record_id": "bot-1", "changes": {"template": "gptagent-1.0.0"}}
    ]


def test_multiple_records_preserve_first_touch_order() -> None:
    plan = WritebackPlan()
    plan.target("botcomponents", "topic-2", original={"data": "a"}).set("data", "b")
    plan.target("bots", "bot-1", original={"template": "default-2"}).set(
        "template", "gptagent-1.0.0"
    )

    writes = plan.pending_writes()

    assert [(w["entity_set"], w["record_id"]) for w in writes] == [
        ("botcomponents", "topic-2"),
        ("bots", "bot-1"),
    ]


def test_target_for_returns_actual_and_final_copy_for_reporting() -> None:
    plan = WritebackPlan()
    plan.target("botcomponents", "topic-1", original={"data": "before"}).set("data", "after")

    target = plan.target_for("botcomponents", "topic-1")

    assert target is not None
    # Actual copy vs final modified copy — comparable without a second stored copy.
    assert target.original["data"] == "before"
    assert target.get("data") == "after"
    # An untouched record has no target (no creation on lookup).
    assert plan.target_for("botcomponents", "never-touched") is None


def test_targets_lists_all_touched_records_in_order() -> None:
    plan = WritebackPlan()
    plan.target("botcomponents", "topic-2", original={"data": "a"})
    plan.target("bots", "bot-1", original={"template": "t"})

    assert [(t.entity_set, t.record_id) for t in plan.targets()] == [
        ("botcomponents", "topic-2"),
        ("bots", "bot-1"),
    ]
