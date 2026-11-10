# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Topic-action entry, recovery guidance and caller-progress boundaries."""

from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest
import responses

import topic_actions as entry
from agentbuilder import DEFAULT_API_VERSION, AgentBuilderError, AgentBuilderHTTPError
from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as native


TENANT_ID = "00000000-0000-0000-0000-000000004444"
ENVIRONMENT_ID = native.MOCK_ENV_ID
AGENT_ID = native.MOCK_AGENT_ID
HOST = (
    "https://0000000000000000000000000000111."
    "1.environment.api.test.powerplatform.com"
)


@pytest.fixture
def request_value() -> dict:
    return {
        "target": {
            "tenantId": TENANT_ID,
            "environmentId": ENVIRONMENT_ID,
            "agentId": AGENT_ID,
        },
        "action": "disable",
        "setKeys": ["synthetic-set"],
        "entry": "caller",
        "callerContext": {"progress": {"connection": "done"}, "private": "do-not-emit"},
    }


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    local = tmp_path / ".local"
    (local / "setup").mkdir(parents=True)
    (local / "config.json").write_text(json.dumps({
        "releaseLine": "da",
        "environmentId": ENVIRONMENT_ID,
        "activeAgent": "selected",
        "agents": [{"slug": "selected", "botId": AGENT_ID}],
        "agent": {"slug": "stale", "botId": TENANT_ID},
    }), encoding="utf-8")
    (local / "setup" / "config.json").write_text(json.dumps({
        "schema_version": 4,
        "environment": {
            "id": ENVIRONMENT_ID,
            "tenant_id": TENANT_ID,
            "power_platform_api_endpoint": HOST,
            "ring": "test",
            "api_version": DEFAULT_API_VERSION,
        },
        "agents": {
            AGENT_ID: {
                "agent": {"id": AGENT_ID, "workspace_slug": "selected"},
                "connect_ready": True,
                "workspace": {"folder": "selected", "agent_path": "selected\\agent.mcs.yml"},
                "steps": {"SETUP-07": {"state": "done"}},
            },
        },
    }), encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def forbid_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("Authentication must be explicitly stubbed in this test.")
    monkeypatch.setattr(entry, "authenticate_flightcheck", forbidden)


def _auth(monkeypatch: pytest.MonkeyPatch, *, tenant=TENANT_ID, account="maker@example.com"):
    calls = []

    def authenticate(*args, **kwargs):
        calls.append((args, kwargs))
        return "private-token", tenant, account

    monkeypatch.setattr(entry, "authenticate_flightcheck", authenticate)
    return calls


def _change_json(path: Path, change) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    change(value)
    path.write_text(json.dumps(value), encoding="utf-8")


@responses.activate
def test_read_only_check_verifies_exact_target_and_preserves_progress(
    workspace, request_value, monkeypatch,
):
    require_validated_mock(native)
    response = native.get_agent()
    response["url"] = response["url"].replace(native.MOCK_AGENTBUILDER_BASE, HOST)
    responses.add(**response)
    auth_calls = _auth(monkeypatch)
    original = deepcopy(request_value)
    files = {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}

    result = entry.inspect_request(
        request_value, workspace_root=workspace, account_hint="MAKER@example.com",
    )

    assert result["reason"] == "inspection_only"
    assert result["checks"] == {
        "account": "verified", "targetReadAccess": "verified",
        "writeAuthority": "unverified", "topicSets": "unverified",
    }
    assert result["completed"] is False
    assert result["writeStatus"] == "not_attempted"
    assert "write authority and topic-set readiness remain unverified" in result["message"]
    assert request_value == original
    assert result["callerContext"] == original["callerContext"]
    assert result["callerContext"] is not request_value["callerContext"]
    assert len(responses.calls) == 1
    assert responses.calls[0].request.method == "GET"
    assert f"/minimalBots/api/{AGENT_ID}" in responses.calls[0].request.url
    assert auth_calls == [(("test",), {
        "cache_path": workspace / entry.DEFAULT_TOKEN_CACHE,
        "account_hint": "MAKER@example.com",
        "include_connectivity": False,
        "allow_write": False,
        "emit_account_identity": False,
        "return_account_identity": True,
    })]
    assert files == {
        path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()
    }


def _materialize_for_topic_actions(workspace):
    def update(document):
        record = document["agents"][AGENT_ID]
        record["connect_ready"] = False
        record["workspace"] = {"folder": "selected", "agent_path": "selected\\agent.mcs.yml"}
        record["steps"] = {"SETUP-07": {"state": "done"}}
    _change_json(workspace / ".local" / "setup" / "config.json", update)


def test_topic_actions_requires_preparation_not_connection_health(workspace, request_value):
    _materialize_for_topic_actions(workspace)
    connection = entry._workspace_target(
        workspace, request_value["target"], require_connect_ready=False,
    )
    assert connection["host"] == HOST
    with pytest.raises(entry.TopicActionsError) as error:
        entry._workspace_target(workspace, request_value["target"])
    assert error.value.reason == "setup_incomplete"


def test_new_entry_stops_before_auth_when_workspace_preparation_is_missing(workspace, request_value):
    _change_json(
        workspace / ".local" / "setup" / "config.json",
        lambda value: value["agents"][AGENT_ID].update(steps={}),
    )
    result = entry.run_topic_actions(
        request_value, workspace_root=workspace,
        confirm=lambda _: pytest.fail("Missing preparation cannot ask for consent."),
    )
    assert result["reason"] == "setup_incomplete"
    assert result["writeStatus"] == "not_attempted"
    assert result["callerContext"] == request_value["callerContext"]


def test_new_direct_and_caller_entries_share_controller_without_completing_caller(
    workspace, request_value, monkeypatch,
):
    from tests.scripts.test_topic_actions_runtime import SyntheticBackend, operation_evidence

    _materialize_for_topic_actions(workspace)
    _auth(monkeypatch)
    backends = []

    def backend(*args):
        assert isinstance(args[-1], entry.TopicActionsClient)
        assert args[-1].single_attempt is True
        assert args[-1].read_only is False
        assert args[-1].signed_in_username == "maker@example.com"
        result = SyntheticBackend([operation_evidence()], gates=("release_control_unavailable",))
        backends.append(result)
        return result

    monkeypatch.setattr("topic_actions_native.NativeActionBackend", backend)
    direct = {**request_value, "entry": "direct", "callerContext": {}}
    results = [
        entry.run_topic_actions(
            value, workspace_root=workspace,
            confirm=lambda _: pytest.fail("Release blocker cannot ask for consent."),
        )
        for value in (direct, request_value)
    ]
    assert results[0]["plan"] == results[1]["plan"]
    assert results[1]["callerContext"] == request_value["callerContext"]
    assert results[1]["callerContext"] is not request_value["callerContext"]
    assert all(not result["completed"] for result in results)
    assert all(result["reason"] == "release_control_unavailable" for result in results)
    assert all(not backend.submissions for backend in backends)


def test_new_entry_cancellation_preserves_context_without_setup_or_auth(tmp_path, request_value):
    result = entry.run_topic_actions(
        request_value, workspace_root=tmp_path, cancelled=True,
        confirm=lambda _: pytest.fail("Cancellation cannot ask for consent."),
    )
    assert result["status"] == "cancelled"
    assert result["callerContext"] == request_value["callerContext"]


def test_proposed_catalog_cli_does_not_authenticate_or_claim_installed_availability(monkeypatch, capsys):
    monkeypatch.setattr(entry.sys, "stdin", io.StringIO(""))
    assert entry.main(["--list-sets"]) == 0
    result = json.loads(capsys.readouterr().out.split(entry.RESULT_MARKER, 1)[1])
    assert result["status"] == "source_catalog_only"
    assert not result["completed"]
    assert result["writeStatus"] == "not_attempted"


@pytest.mark.parametrize(("answer", "status", "completed"), [
    ("approve\n", "completed", True),
    ("deny\n", "denied", False),
    ("cancel\n", "cancelled", False),
    ("", "cancelled", False),
    ("yes\n", "blocked", False),
])
def test_execute_cli_reviews_then_uses_explicit_same_session_consent(
    workspace, request_value, monkeypatch, capsys, answer, status, completed,
):
    from tests.scripts.test_topic_actions_runtime import SyntheticBackend, operation_evidence
    from topic_actions_discovery import DiscoveryTarget

    auth_calls = _auth(monkeypatch)
    before = operation_evidence({"a": "On", "shared": "On"})
    after = operation_evidence(revision="r2")
    target = DiscoveryTarget(TENANT_ID, ENVIRONMENT_ID, AGENT_ID)
    def bind(packet):
        for row in packet.body["botComponentChanges"]:
            row["component"]["parentBotId"] = AGENT_ID
        return replace(
            packet, snapshot=replace(packet.snapshot, evidence=replace(packet.snapshot.evidence, target=target)),
        )
    before, after = bind(before), bind(after)
    request_value["initializeBaseline"] = True
    backend = SyntheticBackend([before, before, after])
    monkeypatch.setattr("topic_actions_native.NativeActionBackend", lambda *args: backend)
    monkeypatch.setattr(entry.sys, "stdin", io.StringIO(json.dumps(request_value) + "\n" + answer))

    exit_code = entry.main(["--execute", "--workspace-root", str(workspace)])

    output = capsys.readouterr().out
    lines = output.splitlines()
    assert lines[0].startswith(entry.REVIEW_MARKER)
    review = json.loads(lines[0].removeprefix(entry.REVIEW_MARKER))
    result = json.loads(lines[-1].removeprefix(entry.RESULT_MARKER))
    assert review["action"] == "disable"
    assert len(review["proposedChanges"]) == 2
    assert result["status"] == status
    assert result["completed"] is completed
    assert exit_code == (1 if status == "blocked" else 0)
    assert auth_calls == [(("test",), {
        "cache_path": workspace / entry.DEFAULT_TOKEN_CACHE,
        "account_hint": None,
        "include_connectivity": False,
        "allow_write": True,
        "emit_account_identity": False,
        "return_account_identity": True,
    })]
    assert len(backend.submissions) == (1 if completed else 0)
    assert "callerContext" not in result
    assert "do-not-emit" not in output
    assert "private-token" not in output
    assert review["baseline"]["status"] == "capture_before_first_write"


def test_preview_is_truthful_nonmutating_and_uses_read_only_auth(
    workspace, request_value, monkeypatch, capsys,
):
    from tests.scripts.test_topic_actions_runtime import SyntheticBackend, operation_evidence

    auth_calls = _auth(monkeypatch)
    backend = SyntheticBackend([operation_evidence({"a": "On", "shared": "On"})])
    monkeypatch.setattr("topic_actions_native.NativeActionBackend", lambda *args: backend)
    monkeypatch.setattr(entry.sys, "stdin", io.StringIO(json.dumps(request_value)))

    assert entry.main(["--preview", "--workspace-root", str(workspace)]) == 0

    output = capsys.readouterr().out
    result = json.loads(output.removeprefix(entry.RESULT_MARKER))
    assert result["status"] == "preview"
    assert not result["completed"]
    assert result["writeStatus"] == "not_attempted"
    assert entry.REVIEW_MARKER not in output
    assert auth_calls[0][1]["allow_write"] is False
    assert auth_calls[0][1]["include_connectivity"] is False
    assert backend.reads == 1 and not backend.submissions


def test_restore_request_derives_scope_and_cannot_initialize_or_narrow_original(request_value):
    value = {**request_value, "action": "restore"}
    value.pop("setKeys")
    assert entry.validate_request(value)["setKeys"] == []
    for update in (
        {"setKeys": ["synthetic-set"]}, {"initializeBaseline": True},
        {"initializeBaseline": "true"},
    ):
        with pytest.raises(entry.TopicActionsError):
            entry.validate_request({**value, **update})


def test_restore_missing_original_stops_without_authentication(workspace, request_value):
    value = {**request_value, "action": "restore", "setKeys": []}
    result = entry.run_topic_actions(
        value, workspace_root=workspace,
        confirm=lambda _: pytest.fail("Missing original evidence cannot ask for consent."),
    )
    assert result["reason"] == "original_baseline_missing"
    assert "cannot be reconstructed from today's states" in result["message"]
    assert result["writeStatus"] == "not_attempted"


@pytest.mark.parametrize("changes", [
    {"contractVersion": 2},
    {"contractVersion": True},
    {"action": "publish"},
    {"setKeys": []},
    {"setKeys": ["duplicate", "duplicate"]},
    {"setKeys": ["unsafe\nkey"]},
    {"setKeys": [{"not": "a key"}]},
    {"target": {"agentId": AGENT_ID}},
    {"entry": "another-caller"},
    {"callerContext": {}},
    {"approval": True},
])
def test_invalid_requests_stop_before_authentication(workspace, request_value, changes):
    request_value.update(changes)
    result = entry.inspect_request(request_value, workspace_root=workspace)
    assert result["reason"] == "invalid_request"
    assert result["writeStatus"] == "not_attempted"


@pytest.mark.parametrize(("state", "reason"), [
    ("missing", "setup_not_run"),
    ("malformed", "setup_broken"),
    ("incomplete", "setup_incomplete"),
    ("duplicate", "target_unverified"),
    ("host_mismatch", "target_unverified"),
    ("missing_workspace", "workspace_missing"),
    ("ambiguous_active_agent", "target_unverified"),
])
def test_setup_and_target_fail_closed(workspace, request_value, state, reason):
    path = workspace / ".local" / "setup" / "config.json"
    if state == "missing":
        path.unlink()
    elif state == "malformed":
        path.write_text("not JSON", encoding="utf-8")
    elif state == "incomplete":
        _change_json(path, lambda v: v["agents"][AGENT_ID].update(
            connect_ready=False, steps={"SETUP-07": {"state": "pending"}},
        ))
    elif state == "duplicate":
        _change_json(path, lambda v: v["agents"].update({
            TENANT_ID: deepcopy(v["agents"][AGENT_ID]),
        }))
    elif state == "missing_workspace":
        (workspace / ".local" / "config.json").unlink()
    elif state == "ambiguous_active_agent":
        _change_json(workspace / ".local" / "config.json", lambda v: v["agents"].append(
            {"slug": "selected", "botId": TENANT_ID},
        ))
    else:
        _change_json(path, lambda v: v["environment"].update(
            power_platform_api_endpoint=native.MOCK_AGENTBUILDER_BASE,
        ))
    result = entry.inspect_request(request_value, workspace_root=workspace)
    assert result["reason"] == reason
    assert result["callerContext"] == request_value["callerContext"]
    assert result["writeStatus"] == "not_attempted"


def test_requested_target_cannot_switch_the_active_agent(workspace, request_value):
    request_value["target"]["agentId"] = TENANT_ID
    result = entry.inspect_request(request_value, workspace_root=workspace)
    assert result["reason"] == "target_unverified"


@responses.activate
@pytest.mark.parametrize(("tenant", "account"), [
    (AGENT_ID, "maker@example.com"),
    (TENANT_ID, "different@example.com"),
    (TENANT_ID, None),
])
def test_wrong_or_unknown_account_stops_before_agent_lookup(
    workspace, request_value, monkeypatch, tenant, account,
):
    _auth(monkeypatch, tenant=tenant, account=account)
    result = entry.inspect_request(
        request_value, workspace_root=workspace, account_hint="maker@example.com",
    )
    assert result["reason"] == "account_mismatch"
    assert result["checks"]["targetReadAccess"] == "unverified"


@responses.activate
@pytest.mark.parametrize(("status", "reason"), [
    (403, "access_denied"), (404, "target_not_found"), (500, "target_unverified"),
])
def test_lookup_failures_do_not_expose_raw_service_bodies(
    workspace, request_value, monkeypatch, status, reason,
):
    _auth(monkeypatch)
    responses.add(
        responses.GET, f"{HOST}/copilotstudio/minimalBots/api/{AGENT_ID}",
        status=status, json={"error": {"message": "private-response-body"}},
    )
    result = entry.inspect_request(request_value, workspace_root=workspace)
    assert result["reason"] == reason
    assert result["writeStatus"] == "not_attempted"
    assert "private-response-body" not in json.dumps(result)
    assert all(call.request.method == "GET" for call in responses.calls)


@responses.activate
def test_remote_identity_mismatch_is_not_success(workspace, request_value, monkeypatch):
    _auth(monkeypatch)
    response = native.get_agent(payload={**native.agent(), "botId": TENANT_ID})
    response["url"] = response["url"].replace(native.MOCK_AGENTBUILDER_BASE, HOST)
    responses.add(**response)
    result = entry.inspect_request(request_value, workspace_root=workspace)
    assert result["reason"] == "target_unverified"
    assert result["completed"] is False


def test_cancel_preserves_progress_without_setup_or_authentication(tmp_path, request_value):
    result = entry.inspect_request(
        request_value, workspace_root=tmp_path, cancelled=True,
    )
    assert result["status"] == "cancelled"
    assert result["callerContext"] == request_value["callerContext"]
    assert result["writeStatus"] == "not_attempted"
    assert list(tmp_path.iterdir()) == []


@responses.activate
def test_cli_emits_only_public_result(workspace, request_value, monkeypatch, capsys):
    _auth(monkeypatch)
    response = native.get_agent()
    response["url"] = response["url"].replace(native.MOCK_AGENTBUILDER_BASE, HOST)
    responses.add(**response)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(request_value)))

    assert entry.main(["--workspace-root", str(workspace)]) == 0

    output = capsys.readouterr().out
    assert output.startswith(entry.RESULT_MARKER)
    assert "do-not-emit" not in output
    assert "private-token" not in output
    public = json.loads(output.removeprefix(entry.RESULT_MARKER))
    assert "callerContext" not in public
    assert public["reason"] == "inspection_only"
    assert public["completed"] is False


