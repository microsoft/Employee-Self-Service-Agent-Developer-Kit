# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

import pytest
import requests

import setup_power_platform_environment as setup_environment


TENANT_ID = "00000000-0000-4000-8000-000000009999"
ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
REQUEST_ID = "00000000-0000-4000-8000-000000003333"
PRINCIPAL_ID = "00000000-0000-4000-8000-000000004444"
ADMIN_ID = "00000000-0000-4000-8000-000000005555"


def test_parser_exposes_bounded_environment_operations() -> None:
    parser = setup_environment.build_parser()
    subparsers = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )

    assert set(subparsers.choices) == {
        "create",
        "forget-account",
        "list-locations",
        "inspect-account",
        "list-roles",
        "grant-maker",
    }
    with pytest.raises(SystemExit):
        parser.parse_args(["create"])
    with pytest.raises(SystemExit):
        parser.parse_args(["grant-maker", "--select-account"])


def test_list_locations_projects_choices_and_preserves_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_environment,
        "authenticate_selected_tenant",
        lambda *args, **kwargs: ("token", TENANT_ID),
    )
    raw_response = {
        "locationSelectionMode": "Region",
        "collection": [
            {
                "name": "europe",
                "code": "EMEA",
                "displayName": "Europe",
                "isDefault": False,
                "isDisabled": True,
            },
            {
                "name": "unitedstates",
                "code": "NA",
                "displayName": "United States",
                "isDefault": True,
                "isDisabled": False,
                "futureServiceField": "preserved",
            },
            {
                "name": "unitedstatesfirstrelease",
                "code": "NA",
                "displayName": "Preview (United States)",
                "isDefault": False,
                "isDisabled": False,
            },
        ],
        "macroRegions": [],
        "futureEnvelopeField": {"preserved": True},
    }
    monkeypatch.setattr(
        setup_environment,
        "list_provisioning_locations",
        lambda token, ring, *, api_version: raw_response,
    )

    assert setup_environment.main(
        [
            "list-locations",
            "--ring",
            "prod",
            "--account",
            "admin@example.test",
            "--kit-root",
            str(tmp_path),
        ]
    ) == 0

    result = json.loads(
        capsys.readouterr().out.removeprefix(
            "DA_ENVIRONMENT_LOCATIONS_JSON:"
        )
    )
    evidence_path = (
        tmp_path / ".local" / "setup" / "environment-locations-prod.json"
    )
    assert result == {
        "tenantId": TENANT_ID,
        "ring": "prod",
        "selectionMode": "Region",
        "locations": [
            {
                "value": "unitedstates",
                "name": "United States",
                "isDefault": True,
                "isDisabled": False,
            },
            {
                "value": "europe",
                "name": "Europe",
                "isDefault": False,
                "isDisabled": True,
            },
            {
                "value": "unitedstatesfirstrelease",
                "name": "Preview (United States)",
                "isDefault": False,
                "isDisabled": False,
            },
        ],
        "macroRegions": [],
        "evidencePath": str(evidence_path.resolve()),
    }
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == {
        "tenantId": TENANT_ID,
        "ring": "prod",
        "response": raw_response,
    }


