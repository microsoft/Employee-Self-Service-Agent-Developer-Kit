# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""In-memory review, single-attempt execution and conservative reconciliation.

The controller is transport-independent. Production admission is supplied only
by the native adapter, never by request JSON or an approval digest.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import time
import threading
from typing import Callable, Protocol

from agentbuilder import AgentBuilderHTTPError
from topic_actions_catalog import CatalogSnapshot, plan_catalog_actions
from topic_actions_components import normalize_state
from topic_actions_discovery import _identity
from topic_actions_planning import TopicPlan, _digest


_LOCKS_GUARD = threading.Lock()
_TARGET_LOCKS: dict[tuple[str, str, str], threading.Lock] = {}


def _target_lock(plan: TopicPlan):
    key = (plan.target.tenant_id, plan.target.environment_id, plan.target.agent_id)
    with _LOCKS_GUARD:
        return _TARGET_LOCKS.setdefault(key, threading.Lock())


@dataclass(frozen=True)
class OperationEvidence:
    snapshot: CatalogSnapshot
    account_id: str = field(repr=False)
    body: dict = field(repr=False)
    blockers: tuple[str, ...] = ()

    def fingerprint(self) -> str:
        return _digest({
            "snapshot": asdict(self.snapshot), "account": self.account_id,
            "body": self.body, "blockers": self.blockers,
        })


class ActionBackend(Protocol):
    def read(self) -> OperationEvidence: ...
    def admission_blockers(self, evidence: OperationEvidence) -> tuple[str, ...]: ...
    def submit_once(self, target_agent_id: str, payload: dict) -> None: ...


def build_state_payload(evidence: OperationEvidence, plan: TopicPlan) -> dict:
    """Preserve complete remote components; change only the approved state pair."""
    token = evidence.body.get("changeToken")
    if not isinstance(token, str) or not token.strip() or not plan.delta:
        raise ValueError("A fresh change token and nonempty delta are required.")
    if plan != plan_catalog_actions(evidence.snapshot, plan.action) or plan.blockers:
        raise ValueError("The plan must be computed from this exact evidence.")
    indexed = {}
    rows = evidence.body.get("botComponentChanges")
    if not isinstance(rows, list):
        raise ValueError("Invalid component collection.")
    for row in rows:
        if not isinstance(row, dict) or row.get("$kind") != "BotComponentInsert":
            raise ValueError("Unsupported component collection.")
        component = row.get("component")
        if not isinstance(component, dict):
            raise ValueError("Invalid component.")
        identity = _identity(component.get("id"))
        if identity in indexed:
            raise ValueError("Ambiguous component identity.")
        if _identity(component.get("parentBotId")) != plan.target.agent_id:
            raise ValueError("Unverified parent identity.")
        indexed[identity] = component
    changes = []
    for change in plan.delta:
        component = indexed.get(change.component_id)
        if (
            component is None or component.get("$kind") != "DialogComponent"
            or normalize_state(component.get("state"), component.get("status"))[0] != change.before
            or any(
                schema != component.get("schemaName")
                for _, schema, identity in evidence.snapshot.members
                if identity == change.component_id
            )
        ):
            raise ValueError("The exact topic state could not be established.")
        updated = deepcopy(component)
        updated["state"] = updated["status"] = "Active" if change.after == "On" else "Inactive"
        changes.append({"$kind": "BotComponentUpdate", "component": updated})
    return {
        "changeToken": token,
        "botComponentChanges": changes,
        **{key: [] for key in (
            "cloudFlowDefinitionChanges", "connectionReferenceChanges",
            "connectorDefinitionChanges", "environmentVariableChanges",
            "aIPluginOperationChanges", "componentCollectionChanges",
            "dataverseTableSearchChanges", "connectedAgentDefinitionChanges",
        )},
    }


def public_plan(plan: TopicPlan) -> dict:
    def changes(items):
        return [
            {"componentId": item.component_id, "before": item.before, "after": item.after}
            for item in items
        ]

    return {
        "target": {
            "tenantId": plan.target.tenant_id, "environmentId": plan.target.environment_id,
            "agentId": plan.target.agent_id,
        },
        "action": plan.action,
        "selectedSets": list(plan.selected_keys), "outcome": plan.outcome,
        "proposedChanges": changes(plan.delta),
        "observedDifferences": changes(plan.state_differences),
        "alreadyCorrect": list(plan.satisfied_member_ids),
        "protected": [{
            "componentId": item.component_id, "reason": item.reason,
            "protectingSets": list(item.protecting_sets),
        } for item in plan.skips],
        "blockers": list(plan.blockers),
    }


