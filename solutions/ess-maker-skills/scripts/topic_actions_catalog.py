# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Proposed catalog adapter and computed whole-set planning.

Schema validity, catalog review and installed-package authority are separate.
Provided inventories exercise policy; they never establish native authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from topic_actions_components import normalize_state
from topic_actions_discovery import (
    DiscoveryError, DiscoverySnapshot, DiscoveryTarget, SourceBinding, TopicEvidence, TopicSet,
    _fail, _identity, _key, _target, build_provisional_snapshot,
)
from topic_actions_flat_discovery import (
    NativeInventory, _selection, _unique_object, inventory_from_response,
)


REFERENCE = Path(__file__).resolve().parents[1] / "src" / "reference" / "topic-actions"
SCHEMA_PATH = REFERENCE / "catalog.schema.json"
BUNDLED_CATALOG = REFERENCE / "catalog.provisional.json"


@dataclass(frozen=True)
class Catalog:
    revision: str
    _document: str = field(repr=False)

    def document(self) -> dict:
        return json.loads(self._document)


@dataclass(frozen=True)
class InstalledPackage:
    package_id: str
    version: str


@dataclass(frozen=True)
class CatalogSnapshot:
    evidence: DiscoverySnapshot
    catalog_revision: str
    inventory_revision: str | None
    members: tuple[tuple[str, str, str | None], ...]
    evidence_kind: str = "provided_inventory"


def parse_catalog(document: dict) -> Catalog:
    """Validate shapes and cross-references without upgrading provisional data."""
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _fail("catalog_schema_unavailable")
    if not Draft202012Validator(schema).is_valid(document):
        _fail("invalid_catalog")
    packages = {}
    for package in document["packages"]:
        key = package["key"]
        if key in packages:
            _fail("duplicate_package")
        packages[key] = package
        topics = {}
        for topic in package["topics"]:
            identity = topic["schemaName"].casefold()
            if identity in topics:
                _fail("duplicate_topic")
            topics[identity] = topic
            classification = topic["classification"]
            if (
                (classification == "required_system" and topic["required"] is not True)
                or (topic["required"] is True and classification != "required_system")
                or (classification in ("isv_topic", "other_non_isv") and topic["required"] is True)
            ):
                _fail("contradictory_classification")
        if len(set(name.casefold() for name in package["agentSchemaNames"])) != len(package["agentSchemaNames"]):
            _fail("duplicate_agent_schema")
        if package["requiredTopicCoverage"] == "complete" and (
            package["requiredTopicSource"] is None
            or any(topic["required"] is None or topic["classification"] == "unknown" for topic in topics.values())
        ):
            _fail("invalid_required_coverage")
    seen = set()
    for topic_set in document["sets"]:
        if topic_set["key"] in seen:
            _fail("duplicate_set")
        seen.add(topic_set["key"])
        variants = set()
        for variant in topic_set["sourceVariants"]:
            key = variant["packageKey"]
            if key not in packages:
                _fail("dangling_package")
            if key in variants:
                _fail("duplicate_variant")
            variants.add(key)
            registry = {topic["schemaName"]: topic for topic in packages[key]["topics"]}
            folded = [name.casefold() for name in variant["memberSchemaNames"]]
            if len(set(folded)) != len(folded):
                _fail("duplicate_member")
            for name in variant["memberSchemaNames"]:
                if name not in registry:
                    _fail("dangling_member")
                topic = registry[name]
                if topic["required"] is True or topic["classification"] in ("required_system", "other_non_isv"):
                    _fail("ineligible_member")
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return Catalog(hashlib.sha256(encoded.encode()).hexdigest(), encoded)


def load_catalog(path: str | Path = BUNDLED_CATALOG) -> Catalog:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
    except DiscoveryError:
        raise
    except (OSError, ValueError):
        _fail("catalog_unreadable")
    return parse_catalog(document)


