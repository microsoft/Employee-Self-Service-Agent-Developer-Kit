# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure controller/transport tests, not evidence of native API qualification."""

from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest
import requests

from agentbuilder import AgentBuilderClient, AgentBuilderError, AgentBuilderHTTPError
from topic_actions_client import TopicActionsClient
from topic_actions_catalog import (
    InstalledPackage, compare_catalog, load_catalog, parse_catalog, plan_catalog_actions,
    snapshot_from_response,
)
from topic_actions_discovery import DiscoveryError, DiscoveryTarget
from topic_actions_execution import (
    OperationEvidence, TopicActionSession, build_state_payload,
)
from topic_actions_flat_discovery import InventoryTopic, NativeInventory
from topic_actions_native import NativeActionBackend
from topic_actions_planning import plan_topic_actions


TARGET = DiscoveryTarget(
    "00000000-0000-0000-0000-000000001111",
    "00000000-0000-0000-0000-000000002222",
    "00000000-0000-0000-0000-000000003333",
)


def catalog_document():
    return {
        "schemaVersion": 1, "authorityStatus": "owner_approved",
        "source": {
            "kind": "ess_package_mapping", "repositoryUrl": "synthetic-source",
            "revision": "r1", "approvalReference": "synthetic-only",
        },
        "packages": [{
            "key": "package", "packageId": "synthetic-package", "packageVersion": "1",
            "agentSchemaNames": ["synthetic.hr"], "sourcePath": "synthetic-path",
            "sourceRevision": "r1", "setCoverage": "complete",
            "requiredTopicCoverage": "complete",
            "requiredTopicSource": {"sourcePath": "synthetic-required", "sourceRevision": "r1"},
            "topics": [
                {"schemaName": f"synthetic.hr.topic.{name}", "classification": "isv_topic", "required": False}
                for name in ("a", "shared", "b", "unrelated")
            ],
        }],
        "sets": [{
            "key": key, "name": key, "integration": {"key": "synthetic", "name": "Synthetic"},
            "sourceVariants": [{
                "packageKey": "package", "membershipStatus": "owner_approved",
                "membershipComplete": True,
                "memberSchemaNames": [f"synthetic.hr.topic.{name}" for name in names],
            }],
        } for key, names in (("alpha", ("a", "shared")), ("beta", ("b", "shared")))],
    }


def operation_evidence(
    states=None, *, selected=("alpha",), revision="r1", document=None,
    trust=True, installed=True, dependencies=True,
):
    states = {"a": "Off", "shared": "Off", "b": "Off", "unrelated": "On", **(states or {})}
    catalog = parse_catalog(document or catalog_document())
    inventory = NativeInventory(TARGET, "synthetic.hr", tuple(
        InventoryTopic(name, f"synthetic.hr.topic.{name}", state)
        for name, state in states.items()
    ), revision)
    snapshot = compare_catalog(
        catalog, inventory, selected,
        installed_packages=(InstalledPackage("synthetic-package", "1"),) if installed else (),
        trusted_catalog_revision=catalog.revision if trust else None,
        dependency_coverage_verified=dependencies,
    )
    body = {
        "changeToken": revision,
        "botComponentChanges": [{
            "$kind": "BotComponentInsert",
            "component": {
                "$kind": "DialogComponent", "id": name, "parentBotId": TARGET.agent_id,
                "schemaName": f"synthetic.hr.topic.{name}",
                "state": "Active" if state == "On" else "Inactive",
                "status": "Active" if state == "On" else "Inactive",
                "dialog": {"private": f"unchanged-{name}"},
            },
        } for name, state in states.items()],
    }
    return OperationEvidence(snapshot, "synthetic-account", body)


class SyntheticBackend:
    """No network and no claim that supplied evidence exists on a real tenant."""

    def __init__(self, packets, *, error=None, gates=()):
        self.packets = iter(packets)
        self.error = error
        self.gates = gates
        self.submissions = []
        self.reads = 0

    def read(self):
        self.reads += 1
        packet = next(self.packets)
        if isinstance(packet, Exception):
            raise packet
        return deepcopy(packet)

    def admission_blockers(self, evidence):
        return self.gates

    def submit_once(self, agent_id, payload):
        self.submissions.append((agent_id, deepcopy(payload)))
        if self.error:
            raise self.error


def test_bundled_proposal_remains_blocked_even_when_every_member_is_present():
    catalog = load_catalog()
    document = catalog.document()
    package = document["packages"][0]
    inventory = NativeInventory(TARGET, package["agentSchemaNames"][0], tuple(
        InventoryTopic(f"synthetic-{index}", topic["schemaName"], "On")
        for index, topic in enumerate(package["topics"])
    ), "synthetic-read")
    selected = (document["sets"][0]["key"],)
    snapshot = compare_catalog(catalog, inventory, selected)
    plan = plan_topic_actions(snapshot, "disable")
    assert plan.outcome == "blocked"
    assert plan.delta == ()
    assert plan.selected_keys == selected
    assert "catalog_review_pending" in plan.blockers
    assert "catalog_release_untrusted" in plan.blockers
    assert any(reason.startswith("installed_package_unverified:") for reason in plan.blockers)
    assert any(reason.startswith("classification_unverified:") for reason in plan.blockers)


def test_native_projection_keeps_captured_unknown_state_and_does_not_invent_parent_fields():
    from tests.conftest import require_validated_mock
    from tests.mocks import agentbuilder_connectivity as native

    require_validated_mock(native)
    component = native.dialog_component_change(schema_name="synthetic.hr.topic.a")
    body = {
        "bot": {"cdsBotId": TARGET.agent_id, "schemaName": "synthetic.hr"},
        "changeToken": "private-token", "botComponentChanges": [component],
    }
    catalog = parse_catalog(catalog_document())
    snapshot = snapshot_from_response(catalog, TARGET, ("alpha",), body)
    plan = plan_catalog_actions(snapshot, "enable")
    assert snapshot.evidence_kind == "native_read"
    assert snapshot.evidence.topics[0].state == "Unknown"
    assert not plan.delta and plan.outcome == "blocked"
    assert "private-token" not in repr(snapshot)
    assert "AdaptiveDialog" not in repr(snapshot)
    component["component"]["parentBotId"] = TARGET.tenant_id
    with pytest.raises(DiscoveryError) as error:
        snapshot_from_response(catalog, TARGET, ("alpha",), body)
    assert error.value.reason == "target_mismatch"