def _component_map(body: dict) -> dict:
    result = {}
    for row in body["botComponentChanges"]:
        if row["$kind"] != "BotComponentInsert":
            raise ValueError("Unsupported readback.")
        item = deepcopy(row["component"])
        identity = _identity(item["id"])
        if identity in result:
            raise ValueError("Ambiguous readback.")
        result[identity] = item
    return result


def _reconcile(before: OperationEvidence, after: OperationEvidence, plan: TopicPlan) -> tuple[list[dict], bool]:
    """Observed desired state after an uncertain submission is not attribution."""
    before_map = _component_map(before.body)
    after_map = _component_map(after.body)
    delta = {item.component_id: item for item in plan.delta}
    containment = set(before_map) == set(after_map)
    for identity, original in before_map.items():
        current = deepcopy(after_map.get(identity))
        if current is None:
            containment = False
            continue
        expected = deepcopy(original)
        if identity in delta:
            expected.pop("state", None)
            expected.pop("status", None)
            current.pop("state", None)
            current.pop("status", None)
        if current != expected:
            containment = False
    stable_authority = (
        before.account_id == after.account_id
        and before.snapshot.catalog_revision == after.snapshot.catalog_revision
        and before.snapshot.evidence.target == after.snapshot.evidence.target
        and before.snapshot.members == after.snapshot.members
        and before.snapshot.evidence.sets == after.snapshot.evidence.sets
        and {
            topic.component_id: topic.required for topic in before.snapshot.evidence.topics
        } == {
            topic.component_id: topic.required for topic in after.snapshot.evidence.topics
        }
        and before.snapshot.evidence.coverage_complete == after.snapshot.evidence.coverage_complete
        and not after.snapshot.evidence.blockers
        and not after.blockers
    )
    results = []
    skips = {item.component_id: item for item in plan.skips}
    for identity in before.snapshot.evidence.selected_member_ids:
        current = after_map.get(identity, {})
        state = normalize_state(current.get("state"), current.get("status"))[0]
        if identity in skips:
            status, reason = "protected", skips[identity].reason
        elif identity in delta:
            status = "observed_desired" if state == delta[identity].after else (
                "unchanged" if state == delta[identity].before else "unverified"
            )
            reason = "readback"
        else:
            desired = "On" if plan.action == "enable" else "Off"
            status = "already_correct" if state == desired else "unverified"
            reason = "readback"
        results.append({"componentId": identity, "state": state, "status": status, "reason": reason})
    return results, containment and stable_authority


