# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for MinimalBot run history / results via the PPAPI makerevaluation API.

These cover ``list_test_runs`` and ``get_test_run`` on
``MinimalBotEvaluationClient`` plus the ``list-runs`` / ``results`` wiring in
``evaluation_runs._minimalbot_command``. No network access: the client's
``_request`` is replaced with a capturing fake.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import pytest
import requests

import minimalbot_evaluation as mbe
import evaluation_runs


ENV_ID = "214d162d-0479-e7b3-b118-3ba749943035"
BOT_ID = "fc27c063-49bb-4241-9546-8239e385a267"


def _run_components(test_set_id="deployed-set"):
    return {
        "bot": {"schemaName": "s"},
        "connectionReferenceChanges": [],
        "botComponentChanges": [
            {"component": {
                "id": test_set_id,
                "definition": {
                    "$kind": "EvaluationSet",
                    "displayName": "Benefits and Policy Lookup",
                    "graders": [{"$kind": "CompareMeaningGrader", "threshold": 0.7}],
                },
            }},
            {"component": {
                "id": "deployed-case",
                "parentBotComponentId": test_set_id,
                "definition": {
                    "$kind": "EvaluationData",
                    "rows": [{"input": "My pay?", "expectedOutput": "Check payroll."}],
                },
            }},
        ],
    }


def _run_components_with_tool(test_set_id="deployed-set"):
    components = _run_components(test_set_id)
    components["connectionReferenceChanges"] = [{
        "connectionReference": {
            "connectorId": (
                "/providers/Microsoft.PowerApps/apis/shared_service-now"
            ),
            "connectionReferenceLogicalName": (
                "contoso_agent.shared_service-now.reference"
            ),
        },
    }]
    return components


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}


def _client_with(responses: list[tuple[int, Any]]) -> mbe.MinimalBotEvaluationClient:
    """Build a client whose ``_request`` returns queued (status, body) pairs."""
    client = mbe.MinimalBotEvaluationClient(ENV_ID, BOT_ID, "tenant-1")
    client._token = "fake-token"  # bypass authenticate()
    calls: list[dict[str, Any]] = []
    queue = list(responses)

    def fake_request(method, url, *, body=None, params=None, operation="request"):
        calls.append({"method": method, "url": url, "body": body, "params": params})
        status, payload = queue.pop(0)
        return _FakeResponse(status), payload

    client._request = fake_request  # type: ignore[assignment]
    client.calls = calls  # type: ignore[attr-defined]
    return client


def test_list_test_runs_hits_ppapi_testruns_and_unwraps_value():
    client = _client_with([(200, {"value": [{"runId": "r1"}, {"runId": "r2"}]})])
    runs = client.list_test_runs()
    assert runs == [{"runId": "r1"}, {"runId": "r2"}]
    url = client.calls[0]["url"]  # type: ignore[attr-defined]
    assert client.calls[0]["method"] == "GET"  # type: ignore[attr-defined]
    assert "https://api.test.powerplatform.com" in url
    assert f"/environments/{ENV_ID}/bots/{BOT_ID}/api/makerevaluation/testruns" in url
    assert "minimalBots" not in url  # status is pure PPAPI, not the components API


def test_list_test_runs_accepts_bare_list():
    client = _client_with([(200, [{"runId": "r1"}])])
    assert client.list_test_runs() == [{"runId": "r1"}]


def test_list_test_runs_wraps_single_object():
    client = _client_with([(200, {"runId": "solo"})])
    assert client.list_test_runs() == [{"runId": "solo"}]


def test_list_test_runs_raises_on_http_error():
    client = _client_with([(403, {})])
    with pytest.raises(mbe.MinimalBotEvaluationError):
        client.list_test_runs()


def test_get_test_run_hits_testruns_run_id():
    client = _client_with([(200, {"runId": "r1", "state": "Completed"})])
    result = client.get_test_run("r1")
    assert result["state"] == "Completed"
    url = client.calls[0]["url"]  # type: ignore[attr-defined]
    assert "/api/makerevaluation/testruns/r1" in url
    assert "minimalBots" not in url


