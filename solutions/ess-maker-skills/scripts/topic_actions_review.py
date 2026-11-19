# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""M5 review/decision contracts; synthetic consent never authorizes live writes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace

from topic_actions_discovery import DiscoveryError, _key, _target
from topic_actions_planning import TopicChange, TopicPlan, TopicSkip, _digest


class ReviewError(ValueError):
    """Static review failure without account, target or caller-context contents."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class TopicReview:
    plan: TopicPlan
    account_id: str = field(repr=False)
    entry: str
    review_basis: str
    status: str
    blockers: tuple[str, ...]
    caller_context: object = field(default=None, repr=False, compare=False)

    @property
    def live_actions_available(self) -> bool:
        return False


@dataclass(frozen=True)
class ReviewDecision:
    review: TopicReview
    status: str
    blockers: tuple[str, ...]
    approval_basis: str | None = None

    @property
    def live_actions_available(self) -> bool:
        return False


def _fail(reason: str) -> None:
    raise ReviewError(reason, "Topic-action review could not be established. No changes attempted.")


def _account(value: str) -> str:
    try:
        return _key(value)
    except DiscoveryError:
        _fail("invalid_account")


def _validate_plan(plan: TopicPlan) -> None:
    if type(plan) is not TopicPlan:
        _fail("invalid_plan")
    try:
        if _target(plan.target) != plan.target:
            _fail("invalid_plan")
        if not isinstance(plan.action, str) or plan.action not in ("enable", "disable"):
            _fail("invalid_plan")
        if not isinstance(plan.selected_keys, tuple) or not plan.selected_keys:
            _fail("invalid_plan")
        for key in plan.selected_keys:
            _key(key)
        if len(set(plan.selected_keys)) != len(plan.selected_keys):
            _fail("invalid_plan")
        _key(plan.evidence_revision)
        if plan.evidence_kind not in ("synthetic", "native_read", "provided_inventory"):
            _fail("invalid_plan")
        if any(not isinstance(value, tuple) for value in (
            plan.delta, plan.satisfied_member_ids, plan.skips, plan.blockers,
            plan.state_differences, plan.observed_satisfied_member_ids,
        )):
            _fail("invalid_plan")
        if any(type(change) is not TopicChange for change in (*plan.delta, *plan.state_differences)):
            _fail("invalid_plan")
        if any(type(skip) is not TopicSkip for skip in plan.skips):
            _fail("invalid_plan")
        for value in (*plan.satisfied_member_ids, *plan.observed_satisfied_member_ids, *plan.blockers):
            _key(value)
        if plan.outcome not in (
            "changes_proposed", "already_correct", "all_protected", "empty", "unknown", "blocked",
        ):
            _fail("invalid_plan")
        if (
            (plan.outcome == "changes_proposed" and not plan.delta)
            or (plan.outcome == "already_correct" and (plan.delta or not plan.satisfied_member_ids))
        ):
            _fail("invalid_plan")
        prefix = "synthetic:" if plan.evidence_kind == "synthetic" else "read_only:"
        expected = prefix + _digest(asdict(replace(plan, approval_basis="")))
        if plan.approval_basis != expected:
            _fail("invalid_plan")
    except ReviewError:
        raise
    except (DiscoveryError, TypeError, ValueError, AttributeError):
        _fail("invalid_plan")


def prepare_review(
    plan: TopicPlan,
    account_id: str,
    *,
    entry: str = "direct",
    caller_context: object = None,
) -> TopicReview:
    """Expose the exact plan without approving it or completing a caller step.

    The plan retains its target, action, selection, delta, satisfied members,
    skip reasons and uncertainty. Account IDs are provisional caller-supplied
    identities, not live authentication evidence. Caller context is opaque,
    retained in memory, and excluded from repr and review fingerprints.
    """
    _validate_plan(plan)
    account_id = _account(account_id)
    if not isinstance(entry, str) or entry not in ("direct", "called"):
        _fail("invalid_entry")
    blockers = list(plan.blockers)
    if plan.evidence_kind != "synthetic":
        blockers.append("production_review_unavailable")
    if plan.outcome in ("all_protected", "empty", "unknown", "blocked"):
        blockers.append("plan_not_actionable")
    reasons = tuple(dict.fromkeys(blockers))
    basis = _digest({"account": account_id, "plan": plan.approval_basis})
    return TopicReview(
        plan, account_id, entry, basis,
        "blocked" if reasons else "awaiting_synthetic_decision",
        reasons, caller_context,
    )


def record_synthetic_decision(
    review: TopicReview,
    decision: str,
    *,
    fresh_plan: TopicPlan | None = None,
    account_id: str | None = None,
    permissions_verified: bool | None = None,
) -> ReviewDecision:
    """Test-only consent/freshness controller; never a production approval.

    Fresh plans, accounts and permission verdicts are supplied by test callers,
    not read from a tenant here. A fingerprint is not a signature or proof of
    deployed freshness. Native/read-only previews cannot be approved through
    this boundary. Denial/cancellation needs no fresh reads and preserves the
    original review and private caller context.
    """
    if type(review) is not TopicReview:
        _fail("invalid_review")
    expected = prepare_review(
        review.plan, review.account_id, entry=review.entry,
        caller_context=review.caller_context,
    )
    if review != expected:
        _fail("invalid_review")
    if not isinstance(decision, str) or decision not in ("approve", "deny", "cancel"):
        _fail("invalid_decision")
    if decision in ("deny", "cancel"):
        return ReviewDecision(review, "denied" if decision == "deny" else "cancelled", ())
    if review.blockers:
        return ReviewDecision(review, "blocked", review.blockers)
    if fresh_plan is None:
        return ReviewDecision(review, "blocked", ("fresh_plan_unavailable",))
    _validate_plan(fresh_plan)
    if account_id is None:
        return ReviewDecision(review, "blocked", ("current_account_unverified",))
    account_id = _account(account_id)
    if permissions_verified is not None and type(permissions_verified) is not bool:
        _fail("invalid_permissions")

    reasons = []
    if account_id != review.account_id:
        reasons.append("maker_changed")
    if fresh_plan.target != review.plan.target:
        reasons.append("target_changed")
    if fresh_plan.action != review.plan.action:
        reasons.append("action_changed")
    if fresh_plan.selected_keys != review.plan.selected_keys:
        reasons.append("selection_changed")
    if fresh_plan.evidence_revision != review.plan.evidence_revision:
        reasons.append("evidence_changed")
    if fresh_plan.skips != review.plan.skips:
        reasons.append("protections_changed")
    if fresh_plan.approval_basis != review.plan.approval_basis:
        reasons.append("plan_changed")
    if permissions_verified is not True:
        reasons.append("permissions_denied" if permissions_verified is False else "permissions_unverified")
    if reasons:
        return ReviewDecision(review, "review_required", tuple(reasons))
    return ReviewDecision(
        review, "approved_synthetic" if review.plan.delta else "approved_synthetic_no_changes",
        (), "synthetic-review:" + review.review_basis,
    )


def review_topic_actions(plan: object, account_id: str) -> TopicReview:
    """Production consent remains unavailable; no synthetic fallback or writes."""
    _fail("implementation_pending")
