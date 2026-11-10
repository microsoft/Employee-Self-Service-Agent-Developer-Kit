# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Native adapter. Read-only until independently verified release admission exists."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy

from agentbuilder import AgentBuilderClient, environment_id_from_host
from setup_existing_da import validate_existing_dev_connection
from topic_actions_catalog import Catalog, snapshot_from_response
from topic_actions_discovery import DiscoveryTarget, _identity, _target
from topic_actions_execution import OperationEvidence


@dataclass
class NativeActionBackend:
    client: AgentBuilderClient
    target: DiscoveryTarget
    selected_keys: tuple[str, ...]
    catalog: Catalog
    account_id: str

    def read(self) -> OperationEvidence:
        target = _target(self.target)
        if (
            _identity(self.client.tenant_id) != target.tenant_id
            or environment_id_from_host(self.client.host, self.client.ring) != target.environment_id
            or not self.account_id
        ):
            raise ValueError("Client identity is not bound to the selected target.")
        validate_existing_dev_connection(
            self.client, environment_id=target.environment_id,
            agent_id=target.agent_id, allow_missing_schema=True,
        )
        body = self.client.fetch_components(target.agent_id)
        snapshot = snapshot_from_response(self.catalog, target, self.selected_keys, body)
        return OperationEvidence(snapshot, self.account_id, deepcopy(body))

    def admission_blockers(self, evidence: OperationEvidence | None) -> tuple[str, ...]:
        # No local flag, catalog label, OAuth scope or maker approval substitutes
        # for centrally controlled admission and platform qualification.
        return (
            "release_control_unavailable",
            "effective_write_permission_unverified",
            "native_stale_write_protection_unqualified",
            "native_batch_behavior_unqualified",
            "native_draft_published_effects_unqualified",
        )

    def submit_once(self, target_agent_id: str, payload: dict) -> None:
        # Fail independently of the controller, including direct Python calls.
        if self.admission_blockers(None):
            raise ValueError("Native topic writes are not admitted.")
        self.client.update_components_once(target_agent_id, payload)