@pytest.mark.parametrize(("change", "reason"), [
    (lambda doc: doc["packages"].append(deepcopy(doc["packages"][0])), "duplicate_package"),
    (lambda doc: doc["sets"].append(deepcopy(doc["sets"][0])), "duplicate_set"),
    (lambda doc: doc["sets"][0]["sourceVariants"].append(deepcopy(doc["sets"][0]["sourceVariants"][0])), "duplicate_variant"),
    (lambda doc: doc["sets"][0]["sourceVariants"][0].update(packageKey="missing"), "dangling_package"),
    (lambda doc: doc["sets"][0]["sourceVariants"][0]["memberSchemaNames"].append("missing"), "dangling_member"),
    (lambda doc: doc["packages"][0]["topics"][0].update(classification="required_system", required=False), "contradictory_classification"),
    (lambda doc: doc["packages"][0]["topics"][0].update(required=True), "contradictory_classification"),
    (lambda doc: doc["packages"][0]["topics"][0].update(classification="required_system", required=True), "ineligible_member"),
    (lambda doc: doc["packages"][0]["topics"][0].update(classification="other_non_isv"), "ineligible_member"),
    (lambda doc: doc["packages"][0].update(requiredTopicSource=None), "invalid_required_coverage"),
    (lambda doc: doc["packages"][0]["topics"][0].update(required=None), "invalid_required_coverage"),
    (lambda doc: doc.update(schemaVersion=2), "invalid_catalog"),
])
def test_catalog_semantics_reject_unsafe_definitions(change, reason):
    document = catalog_document()
    change(document)
    with pytest.raises(DiscoveryError) as error:
        parse_catalog(document)
    assert error.value.reason == reason