def test_authentication_errors_are_sanitized(workspace, request_value, monkeypatch):
    def fail(*args, **kwargs):
        raise AgentBuilderError("private-token private-response-body")
    monkeypatch.setattr(entry, "authenticate_flightcheck", fail)
    result = entry.inspect_request(request_value, workspace_root=workspace)
    assert result["reason"] == "authentication_failed"
    assert "private-token" not in json.dumps(result)


def test_cli_rejects_malformed_json_without_echoing_it(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO('{"private-token": invalid}'))
    assert entry.main([]) == 1
    output = capsys.readouterr().out
    assert "private-token" not in output
    assert json.loads(output.removeprefix(entry.RESULT_MARKER))["reason"] == "invalid_request"


@pytest.mark.parametrize("runner", [entry.inspect_request, entry.run_topic_actions])
@pytest.mark.parametrize(("state", "reason", "explanation", "setup_route"), [
    ("missing", "setup_not_run", "has not established the account, agent and environment", True),
    ("incomplete", "setup_incomplete", "local workspace", True),
    ("malformed", "setup_broken", "could not be read", False),
    ("missing_workspace", "workspace_missing", "workspace information is missing", False),
    ("completed_without_workspace", "setup_broken", "recorded as complete", False),
    ("wrong_target", "target_unverified", "does not match verified workspace identity", False),
])
def test_entry_recovery_is_specific_and_preserves_existing_progress(
    workspace, request_value, runner, state, reason, explanation, setup_route,
):
    setup_path = workspace / ".local" / "setup" / "config.json"
    if state == "missing":
        setup_path.unlink()
    elif state == "incomplete":
        _change_json(setup_path, lambda value: value["agents"][AGENT_ID].update(
            steps={"SETUP-07": {"state": "blocked"}},
        ))
    elif state == "malformed":
        setup_path.write_text("private-malformed-data", encoding="utf-8")
    elif state == "missing_workspace":
        (workspace / ".local" / "config.json").unlink()
    elif state == "completed_without_workspace":
        _change_json(setup_path, lambda value: value["agents"][AGENT_ID].pop("workspace"))
    else:
        request_value["target"]["agentId"] = TENANT_ID
    files = {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}
    original = deepcopy(request_value)
    options = {"workspace_root": workspace}
    if runner is entry.run_topic_actions:
        options["confirm"] = lambda _: pytest.fail("A blocked entry cannot ask for consent.")

    result = runner(request_value, **options)

    assert result["reason"] == reason
    assert explanation in result["message"]
    assert "No topics were changed." in result["message"]
    assert ("/setup" in result["message"]) is setup_route
    if setup_route:
        assert "return to this conversation" in result["message"]
        assert "new topic-change request" in result["message"]
    else:
        assert "recovery route for this problem has not been confirmed" in result["message"]
    assert "private-malformed-data" not in json.dumps(result)
    assert not result["completed"]
    assert result["writeStatus"] == "not_attempted"
    assert result["callerContext"] == original["callerContext"]
    result["callerContext"]["progress"]["connection"] = "changed"
    assert request_value == original
    assert files == {path: path.read_bytes() for path in workspace.rglob("*") if path.is_file()}