def test_get_test_run_requires_run_id():
    client = _client_with([])
    with pytest.raises(mbe.MinimalBotEvaluationError):
        client.get_test_run("")


def test_get_test_run_raises_on_http_error():
    client = _client_with([(404, {})])
    with pytest.raises(mbe.MinimalBotEvaluationError):
        client.get_test_run("missing")


def test_run_test_set_rejects_202_without_run_id():
    # F-5: a 202 whose body carries no runId/id is unusable (the run can't be
    # tracked), so it must raise instead of reporting a phantom success.
    client = _client_with([
        (200, _run_components("test-set-1")),
        (202, {}),  # accepted, but no runId/id
    ])
    with pytest.raises(mbe.MinimalBotEvaluationError) as exc:
        client.run_test_set("test-set-1", mcs_connection_id="mcs-conn")
    assert "no runId/id" in str(exc.value)


def test_run_test_set_succeeds_with_run_id():
    # Positive control: a 202 with a runId returns cleanly.
    client = _client_with([
        (200, _run_components("test-set-1")),
        (202, {"runId": "run-42"}),
    ])
    result = client.run_test_set("test-set-1", mcs_connection_id="mcs-conn")
    assert result["runId"] == "run-42"
    assert result["runName"].startswith(
        "Benefits and Policy Lookup - "
    )
    assert "MinimalBot" not in result["runName"]


def test_run_test_set_preserves_explicit_run_name():
    client = _client_with([
        (200, _run_components("test-set-1")),
        (202, {"runId": "run-42"}),
    ])

    result = client.run_test_set(
        "test-set-1",
        run_name="Quarterly policy regression",
        mcs_connection_id="mcs-conn",
    )

    assert result["runName"] == "Quarterly policy regression"


def test_run_test_set_does_not_require_unrelated_tool_profile():
    client = _client_with([
        (200, _run_components_with_tool("test-set-1")),
        (200, {"value": []}),
        (202, {"runId": "run-42"}),
    ])

    result = client.run_test_set("test-set-1", mcs_connection_id="mcs-conn")

    assert result["runId"] == "run-42"
    assert client.calls[-1]["body"]["toolsConnections"] == []  # type: ignore[attr-defined]


def test_run_test_set_includes_unambiguous_tool_profile():
    client = _client_with([
        (200, _run_components_with_tool("test-set-1")),
        (200, {"value": [{
            "name": "service-now-connection",
            "properties": {
                "statuses": [{"status": "Connected"}],
            },
        }]}),
        (202, {"runId": "run-42"}),
    ])

    client.run_test_set("test-set-1", mcs_connection_id="mcs-conn")

    assert client.calls[-1]["body"]["toolsConnections"] == [{  # type: ignore[attr-defined]
        "botId": BOT_ID,
        "botSchemaName": "s",
        "connections": [{
            "connectorId": "shared_service-now",
            "connectionId": "service-now-connection",
            "connectionReferenceName": (
                "contoso_agent.shared_service-now.reference"
            ),
        }],
    }]


def test_request_translates_transport_error(monkeypatch):
    # F-6: a requests.RequestException must surface as a MinimalBotEvaluationError
    # carrying operation context, not a raw traceback.
    client = mbe.MinimalBotEvaluationClient(ENV_ID, BOT_ID, "tenant-1")
    client._token = "fake-token"

    def boom(*args, **kwargs):
        raise requests.ConnectionError("name resolution failed")

    monkeypatch.setattr(mbe._SESSION, "request", boom)

    with pytest.raises(mbe.MinimalBotEvaluationError) as exc:
        client.read_components()
    msg = str(exc.value)
    assert "component read" in msg
    assert "transport error" in msg


