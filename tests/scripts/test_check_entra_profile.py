# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Public beta profile coverage, permissions and real CLI report contracts."""

import base64
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import requests
import respx

import check_entra_profile as check
from flightcheck import cli, registry
from flightcheck.checks.entra_profile import run_entra_profile_checks
from flightcheck.graph_client import GraphClient, GraphPermissionError
from tests.conftest import require_validated_mock
from tests.mocks import graph, graph_profile as profiles


def _token(tenant=graph.MOCK_TENANT_ID):
    claims = base64.urlsafe_b64encode(json.dumps({"tid": tenant}).encode()).decode().rstrip("=")
    return f"header.{claims}.signature"


@pytest.fixture
def client():
    require_validated_mock(graph)
    require_validated_mock(profiles)
    client = GraphClient(graph.MOCK_TENANT_ID, strict_reads=True)
    client._token = _token()
    client.signed_in_username = "maker@example.test"
    return client


def _tenant_routes(size=2, make_profile=profiles.profile):
    respx.get(f"{graph.GRAPH_BASE}/users").respond(json={
        "value": [profiles.directory_user(i + 1) for i in range(size)],
    })
    return respx.post(f"{profiles.GRAPH_BASE}/$batch").mock(
        side_effect=lambda request: profiles.batch_response(request, make_profile=make_profile),
    )


@respx.mock
def test_own_profile_uses_beta_and_never_reports_values_or_tenant_percentages(client):
    route = respx.get(f"{profiles.GRAPH_BASE}/me/profile").respond(json=profiles.profile())
    report = check.check_attributes(client, "me", ["jobTitle", "employeeType", "workCountry"])
    assert report["status"] == "Passed"
    assert report["scope"] == "me" and report["profileVerified"] is True
    assert report["coverageVerified"] is False
    assert report["usersChecked"] == 1
    assert not route.calls[0].request.url.params
    assert all(row["availability"] == "Available" for row in report["results"])
    text = json.dumps(report)
    assert "coveragePercent" not in text and "isSample" not in report
    assert "Mock title" not in text and "maker@example.test" not in text


@pytest.mark.parametrize("variant,expected", [
    ("null", "Empty"), ("blank", "Empty"), ("omitted", "Not returned"),
    ("zero", "Available"), ("empty_section", "Empty"), ("omitted_section", "Not returned"),
    ("metadata_only", "Unverified"), ("continued", "Unverified"),
    ("same_current", "Available"), ("conflicting_current", "Unverified"),
    ("unknown_current", "Unverified"), ("no_current", "Empty"),
])
@respx.mock
def test_profile_presence_distinguishes_empty_omitted_and_source_ambiguity(client, variant, expected):
    profile = profiles.profile()
    field = "jobTitle"
    detail = profile["positions"][0]["detail"]
    if variant in {"null", "blank"}:
        detail["jobTitle"] = None if variant == "null" else "  "
    elif variant == "omitted":
        del detail["jobTitle"]
    elif variant == "zero":
        field = "layer"
    elif variant in {"empty_section", "omitted_section", "metadata_only"}:
        field = "skills"
        if variant == "omitted_section":
            del profile["skills"]
        elif variant == "metadata_only":
            profile["skills"] = [{"id": "test", "source": {"type": ["user"]}}]
    elif variant == "continued":
        profile["positions@odata.nextLink"] = "https://graph.microsoft.com/beta/me/profile/positions?$skip=1"
    elif variant in {"same_current", "conflicting_current"}:
        second = deepcopy(profile["positions"][0])
        if variant == "conflicting_current":
            second["detail"]["jobTitle"] = None
        profile["positions"].append(second)
    elif variant == "unknown_current":
        del profile["positions"][0]["isCurrent"]
    else:
        profile["positions"][0]["isCurrent"] = False
    respx.get(f"{profiles.GRAPH_BASE}/me/profile").respond(json=profile)
    report = check.check_attributes(client, "me", [field])
    assert report["results"] == [{"attribute": field, "availability": expected}]
    assert report["status"] == ("Passed" if expected == "Available" else "Warning")


@pytest.mark.parametrize("variant", ["bad_section", "bad_record", "bad_nested", "bad_integer", "bad_text"])
@respx.mock
def test_malformed_profile_data_is_an_error_not_an_empty_attribute(client, variant):
    profile = profiles.profile()
    field = "jobTitle"
    if variant == "bad_section":
        profile["positions"] = {}
    elif variant == "bad_record":
        profile["positions"] = [42]
    elif variant == "bad_nested":
        profile["positions"][0]["detail"] = []
    elif variant == "bad_integer":
        field = "layer"
        profile["positions"][0]["detail"]["layer"] = True
    else:
        profile["positions"][0]["detail"]["jobTitle"] = 42
    respx.get(f"{profiles.GRAPH_BASE}/me/profile").respond(json=profile)
    with pytest.raises(ValueError, match="invalid"):
        check.check_attributes(client, "me", [field])