@responses.activate
def test_m1_inspection_does_not_require_business_connection_readiness(
    workspace, request_value, monkeypatch,
):
    _materialize_for_topic_actions(workspace)
    _auth(monkeypatch)
    require_validated_mock(native)
    response = native.get_agent()
    response["url"] = response["url"].replace(native.MOCK_AGENTBUILDER_BASE, HOST)
    responses.add(**response)

    result = entry.inspect_request(request_value, workspace_root=workspace)

    assert result["reason"] == "inspection_only"
    assert result["checks"]["targetReadAccess"] == "verified"
    assert result["checks"]["writeAuthority"] == "unverified"
    assert len(responses.calls) == 1
    assert responses.calls[0].request.method == "GET"


@pytest.mark.parametrize("runner", [entry.inspect_request, entry.run_topic_actions])
def test_authentication_http_failure_is_not_reported_as_agent_read_denial(
    workspace, request_value, runner, monkeypatch,
):
    def fail(*args, **kwargs):
        raise AgentBuilderHTTPError("private-response-body", 403)

    monkeypatch.setattr(entry, "authenticate_flightcheck", fail)
    options = {"workspace_root": workspace}
    if runner is entry.run_topic_actions:
        options["confirm"] = lambda _: pytest.fail("Authentication failure cannot ask for consent.")

    result = runner(request_value, **options)

    assert result["reason"] == "authentication_failed"
    assert "does not establish that the account lacks topic-edit permission" in result["message"]
    assert "private-response-body" not in json.dumps(result)
    assert result["writeStatus"] == "not_attempted"


