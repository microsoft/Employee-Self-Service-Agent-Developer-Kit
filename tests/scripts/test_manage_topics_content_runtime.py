# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Add of content-backed topic sets through the native controller, with synthetic evidence."""

from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
import requests

from agentbuilder import AgentBuilderHTTPError
from manage_topics_catalog import load_catalog, parse_catalog
from manage_topics_execution import ManageTopicsSession
from tests.scripts.test_manage_topics_runtime import TARGET, dev_native_backend


def content_native_backend(*, present=(), realm="dev", action="add"):
    backend = dev_native_backend(realm=realm, selected=("diagnostics",))
    backend.catalog = load_catalog()
    backend.action = action
    package = backend.catalog.document()["packages"][0]
    schema = package["agentSchemaNames"][0]
    backend.client.get_agent.return_value["schemaName"] = schema
    backend.client.get_dev_configuration.return_value = {
        "realm": realm, "cdsBotId": TARGET.agent_id, "schemaName": schema,
        "grsRepositoryId": "synthetic-family",
    }
    body = {
        "bot": {"cdsBotId": TARGET.agent_id, "schemaName": schema},
        "changeToken": "content-r1",
        "botComponentChanges": [{
            "$kind": "BotComponentInsert", "component": {
                "$kind": "DialogComponent", "id": "unrelated", "parentBotId": TARGET.agent_id,
                "schemaName": f"{schema}.topic.unrelated", "state": "Active", "status": "Active",
                "version": 7, "dialog": {"$kind": "AdaptiveDialog", "comment": "Keep this topic."},
            },
        }],
    }
    names = {
        "System-DiagnoseReport": "[System] - Diagnose Report",
        "System-RecordSearchResults": "[System] - Record Search Results",
    }
    for stem in present:
        body["botComponentChanges"].append({
            "$kind": "BotComponentInsert", "component": {
                "$kind": "DialogComponent", "id": f"template-{stem}",
                "parentBotId": TARGET.agent_id, "schemaName": f"{schema}.topic.{stem}",
                "displayName": names[stem], "state": "Inactive", "status": "Inactive",
                "version": 12, "dialog": {"$kind": "AdaptiveDialog", "comment": stem},
            },
        })
    inserted_ids = set()

    def read():
        snapshot = deepcopy(body)
        for row in snapshot.get("botComponentChanges") or ():
            if row["component"]["id"] in inserted_ids:
                row["component"].setdefault("version", 1)
        return snapshot

    backend.components.read_components.side_effect = read

    def submit(payload):
        for row in payload["botComponentChanges"]:
            if row["$kind"] == "BotComponentInsert":
                body["botComponentChanges"].append(deepcopy(row))
                inserted_ids.add(row["component"]["id"])
            elif row["$kind"] == "BotComponentUpdate":
                for existing in body["botComponentChanges"]:
                    if existing["component"]["id"].casefold() == row["component"]["id"].casefold():
                        existing["component"] = deepcopy(row["component"])
        body["changeToken"] = "content-r2"

    backend.components.submit_state_payload.side_effect = submit
    return backend, body


def converted_topic_content(items):
    return [{
        "key": item["key"], "success": True, "elementType": "AdaptiveDialog",
        "objectModel": {"$kind": "AdaptiveDialog", "comment": item["key"].rsplit(".topic.", 1)[-1]},
    } for item in items]