def compare_catalog(
    catalog: Catalog,
    inventory: NativeInventory,
    selected_keys: tuple[str, ...],
    *,
    installed_packages: tuple[InstalledPackage, ...] = (),
    trusted_catalog_revision: str | None = None,
    dependency_coverage_verified: bool = False,
) -> CatalogSnapshot:
    """Resolve exact members and retain every blocker in the selected scope.

    Package records and trust arguments are adapter inputs, not customer
    assertions. The native adapter currently has no qualified package source.
    """
    selected = _selection(selected_keys)
    if not selected or type(catalog) is not Catalog or type(inventory) is not NativeInventory:
        _fail("invalid_selection")
    target = _target(inventory.target)
    if parse_catalog(catalog.document()) != catalog:
        _fail("invalid_catalog")
    if type(dependency_coverage_verified) is not bool:
        _fail("invalid_evidence")
    if not isinstance(installed_packages, tuple) or any(type(item) is not InstalledPackage for item in installed_packages):
        _fail("invalid_package_evidence")
    for item in installed_packages:
        _key(item.package_id)
        _key(item.version)
    if len({item.package_id for item in installed_packages}) != len(installed_packages):
        _fail("ambiguous_installed_package")
    by_schema = {}
    seen_ids = set()
    for topic in inventory.topics:
        _key(topic.component_id)
        _key(topic.schema_name)
        if topic.component_id in seen_ids:
            _fail("ambiguous_inventory")
        seen_ids.add(topic.component_id)
        if topic.state not in ("On", "Off", "Unknown"):
            _fail("invalid_state")
        by_schema.setdefault(topic.schema_name.casefold(), []).append(topic)
    document = catalog.document()
    packages = {item["key"]: item for item in document["packages"]}
    sets = []
    evidence = {}
    members = []
    reasons = []
    if trusted_catalog_revision != catalog.revision:
        reasons.append("catalog_release_untrusted")
    if document["authorityStatus"] != "owner_approved" or not document["source"]["approvalReference"]:
        reasons.append("catalog_review_pending")
    if not inventory.revision:
        reasons.append("inventory_revision_unavailable")
    relevant_packages = set()
    resolved_sets = {}
    for topic_set in document["sets"]:
        candidates = [
            variant for variant in topic_set["sourceVariants"]
            if inventory.agent_schema_name in packages[variant["packageKey"]]["agentSchemaNames"]
        ]
        bound = [
            variant for variant in candidates
            if InstalledPackage(
                packages[variant["packageKey"]]["packageId"],
                packages[variant["packageKey"]]["packageVersion"],
            ) in installed_packages
        ]
        # A unique source variant can be displayed without asserting installation.
        choices = bound or candidates
        if len(choices) != 1:
            if topic_set["key"] in selected:
                reasons.append(f"ambiguous_or_unsupported_set:{topic_set['key']}")
            resolved_sets[topic_set["key"]] = None
            continue
        variant = choices[0]
        package = packages[variant["packageKey"]]
        resolved_sets[topic_set["key"]] = (topic_set, variant, package)
    selected_schemas = set()
    selected_packages = set()
    for key in selected:
        match = resolved_sets.get(key)
        if match:
            selected_schemas.update(name.casefold() for name in match[1]["memberSchemaNames"])
            selected_packages.add(match[2]["key"])
        elif key not in resolved_sets:
            reasons.append(f"missing_set:{key}")
    for topic_set in document["sets"]:
        if resolved_sets.get(topic_set["key"]) is not None:
            continue
        if any(
            inventory.agent_schema_name in packages[variant["packageKey"]]["agentSchemaNames"]
            and (
                variant["packageKey"] in selected_packages
                or selected_schemas.intersection(name.casefold() for name in variant["memberSchemaNames"])
            )
            for variant in topic_set["sourceVariants"]
        ):
            reasons.append(f"outside_membership_ambiguous:{topic_set['key']}")
    for key, match in resolved_sets.items():
        if match is None:
            # Unknown alternate families cannot establish complete protection.
            continue
        topic_set, variant, package = match
        names = variant["memberSchemaNames"]
        uncertain_membership = (
            variant["membershipComplete"] is not True
            or variant["membershipStatus"] != "owner_approved"
        )
        potentially_shared = package["key"] in selected_packages or bool(
            selected_schemas.intersection(topic["schemaName"].casefold() for topic in package["topics"])
        )
        relevant = (
            key in selected
            or bool(selected_schemas.intersection(name.casefold() for name in names))
            or (uncertain_membership and potentially_shared)
        )
        if not relevant:
            continue
        relevant_packages.add(package["key"])
        registry = {topic["schemaName"]: topic for topic in package["topics"]}
        bound = InstalledPackage(package["packageId"], package["packageVersion"]) in installed_packages
        if not bound or not package["packageId"] or not package["packageVersion"]:
            reasons.append(f"installed_package_unverified:{package['key']}")
        if variant["membershipStatus"] != "owner_approved" or variant["membershipComplete"] is not True:
            reasons.append(f"membership_review_pending:{key}")
        ids = []
        for name in names:
            candidates = by_schema.get(name.casefold(), [])
            matches = candidates if len(candidates) == 1 and candidates[0].schema_name == name else []
            identity = matches[0].component_id if len(matches) == 1 else f"unresolved:{package['key']}:{name}"
            state = matches[0].state if len(matches) == 1 else "Unknown"
            definition = registry[name]
            if len(matches) != 1:
                reasons.append(f"unresolved_member:{key}:{name}")
            if definition["classification"] != "isv_topic" or definition["required"] is not False:
                reasons.append(f"classification_unverified:{key}:{name}")
            topic = TopicEvidence(identity, definition["required"], state)
            if identity in evidence and evidence[identity] != topic:
                _fail("ambiguous_topic_ownership")
            evidence[identity] = topic
            ids.append(identity)
            if key in selected:
                members.append((key, name, matches[0].component_id if len(matches) == 1 else None))
        sets.append(TopicSet(
            key, tuple(ids), variant["membershipComplete"],
            SourceBinding(package["packageId"], package["packageVersion"], catalog.revision, bound),
        ))
    for key in relevant_packages:
        package = packages[key]
        if package["requiredTopicCoverage"] != "complete":
            reasons.append(f"required_coverage_unverified:{key}")
        if package["setCoverage"] != "complete":
            reasons.append(f"set_coverage_unverified:{key}")
    if not dependency_coverage_verified:
        reasons.append("custom_dependency_coverage_unverified")
    # Reject the same installed component claimed by different package owners.
    owners = {}
    for key, match in resolved_sets.items():
        if match is None:
            continue
        _, variant, package = match
        if package["key"] not in relevant_packages:
            continue
        for name in variant["memberSchemaNames"]:
            previous = owners.setdefault(name.casefold(), package["key"])
            if previous != package["key"]:
                reasons.append("ambiguous_package_ownership")
    snapshot = build_provisional_snapshot(
        target, selected, tuple(sets), tuple(evidence.values()),
        coverage_complete=not any("coverage_unverified" in reason for reason in reasons),
    )
    snapshot = replace(snapshot, blockers=tuple(dict.fromkeys((*snapshot.blockers, *reasons))))
    return CatalogSnapshot(snapshot, catalog.revision, inventory.revision, tuple(members))


def snapshot_from_response(
    catalog: Catalog, target: DiscoveryTarget, selected_keys: tuple[str, ...], body: dict,
) -> CatalogSnapshot:
    """Native projection reuses M2 normalization; installation remains unverified."""
    inventory = inventory_from_response(target, body)
    normalized = {
        _identity(row["component"]["id"]): normalize_state(
            row["component"].get("state"), row["component"].get("status"),
        )[0] for row in body["botComponentChanges"]
    }
    inventory = replace(inventory, topics=tuple(
        replace(topic, state=normalized.get(topic.component_id, "Unknown"))
        for topic in inventory.topics
    ))
    return replace(compare_catalog(catalog, inventory, selected_keys), evidence_kind="native_read")
