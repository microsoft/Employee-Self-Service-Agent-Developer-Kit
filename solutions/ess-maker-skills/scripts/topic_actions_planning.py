# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""M4 synthetic plans and blocked flat-catalog previews; no live mutations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json

from topic_actions_discovery import (
    DiscoveryError,
    DiscoverySnapshot,
    DiscoveryTarget,
    build_provisional_snapshot,
)


class PlanningError(ValueError):
    """Static planning failure without fixture or target contents."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class TopicChange:
    component_id: str
    before: str
    after: str


@dataclass(frozen=True)
class TopicSkip:
    component_id: str
    reason: str
    protecting_sets: tuple[str, ...] = ()


@dataclass(frozen=True)
class TopicPlan:
    target: DiscoveryTarget
    action: str
    selected_keys: tuple[str, ...]
    evidence_revision: str
    delta: tuple[TopicChange, ...]
    satisfied_member_ids: tuple[str, ...]
    skips: tuple[TopicSkip, ...]
    blockers: tuple[str, ...]
    outcome: str
    approval_basis: str
    state_differences: tuple[TopicChange, ...] = ()
    observed_satisfied_member_ids: tuple[str, ...] = ()
    evidence_kind: str = "synthetic"
    execution_policy: str = "provided_evidence"
    warnings: tuple[str, ...] = ()
    members: tuple[tuple[str, str, str | None], ...] = ()

    @property
    def live_actions_available(self) -> bool:
        return (
            self.evidence_kind == "catalog"
            and self.execution_policy == "source_inventory"
            and not self.blockers
            and self.outcome in ("changes_proposed", "already_correct")
        )


def _fail(reason: str) -> None:
    raise PlanningError(reason, "Topic-action planning could not be established. No changes attempted.")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_provisional_plan(
    snapshot: DiscoverySnapshot,
    action: str,
    *,
    delta: tuple[TopicChange, ...] = (),
    satisfied_member_ids: tuple[str, ...] = (),
    skips: tuple[TopicSkip, ...] = (),
    blockers: tuple[str, ...] = (),
) -> TopicPlan:
    """Validate supplied synthetic outcomes, not compute production policy.

    Test adapters supply the delta, satisfied members and protection skips.
    This boundary checks their scope and consistency and binds the result to
    the synthetic evidence. It does not decide outside-group protection,
    verify live freshness/permissions, or grant consent. The approval basis is
    a synthetic review fingerprint, never maker approval or a native token.
    """
    if type(snapshot) is not DiscoverySnapshot:
        _fail("invalid_snapshot")
    try:
        canonical = build_provisional_snapshot(
            snapshot.target, snapshot.selected_keys, snapshot.sets, snapshot.topics,
            coverage_complete=snapshot.coverage_complete,
        )
        if canonical != snapshot:
            _fail("invalid_snapshot")
        for item in snapshot.sets:
            if any(
                value is not None and not isinstance(value, str)
                for value in (item.description, item.description_provenance)
            ):
                _fail("invalid_snapshot")
        evidence_revision = _digest(asdict(snapshot))
    except (DiscoveryError, TypeError, ValueError):
        _fail("invalid_snapshot")
    if not isinstance(action, str) or action not in ("enable", "disable"):
        _fail("invalid_action")
    if any(
        not isinstance(value, tuple)
        for value in (delta, satisfied_member_ids, skips, blockers)
    ):
        _fail("invalid_plan")
    if any(
        not isinstance(reason, str) or not reason or reason != reason.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in reason)
        for reason in blockers
    ):
        _fail("invalid_blocker")

    desired = "On" if action == "enable" else "Off"
    selected = set(snapshot.selected_member_ids)
    by_id = {item.component_id: item for item in snapshot.topics}
    by_key = {item.key: item for item in snapshot.sets}
    classified: set[str] = set()

    def register(identity: str) -> None:
        if not isinstance(identity, str) or identity not in selected:
            _fail("out_of_scope")
        if identity in classified:
            _fail("ambiguous_plan")
        classified.add(identity)

    for change in delta:
        if type(change) is not TopicChange:
            _fail("invalid_change")
        register(change.component_id)
        topic = by_id.get(change.component_id)
        if (
            topic is None or change.before not in ("On", "Off")
            or change.before != topic.state or change.after != desired
            or change.before == desired
            or (action == "disable" and topic.required is True)
        ):
            _fail("invalid_change")
    for identity in satisfied_member_ids:
        register(identity)
        topic = by_id.get(identity)
        if (
            topic is None or topic.state != desired
            or (action == "disable" and topic.required is True)
        ):
            _fail("invalid_satisfied_member")
    for skip in skips:
        if type(skip) is not TopicSkip:
            _fail("invalid_skip")
        register(skip.component_id)
        topic = by_id.get(skip.component_id)
        if (
            action != "disable" or topic is None
            or not isinstance(skip.protecting_sets, tuple)
            or any(not isinstance(key, str) for key in skip.protecting_sets)
            or len(set(skip.protecting_sets)) != len(skip.protecting_sets)
        ):
            _fail("invalid_skip")
        if skip.reason == "required":
            if topic.required is not True or skip.protecting_sets:
                _fail("invalid_skip")
        elif skip.reason == "shared":
            if topic.required is not False or not skip.protecting_sets:
                _fail("invalid_skip")
            if any(
                key not in by_key or key in snapshot.selected_keys
                or skip.component_id not in by_key[key].member_ids
                for key in skip.protecting_sets
            ):
                _fail("invalid_skip")
        else:
            _fail("invalid_skip")

    reasons = tuple(dict.fromkeys((
        *snapshot.blockers,
        *blockers,
        *(
            f"unknown_state:{identity}"
            for identity in snapshot.selected_member_ids
            if identity in by_id and by_id[identity].state == "Unknown"
        ),
    )))
    if not reasons and classified != selected:
        _fail("incomplete_plan")
    if reasons:
        if not selected and all(reason.startswith("empty_membership:") for reason in reasons):
            outcome = "empty"
        elif all(reason.startswith(("unknown_state:", "unknown_protection:")) for reason in reasons):
            outcome = "unknown"
        else:
            outcome = "blocked"
    elif delta:
        outcome = "changes_proposed"
    elif satisfied_member_ids:
        outcome = "already_correct"
    elif skips:
        outcome = "all_protected"
    else:
        outcome = "empty"
    plan = TopicPlan(
        snapshot.target, action, snapshot.selected_keys, evidence_revision,
        delta, satisfied_member_ids, skips, reasons, outcome, "",
    )
    return replace(plan, approval_basis="synthetic:" + _digest(asdict(plan)))


def plan_topic_actions(snapshot: object, action: str) -> TopicPlan:
    """Preview observed flat-set states without creating an eligible delta.

    Input provenance is retained, not reauthenticated. Interim definitions
    cannot establish protection or package authority, so every flat preview
    remains blocked. State differences and already-matching observations are
    explicitly separate from eligible changes and satisfied eligible members.
    No client, native token, synthetic fallback, or mutation is used.
    """
    from topic_actions_catalog import CatalogSnapshot, plan_catalog_actions
    from topic_actions_discovery import _identity, _key, _target
    from topic_actions_flat_discovery import (
        FlatCatalog,
        FlatDiscoveryResult,
        MemberMatch,
        SetAvailability,
        _selection,
        _validate_catalog,
    )

    if type(snapshot) is CatalogSnapshot:
        return plan_catalog_actions(snapshot, action)
    if type(snapshot) is not FlatDiscoveryResult:
        _fail("implementation_pending")
    if not isinstance(action, str) or action not in ("enable", "disable"):
        _fail("invalid_action")
    try:
        target = _target(snapshot.target)
        if target != snapshot.target:
            _fail("invalid_discovery")
        selected = _selection(snapshot.selected_keys)
        if not selected:
            _fail("invalid_selection")
        if (
            not isinstance(snapshot.sets, tuple)
            or any(type(item) is not SetAvailability for item in snapshot.sets)
            or not isinstance(snapshot.selected_member_ids, tuple)
            or not isinstance(snapshot.blockers, tuple)
            or snapshot.evidence_kind not in ("native_read", "provided_inventory")
        ):
            _fail("invalid_discovery")
        _validate_catalog(FlatCatalog(
            tuple(item.definition for item in snapshot.sets), snapshot.catalog_revision,
        ))
        if snapshot.inventory_revision is not None:
            _key(snapshot.inventory_revision)
        for reason in snapshot.blockers:
            _key(reason)
        by_key = {}
        for availability in snapshot.sets:
            key = availability.definition.key
            if key in by_key or not isinstance(availability.members, tuple):
                _fail("invalid_discovery")
            by_key[key] = availability
            if len(availability.members) != len(availability.definition.members):
                _fail("invalid_discovery")
            for match, definition in zip(availability.members, availability.definition.members):
                if (
                    type(match) is not MemberMatch or match.schema_name != definition.schema_name
                    or match.required is not definition.required
                    or match.state not in ("On", "Off", "Unknown")
                ):
                    _fail("invalid_discovery")
                if match.reason == "exact_schema_match":
                    if match.component_id is None or _identity(match.component_id) != match.component_id:
                        _fail("invalid_discovery")
                elif match.reason in ("missing_member", "ambiguous_member", "not_applicable"):
                    if match.component_id is not None or match.state != "Unknown":
                        _fail("invalid_discovery")
                else:
                    _fail("invalid_discovery")
            resolved = sum(match.component_id is not None for match in availability.members)
            if any(match.reason == "not_applicable" for match in availability.members):
                if not all(match.reason == "not_applicable" for match in availability.members):
                    _fail("invalid_discovery")
                expected_status = "not_applicable"
            elif any(match.reason == "ambiguous_member" for match in availability.members):
                expected_status = "ambiguous"
            else:
                expected_status = "present" if resolved == len(availability.members) else (
                    "partial" if resolved else "absent"
                )
            if availability.status != expected_status:
                _fail("invalid_discovery")

        reasons = [*snapshot.blockers, "authoritative_planning_unavailable"]
        if snapshot.inventory_revision is None:
            reasons.append("inventory_freshness_unverified")
        observed = {}
        for availability in snapshot.sets:
            if availability.definition.key not in selected:
                continue
            if availability.status != "present":
                reasons.append(f"set_{availability.status}:{availability.definition.key}")
            for match in availability.members:
                if match.component_id is None:
                    continue
                previous = observed.get(match.component_id)
                if previous is not None and (
                    previous.schema_name != match.schema_name or previous.state != match.state
                ):
                    _fail("conflicting_evidence")
                observed[match.component_id] = match
                if match.required is None:
                    reasons.append(f"unknown_protection:{match.component_id}")
                if match.state == "Unknown":
                    reasons.append(f"unknown_state:{match.component_id}")
        reasons.extend(f"missing_set:{key}" for key in selected if key not in by_key)
        if tuple(observed) != snapshot.selected_member_ids:
            _fail("invalid_discovery")
        evidence_revision = _digest(asdict(snapshot))
    except PlanningError:
        raise
    except DiscoveryError as error:
        _fail(error.reason)
    except (TypeError, ValueError, AttributeError):
        _fail("invalid_discovery")

    desired = "On" if action == "enable" else "Off"
    differences = tuple(
        TopicChange(identity, match.state, desired)
        for identity, match in observed.items()
        if match.state in ("On", "Off") and match.state != desired
    )
    matching = tuple(identity for identity, match in observed.items() if match.state == desired)
    plan = TopicPlan(
        target, action, selected, evidence_revision, (), (), (),
        tuple(dict.fromkeys(reasons)), "blocked", "",
        state_differences=differences, observed_satisfied_member_ids=matching,
        evidence_kind=snapshot.evidence_kind,
    )
    return replace(plan, approval_basis="read_only:" + _digest(asdict(plan)))