def test_add_reviews_then_inserts_the_whole_set_off_without_touching_other_topics(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, body = content_native_backend()
    original = deepcopy(body["botComponentChanges"])
    reviews = []

    def approve(review):
        backend.components.submit_state_payload.assert_not_called()
        reviews.append(deepcopy(review))
        return "approve"

    result = ManageTopicsSession(backend, "add").run(approve)

    assert result["status"] == "completed" and result["completed"]
    assert result["preservationStatus"] == "verified"
    backend.components.submit_state_payload.assert_called_once()
    payload = backend.components.submit_state_payload.call_args.args[0]
    assert payload["changeToken"] == "content-r1"
    rows = payload["botComponentChanges"]
    schema = body["bot"]["schemaName"]
    assert {row["component"]["schemaName"] for row in rows} == {
        f"{schema}.topic.System-DiagnoseReport", f"{schema}.topic.System-RecordSearchResults",
    }
    assert {row["component"]["displayName"] for row in rows} == {
        "[System] - Diagnose Report", "[System] - Record Search Results",
    }
    for row in rows:
        component = row["component"]
        assert row["$kind"] == "BotComponentInsert"
        assert component["$kind"] == "DialogComponent"
        assert component["state"] == component["status"] == "Inactive"
        assert component["extensionData"] == {"UseProvidedBotComponentId": True}
        assert component["dialog"] == {
            "$kind": "AdaptiveDialog", "comment": component["schemaName"].rsplit(".topic.", 1)[-1],
        }
    assert len(rows) == 2 and body["botComponentChanges"][0] == original[0]
    assert {row["component"]["id"] for row in rows} == {
        row["componentId"] for row in reviews[0]["proposedChanges"]
    }
    assert all(value == [] for key, value in payload.items() if key not in ("changeToken", "botComponentChanges"))
    assert "Add the 2 topics" in reviews[0]["approvalQuestion"]["question"]
    # A disabled add is harmless to publish, so the review must not read as a publish requirement.
    assert (
        "Changes stay in the agent's draft. Microsoft 365 Copilot sees them only after you publish "
        "in Copilot Studio." in reviews[0]["userMessage"]
    )
    assert "must be published" not in reviews[0]["userMessage"]
    assert "draft" in result["userMessage"] and "Copilot Studio" in result["userMessage"]
    assert len(result["topics"]) == 2
    assert "additions" in result["message"]


@pytest.mark.parametrize("realm", ["test", "prod", None, 1, 2])
def test_content_actions_require_an_alm_enrolled_development_target(monkeypatch, realm):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, _ = content_native_backend(realm=realm)
    result = ManageTopicsSession(backend, "add").run(lambda _: pytest.fail("Unsafe target cannot be approved."))
    assert result["status"] == "blocked"
    assert "dev_alm_required" in result["blockers"]
    assert "Development" in result["userMessage"] and "ALM" in result["userMessage"]
    assert "No topics were changed" in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("problem", ["partial", "content", "duplicate", "wrong_kind", "schema_case"])
def test_add_refuses_an_existing_unsafe_set_and_names_the_member(monkeypatch, problem):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, body = content_native_backend(present=("System-DiagnoseReport",))
    component = body["botComponentChanges"][-1]["component"]
    if problem == "content":
        component["dialog"]["comment"] = "Maker edited this topic."
    elif problem == "duplicate":
        duplicate = deepcopy(body["botComponentChanges"][-1])
        duplicate["component"]["id"] = "duplicate"
        body["botComponentChanges"].append(duplicate)
    elif problem == "wrong_kind":
        component["$kind"] = "GlobalVariableComponent"
    elif problem == "schema_case":
        component["schemaName"] = component["schemaName"].upper()
    result = ManageTopicsSession(backend, "add").run(lambda _: pytest.fail("Unsafe content cannot be approved."))
    assert result["status"] == "blocked"
    assert "System-DiagnoseReport" in result["userMessage"]
    assert "No topics were changed" in result["userMessage"]
    if problem == "partial":
        assert "Delete the present topics of this set in Copilot Studio, then run add again." in result["userMessage"]
        assert "remove" not in result["userMessage"].lower()
    elif problem == "content":
        assert "differs" in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_add_equal_template_content_is_noop_and_points_to_enable(monkeypatch, enabled):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, body = content_native_backend(present=("System-DiagnoseReport", "System-RecordSearchResults"))
    for row in body["botComponentChanges"][1:]:
        row["component"]["state"] = row["component"]["status"] = "Active" if enabled else "Inactive"
        row["component"]["dialog"]["diagnostics"] = [{"message": "server metadata"}]
    result = ManageTopicsSession(backend, "add").run(lambda _: pytest.fail("Existing content needs no approval."))
    assert result["status"] == "already_correct" and result["completed"]
    assert "Use enable to turn them on, or turn them on in Copilot Studio." in result["userMessage"]
    assert "No topics were changed" in result["userMessage"]
    assert "draft" not in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("missing_runtime", [False, True])
def test_content_conversion_failure_never_writes_or_exposes_content(monkeypatch, missing_runtime):
    from agentbuilder_object_model import ObjectModelConverterError
    converter = Mock(side_effect=ObjectModelConverterError("private topic text")) if missing_runtime else Mock(
        return_value=[{"key": "bad", "success": False, "error": "private topic text"}],
    )
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converter)
    backend, _ = content_native_backend()
    result = ManageTopicsSession(backend, "add").run(lambda _: pytest.fail("Conversion failed."))
    assert result["status"] == "blocked"
    assert "Object Model" in result["userMessage"]
    assert "install_agentbuilder_object_model.py" in result["userMessage"]
    assert "private topic text" not in json.dumps(result)
    assert "No topics were changed" in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