@pytest.mark.parametrize(
    ("selection_mode", "location", "argument", "request_field", "expected"),
    [
        (
            "Region",
            {"name": "unitedstates", "code": "NA"},
            "--location",
            "location",
            "unitedstates",
        ),
        (
            "Region",
            {"name": "unitedstatesfirstrelease", "code": "NA"},
            "--location",
            "location",
            "unitedstatesfirstrelease",
        ),
        (
            "Region",
            {"name": "europe", "code": "EMEA"},
            "--location",
            "location",
            "europe",
        ),
        (
            "Region",
            {"name": "future-service-location", "code": "FUT"},
            "--location",
            "location",
            "future-service-location",
        ),
        (
            "MacroRegion",
            {"macroRegionId": "NAM"},
            "--macro-region",
            "macroRegion",
            "NAM",
        ),
    ],
)
def test_listed_location_composes_with_create_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    selection_mode: str,
    location: dict[str, str],
    argument: str,
    request_field: str,
    expected: str,
) -> None:
    raw_response = {
        "locationSelectionMode": selection_mode,
        "collection": [location] if selection_mode == "Region" else [],
        "macroRegions": [location] if selection_mode == "MacroRegion" else [],
    }
    monkeypatch.setattr(
        setup_environment,
        "authenticate_selected_tenant",
        lambda *args, **kwargs: ("token", TENANT_ID),
    )
    monkeypatch.setattr(
        setup_environment,
        "list_provisioning_locations",
        lambda *args, **kwargs: raw_response,
    )
    monkeypatch.setattr(
        setup_environment,
        "authenticate_cached_account",
        lambda *args, **kwargs: ("token", TENANT_ID, "admin@example.test"),
    )
    requests: list[dict[str, Any]] = []

    def provision(*args: Any, **kwargs: Any):
        requests.append(kwargs["request_body"])
        return {
            "statusCode": 202,
            "requestId": "service-request",
            "response": None,
        }

    monkeypatch.setattr(setup_environment, "provision_environment", provision)

    assert setup_environment.main(
        ["list-locations", "--ring", "prod", "--kit-root", str(tmp_path)]
    ) == 0
    listed = json.loads(
        capsys.readouterr().out.removeprefix("DA_ENVIRONMENT_LOCATIONS_JSON:")
    )
    choices = listed["locations" if selection_mode == "Region" else "macroRegions"]

    assert setup_environment.main(
        [
            "create",
            "--ring",
            "prod",
            "--account",
            "admin@example.test",
            "--display-name",
            "ESS Development",
            "--environment-type",
            "Sandbox",
            argument,
            choices[0]["value"],
            "--client-request-id",
            REQUEST_ID,
            "--kit-root",
            str(tmp_path),
        ]
    ) == 0

    assert requests == [
        {
            "displayName": "ESS Development",
            "environmentSku": "Sandbox",
            request_field: expected,
        }
    ]


@pytest.mark.parametrize("name", [None, "", "   ", 42])
def test_list_locations_rejects_missing_request_name_and_keeps_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: Any,
) -> None:
    location = {"code": "NA", "displayName": "United States"}
    if name is not None:
        location["name"] = name
    raw_response = {
        "locationSelectionMode": "Region",
        "collection": [location],
        "macroRegions": [],
    }
    monkeypatch.setattr(
        setup_environment,
        "authenticate_selected_tenant",
        lambda *args, **kwargs: ("token", TENANT_ID),
    )
    monkeypatch.setattr(
        setup_environment,
        "list_provisioning_locations",
        lambda *args, **kwargs: raw_response,
    )

    assert setup_environment.main(
        ["list-locations", "--ring", "prod", "--kit-root", str(tmp_path)]
    ) == 1

    output = capsys.readouterr()
    assert "missing a valid request name" in output.err
    assert "DA_ENVIRONMENT_LOCATIONS_JSON:" not in output.out
    evidence = tmp_path / ".local" / "setup" / "environment-locations-prod.json"
    assert json.loads(evidence.read_text(encoding="utf-8"))["response"] == raw_response


def test_create_uses_cached_account_and_persists_service_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, Any] = {}

    def authenticate(*args: Any, **kwargs: Any):
        observed["auth"] = {"args": args, "kwargs": kwargs}
        return "token", TENANT_ID, "admin@example.test"

    def provision(*args: Any, **kwargs: Any):
        observed["provision"] = {"args": args, "kwargs": kwargs}
        return {
            "statusCode": 201,
            "requestId": "service-request",
            "operationLocation": None,
            "response": {
                "status": "Succeeded",
                "futureServiceField": {"preserved": True},
                "updatedEnvironment": {
                    "environmentId": ENVIRONMENT_ID,
                    "displayName": "ESS Development",
                },
            },
        }

    monkeypatch.setattr(
        setup_environment,
        "authenticate_cached_account",
        authenticate,
    )
    monkeypatch.setattr(
        setup_environment,
        "provision_environment",
        provision,
    )

    assert setup_environment.main(
        [
            "create",
            "--ring",
            "prod",
            "--account",
            "admin@example.test",
            "--display-name",
            "ESS Development",
            "--environment-type",
            "Sandbox",
            "--location",
            "unitedstates",
            "--client-request-id",
            REQUEST_ID,
            "--kit-root",
            str(tmp_path),
        ]
    ) == 0

    result = json.loads(
        capsys.readouterr().out.removeprefix(
            "DA_ENVIRONMENT_CREATE_JSON:"
        )
    )
    evidence_path = (
        tmp_path
        / ".local"
        / "setup"
        / "environment"
        / "create-requests"
        / f"{REQUEST_ID}.json"
    )
    assert result == {
        "tenantId": TENANT_ID,
        "ring": "prod",
        "account": "admin@example.test",
        "outcome": "created",
        "statusCode": 201,
        "requestId": "service-request",
        "operationLocation": None,
        "operationStatus": "Succeeded",
        "environment": {
            "id": ENVIRONMENT_ID,
            "name": "ESS Development",
        },
        "evidencePath": str(evidence_path.resolve()),
    }
    assert observed["provision"]["kwargs"]["request_body"] == {
        "displayName": "ESS Development",
        "environmentSku": "Sandbox",
        "location": "unitedstates",
    }
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["outcome"] == "created"
    assert evidence["response"]["futureServiceField"] == {"preserved": True}