def test_module_session_has_bounded_retries():
    # F-6: the shared session must mount a bounded retry adapter for transient
    # statuses (no unbounded raw requests.request calls)...
    adapter = mbe._SESSION.get_adapter("https://example.com")
    retry = adapter.max_retries
    assert retry.total == 3
    assert 429 in retry.status_forcelist
    assert 503 in retry.status_forcelist


def _fake_config() -> dict[str, Any]:
    return {
        "configVersion": 1,
        "setup": "complete",
        "environmentId": ENV_ID,
        "tenantId": "tenant-1",
        "agent": {"botId": BOT_ID, "folder": "workspace/agents/x"},
    }


def test_minimalbot_command_list_runs(monkeypatch, capsys):
    captured: dict[str, bool] = {}

    class FakeClient:
        @classmethod
        def from_config(cls, config):
            return cls()

        def authenticate(self):
            return "tok"

        def list_test_runs(self):
            captured["called"] = True
            return [{"runId": "r1"}]

    monkeypatch.setattr(evaluation_runs, "MinimalBotEvaluationClient", FakeClient)
    args = argparse.Namespace(command="list-runs")
    rc = evaluation_runs._minimalbot_command(args, _fake_config())
    assert rc == 0
    assert captured["called"] is True
    assert "r1" in capsys.readouterr().out


def test_minimalbot_command_results(monkeypatch, capsys):
    class FakeClient:
        environment_id = ENV_ID
        bot_id = BOT_ID
        ring = "test"
        agent_backend = "cosmos"

        @classmethod
        def from_config(cls, config):
            return cls()

        def authenticate(self):
            return "tok"

        def get_test_run(self, run_id):
            assert run_id == "run-42"
            return {"runId": run_id, "state": "Completed"}

    monkeypatch.setattr(evaluation_runs, "MinimalBotEvaluationClient", FakeClient)
    args = argparse.Namespace(command="results", run_id="run-42")
    rc = evaluation_runs._minimalbot_command(args, _fake_config())
    assert rc == 0
    assert "Completed" in capsys.readouterr().out


class _CommandClient:
    environment_id = "active-environment"
    bot_id = "active-bot"
    ring = "test"
    agent_backend = "cosmos"
    signed_in_username = "maker@example.com"

    def __init__(self):
        self.starts = []
        self.result = {
            "runId": "new-run",
            "testSetId": "deployed-set",
            "runName": "Selected run",
            "status": 202,
            "serviceRequestId": "request-id",
            "correlationId": "correlation-id",
            "startedAt": "2026-09-28T12:00:00Z",
            "response": {"runId": "new-run", "state": "Queued"},
        }

    def authenticate(self):
        return "fake-token"

    def _connected(self, connector_id):
        assert connector_id == evaluation_runs.MCS_CONNECTOR_NAME
        return [{
            "name": "selected-profile",
            "properties": {
                "displayName": "Maker profile",
                "accountName": self.signed_in_username,
                "statuses": [{"status": "Connected"}],
            },
        }]

    def list_test_sets(self):
        return [{"id": "deployed-set", "runnable": True}]

    def read_components(self):
        return _run_components()

    def run_test_set(self, test_set_id, **kwargs):
        self.starts.append((test_set_id, kwargs))
        return dict(self.result)

    def get_test_run(self, run_id):
        assert run_id == "new-run"
        return {
            "runId": run_id, "testSetId": "deployed-set", "state": "Completed",
        }


def _command_args():
    return argparse.Namespace(
        command="run",
        test_set_id="deployed-set",
        run_name="Selected run",
        published=False,
        mcs_connection_id="selected-profile",
    )


def _install_command_client(monkeypatch, client):
    monkeypatch.setattr(
        evaluation_runs.MinimalBotEvaluationClient,
        "from_config",
        lambda config: client,
    )


def _install_transport_command_client(monkeypatch, components):
    client = _client_with([(200, components)])
    client.authenticate = lambda: "fake-token"
    client.list_test_sets = lambda: [{"id": "deployed-set", "runnable": True}]
    client._connected = _CommandClient()._connected
    _install_command_client(monkeypatch, client)
    return client