@pytest.mark.parametrize(("failure", "reason", "explanation"), [
    (AgentBuilderHTTPError("private-response-body", 401), "authentication_failed", "couldn't verify"),
    (AgentBuilderHTTPError("private-response-body", 403), "access_denied", "denied read access"),
    (AgentBuilderHTTPError("private-response-body", 404), "target_not_found", "could not be accessed"),
    (AgentBuilderHTTPError("private-response-body", 500), "evidence_read_failed", "evidence was unavailable"),
    (AgentBuilderError("private-response-body"), "evidence_read_failed", "evidence was unavailable"),
])
def test_runtime_entry_distinguishes_denied_reads_from_unavailable_evidence(
    workspace, request_value, monkeypatch, failure, reason, explanation,
):
    _auth(monkeypatch)
    reads = []

    class UnavailableBackend:
        def read(self):
            reads.append(True)
            raise failure

        def admission_blockers(self, evidence):
            pytest.fail("Unavailable evidence cannot reach admission.")

        def submit_once(self, *args):
            pytest.fail("Unavailable evidence cannot submit changes.")

    monkeypatch.setattr("topic_actions_native.NativeActionBackend", lambda *args: UnavailableBackend())
    result = entry.run_topic_actions(
        request_value, workspace_root=workspace,
        confirm=lambda _: pytest.fail("Unavailable evidence cannot ask for consent."),
    )

    assert result["reason"] == reason
    assert explanation in result["message"]
    assert "No topics were changed." in result["message"]
    assert "private-response-body" not in json.dumps(result)
    if reason == "access_denied":
        assert "administrator responsible for that agent and environment" in result["message"]
        assert "Topic-edit permission is still unverified" in result["message"]
    assert len(reads) == 1
    assert result["writeStatus"] == "not_attempted"
    assert not result["completed"]
    assert result["callerContext"] == request_value["callerContext"]


