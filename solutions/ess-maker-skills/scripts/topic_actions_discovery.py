# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""M3 synthetic contracts and an opt-in interim flat-catalog read boundary.

Sets currently represent full Workday, ServiceNow HR and ServiceNow IT
inventories. Keys and source fields are provisional, not a package contract.
TODO(M3 production): bind owner-provided exact membership and protection evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from agentbuilder import AgentBuilderClient
    from topic_actions_flat_discovery import FlatCatalog, FlatDiscoveryResult


class DiscoveryError(ValueError):
    """Static discovery failure without source contents."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class DiscoveryTarget:
    tenant_id: str
    environment_id: str
    agent_id: str


@dataclass(frozen=True)
class SourceBinding:
    package_id: str | None
    package_version: str | None
    revision: str | None
    current: bool | None


@dataclass(frozen=True)
class TopicSet:
    key: str
    member_ids: tuple[str, ...]
    membership_complete: bool | None
    source: SourceBinding | None
    description: str | None = None
    description_provenance: str | None = None


@dataclass(frozen=True)
class TopicEvidence:
    component_id: str
    required: bool | None
    state: str = "Unknown"


@dataclass(frozen=True)
class DiscoverySnapshot:
    target: DiscoveryTarget
    selected_keys: tuple[str, ...]
    sets: tuple[TopicSet, ...]
    topics: tuple[TopicEvidence, ...]
    selected_member_ids: tuple[str, ...]
    coverage_complete: bool | None
    blockers: tuple[str, ...]

    @property
    def evidence_kind(self) -> str:
        return "synthetic"

    @property
    def live_actions_available(self) -> bool:
        return False

    def memberships(self, component_id: str) -> tuple[str, ...]:
        """Return exact reverse membership, not a static shared flag."""
        identity = _identity(component_id)
        return tuple(item.key for item in self.sets if identity in item.member_ids)


def _fail(reason: str) -> None:
    raise DiscoveryError(reason, "Topic-set evidence could not be established. No changes attempted.")


def _identity(value: str) -> str:
    value = _key(value)
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return value


def _key(value: str) -> str:
    if (
        not isinstance(value, str) or not value or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        _fail("invalid_identity")
    return value


def _target(value: DiscoveryTarget) -> DiscoveryTarget:
    try:
        if not isinstance(value, DiscoveryTarget):
            raise ValueError
        return DiscoveryTarget(*(
            str(uuid.UUID(item))
            for item in (value.tenant_id, value.environment_id, value.agent_id)
        ))
    except (ValueError, TypeError, AttributeError):
        _fail("invalid_target")


def _optional_boolean(value: bool | None) -> None:
    if value is not None and type(value) is not bool:
        _fail("invalid_evidence")


def build_provisional_snapshot(
    target: DiscoveryTarget,
    selected_keys: tuple[str, ...],
    sets: tuple[TopicSet, ...],
    topics: tuple[TopicEvidence, ...],
    *,
    coverage_complete: bool | None,
) -> DiscoverySnapshot:
    """Validate synthetic adapter inputs without discovering a tenant.

    This pure boundary always labels its result synthetic and cannot make live
    actions available, even when every supplied evidence field is complete.
    Missing evidence is retained as blockers; malformed identities fail closed.
    Set keys are opaque source identifiers, not a fixed list of ISV names.
    Descriptions are optional and are never used to infer member identities.
    """
    target = _target(target)
    if (
        not isinstance(selected_keys, tuple) or not selected_keys
        or any(
            not isinstance(key, str) or not key or key != key.strip()
            or any(ord(char) < 32 or ord(char) == 127 for char in key)
            for key in selected_keys
        )
        or len(set(selected_keys)) != len(selected_keys)
    ):
        _fail("invalid_selection")
    if not isinstance(sets, tuple) or not isinstance(topics, tuple):
        _fail("invalid_evidence")
    _optional_boolean(coverage_complete)
    normalized_sets = []
    seen_keys = set()
    for item in sets:
        if not isinstance(item, TopicSet):
            _fail("invalid_set")
        _key(item.key)
        if item.key in seen_keys:
            _fail("ambiguous_set")
        seen_keys.add(item.key)
        if not isinstance(item.member_ids, tuple):
            _fail("invalid_evidence")
        members = tuple(_identity(identity) for identity in item.member_ids)
        if len(set(members)) != len(members):
            _fail("ambiguous_membership")
        _optional_boolean(item.membership_complete)
        if item.source is not None:
            if not isinstance(item.source, SourceBinding):
                _fail("invalid_source")
            _optional_boolean(item.source.current)
            for field in (item.source.package_id, item.source.package_version, item.source.revision):
                if field is not None:
                    _identity(field)
        normalized_sets.append(TopicSet(
            item.key, members, item.membership_complete, item.source,
            item.description, item.description_provenance,
        ))
    normalized_topics = []
    seen_ids = set()
    for item in topics:
        if not isinstance(item, TopicEvidence):
            _fail("invalid_evidence")
        identity = _identity(item.component_id)
        if identity in seen_ids:
            _fail("ambiguous_topic")
        seen_ids.add(identity)
        _optional_boolean(item.required)
        if not isinstance(item.state, str) or item.state not in ("On", "Off", "Unknown"):
            _fail("invalid_state")
        normalized_topics.append(TopicEvidence(identity, item.required, item.state))
    by_key = {item.key: item for item in normalized_sets}
    by_id = {item.component_id: item for item in normalized_topics}
    blockers = []
    union = []
    if coverage_complete is not True:
        blockers.append("incomplete_coverage")
    for key in selected_keys:
        item = by_key.get(key)
        if item is None:
            blockers.append(f"missing_set:{key}")
            continue
        for identity in item.member_ids:
            if identity not in union:
                union.append(identity)
        if not item.member_ids:
            blockers.append(f"empty_membership:{key}")
    for item in normalized_sets:
        if item.key not in selected_keys and not set(item.member_ids).intersection(union):
            continue
        if item.membership_complete is not True:
            blockers.append(f"incomplete_membership:{item.key}")
        if item.source is None or any(
            field is None
            for field in (item.source.package_id, item.source.package_version, item.source.revision)
        ):
            blockers.append(f"missing_source:{item.key}")
        elif item.source.current is not True:
            blockers.append(f"stale_or_unverified_source:{item.key}")
        for identity in item.member_ids:
            evidence = by_id.get(identity)
            if evidence is None:
                blockers.append(f"missing_topic:{identity}")
            elif identity in union and evidence.required is None:
                blockers.append(f"unknown_protection:{identity}")
    return DiscoverySnapshot(
        target, selected_keys, tuple(normalized_sets), tuple(normalized_topics),
        tuple(union), coverage_complete, tuple(dict.fromkeys(blockers)),
    )


def discover_topic_sets(
    target: DiscoveryTarget, selected_keys: tuple[str, ...] | None = None,
    *, client: AgentBuilderClient | None = None, catalog: FlatCatalog | None = None,
) -> FlatDiscoveryResult:
    """Opt-in interim source; missing dependencies never use synthetic fallback."""
    if client is None or catalog is None:
        _fail("implementation_pending")
    from topic_actions_flat_discovery import discover_flat_topic_sets

    return discover_flat_topic_sets(client, target, catalog, selected_keys)
