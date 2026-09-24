"""The ``inspect`` diff report: classify discovered components against the baseline."""

from __future__ import annotations

from conftest import ca_component, reference_set
from essmig.customizations import (
    Change,
    Migratability,
    classify,
    migratability,
    render_markdown,
)
from essmig.discovery import DiscoveryResult
from essmig.merge import ComponentResult, Conflict, Outcome

BASE = "kind: Variable\nname: Foo\nscope: Conversation"
EDIT = "kind: Variable\nname: Foo\nscope: User"


def _result(*components) -> DiscoveryResult:
    return DiscoveryResult(
        vertical="hr",
        solution_unique_name="msdyn_CopilotForEmployeeSelfServiceHR",
        solution_id="",
        components={c.component_id: c for c in components},
        skipped=[],
    )


def test_edited_component_yields_a_unified_diff() -> None:
    reference = reference_set([], baseline={"component.Foo": BASE})
    component = ca_component("component.Foo", EDIT, component_type=12)

    entry = classify(component, reference.baseline["component.Foo"])

    assert entry.change is Change.EDITED
    assert "-scope: Conversation" in entry.diff
    assert "+scope: User" in entry.diff


def test_component_identical_to_baseline_is_unchanged() -> None:
    reference = reference_set([], baseline={"component.Foo": BASE})
    component = ca_component("component.Foo", BASE, component_type=12)

    entry = classify(component, reference.baseline["component.Foo"])

    assert entry.change is Change.UNCHANGED
    assert entry.diff == ""


def test_pure_line_ending_difference_is_unchanged() -> None:
    reference = reference_set([], baseline={"component.Foo": BASE})
    component = ca_component("component.Foo", BASE.replace("\n", "\r\n"), component_type=12)

    entry = classify(component, reference.baseline["component.Foo"])

    assert entry.change is Change.UNCHANGED


def test_component_without_baseline_counterpart_is_new() -> None:
    reference = reference_set([], baseline={})
    component = ca_component("topic.Homegrown", EDIT)

    entry = classify(component, reference.baseline.get("topic.Homegrown"))

    assert entry.change is Change.NEW
    assert "scope: User" in entry.diff


def test_markdown_reports_edited_and_new_but_omits_unchanged() -> None:
    reference = reference_set(
        [], baseline={"component.Edited": BASE, "component.Same": BASE}
    )
    result = _result(
        ca_component("component.Same", BASE, component_type=12),
        ca_component("topic.New", EDIT),
        ca_component("component.Edited", EDIT, component_type=12),
    )

    markdown = render_markdown(result, reference.baseline)

    edited = markdown.index("Edited (differs")
    new = markdown.index("New (no ESS")
    assert edited < new
    assert "Unchanged from" not in markdown
    assert "component.Same" not in markdown
    assert "```diff" in markdown


def _outcome(suffix: str, outcome: Outcome, **kwargs) -> ComponentResult:
    return ComponentResult(
        suffix=suffix,
        schemaname=f"esshr_{suffix}",
        display_name=suffix,
        component_type_label="Topic (V2)",
        outcome=outcome,
        **kwargs,
    )


def test_migratability_buckets_each_outcome() -> None:
    assert migratability(_outcome("a", Outcome.MERGED))[0] is Migratability.MIGRATABLE
    assert migratability(_outcome("a", Outcome.CARRIED_NEW))[0] is Migratability.MIGRATABLE
    assert migratability(_outcome("a", Outcome.MANUAL))[0] is Migratability.ACTION
    assert migratability(_outcome("a", Outcome.BLOCKED))[0] is Migratability.UNSUPPORTED
    assert migratability(_outcome("a", Outcome.FAILED))[0] is Migratability.UNSUPPORTED


def test_conflicted_reports_the_number_of_spots() -> None:
    conflict = Conflict(path="x", base=1, ours=2, theirs=3, reason="both changed")
    tier, note = migratability(_outcome("a", Outcome.CONFLICTED, conflicts=[conflict]))

    assert tier is Migratability.ACTION
    assert "1 conflicting spot" in note


def test_deprecated_component_is_action_and_names_the_construct() -> None:
    tier, note = migratability(
        _outcome(
            "a",
            Outcome.CARRIED_NEW,
            deprecated=True,
            unsupported=["uses the unsupported 'OnActivity' trigger"],
        )
    )

    assert tier is Migratability.ACTION
    assert "OnActivity" in note
    assert "disabled" in note


def test_markdown_annotates_migratability_when_outcomes_are_supplied() -> None:
    reference = reference_set([], baseline={"component.Edited": BASE})
    result = _result(
        ca_component("topic.New", EDIT),
        ca_component("component.Edited", EDIT, component_type=12),
    )
    outcomes = {
        "topic.New": _outcome("topic.New", Outcome.CARRIED_NEW),
        "component.Edited": _outcome("component.Edited", Outcome.BLOCKED),
    }

    markdown = render_markdown(result, reference.baseline, outcomes)

    assert "Will it migrate?" in markdown
    assert "✅ Migratable now" in markdown
    assert "⛔ Not supported yet" in markdown
    assert "Migration:" in markdown


def test_markdown_omits_migratability_when_no_outcomes_are_supplied() -> None:
    reference = reference_set([], baseline={})
    result = _result(ca_component("topic.New", EDIT))

    markdown = render_markdown(result, reference.baseline)

    assert "Will it migrate?" not in markdown
    assert "Migration:" not in markdown


# --- agent name & description ------------------------------------------------


def test_render_markdown_shows_a_renamed_agent() -> None:
    from essmig.discovery import AgentMetadata
    from essmig.merge import _AGENT_SUFFIX

    result = DiscoveryResult(
        vertical="hr",
        solution_unique_name="msdyn_CopilotForEmployeeSelfServiceHR",
        solution_id="",
        components={},
        skipped=[],
        agent=AgentMetadata(
            name="Contoso People Helper",
            description="Shipped.",
            baseline_name="ESS HR (Preview)",
            baseline_description="Shipped.",
        ),
    )
    outcome = ComponentResult(
        suffix=_AGENT_SUFFIX,
        schemaname="gptagent_copilotforemployeeselfservicehr",
        display_name="Contoso People Helper",
        component_type_label="Agent",
        outcome=Outcome.MERGED,
        detail="Carried your agent display name onto the template.",
    )
    body = render_markdown(result, {}, {_AGENT_SUFFIX: outcome})

    assert "## Agent name & description" in body
    assert "Contoso People Helper" in body
    assert "ESS HR (Preview)" in body
    assert "✅ Migratable now" in body
