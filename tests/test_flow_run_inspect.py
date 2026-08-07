# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the pure run-action interpreter (``summarize_actions``).

Feeds a recorded run-action list — including the scope-vs-handler cascade shape
(a failure handler that Succeeded while the containing scope Failed, then a
catch-all Response) — through the interpreter and pins the
``{name, status, statusCode}`` contract the caller reasons about. The REST GET
helpers are thin and live-only; this suite covers the offline consumer contract.
"""
from __future__ import annotations

from flow_run_inspect import _extract_status_code, summarize_actions

# A recorded cascade mirroring the scope-vs-handler trap: the connector call
# Failed with a
# 400, its runAfter:[Failed] handler Succeeded (it set the raw error into a
# body), the containing Switch scope is nonetheless marked Failed, a Skipped
# success branch shows the path not taken, and a catch-all Response returns a
# generic message. statusCode lives in each action's fetched outputs.
_G23_ACTIONS = [
    {"name": "Invoke_ServiceNow", "status": "Failed", "outputs": {"statusCode": 400}},
    {"name": "Set_error_body", "status": "Succeeded", "outputs": {"statusCode": 200}},
    {"name": "Switch_on_result", "status": "Failed", "outputs": None},
    {"name": "Success_Response", "status": "Skipped", "outputs": None},
    {"name": "CatchAll_Response", "status": "Succeeded", "outputs": {"statusCode": 500}},
]


def test_summary_preserves_name_and_status_in_order():
    summary = summarize_actions(_G23_ACTIONS)
    assert [a["name"] for a in summary] == [
        "Invoke_ServiceNow", "Set_error_body", "Switch_on_result",
        "Success_Response", "CatchAll_Response",
    ]
    assert [a["status"] for a in summary] == [
        "Failed", "Succeeded", "Failed", "Skipped", "Succeeded",
    ]


def test_summary_surfaces_the_g23_signal():
    # The interpreter must expose that the connector Failed (400) even though a
    # downstream handler Succeeded and the final Response Succeeded (500). This
    # is the exact data the skill-doc teaches the agent to read.
    summary = summarize_actions(_G23_ACTIONS)
    by_name = {a["name"]: a for a in summary}
    assert by_name["Invoke_ServiceNow"]["status"] == "Failed"
    assert by_name["Invoke_ServiceNow"]["statusCode"] == 400
    assert by_name["Switch_on_result"]["status"] == "Failed"
    # The catch-all Response "Succeeded" but carries the generic 500 — a reply
    # reader alone would see only this.
    assert by_name["CatchAll_Response"]["statusCode"] == 500


def test_skipped_action_has_null_status_code():
    summary = summarize_actions([
        {"name": "Skipped_branch", "status": "Skipped", "outputs": None},
    ])
    assert summary[0]["statusCode"] is None


def test_empty_actions_yields_empty_summary():
    assert summarize_actions([]) == []


def test_extract_status_code_handles_missing_and_non_int():
    assert _extract_status_code(None) is None
    assert _extract_status_code({}) is None
    assert _extract_status_code({"statusCode": 200}) == 200
    # A non-int statusCode (malformed outputs) must not leak through as truthy.
    assert _extract_status_code({"statusCode": "200"}) is None
    assert _extract_status_code("not-a-dict") is None


def test_missing_keys_do_not_raise():
    # Defensive: a partial action dict must not KeyError the interpreter.
    summary = summarize_actions([{"status": "Succeeded"}])
    assert summary == [{"name": None, "status": "Succeeded", "statusCode": None}]


def test_cli_falls_back_to_acquire_when_no_env_token(capsys, monkeypatch):
    # With no FLOW_API_TOKEN, main() acquires a token via _resolve_token. Here the
    # acquisition path fails (no config), so it reports cleanly and returns 2.
    import flow_run_inspect
    monkeypatch.delenv("FLOW_API_TOKEN", raising=False)
    monkeypatch.setattr(flow_run_inspect, "_resolve_token", lambda env_tok: None)
    rc = flow_run_inspect.main(["--environment", "e" * 32, "--flow", "f" * 32])
    out = capsys.readouterr().out
    assert rc == 2
    assert "FLOW_API_TOKEN" in out


def test_resolve_token_prefers_env_token():
    import flow_run_inspect
    assert flow_run_inspect._resolve_token("explicit-tok") == "explicit-tok"


def test_cli_renders_cascade(capsys, monkeypatch):
    import flow_run_inspect
    monkeypatch.setenv("FLOW_API_TOKEN", "tok")
    monkeypatch.setattr(flow_run_inspect, "get_latest_run",
                        lambda env, flow, token: {"name": "run-123"})
    monkeypatch.setattr(flow_run_inspect, "get_run_actions",
                        lambda env, flow, run_id, token: _G23_ACTIONS)
    rc = flow_run_inspect.main(["--environment", "e" * 32, "--flow", "f" * 32])
    out = capsys.readouterr().out
    assert rc == 0
    assert "run-123" in out
    assert "Invoke_ServiceNow" in out
    assert "400" in out


def test_cli_no_run_found(capsys, monkeypatch):
    import flow_run_inspect
    monkeypatch.setenv("FLOW_API_TOKEN", "tok")
    monkeypatch.setattr(flow_run_inspect, "get_latest_run",
                        lambda env, flow, token: None)
    rc = flow_run_inspect.main(["--environment", "e" * 32, "--flow", "f" * 32])
    assert rc == 1
    assert "No run found" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# environment-id resolution: config.json carries only the Dataverse org URL, not
# the Power Platform environment GUID the Flow API needs. match_environment_id
# maps one to the other from a listed environments payload, so a maker need not
# hand-find the GUID.
# --------------------------------------------------------------------------- #

_ENVIRONMENTS = [
    {
        "name": "11111111-1111-1111-1111-111111111111",
        "properties": {"linkedEnvironmentMetadata": {
            "instanceApiUrl": "https://orgOTHER.crm.dynamics.com",
        }},
    },
    {
        "name": "22222222-2222-2222-2222-222222222222",
        "properties": {"linkedEnvironmentMetadata": {
            "instanceApiUrl": "https://orgexample.crm.dynamics.com",
        }},
    },
]


def test_match_environment_id_by_instance_api_url():
    from flow_run_inspect import match_environment_id
    env_id = match_environment_id(_ENVIRONMENTS, "https://orgexample.crm.dynamics.com")
    assert env_id == "22222222-2222-2222-2222-222222222222"


def test_match_environment_id_ignores_scheme_and_trailing_slash():
    from flow_run_inspect import match_environment_id
    env_id = match_environment_id(_ENVIRONMENTS, "orgexample.crm.dynamics.com/")
    assert env_id == "22222222-2222-2222-2222-222222222222"


def test_match_environment_id_via_instance_url_field():
    from flow_run_inspect import match_environment_id
    envs = [{"name": "33333333-3333-3333-3333-333333333333",
             "properties": {"linkedEnvironmentMetadata": {
                 "instanceUrl": "https://orgabc.crm.dynamics.com/"}}}]
    assert match_environment_id(envs, "https://orgabc.crm.dynamics.com") == \
        "33333333-3333-3333-3333-333333333333"


def test_match_environment_id_no_match_returns_none():
    from flow_run_inspect import match_environment_id
    assert match_environment_id(_ENVIRONMENTS, "https://orgnope.crm.dynamics.com") is None


def test_cli_resolves_environment_when_not_passed(capsys, monkeypatch):
    import flow_run_inspect
    monkeypatch.setenv("FLOW_API_TOKEN", "tok")
    monkeypatch.setattr(flow_run_inspect, "load_config",
                        lambda: {"dataverseEndpoint": "https://orgexample.crm.dynamics.com"})
    monkeypatch.setattr(flow_run_inspect, "list_environments",
                        lambda token: _ENVIRONMENTS)
    captured = {}

    def fake_latest(env, flow, token):
        captured["env"] = env
        return {"name": "run-9"}

    monkeypatch.setattr(flow_run_inspect, "get_latest_run", fake_latest)
    monkeypatch.setattr(flow_run_inspect, "get_run_actions",
                        lambda env, flow, run_id, token: [])
    rc = flow_run_inspect.main(["--flow", "f" * 32])
    out = capsys.readouterr().out
    assert rc == 0
    assert captured["env"] == "22222222-2222-2222-2222-222222222222"
    assert "22222222" in out  # reports the resolved environment


def test_cli_env_resolution_failure_is_actionable(capsys, monkeypatch):
    import flow_run_inspect
    monkeypatch.setenv("FLOW_API_TOKEN", "tok")
    monkeypatch.setattr(flow_run_inspect, "load_config",
                        lambda: {"dataverseEndpoint": "https://orgnope.crm.dynamics.com"})
    monkeypatch.setattr(flow_run_inspect, "list_environments",
                        lambda token: _ENVIRONMENTS)
    rc = flow_run_inspect.main(["--flow", "f" * 32])
    out = capsys.readouterr().out
    assert rc == 2
    assert "--environment" in out  # tells the operator to pass it explicitly


def test_validate_run_id_rejects_path_separators():
    import pytest

    from flow_run_inspect import _validate_run_id
    _validate_run_id("08585237123456789")          # opaque token — ok
    _validate_run_id("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")  # guid — ok
    for bad in ("../actions", "x/y", "a?b", "a b", ""):
        with pytest.raises(ValueError):
            _validate_run_id(bad)


def test_sas_fetch_failure_does_not_log_the_signed_url(monkeypatch, caplog):
    import logging

    import flow_run_inspect

    signed = "https://blob.example/outputs?sig=SECRET-SAS-TOKEN"

    class _Resp:
        status_code = 200

        def json(self):
            return {"value": [{
                "name": "Invoke", "properties": {
                    "status": "Failed",
                    "outputsLink": {"uri": signed}}}]}

    def _raise(url, headers=None, timeout=None):
        if url == signed:
            raise ConnectionError(f"failed connecting to {signed}")
        return _Resp()

    monkeypatch.setattr(flow_run_inspect, "_get_json",
                        lambda url, headers: _Resp())
    monkeypatch.setattr(flow_run_inspect.requests, "get", _raise)
    with caplog.at_level(logging.WARNING):
        flow_run_inspect.get_run_actions("f" * 32, "f" * 32, "run-1", "tok")
    assert "SECRET-SAS-TOKEN" not in caplog.text  # the signed url must never leak


# --------------------------------------------------------------------------- #
# Auth header: every Flow Management GET must carry the acquired bearer token.
# These pin the HTTP-request layer the pure-interpreter suite above does not
# reach — a regression that dropped or failed to interpolate the token would
# make the whole "why did the flow fail" surface silently 401.
# --------------------------------------------------------------------------- #


def test_auth_headers_interpolates_bearer_token():
    from flow_run_inspect import _auth_headers
    token = "abc123.def456"
    headers = _auth_headers(token)
    # Built by concatenation so the assertion proves the token was interpolated,
    # not that a literal template string was returned.
    assert headers["Authorization"] == "Bearer " + token
    assert token in headers["Authorization"]
    assert "{token}" not in headers["Authorization"]


def test_outgoing_request_carries_bearer_token(monkeypatch):
    import flow_run_inspect

    token = "sentinel-token-9f8e7d"
    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"value": [{"name": "run-1"}]}

    def _fake_get(url, headers=None, timeout=None):
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr(flow_run_inspect.requests, "get", _fake_get)
    flow_run_inspect.get_latest_run("e" * 32, "f" * 32, token)
    assert captured["headers"]["Authorization"] == "Bearer " + token