class TopicActionSession:
    """One review and at most one dispatch. No saved approval, journal or replay."""

    def __init__(
        self, backend: ActionBackend, action: str, *, caller_context: dict | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if action not in ("enable", "disable"):
            raise ValueError("Unsupported action.")
        self.backend = backend
        self.action = action
        self.caller_context = deepcopy(caller_context or {})
        self.clock = clock
        self._used = False

    def run(self, confirm: Callable[[dict], str]) -> dict:
        if self._used:
            return self._result("blocked", blockers=("session_consumed",))
        self._used = True
        try:
            evidence = self.backend.read()
        except AgentBuilderHTTPError as error:
            reason = {
                401: "authentication_failed",
                403: "access_denied",
                404: "target_not_found",
            }.get(error.status_code, "evidence_read_failed")
            return self._result("blocked", blockers=(reason,))
        except Exception:
            return self._result("blocked", blockers=("evidence_read_failed",))
        try:
            plan = plan_catalog_actions(evidence.snapshot, self.action)
            blockers = tuple(dict.fromkeys((
                *plan.blockers, *evidence.blockers, *self.backend.admission_blockers(evidence),
            )))
        except Exception:
            return self._result("blocked", blockers=("evidence_read_failed",))
        if blockers or plan.outcome not in ("changes_proposed", "already_correct"):
            return self._result(
                "blocked", plan=plan, blockers=blockers or (f"plan_{plan.outcome}",),
            )
        # Freeze the basis before handing the public copy to the interaction.
        basis = evidence.fingerprint()
        deadline = self.clock() + 300
        try:
            decision = confirm(public_plan(plan))
        except (KeyboardInterrupt, EOFError):
            decision = "cancel"
        except Exception:
            return self._result("blocked", plan=plan, blockers=("approval_interaction_failed",))
        if decision in ("deny", "cancel"):
            return self._result("denied" if decision == "deny" else "cancelled", plan=plan)
        if decision != "approve":
            return self._result("blocked", plan=plan, blockers=("explicit_approval_required",))
        if self.clock() >= deadline:
            return self._result("review_required", plan=plan, blockers=("approval_expired",))
        lock = _target_lock(plan)
        if not lock.acquire(blocking=False):
            return self._result("review_required", plan=plan, blockers=("operation_in_progress",))
        try:
            return self._execute(plan, basis, deadline)
        finally:
            lock.release()

    def _execute(
        self, plan: TopicPlan, basis: str, deadline: float,
    ) -> dict:
        try:
            fresh = self.backend.read()
            fresh_plan = plan_catalog_actions(fresh.snapshot, self.action)
            fresh_blockers = (*fresh_plan.blockers, *fresh.blockers, *self.backend.admission_blockers(fresh))
            if self.clock() >= deadline:
                return self._result("review_required", plan=fresh_plan, blockers=("approval_expired",))
            if fresh.fingerprint() != basis or fresh_plan != plan or fresh_blockers:
                return self._result(
                    "review_required", plan=fresh_plan,
                    blockers=tuple(dict.fromkeys(("evidence_changed", *fresh_blockers))),
                )
            if not plan.delta:
                topics, verified = _reconcile(fresh, fresh, plan)
                if not verified or any(item["status"] == "unverified" for item in topics):
                    return self._result("review_required", plan=plan, blockers=("evidence_changed",))
                return self._result("already_correct", plan=plan, completed=not plan.skips, topics=topics)
            payload = build_state_payload(fresh, plan)
            final_blockers = self.backend.admission_blockers(fresh)
            if final_blockers or self.clock() >= deadline:
                return self._result(
                    "review_required", plan=plan,
                    blockers=tuple(final_blockers) or ("approval_expired",),
                )
        except Exception:
            return self._result("blocked", plan=plan, blockers=("pre_dispatch_check_failed",))
        # An error after entering submit is potentially applied, even on timeout.
        acknowledged = False
        try:
            self.backend.submit_once(plan.target.agent_id, payload)
            acknowledged = True
        except (Exception, KeyboardInterrupt):
            pass
        try:
            after = self.backend.read()
            topics, scope_verified = _reconcile(fresh, after, plan)
            scope_verified = scope_verified and not self.backend.admission_blockers(after)
        except (Exception, KeyboardInterrupt):
            return self._result(
                "unverified", plan=plan, write_status="submitted",
                blockers=("readback_failed", "fresh_approval_required"),
                topics=[{
                    "componentId": identity, "state": "Unknown",
                    "status": "unverified", "reason": "readback_unavailable",
                } for identity in fresh.snapshot.evidence.selected_member_ids],
            )
        verified = scope_verified and all(
            item["status"] in ("observed_desired", "already_correct", "protected")
            for item in topics
        )
        if not acknowledged:
            return self._result(
                "unverified", plan=plan, write_status="submitted", topics=topics,
                blockers=("submission_outcome_uncertain", "fresh_approval_required"),
            )
        if verified:
            for item in topics:
                if item["status"] == "observed_desired":
                    item["status"] = "changed"
        return self._result(
            ("completed_with_protections" if plan.skips else "completed") if verified else "partial",
            plan=plan, write_status="submitted", topics=topics,
            completed=verified and not plan.skips,
            blockers=() if verified else ("verification_incomplete", "fresh_approval_required"),
        )

    def _result(
        self, status: str, *, plan: TopicPlan | None = None,
        blockers: tuple[str, ...] = (), write_status: str = "not_attempted",
        completed: bool = False, topics: list[dict] | None = None,
    ) -> dict:
        return {
            "contractVersion": 1, "contractStatus": "provisional",
            "status": status, "completed": completed, "writeStatus": write_status,
            "blockers": list(dict.fromkeys(blockers)), "topics": topics or [],
            "plan": public_plan(plan) if plan else None,
            "callerContext": deepcopy(self.caller_context),
            "message": {
                "blocked": "Topic actions are blocked. No changes were attempted.",
                "cancelled": "Cancelled. No changes were attempted.",
                "denied": "Not approved. No changes were attempted.",
                "review_required": "The evidence changed or approval expired. Review and approve a fresh plan.",
                "already_correct": "The eligible topics are already in the requested state. No changes were needed.",
                "completed": "The requested topic states were verified. Nothing was published.",
                "completed_with_protections": "Eligible topic changes were verified; protected topics were left unchanged.",
                "partial": "Not every result could be verified. No changes will be replayed automatically.",
                "unverified": "The submission outcome is uncertain. Observations are not proof that this request made the changes.",
            }[status],
        }
