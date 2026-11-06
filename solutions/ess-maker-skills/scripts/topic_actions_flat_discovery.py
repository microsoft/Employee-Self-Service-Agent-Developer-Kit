# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only comparison of interim flat definitions with one native Dev agent.

The catalog is supplied locally, not bundled from a private repository. Exact
schema keys locate installed IDs; source-template IDs and display names never
do. Presence is not deployed-package, protection, or mutation authority.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path

import requests

from agentbuilder import (
    AgentBuilderClient,
    AgentBuilderError,
    AgentBuilderHTTPError,
    environment_id_from_host,
)
from setup_existing_da import (
    ExistingDASetupError,
    _validate_changeset_identity,
    validate_existing_dev_connection,
)
from topic_actions_discovery import (
    DiscoveryError,
    DiscoveryTarget,
    _fail,
    _identity,
    _key,
    _optional_boolean,
    _target,
)


@dataclass(frozen=True)
class FlatMember:
    schema_name: str
    required: bool | None = None


@dataclass(frozen=True)
class FlatSet:
    key: str
    agent_schema_name: str
    members: tuple[FlatMember, ...]
    source_revision: str
    source_path: str
    template_version: str | None


@dataclass(frozen=True)
class FlatCatalog:
    sets: tuple[FlatSet, ...]
    revision: str


@dataclass(frozen=True)
class InventoryTopic:
    component_id: str
    schema_name: str
    state: str


@dataclass(frozen=True)
class NativeInventory:
    target: DiscoveryTarget
    agent_schema_name: str
    topics: tuple[InventoryTopic, ...]
    revision: str | None


@dataclass(frozen=True)
class MemberMatch:
    schema_name: str
    component_id: str | None
    state: str
    required: bool | None
    reason: str


@dataclass(frozen=True)
class SetAvailability:
    definition: FlatSet
    status: str
    members: tuple[MemberMatch, ...]


@dataclass(frozen=True)
class FlatDiscoveryResult:
    target: DiscoveryTarget
    sets: tuple[SetAvailability, ...]
    selected_keys: tuple[str, ...]
    selected_member_ids: tuple[str, ...]
    catalog_revision: str
    inventory_revision: str | None
    blockers: tuple[str, ...]
    evidence_kind: str = "provided_inventory"

    @property
    def live_actions_available(self) -> bool:
        return False


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("ambiguous_catalog")
        result[key] = value
    return result


def load_flat_catalog(path: str | Path) -> FlatCatalog:
    """Read the explicitly versioned interim format; fail on unknown versions."""
    try:
        contents = Path(path).read_bytes()
        document = json.loads(contents, object_pairs_hook=_unique_object)
    except (OSError, ValueError, TypeError) as error:
        if isinstance(error, DiscoveryError):
            raise
        _fail("catalog_unreadable")
    if not isinstance(document, dict):
        _fail("invalid_catalog")
    if (
        document.get("format") != "adk-local-repository-topic-set-draft"
        or type(document.get("formatVersion")) is not int
        or document["formatVersion"] not in (1, 2)
    ):
        _fail("unsupported_catalog_format")
    source = document.get("source")
    revision = _key(source.get("commit")) if isinstance(source, dict) else None
    rows = document.get("sets")
    if revision is None or not isinstance(rows, list) or not rows:
        _fail("invalid_catalog")
    definitions = []
    keys = set()
    for row in rows:
        if not isinstance(row, dict):
            _fail("invalid_catalog")
        key = _key(row.get("key"))
        if key in keys:
            _fail("ambiguous_set")
        keys.add(key)
        if document["formatVersion"] == 2:
            variants = row.get("sourceVariants")
            if (
                not isinstance(variants, list) or not variants
                or "members" in row or "agentSchemaName" in row
            ):
                _fail("invalid_catalog")
        else:
            if "sourceVariants" in row:
                _fail("unsupported_catalog_format")
            variants = [row]
        for variant in variants:
            if not isinstance(variant, dict):
                _fail("invalid_catalog")
            schema = _key(variant.get("agentSchemaName"))
            if variant.get("membershipCompleteWithinReviewedTemplate") is not True:
                _fail("incomplete_catalog_membership")
            raw_members = variant.get("members")
            if not isinstance(raw_members, list) or not raw_members:
                _fail("empty_membership")
            members = []
            for member in raw_members:
                if not isinstance(member, dict):
                    _fail("invalid_catalog")
                member_schema = _key(member.get("schemaName"))
                _optional_boolean(member.get("required"))
                members.append(FlatMember(member_schema, member.get("required")))
            version = variant.get("templatePackageVersion")
            definitions.append(FlatSet(
                key, schema, tuple(members), revision,
                _key(variant.get("sourcePath")), version,
            ))
    catalog = FlatCatalog(tuple(definitions), sha256(contents).hexdigest())
    _validate_catalog(catalog)
    return catalog


