# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure controller/transport tests, not evidence of native API qualification."""

from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest
import requests

from agentbuilder import AgentBuilderClient, AgentBuilderError
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
    native = NativeActionBackend(client, TARGET, ("alpha",), parse_catalog(catalog_document()), "maker")
    with pytest.raises(ValueError, match="not admitted"):
        native.submit_once(TARGET.agent_id, {})
    client.update_components_once.assert_not_called()


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
