# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Content-backed catalog behavior through the topic-actions entry point."""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from unittest.mock import Mock

import pytest

import topic_actions as entry
import topic_actions_catalog as catalogs
from tests.scripts.test_topic_actions_content_runtime import content_native_backend, converted_topic_content
from tests.scripts.test_topic_actions_runtime import TARGET, dev_native_backend


REFERENCE = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "src" / "reference" / "topic-actions"


@pytest.fixture(autouse=True)
def forbid_auth(monkeypatch):
    monkeypatch.setattr(entry, "authenticate_flightcheck", lambda *a, **k: pytest.fail("Authentication must be explicitly stubbed."))


@pytest.fixture
def content_catalog(tmp_path, monkeypatch):
    document = json.loads((REFERENCE / "catalog.provisional.json").read_text(encoding="utf-8"))
    topic_set = next(item for item in document["sets"] if item["key"] == "diagnostics")
    topic_set["contentFolder"] = "diagnostics"
    root = tmp_path / "content"
    folder = root / "diagnostics"
    folder.mkdir(parents=True)
    for stem in ("System-RecordSearchResults", "System-DiagnoseReport"):
        (folder / f"{stem}.mcs.yml").write_text("kind: AdaptiveDialog\n", encoding="utf-8")
    import topic_actions_content
    monkeypatch.setattr(topic_actions_content, "CONTENT_ROOT", root)
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    load = catalogs.load_catalog
    monkeypatch.setattr(catalogs, "load_catalog", lambda: load(path))
    return path, folder


def test_source_listing_includes_diagnostics_without_claiming_live_presence(capsys):
    assert entry.main(["--list-sets"]) == 0
    result = json.loads(capsys.readouterr().out.removeprefix(entry.RESULT_MARKER))
    assert result["status"] == "source_catalog_only"
    assert result["writeStatus"] == "not_attempted"
    assert {"key": "diagnostics", "name": "Topics"} in result["sets"]
    assert "availability" in result["userMessage"].lower()


def test_source_listing_accepts_complete_content_without_a_converter(content_catalog, capsys):
    assert entry.main(["--list-sets"]) == 0
    result = json.loads(capsys.readouterr().out.removeprefix(entry.RESULT_MARKER))
    assert result["status"] == "source_catalog_only"
    assert {"key": "diagnostics", "name": "Topics"} in result["sets"]


@pytest.mark.parametrize("folder_name", ["../outside", "missing", "absolute"])
def test_source_listing_rejects_missing_or_escaped_content_root(content_catalog, capsys, folder_name):
    path, folder = content_catalog
    outside = path.parent / "outside"
    outside.mkdir()
    document = json.loads(path.read_text(encoding="utf-8"))
    topic_set = next(item for item in document["sets"] if item["key"] == "diagnostics")
    topic_set["contentFolder"] = str(outside) if folder_name == "absolute" else folder_name
    path.write_text(json.dumps(document), encoding="utf-8")

    assert entry.main(["--list-sets"]) == 1
    result = json.loads(capsys.readouterr().out.removeprefix(entry.RESULT_MARKER))
    assert result["reason"] in ("invalid_content_path", "content_unreadable")
    assert result["writeStatus"] == "not_attempted"


@pytest.mark.parametrize("problem", ["missing", "extra", "different_variant", "duplicate_stem"])
def test_source_listing_rejects_content_that_cannot_cover_exact_members(content_catalog, capsys, problem):
    path, folder = content_catalog
    if problem == "missing":
        (folder / "System-DiagnoseReport.mcs.yml").unlink()
    elif problem == "extra":
        (folder / "Unexpected.mcs.yml").write_text("kind: AdaptiveDialog\n", encoding="utf-8")
    else:
        document = json.loads(path.read_text(encoding="utf-8"))
        topic_set = next(item for item in document["sets"] if item["key"] == "diagnostics")
        variant = topic_set["sourceVariants"][1]
        if problem == "different_variant":
            variant["memberSchemaNames"].pop()
        else:
            package = document["packages"][1]
            alias = "another.topic.System-DiagnoseReport"
            package["topics"].append({"schemaName": alias, "classification": "unknown", "required": None})
            variant["memberSchemaNames"].append(alias)
        path.write_text(json.dumps(document), encoding="utf-8")

    assert entry.main(["--list-sets"]) == 1
    result = json.loads(capsys.readouterr().out.removeprefix(entry.RESULT_MARKER))
    assert result["reason"] == "content_members_mismatch"
    assert result["writeStatus"] == "not_attempted"