@respx.mock
def test_section_checks_count_real_content_but_not_metadata_only_notes(client):
    profile = profiles.profile()
    profile["skills"] = [{"displayName": "Mock skill"}]
    profile["anniversaries"] = [{"type": "work", "date": "2020-01-01"}]
    profile["notes"] = [{
        "detail": {"contentType": "text", "content": None},
        "extensions": [{"customField": "Not a standard profile value"}],
    }]
    respx.get(f"{profiles.GRAPH_BASE}/me/profile").respond(json=profile)
    report = check.check_attributes(client, "me", ["skills", "anniversaries", "notes"])
    assert report["results"] == [
        {"attribute": "skills", "availability": "Available"},
        {"attribute": "anniversaries", "availability": "Available"},
        {"attribute": "notes", "availability": "Unverified"},
    ]
    assert "Mock skill" not in json.dumps(report)


@pytest.mark.parametrize("size,is_sample", [(1, False), (99, False), (100, False), (101, True)])
@respx.mock
def test_cap_is_100_and_profiles_are_batched_without_exposing_ids(client, size, is_sample):
    batch = _tenant_routes(size)
    report = check.check_attributes(client, "tenant", ["jobTitle"])
    count = min(size, 100)
    assert report["usersChecked"] == count
    assert report["isSample"] is is_sample
    assert report["populationComplete"] is not is_sample
    assert report["coverageLabel"].startswith("Sample coverage" if is_sample else "Tenant coverage")
    assert report["status"] == "Passed" and report["coverageVerified"] is True
    requests_sent = [json.loads(call.request.content)["requests"] for call in batch.calls]
    assert sum(map(len, requests_sent)) == count
    assert all(len(group) <= 20 for group in requests_sent)
    assert all(row["method"] == "GET" and row["url"].endswith("/profile") for group in requests_sent for row in group)
    assert profiles.directory_user()["id"] not in json.dumps(report)


@respx.mock
def test_enumeration_is_sequential_and_continuations_are_followed_before_profile_reads(client):
    respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=[
        httpx.Response(200, json={
            "value": [profiles.directory_user(1)],
            "@odata.nextLink": f"{graph.GRAPH_BASE}/users?$skiptoken=next",
        }),
        httpx.Response(200, json={"value": [profiles.directory_user(2)]}),
    ])
    respx.post(f"{profiles.GRAPH_BASE}/$batch").mock(side_effect=profiles.batch_response)
    report = check.check_attributes(client, "tenant", ["jobTitle"])
    assert report["usersChecked"] == 2 and report["populationComplete"] is True
    assert [call.request.method for call in respx.calls] == ["GET", "GET", "POST"]
    assert respx.calls[0].request.url.params["$top"] == "100"
    assert respx.calls[0].request.url.params["$select"] == "id,userType"
    assert "$skiptoken=next" in str(respx.calls[1].request.url)


@pytest.mark.parametrize("variant", ["empty", "duplicate", "guest", "invalid_id", "missing_id"])
@respx.mock
def test_invalid_directory_population_is_rejected_before_profile_requests(client, variant):
    users = [profiles.directory_user()]
    if variant == "empty":
        users = []
    elif variant == "duplicate":
        users.append(dict(users[0]))
    elif variant == "guest":
        users[0]["userType"] = "Guest"
    elif variant == "invalid_id":
        users[0]["id"] = "../me"
    else:
        del users[0]["id"]
    respx.get(f"{graph.GRAPH_BASE}/users").respond(json={"value": users})
    with pytest.raises(ValueError):
        check.check_attributes(client, "tenant", ["jobTitle"])
    assert len(respx.calls) == 1


@pytest.mark.parametrize("missing", [1, 2])
@respx.mock
def test_95_percent_threshold_is_applied_to_every_included_check(client, missing):
    index = [0]
    def profile():
        value = profiles.profile()
        if index[0] < missing:
            value["positions"][0]["detail"]["jobTitle"] = None
        index[0] += 1
        return value
    _tenant_routes(20, profile)
    report = check.check_attributes(client, "tenant", ["jobTitle"])
    assert report["results"][0]["coveragePercent"] == (20 - missing) * 5
    assert report["status"] == ("Passed" if missing == 1 else "Warning")


