# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Chained milestone contracts; synthetic decisions are not live write authority."""

from dataclasses import replace

import pytest

from topic_actions_discovery import (
    DiscoveryTarget, SourceBinding, TopicEvidence, TopicSet, build_provisional_snapshot,
)
from topic_actions_flat_discovery import (
    FlatCatalog, FlatMember, FlatSet, InventoryTopic, NativeInventory, compare_flat_catalog,
)
from topic_actions_planning import TopicChange, TopicSkip, build_provisional_plan, plan_topic_actions
from topic_actions_review import (
    ReviewError, prepare_review, record_synthetic_decision, review_topic_actions,
)


TARGET = DiscoveryTarget(
    "00000000-0000-0000-0000-000000001111",
    "00000000-0000-0000-0000-000000002222",
    "00000000-0000-0000-0000-000000003333",
)
ACCOUNT = "synthetic-chain-maker"
SOURCE = SourceBinding("synthetic-package", "1", "r1", True)


def synthetic_enable_plan(*, keys=("alpha", "beta"), state="Off"):
    snapshot = build_provisional_snapshot(
        TARGET, keys,
        (
            TopicSet("alpha", ("a", "shared"), True, SOURCE),
            TopicSet("beta", ("b", "shared"), True, SOURCE),
        ),
        (
            TopicEvidence("a", False, state), TopicEvidence("b", False, state),
            TopicEvidence("shared", False, "On"),
        ),
        coverage_complete=True,
    )
    topics = {item.component_id: item for item in snapshot.topics}
    return build_provisional_plan(
        snapshot, "enable",
        delta=tuple(
            TopicChange(identity, "Off", "On") for identity in snapshot.selected_member_ids
            if topics[identity].state == "Off"
        ),
        satisfied_member_ids=tuple(
            identity for identity in snapshot.selected_member_ids if topics[identity].state == "On"
        ),
    )


def synthetic_approve(review, fresh_plan):
    return record_synthetic_decision(
        review, "approve", fresh_plan=fresh_plan,
        account_id=ACCOUNT, permissions_verified=True,
    )


def test_multi_set_chain_approval_then_external_state_change_requires_new_noop_review():
    plan = synthetic_enable_plan()
    context = {"retained_progress": True}
    review = prepare_review(plan, ACCOUNT, entry="called", caller_context=context)
    assert review.plan is plan
    assert plan.selected_keys == ("alpha", "beta")
    assert plan.delta == (TopicChange("a", "Off", "On"), TopicChange("b", "Off", "On"))
    assert plan.satisfied_member_ids == ("shared",)
    approved = synthetic_approve(review, synthetic_enable_plan())
    assert approved.status == "approved_synthetic"
    assert approved.live_actions_available is False

    fresh = synthetic_enable_plan(state="On")
    stale = synthetic_approve(review, fresh)
    assert stale.status == "review_required"
    assert "evidence_changed" in stale.blockers
    assert stale.approval_basis is None
    assert stale.review.caller_context is context
    renewed = prepare_review(fresh, ACCOUNT, entry="called", caller_context=context)
    assert renewed.plan.delta == ()
    assert renewed.status == "awaiting_synthetic_decision"
    assert synthetic_approve(renewed, fresh).status == "approved_synthetic_no_changes"
    for decision, expected in (("deny", "denied"), ("cancel", "cancelled")):
        result = record_synthetic_decision(renewed, decision)
        assert result.status == expected
        assert result.approval_basis is None
        assert result.review.caller_context is context
        assert result.live_actions_available is False
    assert context == {"retained_progress": True}


def test_disable_chain_rejects_changed_protection_after_review():
    snapshot = build_provisional_snapshot(
        TARGET, ("alpha",),
        (
            TopicSet("alpha", ("a", "shared", "required"), True, SOURCE),
            TopicSet("beta", ("b", "shared"), True, SOURCE),
            TopicSet("gamma", ("g", "shared"), True, SOURCE),
        ),
        (
            TopicEvidence("a", False, "On"), TopicEvidence("shared", False, "On"),
            TopicEvidence("required", True, "On"), TopicEvidence("b", False, "On"),
            TopicEvidence("g", False, "On"),
        ),
        coverage_complete=True,
    )
    plan = build_provisional_plan(
        snapshot, "disable", delta=(TopicChange("a", "On", "Off"),),
        skips=(TopicSkip("shared", "shared", ("beta",)), TopicSkip("required", "required")),
    )
    review = prepare_review(plan, ACCOUNT)
    assert review.plan.skips == plan.skips
    assert synthetic_approve(review, plan).status == "approved_synthetic"
    fresh = build_provisional_plan(
        snapshot, "disable", delta=plan.delta,
        skips=(TopicSkip("shared", "shared", ("gamma",)), TopicSkip("required", "required")),
    )
    decision = synthetic_approve(review, fresh)
    assert plan.evidence_revision == fresh.evidence_revision
    assert decision.status == "review_required"
    assert "protections_changed" in decision.blockers
    assert decision.review.plan.selected_keys == ("alpha",)
    assert decision.approval_basis is None


