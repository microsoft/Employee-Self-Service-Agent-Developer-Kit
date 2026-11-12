# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Fresh review, single-attempt execution and conservative reconciliation.

The controller is transport-independent. The native adapter verifies the selected
target and exact source-inventory scope; service authorization remains native.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import time
import threading
from typing import Callable, Protocol

from requests import RequestException

from agentbuilder import AgentBuilderError, AgentBuilderHTTPError
from topic_actions_catalog import CatalogSnapshot, plan_catalog_actions
from topic_actions_components import normalize_state
from topic_actions_discovery import _identity
from topic_actions_planning import TopicPlan, _digest
from topic_actions_presentation import result_text, review_text


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
        parent_id = component.get("parentBotId")
        # Native bot settings can omit their parent; they are never submitted.
        if parent_id is not None or component.get("$kind") != "BotSettingsComponent":
            if _identity(parent_id) != plan.target.agent_id:
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


def public_plan(plan: TopicPlan, evidence: OperationEvidence | None = None) -> dict:
    def changes(items):
        return [
            {"componentId": item.component_id, "before": item.before, "after": item.after}
            for item in items
        ]

    result = {
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
        "executionPolicy": plan.execution_policy,
        "warnings": list(plan.warnings),
        "members": [
            {"setKey": key, "schemaName": schema, "componentId": identity}
            for key, schema, identity in plan.members
        ],
    }
    if evidence is not None:
        result["account"] = evidence.account_id
        result["currentStates"] = [
            {"componentId": topic.component_id, "state": topic.state}
            for topic in evidence.snapshot.evidence.topics
            if topic.component_id in evidence.snapshot.evidence.selected_member_ids
        ]
    return result


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


def _without_server_generated_fields(value, *, normalize_structured_records: bool = True):
    if isinstance(value, dict):
        parsed_record = (
            normalize_structured_records
            and value.get("$kind") == "ValueExpression"
            and isinstance(value.get("expressionText"), str)
            and bool(value["expressionText"].strip())
        )
        return {
            key: _without_server_generated_fields(
                child, normalize_structured_records=normalize_structured_records,
            )
            for key, child in value.items()
            if key not in {"diagnostics", "structuredCondition"}
            and not (parsed_record and key == "structuredRecordExpression")
        }
    if isinstance(value, list):
        return [
            _without_server_generated_fields(
                child, normalize_structured_records=normalize_structured_records,
            ) for child in value
        ]
    return value


def _preservation_content(
    component: dict, *, state_change: bool, normalize_structured_records: bool = True,
) -> dict:
    """Normalize readback only, not the reviewed evidence or submitted payload."""
    content = deepcopy(component)
    if content.get("$kind") == "DialogComponent" and "dialog" in content:
        content["dialog"] = _without_server_generated_fields(
            content["dialog"], normalize_structured_records=normalize_structured_records,
        )
    if state_change:
        for key in ("state", "status", "version"):
            content.pop(key, None)
        audit = content.get("auditInfo")
        if isinstance(audit, dict):
            audit.pop("modifiedTimeUtc", None)
            if not audit:
                content.pop("auditInfo")
    return content