def inventory_from_response(target: DiscoveryTarget, body: dict) -> NativeInventory:
    """Project the existing native fetch contract; never retain full components."""
    target = _target(target)
    if not isinstance(body, dict):
        _fail("invalid_inventory")
    try:
        schema = _validate_changeset_identity(body, target.agent_id)
    except (ExistingDASetupError, ValueError, TypeError):
        _fail("target_mismatch")
    changes = body.get("botComponentChanges")
    if not isinstance(changes, list):
        _fail("invalid_inventory")
    topics = []
    identities = set()
    for row in changes:
        if not isinstance(row, dict) or row.get("$kind") != "BotComponentInsert":
            _fail("invalid_inventory")
        component = row.get("component")
        if not isinstance(component, dict) or not isinstance(component.get("$kind"), str):
            _fail("invalid_inventory")
        identity = _identity(component.get("id"))
        if identity in identities:
            _fail("ambiguous_inventory")
        identities.add(identity)
        parent = component.get("parentBotId")
        if parent is not None and _identity(parent) != target.agent_id:
            _fail("target_mismatch")
        if component["$kind"] != "DialogComponent":
            continue
        topic_schema = _key(component.get("schemaName"))
        pair = (component.get("state"), component.get("status"))
        state = {
            ("Active", "Active"): "On", ("Inactive", "Inactive"): "Off",
        }.get(pair, "Unknown") if all(isinstance(value, str) for value in pair) else "Unknown"
        topics.append(InventoryTopic(identity, topic_schema, state))
    token = body.get("changeToken")
    if token is not None and (not isinstance(token, str) or not token.strip()):
        _fail("invalid_inventory")
    revision = sha256(token.encode()).hexdigest() if token else None
    return NativeInventory(target, schema, tuple(topics), revision)


def _selection(selected_keys: tuple[str, ...] | None) -> tuple[str, ...]:
    if selected_keys is not None and (
        not isinstance(selected_keys, tuple) or not selected_keys
        or any(_key(key) != key for key in selected_keys)
        or len(set(selected_keys)) != len(selected_keys)
    ):
        _fail("invalid_selection")
    return selected_keys or ()


def _validate_catalog(catalog: FlatCatalog) -> None:
    if not isinstance(catalog, FlatCatalog) or not isinstance(catalog.sets, tuple) or not catalog.sets:
        _fail("invalid_catalog")
    _key(catalog.revision)
    keys = set()
    for definition in catalog.sets:
        if not isinstance(definition, FlatSet):
            _fail("invalid_catalog")
        for value in (
            definition.key, definition.agent_schema_name,
            definition.source_revision, definition.source_path,
        ):
            _key(value)
        if definition.template_version is not None:
            _key(definition.template_version)
        binding = (definition.key, definition.agent_schema_name)
        if binding in keys:
            _fail("ambiguous_set")
        keys.add(binding)
        if not isinstance(definition.members, tuple) or not definition.members:
            _fail("empty_membership")
        schemas = set()
        for member in definition.members:
            if not isinstance(member, FlatMember):
                _fail("invalid_catalog")
            _key(member.schema_name)
            _optional_boolean(member.required)
            if member.schema_name in schemas:
                _fail("ambiguous_membership")
            schemas.add(member.schema_name)


