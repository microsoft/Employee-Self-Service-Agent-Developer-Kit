# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Listing content-backed topic sets for add through the entry point."""

from copy import deepcopy
import io
import json

import pytest

import topic_actions as entry
from tests.scripts.test_topic_actions import AGENT_ID, _auth, forbid_auth, request_value, workspace  # noqa: F401


def _content_picker(
    monkeypatch, workspace, request_value, capsys, *, action, present=(),
    chat_output=False, change_body=None, change_catalog=None, package_index=0, exit_code=0,
):
    from topic_actions_catalog import load_catalog, parse_catalog

    catalog = load_catalog()
    if change_catalog is not None:
        document = catalog.document()
        change_catalog(document)
        catalog = parse_catalog(document)
        monkeypatch.setattr("topic_actions_catalog.load_catalog", lambda: catalog)
    schema = catalog.document()["packages"][package_index]["agentSchemaNames"][0]
    body = {
        "bot": {"cdsBotId": AGENT_ID, "schemaName": schema},
        "changeToken": "picker-read",
        "botComponentChanges": [{
            "$kind": "BotComponentInsert", "component": {
                "$kind": "DialogComponent", "id": stem, "parentBotId": AGENT_ID,
                "schemaName": f"{schema}.topic.{stem}", "state": "Inactive", "status": "Inactive",
            },
        } for stem in present],
    }
    if change_body is not None:
        change_body(body)
    auth_calls = _auth(monkeypatch)
    monkeypatch.setattr(entry.AgentBuilderClient, "get_agent", lambda *args: {"botId": AGENT_ID})
    monkeypatch.setattr(entry.TopicActionsClient, "read_components", lambda *args: deepcopy(body))
    def forbidden(*args, **kwargs):
        pytest.fail("Selection must not convert content, validate Dev enrollment, or write.")
    monkeypatch.setattr(entry.AgentBuilderClient, "get_dev_configuration", forbidden)
    monkeypatch.setattr(entry.TopicActionsClient, "submit_state_payload", forbidden)
    monkeypatch.setattr("agentbuilder_object_model.yaml_to_object_models", forbidden)
    value = {key: item for key, item in request_value.items() if key != "setKeys"}
    value["action"] = action
    monkeypatch.setattr(entry.sys, "stdin", io.StringIO(json.dumps(value)))
    args = ["--list-agent-sets", "--workspace-root", str(workspace)]
    code = entry.main(args + (["--chat-output"] if chat_output else []))
    output = capsys.readouterr().out
    result = json.loads(output.removeprefix(entry.RESULT_MARKER))
    assert code == exit_code, result
    assert auth_calls[0][1]["allow_write"] is False
    assert "do-not-emit" not in output and "private-token" not in output
    assert not (workspace / ".local" / "topic-actions").exists()
    return result


@pytest.mark.parametrize("chat_output", [False, True])
def test_add_picker_offers_absent_shipped_sets_from_a_live_read(
    workspace, request_value, monkeypatch, capsys, chat_output,
):
    result = _content_picker(
        monkeypatch, workspace, request_value, capsys, action="add", chat_output=chat_output,
    )
    assert result["status"] == "sets_listed"
    assert result["setCount"] == 1 and result["discoveryComplete"]
    assert result["sets"] == [{
        "key": "diagnostics", "name": "Diagnostics Topics",
        **({} if chat_output else {"topicCount": 0, "expectedTopicCount": 2, "presence": "Absent"}),
    }]
    # The chat question tool rejects a one-option question without free text; a lone set goes to review.
    assert result["selectionQuestion"] is None
    assert "| Diagnostics Topics | 0 of 2 | Absent |" in result["userMessage"]
    assert "No topics were changed." in result["userMessage"]
    assert not result["completed"] and result["writeStatus"] == "not_attempted"


@pytest.mark.parametrize(("present", "count", "presence"), [
    (("System-DiagnoseReport",), 1, "Partial"),
    (("System-DiagnoseReport", "System-RecordSearchResults"), None, None),
])
def test_add_picker_filters_out_fully_present_sets(
    workspace, request_value, monkeypatch, capsys, present, count, presence,
):
    result = _content_picker(
        monkeypatch, workspace, request_value, capsys, action="add", present=present,
    )
    if count is None:
        assert result["sets"] == [] and result["setCount"] == 0
        assert result["selectionQuestion"] is None
        assert "No supported content-backed topic sets are available to add." in result["userMessage"]
    else:
        assert result["sets"] == [{
            "key": "diagnostics", "name": "Diagnostics Topics", "topicCount": count,
            "expectedTopicCount": 2, "presence": presence,
        }]
        assert result["selectionQuestion"] is None
    assert result["discoveryComplete"] and result["writeStatus"] == "not_attempted"


