# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline deployment state-machine regressions over existing transport seams."""

from copy import deepcopy
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

import evaluation_deployment as deployment
import evaluation_runs
from evaluation_review import set_review_metadata
import minimalbot_evaluation as native
import push


def write_set(folder: Path, *, cases=1):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "set.mcs.yml").write_text(
        "kind: EvaluationSet\ndisplayName: Example\n"
        "graders:\n  - kind: CompareMeaningGrader\n    threshold: 0.7\n",
        encoding="utf-8",
    )
    for index in range(cases):
        (folder / f"set-case{index}.mcs.yml").write_text(
            f"kind: EvaluationData\nrows:\n  - input: Question {index}\n"
            "    expectedOutput: Expected answer\n", encoding="utf-8",
        )
    return folder


def config_for(root, *, minimalbot=False):
    agent = root / "agent"
    (agent / ".baseline").mkdir(parents=True, exist_ok=True)
    config = {
        "environmentId": "11111111-1111-1111-1111-111111111111",
        "agent": {
            "folder": str(agent),
            "botId": "22222222-2222-2222-2222-222222222222",
            "schemaName": "test_agent",
        },
    }
    if minimalbot:
        config["agent"]["releaseLine"] = "da"
        config["powerPlatformApiEndpoint"] = "https://api.powerplatform.com"
    else:
        config["dataverseEndpoint"] = "https://example.crm.dynamics.com"
        (agent / ".component-map.json").write_text("{}", encoding="utf-8")
    return config


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Tests must not call a live service.")
    monkeypatch.setattr(requests.sessions.Session, "request", reject)
    monkeypatch.setattr(push, "run_checkpoint", lambda *args: None)


class DataverseState:
    """In-memory create/patch/read seams already used by push.py."""

    def __init__(self, monkeypatch):
        self.rows = {}
        self.writes = []
        self.fail_child = False
        self.drop_update = False
        monkeypatch.setattr(
            push, "_AuthHolder",
            lambda *args: SimpleNamespace(token="offline", acquire=lambda: None),
        )
        monkeypatch.setattr(push, "_verify_bot_exists", lambda *args: None)
        monkeypatch.setattr(push, "query_all", self.query)
        monkeypatch.setattr(push, "create_record", self.create)
        monkeypatch.setattr(push, "update_record", self.update)
        monkeypatch.setattr(push, "delete_record", self.delete)

    def query(self, *args, **kwargs):
        return deepcopy(list(self.rows.values()))

    def create(self, env, token, table, data):
        assert table == "botcomponents"
        if self.fail_child and "ParentBotComponentId@odata.bind" in data:
            raise requests.ConnectionError("offline child failure")
        record_id = f"component-{len(self.rows) + 1}"
        row = {**data, "botcomponentid": record_id, "statecode": 0}
        parent = data.get("ParentBotComponentId@odata.bind")
        if parent:
            row["_parentbotcomponentid_value"] = parent.removeprefix(
                "/botcomponents("
            ).removesuffix(")")
        self.rows[record_id] = row
        self.writes.append(("create", record_id))
        return record_id

    def update(self, env, token, table, record_id, data):
        self.writes.append(("update", record_id))
        if not self.drop_update:
            self.rows[record_id].update(data)
        return True

    def delete(self, env, token, table, record_id):
        self.writes.append(("delete", record_id))
        del self.rows[record_id]
        return True


class NativeState:
    """Exercise the existing BotComponentInsert/read/changeToken contract offline."""

    def __init__(self, monkeypatch, config):
        self.client = native.MinimalBotEvaluationClient(
            config["environmentId"], config["agent"]["botId"], "offline-tenant",
        )
        self.components = []
        self.puts = []
        self.fail_after_write = False
        self.fail_before_write = False
        self.partial = False
        monkeypatch.setattr(self.client, "authenticate", lambda: None)
        monkeypatch.setattr(self.client, "read_components", self.read)
        monkeypatch.setattr(self.client, "_request", self.request)
        monkeypatch.setattr(
            deployment.MinimalBotEvaluationClient, "from_config",
            classmethod(lambda cls, config: self.client),
        )

    def read(self):
        return {
            "changeToken": str(len(self.components)),
            "botComponentChanges": deepcopy(self.components),
        }

    def request(self, method, url, *, body, operation):
        assert method == "PUT"
        assert body["changeToken"] == str(len(self.components))
        assert set(body) == {
            "changeToken", "botComponentChanges",
            "connectionReferenceChanges", "connectorDefinitionChanges",
        }
        self.puts.append(deepcopy(body))
        if self.fail_before_write:
            raise native.MinimalBotEvaluationError("Uncertain transport failure")
        changes = deepcopy(body["botComponentChanges"])
        self.components.extend(changes[:1] if self.partial else changes)
        if self.fail_after_write:
            raise native.MinimalBotEvaluationError("Uncertain transport failure")
        return SimpleNamespace(status_code=200), {}