@pytest.mark.parametrize(("keys", "state", "reason"), [
    (("alpha", "missing"), "Off", "missing_set:missing"),
    (("alpha", "beta"), "Unknown", "unknown_state:a"),
])
def test_incomplete_evidence_remains_blocked_through_the_chain(keys, state, reason):
    plan = synthetic_enable_plan(keys=keys, state=state)
    review = prepare_review(plan, ACCOUNT)
    decision = synthetic_approve(review, plan)
    assert review.plan is plan
    assert decision.review.plan.selected_keys == keys
    assert reason in plan.blockers
    assert reason in review.blockers
    assert reason in decision.blockers
    assert decision.status == "blocked"
    assert decision.approval_basis is None
    assert decision.live_actions_available is False


@pytest.mark.parametrize("members", [(), ("required",)])
def test_empty_and_all_protected_chain_never_become_successful_disable(members):
    snapshot = build_provisional_snapshot(
        TARGET, ("alpha",), (TopicSet("alpha", members, True, SOURCE),),
        (TopicEvidence("required", True, "On"),), coverage_complete=True,
    )
    plan = build_provisional_plan(
        snapshot, "disable", skips=(TopicSkip("required", "required"),) if members else (),
    )
    review = prepare_review(plan, ACCOUNT)
    decision = synthetic_approve(review, plan)
    assert plan.outcome == ("all_protected" if members else "empty")
    assert review.status == decision.status == "blocked"
    assert "plan_not_actionable" in decision.blockers
    assert decision.approval_basis is None


@pytest.mark.parametrize("kind", ["provided_inventory", "native_read"])
def test_flat_chain_keeps_observations_separate_from_eligible_changes_and_live_consent(kind):
    catalog = FlatCatalog((
        FlatSet("alpha", "exact.hr", (
            FlatMember("exact.hr.topic.One"), FlatMember("exact.hr.topic.Shared"),
        ), "r1", "synthetic-source", "1"),
        FlatSet("beta", "exact.hr", (FlatMember("exact.hr.topic.Shared"),), "r1", "synthetic-source", "1"),
    ), "catalog-r1")
    inventory = NativeInventory(TARGET, "exact.hr", (
        InventoryTopic("a", "exact.hr.topic.One", "Off"),
        InventoryTopic("shared", "exact.hr.topic.Shared", "On"),
    ), "read-r1")
    discovery = replace(compare_flat_catalog(catalog, inventory, ("alpha", "beta")), evidence_kind=kind)
    plan = plan_topic_actions(discovery, "enable")
    context = {"retained_progress": True}
    direct = prepare_review(plan, ACCOUNT)
    called = prepare_review(plan, ACCOUNT, entry="called", caller_context=context)
    assert direct.plan is called.plan is plan
    assert direct.review_basis == called.review_basis
    assert called.plan.state_differences == (TopicChange("a", "Off", "On"),)
    assert called.plan.delta == ()
    assert called.plan.evidence_kind == kind

    fresh_inventory = replace(inventory, revision="read-r2", topics=(
        replace(inventory.topics[0], state="On"), inventory.topics[1],
    ))
    fresh = plan_topic_actions(
        replace(compare_flat_catalog(catalog, fresh_inventory, ("alpha", "beta")), evidence_kind=kind),
        "enable",
    )
    assert fresh.state_differences == ()
    assert fresh.observed_satisfied_member_ids == ("a", "shared")
    assert fresh.outcome == "blocked"
    decision = synthetic_approve(called, fresh)
    assert decision.status == "blocked"
    assert "production_review_unavailable" in decision.blockers
    assert decision.approval_basis is None
    assert decision.review.caller_context is context
    assert decision.live_actions_available is False
    assert prepare_review(fresh, ACCOUNT).status == "blocked"
    with pytest.raises(ReviewError) as error:
        review_topic_actions(plan, ACCOUNT)
    assert error.value.reason == "implementation_pending"