@pytest.mark.parametrize("collection", [None, {}, [None]])
def test_content_picker_does_not_turn_malformed_inventory_into_available_sets(
    workspace, request_value, monkeypatch, capsys, collection,
):
    result = _content_picker(
        monkeypatch, workspace, request_value, capsys, action="add", exit_code=1,
        change_body=lambda body: body.update(botComponentChanges=collection),
    )
    assert result["status"] == "blocked"
    assert "sets" not in result and "selectionQuestion" not in result
    assert result["writeStatus"] == "not_attempted"


def test_content_picker_ignores_unrelated_components_without_topic_schemas(
    workspace, request_value, monkeypatch, capsys,
):
    def add_settings(body):
        body["botComponentChanges"].append({
            "$kind": "BotComponentInsert", "component": {
                "$kind": "BotSettingsComponent", "id": "settings", "schemaName": {"unexpected": "shape"},
            },
        })
    result = _content_picker(
        monkeypatch, workspace, request_value, capsys, action="add",
        present=("System-DiagnoseReport",), change_body=add_settings,
    )
    assert result["sets"] == [{
        "key": "diagnostics", "name": "Diagnostics Topics", "topicCount": 1,
        "expectedTopicCount": 2, "presence": "Partial",
    }]


@pytest.mark.parametrize("package_index", [0, 1, 2])
def test_content_picker_uses_live_presence_for_each_catalog_family(
    workspace, request_value, monkeypatch, capsys, package_index,
):
    result = _content_picker(
        monkeypatch, workspace, request_value, capsys, action="add", package_index=package_index,
        present=("System-DiagnoseReport",),
    )
    assert result["sets"] == [{
        "key": "diagnostics", "name": "Diagnostics Topics", "topicCount": 1,
        "expectedTopicCount": 2, "presence": "Partial",
    }]


def test_content_picker_supports_another_content_set_without_offering_state_only_sets(
    workspace, request_value, monkeypatch, capsys,
):
    def add_set(document):
        definition = deepcopy(next(item for item in document["sets"] if item["key"] == "diagnostics"))
        definition["key"] = "other-content"
        definition["integration"] = {"key": "other", "name": "Other"}
        document["sets"].append(definition)
    result = _content_picker(
        monkeypatch, workspace, request_value, capsys, action="add", change_catalog=add_set,
        present=("System-DiagnoseReport", "WorkdayGetVisas"),
    )
    assert [item["key"] for item in result["sets"]] == ["diagnostics", "other-content"]
    assert result["selectionQuestion"]["options"] == [
        {"label": "Diagnostics Topics"}, {"label": "Other Topics"},
    ]


def test_content_picker_does_not_hide_unresolved_families_as_an_empty_success(
    workspace, request_value, monkeypatch, capsys,
):
    def conflicting_family(document):
        package = deepcopy(document["packages"][0])
        package["key"] = "ambiguous-family"
        document["packages"].append(package)
        definition = next(item for item in document["sets"] if item["key"] == "diagnostics")
        variant = deepcopy(definition["sourceVariants"][0])
        variant["packageKey"] = package["key"]
        definition["sourceVariants"].append(variant)
    result = _content_picker(
        monkeypatch, workspace, request_value, capsys, action="add", change_catalog=conflicting_family,
    )
    assert result["discoveryComplete"] is False
    assert result["selectionQuestion"] is None
    assert "Some topic sets could not be fully identified." in result["userMessage"]
    assert "No supported content-backed topic sets are available" not in result["userMessage"]


def test_content_picker_rejects_selected_sets_before_authentication(
    workspace, request_value, monkeypatch, capsys,
):
    monkeypatch.setattr(entry.sys, "stdin", io.StringIO(json.dumps({
        **request_value, "action": "add", "setKeys": ["diagnostics"],
    })))
    assert entry.main(["--list-agent-sets", "--workspace-root", str(workspace)]) == 1
    result = json.loads(capsys.readouterr().out.removeprefix(entry.RESULT_MARKER))
    assert result["reason"] == "invalid_request"
    assert result["writeStatus"] == "not_attempted"


def test_remove_picker_is_refused_before_authentication(workspace, request_value, monkeypatch, capsys):
    value = {key: item for key, item in request_value.items() if key != "setKeys"}
    monkeypatch.setattr(entry.sys, "stdin", io.StringIO(json.dumps({**value, "action": "remove"})))
    assert entry.main(["--list-agent-sets", "--workspace-root", str(workspace)]) == 1
    result = json.loads(capsys.readouterr().out.removeprefix(entry.RESULT_MARKER))
    assert result["reason"] == "invalid_request"
    assert "sets" not in result and result["writeStatus"] == "not_attempted"
