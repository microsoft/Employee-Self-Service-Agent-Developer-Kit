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
from types import SimpleNamespace
from typing import Any

import pytest

import minimalbot_evaluation as mbe
import evaluation_runs


ENV_ID = "214d162d-0479-e7b3-b118-3ba749943035"
BOT_ID = "fc27c063-49bb-4241-9546-8239e385a267"


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

    def fake_request(method, url, *, body=None, params=None):
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
    assert f"/api/makerevaluation/testruns/r1" in url
    assert "minimalBots" not in url


def test_get_test_run_requires_run_id():
    client = _client_with([])
    with pytest.raises(mbe.MinimalBotEvaluationError):
        client.get_test_run("")


def test_get_test_run_raises_on_http_error():
    client = _client_with([(404, {})])
    with pytest.raises(mbe.MinimalBotEvaluationError):
        client.get_test_run("missing")


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
