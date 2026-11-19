# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Whole-set content operations over fresh native component evidence."""

from dataclasses import asdict, dataclass, replace
import json
from uuid import NAMESPACE_URL, uuid5

from topic_actions_components import normalize_state
from topic_actions_content import load_set_content
from topic_actions_discovery import _identity
from topic_actions_planning import TopicChange, TopicPlan, _digest


@dataclass(frozen=True)
class ContentMember:
    set_key: str
    schema_name: str
    display_name: str
    content_digest: str
    dialog_json: str
    component_fields_json: str
    component_id: str
    state: str
    version: str | int | None


def matching_source_variants(topic_set: dict, packages: dict, agent_schema_name: str) -> list[dict]:
    return [
        variant for variant in topic_set["sourceVariants"]
        if agent_schema_name in packages[variant["packageKey"]]["agentSchemaNames"]
    ]


def dev_blockers(client, target, body: dict) -> tuple[str, ...]:
    """Content writes stay on an ALM-enrolled Development agent; promotion carries them on."""
    from requests import RequestException

    from agentbuilder import AgentBuilderError
    from setup_existing_da import ExistingDASetupError, validate_existing_dev_connection

    try:
        validate_existing_dev_connection(
            client, environment_id=target.environment_id,
            agent_id=target.agent_id, require_alm_family=True,
            expected_schema_name=body["bot"]["schemaName"],
        )
    except ExistingDASetupError:
        return ("dev_alm_required",)
    except (AgentBuilderError, RequestException, ValueError, TypeError, AttributeError):
        return ("dev_validation_failed",)
    return ()


def content_snapshot(catalog, snapshot, body):
    from agentbuilder_object_model import ObjectModelConverterError, yaml_to_object_models

    document = catalog.document()
    packages = {item["key"]: item for item in document["packages"]}
    schema = body["bot"]["schemaName"]
    members = []
    blockers = []
    for key in snapshot.evidence.selected_keys:
        definition = next((item for item in document["sets"] if item["key"] == key), None)
        if definition is None or "contentFolder" not in definition:
            blockers.append(f"content_required:{key}")
            continue
        variants = matching_source_variants(definition, packages, schema)
        if len(variants) != 1:
            blockers.append(f"ambiguous_or_unsupported_set:{key}")
            continue
        variant = variants[0]
        registry = {item["schemaName"]: item for item in packages[variant["packageKey"]]["topics"]}
        content = {item.stem: item for item in load_set_content(definition)}
        try:
            converted = yaml_to_object_models([
                {"key": name, "yaml": content[name.partition(".topic.")[2]].yaml}
                for name in variant["memberSchemaNames"]
            ])
        except ObjectModelConverterError:
            blockers.append("content_converter_unavailable")
            continue
        models = {item["key"]: item for item in converted}
        for name in variant["memberSchemaNames"]:
            item = models.get(name, {})
            dialog = item.get("objectModel")
            if item.get("success") is not True or not isinstance(dialog, dict) or dialog.get("$kind") != "AdaptiveDialog":
                blockers.append(f"content_conversion_failed:{key}:{name}")
                continue
            candidates = [
                row["component"] for row in body["botComponentChanges"]
                if str(row["component"].get("schemaName", "")).casefold() == name.casefold()
            ]
            current = candidates[0] if len(candidates) == 1 else None
            if len(candidates) > 1 or (current and current.get("schemaName") != name):
                blockers.append(f"ambiguous_member:{key}:{name}")
            elif current and current.get("$kind") != "DialogComponent":
                blockers.append(f"wrong_component_kind:{key}:{name}")
            elif current and normalize_dialog(current.get("dialog")) != normalize_dialog(dialog):
                blockers.append(f"content_differs:{key}:{name}")
            identity = _identity(current["id"]) if current else str(uuid5(
                NAMESPACE_URL, _digest({
                    "target": asdict(snapshot.evidence.target), "schema": name,
                    "revision": snapshot.inventory_revision,
                }),
            ))
            topic = registry[name]
            fields = {key: topic[key] for key in ("description",) if key in topic}
            for field, kind in (("managedProperties", "ManagedProperties"), ("shareContext", "ContentShareContext")):
                if field in topic:
                    fields[field] = {**topic[field], "$kind": kind}
            members.append(ContentMember(
                key, name, topic.get("displayName", name),
                content[name.partition(".topic.")[2]].digest,
                json.dumps(dialog, sort_keys=True), json.dumps(fields, sort_keys=True), identity,
                normalize_state(current.get("state"), current.get("status"))[0] if current else "Absent",
                current.get("version") if current else None,
            ))
    ignored = {"set_absent", "empty_membership", "missing_member", "ambiguous_member", "unknown_state"}
    blockers = [
        reason for reason in snapshot.evidence.blockers if reason.split(":", 1)[0] not in ignored
    ] + blockers
    return replace(
        snapshot, content_members=tuple(members),
        members=tuple((item.set_key, item.schema_name, item.component_id) for item in members),
        evidence=replace(snapshot.evidence, blockers=tuple(dict.fromkeys(blockers))),
    )


