# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Graph contract tests use the CSDL-backed builders in tests.mocks.graph."""

import asyncio
import base64
import json
import socket
import threading
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import httpx
import requests
import responses
import respx

import check_entra_profile as check
from flightcheck.graph_client import CollectionRead, GraphClient, GraphPermissionError
from tests.conftest import require_validated_mock
from tests.mocks import graph


def _token(tenant=graph.MOCK_TENANT_ID):
    claims = base64.urlsafe_b64encode(json.dumps({"tid": tenant}).encode()).decode().rstrip("=")
    return f"header.{claims}.signature"


@pytest.fixture
def client():
    require_validated_mock(graph)
    value = GraphClient(graph.MOCK_TENANT_ID, strict_reads=True)
    value._token = _token()
    value.signed_in_username = "maker@example.test"
    return value


@responses.activate
def test_current_profile_reads_selected_properties_without_reporting_values(client):
    profile = graph.profile_user()
    responses.get(f"{graph.GRAPH_BASE}/me", json=profile)
    report = check.check_attributes(client, "me", list(check.ATTRIBUTES))
    assert report["status"] == "Passed"
    assert report["usersChecked"] == 1
    assert report["hrCountryComparison"]["status"] == "NotApplicable"
    assert parse_qs(urlsplit(responses.calls[0].request.url).query)["$select"] == [
        ",".join(["id", *check.ATTRIBUTES]),
    ]
    assert all(row["coveragePercent"] == 100 for row in report["results"])
    assert "Mock title" not in json.dumps(report)
    assert graph.MOCK_USER_ID not in json.dumps(report)


@responses.activate
def test_null_blank_and_omitted_properties_have_distinct_counts(client):
    profile = graph.profile_user()
    profile.update(usageLocation=None, jobTitle="  ")
    del profile["employeeType"]
    responses.get(f"{graph.GRAPH_BASE}/me", json=profile)
    report = check.check_attributes(client, "me", ["usageLocation", "jobTitle", "employeeType"])
    assert report["status"] == "Warning"
    rows = {row["attribute"]: row for row in report["results"]}
    assert rows["usageLocation"]["empty"] == rows["jobTitle"]["empty"] == 1
    assert rows["employeeType"]["notReturned"] == 1
    assert rows["employeeType"]["empty"] == 0


@respx.mock
def test_tenant_gap_below_threshold_is_warning(client):
    first, second = graph.profile_user(user_id="one"), graph.profile_user(user_id="two")
    second["usageLocation"] = None
    respx.get(f"{graph.GRAPH_BASE}/users").respond(json={"value": [first, second]})
    report = check.check_attributes(client, "tenant", ["usageLocation"])
    assert report["status"] == "Warning"
    assert report["results"][0]["coveragePercent"] == 50


@respx.mock
def test_tenant_coverage_reads_every_page_before_applying_threshold(client):
    first = [graph.profile_user(user_id=f"user-{i}") for i in range(19)]
    last = graph.profile_user(user_id="user-19")
    last["usageLocation"] = None
    respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=[
        httpx.Response(200, json={
            "value": first, "@odata.nextLink": f"{graph.GRAPH_BASE}/users?$skiptoken=next",
        }),
        httpx.Response(200, json={"value": [last]}),
    ])
    report = check.check_attributes(client, "tenant", ["usageLocation"])
    assert report["usersChecked"] == 20
    assert report["results"][0]["coveragePercent"] == 95
    assert report["status"] == "Passed"
    assert "including disabled and service accounts" in report["population"]
    assert len(respx.calls) == 2


@respx.mock
def test_denied_second_page_never_becomes_partial_coverage(client):
    respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=[
        httpx.Response(200, json={
            "value": [graph.profile_user()], "@odata.nextLink": f"{graph.GRAPH_BASE}/users?$skiptoken=next",
        }),
        httpx.Response(403),
    ])
    with pytest.raises(PermissionError):
        check.check_attributes(client, "tenant", ["usageLocation"])


@pytest.mark.parametrize("variant", ["empty", "duplicate", "bad_type", "guest", "missing_id"])
@respx.mock
def test_invalid_populations_do_not_produce_coverage(client, variant):
    user = graph.profile_user()
    users = [user]
    if variant == "empty":
        users = []
    elif variant == "duplicate":
        users.append(dict(user))
    elif variant == "bad_type":
        user["usageLocation"] = 42
    elif variant == "guest":
        user["userType"] = "Guest"
    else:
        del user["id"]
    respx.get(f"{graph.GRAPH_BASE}/users").respond(json={"value": users})
    with pytest.raises(ValueError):
        check.check_attributes(client, "tenant", ["usageLocation"])


