# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import sys

import pytest
import requests

import enable_workday_hybrid_flow_authorization as hybrid
from http_errors import APIError


BOT_ID = "923db1bf-2512-4378-a43b-71b944ea717c"
DA_ID = "11111111-1111-1111-1111-111111111111"
TEAM_ID = "22222222-2222-2222-2222-222222222222"
USER_ID = "33333333-3333-3333-3333-333333333333"
BU_ID = "44444444-4444-4444-4444-444444444444"
WORKFLOW_ID = "3164dae9-3a2b-5843-98dd-e62bb5123324"
ENV_URL = "https://example.crm.dynamics.com"
TOKEN = "token"


def test_normalize_guid_canonicalizes_and_rejects_invalid_values():
    assert hybrid.normalize_guid(BOT_ID.upper(), "Bot ID") == BOT_ID
    with pytest.raises(ValueError, match="Bot ID must be a valid GUID"):
        hybrid.normalize_guid("not-a-guid", "Bot ID")


def test_enable_authorization_reuses_existing_valid_records(monkeypatch):
    reports = []
    actions = []

    def fake_query_all(_env, _token, entity_set, _select, filter_expr=None):
        if entity_set == "delegatedauthorizations":
            assert filter_expr == f"botid eq '{BOT_ID}'"
            return [{
                "delegatedauthorizationid": DA_ID,
                "providertype": hybrid.PROVIDER_TYPE_MCSBOT,
            }]
        assert entity_set == "workflows"
        return [{"workflowid": WORKFLOW_ID, "name": "Workday flow"}]

    def fake_get(_env, _token, path, params=None):
        if path == "teams":
            return {
                "value": [{
                    "teamid": TEAM_ID,
                    "name": "Hybrid team",
                    "teamtype": hybrid.TEAM_TYPE_ACCESS,
                }]
            }
        assert path.startswith("RetrieveSharedPrincipalsAndAccess")
        return {
            "PrincipalAccesses": [{
                "AccessMask": "ReadAccess,WriteAccess",
                "Principal": {
                    "@odata.type": "Microsoft.Dynamics.CRM.team",
                    "ownerid": TEAM_ID,
                },
            }]
        }

    monkeypatch.setattr(hybrid, "query_all", fake_query_all)
    monkeypatch.setattr(hybrid, "dataverse_get", fake_get)
    monkeypatch.setattr(
        hybrid,
        "create_record",
        lambda *_args, **_kwargs: pytest.fail("must not create records"),
    )
    monkeypatch.setattr(
        hybrid,
        "execute_action",
        lambda *args: actions.append(args),
    )

    hybrid.enable_authorization(
        ENV_URL,
        TOKEN,
        BOT_ID,
        [WORKFLOW_ID],
        lambda status, message: reports.append((status, message)),
    )

    assert actions == []
    assert [status for status, _message in reports] == [
        "REUSED",
        "REUSED",
        "REUSED",
    ]


def test_enable_authorization_creates_records_and_grants_access(monkeypatch):
    reports = []
    created = []
    actions = []
    share_reads = iter([
        {"PrincipalAccesses": []},
        {
            "PrincipalAccesses": [{
                "AccessMask": hybrid.ACCESS_MASK,
                "Principal": {
                    "@odata.type": "Microsoft.Dynamics.CRM.team",
                    "ownerid": TEAM_ID,
                },
            }]
        },
    ])

    def fake_query_all(_env, _token, entity_set, _select, filter_expr=None):
        if entity_set == "delegatedauthorizations":
            return []
        assert entity_set == "workflows"
        return [{"workflowid": WORKFLOW_ID, "name": "Workday flow"}]

    def fake_get(_env, _token, path, params=None):
        if path == "teams":
            return {"value": []}
        if path == "WhoAmI()":
            return {"UserId": USER_ID}
        if path == f"systemusers({USER_ID})":
            return {"_businessunitid_value": BU_ID}
        return next(share_reads)

    def fake_create(_env, _token, entity_set, data):
        created.append((entity_set, data))
        return DA_ID if entity_set == "delegatedauthorizations" else TEAM_ID

    monkeypatch.setattr(hybrid, "query_all", fake_query_all)
    monkeypatch.setattr(hybrid, "dataverse_get", fake_get)
    monkeypatch.setattr(hybrid, "create_record", fake_create)
    monkeypatch.setattr(
        hybrid,
        "execute_action",
        lambda _env, _token, action, payload: actions.append((action, payload)),
    )

    hybrid.enable_authorization(
        ENV_URL,
        TOKEN,
        BOT_ID,
        [WORKFLOW_ID],
        lambda status, message: reports.append((status, message)),
    )

    assert [entity_set for entity_set, _data in created] == [
        "delegatedauthorizations",
        "teams",
    ]
    assert created[1][1]["administratorid@odata.bind"] == f"/systemusers({USER_ID})"
    assert created[1][1]["businessunitid@odata.bind"] == f"/businessunits({BU_ID})"
    assert actions[0][0] == "GrantAccess"
    assert actions[0][1]["PrincipalAccess"]["Principal"]["teamid"] == TEAM_ID
    assert [status for status, _message in reports] == [
        "CREATED",
        "CREATED",
        "UPDATED",
    ]