def execute(folder, config, root, *, action="run", **kwargs):
    preview = deployment.preview_deployment(
        folder, config=config, solution_root=root, action=action,
        replace=kwargs.get("replace", False),
    )
    assert preview["status"] == "ready", preview
    return deployment.deploy_evaluation_set(
        folder, config=config, solution_root=root, action=action,
        confirmation_token=preview["confirmationToken"], yes=True, **kwargs,
    )


def test_cancellation_never_prepares_or_authenticates(monkeypatch):
    monkeypatch.setattr(
        deployment, "_prepare", lambda *args, **kwargs: pytest.fail("No consent"),
    )
    assert deployment.deploy_evaluation_set("anything")["status"] == "cancelled"


def test_missing_setup_preserves_workspace_review_intent(tmp_path):
    folder = write_set(tmp_path / "workspace" / "evaluations" / "selected")
    result = deployment.preview_deployment(
        folder, action="request-review", config={}, solution_root=tmp_path,
    )
    assert result["status"] == "blocked"
    assert json.loads((folder / "review.json").read_text())["status"] == "review_requested"


def test_reject_other_agent_before_review_write(tmp_path):
    config = config_for(tmp_path)
    folder = write_set(tmp_path / "other-agent" / "evaluations" / "selected")
    result = deployment.preview_deployment(
        folder, action="request-review", config=config, solution_root=tmp_path,
    )
    assert result["status"] == "blocked"
    assert not (folder / "review.json").exists()