@pytest.mark.parametrize("scope,expected", [("me", "User.Read"), ("tenant", "User.Read.All")])
def test_cli_requests_only_its_scope_and_writes_aggregate_json(monkeypatch, tmp_path, capsys, scope, expected):
    client = Mock(signed_in_username="maker@example.test")
    client.get.return_value = graph.profile_user()
    client.get_bounded_collection.return_value = CollectionRead([graph.profile_user()], True)
    constructor = Mock(return_value=client)
    monkeypatch.setattr(check, "GraphClient", constructor)
    output = tmp_path / "report.json"
    code = check.main(["--scope", scope, "--preferred-username", "maker@example.test", "--output", str(output)])
    assert code == 0
    assert client.authenticate.call_args.kwargs["scopes"] == [f"https://graph.microsoft.com/{expected}"]
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report == json.loads(capsys.readouterr().out)
    assert "maker@example.test" not in output.read_text(encoding="utf-8")


def test_cli_rejects_wrong_account_before_reading_profile(monkeypatch, capsys):
    client = Mock(signed_in_username="someone-else@example.test")
    monkeypatch.setattr(check, "GraphClient", Mock(return_value=client))
    assert check.main(["--preferred-username", "maker@example.test"]) == 2
    assert "different or unverifiable account" in json.loads(capsys.readouterr().out)["error"]
    client.get.assert_not_called()
    client.get_bounded_collection.assert_not_called()


def test_cli_denied_read_is_error_not_missing_attributes(monkeypatch, tmp_path, capsys):
    client = Mock()
    client.get.side_effect = PermissionError("denied")
    monkeypatch.setattr(check, "GraphClient", Mock(return_value=client))
    output = tmp_path / "report.json"
    output.write_text('{"status":"Passed"}', encoding="utf-8")
    assert check.main(["--output", str(output)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "Error"
    assert "results" not in report
    assert json.loads(output.read_text(encoding="utf-8")) == report


@pytest.mark.parametrize("size,is_sample", [
    (9999, False), (10_000, False), (10_001, True), (20_000, True),
])
@respx.mock
def test_tenant_cap_and_completeness_are_reported_accurately(client, size, is_sample):
    template = graph.profile_user()
    pages = []
    for offset in range(0, size, 999):
        body = {"value": [
            {**template, "id": f"user-{index}"}
            for index in range(offset, min(offset + 999, size))
        ]}
        if offset + 999 < size:
            body["@odata.nextLink"] = f"{graph.GRAPH_BASE}/users?$skiptoken={offset + 999}"
        pages.append(httpx.Response(200, json=body))
    route = respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=pages)
    report = check.check_attributes(client, "tenant", ["usageLocation"])
    assert report["usersChecked"] == min(size, 10_000)
    assert report["isSample"] is is_sample
    assert report["populationComplete"] is not is_sample
    assert report["coverageLabel"].startswith("Sample coverage" if is_sample else "Tenant coverage")
    assert report["results"][0]["available"] == min(size, 10_000)
    assert route.call_count == 11
    assert parse_qs(urlsplit(str(route.calls[0].request.url)).query)["$top"] == ["999"]
    assert not any("$skiptoken=10989" in str(call.request.url) for call in route.calls)


@respx.mock
def test_threshold_is_applied_before_percentage_rounding(client):
    template = graph.profile_user()
    users = [
        {**template, "id": str(index), "usageLocation": "US" if index < 9499 else None}
        for index in range(9999)
    ]
    pages = []
    for offset in range(0, len(users), 500):
        body = {"value": users[offset:offset + 500]}
        if offset + 500 < len(users):
            body["@odata.nextLink"] = f"{graph.GRAPH_BASE}/users?$skiptoken={offset + 500}"
        pages.append(httpx.Response(200, json=body))
    respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=pages)
    report = check.check_attributes(client, "tenant", ["usageLocation"])
    assert report["results"][0]["coveragePercent"] == 95.0
    assert report["status"] == "Warning"


@pytest.mark.parametrize("failure", ["slow_response", "retry_after", "network_retry"])
@respx.mock
def test_deadline_cancels_network_reads_and_retry_delays_without_partial_coverage(client, failure):
    attempted = []

    async def slow_response(request):
        attempted.append(str(request.url))
        if "$skiptoken" not in request.url.params:
            return httpx.Response(200, json={
                "value": [graph.profile_user()],
                "@odata.nextLink": f"{graph.GRAPH_BASE}/users?$skiptoken=next",
            })
        if failure == "retry_after":
            return httpx.Response(429, headers={"Retry-After": "60"})
        if failure == "network_retry":
            raise httpx.ConnectError("Temporary connection failure.")
        await asyncio.sleep(10)
        return httpx.Response(200, json={"value": [graph.profile_user(user_id="second")]})

    route = respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=slow_response)
    started = monotonic()
    with pytest.raises(TimeoutError, match="budget expired; no partial coverage"):
        client.get_bounded_collection("/users", params={}, limit=10_000, time_budget=0.5)
    assert monotonic() - started < 2
    assert len(attempted) == (3 if failure == "network_retry" else 2)
    assert route.call_count == {
        "slow_response": 1, "retry_after": 2, "network_retry": 3,
    }[failure]