@respx.mock
def test_unknown_source_coverage_has_counts_but_no_misleading_percentage(client):
    value = profiles.profile()
    second = deepcopy(value["positions"][0])
    second["detail"]["employeeType"] = None
    value["positions"].append(second)
    _tenant_routes(2, lambda: value)
    report = check.check_attributes(client, "tenant", ["employeeType", "jobTitle"])
    rows = {row["attribute"]: row for row in report["results"]}
    assert rows["employeeType"]["coveragePercent"] is None
    assert rows["employeeType"]["unverified"] == 2 and rows["employeeType"]["empty"] == 0
    assert rows["jobTitle"]["coveragePercent"] == 100
    assert report["coverageVerified"] is False and report["status"] == "Warning"


@pytest.mark.parametrize("tenant_elapsed,own_elapsed", [(23, 1), (23, 8), (31, 1)])
def test_fallback_shares_deadline_excluding_authentication(monkeypatch, tenant_elapsed, own_elapsed):
    now = [0]
    monkeypatch.setattr("flightcheck.entra_profile.monotonic", lambda: now[0])
    monkeypatch.setattr("flightcheck.checks.entra_profile.monotonic", lambda: now[0])
    directory, own = Mock(), Mock()
    budgets = []
    def denied(*_args, **_kwargs):
        now[0] += tenant_elapsed
        raise GraphPermissionError("Denied")
    def authenticate():
        now[0] += 120
        return own
    def read(**kwargs):
        budgets.append(kwargs["time_budget"])
        now[0] += own_elapsed
        return profiles.profile()
    directory.get_bounded_collection.side_effect = denied
    own.get_bounded_profile.side_effect = read
    runner = SimpleNamespace(graph=directory, self_profile_graph=Mock(side_effect=authenticate))
    row = run_entra_profile_checks(runner)[0]
    assert budgets == ([30 - tenant_elapsed] if tenant_elapsed < 30 else [])
    if tenant_elapsed + own_elapsed < 30:
        assert row.status == "Warning" and row.evidence["profileVerified"] is True
        assert "Own profile only" in row.result
        assert "not a deployment blocker" in row.remediation
    else:
        assert row.status == "Error" and "budget expired" in row.result
        assert "results" not in row.evidence and "Restore the Graph read" in row.remediation
    assert runner.graph is directory


@pytest.mark.parametrize("failure", [
    TimeoutError("budget expired"), requests.ConnectionError("Network unavailable"), ValueError("Invalid data"),
])
def test_nonpermission_errors_do_not_trigger_fallback(failure):
    directory = Mock()
    directory.get_bounded_collection.side_effect = failure
    runner = SimpleNamespace(graph=directory, self_profile_graph=Mock())
    row = run_entra_profile_checks(runner)[0]
    assert row.status == "Error"
    assert "Restore the Graph read" in row.remediation
    runner.self_profile_graph.assert_not_called()


@pytest.mark.parametrize("selection", ["checkpoint", "profile"])
@pytest.mark.parametrize("access", ["tenant", "own", "neither", "network", "ambiguous"])
@respx.mock
def test_real_cli_reports_beta_coverage_and_nonblocking_access_limits(
    monkeypatch, tmp_path, selection, access,
):
    monkeypatch.chdir(tmp_path)
    scopes_used = []
    def authenticate(client, preferred_username=None, *, require_existing_consent=False):
        scopes_used.append(client._scopes)
        if access == "network":
            raise requests.ConnectionError("Network unavailable")
        if access in {"own", "neither"} and require_existing_consent:
            raise GraphPermissionError("Consent unavailable")
        client.signed_in_username = preferred_username
        client._token = _token()
        return client._token
    monkeypatch.setattr(GraphClient, "authenticate", authenticate)
    value = profiles.profile()
    if access == "ambiguous":
        other = deepcopy(value["positions"][0])
        other["detail"]["employeeType"] = None
        value["positions"].append(other)
    if access in {"tenant", "ambiguous"}:
        _tenant_routes(2, lambda: value)
    if access in {"own", "neither"}:
        respx.get(f"{profiles.GRAPH_BASE}/me/profile").respond(
            status_code=403 if access == "neither" else 200, json=value,
        )
    key, profile = "AUTH-PROFILE-001", "entra:test-profile"
    monkeypatch.setitem(registry.PROFILES, profile, registry.ProfileSpec(profile, (key,), "Public profile coverage"))
    target = ["--checkpoint", key] if selection == "checkpoint" else [
        "--profile", profile, "--validation-realm", "dev",
    ]
    output = tmp_path / "report"
    monkeypatch.setattr("sys.argv", [
        "flightcheck", *target, "--tenant-id", graph.MOCK_TENANT_ID,
        "--preferred-username", "maker@example.test", "--output", str(output), "--no-open", "--no-telemetry",
    ])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
    row = next(item for item in payload["results"] if item["checkpoint_id"] == key)
    html = (output / "report.html").read_text(encoding="utf-8")
    assert row["description"] == "Microsoft 365 profile attribute coverage (beta)"
    assert exited.value.code == (1 if access == "network" else 0)
    if access == "network":
        assert row["status"] == "Error" and payload["blocked"] >= 1
        assert "Restore the Graph read" in row["remediation"]
        return
    assert row["status"] == "Warning"
    assert "not a deployment blocker" in row["remediation"]
    assert "Mock title" not in json.dumps(row["evidence"])
    if access in {"tenant", "ambiguous"}:
        assert row["evidence"]["usersChecked"] == 2
        assert "profiles checked" in row["result"]
        assert "Organizational Data Service" in row["remediation"]
        if access == "ambiguous":
            assert "Unverified" in row["result"]
    elif access == "own":
        assert row["evidence"]["usersChecked"] == 1
        assert row["evidence"]["profileVerified"] is True
        assert row["evidence"]["coverageVerified"] is False
        assert "Own profile only" in html and "coveragePercent" not in json.dumps(row["evidence"])
        assert "tenant-wide attribute coverage was not calculated" in row["result"]
        assert scopes_used[-1] == ["https://graph.microsoft.com/User.Read"]
    else:
        assert "Not checked" in row["result"]
        assert "usersChecked" not in row["evidence"]
    assert "Warnings tab" in html and "Needs manual verification" not in html
    assert "--scope checkpoint:" not in html