def test_existing_share_without_write_uses_modify_access(monkeypatch):
    reads = iter([
        {
            "PrincipalAccesses": [{
                "AccessMask": "ReadAccess",
                "Principal": {
                    "@odata.type": "Microsoft.Dynamics.CRM.team",
                    "ownerid": TEAM_ID,
                },
            }]
        },
        {
            "PrincipalAccesses": [{
                "AccessMask": hybrid.ACCESS_MASK,
                "Principal": {
                    "@odata.type": "Microsoft.Dynamics.CRM.team",
                    "ownerid": TEAM_ID,
                },
            }]
        },
    ])
    actions = []

    monkeypatch.setattr(
        hybrid,
        "query_all",
        lambda *_args, **_kwargs: [{
            "workflowid": WORKFLOW_ID,
            "name": "Workday flow",
        }],
    )
    monkeypatch.setattr(
        hybrid,
        "retrieve_workflow_access",
        lambda *_args: next(reads)["PrincipalAccesses"],
    )
    monkeypatch.setattr(
        hybrid,
        "execute_action",
        lambda _env, _token, action, payload: actions.append((action, payload)),
    )

    hybrid.ensure_workflow_access(
        ENV_URL,
        TOKEN,
        WORKFLOW_ID,
        TEAM_ID,
        lambda *_args: None,
    )

    assert actions[0][0] == "ModifyAccess"


def test_duplicate_access_teams_fail_closed(monkeypatch):
    monkeypatch.setattr(
        hybrid,
        "find_access_teams",
        lambda *_args: [
            {"teamid": TEAM_ID, "teamtype": hybrid.TEAM_TYPE_ACCESS},
            {
                "teamid": "55555555-5555-5555-5555-555555555555",
                "teamtype": hybrid.TEAM_TYPE_ACCESS,
            },
        ],
    )

    with pytest.raises(RuntimeError, match="expects exactly one"):
        hybrid.ensure_access_team(
            ENV_URL,
            TOKEN,
            BOT_ID,
            DA_ID,
            lambda *_args: None,
        )


def test_validate_only_uses_config_without_authenticating(monkeypatch, capsys):
    monkeypatch.setattr(
        hybrid,
        "load_config",
        lambda: {"dataverseEndpoint": ENV_URL},
    )
    monkeypatch.setattr(
        hybrid,
        "authenticate",
        lambda *_args: pytest.fail("validation must not authenticate"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "enable_workday_hybrid_flow_authorization.py",
            "--bot-id",
            BOT_ID,
            "--workflow-id",
            WORKFLOW_ID,
            "--validate-only",
        ],
    )

    hybrid.main()

    output = capsys.readouterr().out
    assert "Validated bot ID and 1 unique workflow ID(s)" in output


def test_confirmation_treats_closed_stdin_as_cancel(monkeypatch):
    monkeypatch.setattr(
        "builtins.input",
        lambda _prompt: (_ for _ in ()).throw(EOFError()),
    )

    assert not hybrid._confirm(ENV_URL, BOT_ID, [WORKFLOW_ID])


def _error_response(status_code, body, request_id="request-123"):
    response = requests.Response()
    response.status_code = status_code
    response.headers["x-ms-request-id"] = request_id
    response._content = body.encode("utf-8")
    response.request = requests.Request(
        "POST",
        f"{ENV_URL}/api/data/v9.2/GrantAccess?access_token=query-secret",
    ).prepare()
    return response


def test_format_request_error_includes_safe_dataverse_detail():
    response = _error_response(
        400,
        (
            '{"error":{"code":"0x80040216","message":'
            '"Invalid principal. Bearer secret-token access_token=body-secret"}}'
        ),
    )
    error = APIError(
        response=response,
        resource_name="GrantAccess",
        operation="execute",
    )

    output = hybrid.format_request_error(error)

    assert "HTTP 400" in output
    assert "POST https://example.crm.dynamics.com/api/data/v9.2/GrantAccess" in output
    assert "Request ID: request-123" in output
    assert "Dataverse detail: 0x80040216: Invalid principal." in output
    assert "secret-token" not in output
    assert "body-secret" not in output
    assert "query-secret" not in output


def test_format_request_error_handles_plain_http_error_and_non_json_body():
    response = _error_response(500, "<html>Server error</html>")
    error = requests.HTTPError(response=response)

    output = hybrid.format_request_error(error)

    assert output == (
        "ERROR: Dataverse request failed: HTTP 500 "
        "POST https://example.crm.dynamics.com/api/data/v9.2/GrantAccess\n"
        "Request ID: request-123"
    )


def test_sanitize_error_detail_redacts_bearer_credentials():
    secret = "sensitive" + "-bearer-value"

    output = hybrid._sanitize_error_detail("Bearer " + secret)

    assert secret not in output


def test_format_request_error_truncates_long_dataverse_messages():
    response = _error_response(
        400,
        '{"error":{"code":"LongMessage","message":"' + ("x" * 700) + '"}}',
    )
    error = requests.HTTPError(response=response)

    output = hybrid.format_request_error(error)
    detail = output.split("Dataverse detail: ", 1)[1]

    assert detail.startswith("LongMessage: ")
    assert detail.endswith("...")
    assert len(detail) <= len("LongMessage: ") + hybrid.MAX_ERROR_DETAIL_LENGTH