def test_duplicate_json_keys_are_rejected(tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text('{"schemaVersion": 1, "schemaVersion": 1}', encoding="utf-8")
    with pytest.raises(DiscoveryError) as error:
        load_catalog(path)
    assert error.value.reason == "ambiguous_catalog"


@pytest.mark.parametrize(("settings", "reason"), [
    ({"trust": False}, "catalog_release_untrusted"),
    ({"installed": False}, "installed_package_unverified:package"),
    ({"dependencies": False}, "custom_dependency_coverage_unverified"),
    ({"selected": ("alpha", "missing")}, "missing_set:missing"),
])
def test_authority_and_full_selection_are_not_inferred(settings, reason):
    packet = operation_evidence(**settings)
    plan = plan_catalog_actions(packet.snapshot, "enable")
    assert reason in plan.blockers
    assert not plan.delta
    assert packet.snapshot.evidence.selected_keys == settings.get("selected", ("alpha",))


@pytest.mark.parametrize(("states", "protects", "blocked"), [
    ({"a": "On", "shared": "On", "b": "On"}, True, False),
    ({"a": "On", "shared": "On", "b": "Off"}, False, False),
    ({"a": "On", "shared": "Off", "b": "On"}, True, False),
    ({"a": "On", "shared": "On", "b": "Unknown"}, False, True),
])
def test_outside_set_protection_including_shared_only_on_exception(states, protects, blocked):
    packet = operation_evidence(states)
    plan = plan_catalog_actions(packet.snapshot, "disable")
    assert bool(plan.blockers) is blocked
    assert any(skip.component_id == "shared" for skip in plan.skips) is protects
    if not blocked:
        assert {item.component_id for item in plan.delta} == ({"a"} if protects else {"a", "shared"})


def test_selected_sets_do_not_protect_each_other_and_shared_members_are_deduplicated():
    packet = operation_evidence(
        {"a": "On", "shared": "On", "b": "On"}, selected=("alpha", "beta"),
    )
    plan = plan_catalog_actions(packet.snapshot, "disable")
    assert plan.outcome == "changes_proposed"
    assert {item.component_id for item in plan.delta} == {"a", "b", "shared"}
    assert len(plan.delta) == 3
    assert not plan.skips


def test_missing_member_is_not_a_successful_narrower_plan():
    packet = operation_evidence()
    inventory = NativeInventory(TARGET, "synthetic.hr", (
        InventoryTopic("a", "synthetic.hr.topic.a", "Off"),
    ), "r1")
    catalog = parse_catalog(catalog_document())
    snapshot = compare_catalog(catalog, inventory, ("alpha",))
    plan = plan_catalog_actions(snapshot, "enable")
    assert plan.outcome == "blocked"
    assert not plan.delta
    assert any(member[2] is None for member in snapshot.members)
    assert packet.snapshot.evidence.selected_keys == plan.selected_keys


@pytest.mark.parametrize("schemas", [
    ("SYNTHETIC.hr.topic.a",),
    ("synthetic.hr.topic.a", "SYNTHETIC.hr.topic.a"),
])
def test_schema_matching_is_exact_and_case_aliases_cannot_choose_an_arbitrary_member(schemas):
    catalog = parse_catalog(catalog_document())
    inventory = NativeInventory(TARGET, "synthetic.hr", tuple(
        InventoryTopic(f"id-{index}", schema, "On") for index, schema in enumerate(schemas)
    ), "r1")
    snapshot = compare_catalog(catalog, inventory, ("alpha",))
    plan = plan_catalog_actions(snapshot, "disable")
    assert not plan.delta and plan.outcome == "blocked"
    assert next(item for item in snapshot.members if item[1] == "synthetic.hr.topic.a")[2] is None


def test_incomplete_outside_membership_cannot_be_assumed_disjoint():
    document = catalog_document()
    outside = document["sets"][1]["sourceVariants"][0]
    outside["memberSchemaNames"] = ["synthetic.hr.topic.b"]
    outside["membershipComplete"] = None
    packet = operation_evidence(
        {"a": "On", "shared": "On", "b": "On"}, document=document,
    )
    plan = plan_catalog_actions(packet.snapshot, "disable")
    assert plan.outcome == "blocked" and not plan.delta
    assert "membership_review_pending:beta" in plan.blockers


def test_required_runtime_defense_and_all_protected_are_not_noop():
    packet = operation_evidence({"a": "On", "shared": "On"})
    evidence = packet.snapshot.evidence
    topics = tuple(
        replace(topic, required=True) if topic.component_id in ("a", "shared") else topic
        for topic in evidence.topics
    )
    snapshot = replace(packet.snapshot, evidence=replace(evidence, topics=topics))
    plan = plan_catalog_actions(snapshot, "disable")
    assert plan.outcome == "all_protected"
    assert not plan.delta and not plan.satisfied_member_ids
    backend = SyntheticBackend([replace(packet, snapshot=snapshot)])
    result = TopicActionSession(backend, "disable").run(lambda _: pytest.fail("No approvable scope"))
    assert result["status"] == "blocked"
    assert not result["completed"]
    assert not backend.submissions


def test_approval_then_fresh_read_one_dispatch_and_verified_content_preservation():
    before = operation_evidence()
    after = operation_evidence({"a": "On", "shared": "On"}, revision="r2")
    backend = SyntheticBackend([before, before, after])
    context = {"progress": {"connection": "done"}, "private": "do-not-emit"}
    session = TopicActionSession(backend, "enable", caller_context=context)
    shown = []

    def confirm(plan):
        shown.append(deepcopy(plan))
        plan["proposedChanges"].clear()
        return "approve"

    result = session.run(confirm)
    assert result["status"] == "completed" and result["completed"]
    assert backend.reads == 3 and len(backend.submissions) == 1
    agent_id, payload = backend.submissions[0]
    assert agent_id == TARGET.agent_id
    assert payload["changeToken"] == "r1"
    assert len(payload["botComponentChanges"]) == 2
    originals = {row["component"]["id"]: row["component"] for row in before.body["botComponentChanges"]}
    for row in payload["botComponentChanges"]:
        actual = row["component"]
        expected = deepcopy(originals[actual["id"]])
        expected["state"] = expected["status"] = "Active"
        assert actual == expected
    assert {topic["status"] for topic in result["topics"]} == {"changed"}
    assert result["callerContext"] == context
    assert result["callerContext"] is not context
    assert "do-not-emit" not in json.dumps(shown)
    assert "private" not in json.dumps(shown)
    assert "changeToken" not in json.dumps(result)
    assert session.run(confirm)["blockers"] == ["session_consumed"]
    assert len(backend.submissions) == 1


def server_generated_readback(action):
    """Model the captured selected revision and dependent-dialog diagnostic churn."""
    enabled = {"a": "On", "shared": "On"}
    before = operation_evidence(enabled if action == "disable" else None)
    after = operation_evidence(enabled if action == "enable" else None, revision="r2")
    for packet in (before, after):
        for row in packet.body["botComponentChanges"]:
            component = row["component"]
            component.update(version=1, auditInfo={"createdTimeUtc": "created", "modifiedTimeUtc": "before"})
            component["dialog"]["beginDialog"] = {
                "actions": [{
                    "$kind": "InvokeFlowAction", "flowId": "original-flow",
                    "input": {"binding": {"worker": "Global.Worker"}},
                    "diagnostics": [{"message": "old diagnostic"}],
                }, {
                    "$kind": "ConditionGroup",
                    "conditions": [{
                        "condition": "=true", "structuredCondition": {"old": True},
                        "actions": [],
                    }],
                }],
            }
    for row in after.body["botComponentChanges"]:
        component = row["component"]
        if component["id"] in ("a", "shared"):
            component["version"] = 2
            component["auditInfo"]["modifiedTimeUtc"] = "after"
        actions = component["dialog"]["beginDialog"]["actions"]
        actions[0].pop("diagnostics")
        actions[1]["diagnostics"] = [{"message": "new diagnostic"}]
        actions[1]["conditions"][0]["structuredCondition"] = {"new": True}
    return before, after


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_server_generated_readback_does_not_hide_verified_state_success(action):
    before, after = server_generated_readback(action)
    originals = deepcopy((before.body, after.body))
    backend = SyntheticBackend([before, before, after])

    result = TopicActionSession(backend, action).run(lambda _: "approve")

    assert result["status"] == "completed" and result["completed"]
    assert {topic["status"] for topic in result["topics"]} == {"changed"}
    assert {topic["state"] for topic in result["topics"]} == ({"On"} if action == "enable" else {"Off"})
    assert not result["blockers"]
    assert len(backend.submissions) == 1 and backend.reads == 3
    expected = build_state_payload(before, plan_catalog_actions(before.snapshot, action))
    assert backend.submissions[0][1] == expected
    assert (before.body, after.body) == originals


@pytest.mark.parametrize(("identity", "path", "value"), [
    ("a", ("dialog", "beginDialog", "actions", 0, "flowId"), "another-flow"),
    ("a", ("dialog", "beginDialog", "actions", 0, "input", "binding", "worker"), "Global.Other"),
    ("a", ("dialog", "beginDialog", "actions", 1, "conditions", 0, "condition"), "=false"),
    ("unrelated", ("dialog", "private"), "changed-authored-content"),
    ("a", ("schemaName",), "synthetic.hr.topic.other"),
    ("a", ("parentBotId",), TARGET.tenant_id),
    ("a", ("auditInfo", "createdTimeUtc"), "unexpected"),
    ("a", ("unknownMetadata",), "unexpected"),
    ("a", ("diagnostics",), [{"message": "not a dialog field"}]),
    ("unrelated", ("version",), 2),
    ("unrelated", ("auditInfo", "modifiedTimeUtc"), "after"),
])
def test_generated_readback_does_not_mask_authored_identity_or_unselected_revision_changes(identity, path, value):
    before, after = server_generated_readback("enable")
    component = next(
        row["component"] for row in after.body["botComponentChanges"]
        if row["component"]["id"] == identity
    )
    parent = component
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    backend = SyntheticBackend([before, before, after])

    result = TopicActionSession(backend, "enable").run(lambda _: "approve")

    assert result["status"] == "partial" and not result["completed"]
    assert {topic["status"] for topic in result["topics"]} == {"observed_desired"}
    assert "preservation could not be verified" in result["message"]
    assert result["blockers"] == ["verification_incomplete", "fresh_approval_required"]
    assert len(backend.submissions) == 1


@pytest.mark.parametrize("field", ["version", "diagnostics"])
def test_server_generated_drift_before_dispatch_still_requires_fresh_approval(field):
    before, _ = server_generated_readback("enable")
    fresh = deepcopy(before)
    component = fresh.body["botComponentChanges"][0]["component"]
    if field == "version":
        component["version"] = 2
    else:
        component["dialog"]["beginDialog"]["actions"][0]["diagnostics"] = []
    backend = SyntheticBackend([before, fresh])

    result = TopicActionSession(backend, "enable").run(lambda _: "approve")

    assert result["status"] == "review_required"
    assert "evidence_changed" in result["blockers"]
    assert not backend.submissions


@pytest.mark.parametrize(("decision", "status"), [
    ("deny", "denied"), ("cancel", "cancelled"), ("yes", "blocked"),
])
def test_denial_cancellation_and_unrecognized_consent_never_dispatch(decision, status):
    backend = SyntheticBackend([operation_evidence()])
    result = TopicActionSession(backend, "enable").run(lambda _: decision)
    assert result["status"] == status
    assert backend.reads == 1 and not backend.submissions


@pytest.mark.parametrize("clock_values", [(0, 301), (0, 1, 301)])
def test_expired_review_cannot_dispatch(clock_values):
    before = operation_evidence()
    backend = SyntheticBackend([before, before])
    times = iter(clock_values)
    result = TopicActionSession(backend, "enable", clock=lambda: next(times)).run(lambda _: "approve")
    assert result["status"] == "review_required"
    assert result["blockers"] == ["approval_expired"]
    assert not backend.submissions


@pytest.mark.parametrize("drift", ["state", "revision", "account", "content", "permission", "protection"])
def test_any_relevant_drift_requires_new_review(drift):
    before = operation_evidence()
    fresh = operation_evidence()
    if drift == "state":
        fresh = operation_evidence({"a": "On"})
    elif drift == "revision":
        fresh = operation_evidence(revision="r2")
    elif drift == "account":
        fresh = replace(fresh, account_id="another-maker")
    elif drift == "content":
        fresh.body["botComponentChanges"][-1]["component"]["dialog"] = {"changed": True}
    elif drift == "permission":
        fresh = replace(fresh, blockers=("write_permission_lost",))
    else:
        evidence = fresh.snapshot.evidence
        changed = tuple(replace(topic, required=True) if topic.component_id == "a" else topic for topic in evidence.topics)
        fresh = replace(fresh, snapshot=replace(fresh.snapshot, evidence=replace(evidence, topics=changed)))
    backend = SyntheticBackend([before, fresh])
    result = TopicActionSession(backend, "enable").run(lambda _: "approve")
    assert result["status"] == "review_required"
    assert not backend.submissions


@pytest.mark.parametrize("error", [
    requests.Timeout("private"), requests.ConnectionError("private"),
    AgentBuilderError("conflict-private"),
])
def test_uncertain_submission_is_not_replayed_or_attributed_even_if_readback_is_desired(error):
    before = operation_evidence()
    after = operation_evidence({"a": "On", "shared": "On"}, revision="r2")
    backend = SyntheticBackend([before, before, after], error=error)
    result = TopicActionSession(backend, "enable").run(lambda _: "approve")
    assert result["status"] == "unverified" and not result["completed"]
    assert len(backend.submissions) == 1 and backend.reads == 3
    assert {topic["status"] for topic in result["topics"]} == {"observed_desired"}
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("change", ["partial", "content", "outside", "missing", "read_failure"])
def test_partial_or_out_of_scope_readback_is_not_success(change):
    before = operation_evidence()
    after = operation_evidence({"a": "On", "shared": "On"}, revision="r2")
    if change == "partial":
        after = operation_evidence({"a": "On"}, revision="r2")
    elif change == "content":
        after.body["botComponentChanges"][0]["component"]["dialog"] = {"unexpected": True}
    elif change == "outside":
        after = operation_evidence({"a": "On", "shared": "On", "unrelated": "Off"}, revision="r2")
    elif change == "missing":
        after.body["botComponentChanges"].pop()
    else:
        after = RuntimeError("private-response")
    backend = SyntheticBackend([before, before, after])
    result = TopicActionSession(backend, "enable").run(lambda _: "approve")
    assert result["status"] == ("unverified" if change == "read_failure" else "partial")
    assert not result["completed"]
    assert len(backend.submissions) == 1
    assert "private-response" not in json.dumps(result)


def test_protected_topic_is_not_reported_as_disabled_or_whole_set_complete():
    before = operation_evidence({"a": "On", "shared": "On", "b": "On"})
    after = operation_evidence({"a": "Off", "shared": "On", "b": "On"}, revision="r2")
    backend = SyntheticBackend([before, before, after])
    result = TopicActionSession(backend, "disable").run(lambda _: "approve")
    assert result["status"] == "completed_with_protections"
    assert not result["completed"]
    assert next(item for item in result["topics"] if item["componentId"] == "shared")["status"] == "protected"
    assert len(backend.submissions[0][1]["botComponentChanges"]) == 1


def test_noop_is_approved_and_rechecked_but_never_submitted():
    before = operation_evidence({"a": "On", "shared": "On"})
    backend = SyntheticBackend([before, before])
    result = TopicActionSession(backend, "enable").run(lambda _: "approve")
    assert result["status"] == "already_correct" and result["completed"]
    assert backend.reads == 2 and not backend.submissions
    assert {item["status"] for item in result["topics"]} == {"already_correct"}


def test_in_process_same_target_dispatch_is_serialized_and_other_session_needs_fresh_review():
    before = operation_evidence()
    after = operation_evidence({"a": "On", "shared": "On"}, revision="r2")
    first = SyntheticBackend([before, before, after])
    second = SyntheticBackend([before])
    results = []
    original_submit = first.submit_once

    def submit(agent, payload):
        results.append(TopicActionSession(second, "enable").run(lambda _: "approve"))
        original_submit(agent, payload)

    first.submit_once = submit
    result = TopicActionSession(first, "enable").run(lambda _: "approve")
    assert result["status"] == "completed"
    assert results[0]["status"] == "review_required"
    assert results[0]["blockers"] == ["operation_in_progress"]
    assert not second.submissions and second.reads == 1


def test_release_control_is_rechecked_immediately_before_submission():
    before = operation_evidence()
    backend = SyntheticBackend([before, before])
    gates = iter([(), (), ("release_disabled",)])
    backend.admission_blockers = lambda _: next(gates)
    result = TopicActionSession(backend, "enable").run(lambda _: "approve")
    assert result["status"] == "review_required"
    assert result["blockers"] == ["release_disabled"]
    assert not backend.submissions


def test_native_gate_denies_even_a_direct_submission_and_never_asks_for_consent():
    packet = operation_evidence()
    backend = SyntheticBackend([packet], gates=("release_control_unavailable",))
    result = TopicActionSession(backend, "enable").run(lambda _: pytest.fail("Blocked plan cannot request consent"))
    assert result["status"] == "blocked" and not backend.submissions
    client = Mock(spec=AgentBuilderClient)
    components = Mock(spec=TopicActionsClient)
    native = NativeActionBackend(client, TARGET, ("alpha",), parse_catalog(catalog_document()), "maker", components)
    with pytest.raises(ValueError, match="not admitted"):
        native.submit_once(TARGET.agent_id, {})
    components.submit_state_payload.assert_not_called()


def dev_source_document():
    document = catalog_document()
    document["authorityStatus"] = "provisional"
    document["source"]["approvalReference"] = None
    package = document["packages"][0]
    package.update(
        packageId=None, setCoverage="unknown",
        requiredTopicCoverage="unknown", requiredTopicSource=None,
    )
    for topic in package["topics"]:
        topic.update(classification="unknown", required=None)
    for topic_set in document["sets"]:
        topic_set["sourceVariants"][0].update(
            membershipStatus="provisional", membershipComplete=None,
        )
    return document


def dev_native_backend(*, selected=("alpha",), before=None, after=None, realm="dev"):
    """Synthetic transport packets exercise policy, not native API qualification."""
    catalog = parse_catalog(dev_source_document())
    first = operation_evidence(before, selected=selected, document=catalog.document()).body
    last = operation_evidence(
        after, selected=selected, document=catalog.document(), revision="r2",
    ).body
    for body in (first, last):
        body["bot"] = {"cdsBotId": TARGET.agent_id, "schemaName": "synthetic.hr"}
    client = Mock(spec=AgentBuilderClient)
    client.tenant_id = TARGET.tenant_id
    client.host = "https://0000000000000000000000000000222.2.environment.api.test.powerplatform.com"
    client.ring = "test"
    client.api_version = "2024-10-01"
    client.get_agent.return_value = {"botId": TARGET.agent_id, "realm": realm}
    components = Mock(spec=TopicActionsClient)
    components.tenant_id = TARGET.tenant_id
    components.environment_id = TARGET.environment_id
    components.bot_id = TARGET.agent_id
    components.host = client.host
    components.ring = client.ring
    components.signed_in_username = "synthetic-maker"
    components.single_attempt = True
    components.read_components.side_effect = [deepcopy(first), deepcopy(first), deepcopy(last)]
    return NativeActionBackend(client, TARGET, selected, catalog, "synthetic-maker", components)


def test_dev_source_policy_preserves_unknown_evidence_and_exposes_it_at_review():
    backend = dev_native_backend()
    packet = backend.read()
    assert backend.admission_blockers(packet) == ()
    assert packet.snapshot.source_inventory_only
    assert all(topic.required is None for topic in packet.snapshot.evidence.topics)
    assert packet.snapshot.evidence.coverage_complete is False
    assert all(item.membership_complete is None for item in packet.snapshot.evidence.sets)
    plan = plan_catalog_actions(packet.snapshot, "enable")
    assert plan.outcome == "changes_proposed"
    assert {item.component_id for item in plan.delta} == {"a", "shared"}
    assert plan.execution_policy == "source_inventory"
    assert plan.live_actions_available
    assert {"catalog_review_pending", "installed_package_unverified", "unknown_protection"} <= set(plan.warnings)
    assert "native_draft_published_effects_unqualified" in plan.warnings


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_native_dev_execution_uses_full_computed_union_and_verifies_readback(action):
    enabled = {"a": "On", "shared": "On", "b": "On"}
    backend = dev_native_backend(
        selected=("alpha", "beta"),
        before=enabled if action == "disable" else None,
        after=enabled if action == "enable" else None,
    )
    reviews = []

    def confirm(plan):
        reviews.append(deepcopy(plan))
        return "approve"

    result = TopicActionSession(backend, action).run(confirm)
    assert result["completed"] and result["status"] == "completed"
    assert backend.components.submit_state_payload.call_count == 1
    assert backend.components.read_components.call_count == 3
    payload = backend.components.submit_state_payload.call_args.args[0]
    updates = [row["component"] for row in payload["botComponentChanges"]]
    assert len(updates) == 3
    assert {row["id"] for row in updates} == {"a", "b", "shared"}
    expected_state = "Active" if action == "enable" else "Inactive"
    assert all(row["state"] == row["status"] == expected_state for row in updates)
    assert payload["changeToken"] == "r1"
    backend.client.update_components_once.assert_not_called()
    assert reviews[0]["account"] == "synthetic-maker"
    assert len(reviews[0]["members"]) == 4
    assert reviews[0]["warnings"] == result["warnings"]
    assert "No publish operation was requested" in result["message"]
    with pytest.raises(ValueError, match="already consumed"):
        backend.submit_once(TARGET.agent_id, {})
    assert backend.components.submit_state_payload.call_count == 1


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_native_execution_preserves_unparented_bot_settings_without_submitting_them(action):
    enabled = {"a": "On", "shared": "On"}
    backend = dev_native_backend(
        before=enabled if action == "disable" else None,
        after=enabled if action == "enable" else None,
    )
    settings = {
        "$kind": "BotComponentInsert",
        "component": {
            "$kind": "BotSettingsComponent", "id": "settings",
            "schemaName": "synthetic.hr.BotSettingsComponent.ConnectionParameter",
        },
    }
    packets = list(backend.components.read_components.side_effect)
    for packet in packets:
        packet["botComponentChanges"].append(deepcopy(settings))
    backend.components.read_components.side_effect = packets

    result = TopicActionSession(backend, action).run(lambda _: "approve")

    assert result["status"] == "completed" and result["completed"]
    backend.components.submit_state_payload.assert_called_once()
    payload = backend.components.submit_state_payload.call_args.args[0]
    assert {row["component"]["id"] for row in payload["botComponentChanges"]} == {"a", "shared"}
    assert packets[-1]["botComponentChanges"][-1] == settings


@pytest.mark.parametrize(("kind", "parent"), [
    ("DialogComponent", None),
    ("GlobalVariableComponent", None),
    ("BotSettingsComponent", TARGET.tenant_id),
    ("BotSettingsComponent", ""),
])
def test_payload_still_rejects_missing_or_foreign_parents_outside_bot_settings_omission(kind, parent):
    packet = operation_evidence()
    packet.body["botComponentChanges"].append({
        "$kind": "BotComponentInsert",
        "component": {
            "$kind": kind, "id": "unselected",
            "schemaName": "synthetic.hr.unselected", "parentBotId": parent,
        },
    })
    plan = plan_catalog_actions(packet.snapshot, "enable")

    with pytest.raises(ValueError):
        build_state_payload(packet, plan)


def test_native_dev_noop_confirms_and_rereads_without_submission():
    backend = dev_native_backend()
    reviews = []

    def confirm(plan):
        reviews.append(plan)
        return "approve"

    result = TopicActionSession(backend, "disable").run(confirm)
    assert result["status"] == "already_correct" and result["completed"]
    assert reviews[0]["alreadyCorrect"] == ["a", "shared"]
    assert backend.components.read_components.call_count == 2
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("realm", ["dev", "test", "prod", None, 0, 1, 2])
def test_native_realm_does_not_block_approved_exact_target_execution(realm):
    backend = dev_native_backend(realm=realm, after={"a": "On", "shared": "On"})
    reviews = []
    result = TopicActionSession(backend, "enable").run(
        lambda review: reviews.append(review) or "approve",
    )
    assert result["status"] == "completed" and result["completed"]
    assert len(reviews) == 1
    assert "native_draft_published_effects_unqualified" in reviews[0]["warnings"]
    backend.components.submit_state_payload.assert_called_once()


@pytest.mark.parametrize("returned_id", [TARGET.tenant_id, None, "not-an-id"])
def test_native_direct_lookup_still_must_identify_the_selected_agent(returned_id):
    backend = dev_native_backend(realm="prod")
    backend.client.get_agent.return_value = {"botId": returned_id, "realm": "prod"}
    result = TopicActionSession(backend, "enable").run(
        lambda _: pytest.fail("A mismatched agent cannot request approval."),
    )
    assert result["status"] == "blocked"
    backend.components.read_components.assert_not_called()
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("change", ["missing_member", "unknown_state", "wrong_parent"])
def test_dev_policy_does_not_waive_identity_membership_or_state_failures(change):
    backend = dev_native_backend()
    body = deepcopy(next(backend.components.read_components.side_effect))
    if change == "missing_member":
        body["botComponentChanges"].pop(0)
    elif change == "unknown_state":
        body["botComponentChanges"][0]["component"]["status"] = "Active"
    else:
        body["botComponentChanges"][0]["component"]["parentBotId"] = TARGET.tenant_id
    backend.components.read_components.side_effect = [body]
    result = TopicActionSession(backend, "enable").run(
        lambda _: pytest.fail("Unresolved topics cannot request approval."),
    )
    assert result["status"] == "blocked"
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("change", ["content", "extra_topic", "wrong_target"])
def test_native_submission_independently_rejects_payload_outside_computed_plan(change):
    backend = dev_native_backend()
    packet = backend.read()
    plan = plan_catalog_actions(packet.snapshot, "enable")
    payload = build_state_payload(packet, plan)
    agent = TARGET.agent_id
    if change == "content":
        payload["botComponentChanges"][0]["component"]["dialog"] = {"changed": True}
    elif change == "extra_topic":
        payload["botComponentChanges"].append(deepcopy(payload["botComponentChanges"][0]))
    else:
        agent = TARGET.tenant_id
    with pytest.raises(ValueError):
        backend.submit_once(agent, payload)
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize(("status", "reason"), [
    (302, "write_http_error"), (400, "write_request_rejected"),
    (401, "write_authentication_failed"), (403, "write_access_denied"),
    (404, "write_target_not_found"), (409, "write_conflict"),
    (412, "write_conflict"), (413, "write_request_too_large"),
    (429, "write_throttled"), (500, "write_service_failed"),
])
def test_native_http_failures_keep_safe_status_and_stop_without_replay(status, reason):
    backend = dev_native_backend()
    backend.components.submit_state_payload.side_effect = AgentBuilderHTTPError("private", status)
    result = TopicActionSession(backend, "enable").run(lambda _: "approve")
    assert result["status"] == "unverified" and not result["completed"]
    assert reason in result["blockers"]
    assert result["submissionHttpStatus"] == status
    assert "fresh_approval_required" in result["blockers"]
    assert backend.components.submit_state_payload.call_count == 1
    assert backend.components.read_components.call_count == 3
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize(("failure", "reason"), [
    (requests.Timeout("private"), "write_transport_failed"),
    (requests.ConnectionError("private"), "write_transport_failed"),
    (AgentBuilderError("private"), "write_acknowledgement_unverified"),
    (ValueError("private"), "submission_validation_failed"),
])
def test_submission_failures_are_classified_without_disclosing_details_or_replaying(failure, reason):
    backend = dev_native_backend()
    backend.components.submit_state_payload.side_effect = failure
    result = TopicActionSession(backend, "enable").run(lambda _: "approve")
    assert result["status"] == "unverified" and not result["completed"]
    assert result["submissionHttpStatus"] is None
    assert reason in result["blockers"]
    assert "fresh_approval_required" in result["blockers"]
    assert backend.components.submit_state_payload.call_count == 1
    assert backend.components.read_components.call_count == 3
    assert all(topic["state"] == "Off" for topic in result["topics"])
    assert "private" not in json.dumps(result)


def test_payload_rejects_nonmatching_schema_or_plan_instead_of_changing_another_topic():
    packet = operation_evidence()
    plan = plan_catalog_actions(packet.snapshot, "enable")
    packet.body["botComponentChanges"][0]["component"]["schemaName"] = "another-topic"
    with pytest.raises(ValueError):
        build_state_payload(packet, plan)


@pytest.mark.parametrize(("status", "failure"), [
    (200, None), (301, None), (307, None), (409, None), (412, None),
    (429, None), (500, None), (200, requests.Timeout("private")),
    (200, requests.ConnectionError("private")),
])
def test_isolated_transport_disables_retries_and_redirects_without_changing_shared_defaults(monkeypatch, status, failure):
    client = AgentBuilderClient(
        "https://0000000000000000000000000000222.2.environment.api.test.powerplatform.com",
        "private-token", ring="test", tenant_id=TARGET.tenant_id,
    )
    shared_adapter = client.session.get_adapter("https://")
    isolated = Mock()
    isolated.__enter__ = Mock(return_value=isolated)
    isolated.__exit__ = Mock(return_value=False)
    isolated.proxies = {}
    isolated.request.side_effect = failure
    isolated.request.return_value.status_code = status
    isolated.request.return_value.json.return_value = {}
    monkeypatch.setattr("agentbuilder.requests.Session", Mock(return_value=isolated))
    try:
        if failure is None and status == 200:
            client.update_components_once(TARGET.agent_id, {"changeToken": "synthetic"})
        else:
            with pytest.raises(type(failure) if failure is not None else AgentBuilderError):
                client.update_components_once(TARGET.agent_id, {"changeToken": "synthetic"})
        assert isolated.request.call_count == 1
        assert isolated.request.call_args.kwargs["allow_redirects"] is False
        assert isolated.mount.call_args.args[1].max_retries.total == 0
        assert client.session.get_adapter("https://") is shared_adapter
        assert shared_adapter.max_retries.total == 3
    finally:
        client.session.close()


@pytest.mark.parametrize("status", [200, 307, 400, 409, 429, 500])
def test_topic_client_preserves_http_status_without_replay(monkeypatch, status):
    client = TopicActionsClient(
        TARGET.environment_id, TARGET.agent_id, TARGET.tenant_id,
        host=dev_native_backend().client.host, ring="test",
        token="private-token", account="synthetic-maker",
    )
    expected = build_state_payload(operation_evidence(), plan_catalog_actions(operation_evidence().snapshot, "enable"))
    isolated = Mock()
    isolated.__enter__ = Mock(return_value=isolated)
    isolated.__exit__ = Mock(return_value=False)
    isolated.request.return_value.status_code = status
    isolated.request.return_value.json.return_value = {}
    monkeypatch.setattr("topic_actions_client.requests.Session", Mock(return_value=isolated))
    if status == 200:
        client.submit_state_payload(expected)
    else:
        with pytest.raises(AgentBuilderHTTPError) as error:
            client.submit_state_payload(expected)
        assert error.value.status_code == status
    assert isolated.request.call_count == 1
    assert isolated.request.call_args.kwargs["json"] == expected
    assert isolated.request.call_args.kwargs["allow_redirects"] is False
    assert isolated.mount.call_args.args[1].max_retries.total == 0
    with pytest.raises(ValueError, match="already consumed"):
        client.submit_state_payload(expected)
    assert isolated.request.call_count == 1


def test_topic_client_sends_reviewed_payload_without_extra_reads_or_mutation(monkeypatch):
    client = TopicActionsClient(
        TARGET.environment_id, TARGET.agent_id, TARGET.tenant_id,
        host=dev_native_backend().client.host, ring="test",
        token="private-token", account="synthetic-maker",
    )
    evidence = operation_evidence()
    payload = build_state_payload(evidence, plan_catalog_actions(evidence.snapshot, "enable"))
    original = deepcopy(payload)
    events = []
    def request(*args, **kwargs):
        events.append("submit")
        assert kwargs["body"] == original
        return Mock(status_code=200), {}
    monkeypatch.setattr(client, "read_components", lambda: pytest.fail("No unreviewed reread."))
    monkeypatch.setattr(client, "_request", request)
    client.submit_state_payload(payload)
    assert events == ["submit"]
    assert payload == original


@pytest.mark.parametrize("failure", [requests.Timeout("private"), requests.ConnectionError("private")])
def test_topic_client_does_not_wrap_or_replay_transport_failure(monkeypatch, failure):
    client = TopicActionsClient(
        TARGET.environment_id, TARGET.agent_id, TARGET.tenant_id,
        host=dev_native_backend().client.host, ring="test",
        token="private-token", account="synthetic-maker",
    )
    isolated = Mock()
    isolated.__enter__ = Mock(return_value=isolated)
    isolated.__exit__ = Mock(return_value=False)
    isolated.request.side_effect = failure
    monkeypatch.setattr("topic_actions_client.requests.Session", Mock(return_value=isolated))
    with pytest.raises(type(failure)):
        client.submit_state_payload({"changeToken": "synthetic"})
    with pytest.raises(ValueError, match="already consumed"):
        client.submit_state_payload({"changeToken": "synthetic"})
    assert isolated.request.call_count == 1


def test_read_only_topic_client_refuses_submission_without_network(monkeypatch):
    client = TopicActionsClient(
        TARGET.environment_id, TARGET.agent_id, TARGET.tenant_id,
        host=dev_native_backend().client.host, ring="test",
        token="private-token", account="synthetic-maker", read_only=True,
    )
    request = Mock(side_effect=AssertionError("Preview cannot submit."))
    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(ValueError):
        client.submit_state_payload({"changeToken": "synthetic"})
    request.assert_not_called()


@pytest.mark.parametrize("body", [None, [], "private-response"])
def test_topic_client_rejects_non_object_component_reads(monkeypatch, body):
    client = TopicActionsClient(
        TARGET.environment_id, TARGET.agent_id, TARGET.tenant_id,
        host=dev_native_backend().client.host, ring="test",
        token="private-token", account="synthetic-maker",
    )
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: (Mock(status_code=200), body))
    with pytest.raises(AgentBuilderError, match="unexpected payload"):
        client.read_components()


