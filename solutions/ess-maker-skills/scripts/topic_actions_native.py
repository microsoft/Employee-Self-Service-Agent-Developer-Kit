# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Source-inventory actions; service authorization is not preflighted."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from copy import deepcopy
import time

from agentbuilder import AgentBuilderClient, environment_id_from_host
from topic_actions_client import TopicActionsClient, verify_native_target
from topic_actions_catalog import Catalog, plan_catalog_actions, snapshot_from_response
from topic_actions_discovery import DiscoveryTarget, _identity, _target
from topic_actions_execution import OperationEvidence, build_state_payload
from topic_actions_state import TopicStateStore


@dataclass
class NativeActionBackend:
    client: AgentBuilderClient
    target: DiscoveryTarget
    selected_keys: tuple[str, ...]
    catalog: Catalog
    account_id: str
    components: TopicActionsClient
    state_store: TopicStateStore | None = field(default=None, repr=False)
    restoring: bool = False
    _last_evidence: OperationEvidence | None = field(default=None, init=False, repr=False)
    _last_read_at: float = field(default=0, init=False, repr=False)
    _submitted: bool = field(default=False, init=False, repr=False)

    def _check_target(self) -> DiscoveryTarget:
        target = _target(self.target)
        if (
            _identity(self.client.tenant_id) != target.tenant_id
            or environment_id_from_host(self.client.host, self.client.ring) != target.environment_id
            or not self.account_id
            or not self.components.single_attempt
            or _identity(self.components.tenant_id) != target.tenant_id
            or _identity(self.components.environment_id) != target.environment_id
            or _identity(self.components.bot_id) != target.agent_id
            or self.components.host != self.client.host
            or self.components.ring != self.client.ring
            or str(self.components.signed_in_username or "").casefold() != self.account_id.casefold()
        ):
            raise ValueError("Client identity is not bound to the selected target.")
        return target

    def read(self) -> OperationEvidence:
        previous = self._last_evidence
        self._last_evidence = None
        target = self._check_target()
        verify_native_target(self.client, target)
        body = self.components.read_components()
        snapshot = snapshot_from_response(
            self.catalog, target, self.selected_keys, body, source_inventory_only=True,
        )
        evidence = OperationEvidence(snapshot, self.account_id, deepcopy(body))
        if self.restoring:
            if self.state_store is None:
                raise ValueError("An original baseline is required.")
            if self._submitted and previous is not None:
                # Readback checks the approved restore, not its in-progress journal.
                snapshot = replace(
                    snapshot, restore_states=previous.snapshot.restore_states,
                    restore_revision=previous.snapshot.restore_revision,
                    warnings=tuple(dict.fromkeys((*snapshot.warnings, *previous.snapshot.warnings))),
                )
            else:
                snapshot = self.state_store.restore_snapshot(evidence)
            evidence = OperationEvidence(snapshot, self.account_id, deepcopy(body))
        self._last_evidence = evidence
        self._last_read_at = time.monotonic()
        return self._last_evidence

    def admission_blockers(self, evidence: OperationEvidence | None) -> tuple[str, ...]:
        try:
            target = self._check_target()
            if (
                evidence is None or evidence is not self._last_evidence
                or evidence.account_id != self.account_id
                or evidence.snapshot.evidence.target != target
                or evidence.snapshot.evidence.selected_keys != self.selected_keys
                or evidence.snapshot.catalog_revision != self.catalog.revision
                or evidence.snapshot.evidence_kind != "native_read"
                or not evidence.snapshot.source_inventory_only
            ):
                return ("native_evidence_required",)
            if time.monotonic() - self._last_read_at >= 300:
                return ("native_evidence_expired",)
            token = evidence.body.get("changeToken")
            if not isinstance(token, str) or not token.strip():
                return ("inventory_revision_unavailable",)
            return evidence.snapshot.evidence.blockers
        except (ValueError, AttributeError):
            return ("target_unverified",)

    def submit_once(self, target_agent_id: str, payload: dict) -> None:
        if self._submitted:
            raise ValueError("Native topic submission was already consumed.")
        self._submitted = True
        evidence = self._last_evidence
        if (
            self.admission_blockers(evidence)
            or _identity(target_agent_id) != _target(self.target).agent_id
        ):
            raise ValueError("Native topic writes are not admitted.")
        for action in (("restore",) if self.restoring else ("enable", "disable")):
            plan = plan_catalog_actions(evidence.snapshot, action)
            if (
                plan.delta and not plan.blockers
                and payload == build_state_payload(evidence, plan)
            ):
                break
        else:
            raise ValueError("The payload does not match the exact computed topic action.")
        self.components.submit_state_payload(payload)