@respx.mock
def test_bounded_reads_keep_retry_after_and_backoff_policy(client, monkeypatch):
    delays = []
    original_sleep = asyncio.sleep

    async def sleep(delay):
        delays.append(delay)
        await original_sleep(0)

    monkeypatch.setattr("flightcheck.graph_client.asyncio.sleep", sleep)
    route = respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503),
        httpx.Response(200, json={"value": [graph.profile_user()]}),
    ])
    report = check.check_attributes(client, "tenant", ["usageLocation"])
    assert report["status"] == "Passed"
    assert delays == [7, 2]
    assert route.call_count == 3


@pytest.mark.parametrize("error_type", [
    httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError,
])
@respx.mock
def test_transient_transport_failure_retries_without_duplicating_completed_pages(
    client, monkeypatch, error_type,
):
    delays = []
    original_sleep = asyncio.sleep

    async def sleep(delay):
        delays.append(delay)
        await original_sleep(0)

    monkeypatch.setattr("flightcheck.graph_client.asyncio.sleep", sleep)
    route = respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=[
        httpx.Response(200, json={
            "value": [graph.profile_user(user_id="one")],
            "@odata.nextLink": f"{graph.GRAPH_BASE}/users?$skiptoken=next",
        }),
        error_type("Temporary transport failure."),
        httpx.Response(200, json={"value": [graph.profile_user(user_id="two")]}),
    ])
    report = check.check_attributes(client, "tenant", ["usageLocation"])
    assert report["status"] == "Passed"
    assert report["usersChecked"] == 2
    assert delays == [0]
    assert route.call_count == 3


@respx.mock
def test_transport_and_http_failures_share_one_retry_limit(client, monkeypatch):
    delays = []
    original_sleep = asyncio.sleep

    async def sleep(delay):
        delays.append(delay)
        await original_sleep(0)

    monkeypatch.setattr("flightcheck.graph_client.asyncio.sleep", sleep)
    route = respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=[
        httpx.Response(200, json={
            "value": [graph.profile_user()],
            "@odata.nextLink": f"{graph.GRAPH_BASE}/users?$skiptoken=next",
        }),
        httpx.ConnectError("Temporary connection failure."),
        httpx.Response(503),
        httpx.ReadTimeout("Temporary read timeout."),
        httpx.ConnectError("Connection unavailable."),
    ])
    with pytest.raises(requests.ConnectionError, match="Graph request failed"):
        check.check_attributes(client, "tenant", ["usageLocation"])
    assert delays == [0, 2, 4]
    assert route.call_count == 5


@respx.mock
def test_last_page_crossing_the_limit_is_not_labelled_complete(client):
    respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=[
        httpx.Response(200, json={
            "value": [graph.profile_user(user_id="one"), graph.profile_user(user_id="two")],
            "@odata.nextLink": f"{graph.GRAPH_BASE}/users?$skiptoken=next",
        }),
        httpx.Response(200, json={
            "value": [graph.profile_user(user_id="three"), graph.profile_user(user_id="four")],
        }),
    ])
    collection = client.get_bounded_collection("/users", params={}, limit=3, time_budget=30)
    assert len(collection.items) == 3
    assert collection.complete is False


@respx.mock
def test_retry_exhaustion_on_a_later_page_does_not_report_partial_coverage(client, monkeypatch):
    original_sleep = asyncio.sleep

    async def sleep(_delay):
        await original_sleep(0)

    monkeypatch.setattr("flightcheck.graph_client.asyncio.sleep", sleep)
    route = respx.get(f"{graph.GRAPH_BASE}/users").mock(side_effect=[
        httpx.Response(200, json={
            "value": [graph.profile_user()],
            "@odata.nextLink": f"{graph.GRAPH_BASE}/users?$skiptoken=next",
        }),
        *[httpx.Response(503) for _ in range(4)],
    ])
    with pytest.raises(requests.HTTPError) as failed:
        check.check_attributes(client, "tenant", ["usageLocation"])
    assert failed.value.response.status_code == 503
    assert route.call_count == 5