@pytest.mark.parametrize("scope,permission", [("me", "User.Read"), ("tenant", "User.Read.All")])
@respx.mock
def test_standalone_uses_selected_scope_and_aggregate_json(monkeypatch, tmp_path, capsys, scope, permission):
    seen = []
    def authenticate(client, preferred_username=None, **_kwargs):
        seen.append(client._scopes)
        client.signed_in_username = preferred_username
        client._token = _token()
    monkeypatch.setattr(GraphClient, "authenticate", authenticate)
    if scope == "me":
        respx.get(f"{profiles.GRAPH_BASE}/me/profile").respond(json=profiles.profile())
    else:
        _tenant_routes()
    output = tmp_path / "profile.json"
    assert check.main([
        "--scope", scope, "--tenant-id", graph.MOCK_TENANT_ID,
        "--preferred-username", "maker@example.test", "--attributes", "jobTitle", "--output", str(output),
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(output.read_text(encoding="utf-8"))
    assert report["schemaVersion"] == "m365-profile-check.v2"
    assert seen == [[f"https://graph.microsoft.com/{permission}"]]
    assert "Mock title" not in json.dumps(report)


def test_standalone_tenant_denial_does_not_silently_change_scope(monkeypatch, capsys):
    monkeypatch.setattr(GraphClient, "authenticate", Mock(side_effect=GraphPermissionError("Denied")))
    assert check.main(["--scope", "tenant"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["scope"] == "tenant" and report["coverageVerified"] is False
    assert "Not checked" in report["message"] and "usersChecked" not in report


@pytest.mark.parametrize("identity", ["account", "tenant", "missing"])
def test_identity_guard_stops_before_any_profile_read(client, monkeypatch, capsys, identity):
    client.signed_in_username = "other@example.test" if identity == "account" else "maker@example.test"
    if identity in {"tenant", "missing"}:
        client._token = _token("" if identity == "missing" else str(__import__("uuid").UUID(int=999)))
    monkeypatch.setattr(client, "authenticate", Mock())
    monkeypatch.setattr(client, "get_bounded_profile", Mock())
    monkeypatch.setattr(check, "GraphClient", Mock(return_value=client))
    assert check.main(["--preferred-username", "maker@example.test"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "Error"
    client.get_bounded_profile.assert_not_called()


@respx.mock
def test_profile_timeout_replaces_stale_report_without_partial_numbers(client, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(client, "authenticate", Mock())
    monkeypatch.setattr(client, "get_bounded_profile", Mock(side_effect=TimeoutError("budget expired")))
    monkeypatch.setattr(check, "GraphClient", Mock(return_value=client))
    output = tmp_path / "report.json"
    output.write_text('{"status":"Passed","usersChecked":100}', encoding="utf-8")
    assert check.main(["--output", str(output)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "Error" and "budget expired" in report["error"]
    assert "results" not in report and "usersChecked" not in report
    assert json.loads(output.read_text(encoding="utf-8")) == report
