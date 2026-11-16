# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""M5 pure controller fixtures, not live identity, permission, consent or UX evidence."""

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
ACCOUNT = "synthetic-maker"


def synthetic_plan(*, state="Off", revision="r1", target=TARGET, key="alpha", blockers=()):
    source = SourceBinding("synthetic-package", "1", revision, True)
    snapshot = build_provisional_snapshot(
        target, (key,), (TopicSet(key, ("topic-one",), True, source),),
        (TopicEvidence("topic-one", False, state),), coverage_complete=True,
    )
    return build_provisional_plan(
        snapshot, "enable",
        delta=(TopicChange("topic-one", "Off", "On"),) if state == "Off" else (),
        satisfied_member_ids=("topic-one",) if state == "On" else (),
        blockers=blockers,
    )


@pytest.fixture
def plan():
    return synthetic_plan()


def approve(review, fresh_plan=None, account=ACCOUNT, permissions=True):
    return record_synthetic_decision(
        review, "approve", fresh_plan=fresh_plan or review.plan,
        account_id=account, permissions_verified=permissions,
    )


def test_review_preserves_exact_plan_and_does_not_approve(plan):
    review = prepare_review(plan, ACCOUNT)
    assert review.plan is plan
    assert review.plan.target == TARGET
    assert review.plan.selected_keys == ("alpha",)
    assert review.plan.delta == (TopicChange("topic-one", "Off", "On"),)
    assert review.status == "awaiting_synthetic_decision"
    assert review.blockers == ()
    assert review.live_actions_available is False


def test_explicit_synthetic_approval_is_bound_to_account_and_plan_but_never_live(plan):
    review = prepare_review(plan, ACCOUNT)
    result = approve(review)
    assert result.review is review
    assert result.status == "approved_synthetic"
    assert result.approval_basis == "synthetic-review:" + review.review_basis
    assert result.blockers == ()
    assert result.live_actions_available is False
    assert prepare_review(plan, "another-synthetic-maker").review_basis != review.review_basis


def test_direct_and_called_paths_share_consent_rules_and_preserve_private_context(plan):
    context = {"private": "never-echo-this", "parent_step_complete": False}
    direct = prepare_review(plan, ACCOUNT)
    called = prepare_review(plan, ACCOUNT, entry="called", caller_context=context)
    assert direct.review_basis == called.review_basis
    assert approve(direct).status == approve(called).status
    assert approve(direct).approval_basis == approve(called).approval_basis
    assert called.caller_context is context
    assert context["parent_step_complete"] is False
    assert "never-echo-this" not in repr(called)
    assert ACCOUNT not in repr(called)
    assert "never-echo-this" not in repr(approve(called))


@pytest.mark.parametrize(("decision", "status"), [("deny", "denied"), ("cancel", "cancelled")])
def test_denial_and_cancellation_preserve_progress_without_fresh_reads(plan, decision, status):
    class Forbidden:
        def __getattribute__(self, name):
            pytest.fail("Denial/cancellation must not access fresh input.")

    context = {"completed_setup": True}
    review = prepare_review(plan, ACCOUNT, entry="called", caller_context=context)
    result = record_synthetic_decision(
        review, decision, fresh_plan=Forbidden(), account_id=Forbidden(),
        permissions_verified=Forbidden(),
    )
    assert result.status == status
    assert result.approval_basis is None
    assert result.review is review
    assert result.review.caller_context is context
    assert context == {"completed_setup": True}
    assert result.live_actions_available is False


@pytest.mark.parametrize(("fresh", "reason"), [
    (lambda: synthetic_plan(revision="r2"), "evidence_changed"),
    (lambda: synthetic_plan(state="On"), "plan_changed"),
    (lambda: synthetic_plan(key="owner-defined:new"), "selection_changed"),
    (lambda: synthetic_plan(target=replace(TARGET, agent_id="00000000-0000-0000-0000-000000004444")), "target_changed"),
    (lambda: synthetic_plan(blockers=("stale_plan",)), "plan_changed"),
])
def test_material_drift_requires_new_review_and_preserves_original_selection(plan, fresh, reason):
    context = {"completed_setup": True}
    review = prepare_review(plan, ACCOUNT, entry="called", caller_context=context)
    result = approve(review, fresh())
    assert result.status == "review_required"
    assert reason in result.blockers
    assert result.approval_basis is None
    assert result.review.plan is plan
    assert result.review.plan.selected_keys == ("alpha",)
    assert result.review.caller_context is context
    assert result.live_actions_available is False