def test_create_request_id_cannot_be_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_environment,
        "authenticate_cached_account",
        lambda *args, **kwargs: (
            "token",
            TENANT_ID,
            "admin@example.test",
        ),
    )
    calls = 0

    def provision(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        return {
            "statusCode": 202,
            "requestId": REQUEST_ID,
            "operationLocation": "https://example.test/operation",
            "response": None,
        }

    monkeypatch.setattr(
        setup_environment,
        "provision_environment",
        provision,
    )
    command = [
        "create",
        "--ring",
        "prod",
        "--account",
        "admin@example.test",
        "--display-name",
        "ESS Development",
        "--environment-type",
        "Sandbox",
        "--macro-region",
        "NAM",
        "--client-request-id",
        REQUEST_ID,
        "--kit-root",
        str(tmp_path),
    ]

    assert setup_environment.main(command) == 0
    capsys.readouterr()
    assert setup_environment.main(command) == 1
    assert calls == 1
    assert "already submitted" in capsys.readouterr().err


def test_create_rejects_invalid_request_id_before_writing_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert setup_environment.main(
        [
            "create",
            "--ring",
            "prod",
            "--account",
            "admin@example.test",
            "--display-name",
            "ESS Development",
            "--environment-type",
            "Sandbox",
            "--location",
            "unitedstates",
            "--client-request-id",
            "..\\not-a-guid",
            "--kit-root",
            str(tmp_path),
        ]
    ) == 1

    assert "Client request ID must be a GUID" in capsys.readouterr().err
    assert not (
        tmp_path
        / ".local"
        / "setup"
        / "environment"
        / "create-requests"
    ).exists()


def test_forget_account_targets_both_workspace_caches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, Any] = {}

    def forget(account: str, *, cache_path: Path, shared_cache_path: Path):
        observed["account"] = account
        observed["cache_path"] = cache_path
        observed["shared_cache_path"] = shared_cache_path
        return {"account": account, "status": "removed"}

    monkeypatch.setattr(
        setup_environment,
        "forget_cached_account",
        forget,
    )

    assert setup_environment.main(
        [
            "forget-account",
            "--account",
            "admin@example.test",
            "--kit-root",
            str(tmp_path),
        ]
    ) == 0
    assert observed == {
        "account": "admin@example.test",
        "cache_path": (
            tmp_path / ".local" / ".agentbuilder_token_cache.bin"
        ),
        "shared_cache_path": tmp_path / ".local" / ".token_cache.bin",
    }
    assert json.loads(
        capsys.readouterr().out.removeprefix(
            "DA_AGENTBUILDER_FORGET_ACCOUNT_JSON:"
        )
    ) == {
        "account": "admin@example.test",
        "status": "removed",
    }