def _reconcile(before: OperationEvidence, after: OperationEvidence, plan: TopicPlan) -> tuple[list[dict], bool]:
    """Observed desired state after an uncertain submission is not attribution."""
    before_map = _component_map(before.body)
    after_map = _component_map(after.body)
    delta = {item.component_id: item for item in plan.delta}
    containment = set(before_map) == set(after_map)
    for identity, original in before_map.items():
        current = after_map.get(identity)
        if current is None:
            containment = False
            continue
        if _preservation_content(current, state_change=identity in delta) != _preservation_content(
            original, state_change=identity in delta,
        ):
            containment = False
    stable_authority = (
        before.account_id == after.account_id
        and before.snapshot.catalog_revision == after.snapshot.catalog_revision
        and before.snapshot.source_inventory_only == after.snapshot.source_inventory_only
        and before.snapshot.warnings == after.snapshot.warnings
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
    """One review and at most one dispatch. No saved approval or replay."""

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

    def run(
        self, confirm: Callable[[dict], str], *, preview: bool = False,
        review_only: bool = False, approved_binding: str | None = None,
        approval_deadline: float | None = None,
    ) -> dict:
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
                "blocked", plan=plan, evidence=evidence,
                blockers=blockers or (f"plan_{plan.outcome}",),
            )
        if preview:
            return self._result("preview", plan=plan, evidence=evidence)
        if not plan.delta and approved_binding is None:
            return self._execute(plan, evidence.fingerprint(), self.clock() + 300)
        # Freeze the basis before handing the public copy to the interaction.
        basis = evidence.fingerprint()
        deadline = self.clock() + 300
        if approval_deadline is not None:
            deadline = min(deadline, approval_deadline)
        try:
            review = {**public_plan(plan, evidence), "account": evidence.account_id}
            review["userMessage"] = review_text(review)
            binding = _digest({"evidence": basis, "review": review})
            if review_only:
                result = self._result("review_ready", plan=plan, evidence=evidence)
                result.update(review=review, _reviewBinding=binding, userMessage=review["userMessage"])
                return result
            if approved_binding is not None and approved_binding != binding:
                return self._result("review_required", plan=plan, blockers=("evidence_changed",))
            decision = confirm(review)
        except TimeoutError:
            return self._result("review_required", plan=plan, blockers=("approval_expired",))
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
        submission_reason = "submission_outcome_uncertain"
        submission_http_status = None
        try:
            self.backend.submit_once(plan.target.agent_id, payload)
            acknowledged = True
        except AgentBuilderHTTPError as error:
            submission_http_status = error.status_code
            submission_reason = {
                400: "write_request_rejected",
                401: "write_authentication_failed", 403: "write_access_denied",
                404: "write_target_not_found",
                409: "write_conflict", 412: "write_conflict",
                413: "write_request_too_large", 429: "write_throttled",
            }.get(
                error.status_code,
                "write_service_failed" if 500 <= error.status_code < 600 else "write_http_error",
            )
        except RequestException:
            submission_reason = "write_transport_failed"
        except AgentBuilderError:
            submission_reason = "write_acknowledgement_unverified"
        except ValueError:
            submission_reason = "submission_validation_failed"
        except (Exception, KeyboardInterrupt):
            pass
        try:
            after = self.backend.read()
            topics, scope_verified = _reconcile(fresh, after, plan)
            scope_verified = scope_verified and not self.backend.admission_blockers(after)
        except (Exception, KeyboardInterrupt):
            return self._result(
                "unverified", plan=plan, write_status="submitted",
                submission_http_status=submission_http_status,
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
                submission_http_status=submission_http_status,
                blockers=tuple(dict.fromkeys((
                    submission_reason, "submission_outcome_uncertain", "fresh_approval_required",
                ))),
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
        submission_http_status: int | None = None,
        evidence: OperationEvidence | None = None,
    ) -> dict:
        partial_message = "Not every result could be verified. No changes will be replayed automatically."
        if status == "partial" and topics and all(
            item["status"] in ("observed_desired", "already_correct", "protected")
            for item in topics
        ):
            partial_message = (
                "Readback shows the eligible topics in their requested states, but content or scope "
                "preservation could not be verified. No changes will be replayed automatically."
            )
        result = {
            "contractVersion": 1, "contractStatus": "provisional",
            "status": status, "completed": completed, "writeStatus": write_status,
            "submissionHttpStatus": submission_http_status,
            "blockers": list(dict.fromkeys(blockers)), "topics": topics or [],
            "warnings": list(plan.warnings) if plan else [],
            "plan": public_plan(plan, evidence) if plan else None,
            "callerContext": deepcopy(self.caller_context),
            "message": {
                "blocked": "Topic actions are blocked. No changes were attempted.",
                "preview": "Preview only. No changes were attempted and no executable approval was collected.",
                "review_ready": "Review ready. No approval has been collected and no changes were attempted.",
                "cancelled": "Cancelled. No changes were attempted.",
                "denied": "Not approved. No changes were attempted.",
                "review_required": "The evidence changed or approval expired. Review and approve a fresh plan.",
                "already_correct": "The eligible topics are already in the requested state. No changes were needed.",
                "completed": "The requested topic states were verified. No publish operation was requested.",
                "completed_with_protections": "Eligible topic changes were verified; protected topics were left unchanged.",
                "partial": partial_message,
                "unverified": "The submission outcome is uncertain. Observations are not proof that this request made the changes.",
            }[status],
        }
        result["userMessage"] = result_text(result)
        return result