def diagnostics_transport(monkeypatch, *, action="enable", schema="gptagent_copilotforemployeeselfservicehr"):
    backend = dev_native_backend(selected=("diagnostics",))
    backend.client.session = Mock()
    before_state, after_state = ("Inactive", "Active") if action == "enable" else ("Active", "Inactive")
    before = {
        "bot": {"cdsBotId": TARGET.agent_id, "schemaName": schema},
        "changeToken": "r1",
        "botComponentChanges": [{
            "$kind": "BotComponentInsert",
            "component": {
                "$kind": "DialogComponent", "id": stem, "parentBotId": TARGET.agent_id,
                "displayName": "[System] - Record Search Results" if stem == "System-RecordSearchResults" else "[System] - Diagnose Report",
                "schemaName": f"{schema}.topic.{stem}", "state": before_state, "status": before_state,
                "dialog": {"$kind": "AdaptiveDialog", "id": stem},
            },
        } for stem in ("System-RecordSearchResults", "System-DiagnoseReport")],
    }
    after = deepcopy(before)
    after["changeToken"] = "r2"
    for row in after["botComponentChanges"]:
        row["component"].update(state=after_state, status=after_state)
    live = {"body": before}
    backend.components.read_components.side_effect = lambda: deepcopy(live["body"])
    backend.components.submit_state_payload.side_effect = lambda payload: live.update(body=after)
    monkeypatch.setattr(entry, "_workspace_target", lambda *a, **k: {
        "ring": "test", "host": backend.client.host, "api_version": backend.client.api_version,
    })
    monkeypatch.setattr(entry, "authenticate_flightcheck", lambda *a, **k: (
        "private-token", TARGET.tenant_id, "synthetic-maker",
    ))
    monkeypatch.setattr(entry, "AgentBuilderClient", lambda *a, **k: backend.client)
    monkeypatch.setattr(entry, "TopicActionsClient", lambda *a, **k: backend.components)
    return backend.components


def invoke(workspace, args, monkeypatch, capsys, request=None):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(request or {})))
    code = entry.main(["--workspace-root", str(workspace), *args])
    result = json.loads(capsys.readouterr().out.removeprefix(entry.RESULT_MARKER))
    return code, result


def diagnostics_request(action="enable"):
    return {
        "contractVersion": 1,
        "target": {"tenantId": TARGET.tenant_id, "environmentId": TARGET.environment_id, "agentId": TARGET.agent_id},
        "action": action, "setKeys": ["diagnostics"], "entry": "direct",
    }


def content_transport(monkeypatch, *, schema=None):
    backend, body = content_native_backend()
    if schema is not None:
        body["bot"]["schemaName"] = schema
        body["botComponentChanges"][0]["component"]["schemaName"] = f"{schema}.topic.unrelated"
        backend.client.get_agent.return_value["schemaName"] = schema
        backend.client.get_dev_configuration.return_value["schemaName"] = schema
    backend.client.session = Mock()
    monkeypatch.setattr(entry, "_workspace_target", lambda *a, **k: {
        "ring": "test", "host": backend.client.host, "api_version": backend.client.api_version,
    })
    monkeypatch.setattr(entry, "authenticate_flightcheck", lambda *a, **k: (
        "private-token", TARGET.tenant_id, "synthetic-maker",
    ))
    monkeypatch.setattr(entry, "AgentBuilderClient", lambda *a, **k: backend.client)
    monkeypatch.setattr(entry, "TopicActionsClient", lambda *a, **k: backend.components)
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", converted_topic_content)
    return backend.components, body


def test_added_topics_can_be_enabled_from_the_stored_insert(tmp_path, monkeypatch, capsys):
    components, body = content_transport(monkeypatch)
    code, review = invoke(tmp_path, ["--review"], monkeypatch, capsys, diagnostics_request("add"))
    assert code == 0 and review["status"] == "review_ready"
    code, added = invoke(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], monkeypatch, capsys)
    assert code == 0 and added["completed"], added
    inserted = components.submit_state_payload.call_args.args[0]["botComponentChanges"]
    assert body["botComponentChanges"][1:] == inserted

    code, review = invoke(tmp_path, ["--review"], monkeypatch, capsys, diagnostics_request("enable"))
    assert code == 0 and review["status"] == "review_ready"
    code, enabled = invoke(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], monkeypatch, capsys)
    assert code == 0 and enabled["completed"], enabled
    assert components.submit_state_payload.call_count == 2
    updates = components.submit_state_payload.call_args.args[0]["botComponentChanges"]
    assert {row["component"]["id"] for row in updates} == {row["component"]["id"] for row in inserted}
    for row in updates:
        assert row["$kind"] == "BotComponentUpdate"
        assert row["component"]["parentBotId"] == TARGET.agent_id
        assert row["component"]["state"] == row["component"]["status"] == "Active"