@pytest.mark.parametrize(
    ("ring", "backend"),
    [("prod", None), ("preprod", "cosmos"), ("test", "cosmos")],
)
def test_native_start_link_matches_request_identity_and_completed_link(
    monkeypatch, capsys, ring, backend,
):
    client = _CommandClient()
    client.ring = ring
    client.agent_backend = backend
    _install_command_client(monkeypatch, client)
    config = _fake_config()
    config["environmentId"] = "stale-global-environment"
    config["agent"]["environmentId"] = "different-agent-config"
    assert evaluation_runs._minimalbot_command(_command_args(), config) == 0
    started = json.loads(capsys.readouterr().out)
    assert all(started[key] == value for key, value in client.result.items())
    assert started["userGuidance"] == evaluation_runs.RUN_WAIT_GUIDANCE
    expected = (
        evaluation_runs.COPILOT_STUDIO_ORIGIN_BY_RING[ring]
        + "/environments/active-environment/copilots/active-bot"
        + "/evaluation/runsDetails/deployed-set/new-run"
        + ("?agentBackend=cosmos" if backend else "")
    )
    assert started["agentStudioUrl"] == expected
    assert client.starts == [("deployed-set", {
        "run_name": "Selected run",
        "run_on_published_bot": False,
        "mcs_connection_id": "selected-profile",
    })]
    assert evaluation_runs._minimalbot_command(
        argparse.Namespace(command="results", run_id="new-run"), config,
    ) == 0
    assert json.loads(capsys.readouterr().out)["agentStudioUrl"] == expected
    assert len(client.starts) == 1


@pytest.mark.parametrize("run_id", [None, "", " \n ", False, 5])
def test_native_start_without_valid_run_id_never_prints_success(
    monkeypatch, capsys, run_id,
):
    client = _CommandClient()
    client.result["runId"] = run_id
    _install_command_client(monkeypatch, client)
    with pytest.raises(evaluation_runs.EvaluationRunError, match="run ID"):
        evaluation_runs._minimalbot_command(_command_args(), _fake_config())
    assert capsys.readouterr().out == ""
    assert len(client.starts) == 1


def test_native_start_failure_has_no_link_or_success(monkeypatch, capsys):
    client = _CommandClient()

    def fail(test_set_id, **kwargs):
        raise mbe.MinimalBotEvaluationError("HTTP 403")

    client.run_test_set = fail
    _install_command_client(monkeypatch, client)
    with pytest.raises(mbe.MinimalBotEvaluationError, match="HTTP 403"):
        evaluation_runs._minimalbot_command(_command_args(), _fake_config())
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("missing_identity", ["environment_id", "bot_id", "testSetId"])
def test_native_started_run_with_missing_navigation_identity_is_not_retried(
    monkeypatch, capsys, missing_identity,
):
    client = _CommandClient()
    if missing_identity == "testSetId":
        client.result.pop("testSetId")
    else:
        setattr(client, missing_identity, "")
    _install_command_client(monkeypatch, client)
    assert evaluation_runs._minimalbot_command(_command_args(), _fake_config()) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["runId"] == "new-run"
    assert result["agentStudioUrl"] is None
    assert "do not start another run" in result["navigationWarning"]
    assert len(client.starts) == 1


def test_native_run_preserves_existing_runnable_block(monkeypatch, capsys):
    client = _CommandClient()
    client.list_test_sets = lambda: [{
        "id": "deployed-set",
        "runnable": False,
        "blockedReason": "The selected test set is blocked from running.",
    }]
    _install_command_client(monkeypatch, client)
    with pytest.raises(evaluation_runs.EvaluationRunError, match="blocked from running"):
        evaluation_runs._minimalbot_command(_command_args(), _fake_config())
    assert client.starts == []
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("sets", [
    [],
    [{"id": "other-set", "displayName": "deployed-set", "runnable": True}],
    [{"id": "deployed-set", "state": "Inactive", "runnable": True}],
])
def test_native_run_never_substitutes_a_same_named_or_inactive_set(
    monkeypatch, sets,
):
    client = _CommandClient()
    client.list_test_sets = lambda: sets
    _install_command_client(monkeypatch, client)
    with pytest.raises(evaluation_runs.EvaluationRunError, match="not active"):
        evaluation_runs._minimalbot_command(_command_args(), _fake_config())
    assert client.starts == []