def test_changed_action_invalidates_enable_consent(plan):
    source = SourceBinding("synthetic-package", "1", "r1", True)
    snapshot = build_provisional_snapshot(
        TARGET, ("alpha",), (TopicSet("alpha", ("topic-one",), True, source),),
        (TopicEvidence("topic-one", False, "On"),), coverage_complete=True,
    )
    disable = build_provisional_plan(
        snapshot, "disable", delta=(TopicChange("topic-one", "On", "Off"),),
    )
    result = approve(prepare_review(plan, ACCOUNT), disable)
    assert result.status == "review_required"
    assert "action_changed" in result.blockers
    assert result.approval_basis is None


def test_changed_protecting_sets_invalidate_consent_even_without_source_revision_change():
    source = SourceBinding("synthetic-package", "1", "r1", True)
    snapshot = build_provisional_snapshot(
        TARGET, ("alpha",),
        (
            TopicSet("alpha", ("topic-one", "shared"), True, source),
            TopicSet("beta", ("beta-only", "shared"), True, source),
            TopicSet("gamma", ("gamma-only", "shared"), True, source),
        ),
        (
            TopicEvidence("topic-one", False, "On"), TopicEvidence("shared", False, "On"),
            TopicEvidence("beta-only", False, "On"), TopicEvidence("gamma-only", False, "On"),
        ),
        coverage_complete=True,
    )
    initial = build_provisional_plan(
        snapshot, "disable", delta=(TopicChange("topic-one", "On", "Off"),),
        skips=(TopicSkip("shared", "shared", ("beta",)),),
    )
    revised = build_provisional_plan(
        snapshot, "disable", delta=initial.delta,
        skips=(TopicSkip("shared", "shared", ("beta", "gamma")),),
    )
    assert initial.evidence_revision == revised.evidence_revision
    result = approve(prepare_review(initial, ACCOUNT), revised)
    assert result.status == "review_required"
    assert "protections_changed" in result.blockers
    assert result.approval_basis is None


@pytest.mark.parametrize(("account", "permissions", "reason"), [
    ("another-synthetic-maker", True, "maker_changed"),
    (ACCOUNT, False, "permissions_denied"),
    (ACCOUNT, None, "permissions_unverified"),
])
def test_current_maker_and_permission_verdict_are_required(plan, account, permissions, reason):
    result = approve(prepare_review(plan, ACCOUNT), account=account, permissions=permissions)
    assert result.status == "review_required"
    assert reason in result.blockers
    assert result.approval_basis is None


def test_approval_requires_supplied_fresh_plan_and_current_account(plan):
    review = prepare_review(plan, ACCOUNT)
    missing_plan = record_synthetic_decision(review, "approve", account_id=ACCOUNT, permissions_verified=True)
    missing_account = record_synthetic_decision(review, "approve", fresh_plan=plan, permissions_verified=True)
    assert missing_plan.status == missing_account.status == "blocked"
    assert missing_plan.blockers == ("fresh_plan_unavailable",)
    assert missing_account.blockers == ("current_account_unverified",)
    assert missing_plan.approval_basis is missing_account.approval_basis is None


def test_verified_synthetic_no_op_still_needs_explicit_decision_and_never_submits():
    plan = synthetic_plan(state="On")
    review = prepare_review(plan, ACCOUNT)
    assert review.status == "awaiting_synthetic_decision"
    assert plan.outcome == "already_correct"
    assert plan.delta == ()
    assert record_synthetic_decision(review, "cancel").status == "cancelled"
    approved = approve(review)
    assert approved.status == "approved_synthetic_no_changes"
    assert approved.live_actions_available is False