def test_unverified_package_and_topic_evidence_does_not_claim_verified_absence(
    workspace, request_value, monkeypatch,
):
    from tests.scripts.test_topic_actions_runtime import SyntheticBackend, operation_evidence

    _auth(monkeypatch)
    evidence = replace(operation_evidence(), blockers=(
        "installed_package_unverified:selected-package",
        "unresolved_member:selected-set:topic",
    ))
    backend = SyntheticBackend([evidence])
    monkeypatch.setattr("topic_actions_native.NativeActionBackend", lambda *args: backend)

    result = entry.run_topic_actions(
        request_value, workspace_root=workspace,
        confirm=lambda _: pytest.fail("Unresolved evidence cannot ask for consent."),
    )

    assert "installation could not be verified" in result["message"]
    assert "does not establish that a package is missing" in result["message"]
    assert "may be missing or ambiguous" in result["message"]
    assert "selected scope was not narrowed" in result["message"]
    assert "/connect" not in result["message"]
    assert "/setup" not in result["message"]
    assert result["callerContext"] == request_value["callerContext"]
    assert result["writeStatus"] == "not_attempted"
    assert not backend.submissions


@pytest.mark.parametrize("runner", [entry.inspect_request, entry.run_topic_actions])
def test_cancellation_has_truthful_copy_without_marking_caller_steps_complete(
    tmp_path, request_value, runner,
):
    options = {"workspace_root": tmp_path, "cancelled": True}
    if runner is entry.run_topic_actions:
        options["confirm"] = lambda _: pytest.fail("Cancellation cannot ask for consent.")
    original = deepcopy(request_value)

    result = runner(request_value, **options)

    assert result["message"] == "Canceled. No topics were changed."
    assert result["callerContext"] == original["callerContext"]
    assert request_value == original
    assert not result["completed"]
    assert result["writeStatus"] == "not_attempted"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("tenant", "account"), [
    (ENVIRONMENT_ID, "maker@example.com"),
    (TENANT_ID, "other@example.com"),
    (TENANT_ID, None),
])
def test_authentication_cannot_change_requested_account_or_tenant(
    workspace, request_value, monkeypatch, tenant, account,
):
    _auth(monkeypatch, tenant=tenant, account=account)
    result = entry.run_topic_actions(
        request_value, workspace_root=workspace, account_hint="maker@example.com",
        confirm=lambda _: pytest.fail("A mismatched account cannot request approval."),
    )
    assert result["reason"] == "account_mismatch"
    assert result["writeStatus"] == "not_attempted"


def test_topic_actions_imports_without_connect_workday_or_evaluation_runtime():
    script = """
import importlib
import importlib.abc
from pathlib import Path
import sys

class ForbidConnectDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("minimalbot_evaluation", "connect_workday", "setup_existing_da")):
            raise ImportError("Topic actions must not depend on " + fullname)

sys.meta_path.insert(0, ForbidConnectDependencies())
for module in Path.cwd().glob("topic_actions*.py"):
    importlib.import_module(module.stem)
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=Path(entry.__file__).parent,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