def test_forget_account_reports_partial_cleanup_without_success_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    failure = PermissionError("shared cache is not writable")
    failure.add_note("AgentBuilder cache cleanup completed; shared cache cleanup failed.")

    def fail_cleanup(*args, **kwargs):
        raise failure

    monkeypatch.setattr(setup_environment, "forget_cached_account", fail_cleanup)
    assert setup_environment.main([
        "forget-account", "--account", "admin@example.test", "--kit-root", str(tmp_path),
    ]) == 1

    output = capsys.readouterr()
    assert "DA_AGENTBUILDER_FORGET_ACCOUNT_JSON:" not in output.out
    assert "PermissionError: shared cache is not writable" in output.err
    assert failure.__notes__[0] in output.err


def _role_token(**claims: Any) -> str:
    values = {
        "tid": TENANT_ID, "oid": ADMIN_ID, "upn": "admin@example.test",
        "aud": "https://service.powerapps.com", **claims,
    }
    payload = base64.urlsafe_b64encode(json.dumps(values).encode()).decode().rstrip("=")
    return f"header.{payload}.synthetic-signature"


@pytest.fixture
def role_authorization(monkeypatch: pytest.MonkeyPatch) -> str:
    token = _role_token()
    monkeypatch.setattr(
        setup_environment, "authenticate_cached_account",
        lambda *args, **kwargs: (token, TENANT_ID, "admin@example.test"),
    )
    monkeypatch.setattr(
        setup_environment, "authenticate_environment_roles",
        lambda *args, **kwargs: (token, "admin@example.test"),
    )
    return token


def _role_command(tmp_path: Path, command: str = "grant-maker") -> list[str]:
    arguments = [
        command, "--ring", "prod", "--tenant-id", TENANT_ID,
        "--account", "admin@example.test", "--kit-root", str(tmp_path),
    ]
    if command != "inspect-account":
        arguments.extend(["--environment-id", ENVIRONMENT_ID])
    if command == "grant-maker":
        arguments.extend([
            "--principal-id", PRINCIPAL_ID,
            "--principal-account", "maker@example.test",
            "--principal-tenant-id", TENANT_ID,
            "--client-request-id", REQUEST_ID,
        ])
    return arguments


def _role_assignment() -> dict[str, Any]:
    """User/role shape from the official PowerApps module's 2016-11-01 API."""
    return {"properties": {
        "roleDefinition": {"id": (
            "/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments/"
            f"{ENVIRONMENT_ID}/roleDefinitions/EnvironmentMaker"
        )},
        "principal": {"id": PRINCIPAL_ID, "type": "User", "tenantId": TENANT_ID},
        "futureAssignmentField": "preserved",
    }}


def _role_response(body: Any, status: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.headers["x-ms-request-id"] = "role-service-request"
    return response


def test_inspect_account_retains_authenticated_tenant_local_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], role_authorization: str,
) -> None:
    assert setup_environment.main(_role_command(tmp_path, "inspect-account")) == 0
    output = capsys.readouterr().out
    assert role_authorization not in output
    assert json.loads(output.removeprefix("DA_ENVIRONMENT_ACCOUNT_JSON:")) == {
        "account": "admin@example.test",
        "objectId": ADMIN_ID,
        "tenantId": TENANT_ID,
        "ring": "prod",
    }


@pytest.mark.parametrize("ring", ["prod", "preprod", "test"])
def test_role_operations_are_separate_and_preserve_complete_service_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    role_authorization: str,
    ring: str,
) -> None:
    assignment = _role_assignment()
    grant_body = {
        "add": [{"httpStatus": "Created", "roleAssignment": assignment}],
        "futureServiceField": {"preserved": True},
    }
    bodies = iter([{"value": []}, grant_body, {"value": [assignment]}])
    calls: list[dict[str, Any]] = []

    def request(token, requested_ring, **kwargs):
        assert token == role_authorization
        assert requested_ring == ring
        calls.append(kwargs)
        return _role_response(next(bodies))

    monkeypatch.setattr(setup_environment, "environment_role_request", request)
    for command, expected in (("list-roles", "read"), ("grant-maker", "created"), ("list-roles", "read")):
        arguments = _role_command(tmp_path, command)
        arguments[arguments.index("--ring") + 1] = ring
        assert setup_environment.main(arguments) == 0
        output = capsys.readouterr().out
        marker = "DA_ENVIRONMENT_MAKER_GRANT" if command == "grant-maker" else "DA_ENVIRONMENT_ROLES"
        result = json.loads(output.removeprefix(f"{marker}_JSON:"))
        assert result["outcome"] == expected
        assert role_authorization not in output
        evidence = json.loads(Path(result["evidencePath"]).read_text())
        assert evidence["response"] == result["response"]
        assert evidence["authenticatedIdentity"]["objectId"] == ADMIN_ID
        assert role_authorization not in json.dumps(evidence)
        if command == "grant-maker":
            assert result["response"] == grant_body
            assert evidence["principal"]["id"] == PRINCIPAL_ID
    assert len(calls) == 3
    assert [call["principal_id"] for call in calls] == [None, PRINCIPAL_ID, None]