def test_workspace_review_push_is_scoped_and_does_not_run(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    state = DataverseState(monkeypatch)
    source = write_set(tmp_path / "workspace" / "evaluations" / "selected")
    unrelated = write_set(Path(config["agent"]["folder"]) / "evaluations" / "unrelated")
    result = execute(source, config, tmp_path, action="request-review")
    assert result["status"] == "pushed", result
    assert result["sets"][0]["deployedReviewStatus"] == "review_requested"
    assert result["reviewMetadataPersisted"] is True
    assert result["sets"][0]["testSetId"] == "component-1"
    assert len(state.rows) == 2
    assert not source.exists()
    assert unrelated.exists()
    assert not (unrelated.parents[1] / ".baseline" / "evaluations" / unrelated.name).exists()
    assert "review_requested" in state.rows["component-1"]["description"]
    assert result["environmentId"] == config["environmentId"]


def test_unchanged_dataverse_reuses_id_without_write(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    state = DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    first = execute(folder, config, tmp_path)
    state.writes.clear()
    second = execute(folder, config, tmp_path)
    assert first["status"] == "pushed", first
    assert second["status"] == "up_to_date", second
    assert first["sets"] == second["sets"]
    assert not state.writes
    assert not (folder / "review.json").exists()


def test_dataverse_dirty_update_keeps_parent_identity(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    state = DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    first = execute(folder, config, tmp_path)
    child = folder / "set-case0.mcs.yml"
    child.write_text(child.read_text().replace("Expected answer", "New answer"))
    state.writes.clear()
    second = execute(folder, config, tmp_path)
    assert second["status"] == "pushed", second
    assert second["sets"][0]["testSetId"] == first["sets"][0]["testSetId"]
    assert state.writes == [("update", "component-2")]


@pytest.mark.parametrize("completion_action", ["run", "push"])
def test_review_requested_blocks_run_and_completion_is_not_synthesized(
    tmp_path, monkeypatch, completion_action,
):
    config = config_for(tmp_path)
    DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    assert execute(folder, config, tmp_path, action="request-review")["status"] == "pushed"
    result = deployment.preview_deployment(
        folder, action="run", config=config, solution_root=tmp_path,
    )
    assert result["status"] == "blocked"
    assert json.loads((folder / "review.json").read_text())["status"] == "review_requested"
    set_review_metadata(folder, "review_completed")
    result = execute(folder, config, tmp_path, action=completion_action)
    assert result["status"] == "pushed", result
    assert result["sets"][0]["deployedReviewStatus"] == "review_completed"


def test_request_review_no_change_is_metadata_only_and_repeat_noop(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    state = DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    execute(folder, config, tmp_path)
    state.writes.clear()
    result = execute(folder, config, tmp_path, action="request-review")
    assert result["status"] == "pushed", result
    assert state.writes == [("update", "component-1")]
    state.writes.clear()
    result = execute(folder, config, tmp_path, action="request-review")
    assert result["status"] == "up_to_date", result
    assert not state.writes


def test_stale_preview_cannot_authorize_changed_source(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    state = DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    preview = deployment.preview_deployment(folder, config=config, solution_root=tmp_path)
    child = folder / "set-case0.mcs.yml"
    child.write_text(child.read_text().replace("Expected answer", "Changed answer"))
    result = deployment.deploy_evaluation_set(
        folder, config=config, solution_root=tmp_path, yes=True,
        confirmation_token=preview["confirmationToken"],
    )
    assert result["status"] == "blocked"
    assert not state.writes


def test_selected_deletion_requires_extra_approval(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    state = DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected", cases=2)
    execute(folder, config, tmp_path)
    (folder / "set-case1.mcs.yml").unlink()
    state.writes.clear()
    result = execute(folder, config, tmp_path)
    assert result["status"] == "blocked"
    assert not state.writes
    result = execute(folder, config, tmp_path, force_delete=True)
    assert result["status"] == "pushed", result
    assert len(state.rows) == 2


@pytest.mark.parametrize("action", ["run", "request-review"])
def test_partial_dataverse_write_stops_retry_without_duplicate(tmp_path, monkeypatch, action):
    config = config_for(tmp_path)
    state = DataverseState(monkeypatch)
    state.fail_child = True
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    result = execute(folder, config, tmp_path, action=action)
    assert result["status"] == "failed"
    assert len(state.rows) == 1
    assert "review_requested" not in state.rows["component-1"].get("description", "")
    result = deployment.preview_deployment(folder, config=config, solution_root=tmp_path)
    assert result["status"] == "blocked"
    assert len(state.rows) == 1
    assert folder.exists()


def test_unverified_update_does_not_sync_or_cleanup(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    state = DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    execute(folder, config, tmp_path)
    child = folder / "set-case0.mcs.yml"
    child.write_text(child.read_text().replace("Expected answer", "Changed answer"))
    state.drop_update = True
    result = execute(folder, config, tmp_path)
    assert result["status"] == "failed"
    baseline = Path(config["agent"]["folder"]) / ".baseline" / "evaluations" / "selected"
    assert "Expected answer" in (baseline / child.name).read_text()


def test_native_workspace_plan_is_stable_and_reused_on_unchanged(tmp_path, monkeypatch):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    source = write_set(tmp_path / "workspace" / "evaluations" / "selected")
    preview = deployment.preview_deployment(
        source, config=config, solution_root=tmp_path, action="run",
    )
    assert preview["status"] == "ready", preview
    agent = Path(config["agent"]["folder"])
    saved = json.loads((agent / ".evaluation-preview.json").read_text())
    assert not (agent / "evaluations" / source.name).exists()
    result = deployment.deploy_evaluation_set(
        source, config=config, solution_root=tmp_path, action="run", yes=True,
        confirmation_token=preview["confirmationToken"],
    )
    assert result["status"] == "pushed", result
    assert result["sets"][0]["testSetId"] == saved["plan"]["sets"][0]["testSetId"]
    assert state.puts[0]["botComponentChanges"] == saved["plan"]["changes"]
    assert not source.exists()
    second = execute(agent / "evaluations" / "selected", config, tmp_path)
    assert second["status"] == "up_to_date", second
    assert second["sets"][0]["testSetId"] == result["sets"][0]["testSetId"]
    assert len(state.puts) == 1


@pytest.mark.parametrize("action", ["dirty", "request-review", "completion"])
def test_native_push_reuses_existing_api_for_edits_and_local_review(tmp_path, monkeypatch, action):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    first = execute(folder, config, tmp_path)
    assert first["status"] == "pushed"
    old_components = deepcopy(state.components)
    if action == "dirty":
        child = folder / "set-case0.mcs.yml"
        child.write_text(child.read_text().replace("Expected answer", "Changed answer"))
    elif action == "completion":
        set_review_metadata(folder, "review_completed")
    result = execute(
        folder, config, tmp_path,
        action="request-review" if action == "request-review" else "run",
    )
    if action == "dirty":
        assert result["status"] == "pushed", result
        assert result["deploymentBehavior"] == "new_copy"
        assert result["sets"][0]["testSetId"] != first["sets"][0]["testSetId"]
        assert len(state.puts) == 2
        assert all(change["$kind"] == "BotComponentInsert"
                   for change in state.puts[-1]["botComponentChanges"])
    else:
        assert result["status"] == "up_to_date", result
        assert result["deploymentBehavior"] == "reuse"
        assert result["sets"][0]["testSetId"] == first["sets"][0]["testSetId"]
        assert len(state.puts) == 1
        assert "review.json stays local" in result["reviewWarning"]
        assert (folder / "review.json").exists()
        assert not (folder.parents[1] / ".baseline" / "evaluations" / folder.name / "review.json").exists()
    assert result["reviewMetadataPersisted"] is False
    assert result["sets"][0]["deployedReviewStatus"] is None
    assert state.components[:len(old_components)] == old_components


@pytest.mark.parametrize("change", ["add", "remove"])
def test_native_changed_cases_create_selected_copy_without_remote_deletion(tmp_path, monkeypatch, change):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    agent = Path(config["agent"]["folder"])
    folder = write_set(agent / "evaluations" / "selected", cases=2)
    first = execute(folder, config, tmp_path)
    old_components = deepcopy(state.components)
    if change == "add":
        (folder / "set-case2.mcs.yml").write_text(
            (folder / "set-case0.mcs.yml").read_text(encoding="utf-8"), encoding="utf-8",
        )
    else:
        (folder / "set-case1.mcs.yml").unlink()
    preview = deployment.preview_deployment(
        folder, action="run", config=config, solution_root=tmp_path,
    )
    assert preview["status"] == "ready"
    assert preview["deploymentBehavior"] == "new_copy"
    result = execute(folder, config, tmp_path)
    assert result["status"] == "pushed", result
    assert result["sets"][0]["testSetId"] != first["sets"][0]["testSetId"]
    assert state.components[:len(old_components)] == old_components
    assert len(state.puts) == 2
    expected_paths = {f"evaluations/selected/{path.name}" for path in folder.glob("*.mcs.yml")}
    component_map = json.loads((agent / ".component-map.json").read_text(encoding="utf-8"))
    assert set(component_map) == expected_paths
    baseline = agent / ".baseline" / "evaluations" / folder.name
    assert {path.name for path in baseline.glob("*.mcs.yml")} == {
        path.name for path in folder.glob("*.mcs.yml")
    }


def test_native_workspace_review_uses_existing_push_and_preserves_local_sidecar(tmp_path, monkeypatch):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    agent = Path(config["agent"]["folder"])
    source = write_set(tmp_path / "workspace" / "evaluations" / "selected")
    result = execute(source, config, tmp_path, action="request-review")
    assert result["status"] == "pushed", result
    assert result["reviewMetadataPersisted"] is False
    assert result["sets"][0]["deployedReviewStatus"] is None
    assert result["reviewWarning"] == native.NATIVE_REVIEW_LOCAL_ONLY_WARNING
    assert not source.exists()
    local_review = agent / "evaluations" / "selected" / "review.json"
    assert json.loads(local_review.read_text(encoding="utf-8"))["status"] == "review_requested"
    assert not (agent / ".baseline" / "evaluations" / "selected" / "review.json").exists()
    assert "review_requested" not in json.dumps(state.puts)
    preview = deployment.preview_deployment(
        local_review.parent, action="run", config=config, solution_root=tmp_path,
    )
    assert preview["status"] == "blocked"
    assert "tagged for review" in preview["error"]


def test_native_standalone_push_keeps_existing_yaml_api_and_reports_local_review(
    tmp_path, monkeypatch, capsys,
):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    set_review_metadata(folder, "review_requested")
    result = push.main(["--only", "evaluations/selected/*", "--yes"], config=config)
    assert result["status"] == "pushed"
    assert len(state.puts) == 1
    assert "review_requested" not in json.dumps(state.puts)
    output = capsys.readouterr().out
    assert "existing remote copies are retained" in output
    assert native.NATIVE_REVIEW_LOCAL_ONLY_WARNING in output


def test_native_force_delete_retains_existing_unsupported_operation_guard(tmp_path, monkeypatch):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    result = execute(folder, config, tmp_path, force_delete=True)
    assert result["status"] == "blocked"
    assert "does not support --force-delete" in result["error"]
    assert state.puts == []


@pytest.mark.parametrize("change", ["content", "review-completion"])
def test_native_prepared_run_uses_existing_push_result_once(
    tmp_path, monkeypatch, capsys, change,
):
    monkeypatch.chdir(tmp_path)
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    first = execute(folder, config, tmp_path)
    if change == "content":
        child = folder / "set-case0.mcs.yml"
        child.write_text(
            child.read_text(encoding="utf-8").replace("Expected answer", "Updated answer"),
            encoding="utf-8",
        )
    else:
        set_review_metadata(folder, "review_completed")
    preview = deployment.preview_deployment(
        folder, action="run", config=config, solution_root=tmp_path,
    )
    starts = []

    def start(test_set_id, **kwargs):
        starts.append(test_set_id)
        return {"testSetId": test_set_id, "runId": "new-run"}

    monkeypatch.setattr(state.client, "run_test_set", start)
    monkeypatch.setattr(
        evaluation_runs, "list_native_mcs_connections",
        lambda client: [{"id": "selected-profile"}],
    )
    args = argparse.Namespace(
        set_folder=str(folder), confirmation_token=preview["confirmationToken"],
        yes=True, force_delete=False, replace=False, run_name=None,
        published=False, mcs_connection_id="selected-profile",
    )
    capsys.readouterr()
    assert evaluation_runs._prepared_run_command(args, config) == 0
    result = json.loads(capsys.readouterr().out)
    current_id = result["deployment"]["sets"][0]["testSetId"]
    assert starts == [current_id]
    assert result["testSetId"] == current_id
    assert f"/{current_id}/new-run" in result["agentStudioUrl"]
    if change == "content":
        assert current_id != first["sets"][0]["testSetId"]
        assert len(state.puts) == 2
    else:
        assert current_id == first["sets"][0]["testSetId"]
        assert len(state.puts) == 1
        assert result["deployment"]["reviewWarning"] == native.NATIVE_REVIEW_LOCAL_ONLY_WARNING
        assert result["deployment"]["sets"][0]["deployedReviewStatus"] is None


def test_native_uncertain_committed_write_reconciles_same_ids(tmp_path, monkeypatch):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    state.fail_after_write = True
    result = execute(folder, config, tmp_path)
    assert result["status"] == "failed", result
    assert result["deploymentMayHaveCommitted"] is True
    agent = Path(config["agent"]["folder"])
    pending = json.loads((agent / ".evaluation-pending.json").read_text())
    assert not (agent / ".component-map.json").exists()
    state.fail_after_write = False
    result = execute(folder, config, tmp_path)
    assert result["status"] == "pushed", result
    assert result["sets"][0]["testSetId"] == pending["sets"][0]["testSetId"]
    assert len(state.puts) == 1
    assert not (agent / ".evaluation-pending.json").exists()


@pytest.mark.parametrize("failure", ["partial", "absent", "different-definition"])
def test_native_uncertain_mismatch_stops_without_replay(tmp_path, monkeypatch, failure):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    state.partial = failure == "partial"
    state.fail_before_write = failure == "absent"
    state.fail_after_write = failure == "different-definition"
    assert execute(folder, config, tmp_path)["status"] == "failed"
    if failure == "different-definition":
        state.components[0]["component"]["definition"]["displayName"] = "Other"
    result = deployment.preview_deployment(folder, config=config, solution_root=tmp_path)
    assert result["status"] == "blocked"
    assert len(state.puts) == 1
    assert not (Path(config["agent"]["folder"]) / ".component-map.json").exists()


@pytest.mark.parametrize("minimalbot", [False, True])
def test_method_guard_rejects_even_when_baseline_matches(tmp_path, monkeypatch, minimalbot):
    config = config_for(tmp_path, minimalbot=minimalbot)
    state = NativeState(monkeypatch, config) if minimalbot else DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    assert execute(folder, config, tmp_path)["status"] == "pushed"
    parent = folder / "set.mcs.yml"
    invalid = parent.read_text().replace("CompareMeaningGrader", "GeneralQualityGrader")
    parent.write_text(invalid)
    baseline = Path(config["agent"]["folder"]) / ".baseline" / "evaluations" / folder.name
    (baseline / parent.name).write_text(invalid)
    count = len(state.puts if minimalbot else state.writes)
    result = deployment.preview_deployment(folder, config=config, solution_root=tmp_path)
    assert result["status"] == "blocked"
    assert "Compare Meaning only" in result["error"]
    assert len(state.puts if minimalbot else state.writes) == count


@pytest.mark.parametrize("minimalbot", [False, True])
def test_cleanup_failure_is_successful_deployment_with_warning(tmp_path, monkeypatch, minimalbot):
    config = config_for(tmp_path, minimalbot=minimalbot)
    state = NativeState(monkeypatch, config) if minimalbot else DataverseState(monkeypatch)
    source = write_set(tmp_path / "workspace" / "evaluations" / "selected")

    def fail_cleanup(*args):
        raise OSError("Staging file is locked")

    monkeypatch.setattr(deployment, "cleanup_workspace_set", fail_cleanup)
    first = execute(source, config, tmp_path)
    assert first["status"] == "pushed", first
    assert first["cleanupWarning"] == "Staging file is locked"
    assert source.exists()
    count = len(state.puts if minimalbot else state.writes)
    second = execute(source, config, tmp_path)
    assert second["status"] == "up_to_date", second
    assert second["sets"][0]["testSetId"] == first["sets"][0]["testSetId"]
    assert len(state.puts if minimalbot else state.writes) == count


@pytest.mark.parametrize("minimalbot", [False, True])
def test_lock_cleanup_failure_preserves_deployment_result(tmp_path, monkeypatch, minimalbot):
    config = config_for(tmp_path, minimalbot=minimalbot)
    NativeState(monkeypatch, config) if minimalbot else DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    original_unlink = Path.unlink

    def fail_lock_cleanup(path, *args, **kwargs):
        if path.name == ".evaluation-deployment.lock":
            raise OSError("Lock file is busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_lock_cleanup)
    result = execute(folder, config, tmp_path)
    assert result["status"] == "pushed", result
    assert result["sets"][0]["testSetId"]
    assert result["cleanupWarning"] == (
        "Primary deployment result preserved; lock cleanup failed: Lock file is busy"
    )


def test_lock_cleanup_failure_preserves_structured_failure(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    original_unlink = Path.unlink

    def fail_lock_cleanup(path, *args, **kwargs):
        if path.name == ".evaluation-deployment.lock":
            raise OSError("Lock file is busy")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_lock_cleanup)
    result = deployment.deploy_evaluation_set(
        folder, config=config, solution_root=tmp_path,
        confirmation_token="stale-token", yes=True,
    )
    assert result["status"] == "blocked", result
    assert "changed after preview" in result["error"]
    assert result["cleanupWarning"] == (
        "Primary deployment result preserved; lock cleanup failed: Lock file is busy"
    )


@pytest.mark.parametrize("minimalbot", [False, True])
def test_workspace_change_during_cleanup_blocks_continuation(tmp_path, monkeypatch, minimalbot):
    config = config_for(tmp_path, minimalbot=minimalbot)
    state = NativeState(monkeypatch, config) if minimalbot else DataverseState(monkeypatch)
    source = write_set(tmp_path / "workspace" / "evaluations" / "selected")
    original_cleanup = deployment.cleanup_workspace_set

    def changed(*args):
        child = source / "set-case0.mcs.yml"
        child.write_text(
            child.read_text(encoding="utf-8").replace("Expected answer", "Changed answer"),
            encoding="utf-8",
        )
        return original_cleanup(*args)

    monkeypatch.setattr(deployment, "cleanup_workspace_set", changed)
    result = execute(source, config, tmp_path)
    assert result["status"] == "failed", result
    assert result["stage"] == "deployment"
    assert result["deploymentMayHaveCommitted"] is True
    assert "staging set changed" in result["error"]
    assert "cleanupWarning" not in result
    assert "Changed answer" in (source / "set-case0.mcs.yml").read_text(encoding="utf-8")
    assert state.puts if minimalbot else state.writes


def test_dataverse_baseline_failure_recovers_without_recreating(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    state = DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    original = push.update_baseline_scoped

    def fail(*args):
        raise OSError("Baseline write refused")

    monkeypatch.setattr(push, "update_baseline_scoped", fail)
    result = execute(folder, config, tmp_path)
    assert result["status"] == "failed", result
    assert result["remoteCommitted"] is True
    count = len(state.writes)
    monkeypatch.setattr(push, "update_baseline_scoped", original)
    result = execute(folder, config, tmp_path)
    assert result["status"] == "pushed", result
    assert len(state.writes) == count


def test_native_tracking_failure_recovers_without_reinserting(tmp_path, monkeypatch):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    original = state.client._commit_tracking

    def fail(*args):
        raise native.MinimalBotEvaluationError("Native tracking write failed")

    monkeypatch.setattr(state.client, "_commit_tracking", fail)
    assert execute(folder, config, tmp_path)["status"] == "failed"
    monkeypatch.setattr(state.client, "_commit_tracking", original)
    result = execute(folder, config, tmp_path)
    assert result["status"] == "pushed", result
    assert len(state.puts) == 1


def test_remote_extra_case_blocks_noop(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    state = DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    assert execute(folder, config, tmp_path)["status"] == "pushed"
    state.rows["unexpected"] = {
        **state.rows["component-2"], "botcomponentid": "unexpected",
    }
    count = len(state.writes)
    result = deployment.preview_deployment(folder, config=config, solution_root=tmp_path)
    assert result["status"] == "blocked"
    assert "case identities" in result["error"]
    assert len(state.writes) == count


@pytest.mark.parametrize("minimalbot", [False, True])
def test_target_change_invalidates_confirmation(tmp_path, monkeypatch, minimalbot):
    config = config_for(tmp_path, minimalbot=minimalbot)
    state = NativeState(monkeypatch, config) if minimalbot else DataverseState(monkeypatch)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    preview = deployment.preview_deployment(folder, config=config, solution_root=tmp_path)
    config["agent"]["botId"] = "33333333-3333-3333-3333-333333333333"
    if minimalbot:
        state.client.bot_id = config["agent"]["botId"]
    result = deployment.deploy_evaluation_set(
        folder, config=config, solution_root=tmp_path, yes=True,
        confirmation_token=preview["confirmationToken"],
    )
    assert result["status"] == "blocked"
    assert not (state.puts if minimalbot else state.writes)


def test_native_source_changed_during_push_is_not_marked_synchronized(tmp_path, monkeypatch):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    original = state.request

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        (folder / "new-case.mcs.yml").write_text(
            (folder / "set-case0.mcs.yml").read_text(), encoding="utf-8",
        )
        return result

    monkeypatch.setattr(state.client, "_request", changed)
    result = execute(folder, config, tmp_path)
    assert result["status"] == "failed", result
    assert "Source changed" in result["error"]
    assert not (Path(config["agent"]["folder"]) / ".component-map.json").exists()


@pytest.mark.parametrize("already_deployed", [False, True])
def test_native_workspace_changed_during_deployment_blocks_continuation(
    tmp_path, monkeypatch, already_deployed,
):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    agent = Path(config["agent"]["folder"])
    destination = agent / "evaluations" / "selected"
    if already_deployed:
        assert execute(write_set(destination), config, tmp_path)["status"] == "pushed"
    source = write_set(tmp_path / "workspace" / "evaluations" / "selected")
    original_push = state.client.push_agent_evaluations

    def changed(*args, **kwargs):
        result = original_push(*args, **kwargs)
        if kwargs.get("dry_run", False):
            return result
        assert result["status"] == ("up_to_date" if already_deployed else "pushed")
        child = source / "set-case0.mcs.yml"
        child.write_text(
            child.read_text(encoding="utf-8").replace("Expected answer", "Changed answer"),
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(state.client, "push_agent_evaluations", changed)
    result = execute(source, config, tmp_path)
    assert result["status"] == "failed", result
    assert result["stage"] == "deployment"
    assert result["deploymentMayHaveCommitted"] is True
    assert "Source changed during deployment" in result["error"]
    assert "cleanupWarning" not in result
    assert "Changed answer" in (source / "set-case0.mcs.yml").read_text(encoding="utf-8")
    assert "Expected answer" in (destination / "set-case0.mcs.yml").read_text(encoding="utf-8")
    assert (agent / ".evaluation-preview.json").exists()
    assert len(state.puts) == 1


def test_workspace_collision_requires_replace_then_selected_consent(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    DataverseState(monkeypatch)
    destination = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    source = write_set(tmp_path / "workspace" / "evaluations" / "selected", cases=2)
    result = deployment.preview_deployment(source, config=config, solution_root=tmp_path)
    assert result["status"] == "blocked"
    assert "--replace" in result["error"]
    assert not (destination / "set-case1.mcs.yml").exists()
    result = execute(source, config, tmp_path, replace=True)
    assert result["status"] == "pushed", result
    assert (destination / "set-case1.mcs.yml").exists()


def test_missing_config_cli_returns_json_and_preserves_request(tmp_path, monkeypatch, capsys):
    source = write_set(tmp_path / "workspace" / "evaluations" / "selected")
    monkeypatch.chdir(tmp_path)

    def missing():
        print("Run /setup first.")
        raise SystemExit(1)

    monkeypatch.setattr(deployment, "load_config", missing)
    monkeypatch.setattr(
        "sys.argv", ["evaluation_deployment.py", "preview", "--set-folder", str(source),
                     "--action", "request-review"],
    )
    assert deployment.main() == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["status"] == "blocked"
    assert "Run /setup first." in captured.err
    assert (source / "review.json").exists()


def test_native_preview_for_second_identical_set_gets_own_plan(tmp_path, monkeypatch):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    agent = Path(config["agent"]["folder"])
    first = write_set(agent / "evaluations" / "one")
    second = write_set(agent / "evaluations" / "two")
    assert deployment.preview_deployment(
        first, config=config, solution_root=tmp_path,
    )["status"] == "ready"
    result = execute(second, config, tmp_path)
    assert result["status"] == "pushed", result
    saved_map = json.loads((agent / ".component-map.json").read_text())
    assert all(path.startswith("evaluations/two/") for path in saved_map)
    assert len(state.puts) == 1


def test_native_direct_stale_plan_cannot_duplicate_completed_set(tmp_path, monkeypatch):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    agent = Path(config["agent"]["folder"])
    write_set(agent / "evaluations" / "selected")
    stale = state.client.push_agent_evaluations(agent, dry_run=True)
    current = state.client.push_agent_evaluations(agent, dry_run=True)
    state.client.push_agent_evaluations(agent, plan=current)
    with pytest.raises(native.MinimalBotEvaluationError, match="tracking changed"):
        state.client.push_agent_evaluations(agent, plan=stale)
    assert len(state.puts) == 1


@pytest.mark.parametrize("minimalbot", [False, True])
def test_glob_characters_in_folder_do_not_expand_scope(tmp_path, monkeypatch, minimalbot):
    config = config_for(tmp_path, minimalbot=minimalbot)
    state = NativeState(monkeypatch, config) if minimalbot else DataverseState(monkeypatch)
    agent = Path(config["agent"]["folder"])
    selected = write_set(agent / "evaluations" / "set[1]")
    write_set(agent / "evaluations" / "set1")
    result = execute(selected, config, tmp_path)
    assert result["status"] == "pushed", result
    saved_map = json.loads((agent / ".component-map.json").read_text())
    assert len(saved_map) == 2
    assert all(path.startswith("evaluations/set[1]/") for path in saved_map)
    assert len(state.puts if minimalbot else state.rows) == (1 if minimalbot else 2)


def test_recovery_preserves_unrelated_component_map_changes(tmp_path, monkeypatch):
    config = config_for(tmp_path)
    DataverseState(monkeypatch)
    agent = Path(config["agent"]["folder"])
    folder = write_set(agent / "evaluations" / "selected")
    original = push.update_baseline_scoped

    def fail(*args):
        raise OSError("Baseline failure")

    monkeypatch.setattr(push, "update_baseline_scoped", fail)
    assert execute(folder, config, tmp_path)["status"] == "failed"
    map_path = agent / ".component-map.json"
    saved_map = json.loads(map_path.read_text())
    saved_map["topics/unrelated.mcs.yml"] = {"botcomponentid": "unrelated"}
    map_path.write_text(json.dumps(saved_map), encoding="utf-8")
    monkeypatch.setattr(push, "update_baseline_scoped", original)
    assert execute(folder, config, tmp_path)["status"] == "pushed"
    assert json.loads(map_path.read_text())["topics/unrelated.mcs.yml"] == {
        "botcomponentid": "unrelated",
    }


def test_native_unmapped_remote_child_blocks_unchanged(tmp_path, monkeypatch):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    folder = write_set(Path(config["agent"]["folder"]) / "evaluations" / "selected")
    assert execute(folder, config, tmp_path)["status"] == "pushed"
    extra = deepcopy(state.components[1])
    extra["component"]["id"] = "extra-child"
    state.components.append(extra)
    result = deployment.preview_deployment(folder, config=config, solution_root=tmp_path)
    assert result["status"] == "blocked"
    assert "different child identities" in result["error"]
    assert len(state.puts) == 1


@pytest.mark.parametrize("invalid", ["grader", "blank-output", "multiturn", "empty", "missing-parent"])
def test_native_run_validates_deployed_definition_before_connections(tmp_path, monkeypatch, invalid):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    agent = Path(config["agent"]["folder"])
    write_set(agent / "evaluations" / "selected")
    plan = state.client.push_agent_evaluations(agent, dry_run=True)
    state.components = deepcopy(plan["changes"])
    parent_id = plan["sets"][0]["testSetId"]
    if invalid == "grader":
        state.components[0]["component"]["definition"]["graders"][0]["$kind"] = "GeneralQualityGrader"
    elif invalid == "blank-output":
        state.components[1]["component"]["definition"]["rows"][0]["expectedOutput"] = ""
    elif invalid == "multiturn":
        state.components[1]["component"]["definition"]["$kind"] = "MultiTurnEvaluationCase"
    elif invalid == "empty":
        state.components = state.components[:1]
    else:
        parent_id = "not-deployed"
    monkeypatch.setattr(
        state.client, "_connected", lambda *args: pytest.fail("Must validate before connections"),
    )
    with pytest.raises(native.MinimalBotEvaluationError):
        state.client.run_test_set(parent_id)
    assert not state.puts


def test_native_run_validation_reuses_existing_component_read(tmp_path, monkeypatch):
    config = config_for(tmp_path, minimalbot=True)
    state = NativeState(monkeypatch, config)
    agent = Path(config["agent"]["folder"])
    write_set(agent / "evaluations" / "selected")
    plan = state.client.push_agent_evaluations(agent, dry_run=True)
    state.components = deepcopy(plan["changes"])
    reads = []
    starts = []

    def read():
        reads.append(True)
        return state.read()

    def start(method, url, *, body, operation):
        assert method == "POST"
        starts.append(body)
        return SimpleNamespace(status_code=202, headers={}), {"runId": "started-run"}

    monkeypatch.setattr(state.client, "read_components", read)
    monkeypatch.setattr(state.client, "_request", start)
    result = state.client.run_test_set(
        plan["sets"][0]["testSetId"], mcs_connection_id="existing-connection",
    )
    assert result["runId"] == "started-run"
    assert len(reads) == len(starts) == 1