@pytest.mark.parametrize("schema", [
    "gptagent_copilotforemployeeselfservicehr", "msdyn_copilotforemployeeselfservicedahr",
    "msdyn_copilotforemployeeselfservicedait", "gptagent_copilotforemployeeselfserviceit",
])
def test_add_preserves_template_topic_fields_for_each_agent_family(tmp_path, monkeypatch, capsys, schema):
    components, body = content_transport(monkeypatch, schema=schema)
    code, review = invoke(tmp_path, ["--review"], monkeypatch, capsys, diagnostics_request("add"))
    assert code == 0 and review["status"] == "review_ready"
    code, result = invoke(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], monkeypatch, capsys)
    assert code == 0 and result["completed"], result
    descriptions = {
        f"{schema}.topic.System-RecordSearchResults": "Stores the tool calls and search results of an answer, so that /diagnose can show them.",
        f"{schema}.topic.System-DiagnoseReport": "Shows the evidence behind the previous answer when the user types /diagnose.",
    }
    rows = components.submit_state_payload.call_args.args[0]["botComponentChanges"]
    assert {row["component"]["schemaName"] for row in rows} == set(descriptions)
    assert body["botComponentChanges"][1:] == rows
    for row in rows:
        component = row["component"]
        assert component["parentBotId"] == TARGET.agent_id
        assert component["description"] == descriptions[component["schemaName"]]
        assert component["managedProperties"] == {
            "$kind": "ManagedProperties", "isManaged": False, "isCustomizable": True,
        }
        assert component["shareContext"] == {"$kind": "ContentShareContext"}


def test_second_add_reports_no_change_needed_without_another_write(tmp_path, monkeypatch, capsys):
    components, _ = content_transport(monkeypatch)
    code, review = invoke(tmp_path, ["--review"], monkeypatch, capsys, diagnostics_request("add"))
    assert code == 0 and review["status"] == "review_ready"
    code, added = invoke(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], monkeypatch, capsys)
    assert code == 0 and added["completed"], added

    code, result = invoke(tmp_path, ["--review"], monkeypatch, capsys, diagnostics_request("add"))
    assert code == 0 and result["status"] == "already_correct"
    assert result["userMessage"].splitlines()[0] == "## No change needed."
    assert "No topics were changed." in result["userMessage"]
    assert "Use enable" in result["userMessage"]
    assert result["writeStatus"] == "not_attempted"
    components.submit_state_payload.assert_called_once()


@pytest.mark.parametrize("parent", ["missing", None])
def test_add_requires_the_stored_parent_and_enable_rejects_a_parentless_topic(tmp_path, monkeypatch, capsys, parent):
    components, body = content_transport(monkeypatch)
    submit = components.submit_state_payload.side_effect

    def lose_parent(payload):
        submit(payload)
        component = body["botComponentChanges"][-1]["component"]
        if parent == "missing":
            component.pop("parentBotId", None)
        else:
            component["parentBotId"] = parent

    components.submit_state_payload.side_effect = lose_parent
    code, review = invoke(tmp_path, ["--review"], monkeypatch, capsys, diagnostics_request("add"))
    assert code == 0 and review["status"] == "review_ready"
    code, added = invoke(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], monkeypatch, capsys)
    assert code == 1 and not added["completed"], added
    assert added["writeStatus"] == "submitted"
    assert added["status"] == "partial"
    assert any(topic["status"] == "unverified" for topic in added["topics"])

    code, review = invoke(tmp_path, ["--review"], monkeypatch, capsys, diagnostics_request("enable"))
    assert code == 0 and review["status"] == "review_ready"
    code, enabled = invoke(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], monkeypatch, capsys)
    assert code == 1 and enabled["status"] == "blocked"
    assert enabled["blockers"] == ["pre_dispatch_check_failed"]
    assert enabled["writeStatus"] == "not_attempted"
    assert components.submit_state_payload.call_count == 1
    assert all(row["component"]["state"] == "Inactive" for row in body["botComponentChanges"][1:])


@pytest.mark.parametrize("link_kind", ["folder", "file"])
def test_source_listing_rejects_symlink_content_outside_root(content_catalog, capsys, link_kind):
    path, folder = content_catalog
    outside = path.parent / "outside"
    outside.mkdir()
    if link_kind == "folder":
        target = folder.parent / "linked"
        target.symlink_to(outside, target_is_directory=True)
        document = json.loads(path.read_text(encoding="utf-8"))
        next(item for item in document["sets"] if item["key"] == "diagnostics")["contentFolder"] = "linked"
        path.write_text(json.dumps(document), encoding="utf-8")
    else:
        target = folder / "System-DiagnoseReport.mcs.yml"
        target.rename(outside / target.name)
        target.symlink_to(outside / target.name)

    assert entry.main(["--list-sets"]) == 1
    result = json.loads(capsys.readouterr().out.removeprefix(entry.RESULT_MARKER))
    assert result["reason"] == "invalid_content_path"
    assert result["writeStatus"] == "not_attempted"