def normalize_dialog(value):
    # The readback comparison already defines which server-generated fields to ignore.
    from topic_actions_execution import _without_server_generated_fields
    return _without_server_generated_fields(value)


def has_blocking_diagnostic(value):
    if isinstance(value, dict):
        if "errorCode" in value or str(value.get("$kind", "")).casefold().endswith("error"):
            return True
        return any(has_blocking_diagnostic(child) for child in value.values())
    if isinstance(value, list):
        return any(has_blocking_diagnostic(child) for child in value)
    return False


def plan_content_actions(snapshot, action):
    blockers = list(snapshot.evidence.blockers)
    changes, satisfied = [], []
    for key in snapshot.evidence.selected_keys:
        members = [item for item in snapshot.content_members if item.set_key == key]
        if not members and not blockers:
            blockers.append(f"content_required:{key}")
        present = [item for item in members if item.state != "Absent"]
        if present and len(present) != len(members):
            code = "partial_set" if not blockers else "incomplete_set"
            blockers.extend(f"{code}:{key}:{item.schema_name}" for item in members)
        for item in members:
            if item.state != "Absent":
                satisfied.append(item.component_id)
            else:
                changes.append(TopicChange(
                    item.component_id, "Absent", "Off", "insert", item.schema_name,
                    item.display_name, item.content_digest,
                ))
    if len({item.component_id for item in snapshot.content_members}) > 100:
        blockers.append("selected_topic_limit_exceeded")
    unique_changes = {}
    for change in changes:
        previous = unique_changes.setdefault(change.component_id, change)
        if previous != change:
            blockers.append(f"ambiguous_content:{change.schema_name}")
    changes = list(unique_changes.values())
    satisfied = list(dict.fromkeys(satisfied))
    plan = TopicPlan(
        snapshot.evidence.target, action, snapshot.evidence.selected_keys, _digest(asdict(snapshot)),
        tuple(changes) if not blockers else (), tuple(satisfied) if not blockers else (), (),
        tuple(dict.fromkeys(blockers)), "blocked" if blockers else "changes_proposed" if changes else "already_correct", "",
        state_differences=tuple(changes), observed_satisfied_member_ids=tuple(satisfied),
        evidence_kind="catalog", execution_policy="source_inventory", warnings=snapshot.warnings,
        members=snapshot.members,
    )
    return replace(plan, approval_basis="catalog:" + _digest(asdict(plan)))


def content_change_rows(evidence, plan):
    members = {item.schema_name: item for item in evidence.snapshot.content_members}
    return [{
        "$kind": "BotComponentInsert", "component": {
            "$kind": "DialogComponent", "id": change.component_id,
            "parentBotId": plan.target.agent_id,
            "schemaName": change.schema_name, "displayName": change.display_name,
            **json.loads(members[change.schema_name].component_fields_json),
            "state": "Inactive", "status": "Inactive",
            "dialog": json.loads(members[change.schema_name].dialog_json),
            "extensionData": {"UseProvidedBotComponentId": True},
        },
    } for change in plan.delta]