@pytest.mark.parametrize("status", [200, 307, 403])
def test_topic_client_read_uses_native_post_and_does_not_follow_redirects(monkeypatch, status):
    client = TopicActionsClient(
        TARGET.environment_id, TARGET.agent_id, TARGET.tenant_id,
        host=dev_native_backend().client.host, ring="test",
        token="private-token", account="synthetic-maker",
    )
    isolated = Mock()
    isolated.__enter__ = Mock(return_value=isolated)
    isolated.__exit__ = Mock(return_value=False)
    isolated.request.return_value.status_code = status
    body = operation_evidence().body
    isolated.request.return_value.json.return_value = body
    monkeypatch.setattr("topic_actions_client.requests.Session", Mock(return_value=isolated))
    if status == 200:
        assert client.read_components() == body
    else:
        with pytest.raises(AgentBuilderHTTPError) as error:
            client.read_components()
        assert error.value.status_code == status
    isolated.request.assert_called_once()
    assert isolated.request.call_args.args == ("POST", client._components_url)
    assert isolated.request.call_args.kwargs["json"] == {}
    assert isolated.request.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("action", ["enable", "disable"])
@pytest.mark.parametrize("generated_changes", [False, True])
def test_native_controller_executes_through_topic_owned_client(monkeypatch, action, generated_changes):
    backend = dev_native_backend(
        before={"a": "On", "shared": "On"} if action == "disable" else None,
    )
    remote = deepcopy(next(backend.components.read_components.side_effect))
    if generated_changes:
        before, after = server_generated_readback(action)
        remote["botComponentChanges"] = deepcopy(before.body["botComponentChanges"])
    components = TopicActionsClient(
        TARGET.environment_id, TARGET.agent_id, TARGET.tenant_id,
        ring=backend.client.ring, host=backend.client.host,
        token="private-token", account=backend.account_id,
    )
    backend.components = components
    writes = []
    def request(method, url, **kwargs):
        assert url == components._components_url
        if method == "PUT":
            payload = kwargs["body"]
            writes.append(deepcopy(payload))
            changes = {row["component"]["id"]: row for row in payload["botComponentChanges"]}
            remote["botComponentChanges"] = [
                {"$kind": "BotComponentInsert", "component": deepcopy(changes[row["component"]["id"]]["component"])}
                if row["component"]["id"] in changes else row
                for row in remote["botComponentChanges"]
            ]
            if generated_changes:
                remote["botComponentChanges"] = deepcopy(after.body["botComponentChanges"])
            remote["changeToken"] = "r2"
            return Mock(status_code=200), {}
        assert method == "POST"
        return Mock(status_code=200), deepcopy(remote)
    monkeypatch.setattr(components, "_request", request)
    result = TopicActionSession(backend, action).run(lambda _: "approve")
    assert result["completed"] and result["status"] == "completed"
    assert len(writes) == 1
    assert {row["component"]["id"] for row in writes[0]["botComponentChanges"]} == {"a", "shared"}
    assert all(topic["state"] == ("On" if action == "enable" else "Off") for topic in result["topics"])
    backend.client.fetch_components.assert_not_called()
    backend.client.update_components_once.assert_not_called()


@pytest.mark.parametrize(("field", "value"), [
    ("tenant_id", TARGET.agent_id),
    ("environment_id", TARGET.agent_id),
    ("bot_id", TARGET.tenant_id),
    ("host", "https://another.invalid"),
    ("ring", "prod"),
    ("signed_in_username", "another-maker"),
    ("single_attempt", False),
])
def test_topic_component_client_must_remain_bound_to_reviewed_target_and_account(field, value):
    backend = dev_native_backend()
    packet = backend.read()
    payload = build_state_payload(packet, plan_catalog_actions(packet.snapshot, "enable"))
    setattr(backend.components, field, value)
    with pytest.raises(ValueError, match="not admitted"):
        backend.submit_once(TARGET.agent_id, payload)
    backend.components.submit_state_payload.assert_not_called()