@pytest.mark.parametrize(
    "invalid_identity",
    [
        {"tid": PRINCIPAL_ID}, {"oid": ""}, {"upn": "different@example.test"},
        {"aud": "https://api.powerplatform.com"},
    ],
)
def test_grant_rejects_invalid_actor_identity_before_any_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    invalid_identity: dict[str, str],
) -> None:
    monkeypatch.setattr(
        setup_environment, "authenticate_cached_account",
        lambda *args, **kwargs: (
            _role_token(**invalid_identity), TENANT_ID, "admin@example.test",
        ),
    )
    monkeypatch.setattr(
        setup_environment, "environment_role_request",
        lambda *args, **kwargs: pytest.fail("Unverified identity must not submit a request."),
    )
    assert setup_environment.main(_role_command(tmp_path)) == 1
    assert "ERROR:" in capsys.readouterr().err
    assert not (tmp_path / ".local" / "setup" / "environment" / "role-grants").exists()


@pytest.mark.parametrize(
    ("argument", "value", "error"),
    [
        ("--principal-tenant-id", PRINCIPAL_ID, "creation tenant"),
        ("--principal-account", " ", "sign-in name is required"),
    ],
)
def test_grant_rejects_invalid_recipient_before_authorization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    argument: str, value: str, error: str,
) -> None:
    arguments = _role_command(tmp_path)
    arguments[arguments.index(argument) + 1] = value
    monkeypatch.setattr(
        setup_environment, "authenticate_cached_account",
        lambda *args, **kwargs: pytest.fail("Invalid recipient must fail before authorization."),
    )
    assert setup_environment.main(arguments) == 1
    assert error in capsys.readouterr().err


def test_role_read_rejects_a_different_interactively_selected_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        setup_environment, "authenticate_environment_roles",
        lambda *args, **kwargs: (
            _role_token(upn="other@example.test"), "other@example.test",
        ),
    )
    monkeypatch.setattr(
        setup_environment, "environment_role_request",
        lambda *args, **kwargs: pytest.fail("A different account must not reach role inspection."),
    )
    assert setup_environment.main(_role_command(tmp_path, "list-roles")) == 1
    assert "selected a different account" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("command", "body", "outcome"),
    [
        ("grant-maker", {"add": [{"httpStatus": "Forbidden", "detail": "retained"}]}, "unconfirmed"),
        ("grant-maker", {"add": [{"httpStatus": "Created", "roleAssignment": {}}]}, "unconfirmed"),
        ("list-roles", {"unexpected": []}, "invalid-response"),
    ],
)
def test_role_http_success_does_not_mask_unconfirmed_or_unreadable_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    role_authorization: str, command: str, body: Any, outcome: str,
) -> None:
    monkeypatch.setattr(
        setup_environment, "environment_role_request",
        lambda *args, **kwargs: _role_response(body),
    )
    assert setup_environment.main(_role_command(tmp_path, command)) == 1
    result = json.loads(capsys.readouterr().out.split("_JSON:", 1)[1])
    assert result["outcome"] == outcome
    assert result["response"] == body
    assert json.loads(Path(result["evidencePath"]).read_text())["response"] == body