@pytest.mark.parametrize("diagnostic,blocks", [
    ({"errorCode": "invalid"}, True), ({"$kind": "ExpressionError"}, True),
    ({"$kind": "ExpressionWarning"}, False),
])
def test_add_leaves_inserted_topics_off_when_service_reports_errors(monkeypatch, diagnostic, blocks):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, body = content_native_backend()
    submit = backend.components.submit_state_payload.side_effect

    def with_diagnostic(payload):
        submit(payload)
        body["botComponentChanges"][-1]["component"]["dialog"]["diagnostics"] = [diagnostic]

    backend.components.submit_state_payload.side_effect = with_diagnostic
    result = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert result["completed"] is not blocks
    assert result["status"] == ("partial" if blocks else "completed")
    assert all(row["component"]["state"] == "Inactive" for row in body["botComponentChanges"][1:])
    assert "draft" in result["userMessage"]
    if blocks:
        assert "blocking" in result["userMessage"].lower()
        assert (
            "The inserted topics remain off. Delete them in Copilot Studio before trying add again."
            in result["userMessage"]
        )
        assert "remove" not in result["userMessage"].lower()
    backend.components.submit_state_payload.assert_called_once()


@pytest.mark.parametrize("failure", ["missing", "malformed", "partial", "wrong_id", "outside_changed", "timeout", "conflict"])
def test_add_never_claims_success_or_loses_planned_rows_on_failed_readback(monkeypatch, failure):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, body = content_native_backend()
    submit = backend.components.submit_state_payload.side_effect

    def fail(payload):
        submit(payload)
        if failure == "missing":
            body.pop("botComponentChanges")
        elif failure == "malformed":
            body["botComponentChanges"] = {}
        elif failure == "partial":
            body["botComponentChanges"].pop()
        elif failure == "wrong_id":
            body["botComponentChanges"][-1]["component"]["id"] = "unexpected-id"
        elif failure == "outside_changed":
            body["botComponentChanges"][0]["component"]["dialog"]["comment"] = "changed"
        elif failure == "timeout":
            raise requests.Timeout("private")
        else:
            raise AgentBuilderHTTPError("private", 409)

    backend.components.submit_state_payload.side_effect = fail
    result = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert not result["completed"]
    assert len(result["topics"]) == 2
    assert "draft" in result["userMessage"]
    if failure == "partial":
        assert "delete the inserted topics in Copilot Studio" in result["userMessage"]
        assert "remove" not in result["userMessage"].lower()
    backend.components.submit_state_payload.assert_called_once()


@pytest.mark.parametrize("drift", ["schema", "family", "before_submit"])
def test_add_rechecks_dev_family_before_every_write(monkeypatch, drift):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, _ = content_native_backend()
    valid = deepcopy(backend.client.get_dev_configuration.return_value)
    invalid = deepcopy(valid)
    if drift == "schema":
        invalid["schemaName"] = "different.agent"
    else:
        invalid.pop("grsRepositoryId")
    if drift == "before_submit":
        backend.client.get_dev_configuration.side_effect = [valid] * 5 + [invalid]
    else:
        backend.client.get_dev_configuration.return_value = invalid
    result = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert not result["completed"]
    assert result["writeStatus"] == "not_attempted"
    assert "No topics were changed" in result["userMessage"]
    assert "draft" not in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