@pytest.mark.parametrize("outcome", ["all_protected", "empty", "unknown"])
def test_non_actionable_outcomes_are_not_successful_approvals(outcome):
    source = SourceBinding("synthetic-package", "1", "r1", True)
    members = () if outcome == "empty" else ("topic-one",)
    required = outcome == "all_protected"
    snapshot = build_provisional_snapshot(
        TARGET, ("alpha",), (TopicSet("alpha", members, True, source),),
        (TopicEvidence("topic-one", required, "Unknown" if outcome == "unknown" else "On"),),
        coverage_complete=True,
    )
    plan = build_provisional_plan(
        snapshot, "disable",
        skips=(TopicSkip("topic-one", "required"),) if required else (),
    )
    review = prepare_review(plan, ACCOUNT)
    assert review.plan.outcome == outcome
    assert review.status == "blocked"
    result = approve(review)
    assert "plan_not_actionable" in result.blockers
    assert result.status == "blocked"
    assert result.approval_basis is None


def test_blocked_plan_reasons_survive_review_and_cannot_be_overridden(plan):
    blocked = synthetic_plan(blockers=("stale_plan",))
    review = prepare_review(blocked, ACCOUNT)
    assert "stale_plan" in review.blockers
    result = approve(review, plan)
    assert result.status == "blocked"
    assert "stale_plan" in result.blockers
    assert result.approval_basis is None


def test_native_flat_preview_does_not_become_live_approval_with_true_permissions():
    catalog = FlatCatalog((
        FlatSet("alpha", "exact.hr", (FlatMember("exact.hr.topic.One"),), "r1", "synthetic-source", "1"),
    ), "catalog-r1")
    inventory = NativeInventory(
        TARGET, "exact.hr", (InventoryTopic("topic-one", "exact.hr.topic.One", "Off"),), "read-r1",
    )
    discovery = replace(compare_flat_catalog(catalog, inventory, ("alpha",)), evidence_kind="native_read")
    plan = plan_topic_actions(discovery, "enable")
    review = prepare_review(plan, ACCOUNT)
    assert review.plan.state_differences == (TopicChange("topic-one", "Off", "On"),)
    assert review.plan.delta == ()
    assert "production_review_unavailable" in review.blockers
    result = approve(review)
    assert result.status == "blocked"
    assert result.approval_basis is None
    assert result.live_actions_available is False


@pytest.mark.parametrize("field", [
    {"delta": ()},
    {"selected_keys": ("other-selection",)},
    {"blockers": ("hidden-blocker",)},
    {"approval_basis": "synthetic:forged"},
])
def test_changed_plan_cannot_reuse_its_previous_review_fingerprint(plan, field):
    with pytest.raises(ReviewError) as error:
        prepare_review(replace(plan, **field), ACCOUNT)
    assert error.value.reason == "invalid_plan"


@pytest.mark.parametrize("field", [
    {"review_basis": "forged"},
    {"account_id": "different-maker"},
    {"blockers": ("hidden-blocker",)},
    {"status": "approved"},
])
def test_forged_review_fields_are_rejected(plan, field):
    review = prepare_review(plan, ACCOUNT)
    with pytest.raises(ReviewError) as error:
        approve(replace(review, **field))
    assert error.value.reason == "invalid_review"


@pytest.mark.parametrize("account", ["", " unsafe", "private\naccount", None])
def test_invalid_accounts_do_not_echo_private_identity(plan, account):
    with pytest.raises(ReviewError) as error:
        prepare_review(plan, account)
    assert error.value.reason == "invalid_account"
    assert "private" not in str(error.value)


@pytest.mark.parametrize("decision", ["", "Approve", "setup-complete", True, None])
def test_only_explicit_decisions_are_admitted(plan, decision):
    with pytest.raises(ReviewError) as error:
        record_synthetic_decision(prepare_review(plan, ACCOUNT), decision)
    assert error.value.reason == "invalid_decision"


def test_truthy_non_boolean_permission_evidence_is_rejected(plan):
    with pytest.raises(ReviewError) as error:
        approve(prepare_review(plan, ACCOUNT), permissions=1)
    assert error.value.reason == "invalid_permissions"


def test_production_review_never_invokes_synthetic_consent_or_live_inputs(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("Production review must not invoke the synthetic controller.")

    class LiveInput:
        def __getattribute__(self, name):
            pytest.fail("Production approval is unavailable; do not access live inputs.")

    monkeypatch.setattr("topic_actions_review.prepare_review", forbidden)
    monkeypatch.setattr("topic_actions_review.record_synthetic_decision", forbidden)
    with pytest.raises(ReviewError) as error:
        review_topic_actions(LiveInput(), ACCOUNT)
    assert error.value.reason == "implementation_pending"
    assert list(tmp_path.iterdir()) == []