@pytest.mark.parametrize(
    ("local_status", "baseline_status", "blocked"),
    [
        ("review_requested", None, True),
        ("review_completed", "review_requested", False),
        ("review_requested", "review_requested", True),
        ("review_completed", "review_completed", False),
        (None, "review_completed", False),
        (None, "review_requested", False),
    ],
)
def test_native_run_preserves_local_review_without_new_api_prerequisite(
    monkeypatch, tmp_path, local_status, baseline_status, blocked,
):
    folder = tmp_path / "evaluations" / "pay"
    baseline = tmp_path / ".baseline" / "evaluations" / "pay"
    folder.mkdir(parents=True)
    baseline.mkdir(parents=True)
    for root, status in [(folder, local_status), (baseline, baseline_status)]:
        if status:
            (root / "review.json").write_text(
                json.dumps({"status": status}), encoding="utf-8",
            )
    (tmp_path / ".component-map.json").write_text(json.dumps({
        "evaluations/pay/set.mcs.yml": {
            "botcomponentid": "deployed-set", "componenttype": 19,
        },
    }), encoding="utf-8")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    client = _CommandClient()
    client.list_test_sets = lambda: [{
        "id": "deployed-set",
        "runnable": True,
    }]
    _install_command_client(monkeypatch, client)
    config = _fake_config()
    config["agent"]["folder"] = str(tmp_path)
    if blocked:
        with pytest.raises(evaluation_runs.EvaluationRunError, match="tagged for review"):
            evaluation_runs._minimalbot_command(_command_args(), config)
        assert client.starts == []
    else:
        assert evaluation_runs._minimalbot_command(_command_args(), config) == 0
        assert len(client.starts) == 1
    assert before == {
        path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }


@pytest.mark.parametrize("graders", [
    None, [], "CompareMeaningGrader",
    [{"$kind": "GeneralQualityGrader"}],
    [{"$kind": "UnknownGrader"}],
    [{"$kind": "CompareMeaningGrader"}, {"$kind": "GeneralQualityGrader"}],
])
def test_native_direct_command_validates_actual_deployed_grader(
    monkeypatch, capsys, graders,
):
    components = _run_components()
    components["botComponentChanges"][0]["component"]["definition"]["graders"] = graders
    client = _install_transport_command_client(monkeypatch, components)
    with pytest.raises(mbe.MinimalBotEvaluationError, match="Compare Meaning"):
        evaluation_runs._minimalbot_command(_command_args(), _fake_config())
    assert len(client.calls) == 1
    assert "minimalBots" in client.calls[0]["url"]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("invalid_child", [
    {"$kind": "MultiTurnEvaluationCase"},
    {"$kind": "EvaluationData", "rows": [{"input": "My pay?", "expectedOutput": " "}]},
    {"$kind": "EvaluationData", "rows": [{"input": "", "expectedOutput": "Answer"}]},
    None,
])
def test_native_direct_command_validates_all_deployed_children(
    monkeypatch, capsys, invalid_child,
):
    components = _run_components()
    components["botComponentChanges"].append({"component": {
        "id": "invalid-case", "parentBotComponentId": "deployed-set",
        "definition": invalid_child,
    }})
    client = _install_transport_command_client(monkeypatch, components)
    with pytest.raises(mbe.MinimalBotEvaluationError, match="Deployed test set"):
        evaluation_runs._minimalbot_command(_command_args(), _fake_config())
    assert len(client.calls) == 1
    assert "minimalBots" in client.calls[0]["url"]
    assert capsys.readouterr().out == ""