def compare_flat_catalog(
    catalog: FlatCatalog,
    inventory: NativeInventory,
    selected_keys: tuple[str, ...] | None = None,
) -> FlatDiscoveryResult:
    """Compare exact keys without selecting all sets or narrowing partial scope."""
    _validate_catalog(catalog)
    if not isinstance(inventory, NativeInventory) or not isinstance(inventory.topics, tuple):
        _fail("invalid_inventory")
    target = _target(inventory.target)
    _key(inventory.agent_schema_name)
    selected = _selection(selected_keys)
    by_schema = {}
    identities = set()
    for topic in inventory.topics:
        if not isinstance(topic, InventoryTopic):
            _fail("invalid_inventory")
        identity = _identity(topic.component_id)
        _key(topic.schema_name)
        if identity in identities:
            _fail("ambiguous_inventory")
        identities.add(identity)
        if topic.state not in ("On", "Off", "Unknown"):
            _fail("invalid_state")
        topic = replace(topic, component_id=identity)
        by_schema.setdefault(topic.schema_name, []).append(topic)
    results = []
    union = []
    blockers = [
        "interim_definition_contract",
        "deployed_package_binding_unverified",
        "protection_coverage_unverified",
    ]
    if inventory.revision is None:
        blockers.append("inventory_freshness_unverified")
    by_key = {}
    for definition in catalog.sets:
        by_key.setdefault(definition.key, []).append(definition)
    for variants in by_key.values():
        # A logical set has one explicit inventory per exact agent schema.
        # Never union inventories across template/package families.
        definition = next(
            (item for item in variants if item.agent_schema_name == inventory.agent_schema_name),
            variants[0],
        )
        matches = []
        applicable = definition.agent_schema_name == inventory.agent_schema_name
        for member in definition.members:
            candidates = by_schema.get(member.schema_name, []) if applicable else []
            reason = "not_applicable" if not applicable else (
                "missing_member" if not candidates else (
                    "ambiguous_member" if len(candidates) != 1 else "exact_schema_match"
                )
            )
            topic = candidates[0] if reason == "exact_schema_match" else None
            matches.append(MemberMatch(
                member.schema_name, topic.component_id if topic else None,
                topic.state if topic else "Unknown", member.required, reason,
            ))
        resolved = [item for item in matches if item.component_id is not None]
        status = "not_applicable" if not applicable else (
            "ambiguous" if any(item.reason == "ambiguous_member" for item in matches) else (
                "present" if len(resolved) == len(matches) else (
                    "partial" if resolved else "absent"
                )
            )
        )
        results.append(SetAvailability(definition, status, tuple(matches)))
        if definition.key in selected:
            if status != "present":
                blockers.append(f"set_{status}:{definition.key}")
            for item in resolved:
                if item.component_id not in union:
                    union.append(item.component_id)
                if item.required is None:
                    blockers.append(f"unknown_protection:{item.component_id}")
                if item.state == "Unknown":
                    blockers.append(f"unknown_state:{item.component_id}")
    known = {item.definition.key for item in results}
    blockers.extend(f"missing_set:{key}" for key in selected if key not in known)
    return FlatDiscoveryResult(
        target, tuple(results), selected, tuple(union),
        catalog.revision, inventory.revision, tuple(dict.fromkeys(blockers)),
    )


def discover_flat_topic_sets(
    client: AgentBuilderClient,
    target: DiscoveryTarget,
    catalog: FlatCatalog,
    selected_keys: tuple[str, ...] | None = None,
) -> FlatDiscoveryResult:
    """Verify client binding and native Dev identity before one component fetch."""
    target = _target(target)
    _selection(selected_keys)
    _validate_catalog(catalog)
    try:
        if (
            _identity(client.tenant_id) != target.tenant_id
            or environment_id_from_host(client.host, client.ring) != target.environment_id
        ):
            _fail("client_target_mismatch")
        validate_existing_dev_connection(
            client, environment_id=target.environment_id,
            agent_id=target.agent_id, allow_missing_schema=True,
        )
        inventory = inventory_from_response(target, client.fetch_components(target.agent_id))
    except DiscoveryError:
        raise
    except AgentBuilderHTTPError as error:
        _fail({
            401: "authentication_failed", 403: "access_denied",
            404: "agent_not_found", 429: "throttled",
        }.get(error.status_code, "read_failed"))
    except requests.Timeout:
        _fail("read_timeout")
    except ExistingDASetupError:
        _fail("target_unverified")
    except (AgentBuilderError, requests.RequestException, ValueError, AttributeError, KeyError):
        _fail("read_failed")
    return replace(
        compare_flat_catalog(catalog, inventory, selected_keys),
        evidence_kind="native_read",
    )