def content_set_overview(evidence, catalog, action):
    """Keep live presence separate from the safety checks in a write review."""
    from topic_actions_presentation import result_text

    document = catalog.document()
    packages = {item["key"]: item for item in document["packages"]}
    schema = evidence.body["bot"]["schemaName"]
    present = {
        row["component"]["schemaName"] for row in evidence.body["botComponentChanges"]
        if isinstance(row["component"].get("schemaName"), str)
    }
    sets = []
    diagnostics = []
    for definition in document["sets"]:
        if "contentFolder" not in definition:
            continue
        variants = matching_source_variants(definition, packages, schema)
        if not variants:
            continue
        if len(variants) != 1:
            diagnostics.append(f"ambiguous_or_unsupported_set:{definition['key']}")
            continue
        names = variants[0]["memberSchemaNames"]
        count = sum(name in present for name in names)
        if count == len(names):
            continue
        sets.append({
            "key": definition["key"],
            "name": f"{definition['integration']['name']} {definition['name']}",
            "topicCount": count, "expectedTopicCount": len(names),
            "presence": "Absent" if count == 0 else "Partial" if count < len(names) else "Present",
        })
    target = evidence.snapshot.evidence.target
    question = f"Which topic sets would you like to {action}?"
    result = {
        "contractVersion": 1, "contractStatus": "provisional",
        "status": "sets_listed", "reason": "sets_listed", "action": action,
        "completed": False, "writeStatus": "not_attempted",
        "target": {"tenantId": target.tenant_id, "environmentId": target.environment_id, "agentId": target.agent_id},
        "sets": sets, "setCount": len(sets), "discoveryComplete": not diagnostics,
        "selectionQuestion": {
            "header": question, "question": question, "multiSelect": True,
            "options": [{"label": item["name"]} for item in sets], "allowFreeformInput": False,
        } if len(sets) > 1 and not diagnostics else None,
        "warnings": list(evidence.snapshot.warnings), "availabilityDiagnostics": diagnostics,
    }
    result["userMessage"] = result_text(result)
    return result


def content_reconcile(before, after, plan):
    """Verify the inserted members and that nothing else changed."""
    from topic_actions_execution import _component_map, _preservation_content

    before_map = _component_map(before.body)
    after_map = _component_map(after.body)
    delta = {item.component_id: item for item in plan.delta}
    containment = set(after_map) == set(before_map) | set(delta) and all(
        identity in after_map
        and _preservation_content(after_map[identity], state_change=False)
        == _preservation_content(original, state_change=False)
        for identity, original in before_map.items()
    )
    results = []
    members = {item.component_id: item for item in before.snapshot.content_members}
    for member in members.values():
        current = after_map.get(member.component_id, {})
        valid = (
            current.get("$kind") == "DialogComponent"
            and current.get("schemaName") == member.schema_name
            and current.get("parentBotId") is not None
            and _identity(current["parentBotId"]) == plan.target.agent_id
            and normalize_dialog(current.get("dialog")) == normalize_dialog(json.loads(member.dialog_json))
            and sum(row.get("schemaName") == member.schema_name for row in after_map.values()) == 1
        )
        state = normalize_state(current.get("state"), current.get("status"))[0]
        blocking = member.component_id in delta and has_blocking_diagnostic(current)
        valid = valid and (state == "Off" if member.component_id in delta else True) and not blocking
        results.append({
            "componentId": member.component_id, "state": state,
            "status": ("observed_desired" if member.component_id in delta else "already_correct") if valid else "unverified",
            "reason": "blocking_diagnostic" if blocking else "readback",
        })
    authority = (
        before.account_id == after.account_id
        and before.snapshot.catalog_revision == after.snapshot.catalog_revision
        and before.snapshot.evidence.target == after.snapshot.evidence.target
        and not after.snapshot.evidence.blockers and not after.blockers
    )
    return results, containment and authority, "violated" if not containment else "verified" if authority else "unverified"