def test_content_preview_says_nothing_changed_and_does_not_request_publish(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, _ = content_native_backend()
    result = ManageTopicsSession(backend, "add").run(None, preview=True)
    assert result["status"] == "preview"
    assert "No topics were changed" in result["userMessage"]
    assert "publish in Copilot Studio" not in result["userMessage"]
    assert "draft" not in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


def test_content_admission_read_failure_is_not_reported_as_a_submission(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, _ = content_native_backend()
    valid = deepcopy(backend.client.get_dev_configuration.return_value)
    backend.client.get_dev_configuration.side_effect = [valid] * 5 + [requests.Timeout("private")]
    result = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert result["writeStatus"] == "not_attempted"
    assert "No topics were changed" in result["userMessage"]
    assert "draft" not in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


def test_content_initial_read_failure_says_nothing_changed(monkeypatch):
    backend, _ = content_native_backend()
    backend.components.read_components.side_effect = requests.Timeout("private")
    result = ManageTopicsSession(backend, "add").run(lambda _: pytest.fail("No review without evidence."))
    assert result["writeStatus"] == "not_attempted"
    assert "No topics were changed" in result["userMessage"]
    assert "draft" not in result["userMessage"]


def test_shipped_content_add_with_real_converter_offline():
    from agentbuilder_object_model import ObjectModelConverterError, validate_object_model_runtime

    try:
        validate_object_model_runtime()
    except ObjectModelConverterError as error:
        pytest.skip(str(error))
    backend, body = content_native_backend()
    added = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert added["completed"], added
    assert len(body["botComponentChanges"]) == 3
    assert all(row["component"]["dialog"]["$kind"] == "AdaptiveDialog" for row in body["botComponentChanges"])
    backend.components.submit_state_payload.assert_called_once()


@pytest.mark.parametrize("action", ["enable", "disable"])
def test_diagnostics_state_actions_do_not_use_the_converter_or_dev_gate(monkeypatch, action):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", Mock(side_effect=AssertionError("No converter")))
    backend, body = content_native_backend(
        present=("System-DiagnoseReport", "System-RecordSearchResults"), realm="prod", action=None,
    )
    initial = "Inactive" if action == "enable" else "Active"
    for row in body["botComponentChanges"][1:]:
        row["component"]["state"] = row["component"]["status"] = initial

    def submit(payload):
        for update in payload["botComponentChanges"]:
            for row in body["botComponentChanges"]:
                if row["component"]["id"] == update["component"]["id"]:
                    row["component"] = deepcopy(update["component"])

    backend.components.submit_state_payload.side_effect = submit
    result = ManageTopicsSession(backend, action).run(lambda _: "approve")
    assert result["completed"]
    backend.client.get_dev_configuration.assert_not_called()
    backend.components.submit_state_payload.assert_called_once()


def test_content_version_drift_requires_new_approval(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, body = content_native_backend()

    def approve(review):
        body["botComponentChanges"][-1]["component"]["version"] = 99
        return "approve"

    result = ManageTopicsSession(backend, "add").run(approve)
    assert result["status"] == "review_required"
    assert "evidence_changed" in result["blockers"]
    assert result["writeStatus"] == "not_attempted"
    backend.components.submit_state_payload.assert_not_called()


def test_content_approval_expiry_never_dispatches(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, _ = content_native_backend()
    now = [0]

    def approve(review):
        now[0] = 301
        return "approve"

    result = ManageTopicsSession(backend, "add", clock=lambda: now[0]).run(approve)
    assert result["status"] == "review_required"
    assert "approval_expired" in result["blockers"]
    assert "No topics were changed" in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


def test_content_backend_rejects_tampered_approved_payload(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, _ = content_native_backend()
    submit = backend.submit_once

    def tamper(agent_id, payload):
        changed = deepcopy(payload)
        changed["botComponentChanges"][0]["component"]["dialog"]["comment"] = "unapproved edit"
        return submit(agent_id, changed)

    backend.submit_once = tamper
    result = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert not result["completed"]
    assert result["writeStatus"] == "not_attempted"
    assert "No topics were changed" in result["userMessage"]
    backend.components.submit_state_payload.assert_not_called()


def test_content_actions_refuse_unsupported_agent_schema(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, body = content_native_backend()
    body["bot"]["schemaName"] = "unsupported.agent"
    backend.client.get_agent.return_value["schemaName"] = "unsupported.agent"
    backend.client.get_dev_configuration.return_value["schemaName"] = "unsupported.agent"
    result = ManageTopicsSession(backend, "add").run(lambda _: pytest.fail("No supported source family."))
    assert result["status"] == "blocked"
    assert "ambiguous_or_unsupported_set:diagnostics" in result["blockers"]
    assert result["writeStatus"] == "not_attempted"
    backend.components.submit_state_payload.assert_not_called()


def test_content_changes_after_approval_invalidate_the_review(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, _ = content_native_backend()

    def approve(review):
        def changed(items):
            results = converted_topic_content(items)
            results[0]["objectModel"]["comment"] = "different conversion"
            return results
        monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", changed)
        return "approve"

    result = ManageTopicsSession(backend, "add").run(approve)
    assert result["status"] == "review_required"
    assert "evidence_changed" in result["blockers"]
    backend.components.submit_state_payload.assert_not_called()


def test_content_actions_submit_shared_members_once_for_multiple_sets(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, _ = content_native_backend()
    document = backend.catalog.document()
    second = deepcopy(next(item for item in document["sets"] if item["key"] == "diagnostics"))
    second["key"] = "other-diagnostics"
    document["sets"].append(second)
    backend.catalog = parse_catalog(document)
    backend.selected_keys = ("diagnostics", "other-diagnostics")
    result = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert result["completed"], result
    payload = backend.components.submit_state_payload.call_args.args[0]
    assert len(payload["botComponentChanges"]) == 2
    assert len(result["topics"]) == 2


def test_add_does_not_claim_failed_topics_are_off_when_readback_reports_on(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, body = content_native_backend()
    submit = backend.components.submit_state_payload.side_effect

    def unexpectedly_active(payload):
        submit(payload)
        component = body["botComponentChanges"][-1]["component"]
        component["state"] = component["status"] = "Active"
        component["dialog"]["diagnostics"] = [{"errorCode": "invalid"}]

    backend.components.submit_state_payload.side_effect = unexpectedly_active
    result = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert not result["completed"]
    assert "remain off" not in result["userMessage"]
    assert "disable" in result["userMessage"].lower()
    assert "remove" not in result["userMessage"].lower()


def test_content_actions_cannot_reuse_a_state_only_backend(monkeypatch):
    backend = dev_native_backend()
    result = ManageTopicsSession(backend, "add").run(lambda _: pytest.fail("No content evidence."))
    assert result["status"] == "blocked"
    assert not result["completed"]
    backend.components.submit_state_payload.assert_not_called()


def test_add_result_states_the_verified_count_the_changed_agent_and_how_to_turn_them_on(monkeypatch):
    # Makers check the count and target before publishing, as they do after enable/disable.
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, _ = content_native_backend()
    result = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert result["completed"], result
    lines = result["userMessage"].splitlines()
    assert "**2 topics added and verified.**" in lines
    assert f"- Agent: {TARGET.agent_id}" in lines
    assert f"- Environment: {TARGET.environment_id}" in lines
    assert "Use enable to turn them on, or turn them on in Copilot Studio." in lines


def test_partial_add_explains_the_unverified_topics_under_next_steps(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, body = content_native_backend()
    submit = backend.components.submit_state_payload.side_effect

    def one_enabled(payload):
        submit(payload)
        component = body["botComponentChanges"][-1]["component"]
        component["state"] = component["status"] = "Active"

    backend.components.submit_state_payload.side_effect = one_enabled
    result = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert result["status"] == "partial"
    message = result["userMessage"]
    assert "Requested states observed: 1/2 topics." in message
    assert "Some requested topic states could not be verified. Full completion is not confirmed." in message
    steps = message.split("**NEXT STEPS**", 1)[1]
    assert "delete the inserted topics in Copilot Studio" in steps
    assert "remove" not in message.lower()


def test_add_reports_changed_outside_content_as_a_preservation_failure(monkeypatch):
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    backend, body = content_native_backend()
    submit = backend.components.submit_state_payload.side_effect

    def change_outside(payload):
        submit(payload)
        body["botComponentChanges"][0]["component"]["dialog"]["comment"] = "changed"

    backend.components.submit_state_payload.side_effect = change_outside
    result = ManageTopicsSession(backend, "add").run(lambda _: "approve")
    assert not result["completed"]
    assert (
        "Other content, topic membership or outside-scope states did not match the reviewed evidence."
        in result["userMessage"]
    )


def test_the_session_refuses_remove():
    # Deleting components stays a maker action in Copilot Studio; this command only inserts.
    backend, _ = content_native_backend()
    with pytest.raises(ValueError):
        ManageTopicsSession(backend, "remove")
    backend.components.submit_state_payload.assert_not_called()