@pytest.mark.parametrize("mismatch", ["user", "tenant", "role-environment", "principal-type"])
def test_grant_acknowledgement_requires_the_exact_user_role_and_tenant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    role_authorization: str, mismatch: str,
) -> None:
    assignment = _role_assignment()
    properties = assignment["properties"]
    if mismatch == "user":
        properties["principal"]["id"] = ADMIN_ID
    elif mismatch == "tenant":
        properties["principal"]["tenantId"] = ADMIN_ID
    elif mismatch == "principal-type":
        properties["principal"]["type"] = "Group"
    else:
        properties["roleDefinition"]["id"] = properties["roleDefinition"]["id"].replace(
            ENVIRONMENT_ID, ADMIN_ID,
        )
    body = {"add": [{"httpStatus": "Created", "roleAssignment": assignment}]}
    monkeypatch.setattr(
        setup_environment, "environment_role_request",
        lambda *args, **kwargs: _role_response(body),
    )
    assert setup_environment.main(_role_command(tmp_path)) == 1
    result = json.loads(capsys.readouterr().out.split("_JSON:", 1)[1])
    assert result["outcome"] == "unconfirmed"
    assert result["response"] == body


def test_role_rejection_preserves_full_service_error_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    role_authorization: str,
) -> None:
    body = {"error": {"code": "Forbidden", "futureField": "preserved"}}
    response = _role_response(body, 403)

    def reject(*args, **kwargs):
        raise setup_environment.AgentBuilderHTTPError(
            "Environment role assignment", 403,
            error_code="Forbidden", request_id="role-service-request", response=response,
        )

    monkeypatch.setattr(setup_environment, "environment_role_request", reject)
    assert setup_environment.main(_role_command(tmp_path)) == 1
    output = capsys.readouterr()
    assert "DA_ENVIRONMENT_MAKER_GRANT_ERROR_RESPONSE_JSON:" in output.out
    assert "futureField" in output.out
    assert "HTTP 403" in output.err
    evidence = tmp_path / ".local" / "setup" / "environment" / "role-grants" / f"{REQUEST_ID}.json"
    assert json.loads(evidence.read_text())["response"] == body
    assert json.loads(evidence.read_text())["outcome"] == "service-rejected"


def test_role_response_is_visible_when_evidence_cannot_be_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    role_authorization: str,
) -> None:
    body = {"add": [{"httpStatus": "Created", "roleAssignment": _role_assignment()}]}
    monkeypatch.setattr(
        setup_environment, "environment_role_request",
        lambda *args, **kwargs: _role_response(body),
    )

    def fail_write(*args, **kwargs):
        raise PermissionError("synthetic evidence write failure")

    monkeypatch.setattr(setup_environment, "_write_json", fail_write)
    assert setup_environment.main(_role_command(tmp_path)) == 1
    output = capsys.readouterr()
    assert "PermissionError: synthetic evidence write failure" in output.err
    assert f"Role response JSON: {json.dumps(body)}" in output.err
    assert "DA_ENVIRONMENT_MAKER_GRANT_JSON:" not in output.out


@pytest.mark.parametrize("evidence_write_fails", [False, True])
def test_uncertain_role_grant_is_not_replayed_and_can_be_inspected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    role_authorization: str,
    evidence_write_fails: bool,
) -> None:
    calls = 0
    failure = requests.ReadTimeout("synthetic role-grant timeout")

    def request(*args, **kwargs):
        nonlocal calls
        calls += 1
        if kwargs["principal_id"] is not None:
            raise failure
        return _role_response({"value": []})

    write = setup_environment._write_json
    monkeypatch.setattr(setup_environment, "environment_role_request", request)
    if evidence_write_fails:
        def fail_write(*args, **kwargs):
            raise PermissionError("synthetic evidence write failure")
        monkeypatch.setattr(setup_environment, "_write_json", fail_write)
    assert setup_environment.main(_role_command(tmp_path)) == 1
    output = capsys.readouterr()
    assert "ReadTimeout: synthetic role-grant timeout" in output.err
    if evidence_write_fails:
        assert "evidence write failure" in output.err
    else:
        evidence = tmp_path / ".local" / "setup" / "environment" / "role-grants" / f"{REQUEST_ID}.json"
        assert json.loads(evidence.read_text())["outcome"] == "uncertain"
    assert setup_environment.main(_role_command(tmp_path)) == 1
    assert "already submitted" in capsys.readouterr().err
    assert calls == 1
    monkeypatch.setattr(setup_environment, "_write_json", write)
    assert setup_environment.main(_role_command(tmp_path, "list-roles")) == 0
    assert calls == 2