def test_native_disappeared_deployed_definition_never_runs(monkeypatch):
    client = _install_transport_command_client(monkeypatch, {"botComponentChanges": []})
    with pytest.raises(mbe.MinimalBotEvaluationError, match="was not found"):
        evaluation_runs._minimalbot_command(_command_args(), _fake_config())
    assert len(client.calls) == 1
    assert "minimalBots" in client.calls[0]["url"]


def test_native_list_connections_supports_explicit_profile_selection(monkeypatch, capsys):
    client = _CommandClient()
    _install_command_client(monkeypatch, client)
    assert evaluation_runs._minimalbot_command(
        argparse.Namespace(command="list-connections"), _fake_config(),
    ) == 0
    [profile] = json.loads(capsys.readouterr().out)
    assert profile["id"] == "selected-profile"
    assert profile["displayName"] == "Maker profile"
    assert profile["matchesSignedInAccount"] is True
    assert client.starts == []


@pytest.mark.parametrize("profiles", [
    [],
    [{"name": "other-profile", "statuses": [{"status": "Connected"}]}],
    [{"name": "selected-profile", "properties": {"statuses": [{"status": "Error"}]}}],
    [{"name": "selected-profile"}],
])
def test_native_run_rejects_missing_disconnected_or_unverified_profile(
    monkeypatch, capsys, profiles,
):
    client = _CommandClient()
    client._connected = lambda connector_id: profiles
    _install_command_client(monkeypatch, client)
    with pytest.raises(evaluation_runs.EvaluationRunError, match="missing or is not Connected"):
        evaluation_runs._minimalbot_command(_command_args(), _fake_config())
    assert client.starts == []
    assert capsys.readouterr().out == ""


def test_native_connection_discovery_accepts_transport_top_level_statuses():
    client = _CommandClient()
    client._connected = lambda connector_id: [{
        "name": "profile",
        "statuses": [{"status": "Connected"}],
        "properties": {"displayName": "Existing transport shape"},
    }]
    assert evaluation_runs.list_native_mcs_connections(client)[0]["id"] == "profile"


def test_native_prepared_run_uses_verified_target_and_id(monkeypatch, capsys, tmp_path):
    import evaluation_deployment

    client = _CommandClient()
    _install_command_client(monkeypatch, client)
    config = _fake_config()
    agent = tmp_path / "agent"
    source = tmp_path / "workspace" / "evaluations" / "pay"
    config["agent"]["folder"] = str(agent)
    config["environmentId"] = "stale-global-environment"
    monkeypatch.setattr(evaluation_runs, "is_minimalbot", lambda config: True)
    deployment = {
        "status": "up_to_date", "backend": "minimalbot", "action": "run",
        "environmentId": client.environment_id, "botId": client.bot_id,
        "sets": [{
            "sourceFolder": str(source),
            "agentSetFolder": str(agent / "evaluations" / "pay"),
            "testSetId": "deployed-set", "deployedReviewStatus": None,
        }],
    }
    calls = []

    def deploy(folder, **kwargs):
        calls.append((folder, kwargs))
        return deployment

    monkeypatch.setattr(evaluation_deployment, "deploy_evaluation_set", deploy)
    args = argparse.Namespace(
        set_folder=str(source), confirmation_token="confirmed-token",
        yes=True, force_delete=False, replace=False, run_name="Selected run",
        published=False, mcs_connection_id="selected-profile",
    )
    assert evaluation_runs._prepared_run_command(args, config) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["deployment"] == deployment
    assert result["testSetId"] == "deployed-set"
    assert result["runId"] == "new-run"
    assert "/environments/active-environment/copilots/active-bot/" in result["agentStudioUrl"]
    assert client.starts[0][0] == "deployed-set"
    assert len(client.starts) == len(calls) == 1
