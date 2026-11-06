"""The migration verdict: eligibility, blockers, worklist and employee impact."""

from __future__ import annotations

import json

from conftest import ca_component, dialog_component, reference_set
from essmig.assessment import Eligibility, assess
from essmig.merge import merge

CLEAN = json.dumps(
    {"kind": "AdaptiveDialog", "beginDialog": {"kind": "OnRecognizedIntent"}, "actions": []}
)
FALLBACK = json.dumps(
    {"kind": "AdaptiveDialog", "beginDialog": {"kind": "OnUnknownIntent"}, "actions": []}
)
HANDOFF = json.dumps(
    {
        "kind": "AdaptiveDialog",
        "beginDialog": {"kind": "OnRecognizedIntent"},
        "actions": [{"kind": "TransferConversationV2", "id": "a1"}],
    }
)


def _merged(components, reference):
    return merge(reference, {c.component_id: c for c in components}, "hr")


def test_a_clean_carry_is_ready() -> None:
    reference = reference_set([])
    verdict = assess(_merged([ca_component("topic.New", CLEAN)], reference))

    assert verdict.eligibility is Eligibility.READY
    assert not verdict.blockers
    assert not verdict.worklist


def test_a_rebuildable_gap_is_work_not_a_blocker() -> None:
    reference = reference_set([])
    verdict = assess(_merged([ca_component("topic.Fallback", FALLBACK)], reference))

    assert verdict.eligibility is Eligibility.NEEDS_WORK
    assert not verdict.blockers
    assert any("rebuild on supported building blocks" in item for item in verdict.worklist)


def test_a_capability_with_no_path_forward_blocks() -> None:
    reference = reference_set([])
    verdict = assess(_merged([ca_component("topic.Escalate", HANDOFF)], reference))

    assert verdict.eligibility is Eligibility.BLOCKED
    assert any("does not support yet" in blocker for blocker in verdict.blockers)
    assert not verdict.worklist


def test_a_conflict_is_worklist() -> None:
    base = json.dumps(
        {"kind": "AdaptiveDialog", "beginDialog": {"kind": "OnRecognizedIntent"}, "greeting": "a"}
    )
    ours = json.dumps(
        {"kind": "AdaptiveDialog", "beginDialog": {"kind": "OnRecognizedIntent"}, "greeting": "b"}
    )
    reference = reference_set(
        [
            dialog_component(
                "topic.Greet", {"beginDialog": {"kind": "OnRecognizedIntent"}, "greeting": "c"}
            )
        ],
        {"topic.Greet": base},
    )
    verdict = assess(_merged([ca_component("topic.Greet", ours)], reference))

    assert verdict.eligibility is Eligibility.NEEDS_WORK
    assert any("re-apply your change by hand" in item for item in verdict.worklist)


def test_a_blocker_outranks_a_worklist_item() -> None:
    reference = reference_set([])
    verdict = assess(
        _merged(
            [ca_component("topic.Fallback", FALLBACK), ca_component("topic.Escalate", HANDOFF)],
            reference,
        )
    )

    assert verdict.eligibility is Eligibility.BLOCKED
    assert verdict.blockers and verdict.worklist


def test_employee_impact_always_names_history_and_analytics() -> None:
    reference = reference_set([])
    verdict = assess(_merged([ca_component("topic.New", CLEAN)], reference))
    text = " ".join(verdict.employee_impact)

    assert "conversation history" in text
    assert "analytics" in text.lower()


def test_employee_impact_leads_with_disabled_topics_when_there_are_any() -> None:
    reference = reference_set([])
    verdict = assess(_merged([ca_component("topic.Fallback", FALLBACK)], reference))

    assert "disabled in the package" in verdict.employee_impact[0]


def test_the_verdict_serializes_for_the_migration_funnel() -> None:
    reference = reference_set([])
    payload = assess(_merged([ca_component("topic.Escalate", HANDOFF)], reference)).to_json()

    assert payload["eligibility"] == "blocked"
    assert payload["verdict"]
    assert isinstance(payload["blockers"], list)
    assert isinstance(payload["employeeImpact"], list)