@pytest.mark.parametrize("content_changed", [False, True])
def test_approval_is_bound_to_content_bytes(content_catalog, tmp_path, monkeypatch, capsys, content_changed):
    _, folder = content_catalog
    components = diagnostics_transport(monkeypatch)
    code, review = invoke(tmp_path, ["--review"], monkeypatch, capsys, diagnostics_request())
    assert code == 0 and review["status"] == "review_ready"
    components.submit_state_payload.assert_not_called()
    if content_changed:
        path = folder / "System-DiagnoseReport.mcs.yml"
        path.write_bytes(path.read_bytes() + b" ")

    code, result = invoke(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], monkeypatch, capsys)
    if content_changed:
        assert code == 1 and result["status"] == "review_required"
        assert result["writeStatus"] == "not_attempted"
        components.submit_state_payload.assert_not_called()
    else:
        assert code == 0 and result["completed"]
        assert result["writeStatus"] == "submitted"
        components.submit_state_payload.assert_called_once()


@pytest.mark.parametrize("schema", [
    "gptagent_copilotforemployeeselfservicehr", "msdyn_copilotforemployeeselfservicedahr",
    "msdyn_copilotforemployeeselfservicedait", "gptagent_copilotforemployeeselfserviceit",
])
@pytest.mark.parametrize("action", ["enable", "disable"])
def test_diagnostics_state_actions_use_reviewed_whole_set_without_converter(tmp_path, monkeypatch, capsys, schema, action):
    import agentbuilder_object_model

    monkeypatch.setattr(agentbuilder_object_model, "yaml_to_object_models", lambda *a, **k: pytest.fail("State actions must not convert topic content."))
    components = diagnostics_transport(monkeypatch, action=action, schema=schema)
    code, review = invoke(tmp_path, ["--review"], monkeypatch, capsys, diagnostics_request(action))
    assert code == 0 and review["status"] == "review_ready"
    assert "Diagnostics Topics" in review["userMessage"]
    assert "System-RecordSearchResults" in review["userMessage"]
    assert "System-DiagnoseReport" in review["userMessage"]
    components.submit_state_payload.assert_not_called()

    code, result = invoke(tmp_path, ["--apply-review", review["reviewId"], "--decision", "approve"], monkeypatch, capsys)
    assert code == 0 and result["completed"]
    components.submit_state_payload.assert_called_once()
    payload = components.submit_state_payload.call_args.args[0]
    assert payload["changeToken"] == "r1"
    changes = payload["botComponentChanges"]
    assert len(changes) == 2
    assert {row["component"]["schemaName"] for row in changes} == {
        f"{schema}.topic.System-RecordSearchResults", f"{schema}.topic.System-DiagnoseReport",
    }
    state = "Active" if action == "enable" else "Inactive"
    assert all(row["$kind"] == "BotComponentUpdate" and row["component"]["state"] == row["component"]["status"] == state for row in changes)


@pytest.mark.parametrize(("stem", "digest"), [
    ("System-RecordSearchResults", "06ddd4b7901643329a3526179541d34d327d40578fd1f97c632918ac5ffd4780"),
    ("System-DiagnoseReport", "9de271c4ccf7808fe44ed459291cbf9f9bbad5d3d48d852dc61b36a7ec676e21"),
])
def test_shipped_topics_preserve_template_text_without_installer_values(stem, digest):
    data = (REFERENCE / "content" / "diagnostics" / f"{stem}.mcs.yml").read_bytes()
    assert hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest() == digest
    text = data.decode("utf-8")
    assert "msdyn_" not in text and "gptagent_" not in text
    assert set(re.findall(r"</?[A-Za-z_][A-Za-z0-9_]*>", text)) <= {
        "<File>", "</File>", "<External>", "</External>", "<k>", "<digits>",
    }


@pytest.mark.parametrize("stem", ["System-RecordSearchResults", "System-DiagnoseReport"])
def test_shipped_topics_convert_to_adaptive_dialogs(stem):
    from agentbuilder_object_model import (
        ObjectModelConverterError, validate_object_model_runtime, yaml_to_object_models,
    )

    text = (REFERENCE / "content" / "diagnostics" / f"{stem}.mcs.yml").read_text(encoding="utf-8")
    try:
        validate_object_model_runtime()
    except ObjectModelConverterError as error:
        pytest.skip(str(error))
    result, = yaml_to_object_models([{"key": stem, "yaml": text}])
    assert result["success"] is True, result
    assert result["elementType"] == "AdaptiveDialog"
    assert result["objectModel"]["$kind"] == "AdaptiveDialog"