def test_cli_budget_expiry_replaces_stale_coverage_with_error(client, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(client, "authenticate", Mock())
    monkeypatch.setattr(client, "get_bounded_collection", Mock(side_effect=TimeoutError(
        "The 30-second coverage budget expired; no partial coverage is reported.",
    )))
    monkeypatch.setattr(check, "GraphClient", Mock(return_value=client))
    output = tmp_path / "report.json"
    output.write_text('{"status":"Passed","usersChecked":100}', encoding="utf-8")
    assert check.main(["--scope", "tenant", "--output", str(output)]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "Error"
    assert "budget expired" in report["error"]
    assert "results" not in report
    assert "usersChecked" not in report
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_aggregation_must_also_finish_inside_the_budget(client, monkeypatch):
    clock = Mock(side_effect=[0, 29.9, 30.1])
    monkeypatch.setattr("flightcheck.entra_profile.monotonic", clock)
    monkeypatch.setattr(client, "get_bounded_collection", Mock(
        return_value=CollectionRead([graph.profile_user()], True),
    ))
    with pytest.raises(TimeoutError, match="budget expired; no partial coverage"):
        check.check_attributes(client, "tenant", ["usageLocation"])


@pytest.mark.parametrize("continuation", [
    "https://example.test/users", f"{graph.GRAPH_BASE}/groups", "",
    f"{graph.GRAPH_BASE}/users",
])
@respx.mock
def test_invalid_or_repeated_continuation_does_not_become_a_successful_sample(client, continuation):
    respx.get(f"{graph.GRAPH_BASE}/users").respond(json={
        "value": [graph.profile_user()], "@odata.nextLink": continuation,
    })
    with pytest.raises(ValueError, match="continuation"):
        check.check_attributes(client, "tenant", ["usageLocation"])


@pytest.mark.parametrize("status", [
    "Passed", "Warning", "Denied", "OwnEmpty", "OwnOmitted", "BothDenied", "Error",
])
@respx.mock
def test_registered_flightcheck_writes_html_json_and_nonblocking_warnings(
    client, monkeypatch, tmp_path, capsys, status,
):
    from flightcheck import cli

    monkeypatch.chdir(tmp_path)
    user = graph.profile_user()
    if status == "Warning":
        user["usageLocation"] = None
    fallback = status in {"Denied", "OwnEmpty", "OwnOmitted", "BothDenied"}
    respx.get(f"{graph.GRAPH_BASE}/users").respond(
        status_code=403 if fallback else 400 if status == "Error" else 200,
        json={"value": [user]},
    )
    own = graph.profile_user()
    if status == "OwnEmpty":
        own["jobTitle"] = None
    elif status == "OwnOmitted":
        del own["employeeType"]
    own_route = respx.get(f"{graph.GRAPH_BASE}/me").respond(
        status_code=403 if status == "BothDenied" else 200, json=own,
    ) if fallback else None
    scopes_used = []

    def authenticate(self, preferred_username=None, *, scopes=None, require_existing_consent=False):
        assert scopes == [f"https://graph.microsoft.com/{'User.Read.All' if require_existing_consent else 'User.Read'}"]
        scopes_used.extend(scopes)
        self._token = _token()
        self.signed_in_username = preferred_username
        return self._token

    monkeypatch.setattr(GraphClient, "authenticate", authenticate)
    output = tmp_path / "flightcheck-report"
    monkeypatch.setattr("sys.argv", [
        "flightcheck", "--checkpoint", "AUTH-PROFILE-001",
        "--tenant-id", graph.MOCK_TENANT_ID,
        "--preferred-username", "maker@example.test",
        "--output", str(output), "--no-open", "--no-telemetry",
    ])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
    row = next(item for item in payload["results"] if item["checkpoint_id"] == "AUTH-PROFILE-001")
    assert row["status"] == ("Warning" if fallback else status)
    assert exited.value.code == (1 if status == "Error" else 0)
    html = (output / "report.html").read_text(encoding="utf-8")
    assert "AUTH-PROFILE-001" in html
    assert "/flightcheck --checkpoint AUTH-PROFILE-001" in html
    assert "--scope checkpoint:" not in html
    if status == "Warning" or fallback:
        assert "Warnings tab" in html
        assert "Needs manual verification" not in html
    if status in {"Passed", "Warning"}:
        assert "Tenant coverage (1 accounts checked)" in row["result"]
        assert row["evidence"]["usersChecked"] == 1
        assert "Tenant coverage" in html
        assert "Mock title" not in json.dumps(row["evidence"])
    if status == "Warning":
        assert "Data-quality concern" in row["result"]
        assert "not a deployment blocker" in row["remediation"]
        assert "Personalization opportunity" in row["remediation"]
        assert "If ESS uses Entra for an attribute" in row["remediation"]
        assert "more personalized knowledge answers" in row["remediation"]
        assert "tenant administrator" in row["remediation"]
        assert "HR-to-Entra sync" in row["remediation"]
        stdout = capsys.readouterr().out
        assert "NON-BLOCKING WARNINGS (1)" in stdout
        assert "NEEDS MANUAL VERIFICATION" not in stdout
    elif status == "Passed":
        assert row["remediation"] == ""
    elif status == "BothDenied":
        assert "Not checked" in row["result"]
        assert row["evidence"]["coverageVerified"] is False
        assert "results" not in row["evidence"]
        assert "usersChecked" not in row["evidence"]
        assert "Access limitation, not a deployment blocker" in row["remediation"]
        assert row["evidence"]["profileVerified"] is False
    elif fallback:
        assert "Own profile only" in row["result"]
        assert "tenant-wide attribute coverage was not calculated" in row["result"]
        assert "Personalization opportunity, not a deployment blocker" in row["remediation"]
        assert "your own profile" in row["remediation"]
        assert "existing approved User.Read.All" in row["remediation"]
        evidence = row["evidence"]
        assert evidence["scope"] == "me" and evidence["usersChecked"] == 1
        assert evidence["profileVerified"] is True and evidence["coverageVerified"] is False
        assert len(evidence["results"]) == len(check.ATTRIBUTES)
        assert not {"isSample", "populationComplete", "thresholdPercent"}.intersection(evidence)
        assert "coveragePercent" not in json.dumps(evidence)
        assert "Mock title" not in json.dumps(evidence)
        assert graph.MOCK_USER_ID not in json.dumps(evidence)
        states = {item["attribute"]: item["availability"] for item in evidence["results"]}
        assert states["jobTitle"] == ("Empty" if status == "OwnEmpty" else "Available")
        assert states["employeeType"] == ("Not returned" if status == "OwnOmitted" else "Available")
        assert "Own profile only" in html
        assert "%" not in row["result"]
    else:
        assert "400" in row["result"]
        assert "admin-consented User.Read.All" in row["remediation"]
        assert "results" not in row["evidence"]
    assert scopes_used == [
        "https://graph.microsoft.com/User.Read.All",
        *(["https://graph.microsoft.com/User.Read"] if fallback else []),
    ]
    assert (own_route.call_count if own_route else 0) == int(fallback)


def test_shared_da_planning_discovers_coverage_but_not_in_local_mode():
    from flightcheck import registry
    from flightcheck.da_execution import plan_da_checks

    assert "AUTH-PROFILE-001" in plan_da_checks(scope="full")[0]
    assert "AUTH-PROFILE-001" not in plan_da_checks(local=True)[0]
    plan = registry.transitive_requirements("AUTH-PROFILE-001")
    assert plan.clients == frozenset({registry.GRAPH})
    assert plan.graph_scopes == ("https://graph.microsoft.com/User.Read.All",)
    assert plan.graph_permission_optional is True
    assert not plan.requires_config
    assert not plan.requires_dataverse_endpoint


def test_da_permission_error_is_not_checked_warning_without_manual_verification(client, monkeypatch):
    from flightcheck import registry
    from flightcheck.da_execution import DAExecutor

    monkeypatch.setattr(client, "get_bounded_collection", Mock(side_effect=GraphPermissionError("HTTP 403")))
    spec = registry.resolve("AUTH-PROFILE-001")
    runner = SimpleNamespace(graph=client, agent_slug="hr", env_id="test-environment")
    runner.self_profile_graph = Mock(side_effect=GraphPermissionError("User.Read denied"))
    executor = DAExecutor(runner, SimpleNamespace(), (spec.key,), (spec,), {})
    runner.da_executor = executor
    row = executor.run(runner)[0]
    assert row.status == "Warning"
    assert "Not checked" in row.result
    assert row.evidence["coverageVerified"] is False
    assert "not a deployment blocker" in row.remediation
    assert "manualVerificationSteps" not in row.evidence


@pytest.mark.parametrize("stage", ["consent", "read"])
def test_standalone_unavailable_tenant_permission_is_warning_without_coverage(
    client, monkeypatch, tmp_path, capsys, stage,
):
    monkeypatch.setattr(client, "authenticate", Mock(
        side_effect=GraphPermissionError("consent_required") if stage == "consent" else None,
    ))
    read = Mock(side_effect=GraphPermissionError("HTTP 403"))
    monkeypatch.setattr(client, "get_bounded_collection", read)
    monkeypatch.setattr(check, "GraphClient", Mock(return_value=client))
    output = tmp_path / "report.json"
    assert check.main(["--scope", "tenant", "--output", str(output)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "Warning"
    assert report["coverageVerified"] is False
    assert "Not checked" in report["message"]
    assert "results" not in report and "usersChecked" not in report
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert read.call_count == (0 if stage == "consent" else 1)


@pytest.mark.parametrize("selection", ["checkpoint", "profile"])
@pytest.mark.parametrize("failure", ["consent", "filesystem", "network"])
def test_focused_permission_fallback_does_not_hide_other_authentication_failures(
    monkeypatch, tmp_path, capsys, selection, failure,
):
    from flightcheck import cli, registry

    monkeypatch.chdir(tmp_path)
    key = "AUTH-PROFILE-001"
    profile = "entra:test-permissions"
    monkeypatch.setitem(registry.PROFILES, profile, registry.ProfileSpec(
        profile, (key,), "Optional directory profile coverage.",
    ))
    failures = {
        "consent": GraphPermissionError("consent_required"),
        "filesystem": PermissionError("Token cache access denied."),
        "network": requests.ConnectionError("Network unavailable."),
    }

    def authenticate(self, preferred_username=None, *, scopes=None, require_existing_consent=False):
        assert require_existing_consent is (scopes == ["https://graph.microsoft.com/User.Read.All"])
        raise failures[failure]

    monkeypatch.setattr(GraphClient, "authenticate", authenticate)
    output = tmp_path / "report"
    target = ["--checkpoint", key] if selection == "checkpoint" else [
        "--profile", profile, "--validation-realm", "dev",
    ]
    monkeypatch.setattr("sys.argv", [
        "flightcheck", *target, "--tenant-id", graph.MOCK_TENANT_ID,
        "--preferred-username", "maker@example.test",
        "--output", str(output), "--no-open", "--no-telemetry",
    ])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
    row = next(item for item in payload["results"] if item["checkpoint_id"] == key)
    if failure == "consent":
        assert exited.value.code == 0
        assert payload["blocked"] == payload["errors"] == payload["manual"] == 0
        assert row["status"] == "Warning"
        assert "Not checked" in row["result"]
        assert row["evidence"]["coverageVerified"] is False
        assert "not a deployment blocker" in row["remediation"]
        assert "results" not in row["evidence"]
        assert "Not checked" in (output / "report.html").read_text(encoding="utf-8")
    else:
        assert exited.value.code == 1
        assert payload["blocked"] >= 1
        assert row["status"] == "Error"


def test_optional_coverage_does_not_weaken_required_graph_plans(monkeypatch):
    from flightcheck import cli, registry
    from flightcheck.runner import CheckResult

    required = registry.CheckpointSpec(
        key="TEST-GRAPH-REQUIRED", category_label="Test", clients=frozenset({registry.GRAPH}),
        requires_config=False,
        category_fn=lambda _: [CheckResult(
            "TEST-GRAPH-REQUIRED", "Test", "High", "Passed", "Required Graph read", "Complete.",
        )],
    )
    monkeypatch.setitem(registry.REGISTRY, required.key, required)
    monkeypatch.setitem(registry.PROFILES, "entra:test-mixed", registry.ProfileSpec(
        "entra:test-mixed", ("AUTH-PROFILE-001", required.key), "Mixed Graph permission requirements.",
    ))
    plan = registry.profile_requirements("entra:test-mixed")
    assert plan.graph_permission_optional is False
    assert plan.graph_scopes is None
    availability = {"graph": {"required": True, "available": False}}
    cli._record_graph_permission_failure(
        availability, plan.graph_permission_optional, GraphPermissionError("consent_required"),
    )
    blockers = cli._client_blockers(availability, "PROFILE")
    assert len(blockers) == 1
    assert blockers[0].status == "Blocked"


@pytest.mark.parametrize("tenant_elapsed,own_elapsed", [(23, 1), (23, 8), (31, 1)])
def test_fallback_shares_read_budget_but_excludes_self_authentication(
    monkeypatch, tenant_elapsed, own_elapsed,
):
    from flightcheck.checks.entra_profile import run_entra_profile_checks

    now = [0]
    monkeypatch.setattr("flightcheck.entra_profile.monotonic", lambda: now[0])
    monkeypatch.setattr("flightcheck.checks.entra_profile.monotonic", lambda: now[0])
    tenant_client, own_client = Mock(), Mock()
    read_budgets = []

    def denied(*_args, **_kwargs):
        now[0] += tenant_elapsed
        raise GraphPermissionError("Directory read denied")

    def authenticate():
        now[0] += 120
        return own_client

    def read(**kwargs):
        read_budgets.append(kwargs["time_budget"])
        now[0] += own_elapsed
        return graph.profile_user()

    tenant_client.get_bounded_collection.side_effect = denied
    own_client.get_bounded_profile.side_effect = read
    runner = SimpleNamespace(graph=tenant_client, self_profile_graph=Mock(side_effect=authenticate))
    row = run_entra_profile_checks(runner)[0]
    assert runner.graph is tenant_client
    assert read_budgets == ([30 - tenant_elapsed] if tenant_elapsed < 30 else [])
    if tenant_elapsed + own_elapsed < 30:
        assert row.status == "Warning"
        assert row.evidence["profileVerified"] is True
        assert "Own profile only" in row.result
        assert "not a deployment blocker" in row.remediation
    else:
        assert row.status == "Error"
        assert "budget expired" in row.result
        assert "results" not in row.evidence
        assert "Restore the Graph read" in row.remediation
    if tenant_elapsed >= 30:
        runner.self_profile_graph.assert_not_called()


@pytest.mark.parametrize("failure", [
    TimeoutError("budget expired"), requests.ConnectionError("Network unavailable"),
    ValueError("Invalid directory data"),
])
def test_fallback_does_not_hide_nonpermission_read_failures(failure):
    from flightcheck.checks.entra_profile import run_entra_profile_checks

    client = Mock()
    client.get_bounded_collection.side_effect = failure
    runner = SimpleNamespace(graph=client, self_profile_graph=Mock())
    row = run_entra_profile_checks(runner)[0]
    assert row.status == "Error"
    assert (type(failure).__name__ if isinstance(failure, requests.RequestException) else str(failure)) in row.result
    assert "Restore the Graph read" in row.remediation
    runner.self_profile_graph.assert_not_called()


@pytest.mark.parametrize("identity", ["matching", "other_account", "missing_account", "other_tenant", "missing_tenant"])
def test_self_profile_authentication_verifies_account_and_tenant(monkeypatch, identity):
    from flightcheck.runner import FlightCheckRunner

    def authenticate(client, preferred_username=None, *, scopes=None):
        assert preferred_username == "maker@example.test"
        assert scopes == ["https://graph.microsoft.com/User.Read"]
        client.signed_in_username = {
            "other_account": "other@example.test", "missing_account": None,
        }.get(identity, preferred_username)
        client._token = _token(
            "00000000-0000-4000-8000-000000009999" if identity == "other_tenant"
            else "" if identity == "missing_tenant" else graph.MOCK_TENANT_ID,
        )
        return client._token

    monkeypatch.setattr(GraphClient, "authenticate", authenticate)
    runner = FlightCheckRunner()
    runner.tenant_id = graph.MOCK_TENANT_ID
    runner.authenticated_account = "maker@example.test"
    runner.graph = Mock()
    original = runner.graph
    if identity == "matching":
        assert runner.self_profile_graph().signed_in_username == "maker@example.test"
    else:
        with pytest.raises(ValueError, match="different|unreadable tenant identity"):
            runner.self_profile_graph()
    assert runner.graph is original


@respx.mock
def test_self_profile_retry_after_is_cancelled_by_its_remaining_deadline(client):
    route = respx.get(f"{graph.GRAPH_BASE}/me").respond(429, headers={"Retry-After": "60"})
    started = monotonic()
    with pytest.raises(TimeoutError, match="budget expired; no partial coverage"):
        client.get_bounded_profile(params={}, time_budget=0.5)
    assert monotonic() - started < 2
    assert route.call_count == 1


@pytest.mark.parametrize("scope", ["tenant", "me"])
def test_slow_dns_does_not_delay_bounded_read_shutdown(client, monkeypatch, scope):
    """Cancellation must include DNS and event-loop shutdown, not just HTTP I/O."""
    from flightcheck import graph_client

    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(key, raising=False)
    dns_started = threading.Event()
    processes = []
    create_process = asyncio.create_subprocess_exec

    async def record_process(*args, **kwargs):
        process = await create_process(*args, **kwargs)
        processes.append(process)
        dns_started.set()
        return process

    def slow_dns(*_args, **_kwargs):
        dns_started.set()
        threading.Event().wait(3)
        raise socket.gaierror(socket.EAI_AGAIN, "Simulated slow DNS")

    monkeypatch.setattr(
        graph_client, "_DNS_LOOKUP", "import time; time.sleep(10)\n" + graph_client._DNS_LOOKUP,
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", record_process)
    monkeypatch.setattr(socket, "getaddrinfo", slow_dns)
    started = monotonic()
    with pytest.raises(TimeoutError, match="budget expired; no partial coverage"):
        if scope == "tenant":
            client.get_bounded_collection("/users", params={}, limit=10_000, time_budget=0.5)
        else:
            client.get_bounded_profile(params={}, time_budget=0.5)
    elapsed = monotonic() - started
    assert dns_started.is_set()
    assert elapsed < 2, f"The 0.5-second budget took {elapsed:.2f}s including shutdown."
    assert processes and all(process.returncode is not None for process in processes)


@pytest.mark.parametrize("host,family", [
    ("127.0.0.1", socket.AF_INET), ("::1", socket.AF_INET6),
])
def test_bounded_dns_preserves_address_families_and_reaps_worker(host, family, monkeypatch):
    from flightcheck import graph_client

    def forbidden(*_args, **_kwargs):
        pytest.fail("Bounded reads must not use the parent process's DNS thread pool.")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    with asyncio.Runner(loop_factory=graph_client._bounded_event_loop) as runner:
        addresses = runner.run(asyncio.wait_for(
            graph_client._bounded_getaddrinfo(
                host.encode("ascii"), 443, family=family,
                type=socket.SOCK_STREAM, flags=socket.AI_NUMERICHOST,
            ),
            timeout=5,
        ))
    assert addresses
    assert all(row[0] == family and row[1] == socket.SOCK_STREAM for row in addresses)
    assert all(row[4][0] == host and row[4][1] == 443 for row in addresses)


def test_bounded_dns_failure_preserves_transport_error_semantics(monkeypatch):
    from flightcheck import graph_client

    monkeypatch.setattr(graph_client, "_DNS_LOOKUP", (
        f"import json; json.dump({{'error': {socket.EAI_AGAIN}}}, __import__('sys').stdout)"
    ))
    with asyncio.Runner(loop_factory=graph_client._bounded_event_loop) as runner:
        with pytest.raises(socket.gaierror) as failed:
            runner.run(graph_client._bounded_getaddrinfo("example.test", 443))
    assert failed.value.errno == socket.EAI_AGAIN


def test_failed_dns_worker_is_an_explicit_error(monkeypatch):
    from flightcheck import graph_client

    monkeypatch.setattr(graph_client, "_DNS_LOOKUP", "raise SystemExit(1)")
    with asyncio.Runner(loop_factory=graph_client._bounded_event_loop) as runner:
        with pytest.raises(RuntimeError, match="DNS resolver process failed"):
            runner.run(graph_client._bounded_getaddrinfo("example.test", 443))


@pytest.mark.parametrize("entrypoint", ["checkpoint", "profile", "standalone-me", "standalone-tenant"])
def test_coverage_rejects_another_tenant_before_reading_profiles(monkeypatch, tmp_path, capsys, entrypoint):
    from flightcheck import cli, registry

    monkeypatch.chdir(tmp_path)
    tenant_read = Mock(return_value=CollectionRead([graph.profile_user()], True))
    own_read = Mock(return_value=graph.profile_user())

    def authenticate(client, preferred_username=None, **_kwargs):
        client.signed_in_username = preferred_username
        client._token = _token("00000000-0000-4000-8000-000000009999")
        return client._token

    monkeypatch.setattr(GraphClient, "authenticate", authenticate)
    monkeypatch.setattr(GraphClient, "get_bounded_collection", tenant_read)
    monkeypatch.setattr(GraphClient, "get", own_read)
    common = ["--tenant-id", graph.MOCK_TENANT_ID, "--preferred-username", "maker@example.test"]
    if entrypoint.startswith("standalone-"):
        assert check.main(["--scope", entrypoint.partition("-")[2], *common]) == 2
        assert "different tenant" in json.loads(capsys.readouterr().out)["error"]
    else:
        key = "AUTH-PROFILE-001"
        profile = "entra:test-identity"
        monkeypatch.setitem(registry.PROFILES, profile, registry.ProfileSpec(
            profile, (key,), "Coverage identity verification.",
        ))
        target = ["--checkpoint", key] if entrypoint == "checkpoint" else [
            "--profile", profile, "--validation-realm", "dev",
        ]
        output = tmp_path / "report"
        monkeypatch.setattr("sys.argv", [
            "flightcheck", *target, *common, "--output", str(output), "--no-open", "--no-telemetry",
        ])
        with pytest.raises(SystemExit) as exited:
            cli.main()
        assert exited.value.code == 1
        payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
        row = next(item for item in payload["results"] if item["checkpoint_id"] == key)
        assert row["status"] == "Error"
        assert "different tenant" in row["result"]
        assert "Restore the Graph read" in row["remediation"]
        assert "results" not in row["evidence"]
    tenant_read.assert_not_called()
    own_read.assert_not_called()


@respx.mock
def test_own_profile_fallback_preserves_required_graph_client_blockers(monkeypatch, tmp_path):
    from flightcheck import cli, registry
    from flightcheck.graph_client import GraphConsentError
    from flightcheck.runner import CheckResult

    monkeypatch.chdir(tmp_path)
    required = registry.CheckpointSpec(
        key="TEST-GRAPH-REQUIRED", category_label="Test", clients=frozenset({registry.GRAPH}),
        requires_config=False,
        category_fn=lambda _: [CheckResult(
            "TEST-GRAPH-REQUIRED", "Test", "High", "Passed", "Required Graph read", "Complete.",
        )],
    )
    monkeypatch.setitem(registry.REGISTRY, required.key, required)
    monkeypatch.setitem(registry.PROFILES, "entra:test-mixed", registry.ProfileSpec(
        "entra:test-mixed", ("AUTH-PROFILE-001", required.key), "Mixed Graph access requirements.",
    ))

    def authenticate(client, preferred_username=None, *, scopes=None, require_existing_consent=False):
        if scopes != ["https://graph.microsoft.com/User.Read"]:
            raise GraphConsentError("Directory consent unavailable")
        client.signed_in_username = preferred_username
        client._token = _token()
        return client._token

    monkeypatch.setattr(GraphClient, "authenticate", authenticate)
    respx.get(f"{graph.GRAPH_BASE}/me").respond(json=graph.profile_user())
    output = tmp_path / "report"
    monkeypatch.setattr("sys.argv", [
        "flightcheck", "--profile", "entra:test-mixed", "--validation-realm", "dev",
        "--tenant-id", graph.MOCK_TENANT_ID, "--preferred-username", "maker@example.test",
        "--output", str(output), "--no-open", "--no-telemetry",
    ])
    with pytest.raises(SystemExit) as exited:
        cli.main()
    payload = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert exited.value.code == 1 and payload["blocked"] >= 1
    row = next(item for item in payload["results"] if item["checkpoint_id"] == "AUTH-PROFILE-001")
    assert row["status"] == "Warning" and row["evidence"]["profileVerified"] is True
    assert "Own profile only" in row["result"]
    assert "not a deployment blocker" in row["remediation"]
